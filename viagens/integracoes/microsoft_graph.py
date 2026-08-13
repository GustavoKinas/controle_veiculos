"""
Leitura das agendas de veículo na Microsoft Graph.

Cada veículo é uma **caixa de recurso** no Outlook (`Veiculo.email_recurso`) e
cada reserva, um evento na agenda dela.

Este módulo é a **borda** da integração: tudo que é específico da Microsoft
mora aqui, e a saída é uma lista de dicionários no formato normalizado que
`services.sincronizar_reservas` consome. Trocar o Graph por outra fonte não
deveria tocar em nada além deste arquivo.

Endpoint usado: `GET /users/{email}/calendar/calendarView`, e não o
`getSchedule` da POC inicial — o calendarView é o único que devolve o `id` do
evento (chave de idempotência do sync) e o `organizer.emailAddress.address`
(chave de junção com o cadastro). Ver docs/PRE_CADASTRO_VIAGENS.md §8.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import requests
from zoneinfo import ZoneInfo

# O Graph converte os horários para este fuso (cabeçalho `Prefer`) e os devolve
# SEM offset — os datetimes resultantes são naive e representam São Paulo.
FUSO = ZoneInfo("America/Sao_Paulo")

# Margem de segurança para não usar um token que expira no meio da chamada.
FOLGA_TOKEN_SEGUNDOS = 300

TIMEOUT_SEGUNDOS = 30


class GraphIndisponivel(Exception):
    """Falha ao falar com a Microsoft Graph (rede, credencial, permissão)."""


def janela_de_consulta(dias: int = 30) -> tuple[str, str]:
    """
    Janela `[hoje 00:00, hoje+dias 00:00)` em horário de São Paulo, no formato
    ISO 8601 com offset que o Graph espera em `startDateTime`/`endDateTime`.

    Calculada na chamada, nunca no import nem no `__init__`: o sync roda em
    laço num processo de longa duração e atravessa a virada do dia.

    Usa `datetime.now(FUSO)` e não `date.today()` — o segundo lê o relógio do
    sistema, e num container em UTC ele já virou o dia seguinte às 21h de
    Brasília, o que faria as reservas de hoje sumirem da janela.
    """
    hoje = datetime.now(FUSO).date()
    inicio = datetime.combine(hoje, time.min, tzinfo=FUSO)
    return inicio.isoformat(), (inicio + timedelta(days=dias)).isoformat()


def _horario(bloco: dict | None) -> datetime | None:
    """
    Converte o bloco `{"dateTime": ..., "timeZone": ...}` em datetime truncado
    no minuto. O Graph manda 7 casas de fração de segundo.
    """
    valor = (bloco or {}).get("dateTime")
    if not valor:
        return None
    return datetime.fromisoformat(valor).replace(second=0, microsecond=0)


def normalizar_evento(evento: dict, email_recurso: str) -> dict | None:
    """
    Traduz um evento do Graph para o formato que o sync consome.

    Devolve `None` para eventos inaproveitáveis (sem id ou sem data), que são
    contados como ignorados em vez de derrubar o lote.

    Formato de saída — é este o contrato entre a borda e o serviço:

        {
            "id_externo":        str,          # id do evento (idempotência)
            "email_recurso":     str,          # minúsculo: chave do veículo
            "solicitante_email": str,          # minúsculo, "" se ausente
            "solicitante_nome":  str,          # texto cru, sem espaços nas pontas
            "data":              date,
            "hora_inicio":       time | None,  # None em evento de dia inteiro
            "hora_fim":          time | None,
            "cancelado":         bool,
        }
    """
    id_externo = evento.get("id")
    inicio = _horario(evento.get("start"))
    if not id_externo or inicio is None:
        return None

    fim = _horario(evento.get("end"))
    dia_inteiro = bool(evento.get("isAllDay"))

    organizador = (evento.get("organizer") or {}).get("emailAddress") or {}
    # O assunto costuma trazer o nome digitado pelo solicitante; o `.strip()`
    # não é cosmético: os assuntos vêm com espaço sobrando no fim, e sem ele
    # qualquer comparação por nome falharia.
    nome = (organizador.get("name") or evento.get("subject") or "").strip()

    return {
        "id_externo": id_externo,
        "email_recurso": email_recurso.strip().lower(),
        "solicitante_email": (organizador.get("address") or "").strip().lower(),
        "solicitante_nome": nome,
        "data": inicio.date(),
        # Dia inteiro grava horário NULO, não 00:00: "sem horário definido" e
        # "sai à meia-noite" são coisas diferentes na agenda do operador.
        "hora_inicio": None if dia_inteiro else inicio.time(),
        "hora_fim": None if dia_inteiro or fim is None else fim.time(),
        "cancelado": bool(evento.get("isCancelled")),
    }


@dataclass
class ResultadoColeta:
    """
    O que a coleta conseguiu trazer — e de onde.

    `caixas_consultadas` é a parte que importa para a correção do sync: só as
    caixas que responderam com sucesso podem ter suas reservas ausentes
    tratadas como canceladas. Uma caixa que falhou volta com a lista vazia, e
    tratar isso como "sumiu tudo" cancelaria reservas legítimas.
    """

    eventos: list[dict] = field(default_factory=list)
    caixas_consultadas: set[str] = field(default_factory=set)
    erros: dict[str, str] = field(default_factory=dict)


class MicrosoftGraphClient:
    """Cliente mínimo do Graph: token com cache e leitura de calendarView."""

    def __init__(self, client_id=None, client_secret=None, token_url=None):
        self.client_id = client_id or os.getenv("CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SECRETY_VALUE", "")
        self.token_url = token_url or os.getenv("URL_MICROSOFT", "")
        self._token: str | None = None
        self._expira_em: datetime | None = None

    # -- autenticação ------------------------------------------------------
    def _obter_token(self) -> str:
        if self._token and self._expira_em and datetime.now() < self._expira_em:
            return self._token

        if not (self.client_id and self.client_secret and self.token_url):
            raise GraphIndisponivel(
                "Credenciais da Microsoft Graph ausentes. Defina CLIENT_ID, "
                "SECRETY_VALUE e URL_MICROSOFT no .env."
            )

        try:
            resposta = requests.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
                timeout=TIMEOUT_SEGUNDOS,
            )
            resposta.raise_for_status()
        except requests.RequestException as erro:
            raise GraphIndisponivel(f"Falha ao obter token: {erro}") from erro

        dados = resposta.json()
        self._token = dados["access_token"]
        self._expira_em = datetime.now() + timedelta(
            seconds=dados["expires_in"] - FOLGA_TOKEN_SEGUNDOS
        )
        return self._token

    # -- leitura -----------------------------------------------------------
    def eventos_da_caixa(self, email_recurso: str, inicio: str, fim: str) -> list[dict]:
        """Eventos brutos de uma caixa de recurso, seguindo a paginação."""
        token = self._obter_token()
        url = (
            "https://graph.microsoft.com/v1.0/"
            f"users/{email_recurso}/calendar/calendarView"
        )
        cabecalhos = {
            "Authorization": f"Bearer {token}",
            "Prefer": 'outlook.timezone="E. South America Standard Time"',
        }
        parametros = {
            "startDateTime": inicio,
            "endDateTime": fim,
            "$select": "id,subject,start,end,organizer,isCancelled,isAllDay,iCalUId",
            "$top": 100,
        }

        eventos: list[dict] = []
        while url:
            try:
                resposta = requests.get(
                    url, headers=cabecalhos, params=parametros,
                    timeout=TIMEOUT_SEGUNDOS,
                )
                resposta.raise_for_status()
            except requests.RequestException as erro:
                raise GraphIndisponivel(f"{email_recurso}: {erro}") from erro

            dados = resposta.json()
            eventos.extend(dados.get("value", []))
            url = dados.get("@odata.nextLink")
            # O nextLink já traz os parâmetros embutidos.
            parametros = None

        return eventos

    def coletar(self, emails_recurso, dias: int = 30) -> ResultadoColeta:
        """
        Lê todas as caixas informadas e devolve os eventos já normalizados.

        Falha numa caixa **não** derruba as outras: o erro é registrado e a
        caixa fica de fora de `caixas_consultadas`, o que impede o sync de
        cancelar as reservas dela por engano.
        """
        inicio, fim = janela_de_consulta(dias)
        resultado = ResultadoColeta()

        for email in emails_recurso:
            try:
                brutos = self.eventos_da_caixa(email, inicio, fim)
            except GraphIndisponivel as erro:
                resultado.erros[email] = str(erro)
                continue

            resultado.caixas_consultadas.add(email.strip().lower())
            for bruto in brutos:
                normalizado = normalizar_evento(bruto, email)
                if normalizado is not None:
                    resultado.eventos.append(normalizado)

        return resultado


def periodo_da_janela(dias: int = 30) -> tuple[date, date]:
    """A mesma janela da consulta, como datas — é o que o sync usa para saber
    quais reservas existentes estão no escopo desta rodada."""
    hoje = datetime.now(FUSO).date()
    return hoje, hoje + timedelta(days=dias)
