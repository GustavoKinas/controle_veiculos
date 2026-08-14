"""
Regras de negócio do fechamento e rateio de custos por Centro de Custo.

Mantidas fora das views para ficarem reutilizáveis (preview na tela, confirmação
via POST, futuros comandos/relatórios) e testáveis isoladamente.
"""

import calendar
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from datetime import date

from django.db import transaction
from django.db.models import Sum, Max, Min, QuerySet
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError

from colaboradores.models import Funcionario

from .models import Fechamento, FechamentoRateio, ReservaViagem, Veiculo, Viagem


class ReservaIndisponivel(Exception):
    """
    A reserva não pode ser lançada: já virou viagem, foi cancelada ou outro
    operador a pegou primeiro.

    Exceção própria (e não `ValidationError`) para separar "o formulário está
    errado" de "o estado do sistema mudou debaixo dos seus pés" — são erros
    diferentes e merecem mensagens diferentes na tela.
    """


class ViagemNaoEstaEmAndamento(Exception):
    """Tentativa de registrar chegada numa viagem que já foi concluída."""

CEM = Decimal("100")
DUAS_CASAS = Decimal("0.01")


def _percentual(parte: int, total: int) -> Decimal:
    if not total:
        return Decimal("0.00")
    return (Decimal(parte) / Decimal(total) * CEM).quantize(
        DUAS_CASAS, rounding=ROUND_HALF_UP
    )

def validar_quilometragem(veiculo, data, km_inicial, km_final, viagem_id=None):
    """
    Valida a quilometragem de uma viagem contra o histórico do veículo.

    Regras:
      1. `km_final` deve ser maior que `km_inicial`;
      2. `km_inicial` não pode ser menor que a maior KM já registrada para o
         veículo até a data (o hodômetro nunca anda para trás);
      3. `km_final` não pode invadir a faixa de um lançamento posterior.

    Os erros são levantados já endereçados ao campo correspondente, para que
    tanto o ModelForm quanto o admin os exibam no lugar certo.
    """
    erros = {}
    if km_inicial is None:
        return                                              # campo faltando: erro de field já foi acusado

    # `km_final is None` = viagem em andamento. As regras que dependem do fim
    # ficam suspensas até a chegada ser registrada; as que dependem só do
    # início continuam valendo desde a saída.
    if km_final is not None and km_final <= km_inicial:      # regra 1
        erros.setdefault("km_final", []).append(
            "A quilometragem final deve ser maior que a inicial."
        )

    # Piso e teto dependem do veículo e da data. Sem eles vale só a regra 1 —
    # mas o que já foi acumulado precisa sair mesmo assim, por isso a função
    # tem um único ponto de saída (o `raise` lá embaixo).
    if veiculo is not None and data is not None:
        viagens_do_veiculo = Viagem.objects.filter(veiculo=veiculo)
        if viagem_id is not None:                               # edição: não comparar consigo mesma
            viagens_do_veiculo = viagens_do_veiculo.exclude(pk=viagem_id)

        # Piso (regra 2): maior KM já registrada para o veículo até esta data.
        #
        # Coalesce porque uma viagem em andamento tem km_final NULO e o
        # MAX() do SQL ignora nulos: sem isso, o carro que saiu com 105.000 e
        # não voltou não contaria como piso, e a viagem seguinte poderia ser
        # lançada com quilometragem menor.
        piso_quilometragem = viagens_do_veiculo.filter(data__lte=data).aggregate(
            km=Max(Coalesce("km_final", "km_inicial"))
        )["km"]
        if piso_quilometragem is None and not viagens_do_veiculo.exists():
            # Veículo ainda sem viagens: o piso é o hodômetro cadastrado. Se já
            # existem viagens (todas posteriores a esta data), `km_atual` é o maior
            # KM global e não serve de piso — quem limita aqui é o teto (regra 3).
            piso_quilometragem = veiculo.km_atual

        if piso_quilometragem is not None and km_inicial < piso_quilometragem:
            erros.setdefault("km_inicial", []).append(
                f"KM inicial ({km_inicial}) não pode ser menor que "
                f"{piso_quilometragem} (maior KM já registrada para "
                f"{veiculo} até esta data)."
            )

        # Teto (regra 3): não invadir a faixa de um lançamento posterior existente.
        teto_quilometragem = viagens_do_veiculo.filter(data__gt=data).aggregate(
            km=Min("km_inicial")
        )["km"]
        if teto_quilometragem is not None:
            if km_final is not None and km_final > teto_quilometragem:
                erros.setdefault("km_final", []).append(
                    f"KM final ({km_final}) invade um lançamento posterior "
                    f"(que inicia em {teto_quilometragem})."
                )
            # Viagem em andamento: o fim é desconhecido, mas o início já não
            # pode ultrapassar o teto.
            elif km_final is None and km_inicial > teto_quilometragem:
                erros.setdefault("km_inicial", []).append(
                    f"KM inicial ({km_inicial}) invade um lançamento posterior "
                    f"(que inicia em {teto_quilometragem})."
                )

    if erros:
        raise ValidationError(erros)

