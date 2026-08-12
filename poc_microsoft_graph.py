import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
        "inovacao@grupoflexivel.com.br"
        ]

EMAIL_AUTOMACAO='automacao@grupoflexivel.com.br'

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

for sala in SALAS:

    agenda = graph.get_room_reservations(
        sala,
        start_datetime="2026-08-12T00:00:00-03:00",
        end_datetime="2026-08-13T00:00:00-03:00",
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
        print(f"Início: {inicio:%d/%m/%Y %H:%M}" if inicio else "Início: não informado")
        print(f"Fim: {fim:%d/%m/%Y %H:%M}" if fim else "Fim: não informado")
        print(f"  (objetos: {inicio!r} ate {fim!r})")
        print(f"Event ID: {evento.get('id')}")
        print("-" * 80)


