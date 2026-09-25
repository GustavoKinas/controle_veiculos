import importlib
import os
import tempfile
from unittest import TestCase, mock

from controle_veiculos.directory_config import DirectoryConfig


class DirectoryConfigTests(TestCase):
    def setUp(self):
        self.ca_file = tempfile.NamedTemporaryFile()
        self.addCleanup(self.ca_file.close)
        self.environ = {
            "LDAP_URI": "ldaps://dc.example.test:636",
            "LDAP_BASE_DN": "DC=example,DC=test",
            "LDAP_BIND_USER": "svc-app@example.test",
            "LDAP_BIND_PASSWORD": "service-secret",
            "LDAP_TLS_PROFILE": "validated",
            "LDAP_CA_CERT_FILE": self.ca_file.name,
            "LDAP_NETWORK_TIMEOUT": "5",
            "LDAP_OPERATION_TIMEOUT": "10",
            "SESSION_MAX_AGE": "28800",
        }

    def test_configuracao_valida_e_imutavel_e_repr_nao_expoe_senha(self):
        config = DirectoryConfig.from_env(self.environ)

        self.assertEqual(config.uri, "ldaps://dc.example.test:636")
        self.assertEqual(config.connect_timeout, 5)
        self.assertEqual(config.operation_timeout, 10)
        self.assertEqual(config.session_max_age, 28800)
        self.assertNotIn("service-secret", repr(config))
        with self.assertRaises(AttributeError):
            config.uri = "ldaps://other.example.test"

    def test_variaveis_obrigatorias_ausentes_sao_identificadas(self):
        required = tuple(self.environ)
        for name in required:
            with self.subTest(name=name):
                values = dict(self.environ)
                values.pop(name)
                with self.assertRaisesRegex(ValueError, name):
                    DirectoryConfig.from_env(values)

    def test_rejeita_ldap_em_claro_ip_literal_hostname_ausente_e_perfil_nao_validado(self):
        invalid = (
            ("LDAP_URI", "ldap://dc.example.test:389"),
            ("LDAP_URI", "ldaps:///DC=example,DC=test"),
            ("LDAP_URI", "ldaps://192.0.2.10:636"),
            ("LDAP_TLS_PROFILE", "unvalidated"),
        )
        for name, value in invalid:
            with self.subTest(name=name, value=value):
                values = dict(self.environ, **{name: value})
                with self.assertRaises(ValueError):
                    DirectoryConfig.from_env(values)

    def test_rejeita_ca_ausente_ou_ilegivel(self):
        values = dict(self.environ, LDAP_CA_CERT_FILE="/tmp/nao-existe-ca.pem")
        with self.assertRaisesRegex(ValueError, "LDAP_CA_CERT_FILE"):
            DirectoryConfig.from_env(values)

        with mock.patch("controle_veiculos.directory_config.os.access", return_value=False):
            with self.assertRaisesRegex(ValueError, "LDAP_CA_CERT_FILE"):
                DirectoryConfig.from_env(self.environ)

    def test_timeouts_devem_ser_positivos_e_sessao_deve_ser_oito_horas(self):
        for key in ("LDAP_NETWORK_TIMEOUT", "LDAP_OPERATION_TIMEOUT"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, key):
                    DirectoryConfig.from_env(dict(self.environ, **{key: "0"}))
        with self.assertRaisesRegex(ValueError, "SESSION_MAX_AGE"):
            DirectoryConfig.from_env(dict(self.environ, SESSION_MAX_AGE="3600"))

    def test_repr_nao_contem_senha_mesmo_com_outros_dados(self):
        config = DirectoryConfig.from_env(self.environ)

        self.assertNotIn(self.environ["LDAP_BIND_PASSWORD"], repr(config))


class DirectoryConfigStartupTests(TestCase):
    def test_wsgi_valida_configuracao_antes_de_criar_aplicacao(self):
        import controle_veiculos.directory_config as directory_config
        from types import SimpleNamespace

        events = []
        with mock.patch.object(
            directory_config,
            "get_directory_config",
            side_effect=lambda: events.append("config") or SimpleNamespace(tls_profile="validated"),
        ):
            with mock.patch("django.core.wsgi.get_wsgi_application", side_effect=lambda: events.append("application") or object()):
                with mock.patch(
                    "colaboradores.auth_logging.log_directory_transport",
                    side_effect=lambda **kwargs: events.append(("transport", kwargs)),
                ):
                    importlib.import_module("controle_veiculos.wsgi")

        self.assertEqual(
            events,
            [
                "config",
                "application",
                ("transport", {"transport": "LDAPS", "tls_profile": "validated"}),
            ],
        )

    def test_get_directory_config_usa_cache_explicitamente_limpo(self):
        import controle_veiculos.directory_config as directory_config

        with tempfile.NamedTemporaryFile() as ca_file:
            values = {
                "LDAP_URI": "ldaps://dc.example.test:636",
                "LDAP_BASE_DN": "DC=example,DC=test",
                "LDAP_BIND_USER": "svc-app@example.test",
                "LDAP_BIND_PASSWORD": "secret",
                "LDAP_TLS_PROFILE": "validated",
                "LDAP_CA_CERT_FILE": ca_file.name,
                "LDAP_NETWORK_TIMEOUT": "5",
                "LDAP_OPERATION_TIMEOUT": "10",
                "SESSION_MAX_AGE": "28800",
            }
            directory_config.get_directory_config.cache_clear()
            with mock.patch.dict(os.environ, values, clear=False):
                first = directory_config.get_directory_config()
                second = directory_config.get_directory_config()
            directory_config.get_directory_config.cache_clear()

        self.assertIs(first, second)