def atualizar_km_veiculo(veiculo):
    """
    Recalcula o hodômetro do veículo a partir das viagens existentes.

    Ao contrário de um UPDATE condicional (que só sobe o km), o recompute
    também ABAIXA o valor — necessário quando uma viagem é editada para menos
    ou excluída. Chamado no `save()` e no `post_delete` de `Viagem`.
    """
    if veiculo is None:
        return
    # Coalesce pelo mesmo motivo do piso: a viagem em andamento não tem
    # km_final, mas o hodômetro já avançou até o km_inicial dela.
    maior_km = veiculo.viagens.aggregate(km=Max(Coalesce("km_final", "km_inicial")))["km"]
    if maior_km is None:
        # Sem viagens: preserva o hodômetro informado no cadastro do veículo.
        return
    if veiculo.km_atual != maior_km:
        veiculo.km_atual = maior_km
        veiculo.save(update_fields=["km_atual"])

# ---------------------------------------------------------------------------
# Agenda / pré-cadastro de viagens
# ---------------------------------------------------------------------------

def reservas_no_periodo(data_inicio: date, data_fim: date) -> QuerySet[ReservaViagem]:
    """
    Reservas visíveis na agenda entre duas datas (limites inclusivos).

    Canceladas ficam de fora: são ruído para o operador. O `select_related`
    evita N+1 — a agenda renderiza funcionário, veículo e, desde a fase 3, o
    estado da viagem vinculada (para decidir entre "Lançar KM" e "Registrar
    chegada") em cada card.
    """
    return (
        ReservaViagem.objects.filter(data__range=(data_inicio, data_fim))
        .exclude(status=ReservaViagem.Status.CANCELADA)
        .select_related("funcionario", "veiculo", "viagem")
        .order_by("hora_inicio", "id")
    )


