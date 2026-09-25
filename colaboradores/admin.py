from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from .auth_logging import log_admin_auth_change, remote_addr_from_request
from .auth_admin_forms import (
    ConverterFuncionarioLocalForm, DirectoryFuncionarioChangeForm,
    LocalFuncionarioChangeForm, LocalFuncionarioCreationForm,
    VincularFuncionarioADForm,
)
from .models import CentroCusto, Departamento, Funcionario, Secao, UnidadeFabril
from .sincronizacao_erp import sincronizar


@admin.register(Funcionario)
class FuncionarioAdmin(UserAdmin):
    list_display = ("username", "nome", "auth_source", "grupos", "codigo_funcionario_erp", "centro_custo", "unidade_fabril", "ativo", "is_staff", "email")
    list_filter = ("ativo", "is_staff", "is_superuser", "centro_custo", "unidade_fabril", "departamento", "secao", "email")
    search_fields = ("username", "nome", "codigo_funcionario_erp", "email")
    ordering = ("nome",)
    # Acrescenta o botão "Sincronizar com o ERP" à listagem, via
    # object-tools-items (ver templates/admin/colaboradores/funcionario/).
    change_list_template = "admin/colaboradores/funcionario/change_list.html"
    change_form_template = "admin/colaboradores/funcionario/change_form.html"
    readonly_fields = ("auth_source", "directory_guid")
    filter_horizontal = ("groups",)
    add_form = LocalFuncionarioCreationForm
    form = LocalFuncionarioChangeForm

    @admin.display(description="Grupos")
    def grupos(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True))

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            previous = Funcionario.objects.get(pk=obj.pk)
            before = {
                "auth_source": previous.auth_source,
                "directory_guid": previous.directory_guid,
                "groups": tuple(previous.groups.order_by("name").values_list("name", flat=True)),
            }
        super().save_model(request, obj, form, change)
        request._auth_admin_snapshot = before

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        user = form.instance
        groups = tuple(user.groups.order_by("name").values_list("name", flat=True))
        actor = request.user.get_username()
        remote_addr = remote_addr_from_request(request)
        before = getattr(request, "_auth_admin_snapshot", None)

        if not change:
            log_admin_auth_change(
                event="account_created",
                actor=actor,
                target=user.username,
                remote_addr=remote_addr,
                source=user.auth_source,
                groups=", ".join(groups),
            )
        elif before and before["groups"] != groups:
            log_admin_auth_change(
                event="groups_changed",
                actor=actor,
                target=user.username,
                remote_addr=remote_addr,
                source=user.auth_source,
                groups=", ".join(groups),
            )

    # Estende os fieldsets padrão do UserAdmin com os campos do negócio.
    fieldsets = (
        (None, {"fields": ("username", "password", "auth_source", "directory_guid")}),
        ("Dados pessoais", {"fields": ("first_name", "last_name", "email")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    ) + (
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
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "password1", "password2", "groups", "is_active", "is_staff", "is_superuser")}),
    ) + (
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
            path("add-directory/", self.admin_site.admin_view(self.add_directory_view), name="colaboradores_funcionario_add_directory"),
            path("<path:object_id>/converter-directory/", self.admin_site.admin_view(self.converter_directory_view), name="colaboradores_funcionario_converter_directory"),
            path("<path:object_id>/converter-local/", self.admin_site.admin_view(self.converter_local_view), name="colaboradores_funcionario_converter_local"),
            path("<path:object_id>/religar-ad/", self.admin_site.admin_view(self.religar_ad_view), name="colaboradores_funcionario_religar_ad"),
            path(
                "sincronizar-erp/",
                self.admin_site.admin_view(self.sincronizar_erp_view),
                name="colaboradores_funcionario_sincronizar_erp",
            ),
        ]
        return urls_extras + super().get_urls()

    def get_fieldsets(self, request, obj=None):
        if obj is None and getattr(request, "directory_creation", False):
            return (
                (None, {"fields": ("username", "groups", "is_active", "is_staff", "is_superuser")}),
                *self.add_fieldsets[1:],
            )
        if obj is not None and obj.auth_source == Funcionario.AuthSource.DIRECTORY:
            return tuple(
                (title, {**options, "fields": tuple(field for field in options["fields"] if field != "password")})
                for title, options in self.fieldsets
            )
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None and getattr(request, "directory_creation", False):
            kwargs["form"] = VincularFuncionarioADForm
        elif obj is not None:
            kwargs["form"] = (
                DirectoryFuncionarioChangeForm
                if obj.auth_source == Funcionario.AuthSource.DIRECTORY
                else LocalFuncionarioChangeForm
            )
        return super().get_form(request, obj, **kwargs)

    def user_change_password(self, request, id, form_url=""):
        user = self.get_object(request, id)
        if user and user.auth_source == Funcionario.AuthSource.DIRECTORY:
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    def add_directory_view(self, request):
        request.directory_creation = True
        return self.add_view(request, extra_context={"title": "Novo vínculo AD", "directory_creation": True})

    def _transition_user(self, request, object_id, source):
        user = get_object_or_404(Funcionario, pk=object_id)
        if not self.has_change_permission(request, user):
            raise PermissionDenied
        if user.auth_source != source:
            raise PermissionDenied
        return user

    def _transition_context(self, request, user, title, form=None):
        return {
            **self.admin_site.each_context(request), "title": title,
            "opts": self.model._meta, "original": user, "form": form,
        }

    def converter_directory_view(self, request, object_id):
        user = self._transition_user(request, object_id, Funcionario.AuthSource.LOCAL)
        if user.is_superuser:
            raise PermissionDenied
        if request.method == "POST" and any(key.lower().startswith("password") for key in request.POST):
            return HttpResponseBadRequest("Senha não pode ser enviada para vínculo AD.")
        if request.method == "POST" and request.POST.get("confirmar") == "on":
            previous_source = user.auth_source
            user.auth_source = Funcionario.AuthSource.DIRECTORY
            user.directory_guid = None
            user.set_unusable_password()
            user.save(update_fields=["auth_source", "password", "directory_guid"])
            self.log_change(request, user, "Origem alterada para Active Directory")
            log_admin_auth_change(
                event="authentication_source_changed",
                actor=request.user.get_username(),
                target=user.username,
                remote_addr=remote_addr_from_request(request),
                **{"from": previous_source, "to": user.auth_source},
            )
            return redirect(reverse("admin:colaboradores_funcionario_change", args=[user.pk]))
        return render(request, "admin/colaboradores/funcionario/transition_auth.html", self._transition_context(request, user, "Converter para vínculo AD"))

    def converter_local_view(self, request, object_id):
        user = self._transition_user(request, object_id, Funcionario.AuthSource.DIRECTORY)
        form = ConverterFuncionarioLocalForm(request.POST or None, funcionario=user)
        if request.method == "POST" and form.is_valid():
            form.save()
            self.log_change(request, user, "Origem alterada para local")
            log_admin_auth_change(
                event="authentication_source_changed",
                actor=request.user.get_username(),
                target=user.username,
                remote_addr=remote_addr_from_request(request),
                **{"from": Funcionario.AuthSource.DIRECTORY, "to": Funcionario.AuthSource.LOCAL},
            )
            return redirect(reverse("admin:colaboradores_funcionario_change", args=[user.pk]))
        return render(request, "admin/colaboradores/funcionario/transition_auth.html", self._transition_context(request, user, "Converter para usuário local", form))

    def religar_ad_view(self, request, object_id):
        user = self._transition_user(request, object_id, Funcionario.AuthSource.DIRECTORY)
        if request.method == "POST" and request.POST.get("confirmar") == "on":
            old_guid = user.directory_guid
            user.directory_guid = None
            user.save(update_fields=["directory_guid"])
            self.log_change(request, user, "GUID do Active Directory limpo para religação")
            log_admin_auth_change(
                event="directory_guid_relinked",
                actor=request.user.get_username(),
                target=user.username,
                remote_addr=remote_addr_from_request(request),
                source=Funcionario.AuthSource.DIRECTORY,
                registered_guid=old_guid,
            )
            return redirect(reverse("admin:colaboradores_funcionario_change", args=[user.pk]))
        return render(request, "admin/colaboradores/funcionario/transition_auth.html", self._transition_context(request, user, "Religar identidade AD"))

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
