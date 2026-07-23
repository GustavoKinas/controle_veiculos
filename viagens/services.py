"""
Regras de negócio do fechamento e rateio de custos por Centro de Custo.

Mantidas fora das views para ficarem reutilizáveis (preview na tela, confirmação
via POST, futuros comandos/relatórios) e testáveis isoladamente.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from datetime import date

from django.db import transaction
from django.db.models import Sum

from .models import Fechamento, FechamentoRateio, Viagem

CEM = Decimal("100")
DUAS_CASAS = Decimal("0.01")


def _percentual(parte: int, total: int) -> Decimal:
    if not total:
        return Decimal("0.00")
    return (Decimal(parte) / Decimal(total) * CEM).quantize(
        DUAS_CASAS, rounding=ROUND_HALF_UP
    )


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

    total_km = sum(v.km_percorrida for v in viagens)

    km_por_cc: dict[int, int] = defaultdict(int)
    for v in viagens:
        km_por_cc[v.centro_custo_id] += v.km_percorrida

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

    Viagem.objects.filter(id__in=[v.id for v in viagens]).update(fechamento=fechamento)

    return fechamento
