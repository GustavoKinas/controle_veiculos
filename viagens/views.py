from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from .exports import exportar_fechamento_excel
from .forms import FechamentoFiltroForm, LancamentoViagemForm
from .models import Fechamento, Viagem
from .services import (
    calcular_rateio,
    confirmar_fechamento,
    montar_calendario,
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
