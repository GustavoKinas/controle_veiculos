import csv
from django.core.management.base import BaseCommand
from colaboradores.forms import gerar_username
from colaboradores.models import Funcionario, UnidadeFabril,CentroCusto

class Command(BaseCommand):
    help = 'Realiza a importação dos funcionarios de um .CSV para cadastrar na aplicação'

    def add_arguments(self,parser):
        parser.add_argument('csv_file', type=str)

    def handle(self,*args,**options):
        path = options['csv_file']

        unidades = {
            unidade.nome.strip(): unidade for unidade in UnidadeFabril.objects.all()
        }

        buscador_centro_custo = CentroCusto.objects.in_bulk(field_name='codigo')
        
        funcionarios_existentes = {
            funcionario.nome.strip().lower()
            for funcionario in Funcionario.objects.all()
        }

        with open(path, 'r', encoding='cp1252') as file:
            reader = csv.DictReader(file,delimiter=';')
            print(reader.fieldnames)

            for row in reader:
                nome_funcionario = row["Nome"]
                nome_funcionario_formatado = nome_funcionario.strip().lower()
                unidade_fabril_funcionario = row["Unidade"].strip()
                codigo_centro_custo_funcionario = row["Centro de Custo"].strip()


                if nome_funcionario_formatado in funcionarios_existentes:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Funcionário {nome_funcionario_formatado} já existe"
                        )
                    )
                    continue

                unidade = unidades.get(unidade_fabril_funcionario)

                if not unidade:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Unidade fabril '{unidade_fabril_funcionario}' não encontrada."
                        )
                    )
                    continue

                centro_custo = buscador_centro_custo.get(codigo_centro_custo_funcionario,None)

                if centro_custo is None:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Centro de Custo '{codigo_centro_custo_funcionario}' não encontrado (funcionário: {nome_funcionario})."
                        )
                    )
                    continue

                funcionario = Funcionario(
                    nome=nome_funcionario,
                    unidade_fabril=unidade,
                    centro_custo=centro_custo,
                    username=gerar_username(nome_funcionario),
                )

                try:
                    # Sem login nesta etapa.
                    funcionario.set_unusable_password()
                    funcionario.save()

                    funcionarios_existentes.add(nome_funcionario_formatado)

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Funcionário {nome_funcionario} cadastrado."
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Erro ao salvar {nome_funcionario}: {str(e)}"
                        )
                    )
                    continue