@transaction.atomic
def sincronizar_reservas(
    *,
    eventos: list[dict],
    caixas_consultadas: set[str],
    data_inicio: date,
    data_fim: date,
) -> dict:
    """
    Aplica no banco os eventos já normalizados pela borda da integração.

    Idempotente: a identidade de uma reserva é o `id_externo` (o id do evento
    no Outlook), nunca a combinação veículo+solicitante+período — uma reunião
    remarcada mantém o mesmo id e muda o horário; com chave natural o sync
    entenderia "sumiu uma, nasceu outra" e duplicaria o registro.

    Quatro queries, independentemente do volume: veículos, funcionários,
    reservas existentes e as ausentes da janela.

    Regras de estado:

    | Estado atual | No Outlook          | Ação                       |
    |--------------|---------------------|----------------------------|
    | (nova)       | presente            | cria PENDENTE              |
    | PENDENTE     | alterada            | atualiza                   |
    | PENDENTE     | cancelada ou sumiu  | CANCELADA                  |
    | CANCELADA    | reapareceu          | volta para PENDENTE        |
    | LANCADA      | qualquer coisa      | **nada** — o fato aconteceu|

    `caixas_consultadas` é o que torna a varredura de ausentes segura: uma
    caixa cuja chamada falhou volta sem eventos, e tratar isso como "sumiu
    tudo" cancelaria reservas legítimas. Só o que foi efetivamente consultado
    entra na varredura.
    """
    resumo = {
        "criadas": 0,
        "atualizadas": 0,
        "canceladas": 0,
        "reabertas": 0,
        "ignoradas_sem_veiculo": 0,
        "intocadas_lancadas": 0,
    }
    if not caixas_consultadas:
        return resumo

    # 1. Veículos por caixa de recurso — 1 query.
    veiculos = {
        veiculo.email_recurso.lower(): veiculo
        for veiculo in Veiculo.objects.exclude(email_recurso="")
    }

    # 2. Colaboradores pelos e-mails que apareceram no lote — 1 query.
    #    Tudo em minúsculo dos dois lados: o `IN` do Postgres diferencia caixa.
    emails = {e["solicitante_email"] for e in eventos if e["solicitante_email"]}
    funcionarios = {
        funcionario.email.lower(): funcionario
        for funcionario in Funcionario.objects.filter(email__in=emails)
    }

    # 3. Reservas já conhecidas, pela chave de idempotência — 1 query.
    ids_do_lote = [e["id_externo"] for e in eventos]
    existentes = {
        reserva.id_externo: reserva
        for reserva in ReservaViagem.objects.filter(
            origem=ReservaViagem.Origem.OUTLOOK, id_externo__in=ids_do_lote
        )
    }

    ids_vistos: set[str] = set()

    for evento in eventos:
        veiculo = veiculos.get(evento["email_recurso"])
        if veiculo is None:
            # Caixa de recurso sem veículo cadastrado: não é erro, é uma sala
            # que ainda não virou veículo no sistema.
            resumo["ignoradas_sem_veiculo"] += 1
            continue

        ids_vistos.add(evento["id_externo"])
        reserva = existentes.get(evento["id_externo"])

        if reserva is not None and reserva.status == ReservaViagem.Status.LANCADA:
            # A viagem já aconteceu e tem quilometragem. O passado não se
            # reescreve, aconteça o que acontecer no Outlook.
            resumo["intocadas_lancadas"] += 1
            continue

        if evento["cancelado"]:
            if reserva is not None and reserva.status != ReservaViagem.Status.CANCELADA:
                reserva.status = ReservaViagem.Status.CANCELADA
                reserva.save(update_fields=["status", "atualizada_em"])
                resumo["canceladas"] += 1
            continue

        campos = {
            "funcionario": funcionarios.get(evento["solicitante_email"]),
            "solicitante_nome": evento["solicitante_nome"],
            "solicitante_email": evento["solicitante_email"],
            "veiculo": veiculo,
            "data": evento["data"],
            "hora_inicio": evento["hora_inicio"],
            "hora_fim": evento["hora_fim"],
        }

        if reserva is None:
            ReservaViagem.objects.create(
                origem=ReservaViagem.Origem.OUTLOOK,
                id_externo=evento["id_externo"],
                status=ReservaViagem.Status.PENDENTE,
                **campos,
            )
            resumo["criadas"] += 1
            continue

        reabrindo = reserva.status == ReservaViagem.Status.CANCELADA
        for campo, valor in campos.items():
            setattr(reserva, campo, valor)
        reserva.status = ReservaViagem.Status.PENDENTE
        reserva.save()
        resumo["reabertas" if reabrindo else "atualizadas"] += 1

    # 4. Ausentes: pendentes na janela, de caixas consultadas com sucesso, que
    #    não vieram no payload. Evento EXCLUÍDO no Outlook não chega marcado —
    #    ele simplesmente some, e esta varredura é a única forma de detectá-lo.
    canceladas = (
        ReservaViagem.objects.filter(
            origem=ReservaViagem.Origem.OUTLOOK,
            status=ReservaViagem.Status.PENDENTE,
            data__gte=data_inicio,
            data__lte=data_fim,
            veiculo__email_recurso__in=caixas_consultadas,
        )
        .exclude(id_externo__in=ids_vistos)
        .update(status=ReservaViagem.Status.CANCELADA)
    )
    resumo["canceladas"] += canceladas

    return resumo


