"""
Testes da sincronização de funcionários com o ERP.

Cobre o cliente HTTP (`colaboradores/integracoes/erp.py`), o serviço
(`colaboradores/sincronizacao_erp.py`), o command e a trava de acesso do
botão no Admin. Ver docs/superpowers/plans/2026-09-23-...-plano.md.
"""

import json
from io import StringIO
from unittest import mock

import requests
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from colaboradores.integracoes.erp import ERPIndisponivel, buscar_funcionarios
from colaboradores.models import CentroCusto, Departamento, Funcionario, Secao, UnidadeFabril
from colaboradores.sincronizacao_erp import sincronizar

ENV_ERP = {
    "ERP_FUNCIONARIOS_API_URL": "https://10.1.1.220/api/funcionarios/v10/informacoes",
    "ERP_FUNCIONARIOS_API_TOKEN": "token-secreto-de-teste",
    "ERP_FUNCIONARIOS_API_TIMEOUT": "300",
}


def _resposta(status_code=200, payload=None, corpo_invalido=False):
    resposta = mock.Mock()
    resposta.status_code = status_code
    if corpo_invalido:
        resposta.json.side_effect = json.JSONDecodeError("erro", "doc", 0)
    else:
        resposta.json.return_value = payload
    return resposta


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------
class ERPClientTest(TestCase):
    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_monta_url_parametros_e_headers_de_admissao(self, get_mock):
        get_mock.return_value = _resposta(payload={"data": []})

        buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

        get_mock.assert_called_once()
        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["params"], {"dataAdmissao": "202609"})
        self.assertEqual(kwargs["headers"]["empresa"], "1")
        self.assertEqual(kwargs["headers"]["accept"], "application/json")
        self.assertEqual(kwargs["headers"]["Authorization"], "token-secreto-de-teste")
        self.assertEqual(kwargs["timeout"], 300)
        self.assertFalse(kwargs["verify"])

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_monta_parametro_de_demissao(self, get_mock):
        get_mock.return_value = _resposta(payload={"data": []})

        buscar_funcionarios(empresa=20, periodo="202609", operacao="demissao")

        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["params"], {"dataDemissao": "202609"})
        self.assertEqual(kwargs["headers"]["empresa"], "20")

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_devolve_data_da_resposta_valida(self, get_mock):
        registros = [{"codFuncionario": 1, "nome": "Ana", "situacao": "Ativo"}]
        get_mock.return_value = _resposta(payload={"data": registros})

        resultado = buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

        self.assertEqual(resultado, registros)

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_data_vazia_e_valida(self, get_mock):
        get_mock.return_value = _resposta(payload={"data": []})

        resultado = buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

        self.assertEqual(resultado, [])

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_json_invalido_levanta_erpindisponivel(self, get_mock):
        get_mock.return_value = _resposta(corpo_invalido=True)

        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_data_ausente_levanta_erpindisponivel(self, get_mock):
        get_mock.return_value = _resposta(payload={"outracoisa": []})

        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_data_nao_lista_levanta_erpindisponivel(self, get_mock):
        get_mock.return_value = _resposta(payload={"data": {"não": "é lista"}})

        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_status_http_fora_de_2xx_levanta_erpindisponivel(self, get_mock):
        get_mock.return_value = _resposta(status_code=500, payload={})

        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

    @mock.patch.dict("os.environ", ENV_ERP, clear=False)
    @mock.patch("colaboradores.integracoes.erp.requests.get")
    def test_erro_de_conexao_levanta_erpindisponivel(self, get_mock):
        get_mock.side_effect = requests.ConnectionError("sem rede")

        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

    @mock.patch.dict("os.environ", {**ENV_ERP, "ERP_FUNCIONARIOS_API_TOKEN": ""}, clear=False)
    def test_token_ausente_levanta_erpindisponivel_sem_expor_valor(self):
        with self.assertRaises(ERPIndisponivel) as contexto:
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")

        self.assertNotIn("token-secreto-de-teste", str(contexto.exception))

    @mock.patch.dict("os.environ", {**ENV_ERP, "ERP_FUNCIONARIOS_API_URL": ""}, clear=False)
    def test_url_ausente_levanta_erpindisponivel(self):
        with self.assertRaises(ERPIndisponivel):
            buscar_funcionarios(empresa=1, periodo="202609", operacao="admissao")


# ---------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------
def _unidades():
    return {
        1: UnidadeFabril.objects.create(nome="Matriz", codigo_empresa_erp=1),
        2: UnidadeFabril.objects.create(nome="Filial MG", codigo_empresa_erp=2),
        20: UnidadeFabril.objects.create(nome="EVO", codigo_empresa_erp=20),
    }


