from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CentroCusto, Funcionario, UnidadeFabril


@admin.register(Funcionario)
class FuncionarioAdmin(UserAdmin):
    list_display = ("username", "nome", "centro_custo", "unidade_fabril", "ativo", "is_staff","email")
    list_filter = ("ativo", "is_staff", "is_superuser", "centro_custo", "unidade_fabril","email")
    search_fields = ("username", "nome", "email")
    ordering = ("nome",)

    # Estende os fieldsets padrão do UserAdmin com os campos do negócio.
    fieldsets = UserAdmin.fieldsets + (
        (
            "Dados do colaborador",
            {"fields": ("nome", "unidade_fabril", "centro_custo", "ativo")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Dados do colaborador",
            {"fields": ("nome", "unidade_fabril", "centro_custo", "ativo")},
        ),
    )


@admin.register(CentroCusto)
class CentroCustoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao")
    search_fields = ("codigo", "descricao")


@admin.register(UnidadeFabril)
class UnidadeFabrilAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)
