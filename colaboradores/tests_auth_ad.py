import uuid
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.test import override_settings

from colaboradores.models import Funcionario


class FuncionarioAuthFieldsTests(TestCase):
    def test_novo_funcionario_tem_origem_directory(self):
        user = Funcionario.objects.create_user(username="ana.silva")

        self.assertEqual(user.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertIsNone(user.directory_guid)
        self.assertFalse(user.has_usable_password())

    def test_manager_recusa_senha_em_conta_directory(self):
        with self.assertRaisesRegex(ValueError, "usuários do Active Directory"):
            Funcionario.objects.create_user(username="ana.silva", password="local")

        with self.assertRaisesRegex(ValueError, "usuários do Active Directory"):
            Funcionario.objects.create_user(username="vazia", password="")

        with self.assertRaisesRegex(ValueError, "usuários do Active Directory"):
            Funcionario.objects.create_user(
                username="bia.silva", password="local",
                auth_source=Funcionario.AuthSource.DIRECTORY,
            )

    def test_save_torna_inutilizavel_senha_direta_em_conta_directory(self):
        user = Funcionario(username="ana.silva")
        user.save()
        user.set_password("nao-persistir")
        user.nome = "Ana Silva"
        user.save(update_fields={"nome"})

        user.refresh_from_db()
        self.assertEqual(user.auth_source, Funcionario.AuthSource.DIRECTORY)
        self.assertFalse(user.has_usable_password())

    def test_guid_ad_nao_pode_ser_repetido(self):
        guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        Funcionario.objects.create_user(username="ana.silva", directory_guid=guid)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Funcionario.objects.create_user(username="bia.silva", directory_guid=guid)


class DirectoryClientTests(TestCase):
    def _client(self):
        from colaboradores.directory import DirectoryClient

        return DirectoryClient(
            uri="ldaps://dc.example.test:636",
            base_dn="DC=example,DC=test",
            bind_user="svc-app@example.test",
            bind_password="service-secret",
            tls_profile="validated",
            ca_cert_file="etc/flexivel-root-ca.crt",
            connect_timeout=5,
            operation_timeout=10,
        )

    def _connection(self, *, bind=True, search=True, response=None, result=None):
        connection = MagicMock()
        connection.bind.return_value = bind
        connection.search.return_value = search
        connection.response = response or []
        connection.result = result or {}
        return connection

    def test_busca_escapa_filtro_e_le_guid_binario_little_endian(self):
        from colaboradores.directory import DirectoryStatus

        guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        connection = self._connection(response=[{
            "type": "searchResEntry",
            "dn": "CN=Ana,DC=example,DC=test",
            "raw_attributes": {"objectGUID": [guid.bytes_le]},
        }])
        with patch("colaboradores.directory.Connection") as connection_class:
            connection_class.return_value.__enter__.return_value = connection

            lookup = self._client().find_user("*)(objectClass=*)")

        self.assertEqual(lookup.status, DirectoryStatus.OK)
        self.assertEqual(lookup.entry.object_guid, guid)
        self.assertEqual(lookup.entry.dn, "CN=Ana,DC=example,DC=test")
        args = connection.search.call_args.kwargs
        self.assertIn(r"\2a\29\28objectClass=\2a\29", args["search_filter"])
        self.assertEqual(args["size_limit"], 2)
        self.assertEqual(args["attributes"], ["objectGUID"])
        self.assertEqual(args["search_scope"], "SUBTREE")

    def test_busca_sem_resultado_e_ambigua_sao_tipadas(self):
        from colaboradores.directory import DirectoryStatus

        with patch("colaboradores.directory.Connection") as connection_class:
            connection_class.return_value.__enter__.return_value = self._connection(response=[])
            missing = self._client().find_user("ana")

        self.assertEqual(missing.status, DirectoryStatus.NOT_FOUND)
        entries = [
            {"type": "searchResEntry", "dn": f"CN={name}", "raw_attributes": {}}
            for name in ("Ana", "Ana 2")
        ]
        with patch("colaboradores.directory.Connection") as connection_class:
            connection_class.return_value.__enter__.return_value = self._connection(response=entries)
            ambiguous = self._client().find_user("ana")

        self.assertEqual(ambiguous.status, DirectoryStatus.AMBIGUOUS)
        self.assertIsNone(ambiguous.entry)

    def test_bind_da_conta_de_servico_recusado_e_indisponivel(self):
        from colaboradores.directory import DirectoryStatus

        connection = self._connection(bind=False)
        with patch("colaboradores.directory.Connection") as connection_class:
            connection_class.return_value.__enter__.return_value = connection

            lookup = self._client().find_user("ana")

        self.assertEqual(lookup.status, DirectoryStatus.UNAVAILABLE)
        connection.search.assert_not_called()

    def test_senha_vazia_e_rejeitada_sem_criar_conexao(self):
        from colaboradores.directory import DirectoryClient, DirectoryStatus

        with patch("colaboradores.directory.Connection") as connection_class:
            status = self._client().verify_password("CN=Ana", "")

        self.assertEqual(status, DirectoryStatus.INVALID)
        connection_class.assert_not_called()

    def test_bind_invalido_e_subcodigos_de_conta_sao_tipados(self):
        from colaboradores.directory import DirectoryStatus

        casos = {
            "52e": DirectoryStatus.INVALID,
            "532": DirectoryStatus.PASSWORD_EXPIRED,
            "533": DirectoryStatus.DISABLED,
            "701": DirectoryStatus.EXPIRED,
            "773": DirectoryStatus.MUST_CHANGE_PASSWORD,
            "775": DirectoryStatus.LOCKED,
        }
        for subcode, expected in casos.items():
            with self.subTest(subcode=subcode):
                connection = self._connection(
                    bind=False,
                    result={"result": 49, "description": "invalidCredentials", "message": f"data {subcode}, v1"},
                )
                with patch("colaboradores.directory.Connection") as connection_class:
                    connection_class.return_value.__enter__.return_value = connection

                    status = self._client().verify_password("CN=Ana", "wrong")

                self.assertEqual(status, expected)

    def test_timeout_e_falha_tls_sao_indisponibilidade(self):
        from colaboradores.directory import DirectoryStatus
        from ldap3.core.exceptions import LDAPSocketOpenError

        with patch("colaboradores.directory.Connection", side_effect=LDAPSocketOpenError("timeout")):
            lookup = self._client().find_user("ana")

        self.assertEqual(lookup.status, DirectoryStatus.UNAVAILABLE)

        with patch("colaboradores.directory.Connection", side_effect=LDAPSocketOpenError("TLS failure")):
            status = self._client().verify_password("CN=Ana", "secret")

        self.assertEqual(status, DirectoryStatus.UNAVAILABLE)


class AuthenticationServiceTests(TestCase):
    def setUp(self):
        from colaboradores.models import Funcionario

        self.Funcionario = Funcionario

    def test_usuario_local_autentica_sem_instanciar_cliente_directory(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService, AuthenticationStatus

        local = self.Funcionario.objects.create_user(
            username="ana.local", password="SenhaLocal-123",
            auth_source=self.Funcionario.AuthSource.LOCAL,
        )
        factory = Mock(side_effect=AssertionError("não pode consultar o AD"))

        result = AuthenticationService(directory_client_factory=factory).authenticate(
            " ana.local ", "SenhaLocal-123"
        )

        self.assertEqual(result.user.pk, local.pk)
        self.assertEqual(result.status, AuthenticationStatus.OK)
        factory.assert_not_called()

    def test_senha_vazia_usuario_ausente_ou_inativo_nao_chamam_directory(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService, AuthenticationStatus

        directory = self.Funcionario.objects.create_user(username="ana.ad")
        inactive = self.Funcionario.objects.create_user(username="inativo")
        inactive.is_active = False
        inactive.save(update_fields={"is_active"})
        factory = Mock(side_effect=AssertionError("não pode consultar o AD"))
        service = AuthenticationService(directory_client_factory=factory)

        for username, password in ((directory.username, ""), ("inexistente", "x"), (inactive.username, "x")):
            with self.subTest(username=username, password=password):
                result = service.authenticate(username, password)
                self.assertIsNone(result.user)
                self.assertEqual(result.status, AuthenticationStatus.INVALID)
        factory.assert_not_called()

    def test_directory_grava_guid_somente_apos_bind_bem_sucedido(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService, AuthenticationStatus
        from colaboradores.directory import DirectoryEntry, DirectoryLookup, DirectoryStatus

        user = self.Funcionario.objects.create_user(username="ana.ad")
        guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        client = Mock()
        client.find_user.return_value = DirectoryLookup(
            DirectoryStatus.OK, DirectoryEntry("CN=Ana,DC=example,DC=test", guid)
        )
        client.verify_password.return_value = DirectoryStatus.INVALID
        service = AuthenticationService(directory_client_factory=lambda: client)

        rejected = service.authenticate(user.username, "senha-errada")
        user.refresh_from_db()
        self.assertEqual(rejected.status, AuthenticationStatus.INVALID)
        self.assertIsNone(user.directory_guid)

        client.verify_password.return_value = DirectoryStatus.OK
        accepted = service.authenticate(user.username, "senha-correta")
        user.refresh_from_db()
        self.assertEqual(accepted.user.pk, user.pk)
        self.assertEqual(accepted.status, AuthenticationStatus.OK)
        self.assertEqual(user.directory_guid, guid)
        client.find_user.assert_called_with(user.username)
        client.verify_password.assert_called_with("CN=Ana,DC=example,DC=test", "senha-correta")

    def test_guid_divergente_e_indisponibilidade_nao_usam_hash_local(self):
        from unittest.mock import Mock, patch

        from colaboradores.authentication import AuthenticationService, AuthenticationStatus
        from colaboradores.directory import DirectoryEntry, DirectoryLookup, DirectoryStatus

        user = self.Funcionario.objects.create_user(username="ana.ad")
        user.directory_guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        user.save(update_fields={"directory_guid"})
        client = Mock()
        client.find_user.return_value = DirectoryLookup(
            DirectoryStatus.OK,
            DirectoryEntry("CN=Ana,DC=example,DC=test", uuid.UUID("87654321-4321-8765-4321-876543218765")),
        )
        service = AuthenticationService(directory_client_factory=lambda: client)

        mismatch = service.authenticate(user.username, "senha")
        self.assertEqual(mismatch.status, AuthenticationStatus.IDENTITY_MISMATCH)
        client.verify_password.assert_not_called()

        client.find_user.return_value = DirectoryLookup(DirectoryStatus.UNAVAILABLE)
        with patch.object(user, "check_password", side_effect=AssertionError("fallback local proibido")):
            unavailable = service.authenticate(user.username, "senha")
        self.assertEqual(unavailable.status, AuthenticationStatus.DIRECTORY_UNAVAILABLE)

    def test_guid_ja_vinculado_a_outro_cadastro_negar_autenticacao(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService, AuthenticationStatus
        from colaboradores.directory import DirectoryEntry, DirectoryLookup, DirectoryStatus

        guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        user = self.Funcionario.objects.create_user(username="ana.ad")
        self.Funcionario.objects.create_user(username="outra.conta", directory_guid=guid)
        client = Mock()
        client.find_user.return_value = DirectoryLookup(
            DirectoryStatus.OK, DirectoryEntry("CN=Ana,DC=example,DC=test", guid)
        )
        client.verify_password.return_value = DirectoryStatus.OK

        result = AuthenticationService(directory_client_factory=lambda: client).authenticate(
            user.username, "senha-correta"
        )

        user.refresh_from_db()
        self.assertIsNone(result.user)
        self.assertEqual(result.status, AuthenticationStatus.IDENTITY_MISMATCH)
        self.assertIsNone(user.directory_guid)

    def test_directory_nao_autentica_por_hash_local_existente(self):
        from colaboradores.authentication import AuthenticationService, AuthenticationStatus
        from django.contrib.auth.hashers import make_password
        from unittest.mock import Mock

        user = self.Funcionario.objects.create_user(username="ana.ad")
        self.Funcionario.objects.filter(pk=user.pk).update(password=make_password("senha-local"))
        client = Mock()
        from colaboradores.directory import DirectoryLookup, DirectoryStatus
        client.find_user.return_value = DirectoryLookup(DirectoryStatus.UNAVAILABLE)

        result = AuthenticationService(directory_client_factory=lambda: client).authenticate(
            user.username, "senha-local"
        )

        self.assertEqual(result.status, AuthenticationStatus.DIRECTORY_UNAVAILABLE)
        self.assertIsNone(result.user)


class HybridAuthBackendTests(TestCase):
    def test_backend_hibrido_preserva_permissoes_e_configura_apenas_um_backend(self):
        from django.conf import settings
        from django.contrib.auth.backends import ModelBackend

        from colaboradores.auth_backends import HybridAuthBackend

        self.assertTrue(issubclass(HybridAuthBackend, ModelBackend))
        self.assertEqual(settings.AUTHENTICATION_BACKENDS, ["colaboradores.auth_backends.HybridAuthBackend"])

    def test_backend_guarda_resultado_tipado_no_request(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from colaboradores.auth_backends import HybridAuthBackend
        from colaboradores.authentication import AuthenticationResult, AuthenticationStatus
        from colaboradores.models import Funcionario

        user = Funcionario.objects.create_user(
            username="ana.local", password="senha-local", auth_source=Funcionario.AuthSource.LOCAL
        )
        service = Mock()
        service.authenticate.return_value = AuthenticationResult(user, AuthenticationStatus.OK)
        request = SimpleNamespace()
        with patch("colaboradores.auth_backends.AuthenticationService", return_value=service):
            authenticated = HybridAuthBackend().authenticate(request, username=user.username, password="senha-local")

        self.assertEqual(authenticated.pk, user.pk)
        self.assertEqual(request.hybrid_auth_result.status, AuthenticationStatus.OK)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    MIDDLEWARE=tuple(m for m in settings.MIDDLEWARE if "whitenoise" not in m.lower()),
)
class HybridLoginViewTests(TestCase):
    def test_mensagens_invalidas_genericas_e_indisponibilidade_distinta(self):
        from django.contrib.auth.forms import AuthenticationForm
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from colaboradores.authentication import AuthenticationResult, AuthenticationStatus
        from colaboradores.auth_views import HybridLoginView

        for status, expected in (
            (AuthenticationStatus.INVALID, "Usuário ou senha inválidos."),
            (AuthenticationStatus.IDENTITY_MISMATCH, "Usuário ou senha inválidos."),
            (AuthenticationStatus.DIRECTORY_UNAVAILABLE, "Serviço de autenticação indisponível. Tente em instantes."),
            (AuthenticationStatus.ACCOUNT_DISABLED, "Não foi possível autenticar. Contate o suporte de TI."),
            (AuthenticationStatus.ACCOUNT_EXPIRED, "Não foi possível autenticar. Contate o suporte de TI."),
            (AuthenticationStatus.ACCOUNT_LOCKED, "Não foi possível autenticar. Contate o suporte de TI."),
            (AuthenticationStatus.PASSWORD_EXPIRED, "Não foi possível autenticar. Contate o suporte de TI."),
            (AuthenticationStatus.MUST_CHANGE_PASSWORD, "Não foi possível autenticar. Contate o suporte de TI."),
        ):
            with self.subTest(status=status):
                request = RequestFactory().post("/login/")
                request.user = AnonymousUser()
                request.hybrid_auth_result = AuthenticationResult(None, status)
                view = HybridLoginView()
                view.setup(request)
                response = view.form_invalid(AuthenticationForm(request=request, data={}))
                self.assertContains(response, expected)
                self.assertNotContains(response, "sAMAccountName")

    def test_login_real_mostra_indisponibilidade_e_mensagem_generica_sem_revelar_usuario(self):
        from unittest.mock import patch

        from colaboradores.authentication import AuthenticationResult, AuthenticationStatus

        with patch("colaboradores.auth_backends.AuthenticationService") as service_class:
            service_class.return_value.authenticate.return_value = AuthenticationResult(
                None, AuthenticationStatus.DIRECTORY_UNAVAILABLE
            )
            unavailable = self.client.post(reverse("login"), {"username": "ana.ad", "password": "senha"})
        self.assertContains(unavailable, "Serviço de autenticação indisponível. Tente em instantes.")

        with patch("colaboradores.auth_backends.AuthenticationService") as service_class:
            service_class.return_value.authenticate.return_value = AuthenticationResult(
                None, AuthenticationStatus.INVALID
            )
            invalid = self.client.post(reverse("login"), {"username": "inexistente", "password": "x"})
        self.assertContains(invalid, "Usuário ou senha inválidos.")
        self.assertNotContains(invalid, "inexistente")

    def test_configura_sessao_de_oito_horas_e_expiracao_no_fechamento(self):
        from django.conf import settings

        self.assertEqual(settings.SESSION_COOKIE_AGE, 28800)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

    def test_login_local_redireciona_para_pagina_do_grupo(self):
        from colaboradores.models import Funcionario
        from colaboradores.permissoes import GRUPO_PORTARIA, sincronizar_perfis

        sincronizar_perfis()
        group = Group.objects.get(name=GRUPO_PORTARIA)
        user = Funcionario.objects.create_user(
            username="portaria.login", password="SenhaLocal-123",
            auth_source=Funcionario.AuthSource.LOCAL,
        )
        user.groups.add(group)
        session = self.client.session
        session["pre_login"] = "preservada"
        session.save()
        old_session_key = session.session_key
        response = self.client.post(reverse("login"), {
            "username": user.username, "password": "SenhaLocal-123",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[0][0], reverse("pagina_inicial"))
        self.assertTrue(self.client.session.get("_auth_user_id"))
        self.assertNotEqual(self.client.session.session_key, old_session_key)


class AuthLoggingTests(TestCase):
    def test_logger_de_auditoria_tem_saida_console_info(self):
        from django.conf import settings

        config = settings.LOGGING["loggers"]["colaboradores.auth"]
        self.assertEqual(config["level"], "INFO")
        self.assertFalse(config["propagate"])
        self.assertIn("auth_audit_console", config["handlers"])

    def test_resultados_de_login_e_vinculos_registram_contexto_sem_segredos(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService
        from colaboradores.directory import DirectoryEntry, DirectoryLookup, DirectoryStatus
        from colaboradores.models import Funcionario

        local = Funcionario.objects.create_user(
            username="ana.local", password="senha-local-super-secreta",
            auth_source=Funcionario.AuthSource.LOCAL,
        )
        local_hash = local.password
        service = AuthenticationService(directory_client_factory=Mock())
        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            service.authenticate(local.username, "senha-local-super-secreta", remote_addr="192.0.2.10")
            service.authenticate("usuario-ausente", "senha-informada", remote_addr="192.0.2.11")

        log_text = "\n".join(captured.output)
        self.assertIn("login=ana.local", log_text)
        self.assertIn("source=LOCAL", log_text)
        self.assertIn("result=OK", log_text)
        self.assertIn("remote_addr=192.0.2.10", log_text)
        self.assertIn("source=UNKNOWN", log_text)
        self.assertNotIn("senha-local-super-secreta", log_text)
        self.assertNotIn("senha-informada", log_text)
        self.assertNotIn(local_hash, log_text)

        directory = Funcionario.objects.create_user(username="bia.directory")
        ldap_message_secret = "FULL-LDAP-RESPONSE-CONTAINS-SECRET"
        client = Mock()
        client.find_user.return_value = DirectoryLookup(DirectoryStatus.UNAVAILABLE)
        client.last_response = ldap_message_secret
        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            AuthenticationService(directory_client_factory=lambda: client).authenticate(
                directory.username, "senha-directory", remote_addr="192.0.2.12"
            )
        log_text = "\n".join(captured.output)
        self.assertIn("source=DIRECTORY", log_text)
        self.assertIn("result=DIRECTORY_UNAVAILABLE", log_text)
        self.assertNotIn("senha-directory", log_text)
        self.assertNotIn(ldap_message_secret, log_text)

    def test_eventos_de_guid_gravado_e_divergente_incluem_somente_guids_e_status(self):
        from unittest.mock import Mock

        from colaboradores.authentication import AuthenticationService
        from colaboradores.directory import DirectoryEntry, DirectoryLookup, DirectoryStatus
        from colaboradores.models import Funcionario

        user = Funcionario.objects.create_user(username="guid.user")
        guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        client = Mock()
        client.find_user.return_value = DirectoryLookup(
            DirectoryStatus.OK, DirectoryEntry("CN=Guid,DC=example,DC=test", guid)
        )
        client.verify_password.return_value = DirectoryStatus.OK
        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            AuthenticationService(directory_client_factory=lambda: client).authenticate(
                user.username, "senha-super-secreta"
            )
        self.assertIn("event=directory_guid_linked", "\n".join(captured.output))
        self.assertNotIn("senha-super-secreta", "\n".join(captured.output))

        user.directory_guid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        user.save(update_fields={"directory_guid"})
        with self.assertLogs("colaboradores.auth", level="INFO") as captured:
            AuthenticationService(directory_client_factory=lambda: client).authenticate(
                user.username, "senha-super-secreta"
            )
        log_text = "\n".join(captured.output)
        self.assertIn("result=IDENTITY_MISMATCH", log_text)
        self.assertIn(str(guid), log_text)
        self.assertNotIn("CN=Guid", log_text)
        self.assertNotIn("senha-super-secreta", log_text)
