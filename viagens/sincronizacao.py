"""
Orquestração do sync com o Outlook.

A integração tem duas metades que não se conhecem — `integracoes.microsoft_graph`
fala HTTP e `services.sincronizar_reservas` conhece as regras do banco — e
alguém precisa juntá-las. Até a fase 4 esse alguém era o management command.

Agora existem **dois** disparadores (o comando e o botão da agenda), então a
cola virou este módulo. Se ela tivesse sido copiada para a view, uma correção
de regra passaria a exigir lembrar dos dois lugares.

Mora fora de `services.py` de propósito: aquele módulo não importa a
integração, e é isso que permite testar todas as regras de sincronização sem
mock de HTTP.
"""

from dataclasses import dataclass, field

from django.db import transaction

from .integracoes.microsoft_graph import (
    GraphIndisponivel,
    MicrosoftGraphClient,
    janela_de_consulta,
    periodo_da_janela,
)
from .models import Veiculo
from .services import sincronizar_reservas

JANELA_PADRAO_DIAS = 30


class SemCaixasCadastradas(Exception):
    """Nenhum veículo ativo tem caixa de recurso — não há o que consultar."""


@dataclass
class ResultadoSincronizacao:
    """O que aconteceu numa rodada, para o comando e a tela relatarem."""

    resumo: dict[str, int] = field(default_factory=dict)
    erros: dict[str, str] = field(default_factory=dict)
    caixas_consultadas: set[str] = field(default_factory=set)
    caixas_pedidas: int = 0
    total_eventos: int = 0
    janela: tuple[str, str] = ("", "")
    dry_run: bool = False

    @property
    def houve_falha_parcial(self) -> bool:
        """Alguma caixa não respondeu, mas outras sim."""
        return bool(self.erros)

    @property
    def alterou_algo(self) -> bool:
        return any(self.resumo.get(chave) for chave in ("criadas", "atualizadas", "canceladas", "reabertas"))

    def descrever(self) -> str:
        """Uma linha de resumo, para mensagem de tela."""
        partes = [
            f"{self.resumo.get('criadas', 0)} criada(s)",
            f"{self.resumo.get('atualizadas', 0)} atualizada(s)",
            f"{self.resumo.get('canceladas', 0)} cancelada(s)",
        ]
        if self.resumo.get("reabertas"):
            partes.append(f"{self.resumo['reabertas']} reaberta(s)")
        return ", ".join(partes)


def caixas_de_recurso() -> list[str]:
    """
    Caixas a consultar: só as de veículo ativo cadastrado.

    Cada caixa custa uma requisição HTTP; consultar uma agenda cujo veículo o
    sistema ignoraria depois é desperdício puro.
    """
    return list(
        Veiculo.objects.filter(ativo=True)
        .exclude(email_recurso="")
        .values_list("email_recurso", flat=True)
    )


def executar_sincronizacao(
    *, dias: int = JANELA_PADRAO_DIAS, dry_run: bool = False
) -> ResultadoSincronizacao:
    """
    Roda uma rodada completa: consulta o Graph e aplica no banco.

    `dry_run` executa o serviço **de verdade** dentro de uma transação e faz
    rollback, em vez de simular. É o que torna o número exato, inclusive o de
    cancelamentos — uma simulação a seco só chegaria lá reimplementando as
    regras, e aí estaria testando a cópia, não o original.

    Levanta `SemCaixasCadastradas` se não houver o que consultar e
    `GraphIndisponivel` se a credencial faltar ou for recusada. Falha de uma
    caixa específica **não** levanta: fica em `erros`, e as demais seguem.
    """
    if dias < 1:
        raise ValueError("A janela precisa ser de pelo menos 1 dia.")

    caixas = caixas_de_recurso()
    if not caixas:
        raise SemCaixasCadastradas(
            "Nenhum veículo ativo com caixa de recurso cadastrada. "
            "Preencha o e-mail de recurso do veículo antes de sincronizar."
        )

    cliente = MicrosoftGraphClient()
    coleta = cliente.coletar(caixas, dias=dias)

    data_inicio, data_fim = periodo_da_janela(dias)
    argumentos = {
        "eventos": coleta.eventos,
        "caixas_consultadas": coleta.caixas_consultadas,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
    }

    if dry_run:
        with transaction.atomic():
            resumo = sincronizar_reservas(**argumentos)
            transaction.set_rollback(True)
    else:
        resumo = sincronizar_reservas(**argumentos)

    return ResultadoSincronizacao(
        resumo=resumo,
        erros=dict(coleta.erros),
        caixas_consultadas=set(coleta.caixas_consultadas),
        caixas_pedidas=len(caixas),
        total_eventos=len(coleta.eventos),
        janela=janela_de_consulta(dias),
        dry_run=dry_run,
    )


__all__ = [
    "GraphIndisponivel",
    "JANELA_PADRAO_DIAS",
    "ResultadoSincronizacao",
    "SemCaixasCadastradas",
    "executar_sincronizacao",
]
