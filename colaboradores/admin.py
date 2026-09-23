from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import path

from .models import CentroCusto, Departamento, Funcionario, Secao, UnidadeFabril
from .sincronizacao_erp import sincronizar


@admin.register(Funcionario)
class FuncionarioAdmin(UserAdmin):
    list_display = ("username", "nome", "codigo_funcionario_erp", "centro_custo", "unidade_fabril", "ativo", "is_staff", "email")
    list_filter = ("ativo", "is_staff", "is_superuser", "centro_custo", "unidade_fabril", "departamento", "secao", "email")
    search_fields = ("username", "nome", "codigo_funcionario_erp", "email")
    ordering = ("nome",)
    # Acrescenta o botão "Sincronizar com o ERP" à listagem, via
    # object-tools-items (ver templates/admin/colaboradores/funcionario/).
    change_list_template = "admin/colaboradores/funcionario/change_list.html"

    # Estende os fieldsets padrão do UserAdmin com os campos do negócio.
    fieldsets = UserAdmin.fieldsets + (
        (
            "Dados do colaborador",
            {
                "fields": (
                    "nome",
                    "codigo_funcionario_erp",
                    "unidade_fabril",
                    "centro_custo",
                    "departamento",
                    "secao",
                    "ativo",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Dados do colaborador",
            {
                "fields": (
                    "nome",
                    "codigo_funcionario_erp",
                    "unidade_fabril",
                    "centro_custo",
                    "departamento",
                    "secao",
                    "ativo",
                )
            },
        ),
    )

    def get_urls(self):
        urls_extras = [
            path(
                "sincronizar-erp/",
                self.admin_site.admin_view(self.sincronizar_erp_view),
                name="colaboradores_funcionario_sincronizar_erp",
            ),
        ]
        return urls_extras + super().get_urls()

    def sincronizar_erp_view(self, request):
        """
        Roda as duas operações do mês corrente para as três empresas.

        `self.admin_site.admin_view()` já garante `is_staff` (e a trava dupla
        do `ControleVeiculosAdminSite` recusa quem é de um perfil
        operacional). A checagem de superusuário aqui é extra e explícita:
        disparar uma sincronização grava no banco de produção, e um `is_staff`
        comum não deveria bastar para isso.

        GET mostra a confirmação; só o POST executa — evitar que um GET
        (prefetch de navegador, link clicado sem querer) dispare uma
        sincronização de verdade.
        """
        if not request.user.is_superuser:
            raise PermissionDenied

        resultado = None
        if request.method == "POST":
            resultado = sincronizar()

        return render(
            request,
            "admin/colaboradores/funcionario/sincronizar_erp.html",
            {
                **self.admin_site.each_context(request),
                "title": "Sincronizar funcionários com o ERP",
                "opts": self.model._meta,
                "resultado": resultado,
            },
        )


@admin.register(CentroCusto)
class CentroCustoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao")
    search_fields = ("codigo", "descricao")


@admin.register(UnidadeFabril)
class UnidadeFabrilAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo_empresa_erp")
    search_fields = ("nome",)


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ("descricao",)
    search_fields = ("descricao",)


@admin.register(Secao)
class SecaoAdmin(admin.ModelAdmin):
    list_display = ("descricao", "departamento")
    list_filter = ("departamento",)
    search_fields = ("descricao", "departamento__descricao")