def montar_calendario(ano: int, mes: int) -> dict:
    """
    Monta a grade mensal da agenda em **uma única query**.

    Devolve as semanas já no formato que o template consome — pares
    `(dia, reservas_do_dia)` —, porque o template do Django não sabe acessar
    dicionário por chave dinâmica. Uma query por dia seriam 35+ queries.

    A grade inclui os dias vizinhos que completam a primeira e a última
    semana; o template os exibe esmaecidos (`dia.month != mes`).
    """
    semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(ano, mes)
    primeiro_dia, ultimo_dia = semanas[0][0], semanas[-1][-1]

    agrupadas: dict[date, list[ReservaViagem]] = defaultdict(list)
    for reserva in reservas_no_periodo(primeiro_dia, ultimo_dia):
        agrupadas[reserva.data].append(reserva)

    return {
        "semanas": [
            [(dia, agrupadas.get(dia, [])) for dia in semana] for semana in semanas
        ],
        "primeiro_dia": primeiro_dia,
        "ultimo_dia": ultimo_dia,
        "total_no_mes": sum(
            len(reservas)
            for dia, reservas in agrupadas.items()
            if dia.month == mes and dia.year == ano
        ),
    }


def viagem_em_andamento_do_veiculo(veiculo, ignorar_viagem_id=None) -> Viagem | None:
    """
    A viagem aberta do veículo, se houver.

    Um carro não pode estar em duas viagens ao mesmo tempo: enquanto não
    registrarem a chegada, ele não sai de novo.
    """
    consulta = Viagem.objects.filter(veiculo=veiculo, km_final__isnull=True)
    if ignorar_viagem_id is not None:
        consulta = consulta.exclude(pk=ignorar_viagem_id)
    return consulta.select_related("funcionario").first()


@transaction.atomic
def lancar_viagem_da_reserva(
    *,
    reserva_pk: int,
    km_inicial: int,
    km_final: int | None = None,
    funcionario=None,
    usuario=None,
) -> Viagem:
    """
    Converte uma reserva PENDENTE em `Viagem` e marca a reserva como LANCADA.

    Atende os dois fluxos da portaria com o mesmo caminho de código:

    - **Fluxo A** (duas etapas): `km_final=None` → viagem em andamento;
    - **Fluxo B** (retrospectivo): `km_final` informado → viagem concluída.

    Parâmetros por palavra-chave (`*`) de propósito: `km_inicial` e `km_final`
    são dois inteiros seguidos, e trocá-los de posição numa chamada posicional
    passaria despercebido.

    `funcionario` só é usado quando a reserva veio do Outlook sem colaborador
    identificado — nesse caso quem informa é o operador, na tela.

    Levanta `ReservaIndisponivel` se a reserva já foi lançada/cancelada, e
    `ValidationError` se a quilometragem violar as regras do hodômetro.
    """
    # select_for_update trava a linha até o fim da transação: dois operadores
    # clicando no mesmo card ao mesmo tempo — ou o mesmo operador com duas
    # abas — não criam duas viagens. O segundo espera e encontra o status já
    # alterado, caindo no ReservaIndisponivel.
    # `of=("self",)` trava SÓ a linha da reserva. Sem isso o Postgres recusa a
    # consulta: `funcionario` é FK opcional, o select_related gera LEFT OUTER
    # JOIN e "FOR UPDATE não pode ser aplicado ao lado nulável de uma junção
    # externa". Travar o funcionário também não faria sentido algum.
    reserva = (
        ReservaViagem.objects.select_for_update(of=("self",))
        .select_related("funcionario", "veiculo")
        .filter(pk=reserva_pk, status=ReservaViagem.Status.PENDENTE)
        .first()
    )
    if reserva is None:
        raise ReservaIndisponivel(
            "Esta reserva já foi lançada ou cancelada por outra pessoa."
        )

    # O colaborador vem SEMPRE da reserva quando ela o tem. O parâmetro só
    # entra em cena no caso não identificado — nunca para sobrescrever.
    funcionario_da_viagem = reserva.funcionario or funcionario
    if funcionario_da_viagem is None:
        raise ValidationError(
            {"funcionario": "Informe o colaborador responsável pela viagem."}
        )

    aberta = viagem_em_andamento_do_veiculo(reserva.veiculo)
    if aberta is not None:
        raise ValidationError(
            {
                "km_inicial": (
                    f"{reserva.veiculo} está em viagem desde "
                    f"{aberta.data:%d/%m/%Y} (KM {aberta.km_inicial}). "
                    "Registre a chegada antes de lançar uma nova saída."
                )
            }
        )

    if funcionario_da_viagem.centro_custo_id is None:
        # Sem centro de custo não há para onde ratear o combustível. Melhor
        # barrar aqui, com nome e sobrenome, do que deixar o full_clean()
        # devolver um "este campo não pode ser nulo" sobre `centro_custo`.
        raise ValidationError(
            {
                "funcionario": (
                    f"{funcionario_da_viagem} não tem centro de custo definido. "
                    "Ajuste o cadastro do colaborador antes de lançar a viagem."
                )
            }
        )

    viagem = Viagem(
        funcionario=funcionario_da_viagem,
        veiculo=reserva.veiculo,      # da reserva, jamais do POST
        data=reserva.data,
        km_inicial=km_inicial,
        km_final=km_final,
        lancada_por=usuario,
    )
    viagem.congelar_centro_custo()    # antes do full_clean, ver o método
    # Sem ModelForm não existe `_post_clean()`, e `save()` não valida:
    # o full_clean() aqui é o que mantém piso, teto e data futura valendo
    # também neste caminho.
    viagem.full_clean()
    viagem.save()

    reserva.viagem = viagem
    reserva.status = ReservaViagem.Status.LANCADA
    reserva.save(update_fields=["viagem", "status", "atualizada_em"])

    return viagem


