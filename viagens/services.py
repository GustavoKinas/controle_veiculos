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
from django.core.exceptions import ValidationError

from .models import Fechamento, FechamentoRateio, ReservaViagem, Viagem

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
    if km_inicial is None or km_final is None:
        return                                              # campo faltando: erro de field já foi acusado

    if km_final <= km_inicial:                              # regra 1
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
        piso_quilometragem = viagens_do_veiculo.filter(data__lte=data).aggregate(
            km=Max("km_final")
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
        if teto_quilometragem is not None and km_final > teto_quilometragem:
            erros.setdefault("km_final", []).append(
                f"KM final ({km_final}) invade um lançamento posterior "
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
    maior_km = veiculo.viagens.aggregate(km=Max("km_final"))["km"]
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
    evita N+1 — a agenda renderiza funcionário e veículo de cada card.
    """
    return (
        ReservaViagem.objects.filter(data__range=(data_inicio, data_fim))
        .exclude(status=ReservaViagem.Status.CANCELADA)
        .select_related("funcionario", "veiculo")
        .order_by("hora_inicio", "id")
    )


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


def viagens_em_aberto(data_inicio: date, data_fim: date):
    """Viagens no período que ainda NÃO entraram em nenhum fechamento."""
    return Viagem.objects.filter(
        fechamento__isnull=True,
        data__gte=data_inicio,
        data__lte=data_fim,
    )


def calcular_rateio(data_inicio: date, data_fim: date) -> dict:
    """
    Prévia (somente leitura) do rateio do período: total de km, quantidade de
    viagens e a soma/percentual por Centro de Custo.
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
    viagens = list(
        Viagem.objects.select_for_update()
        .filter(fechamento__isnull=True, data__gte=data_inicio, data__lte=data_fim)
    )

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




