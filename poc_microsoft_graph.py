import requests
import os
from dotenv import load_dotenv
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID","Client_ID não identificado")
TENANT_ID = os.getenv("TENANT_ID","TENANT_ID não identificado")
SECRETY_VALUE = os.getenv("SECRETY_VALUE", "Secrety_Value não identificado")
URL = os.getenv("URL_MICROSOFT", "URL não identificada")

SALAS = ["autenticidade@grupoflexivel.com.br",
        "integridade@grupoflexivel.com.br",
        "humanismo@grupoflexivel.com.br",
        "sustentabilidade@grupoflexivel.com.br",
        "produtividade@grupoflexivel.com.br",
        "integracao@grupoflexivel.com.br",
        "eficiencia@grupoflexivel.com.br",
        "inovacao@grupoflexivel.com.br",
        "cronossxk9g85@puflexivel.com.br",
        "cronossxb9b09@puflexivel.com.br",
        "stradarln1j19@puflexivel.com.br"
        ]

EMAIL_AUTOMACAO='automacao@grupoflexivel.com.br'

FUSO = ZoneInfo("America/Sao_Paulo")


def janela_de_consulta(dias: int = 1) -> tuple[str, str]:
    """
    Janela [hoje 00:00, hoje+dias 00:00) em horário de São Paulo, no formato
    ISO 8601 com offset — que é como o Graph espera receber start/endDateTime.

    Duas decisões que parecem detalhe e não são:

    - **Calculada na chamada**, nunca guardada no `__init__` nem no import. Um
      processo de longa duração (o scheduler, que roda em laço) atravessa a
      virada do dia; um valor congelado passaria a consultar ontem para
      sempre, sem erro e sem log.
    - **`datetime.now(FUSO)` e não `date.today()`.** O segundo usa o relógio
      do sistema: num container em UTC, das 21h de Brasília em diante ele já
      virou o dia seguinte, e as reservas de hoje sumiriam da janela.

    O offset sai do `zoneinfo`, não de um literal "-03:00" — hoje os dois
    coincidem (o Brasil não tem horário de verão desde 2019), mas a constante
    sobreviveria à premissa que a justifica.
    """
    hoje = datetime.now(FUSO).date()
    inicio = datetime.combine(hoje, time.min, tzinfo=FUSO)
    return inicio.isoformat(), (inicio + timedelta(days=dias)).isoformat()