@transaction.atomic
def registrar_chegada(*, viagem_pk: int, km_final: int) -> Viagem:
    """
    Fecha uma viagem em andamento com a quilometragem de chegada (Fluxo A).

    A trava `km_final__isnull=True` no próprio filtro impede que uma viagem já
    concluída seja alterada por aqui — inclusive numa segunda aba aberta.
    """
    viagem = (
        Viagem.objects.select_for_update(of=("self",))
        .select_related("veiculo", "funcionario")
        .filter(pk=viagem_pk, km_final__isnull=True)
        .first()
    )
    if viagem is None:
        raise ViagemNaoEstaEmAndamento(
            "Esta viagem já foi concluída ou não existe."
        )

    viagem.km_final = km_final
    viagem.full_clean()
    viagem.save()      # recalcula km_percorrida e o hodômetro do veículo
    return viagem


def viagens_em_aberto(data_inicio: date, data_fim: date) -> QuerySet[Viagem]:
    """
    Viagens do período elegíveis para fechamento.

    Dois filtros, e o segundo é crítico:

    - `fechamento__isnull=True` — ainda não entrou em nenhum fechamento;
    - `km_final__isnull=False` — **viagem em andamento fica de fora**. Ela
      ainda não tem quilometragem, e o fechamento é irreversível: se fosse
      consumida agora, seria marcada como fechada com 0 km e os quilômetros
      reais nunca entrariam em rateio nenhum.

    Esta é a única definição de "viagem fechável" no sistema. `calcular_rateio`
    e `confirmar_fechamento` usam esta função justamente para que a prévia e a
    confirmação nunca divirjam.
    """
    return Viagem.objects.filter(
        fechamento__isnull=True,
        km_final__isnull=False,
        data__gte=data_inicio,
        data__lte=data_fim,
    )


def contar_viagens_em_andamento(data_inicio: date, data_fim: date) -> int:
    """
    Viagens do período que ainda estão na rua (sem `km_final`).

    Elas ficam de fora do fechamento por construção — ver `viagens_em_aberto`.
    O número existe para **avisar o operador antes de confirmar**: fechar o
    período agora deixa essas viagens sem fechamento nenhum, e a ação é
    irreversível.
    """
    return Viagem.objects.filter(
        fechamento__isnull=True,
        km_final__isnull=True,
        data__gte=data_inicio,
        data__lte=data_fim,
    ).count()

