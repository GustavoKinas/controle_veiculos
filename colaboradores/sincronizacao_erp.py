"""
Orquestração da sincronização de funcionários com o ERP.

Mesmo papel que `viagens/sincronizacao.py` cumpre para o Outlook: junta a
borda HTTP (`colaboradores.integracoes.erp`) com as regras do banco, para que
o command, o botão do Admin e o cron chamem sempre o mesmo caminho.

Regras fechadas no desenho (docs/superpowers/specs/2026-09-22-...):
    - identidade permanente é unidade_fabril + codigo_funcionario_erp;
    - admissão grava só data_admissao; demissão grava só data_demissao;
    - admissão exige "situacao"; demissão ignora "situacao" e sempre inativa;
    - admissões de todas as empresas rodam antes de qualquer demissão;
    - e-mail, cargo, carteira de saúde e dependentes não são tocados aqui;
    - falha de um registro/empresa/operação não aborta o restante do lote.

Uma lacuna do desenho: ele não diz o que fazer quando uma demissão retorna um
código que não existe localmente. A decisão tomada aqui foi criar o registro
já inativo (simétrico à admissão, que cria ativo) em vez de descartar o
registro — mantém o histórico do ERP em vez de silenciá-lo. Revisar com o
usuário se a EVO/Matriz/Filial MG puderem mandar demissão de gente que nunca
passou por uma admissão sincronizada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .forms import gerar_username
from .integracoes.erp import ERPIndisponivel, buscar_funcionarios
from .management.commands.cadastro_centro_custo import normalizar_codigo
from .models import (
    CentroCusto,
    Departamento,
    Funcionario,
    Secao,
    UnidadeFabril,
    normalizar_descricao_catalogo,
    preparar_descricao_catalogo,
)

# Único mapa de empresas conhecido pelo ERP hoje. Ampliar aqui quando surgir
# uma nova empresa — o código não descobre isso sozinho, de propósito: uma
# UnidadeFabril nova sem entrada aqui deve falhar visivelmente, não ser
# ignorada em silêncio.
EMPRESAS_ERP: tuple[int, ...] = (1, 2, 20)

TAMANHO_CODIGO_CENTRO_CUSTO = 10


class RegistroInvalido(Exception):
    """Um registro específico não pode ser persistido — não aborta o lote."""


@dataclass
class ResultadoSincronizacaoERP:
    """O que aconteceu numa rodada, para o command e o Admin relatarem."""

    periodo: str = ""
    operacoes: tuple[str, ...] = ()
    empresas_processadas: list[int] = field(default_factory=list)
    empresas_com_falha: list[int] = field(default_factory=list)
    recebidos: int = 0
    funcionarios_criados: int = 0
    funcionarios_criados_inativos: int = 0
    funcionarios_atualizados: int = 0
    funcionarios_inativados: int = 0
    catalogos_criados: int = 0
    ignorados: int = 0
    erros: list[dict] = field(default_factory=list)

    @property
    def houve_falha(self) -> bool:
        return bool(self.erros) or bool(self.empresas_com_falha)

    def resumo(self) -> dict[str, int]:
        return {
            "recebidos": self.recebidos,
            "criados": self.funcionarios_criados,
            "criados_inativos": self.funcionarios_criados_inativos,
            "atualizados": self.funcionarios_atualizados,
            "inativados": self.funcionarios_inativados,
            "catalogos_criados": self.catalogos_criados,
            "ignorados": self.ignorados,
        }


def mes_corrente() -> str:
    """AAAAMM em America/Sao_Paulo — `timezone.localdate()`, não `date.today()`
    (ver armadilha do relógio do sistema em docs/CONTEXTO_RETOMADA.md §5)."""
    return timezone.localdate().strftime("%Y%m")


def _normalizar_codigo_funcionario(bruto) -> str:
    if bruto is None or isinstance(bruto, bool):
        return ""
    if isinstance(bruto, int):
        return str(bruto)
    return str(bruto).strip()


def _parse_data(bruto: str | None, rotulo: str):
    valor = (bruto or "").strip()
    if not valor:
        return None
    data = parse_date(valor)
    if data is None:
        raise RegistroInvalido(f"{rotulo} em formato inválido: '{valor}'.")
    return data


def _garantir_departamento(bruto, resultado: ResultadoSincronizacaoERP):
    descricao = preparar_descricao_catalogo(bruto)
    if not descricao:
        return None
    departamento, criado = Departamento.objects.get_or_create(
        descricao_normalizada=normalizar_descricao_catalogo(descricao),
        defaults={"descricao": descricao},
    )
    if criado:
        resultado.catalogos_criados += 1
    elif departamento.descricao != descricao:
        departamento.descricao = descricao
        departamento.save(update_fields=["descricao"])
    return departamento


def _garantir_secao(departamento, bruto, resultado: ResultadoSincronizacaoERP):
    descricao = preparar_descricao_catalogo(bruto)
    if not descricao or departamento is None:
        return None
    secao, criado = Secao.objects.get_or_create(
        departamento=departamento,
        descricao_normalizada=normalizar_descricao_catalogo(descricao),
        defaults={"descricao": descricao},
    )
    if criado:
        resultado.catalogos_criados += 1
    elif secao.descricao != descricao:
        secao.descricao = descricao
        secao.save(update_fields=["descricao"])
    return secao


def _resolver_centro_custo(codigo_bruto, descricao_bruta):
    codigo = normalizar_codigo(codigo_bruto or "")
    if not codigo:
        return None
    if len(codigo) != TAMANHO_CODIGO_CENTRO_CUSTO:
        raise RegistroInvalido(
            f"código de centro de custo inválido: '{codigo_bruto}'."
        )
    descricao = (descricao_bruta or "").strip()
    centro, criado = CentroCusto.objects.get_or_create(
        codigo=codigo, defaults={"descricao": descricao}
    )
    if not criado and descricao and centro.descricao != descricao:
        centro.descricao = descricao
        centro.save(update_fields=["descricao"])
    return centro


def _persistir_registro(
    registro: dict,
    operacao: str,
    unidade: UnidadeFabril,
    resultado: ResultadoSincronizacaoERP,
) -> None:
    codigo = _normalizar_codigo_funcionario(registro.get("codFuncionario"))
    if not codigo or len(codigo) > 125:
        raise RegistroInvalido("codFuncionario ausente, vazio ou muito longo.")

    nome = (registro.get("nome") or "").strip()
    if not nome or len(nome) > 125:
        raise RegistroInvalido("nome ausente, vazio ou muito longo.")

    if operacao == "admissao":
        situacao = (registro.get("situacao") or "").strip()
        if not situacao:
            raise RegistroInvalido("situação ausente em admissão.")
        ativo = situacao.casefold() == "ativo"
        nova_data_admissao = _parse_data(registro.get("dataAdmissao"), "dataAdmissao")
        nova_data_demissao = None  # não usado neste ramo
    else:
        ativo = False
        nova_data_demissao = _parse_data(registro.get("dataDemissao"), "dataDemissao")
        nova_data_admissao = None  # não usado neste ramo

    departamento = _garantir_departamento(registro.get("departamento"), resultado)
    secao = _garantir_secao(departamento, registro.get("secao"), resultado)
    centro_custo = _resolver_centro_custo(
        registro.get("codCentroCusto"), registro.get("centroCusto")
    )

    funcionario = (
        Funcionario.objects.select_for_update()
        .filter(unidade_fabril=unidade, codigo_funcionario_erp=codigo)
        .first()
    )

    if funcionario is None:
        funcionario = Funcionario(
            nome=nome,
            codigo_funcionario_erp=codigo,
            unidade_fabril=unidade,
            departamento=departamento,
            secao=secao,
            centro_custo=centro_custo,
            ativo=ativo,
            is_active=ativo,
            username=gerar_username(nome),
        )
        if operacao == "admissao":
            funcionario.data_admissao = nova_data_admissao
        else:
            funcionario.data_demissao = nova_data_demissao
        funcionario.set_unusable_password()
        funcionario.save()

        if operacao == "admissao":
            resultado.funcionarios_criados += 1
        else:
            # Demissão de um código nunca visto localmente: ver a nota no
            # topo do módulo sobre esta lacuna do desenho.
            resultado.funcionarios_criados_inativos += 1
        return

    campos_alterados: list[str] = []

    if funcionario.nome != nome:
        funcionario.nome = nome
        campos_alterados.append("nome")
    if departamento is not None and funcionario.departamento_id != departamento.id:
        funcionario.departamento = departamento
        campos_alterados.append("departamento")
    if secao is not None and funcionario.secao_id != secao.id:
        funcionario.secao = secao
        campos_alterados.append("secao")
    if centro_custo is not None and funcionario.centro_custo_id != centro_custo.id:
        funcionario.centro_custo = centro_custo
        campos_alterados.append("centro_custo")

    tornou_se_inativo = False
    if operacao == "admissao":
        if funcionario.ativo != ativo or funcionario.is_active != ativo:
            funcionario.ativo = ativo
            funcionario.is_active = ativo
            campos_alterados += ["ativo", "is_active"]
        if funcionario.data_admissao != nova_data_admissao:
            funcionario.data_admissao = nova_data_admissao
            campos_alterados.append("data_admissao")
    else:
        tornou_se_inativo = bool(funcionario.ativo)
        if funcionario.ativo or funcionario.is_active:
            funcionario.ativo = False
            funcionario.is_active = False
            campos_alterados += ["ativo", "is_active"]
        if funcionario.data_demissao != nova_data_demissao:
            funcionario.data_demissao = nova_data_demissao
            campos_alterados.append("data_demissao")

    if not campos_alterados:
        return

    funcionario.save(update_fields=campos_alterados)

    if tornou_se_inativo:
        resultado.funcionarios_inativados += 1
    else:
        resultado.funcionarios_atualizados += 1


def _processar_empresa(
    empresa: int,
    operacao: str,
    periodo: str,
    unidade: UnidadeFabril,
    resultado: ResultadoSincronizacaoERP,
) -> None:
    try:
        registros = buscar_funcionarios(empresa=empresa, periodo=periodo, operacao=operacao)
    except ERPIndisponivel as erro:
        if empresa not in resultado.empresas_com_falha:
            resultado.empresas_com_falha.append(empresa)
        resultado.erros.append({"empresa": empresa, "operacao": operacao, "erro": str(erro)})
        return

    if empresa not in resultado.empresas_processadas:
        resultado.empresas_processadas.append(empresa)
    resultado.recebidos += len(registros)

    for posicao, registro in enumerate(registros):
        try:
            with transaction.atomic():
                _persistir_registro(registro, operacao, unidade, resultado)
        except RegistroInvalido as erro:
            resultado.ignorados += 1
            resultado.erros.append(
                {
                    "empresa": empresa,
                    "operacao": operacao,
                    "posicao": posicao,
                    "erro": str(erro),
                }
            )
        except IntegrityError as erro:
            resultado.ignorados += 1
            resultado.erros.append(
                {
                    "empresa": empresa,
                    "operacao": operacao,
                    "posicao": posicao,
                    "erro": f"violação de integridade: {erro}",
                }
            )


def sincronizar(
    *,
    periodo: str | None = None,
    operacoes: tuple[str, ...] = ("admissao", "demissao"),
) -> ResultadoSincronizacaoERP:
    """
    Roda uma rodada completa: admissão de todas as empresas, depois demissão
    de todas as empresas (nunca o contrário, mesmo se `operacoes` vier na
    ordem inversa) — um funcionário nas duas respostas do mês termina
    inativo, como o desenho pede.
    """
    periodo = periodo or mes_corrente()
    resultado = ResultadoSincronizacaoERP(periodo=periodo, operacoes=operacoes)

    unidades_por_empresa = {
        unidade.codigo_empresa_erp: unidade
        for unidade in UnidadeFabril.objects.all()
        if unidade.codigo_empresa_erp is not None
    }

    ordem = [op for op in ("admissao", "demissao") if op in operacoes]

    for operacao in ordem:
        for empresa in EMPRESAS_ERP:
            unidade = unidades_por_empresa.get(empresa)
            if unidade is None:
                if empresa not in resultado.empresas_com_falha:
                    resultado.empresas_com_falha.append(empresa)
                resultado.erros.append(
                    {
                        "empresa": empresa,
                        "operacao": operacao,
                        "erro": "Unidade fabril sem codigo_empresa_erp cadastrado.",
                    }
                )
                continue

            _processar_empresa(empresa, operacao, periodo, unidade, resultado)

    return resultado


__all__ = [
    "EMPRESAS_ERP",
    "ERPIndisponivel",
    "ResultadoSincronizacaoERP",
    "mes_corrente",
    "sincronizar",
]
