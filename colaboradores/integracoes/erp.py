"""
Leitura de admissões e demissões na API de funcionários do ERP.

Este módulo é a **borda** da integração: tudo que é específico do ERP mora
aqui (URL, headers, timeout, SSL, validação do envelope da resposta), e a
saída é a lista bruta de `data` que `colaboradores.sincronizacao_erp` consome.
Trocar o ERP por outra fonte não deveria tocar em nada além deste arquivo —
mesmo papel que `viagens/integracoes/microsoft_graph.py` cumpre para o
Outlook.

Contrato fechado no desenho (docs/superpowers/specs/2026-09-22-...):
    GET {ERP_FUNCIONARIOS_API_URL}?dataAdmissao=AAAAMM   (operação "admissao")
    GET {ERP_FUNCIONARIOS_API_URL}?dataDemissao=AAAAMM   (operação "demissao")
    headers: accept: application/json
             empresa: <código da empresa ERP>
             Authorization: <token cru, sem prefixo Bearer>
Sem paginação — a resposta inteira vem em `data`.
"""

from __future__ import annotations

import json
import os

import requests
import urllib3

# SSL desabilitado é decisão fixa do desenho (o servidor do ERP tem cadeia
# intermediária incompleta), não uma opção de configuração. Sem desligar o
# aviso, cada chamada despejaria um InsecureRequestWarning no log.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PARAMETRO_POR_OPERACAO = {
    "admissao": "dataAdmissao",
    "demissao": "dataDemissao",
}

TIMEOUT_PADRAO_SEGUNDOS = 300


class ERPIndisponivel(Exception):
    """Falha ao falar com a API do ERP (rede, credencial, resposta inválida)."""


def _url() -> str:
    url = os.environ.get("ERP_FUNCIONARIOS_API_URL", "")
    if not url:
        raise ERPIndisponivel(
            "ERP_FUNCIONARIOS_API_URL ausente. Configure no .env."
        )
    return url


def _token() -> str:
    token = os.environ.get("ERP_FUNCIONARIOS_API_TOKEN", "")
    if not token:
        raise ERPIndisponivel(
            "ERP_FUNCIONARIOS_API_TOKEN ausente. Configure no .env."
        )
    return token


def _timeout() -> int:
    bruto = os.environ.get("ERP_FUNCIONARIOS_API_TIMEOUT", "")
    if not bruto:
        return TIMEOUT_PADRAO_SEGUNDOS
    try:
        return int(bruto)
    except ValueError:
        raise ERPIndisponivel(
            f"ERP_FUNCIONARIOS_API_TIMEOUT inválido: '{bruto}'."
        ) from None


def buscar_funcionarios(empresa: int, periodo: str, operacao: str) -> list[dict]:
    """
    Consulta uma empresa/operação/período e devolve a lista bruta de `data`.

    `periodo` é `AAAAMM`. `operacao` é "admissao" ou "demissao" — escolhe o
    parâmetro `dataAdmissao`/`dataDemissao` enviado ao ERP.

    Levanta `ERPIndisponivel` em qualquer falha (config, rede, timeout,
    status HTTP fora de 2xx, corpo que não seja JSON, ou JSON sem `data`
    como lista). O chamador decide se a falha de uma empresa/operação
    interrompe ou não o restante do lote — este cliente não sabe disso.
    """
    parametro = PARAMETRO_POR_OPERACAO.get(operacao)
    if parametro is None:
        raise ERPIndisponivel(f"Operação desconhecida: '{operacao}'.")

    try:
        resposta = requests.get(
            _url(),
            params={parametro: periodo},
            headers={
                "accept": "application/json",
                "empresa": str(empresa),
                "Authorization": _token(),
            },
            timeout=_timeout(),
            verify=False,
        )
    except requests.RequestException as erro:
        raise ERPIndisponivel(
            f"empresa {empresa}, {operacao} {periodo}: falha de conexão — {erro}"
        ) from erro

    if not (200 <= resposta.status_code < 300):
        raise ERPIndisponivel(
            f"empresa {empresa}, {operacao} {periodo}: "
            f"HTTP {resposta.status_code}."
        )

    try:
        payload = resposta.json()
    except (json.JSONDecodeError, ValueError) as erro:
        raise ERPIndisponivel(
            f"empresa {empresa}, {operacao} {periodo}: resposta não é JSON válido."
        ) from erro

    if not isinstance(payload, dict) or "data" not in payload:
        raise ERPIndisponivel(
            f"empresa {empresa}, {operacao} {periodo}: resposta sem campo 'data'."
        )

    dados = payload["data"]
    if not isinstance(dados, list):
        raise ERPIndisponivel(
            f"empresa {empresa}, {operacao} {periodo}: 'data' não é uma lista."
        )

    return dados