def contar_reservas_viagem_pendentes(data_inicio: date, data_fim: date) -> int:
    """
    Reservas do período que nunca viraram viagem.

    Pendente é o estado de quem não foi resolvido: reserva **lançada** já
    virou viagem e entra no rateio; **cancelada** foi descartada de propósito.
    Sobra a pendente — alguém reservou o carro e ninguém lançou a
    quilometragem.

    Ao contrário da viagem em andamento, uma reserva pendente **não carrega
    quilometragem nenhuma** e por isso não tem como distorcer o rateio. O
    número existe como sinal de trabalho inacabado: fechar o período com
    reservas pendentes é legítimo, mas provavelmente significa que a portaria
    esqueceu de lançar alguma coisa.

    `data__range` é inclusivo nas duas pontas — mesmo intervalo de
    `contar_viagens_em_andamento`, escrito de outro jeito.

    ⚠️ Uma reserva pendente antiga continua sendo contada em toda prévia que
    inclua a data dela, mesmo depois do período já ter sido fechado. É o
    comportamento correto (ela *continua* pendente), mas significa que o aviso
    só some quando alguém lança ou cancela a reserva.
    """
    return ReservaViagem.objects.filter(
        status=ReservaViagem.Status.PENDENTE,
        data__range=(data_inicio, data_fim),
    ).count()


def calcular_rateio(data_inicio: date, data_fim: date) -> dict:
    """
    Prévia (somente leitura) do rateio do período: total de km, quantidade de
    viagens, a soma/percentual por Centro de Custo e **duas contagens de
    pendência** — viagens ainda na rua e reservas que nunca viraram viagem.

    As duas pendências não afetam o rateio: viagem em andamento não tem
    quilometragem e reserva pendente muito menos. Elas existem para o operador
    saber o que fica para trás antes de confirmar uma ação irreversível.
    """
    viagens = viagens_em_aberto(data_inicio, data_fim)

    total_km = viagens.aggregate(total=Sum("km_percorrida"))["total"] or 0

    agregado = (
        viagens.values(
            "centro_custo",
            "centro_custo__codigo",
            "centro_custo__descricao",
        )
        .annotate(km=Sum("km_percorrida"))
        .order_by("-km")
    )

    linhas = [
        {
            "centro_custo_id": row["centro_custo"],
            "codigo": row["centro_custo__codigo"],
            "descricao": row["centro_custo__descricao"],
            "km": row["km"] or 0,
            "percentual": _percentual(row["km"] or 0, total_km),
        }
        for row in agregado
    ]

    return {
        "total_km": total_km,
        "quantidade_viagens": viagens.count(),
        # Os dois contadores de pendência do período. Nenhum dos dois entra na
        # conta do rateio — existem para o operador decidir se é hora de
        # fechar, já que o fechamento é irreversível.
        "quantidade_em_andamento": contar_viagens_em_andamento(data_inicio, data_fim),
        "quantidade_reservas_pendentes": contar_reservas_viagem_pendentes(
            data_inicio, data_fim
        ),
        "linhas": linhas,
    }


@transaction.atomic
def confirmar_fechamento(data_inicio: date, data_fim: date, usuario=None):
    """
    Fecha o período de forma atômica e à prova de concorrência:

    1. Trava (select_for_update) as viagens em aberto do período.
    2. Calcula o total e o rateio por Centro de Custo sobre o conjunto travado.
    3. Cria o Fechamento e os snapshots de rateio.
    4. Marca todas as viagens com o fechamento (nunca mais entram em outro).

    Retorna o Fechamento criado, ou None se não havia viagens em aberto.
    """
    # Reutiliza `viagens_em_aberto` em vez de repetir o filtro: antes, a mesma
    # regra estava escrita em dois lugares, e bastava alterar um deles para a
    # prévia mostrar um conjunto e o fechamento consumir outro.
    viagens = list(viagens_em_aberto(data_inicio, data_fim).select_for_update())

    if not viagens:
        return None

    total_km = sum(viagem.km_percorrida for viagem in viagens)

    km_por_cc: dict[int, int] = defaultdict(int)
    for viagem in viagens:
        km_por_cc[viagem.centro_custo_id] += viagem.km_percorrida

    fechamento = Fechamento.objects.create(
        data_inicio=data_inicio,
        data_fim=data_fim,
        total_km=total_km,
        criado_por=usuario,
    )

    FechamentoRateio.objects.bulk_create(
        [
            FechamentoRateio(
                fechamento=fechamento,
                centro_custo_id=centro_custo_id,
                km_percorrida=km,
                percentual=_percentual(km, total_km),
            )
            for centro_custo_id, km in km_por_cc.items()
        ]
    )

    Viagem.objects.filter(id__in=[viagem.id for viagem in viagens]).update(fechamento=fechamento)

    return fechamento




