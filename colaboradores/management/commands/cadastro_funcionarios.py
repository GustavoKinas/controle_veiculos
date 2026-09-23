"""
Importa colaboradores de um CSV.

O formato antigo aceita nome, unidade por nome, centro de custo e e-mail.
Também é aceito o formato exportado pelo ERP:

    Código Empresa;Funcionário;Nome Funcionário;Departamento;Seção

Nesse formato, a unidade é resolvida por `UnidadeFabril.codigo_empresa_erp` e
a identidade do funcionário é o par `Código Empresa + Funcionário`.

Os catálogos de departamento e seção são criados automaticamente. A seção é
específica do departamento, então duas seções com a mesma descrição em
departamentos diferentes são registros distintos.

    python manage.py cadastro_funcionarios caminho/arquivo.csv
"""

import csv
import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from colaboradores.forms import gerar_username
from colaboradores.models import (
    CentroCusto,
    Departamento,
    Funcionario,
    Secao,
    UnidadeFabril,
    normalizar_descricao_catalogo,
    preparar_descricao_catalogo,
)

from .cadastro_centro_custo import normalizar_codigo


COLUNAS_ACEITAS = {
    "nome": ("nome", "nomefuncionario"),
    "unidade": ("unidade", "unidadefabril"),
    "codigo_empresa": ("codigoempresa",),
    "codigo_funcionario_erp": (
        "funcionario",
        "codfuncionario",
        "codigofuncionarioerp",
    ),
    "centro_custo": ("centrodecusto", "centrocusto"),
    "email": ("email",),
    "departamento": ("departamento",),
    "secao": ("secao",),
}

OBRIGATORIAS_FORMATO_ERP = (
    "nome",
    "codigo_empresa",
    "codigo_funcionario_erp",
    "departamento",
    "secao",
)