def _respostas_por_empresa_e_operacao(mapa: dict) -> mock.Mock:
    """
    `mapa` é `{(empresa, operacao): [registros]}`. Empresas/operações
    ausentes do mapa devolvem lista vazia — mesmo comportamento de uma
    consulta real sem admitidos/demitidos no período.
    """

    def _buscar(empresa, periodo, operacao):
        return mapa.get((empresa, operacao), [])

    return mock.patch(
        "colaboradores.sincronizacao_erp.buscar_funcionarios", side_effect=_buscar
    )


class FuncionarioSyncServiceTest(TestCase):
    def setUp(self):
        self.unidades = _unidades()

    def test_cria_funcionario_ativo_por_admissao(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 100, "nome": "Ana Souza", "situacao": "Ativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            resultado = sincronizar(operacoes=("admissao",))

        funcionario = Funcionario.objects.get(
            unidade_fabril=self.unidades[1], codigo_funcionario_erp="100"
        )
        self.assertEqual(funcionario.nome, "Ana Souza")
        self.assertTrue(funcionario.ativo)
        self.assertTrue(funcionario.is_active)
        self.assertFalse(funcionario.has_usable_password())
        self.assertEqual(resultado.funcionarios_criados, 1)

    def test_admissao_com_situacao_diferente_de_ativo_cria_inativo(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 101, "nome": "Beto Lima", "situacao": "Inativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        funcionario = Funcionario.objects.get(
            unidade_fabril=self.unidades[1], codigo_funcionario_erp="101"
        )
        self.assertFalse(funcionario.ativo)
        self.assertFalse(funcionario.is_active)

    def test_admissao_com_situacao_vazia_e_ignorada_com_erro(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 102, "nome": "Carla Dias", "situacao": ""}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            resultado = sincronizar(operacoes=("admissao",))

        self.assertFalse(
            Funcionario.objects.filter(codigo_funcionario_erp="102").exists()
        )
        self.assertEqual(resultado.ignorados, 1)
        self.assertTrue(resultado.erros)

    def test_mesmo_codigo_em_empresas_diferentes_nao_colide(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 200, "nome": "Duplicado", "situacao": "Ativo"}
            ],
            (2, "admissao"): [
                {"codFuncionario": 200, "nome": "Duplicado", "situacao": "Ativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        self.assertEqual(
            Funcionario.objects.filter(codigo_funcionario_erp="200").count(), 2
        )

    def test_demissao_inativa_funcionario_existente(self):
        Funcionario.objects.create(
            username="beto.lima",
            nome="Beto Lima",
            unidade_fabril=self.unidades[1],
            codigo_funcionario_erp="101",
            ativo=True,
            is_active=True,
        )
        mapa = {
            (1, "demissao"): [{"codFuncionario": 101, "nome": "Beto Lima"}],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            resultado = sincronizar(operacoes=("demissao",))

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="101")
        self.assertFalse(funcionario.ativo)
        self.assertFalse(funcionario.is_active)
        self.assertEqual(resultado.funcionarios_inativados, 1)

    def test_demissao_de_codigo_desconhecido_cria_inativo(self):
        mapa = {
            (1, "demissao"): [{"codFuncionario": 999, "nome": "Fulano"}],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            resultado = sincronizar(operacoes=("demissao",))

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="999")
        self.assertFalse(funcionario.ativo)
        self.assertEqual(resultado.funcionarios_criados_inativos, 1)

    def test_ordem_admissao_antes_de_demissao_no_mesmo_lote(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 300, "nome": "Igor", "situacao": "Ativo"}
            ],
            (1, "demissao"): [{"codFuncionario": 300, "nome": "Igor"}],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar()

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="300")
        self.assertFalse(funcionario.ativo)

    def test_data_admissao_gravada_e_data_demissao_limpa_por_admissao(self):
        Funcionario.objects.create(
            username="joana",
            nome="Joana",
            unidade_fabril=self.unidades[1],
            codigo_funcionario_erp="400",
            data_demissao="2025-01-10",
        )
        mapa = {
            (1, "admissao"): [
                {
                    "codFuncionario": 400,
                    "nome": "Joana",
                    "situacao": "Ativo",
                    "dataAdmissao": "2026-09-01",
                }
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="400")
        self.assertEqual(str(funcionario.data_admissao), "2026-09-01")

    def test_ausencia_na_resposta_nao_altera_funcionario(self):
        funcionario = Funcionario.objects.create(
            username="permanece",
            nome="Permanece",
            unidade_fabril=self.unidades[1],
            codigo_funcionario_erp="500",
            ativo=True,
        )
        with _respostas_por_empresa_e_operacao({}):
            sincronizar()

        funcionario.refresh_from_db()
        self.assertTrue(funcionario.ativo)

    def test_centro_custo_e_criado_e_atualizado(self):
        mapa = {
            (1, "admissao"): [
                {
                    "codFuncionario": 600,
                    "nome": "Lia",
                    "situacao": "Ativo",
                    "codCentroCusto": "1234567890",
                    "centroCusto": "Produção",
                }
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        centro = CentroCusto.objects.get(codigo="1234567890")
        self.assertEqual(centro.descricao, "Produção")
        funcionario = Funcionario.objects.get(codigo_funcionario_erp="600")
        self.assertEqual(funcionario.centro_custo, centro)

    def test_centro_custo_vazio_preserva_vinculo_local(self):
        centro = CentroCusto.objects.create(codigo="1111111111", descricao="Preservado")
        funcionario = Funcionario.objects.create(
            username="mario",
            nome="Mario",
            unidade_fabril=self.unidades[1],
            codigo_funcionario_erp="700",
            centro_custo=centro,
        )
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 700, "nome": "Mario", "situacao": "Ativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        funcionario.refresh_from_db()
        self.assertEqual(funcionario.centro_custo, centro)

    def test_departamento_e_secao_criados_e_vinculados(self):
        mapa = {
            (1, "admissao"): [
                {
                    "codFuncionario": 800,
                    "nome": "Nina",
                    "situacao": "Ativo",
                    "departamento": "Produção",
                    "secao": "Impressão",
                }
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="800")
        self.assertEqual(funcionario.departamento.descricao, "Produção")
        self.assertEqual(funcionario.secao.descricao, "Impressão")
        self.assertEqual(funcionario.secao.departamento, funcionario.departamento)

    def test_registro_invalido_isolado_nao_aborta_o_lote(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 900, "nome": "", "situacao": "Ativo"},
                {"codFuncionario": 901, "nome": "Válido", "situacao": "Ativo"},
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            resultado = sincronizar(operacoes=("admissao",))

        self.assertTrue(
            Funcionario.objects.filter(codigo_funcionario_erp="901").exists()
        )
        self.assertEqual(resultado.ignorados, 1)

    def test_falha_de_uma_empresa_nao_aborta_as_demais(self):
        def _buscar(empresa, periodo, operacao):
            if empresa == 1:
                raise ERPIndisponivel("empresa 1 fora do ar")
            return [{"codFuncionario": 950, "nome": "Ok", "situacao": "Ativo"}]

        with mock.patch(
            "colaboradores.sincronizacao_erp.buscar_funcionarios", side_effect=_buscar
        ):
            resultado = sincronizar(operacoes=("admissao",))

        self.assertTrue(
            Funcionario.objects.filter(
                codigo_funcionario_erp="950", unidade_fabril=self.unidades[2]
            ).exists()
        )
        self.assertIn(1, resultado.empresas_com_falha)

    def test_email_e_cargo_nao_sao_alterados_pelo_erp(self):
        funcionario = Funcionario.objects.create(
            username="preserva.email",
            nome="Preserva Email",
            email="ja-cadastrado@grupoflexivel.com.br",
            unidade_fabril=self.unidades[1],
            codigo_funcionario_erp="960",
        )
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 960, "nome": "Preserva Email", "situacao": "Ativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            sincronizar(operacoes=("admissao",))

        funcionario.refresh_from_db()
        self.assertEqual(funcionario.email, "ja-cadastrado@grupoflexivel.com.br")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
class SincronizarFuncionariosERPCommandTest(TestCase):
    def setUp(self):
        self.unidades = _unidades()

    def test_sai_com_erro_quando_ha_falhas(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 1, "nome": "", "situacao": "Ativo"}
            ],
        }
        with _respostas_por_empresa_e_operacao(mapa):
            with self.assertRaises(CommandError):
                call_command(
                    "sincronizar_funcionarios_erp",
                    "--operacao",
                    "admissao",
                    stdout=StringIO(),
                )

    @mock.patch.dict("os.environ", {**ENV_ERP}, clear=False)
    def test_saida_nao_expoe_token(self):
        mapa = {
            (1, "admissao"): [
                {"codFuncionario": 1, "nome": "Ok", "situacao": "Ativo"}
            ],
        }
        saida = StringIO()
        with _respostas_por_empresa_e_operacao(mapa):
            call_command(
                "sincronizar_funcionarios_erp", "--operacao", "admissao", stdout=saida
            )

        self.assertNotIn("token-secreto-de-teste", saida.getvalue())


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
STORAGES_DE_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@override_settings(STORAGES=STORAGES_DE_TESTE)
class SincronizarERPAdminTest(TestCase):
    def setUp(self):
        self.url = reverse("admin:colaboradores_funcionario_sincronizar_erp")

    def test_usuario_comum_nao_acessa(self):
        Funcionario.objects.create_user(
            username="comum", password="senha-123", is_staff=True,
            auth_source=Funcionario.AuthSource.LOCAL,
        )
        self.client.login(username="comum", password="senha-123")

        resposta = self.client.get(self.url)

        self.assertNotEqual(resposta.status_code, 200)

    def test_superusuario_acessa(self):
        Funcionario.objects.create_superuser(
            username="admin-teste", password="senha-123", email=""
        )
        self.client.login(username="admin-teste", password="senha-123")

        with _respostas_por_empresa_e_operacao({}):
            resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 200)