class MicrosoftGraphClient:

    def __init__(self):
        self.token = None
        self.token_expiracao = None

    def get_access_token(self):
        #Se já temos um token e ele ainda é válido (com margem de 5 minutos de folga), reutiliza!
        if self.token and self.token_expiracao and datetime.now() < self.token_expiracao:
            print('Reutilizado token existente em cache...')
            return self.token

        print("Token expirado ou inexistente. Solicitando novo token...")

        url = URL
        
        data = {
            "client_id":CLIENT_ID,
            "client_secret":SECRETY_VALUE,
            "scope":"https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
            }

        response = requests.post(url, data=data, timeout=30)
        response.raise_for_status()

        self.token = response.json()["access_token"]

        expires_in = response.json()["expires_in"]
        self.token_expiracao = datetime.now() + timedelta(
        seconds=expires_in - 300
    )



        return self.token
    
    def get_room_schedule(self):
        token = self.get_access_token()

        url = (
            f"https://graph.microsoft.com/v1.0/users/{EMAIL_AUTOMACAO}/calendar/getSchedule"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": 'outlook.timezone="E. South America Standard Time"'
        }

        payload = {
            "schedules":SALAS,
        "startTime": {
            "dateTime": "2026-08-12T08:00:00",
            "timeZone": "E. South America Standard Time"
        },
        "endTime": {
            "dateTime": "2026-08-12T18:00:00",
            "timeZone": "E. South America Standard Time"
        },
        "availabilityViewInterval": 30
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()["value"],token

    def get_room_reservations(self,room_email,start_datetime,end_datetime):

        token = self.get_access_token()

        url = (
            "https://graph.microsoft.com/v1.0/"
            f"users/{room_email}/calendar/calendarView"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Prefer": 'outlook.timezone="E. South America Standard Time"',
        }

        params = {
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
            "$select": (
                "id,"
                "subject,"
                "start,"
                "end,"
                "organizer,"
                "isCancelled,"
                "isAllDay,"
                "iCalUId"
            ),
        }

        eventos = []

        while url:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            eventos.extend(data.get("value", []))

            url = data.get("@odata.nextLink")

            # O nextLink já contém os parâmetros
            params = None

        return eventos

def horario_do_evento(bloco: dict | None) -> datetime | None:
    """
    Converte o bloco {"dateTime": ..., "timeZone": ...} do Graph em `datetime`
    truncado no minuto (segundos e microssegundos zerados).

    Dois detalhes do formato do Graph:

    - o valor vem com 7 casas de fração de segundo
      ("2026-08-12T11:00:00.0000000"), daí o corte;
    - vem **sem offset**, porque o horário já foi convertido para o fuso
      pedido no cabeçalho `Prefer`. O datetime resultante é *naive* e
      representa horário de São Paulo — nunca o trate como UTC.

    Para alimentar `ReservaViagem`: `.date()` vai em `data` e `.time()` em
    `hora_inicio` / `hora_fim`.
    """
    valor = (bloco or {}).get("dateTime")
    if not valor:
        return None
    return datetime.fromisoformat(valor).replace(second=0, microsecond=0)


def descreve_periodo(evento: dict) -> str:
    """
    Texto do período de um evento, tratando o caso de dia inteiro.

    O `end` de um evento de dia inteiro é **exclusivo**: um bloqueio de um
    único dia vem como 13/08 00:00 → 14/08 00:00. Exibir isso cru sugere que
    o carro só volta na madrugada seguinte, então recuamos um dia para mostrar
    o último dia efetivamente ocupado.

    Para alimentar `ReservaViagem`, um evento de dia inteiro deve gravar
    `hora_inicio`/`hora_fim` nulos (o modelo já os aceita) em vez de 00:00 —
    "sem horário definido" e "sai à meia-noite" são coisas diferentes.
    """
    inicio = horario_do_evento(evento.get("start"))
    fim = horario_do_evento(evento.get("end"))

    if inicio is None or fim is None:
        return "não informado"

    if not evento.get("isAllDay"):
        return f"{inicio:%d/%m/%Y %H:%M} até {fim:%d/%m/%Y %H:%M}"

    ultimo_dia = (fim - timedelta(days=1)).date()
    if ultimo_dia <= inicio.date():
        return f"Dia inteiro — {inicio:%d/%m/%Y}"
    return f"Dia inteiro — {inicio:%d/%m/%Y} a {ultimo_dia:%d/%m/%Y}"


def formata_retorno_json(json):
    for sala in json:
        nome = sala["scheduleId"]
        nome = nome.split("@")[0].capitalize()

        print(f"Sala: {nome}")

        reservas = sala["scheduleItems"]

        for reserva in reservas:

            requerente = reserva.get("subject","Sem assunto/Requerente")
            inicio_reserva = datetime.fromisoformat(reserva["start"]["dateTime"])
            fim_reserva = datetime.fromisoformat(reserva["end"]["dateTime"])

            hora_inicio = inicio_reserva.strftime("%H:%M")
            hora_fim = fim_reserva.strftime("%H:%M")

            print(f" - {requerente} | Início {hora_inicio} | Fim: {hora_fim}")
        print('------'*20)


graph = MicrosoftGraphClient()

# A janela é calculada aqui, no ponto de uso — e `dias` já é o parâmetro que
# a fase 4 vai subir para 30.
inicio_janela, fim_janela = janela_de_consulta(dias=1)
print(f"Janela consultada: {inicio_janela} a {fim_janela}")

for sala in SALAS:

    agenda = graph.get_room_reservations(
        sala,
        start_datetime=inicio_janela,
        end_datetime=fim_janela,
    )

    print()
    print("=" * 80)
    print(f"SALA: {sala}")
    print("=" * 80)

    if not agenda:
        print("Nenhuma reserva encontrada.")
        continue

    for evento in agenda:

        if evento.get("isCancelled"):
            continue

        organizer = evento.get("organizer") or {}
        email_address = organizer.get("emailAddress") or {}

        nome = email_address.get("name", "Não identificado")
        email = email_address.get("address", "Não identificado")

        inicio = horario_do_evento(evento.get("start"))
        fim = horario_do_evento(evento.get("end"))

        print(f"Assunto: {evento.get('subject')}")
        print(f"Organizador: {nome}")
        print(f"E-mail: {email}")
        print(f"Período: {descreve_periodo(evento)}")
        print(f"  (objetos: {inicio!r} ate {fim!r})")
        print(f"Event ID: {evento.get('id')}")
        print("-" * 80)


