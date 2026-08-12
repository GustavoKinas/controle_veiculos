from django.contrib import admin

from .models import Fechamento, FechamentoRateio, ReservaViagem, Viagem, Veiculo


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
        "veiculo"
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

@admin.register(Veiculo)
class VeiculoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "placa", "modelo", "marca", "km_atual", "ativo")
    list_filter = ("ativo", "marca")
    search_fields = ("placa", "modelo", "marca", "email_recurso")


@admin.register(ReservaViagem)
class ReservaViagemAdmin(admin.ModelAdmin):
    """Cadastro manual de reservas enquanto o sync com o Outlook não existe."""

    list_display = (
        "data",
        "hora_inicio",
        "descricao_solicitante",
        "veiculo",
        "status",
        "origem",
        "viagem",
    )
    list_filter = ("status", "origem", "veiculo")
    search_fields = ("solicitante_nome", "funcionario__nome", "destino", "id_externo")
    date_hierarchy = "data"
    autocomplete_fields = ("veiculo",)
    # Preenchidos pelo fluxo de lançamento (fase 3), nunca à mão.
    readonly_fields = ("viagem", "criada_em", "atualizada_em")

