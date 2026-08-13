"""
Importa colaboradores de um CSV.

Colunas aceitas (a comparação ignora maiúsculas, acentos de cabeçalho e
underscores, porque os dois CSVs do projeto usam grafias diferentes):

| Campo            | Nomes aceitos                                  | Obrigatório |
|------------------|------------------------------------------------|-------------|
| Nome             | `nome`, `Nome`                                 | sim         |
| Unidade fabril   | `unidade`, `Unidade`, `unidade_fabril`         | sim         |
| Centro de custo  | `centro de custo`, `Centro de Custo`           | **não**     |
| E-mail           | `email`, `e-mail`, `E-mail`                    | **não**     |

**Os dois campos opcionais existem pela mesma razão: quem trabalha na produção
não reserva carro.** O colaborador entra no cadastro de qualquer forma; o que
cada campo ausente custa é:

- **sem e-mail** → não é identificado nas reservas vindas do Outlook (o
  operador escolhe o colaborador na hora de lançar);
- **sem centro de custo** → não aparece no `<select>` da tela de lançamento,
  porque não haveria para onde ratear o combustível.

Basta preencher o campo depois para a pessoa passar a poder viajar.

O código do centro de custo é normalizado: o ERP exporta `1.01.1.1.05.014` e
o banco guarda `1011105014`.

    python manage.py cadastro_funcionarios caminho/arquivo.csv
"""

import csv

from django.core.management.base import BaseCommand, CommandError

from colaboradores.forms import gerar_username
from colaboradores.models import CentroCusto, Funcionario, UnidadeFabril

from .cadastro_centro_custo import normalizar_codigo

# Cada campo lógico e as grafias de cabeçalho que aceitamos para ele.
COLUNAS_ACEITAS = {
    "nome": ("nome",),
    "unidade": ("unidade", "unidadefabril"),
    "centro_custo": ("centrodecusto", "centrocusto"),
    "email": ("email",),
}

# Centro de custo e e-mail ficam de fora: colaborador da produção é cadastrado
# sem eles (ver o docstring acima).
OBRIGATORIAS = ("nome", "unidade")


def _chave(cabecalho: str) -> str:
    """Normaliza um nome de coluna para comparação: minúsculo, sem espaços,
    hifens ou underscores. `"Centro de Custo"` e `"centro_custo"` viram a
    mesma coisa."""
    return "".join(cabecalho.lower().split()).replace("_", "").replace("-", "")


def mapear_colunas(
    cabecalhos: list[str] | None, obrigatorias: tuple[str, ...] = OBRIGATORIAS
) -> dict[str, str]:
    """
    Descobre qual coluna do arquivo corresponde a cada campo lógico.

    Valida o cabeçalho **uma vez**, antes de processar qualquer linha: um CSV
    sem a coluna de centro de custo produziria 196 mensagens de erro idênticas
    em vez de uma explicação clara.

    `obrigatorias` é parâmetro porque o mesmo CSV serve a dois comandos com
    exigências diferentes — o backfill de e-mail precisa só de nome e e-mail.
    """
    if not cabecalhos:
        raise CommandError("O arquivo não tem cabeçalho.")

    encontradas = {_chave(c): c for c in cabecalhos}
    mapa = {}
    for campo, aceitos in COLUNAS_ACEITAS.items():
        for aceito in aceitos:
            if aceito in encontradas:
                mapa[campo] = encontradas[aceito]
                break

    faltando = [campo for campo in obrigatorias if campo not in mapa]
    if faltando:
        raise CommandError(
            f"Colunas obrigatórias ausentes: {', '.join(faltando)}. "
            f"O arquivo tem: {', '.join(cabecalhos)}."
        )
    return mapa


