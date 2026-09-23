import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from .models import Funcionario, UnidadeFabril


class CadastroFuncionariosCommandTest(TestCase):
    def test_importa_csv_do_erp_por_codigo_empresa_e_cria_catalogos(self):
        unidade = UnidadeFabril.objects.create(
            nome="Matriz",
            codigo_empresa_erp=1,
        )

        with TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "funcionarios.csv"
            with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
                escritor = csv.writer(arquivo, delimiter=";")
                escritor.writerow(
                    [
                        "Código Empresa",
                        "Funcionário",
                        "Nome Funcionário",
                        "Departamento",
                        "Seção",
                    ]
                )
                escritor.writerow(
                    [
                        "1",
                        "518",
                        "ANA SOUZA",
                        "PRODUÇÃO",
                        "MONTAGEM",
                    ]
                )

            call_command(
                "cadastro_funcionarios",
                str(caminho),
                stdout=StringIO(),
            )

        funcionario = Funcionario.objects.get(codigo_funcionario_erp="518")

        self.assertEqual(funcionario.unidade_fabril, unidade)
        self.assertEqual(funcionario.nome, "ANA SOUZA")
        self.assertEqual(funcionario.departamento.descricao, "PRODUÇÃO")
        self.assertEqual(funcionario.secao.descricao, "MONTAGEM")
        self.assertEqual(funcionario.secao.departamento, funcionario.departamento)
