from django.contrib import admin

from .models import Fechamento, FechamentoRateio, Viagem


class FechamentoRateioInline(admin.TabularInline):
    model = FechamentoRateio
    extra = 0
    can_delete = False
    readonly_fields = ("centro_custo", "km_percorrida", "percentual")


@admin.register(Viagem)
class ViagemAdmin(admin.ModelAdmin):
    list_display = (
        "data",
        "funcionario",
        "centro_custo",
        "km_inicial",
        "km_final",
        "km_percorrida",
        "fechamento",
    )
    list_filter = ("fechamento", "centro_custo", "data")
    search_fields = ("funcionario__nome", "funcionario__username")
    date_hierarchy = "data"
    readonly_fields = ("km_percorrida", "centro_custo", "criada_em", "lancada_por")


@admin.register(Fechamento)
class FechamentoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "total_km", "criado_por", "criado_em")
    inlines = [FechamentoRateioInline]
    readonly_fields = ("total_km", "criado_por", "criado_em")
    date_hierarchy = "criado_em"