class Command(BaseCommand):
    help = "Importa colaboradores de um .CSV (nome, unidade, centro de custo e e-mail)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_file", type=str)
        parser.add_argument(
            "--encoding",
            default="cp1252",
            help="Codificação do arquivo (padrão: cp1252, que é o do Excel no Windows).",
        )

    def handle(self, *args, **options) -> None:
        caminho = options["csv_file"]

        unidades = {
            unidade.nome.strip(): unidade for unidade in UnidadeFabril.objects.all()
        }
        centros_custo = CentroCusto.objects.in_bulk(field_name="codigo")

        nomes_existentes = {
            funcionario.nome.strip().lower()
            for funcionario in Funcionario.objects.all()
        }
        # O e-mail é único (constraint parcial em Funcionario.Meta). Guardar os
        # que já existem evita descobrir a colisão só no IntegrityError.
        emails_existentes = set(
            Funcionario.objects.exclude(email="").values_list("email", flat=True)
        )

        criados = ignorados = com_erro = 0
        sem_centro_custo = cc_nao_encontrado = sem_email = 0

        try:
            arquivo = open(caminho, "r", encoding=options["encoding"])
        except OSError as erro:
            raise CommandError(f"Não consegui abrir {caminho}: {erro}") from erro

        with arquivo:
            leitor = csv.DictReader(arquivo, delimiter=";")
            colunas = mapear_colunas(leitor.fieldnames)
            self.stdout.write(f"Colunas reconhecidas: {colunas}")

            for linha in leitor:
                nome = (linha.get(colunas["nome"]) or "").strip()
                if not nome:
                    continue

                if nome.lower() in nomes_existentes:
                    self.stdout.write(
                        self.style.WARNING(f"{nome}: já existe, ignorado.")
                    )
                    ignorados += 1
                    continue

                unidade = unidades.get((linha.get(colunas["unidade"]) or "").strip())
                if unidade is None:
                    self.stdout.write(
                        self.style.ERROR(
                            f"{nome}: unidade fabril "
                            f"'{linha.get(colunas['unidade'])}' não encontrada."
                        )
                    )
                    com_erro += 1
                    continue

                # Normaliza o código: o ERP exporta "1.01.1.1.05.014" e o
                # banco guarda "1011105014".
                bruto_cc = (
                    linha.get(colunas["centro_custo"], "") if "centro_custo" in colunas else ""
                )
                codigo_cc = normalizar_codigo(bruto_cc)
                centro_custo = None

                if codigo_cc:
                    centro_custo = centros_custo.get(codigo_cc)
                    if centro_custo is None:
                        # Código presente mas desconhecido é um problema de
                        # dado, não da pessoa: cadastra mesmo assim e avisa,
                        # em vez de deixar o colaborador fora do sistema.
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: centro de custo '{bruto_cc.strip()}' não "
                                "cadastrado — importado SEM centro de custo."
                            )
                        )
                        cc_nao_encontrado += 1
                elif "centro_custo" in colunas:
                    sem_centro_custo += 1

                # O e-mail é opcional; o `lower()` aqui é só para conferir a
                # colisão — quem normaliza para valer é o Funcionario.save().
                email = ""
                if "email" in colunas:
                    email = (linha.get(colunas["email"]) or "").strip().lower()
                if not email:
                    sem_email += 1

                if email and email in emails_existentes:
                    self.stdout.write(
                        self.style.ERROR(
                            f"{nome}: e-mail {email} já está em uso por outro cadastro."
                        )
                    )
                    com_erro += 1
                    continue

                funcionario = Funcionario(
                    nome=nome,
                    email=email,
                    unidade_fabril=unidade,
                    centro_custo=centro_custo,
                    username=gerar_username(nome),
                )
                # Sem login nesta etapa do projeto.
                funcionario.set_unusable_password()

                try:
                    funcionario.save()
                except Exception as erro:
                    # Sem `transaction.atomic` neste comando: cada save é sua
                    # própria transação, então uma linha ruim não invalida as
                    # seguintes. Envolver tudo em atomic faria o Postgres
                    # abortar a transação no primeiro IntegrityError e todas as
                    # queries posteriores falhariam em cascata.
                    self.stdout.write(self.style.ERROR(f"{nome}: erro ao salvar — {erro}"))
                    com_erro += 1
                    continue

                nomes_existentes.add(nome.lower())
                if email:
                    emails_existentes.add(email)
                criados += 1
                self.stdout.write(self.style.SUCCESS(f"{nome}: cadastrado."))

        self.stdout.write("")
        for rotulo, valor in (
            ("cadastrados", criados),
            ("já existiam", ignorados),
            ("com erro (não cadastrados)", com_erro),
            ("— destes, sem e-mail", sem_email),
            ("— destes, sem centro de custo", sem_centro_custo),
            ("— destes, com centro de custo desconhecido", cc_nao_encontrado),
        ):
            self.stdout.write(f"  {rotulo:44} {valor:>4}")

        if sem_centro_custo or cc_nao_encontrado:
            self.stdout.write(
                self.style.WARNING(
                    "\nColaborador sem centro de custo não aparece na tela de "
                    "lançamento de viagem — é só preencher o cadastro depois."
                )
            )
