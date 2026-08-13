from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from django.core.exceptions import ValidationError

from .exports import exportar_fechamento_excel
from .forms import (
    FechamentoFiltroForm,
    LancamentoDeReservaForm,
    LancamentoViagemForm,
    RegistrarChegadaForm,
)
from .models import Fechamento, ReservaViagem, Viagem
from .services import (
    ReservaIndisponivel,
    ViagemNaoEstaEmAndamento,
    calcular_rateio,
    confirmar_fechamento,
    lancar_viagem_da_reserva,
    montar_calendario,
    registrar_chegada,
    reservas_no_periodo,
)


def _data_do_parametro(valor: str | None, padrao: date) -> date:
    """
    Converte `?dia=AAAA-MM-DD` em data, caindo no padrão se vier ausente ou
    malformado. Parâmetro de URL é entrada do usuário: nunca pode virar 500.
    """
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return padrao


def _mes_do_parametro(ano: str | None, mes: str | None, padrao: date) -> date:
    """Primeiro dia do mês pedido em `?ano=&mes=`, ou o mês do padrão."""
    try:
        return date(int(ano), int(mes), 1)
    except (TypeError, ValueError):
        return padrao.replace(day=1)


def _aplicar_erros_do_modelo(form, erro: ValidationError) -> None:
    """
    Leva um `ValidationError` vindo do modelo para o formulário.

    `form.add_error(None, erro)` levanta `ValueError` quando o dicionário de
    erros cita um campo que o formulário não possui — e nos formulários de
    reserva isso é a regra, não a exceção: `data`, `veiculo` e `funcionario`
    vêm da reserva e **de propósito** não existem como campos editáveis.

    Erro endereçado a campo que existe no form vai para o campo; o resto vira
    erro geral, exibido no topo. Assim uma regra nova no modelo nunca derruba
    a tela com um 500.
    """
    if not hasattr(erro, "error_dict"):
        form.add_error(None, erro)
        return

    for campo, mensagens in erro.error_dict.items():
        destino = campo if campo in form.fields else None
        form.add_error(destino, mensagens)


class AgendaView(LoginRequiredMixin, View):
    """
    Agenda de pré-cadastros: o dia selecionado em destaque (a fila de trabalho
    do operador) e a grade do mês abaixo (panorama).

    Somente leitura nesta fase — o botão "Lançar KM" de cada card é habilitado
    na fase 3, quando existir a tela de conclusão da reserva.

    Navegação por htmx com `hx-select`, o mesmo padrão já usado na paginação
    de colaboradores e no histórico de fechamentos: o servidor devolve a
    página inteira e o htmx troca só o pedaço.
    """

    template_name = "agenda.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        hoje = timezone.localdate()
        dia_selecionado = _data_do_parametro(request.GET.get("dia"), hoje)
        # Sem ?ano/&mes explícitos, o mês exibido é o do dia selecionado.
        mes_exibido = _mes_do_parametro(
            request.GET.get("ano"), request.GET.get("mes"), dia_selecionado
        )

        calendario = montar_calendario(mes_exibido.year, mes_exibido.month)

        contexto = {
            **calendario,
            "hoje": hoje,
            "dia_selecionado": dia_selecionado,
            "reservas_do_dia": reservas_no_periodo(dia_selecionado, dia_selecionado),
            "mes_exibido": mes_exibido,
            # Somar/subtrair 1 no mês vira caso especial em dezembro e janeiro;
            # andar pelos dias resolve sem condicional.
            "mes_anterior": mes_exibido - timedelta(days=1),
            "mes_seguinte": (mes_exibido + timedelta(days=32)).replace(day=1),
        }
        return render(request, self.template_name, contexto)


