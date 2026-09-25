import io
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from colaboradores.models import Funcionario
from colaboradores.permissoes import GRUPO_PORTARIA, criar_usuario_de_perfil


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}, MIDDLEWARE=tuple(
    middleware for middleware in settings.MIDDLEWARE if "whitenoise" not in middleware.lower()
))
class DirectoryFuncionarioFormTests(TestCase):
    def setUp(self):
        self.grupo = Group.objects.create(name="Portaria teste")
        self.admin_user = Funcionario.objects.create_superuser(
            username="admin.test", password="segredo-admin", auth_source=Funcionario.AuthSource.LOCAL
        )
        self.client.force_login(self.admin_user)

    def test_formulario_directory_nao_exibe_ou_aceita_senha(self):
        from colaboradores.auth_admin_forms import DirectoryFuncionarioCreationForm

        form = DirectoryFuncionarioCreationForm()
        self.assertNotIn("password", form.fields)
        self.assertNotIn("password1", form.fields)
        self.assertNotIn("password2", form.fields)
        self.assertIn("groups", form.fields)
        self.assertNotIn("user_permissions", form.fields)
        form = DirectoryFuncionarioCreationForm(data={
            "username": "ana.silva", "nome": "Ana Silva",
            "password1": "tentativa", "password2": "tentativa",
        })
        self.assertFalse(form.is_valid())

    def test_criacao_directory_persiste_grupo_e_senha_inutilizavel(self):
        from colaboradores.auth_admin_forms import DirectoryFuncionarioCreationForm

        form = DirectoryFuncionarioCreationForm(data={
            "username": "ana.silva", "nome": "Ana Silva", "groups": [self.grupo.pk]
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.all()), [self.grupo])

    def test_criacao_local_exige_senha_e_persiste_grupo(self):
        from colaboradores.auth_admin_forms import LocalFuncionarioCreationForm

        data = {"username": "local", "nome": "Local", "groups": [self.grupo.pk]}
        self.assertFalse(LocalFuncionarioCreationForm(data=data).is_valid())
        form = LocalFuncionarioCreationForm(data={
            **data, "password1": "senha-forte-123", "password2": "senha-forte-123"
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-forte-123"))
        self.assertEqual(list(user.groups.all()), [self.grupo])

    def test_vinculo_preserva_grafia_e_rejeita_username_local_igual_sem_caixa(self):
        from colaboradores.auth_admin_forms import VincularFuncionarioADForm

        Funcionario.objects.create_user(username="Ana.Silva", auth_source=Funcionario.AuthSource.LOCAL)
        form = VincularFuncionarioADForm(data={"username": " ana.silva ", "nome": "Ana"})
        self.assertFalse(form.is_valid())
        form = VincularFuncionarioADForm(data={"username": " Joao.Silva ", "nome": "João"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().username, "Joao.Silva")

    def test_conversoes_exigem_senha_local_nova_e_preservam_grupos(self):
        from colaboradores.auth_admin_forms import ConverterFuncionarioLocalForm

        user = Funcionario.objects.create_user(
            username="pessoa", password="senha-antiga", auth_source=Funcionario.AuthSource.LOCAL
        )
        user.groups.add(self.grupo)
        url = reverse("admin:colaboradores_funcionario_converter_directory", args=[user.pk])
        response = self.client.post(url, {"confirmar": "on"})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertFalse(user.has_usable_password())
        self.assertIsNone(user.directory_guid)
        self.assertEqual(list(user.groups.all()), [self.grupo])

        self.assertFalse(ConverterFuncionarioLocalForm(data={}).is_valid())
        url = reverse("admin:colaboradores_funcionario_converter_local", args=[user.pk])
        response = self.client.post(url, {"password1": "senha-nova-123", "password2": "senha-nova-123"})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-nova-123"))
        self.assertIsNone(user.directory_guid)
        self.assertEqual(list(user.groups.all()), [self.grupo])

    def test_admin_directory_sem_controle_de_senha_e_religacao_exige_post(self):
        import uuid

        user = Funcionario.objects.create_user(
            username="ad.user", auth_source=Funcionario.AuthSource.DIRECTORY,
            directory_guid=uuid.uuid4(),
        )
        user.set_unusable_password()
        user.save()
        change = self.client.get(reverse("admin:colaboradores_funcionario_change", args=[user.pk]))
        self.assertEqual(change.status_code, 200)
        self.assertNotContains(change, "name=\"password\"")
        self.assertNotContains(change, "/password/")
        self.assertContains(change, "groups")
        self.assertNotContains(change, "user_permissions")
        self.assertEqual(self.client.get(reverse("admin:auth_user_password_change", args=[user.pk])).status_code, 403)
        url = reverse("admin:colaboradores_funcionario_religar_ad", args=[user.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.directory_guid)
        self.assertEqual(self.client.post(url, {"confirmar": "on"}).status_code, 302)
        user.refresh_from_db()
        self.assertIsNone(user.directory_guid)

    def test_rotas_de_criacao_separam_local_e_directory(self):
        local_url = reverse("admin:colaboradores_funcionario_add")
        directory_url = reverse("admin:colaboradores_funcionario_add_directory")
        self.assertContains(self.client.get(local_url), 'name="password1"')
        directory_page = self.client.get(directory_url)
        self.assertEqual(directory_page.status_code, 200)
        self.assertNotContains(directory_page, 'name="password1"')
        self.assertContains(directory_page, 'name="groups"')

        response = self.client.post(directory_url, {
            "username": "diretorio", "nome": "Diretório", "groups": [self.grupo.pk],
            "is_active": "on", "ativo": "on",
        })
        self.assertEqual(response.status_code, 302)
        user = Funcionario.objects.get(username="diretorio")
        self.assertEqual(user.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.all()), [self.grupo])

        response = self.client.post(local_url, {
            "username": "local2", "nome": "Local 2", "groups": [self.grupo.pk],
            "password1": "senha-forte-123", "password2": "senha-forte-123",
            "is_active": "on", "ativo": "on",
        })
        self.assertEqual(response.status_code, 302)
        user = Funcionario.objects.get(username="local2")
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-forte-123"))

    def test_edicao_directory_salva_grupo_e_recusa_senha_extra(self):
        user = Funcionario.objects.create_user(username="ad.edit", auth_source=Funcionario.AuthSource.DIRECTORY)
        user.set_unusable_password()
        user.save()
        url = reverse("admin:colaboradores_funcionario_change", args=[user.pk])
        payload = {"username": user.username, "nome": "AD Edit", "groups": [self.grupo.pk], "is_active": "on", "ativo": "on", "date_joined_0": user.date_joined.strftime("%Y-%m-%d"), "date_joined_1": user.date_joined.strftime("%H:%M:%S"), "_save": "Salvar"}
        response = self.client.post(url, {**payload, "password": "injetada"})
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.groups.count(), 0)
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response.context.get("adminform"), "form", None).errors if response.context else None)
        user.refresh_from_db()
        self.assertEqual(list(user.groups.all()), [self.grupo])

    def test_conversao_directory_recusa_senha_enviada(self):
        user = Funcionario.objects.create_user(username="local3", password="antiga", auth_source=Funcionario.AuthSource.LOCAL)
        url = reverse("admin:colaboradores_funcionario_converter_directory", args=[user.pk])
        response = self.client.post(url, {"confirmar": "on", "password": "indevida"})
        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("antiga"))

    def test_superusuario_nao_pode_ser_directory(self):
        from colaboradores.auth_admin_forms import DirectoryFuncionarioCreationForm

        form = DirectoryFuncionarioCreationForm(data={
            "username": "admin.ad", "nome": "Admin AD", "is_superuser": "on"
        })
        self.assertFalse(form.is_valid())
        url = reverse("admin:colaboradores_funcionario_converter_directory", args=[self.admin_user.pk])
        self.assertEqual(self.client.post(url, {"confirmar": "on"}).status_code, 403)

    def test_create_superuser_sem_origem_cria_conta_local(self):
        user = Funcionario.objects.create_superuser(username="novo.admin", password="senha-admin")
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-admin"))

    def test_comando_createsuperuser_cria_conta_local(self):
        with patch.dict("os.environ", {"DJANGO_SUPERUSER_PASSWORD": "senha-cli"}):
            call_command("createsuperuser", interactive=False, username="cli.admin", stdout=io.StringIO())
        user = Funcionario.objects.get(username="cli.admin")
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-cli"))

    def test_criar_usuario_de_perfil_cria_local_e_recusa_directory_existente(self):
        user, created = criar_usuario_de_perfil(
            username="operador", senha="senha-local", nome="Operador", grupo=GRUPO_PORTARIA
        )
        self.assertTrue(created)
        self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
        self.assertTrue(user.check_password("senha-local"))

        directory = Funcionario.objects.create_user(
            username="operador.ad",
            auth_source=Funcionario.AuthSource.DIRECTORY,
        )
        before_password = directory.password
        with self.assertRaises(ValueError):
            criar_usuario_de_perfil(
                username="operador.ad", senha="senha-nova", nome="Outro", grupo=GRUPO_PORTARIA
            )
        directory.refresh_from_db()
        self.assertEqual(directory.password, before_password)
        self.assertEqual(directory.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertEqual(directory.groups.count(), 0)

    def test_criar_usuario_de_perfil_recusa_colisao_de_caixa_sem_alterar_conta(self):
        directory = Funcionario.objects.create_user(
            username="Ana.Silva",
            auth_source=Funcionario.AuthSource.DIRECTORY,
        )
        before_password = directory.password
        with self.assertRaises(ValueError):
            criar_usuario_de_perfil(
                username="ana.silva", senha="senha-nova", nome="Outra", grupo=GRUPO_PORTARIA
            )
        directory.refresh_from_db()
        self.assertEqual(directory.username, "Ana.Silva")
        self.assertEqual(directory.password, before_password)
        self.assertEqual(directory.groups.count(), 0)
        self.assertFalse(Funcionario.objects.filter(username="ana.silva").exists())

    def test_formularios_local_e_edicao_recusam_username_igual_sem_caixa(self):
        from colaboradores.auth_admin_forms import (
            DirectoryFuncionarioChangeForm, LocalFuncionarioChangeForm,
            LocalFuncionarioCreationForm,
        )

        existing = Funcionario.objects.create_user(
            username="Ana.Silva", auth_source=Funcionario.AuthSource.LOCAL
        )
        local = LocalFuncionarioCreationForm(data={
            "username": "ana.silva", "nome": "Outra", "password1": "senha-forte-123",
            "password2": "senha-forte-123",
        })
        self.assertFalse(local.is_valid())
        self.assertIn("username", local.errors)

        target_local = Funcionario.objects.create_user(
            username="bia", password="senha", auth_source=Funcionario.AuthSource.LOCAL
        )
        local_change = LocalFuncionarioChangeForm(
            data={"username": "ana.silva"}, instance=target_local
        )
        self.assertFalse(local_change.is_valid())
        self.assertIn("username", local_change.errors)

        target_directory = Funcionario.objects.create_user(
            username="carla", auth_source=Funcionario.AuthSource.DIRECTORY
        )
        directory_change = DirectoryFuncionarioChangeForm(
            data={"username": "ana.silva"}, instance=target_directory
        )
        self.assertFalse(directory_change.is_valid())
        self.assertIn("username", directory_change.errors)

        same_user = LocalFuncionarioChangeForm(
            data={"username": existing.username}, instance=existing
        )
        self.assertNotIn("username", same_user.errors)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}, MIDDLEWARE=tuple(
    middleware for middleware in settings.MIDDLEWARE if "whitenoise" not in middleware.lower()
))
class AuthAdminAuditTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="Auditoria grupo")
        self.admin_user = Funcionario.objects.create_superuser(
            username="auditoria.admin", password="senha-admin", auth_source=Funcionario.AuthSource.LOCAL
        )
        self.client.force_login(self.admin_user)

    def test_conversao_de_origem_registra_ator_alvo_e_endereco(self):
        user = Funcionario.objects.create_user(
            username="transicao.local", password="senha-local",
            auth_source=Funcionario.AuthSource.LOCAL,
        )
        url = reverse("admin:colaboradores_funcionario_converter_directory", args=[user.pk])

        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            response = self.client.post(url, {"confirmar": "on"}, REMOTE_ADDR="192.0.2.20")

        self.assertEqual(response.status_code, 302)
        log_text = "\n".join(captured.output)
        self.assertIn("event=authentication_source_changed", log_text)
        self.assertIn("actor=auditoria.admin", log_text)
        self.assertIn("target=transicao.local", log_text)
        self.assertIn("from=LOCAL", log_text)
        self.assertIn("to=DIRECTORY", log_text)
        self.assertIn("remote_addr=192.0.2.20", log_text)
        self.assertNotIn("senha-local", log_text)

    def test_criacao_directory_registra_origem_e_grupo_selecionado(self):
        url = reverse("admin:colaboradores_funcionario_add_directory")
        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            response = self.client.post(url, {
                "username": "nova.directory", "nome": "Nova Directory",
                "groups": [self.group.pk], "is_active": "on", "ativo": "on",
            }, REMOTE_ADDR="192.0.2.23")

        self.assertEqual(response.status_code, 302)
        log_text = "\n".join(captured.output)
        self.assertIn("event=account_created", log_text)
        self.assertIn("source=DIRECTORY", log_text)
        self.assertIn("groups=Auditoria grupo", log_text)
        self.assertNotIn("password", log_text.lower())

    def test_alteracao_de_grupo_registra_grupos_efetivos_sem_credenciais(self):
        user = Funcionario.objects.create_user(username="grupo.directory")
        user.set_unusable_password()
        user.save()
        url = reverse("admin:colaboradores_funcionario_change", args=[user.pk])
        payload = {
            "username": user.username,
            "nome": "Grupo Directory",
            "groups": [self.group.pk],
            "is_active": "on",
            "ativo": "on",
            "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
            "_save": "Salvar",
        }

        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            response = self.client.post(url, payload, REMOTE_ADDR="192.0.2.21")

        self.assertEqual(response.status_code, 302)
        log_text = "\n".join(captured.output)
        self.assertIn("event=groups_changed", log_text)
        self.assertIn("actor=auditoria.admin", log_text)
        self.assertIn("target=grupo.directory", log_text)
        self.assertIn("groups=Auditoria grupo", log_text)
        self.assertNotIn("password", log_text.lower())

    def test_religacao_registra_guid_anterior_sem_detalhe_ldap(self):
        import uuid

        user = Funcionario.objects.create_user(
            username="religar.directory",
            directory_guid=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        )
        user.set_unusable_password()
        user.save()
        url = reverse("admin:colaboradores_funcionario_religar_ad", args=[user.pk])

        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            response = self.client.post(url, {"confirmar": "on"}, REMOTE_ADDR="192.0.2.22")

        self.assertEqual(response.status_code, 302)
        log_text = "\n".join(captured.output)
        self.assertIn("event=directory_guid_relinked", log_text)
        self.assertIn("registered_guid=12345678-1234-5678-1234-567812345678", log_text)
        self.assertIn("actor=auditoria.admin", log_text)
        self.assertNotIn("CN=", log_text)
