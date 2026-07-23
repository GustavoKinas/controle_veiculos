import csv
from django.core.management.base import BaseCommand

from colaboradores.models import CentroCusto

class Command(BaseCommand):
    help = 'Realiza a importação dos centro de custo de um .CSV para cadastrar na aplicação'

    def add_arguments(self,parser):
        parser.add_argument('csv_file', type=str)

    def handle(self,*args,**options):
        path = options['csv_file']

        centros_de_custo = CentroCusto.objects.all()

        codigos_centro_custo = {centro_custo.codigo for centro_custo in centros_de_custo}
        descricoes_centro_custo = {centro_custo.descricao for centro_custo in centros_de_custo}

        with open(path, 'r', encoding='cp1252') as file:
            reader = csv.DictReader(file,delimiter=';')
            print(reader.fieldnames)

            for row in reader:

                codigo = row["Centro de Custo"]
                codigo = codigo.strip()

                if codigo in codigos_centro_custo:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Código{codigo} já existe nos cadastros de Centro de Custo"
                        )
                    )
                    continue

                descricao = row["Descrição"]
                descricao = descricao.strip()

                if descricao in descricoes_centro_custo:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Descrição {descricao} já existe nos cadastros de Centro de Custo"
                        )
                    )
                    continue

                centro_de_custo = CentroCusto(
                    codigo=codigo,
                    descricao=descricao
                )
                try:
                    centro_de_custo.save()
    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Centro de Custo {codigo} - {descricao} cadastrado com sucesso."
                        )
                    )
                    # Atualiza a lista local pra futuras validações
                    codigos_centro_custo.add(codigo)
                    descricoes_centro_custo.add(descricao)
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Erro ao salvar {codigo}: {str(e)}"
                        )
                    )
                    continue