class LancarReservaView(LoginRequiredMixin, View):
    """
    Conclusão de uma reserva (fase 3), atendendo os dois fluxos da portaria.

    GET  → formulário com os dados da reserva em texto fixo.
    POST → cria a `Viagem` e marca a reserva como lançada.

    A view não constrói a viagem: isso é responsabilidade de
    `services.lancar_viagem_da_reserva`, que faz o trabalho dentro de uma
    transação. Aqui só traduzimos exceção em mensagem de tela.
    """

    template_name = "lancar_reserva.html"

    def _reserva_pendente(self, pk: int) -> ReservaViagem:
        """
        404 para reserva inexistente **ou já resolvida**.

        O filtro por status no próprio lookup é o que impede o duplo
        lançamento pela segunda aba: ela não encontra mais a reserva.
        """
        return get_object_or_404(
            ReservaViagem.objects.select_related("funcionario", "veiculo"),
            pk=pk,
            status=ReservaViagem.Status.PENDENTE,
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        reserva = self._reserva_pendente(pk)
        return render(
            request,
            self.template_name,
            {"reserva": reserva, "form": LancamentoDeReservaForm(reserva=reserva)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        reserva = self._reserva_pendente(pk)
        form = LancamentoDeReservaForm(request.POST, reserva=reserva)

        if form.is_valid():
            try:
                viagem = lancar_viagem_da_reserva(
                    reserva_pk=reserva.pk,
                    km_inicial=form.cleaned_data["km_inicial"],
                    km_final=form.cleaned_data.get("km_final"),
                    funcionario=form.cleaned_data.get("funcionario"),
                    usuario=request.user,
                )
            except ReservaIndisponivel as erro:
                # Estado mudou entre o GET e o POST — não é erro de campo.
                messages.error(request, str(erro))
                return redirect(f"{reverse('agenda')}?dia={reserva.data:%Y-%m-%d}")
            except ValidationError as erro:
                # Regras do modelo (piso, teto, data futura, veículo na rua).
                _aplicar_erros_do_modelo(form, erro)
            else:
                if viagem.em_andamento:
                    messages.success(
                        request,
                        f"Saída registrada: {viagem.funcionario} com "
                        f"{viagem.veiculo.placa} em KM {viagem.km_inicial}. "
                        "Registre a chegada quando o veículo retornar.",
                    )
                else:
                    messages.success(
                        request,
                        f"Viagem de {viagem.funcionario} lançada "
                        f"({viagem.km_percorrida} km).",
                    )
                return redirect(f"{reverse('agenda')}?dia={viagem.data:%Y-%m-%d}")

        return render(request, self.template_name, {"reserva": reserva, "form": form})


class RegistrarChegadaView(LoginRequiredMixin, View):
    """Segunda etapa do Fluxo A: informar o KM de retorno."""

    template_name = "registrar_chegada.html"

    def _viagem_aberta(self, pk: int) -> Viagem:
        # `km_final__isnull=True` no lookup: viagem já concluída dá 404 em vez
        # de permitir reescrever a quilometragem.
        return get_object_or_404(
            Viagem.objects.select_related("funcionario", "veiculo"),
            pk=pk,
            km_final__isnull=True,
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        viagem = self._viagem_aberta(pk)
        return render(
            request,
            self.template_name,
            {"viagem": viagem, "form": RegistrarChegadaForm()},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        viagem = self._viagem_aberta(pk)
        form = RegistrarChegadaForm(request.POST)

        if form.is_valid():
            try:
                viagem = registrar_chegada(
                    viagem_pk=viagem.pk, km_final=form.cleaned_data["km_final"]
                )
            except ViagemNaoEstaEmAndamento as erro:
                messages.error(request, str(erro))
                return redirect(f"{reverse('agenda')}?dia={viagem.data:%Y-%m-%d}")
            except ValidationError as erro:
                # Mesma armadilha: um erro de piso cai em `km_inicial`, que
                # não é campo deste formulário (só o km de chegada é).
                _aplicar_erros_do_modelo(form, erro)
            else:
                messages.success(
                    request,
                    f"Chegada registrada: {viagem.km_percorrida} km percorridos "
                    f"por {viagem.funcionario}.",
                )
                return redirect(f"{reverse('agenda')}?dia={viagem.data:%Y-%m-%d}")

        return render(request, self.template_name, {"viagem": viagem, "form": form})


class LancarViagemView(LoginRequiredMixin, View):
    """Tela do operador (portaria) para lançar as viagens dos colaboradores."""

    template_name = "lancar_viagem.html"

    def _context(self, form=None):
        return {
            "form": form or LancamentoViagemForm(),
            "ultimas_viagens": (
                Viagem.objects.select_related("funcionario", "centro_custo", "veiculo")
                .order_by("-criada_em")[:15]
            ),
        }

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, self.template_name, self._context())

    def post(self, request: HttpRequest) -> HttpResponse:
        form = LancamentoViagemForm(request.POST)

        if form.is_valid():
            viagem = form.save(commit=False)
            viagem.lancada_por = request.user
            # centro_custo e km_percorrida são preenchidos no Viagem.save().
            viagem.save()
            messages.success(
                request,
                f"Viagem de {viagem.funcionario} em {viagem.data:%d/%m/%Y} "
                f"lançada ({viagem.km_percorrida} km).",
            )
            return redirect("lancar_viagem")

        messages.error(request, "Não foi possível lançar a viagem. Verifique os campos.")
        return render(request, self.template_name, self._context(form))


class FechamentoView(LoginRequiredMixin, View):
    """
    Tela de fechamento e rateio.

    - GET sem datas: mostra apenas o filtro de período.
    - GET com data_inicio e data_fim: mostra a prévia do rateio (somente leitura).
    - GET com ?concluido=<id>: mostra o aviso do fechamento recém-criado com o
      link de exportação em Excel.
    - POST (acao=confirmar): fecha o período de forma atômica.
    """

    template_name = "fechamento.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        tem_filtro = "data_inicio" in request.GET and "data_fim" in request.GET
        form = FechamentoFiltroForm(request.GET if tem_filtro else None)
        contexto = {"form": form, "rateio": None, "fechamento_concluido": None}

        concluido_id = request.GET.get("concluido")
        if concluido_id and concluido_id.isdigit():
            contexto["fechamento_concluido"] = Fechamento.objects.filter(
                pk=concluido_id
            ).first()

        if tem_filtro and form.is_valid():
            data_inicio = form.cleaned_data["data_inicio"]
            data_fim = form.cleaned_data["data_fim"]
            contexto["rateio"] = calcular_rateio(data_inicio, data_fim)
            contexto["data_inicio"] = data_inicio
            contexto["data_fim"] = data_fim

        return render(request, self.template_name, contexto)

    def post(self, request: HttpRequest) -> HttpResponse:
        form = FechamentoFiltroForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Período inválido para o fechamento.")
            return render(request, self.template_name, {"form": form, "rateio": None})

        data_inicio = form.cleaned_data["data_inicio"]
        data_fim = form.cleaned_data["data_fim"]

        fechamento = confirmar_fechamento(data_inicio, data_fim, usuario=request.user)

        if fechamento is None:
            messages.warning(
                request,
                "Nenhuma viagem em aberto foi encontrada nesse período.",
            )
            return redirect("fechamento")

        messages.success(
            request,
            f"Fechamento confirmado: {fechamento.total_km} km processados em "
            f"{fechamento.viagens.count()} viagem(ns).",
        )
        return redirect(f"{reverse('fechamento')}?concluido={fechamento.pk}")


class FechamentoExportarView(LoginRequiredMixin, View):
    """Download do detalhamento (resumo + viagens) de um fechamento em Excel."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        fechamento = get_object_or_404(Fechamento, pk=pk)
        return exportar_fechamento_excel(fechamento)


class HistoricoFechamentosView(LoginRequiredMixin, ListView):
    model = Fechamento
    template_name = "historico_fechamentos.html"
    context_object_name = "fechamentos"
    paginate_by = 20

    def get_queryset(self):
        return (
            Fechamento.objects.prefetch_related("rateios__centro_custo")
            .select_related("criado_por")
            .order_by("-criado_em")
        )
