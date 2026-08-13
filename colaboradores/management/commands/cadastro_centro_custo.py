"""
Importa centros de custo de um CSV.

O código é normalizado para os 10 dígitos que o modelo exige: a exportação do
ERP vem com separadores (`1.01.1.1.05.014`) e o banco guarda `1011105014`.
Sem isso, todo código novo estoura em "valor é muito longo para
character varying(10)".

Colunas aceitas (comparação ignora caixa, espaços e separadores):
`Centro de Custo` / `centro_custo`, e `Descrição` / `descricao`.

    python manage.py cadastro_centro_custo caminho/cc.csv
"""

import csv
import re

from django.core.management.base import BaseCommand, CommandError

COLUNAS_ACEITAS = {
    "codigo": ("centrodecusto", "centrocusto", "codigo"),
    "descricao": ("descricao", "descrição"),
}

TAMANHO_CODIGO = 10


def _chave(cabecalho: str) -> str:
    return "".join(cabecalho.lower().split()).replace("_", "").replace("-", "")


def normalizar_codigo(bruto: str) -> str:
    """
    `"1.01.1.1.05.014"` → `"1011105014"`.

    O ERP exporta com separadores e o modelo valida `^\\d{10}$`. Note que o
    validador só roda em `full_clean()`, que o `save()` não chama — sem esta
    normalização o único guarda-costas seria o `varchar(10)` do Postgres, e o
    erro chegaria como falha de banco em vez de dado inválido.
    """
    return re.sub(r"\D", "", bruto or "")


class Command(BaseCommand):
    help = "Importa centros de custo de um .CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_file", type=str)
        parser.add_argument("--encoding", default="cp1252")

    def handle(self, *args, **options) -> None:
        # Import tardio: o modelo é carregado depois do setup do Django.
        from colaboradores.models import CentroCusto

        criados = atualizados = ignorados = invalidos = 0

        try:
            arquivo = open(options["csv_file"], encoding=options["encoding"])
        except OSError as erro:
            raise CommandError(f"Não consegui abrir o arquivo: {erro}") from erro

        with arquivo:
            leitor = csv.DictReader(arquivo, delimiter=";")
            if not leitor.fieldnames:
                raise CommandError("O arquivo não tem cabeçalho.")

            encontradas = {_chave(c): c for c in leitor.fieldnames}
            colunas = {}
            for campo, aceitos in COLUNAS_ACEITAS.items():
                for aceito in aceitos:
                    if aceito in encontradas:
                        colunas[campo] = encontradas[aceito]
                        break
            faltando = [campo for campo in COLUNAS_ACEITAS if campo not in colunas]
            if faltando:
                raise CommandError(
                    f"Colunas obrigatórias ausentes: {', '.join(faltando)}. "
                    f"O arquivo tem: {', '.join(leitor.fieldnames)}."
                )

            vistos: set[str] = set()

            for linha in leitor:
                codigo = normalizar_codigo(linha.get(colunas["codigo"]))
                descricao = (linha.get(colunas["descricao"]) or "").strip()

                # Linha em branco no fim do arquivo: pular em silêncio. Sem
                # isto, um código vazio passa direto e vira um CentroCusto
                # inválido no banco (o varchar aceita string vazia).
                if not codigo and not descricao:
                    continue

                if len(codigo) != TAMANHO_CODIGO:
                    self.stdout.write(
                        self.style.ERROR(
                            f"código inválido '{linha.get(colunas['codigo'])}' "
                            f"→ '{codigo}' ({len(codigo)} dígitos, esperado {TAMANHO_CODIGO})."
                        )
                    )
                    invalidos += 1
                    continue

                # O arquivo é por colaborador, então o mesmo código se repete.
                if codigo in vistos:
                    ignorados += 1
                    continue
                vistos.add(codigo)

                # O código é a ÚNICA chave. A versão anterior também pulava
                # quando a DESCRIÇÃO já existia — e centros de custo distintos
                # podem compartilhar descrição, então códigos legítimos eram
                # descartados em silêncio.
                _, foi_criado = CentroCusto.objects.update_or_create(
                    codigo=codigo, defaults={"descricao": descricao}
                )
                criados += foi_criado
                atualizados += not foi_criado

                if foi_criado:
                    self.stdout.write(
                        self.style.SUCCESS(f"{codigo} — {descricao}: cadastrado.")
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{criados} criado(s), {atualizados} atualizado(s), "
                f"{ignorados} repetido(s) no arquivo, {invalidos} inválido(s)."
            )
        )