def _chave(cabecalho: str) -> str:
    """Normaliza cabeçalho, incluindo acentos e BOM do UTF-8."""
    sem_acentos = unicodedata.normalize("NFKD", cabecalho or "")
    sem_acentos = "".join(
        caractere for caractere in sem_acentos if not unicodedata.combining(caractere)
    )
    return (
        sem_acentos.lstrip("\ufeff")
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def mapear_colunas(
    cabecalhos: list[str] | None, obrigatorias: tuple[str, ...] = ("nome",)
) -> dict[str, str]:
    """Descobre e valida as colunas lógicas do arquivo."""
    if not cabecalhos:
        raise CommandError("O arquivo não tem cabeçalho.")

    encontradas = {_chave(cabecalho): cabecalho for cabecalho in cabecalhos}
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


def _normalizar_nome(nome: str) -> str:
    return " ".join((nome or "").split()).casefold()


def _normalizar_codigo_empresa(valor: str) -> int | None:
    bruto = (valor or "").strip()
    if not bruto or not bruto.isdecimal():
        return None
    codigo = int(bruto)
    return codigo if codigo > 0 else None


def _normalizar_codigo_funcionario(valor: str) -> str:
    return (valor or "").strip()


class Command(BaseCommand):
    help = "Importa colaboradores de um CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_file", type=str)
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help=(
                "Codificação do arquivo (padrão: utf-8-sig; use cp1252 para "
                "exportações antigas do Excel)."
            ),
        )

    def handle(self, *args, **options) -> None:
        caminho = options["csv_file"]

        unidades_por_codigo = {
            unidade.codigo_empresa_erp: unidade
            for unidade in UnidadeFabril.objects.all()
            if unidade.codigo_empresa_erp is not None
        }
        unidades_por_nome = {
            unidade.nome.strip(): unidade for unidade in UnidadeFabril.objects.all()
        }
        centros_custo = CentroCusto.objects.in_bulk(field_name="codigo")

        funcionarios_por_nome = defaultdict(list)
        funcionarios_por_identidade = {}
        for funcionario in Funcionario.objects.all():
            funcionarios_por_nome[_normalizar_nome(funcionario.nome)].append(funcionario)
            if funcionario.unidade_fabril_id and funcionario.codigo_funcionario_erp:
                funcionarios_por_identidade[
                    (funcionario.unidade_fabril_id, funcionario.codigo_funcionario_erp)
                ] = funcionario

        criados = atualizados = ignorados = com_erro = 0
        sem_centro_custo = cc_nao_encontrado = sem_email = 0
        catalogos_criados = 0

        try:
            arquivo = open(caminho, "r", encoding=options["encoding"], newline="")
        except OSError as erro:
            raise CommandError(f"Não consegui abrir {caminho}: {erro}") from erro

        with arquivo:
            leitor = csv.DictReader(arquivo, delimiter=";")
            colunas = mapear_colunas(leitor.fieldnames)
            formato_erp = any(
                campo in colunas
                for campo in (
                    "codigo_empresa",
                    "codigo_funcionario_erp",
                    "departamento",
                    "secao",
                )
            )
            if formato_erp:
                colunas = mapear_colunas(
                    leitor.fieldnames,
                    obrigatorias=OBRIGATORIAS_FORMATO_ERP,
                )
            elif "unidade" not in colunas:
                raise CommandError(
                    "O arquivo deve informar a unidade por nome ou por "
                    "'Código Empresa'."
                )

            self.stdout.write(f"Colunas reconhecidas: {colunas}")

            for linha in leitor:
                nome = (linha.get(colunas["nome"]) or "").strip()
                if not nome:
                    continue

                unidade = None
                codigo_funcionario_erp = None
                departamento = secao = None
                funcionario = None

                if formato_erp:
                    codigo_empresa = _normalizar_codigo_empresa(
                        linha.get(colunas["codigo_empresa"])
                    )
                    if codigo_empresa is None:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: código de empresa inválido "
                                f"'{linha.get(colunas['codigo_empresa'])}'."
                            )
                        )
                        com_erro += 1
                        continue

                    unidade = unidades_por_codigo.get(codigo_empresa)
                    if unidade is None:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: unidade fabril com código de empresa "
                                f"ERP '{codigo_empresa}' não encontrada."
                            )
                        )
                        com_erro += 1
                        continue

                    codigo_funcionario_erp = _normalizar_codigo_funcionario(
                        linha.get(colunas["codigo_funcionario_erp"])
                    )
                    if not codigo_funcionario_erp:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: código ERP do funcionário vazio."
                            )
                        )
                        com_erro += 1
                        continue

                    descricao_departamento = preparar_descricao_catalogo(
                        linha.get(colunas["departamento"])
                    )
                    descricao_secao = preparar_descricao_catalogo(
                        linha.get(colunas["secao"])
                    )
                    if not descricao_departamento or not descricao_secao:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: departamento e seção são obrigatórios."
                            )
                        )
                        com_erro += 1
                        continue

                    departamento, foi_criado = Departamento.objects.get_or_create(
                        descricao_normalizada=normalizar_descricao_catalogo(
                            descricao_departamento
                        ),
                        defaults={"descricao": descricao_departamento},
                    )
                    catalogos_criados += foi_criado

                    secao, foi_criado = Secao.objects.get_or_create(
                        departamento=departamento,
                        descricao_normalizada=normalizar_descricao_catalogo(
                            descricao_secao
                        ),
                        defaults={"descricao": descricao_secao},
                    )
                    catalogos_criados += foi_criado

                    funcionario = funcionarios_por_identidade.get(
                        (unidade.pk, codigo_funcionario_erp)
                    )
                    if funcionario is None:
                        candidatos_legados = [
                            candidato
                            for candidato in funcionarios_por_nome[_normalizar_nome(nome)]
                            if not candidato.codigo_funcionario_erp
                        ]
                        if len(candidatos_legados) == 1:
                            funcionario = candidatos_legados[0]
                        elif len(candidatos_legados) > 1:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"{nome}: mais de um cadastro legado sem "
                                    "código ERP para vincular."
                                )
                            )
                            com_erro += 1
                            continue
                else:
                    if funcionarios_por_nome[_normalizar_nome(nome)]:
                        self.stdout.write(
                            self.style.WARNING(f"{nome}: já existe, ignorado.")
                        )
                        ignorados += 1
                        continue

                    unidade = unidades_por_nome.get(
                        (linha.get(colunas["unidade"]) or "").strip()
                    )
                    if unidade is None:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{nome}: unidade fabril "
                                f"'{linha.get(colunas['unidade'])}' não encontrada."
                            )
                        )
                        com_erro += 1
                        continue

                bruto_cc = (
                    linha.get(colunas["centro_custo"], "")
                    if "centro_custo" in colunas
                    else ""
                )
                codigo_cc = normalizar_codigo(bruto_cc)
                centro_custo = None
                if "centro_custo" in colunas:
                    if codigo_cc:
                        centro_custo = centros_custo.get(codigo_cc)
                        if centro_custo is None:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"{nome}: centro de custo '{bruto_cc.strip()}' "
                                    "não cadastrado — importado SEM centro de custo."
                                )
                            )
                            cc_nao_encontrado += 1
                    else:
                        sem_centro_custo += 1

                email = None
                if "email" in colunas:
                    email = (linha.get(colunas["email"]) or "").strip().lower()
                    if not email:
                        sem_email += 1

                if formato_erp and funcionario is not None:
                    dados = {
                        "nome": nome,
                        "codigo_funcionario_erp": codigo_funcionario_erp,
                        "unidade_fabril": unidade,
                        "departamento": departamento,
                        "secao": secao,
                    }
                    if "centro_custo" in colunas:
                        dados["centro_custo"] = centro_custo
                    if "email" in colunas:
                        dados["email"] = email or ""

                    campos_relacionais = {
                        "unidade_fabril",
                        "centro_custo",
                        "departamento",
                        "secao",
                    }
                    campos_alterados = []
                    for campo, valor in dados.items():
                        if campo in campos_relacionais:
                            atual = getattr(funcionario, f"{campo}_id")
                            novo = valor.pk if valor is not None else None
                        else:
                            atual = getattr(funcionario, campo)
                            novo = valor
                        if atual != novo:
                            setattr(funcionario, campo, valor)
                            campos_alterados.append(campo)

                    if campos_alterados:
                        funcionario.save(update_fields=campos_alterados)
                        atualizados += 1
                        self.stdout.write(self.style.SUCCESS(f"{nome}: atualizado."))
                    else:
                        ignorados += 1
                        self.stdout.write(
                            self.style.WARNING(f"{nome}: já estava atualizado.")
                        )
                    funcionarios_por_identidade[
                        (unidade.pk, codigo_funcionario_erp)
                    ] = funcionario
                else:
                    funcionario = Funcionario(
                        nome=nome,
                        email=email or "" if email is not None else "",
                        unidade_fabril=unidade,
                        centro_custo=centro_custo,
                        codigo_funcionario_erp=codigo_funcionario_erp,
                        departamento=departamento,
                        secao=secao,
                        username=gerar_username(nome),
                    )
                    funcionario.set_unusable_password()

                    try:
                        funcionario.save()
                    except Exception as erro:
                        self.stdout.write(
                            self.style.ERROR(f"{nome}: erro ao salvar — {erro}")
                        )
                        com_erro += 1
                        continue

                    criados += 1
                    funcionarios_por_nome[_normalizar_nome(nome)].append(funcionario)
                    if unidade and codigo_funcionario_erp:
                        funcionarios_por_identidade[
                            (unidade.pk, codigo_funcionario_erp)
                        ] = funcionario
                    self.stdout.write(self.style.SUCCESS(f"{nome}: cadastrado."))

        self.stdout.write("")
        for rotulo, valor in (
            ("cadastrados", criados),
            ("atualizados", atualizados),
            ("já existiam", ignorados),
            ("com erro (não cadastrados)", com_erro),
            ("catálogos criados", catalogos_criados),
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
