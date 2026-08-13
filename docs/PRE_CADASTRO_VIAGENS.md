# Pré-cadastro de viagens (agenda) — desenho técnico

> **Status:** fases 1 e 2 **implementadas** (modelo, admin, mock, agenda).
> Fases 3 a 5 pendentes. Os esboços de código das seções 6 e 8 ainda são
> propostas.
>
> Documento de contexto: serve para retomar o trabalho em outra sessão e para
> ser reenviado como contexto a modelos de LLM. Complementa o
> [DEVELOPMENT.md](../DEVELOPMENT.md) (estado atual do sistema) e o
> [ESTUDO.md](../ESTUDO.md) (roteiro de estudo e defeitos conhecidos).

---

## 1. Objetivo

Hoje a portaria lança cada viagem do zero: funcionário, data, veículo, KM
inicial e KM final. O objetivo é receber **pré-cadastros** (reservas de
veículo) e reduzir o trabalho do operador a preencher apenas a quilometragem.

A origem final dos pré-cadastros será o **Outlook, via Microsoft Graph API**
(reservas de veículo como recursos). Nesta etapa trabalhamos com **dados
mockados**, mas a fronteira da integração já é definida (seção 8) para que o
cliente do Graph entre depois sem alterar nada do resto.

**Fora de escopo nesta etapa:** cliente do Graph, autenticação OAuth da
aplicação, detecção de conflito de reserva (mesmo veículo, mesmo horário),
notificações.

---

## 2. Contexto necessário do sistema atual

Resumo do que já existe e que este desenho não pode quebrar:

- **`Viagem`** (`viagens/models.py`) é a fonte da verdade do rateio:
  `funcionario`, `veiculo`, `data`, `km_inicial`, `km_final`,
  `km_percorrida` (calculado no `save()`), `centro_custo` (congelado a partir
  do funcionário), `fechamento?`, `lancada_por?`.
- **Validação em três camadas**: formulário (o que a tela oferece),
  `Viagem.clean()` (regras de domínio: piso/teto do hodômetro, data futura) e
  banco (`CheckConstraint km_final > km_inicial`, `NOT NULL` em `veiculo`).
- **`Veiculo.km_atual`** é recalculado por `services.atualizar_km_veiculo()`
  no `save()` da viagem e num `post_delete`.
- **`confirmar_fechamento()` é irreversível**: consome toda viagem do período
  com `fechamento IS NULL`, grava o snapshot do rateio e marca as viagens.
  Uma viagem consumida **nunca** entra em outro fechamento.
- Stack: Django 6.0.5, PostgreSQL, templates server-side com Tailwind (CDN) +
  DaisyUI + **htmx**, sem build de JS. Testes em `viagens/tests.py`
  (`python manage.py test viagens`).

---

## 3. Decisão de arquitetura: reserva **não** é viagem

A alternativa óbvia — tornar `km_inicial`/`km_final` nulos e criar `Viagem`
"pela metade" — **foi descartada**. Consequências concretas:

- `confirmar_fechamento()` consumiria as viagens pendentes do período com 0 km
  e as marcaria como fechadas. Como o fechamento é irreversível, **a viagem
  seria perdida** (nunca mais poderia ser lançada ou rateada);
- `calcular_rateio()` somaria zeros e distorceria os percentuais por centro de
  custo;
- `validar_quilometragem()` e `atualizar_km_veiculo()` pressupõem km presente;
- toda query de `services.py` passaria a exigir um filtro de status — e a
  omissão desse filtro em um único ponto reintroduz os problemas acima.

A separação é conceitual, e é a mesma filosofia do centro de custo congelado:

> **`ReservaViagem` é uma intenção. `Viagem` é um fato consumado.**

Reserva pode ser cancelada, remarcada ou ignorada; nada disso pode tocar no
financeiro. O lançamento avulso (`/viagens/lancar/`) continua existindo sem
alteração — viagem não planejada é realidade em qualquer portaria.

---

## 4. Modelagem

Novo modelo em `viagens/models.py` (esboço):

```python
class ReservaViagem(models.Model):
    """Pré-cadastro de viagem. Hoje mock, futuramente Outlook via Graph."""

    class Status(models.TextChoices):
        PENDENTE  = "pendente",  "Pendente"
        LANCADA   = "lancada",   "Lançada"
        CANCELADA = "cancelada", "Cancelada"

    class Origem(models.TextChoices):
        MANUAL  = "manual",  "Manual"
        OUTLOOK = "outlook", "Outlook"

    funcionario = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.PROTECT,
                                    related_name="reservas")
    veiculo     = models.ForeignKey(Veiculo, on_delete=models.PROTECT,
                                    related_name="reservas")
    data        = models.DateField()
    hora_inicio = models.TimeField(null=True, blank=True)
    hora_fim    = models.TimeField(null=True, blank=True)
    titulo      = models.CharField(max_length=200, blank=True, default="")
    destino     = models.CharField(max_length=200, blank=True, default="")

    origem      = models.CharField(max_length=20, choices=Origem.choices,
                                   default=Origem.MANUAL)
    id_externo  = models.CharField(max_length=255, blank=True, default="")

    status      = models.CharField(max_length=20, choices=Status.choices,
                                   default=Status.PENDENTE)

    # Rastreabilidade: qual lançamento nasceu desta reserva.
    viagem      = models.OneToOneField("Viagem", on_delete=models.SET_NULL,
                                       null=True, blank=True,
                                       related_name="reserva")

    criada_em     = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reserva de Viagem"
        verbose_name_plural = "Reservas de Viagem"
        db_table = "reserva_viagem"
        ordering = ["data", "hora_inicio", "id"]
        indexes = [models.Index(fields=["data", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["origem", "id_externo"],
                condition=~models.Q(id_externo=""),
                name="uniq_reserva_por_evento_externo",
            )
        ]
```

### Por que cada decisão

**`id_externo` + `UniqueConstraint` parcial** — torna a sincronização futura
*idempotente*: rodar o sync duas vezes não duplica reservas. A condição
`~Q(id_externo="")` libera as reservas manuais, que não têm id externo.
Nascer com isso é barato; adicionar depois, com duplicatas já no banco, não é.

**`status` explícito, mesmo havendo a FK `viagem`** — em `Viagem.fechamento` o
estado é derivado da FK (`fechada = fechamento_id is not None`), porque só há
dois estados. Aqui são **três**, e "cancelada" não é representável pela
ausência de viagem. A FK dá rastreabilidade; o `status` carrega a máquina de
estados.

**O que a reserva NÃO tem:** quilometragem, centro de custo, `lancada_por`.
Tudo isso pertence ao fato, não à intenção.

**`índice ("data", "status")`** — a consulta do calendário é sempre "reservas
deste intervalo que não estão canceladas".

---

## 5. Fluxo de telas

O trabalho da portaria não é navegar um calendário: é **zerar a lista de
hoje**. Por isso a agenda abre no dia corrente, com o mês abaixo como
panorama.

```
/viagens/agenda/            (sugestão: nova tela inicial no lugar de lancar_viagem)

  [ ← Agosto 2026 → ]                              [ Hoje ]

  ┌── HOJE, 10/08 ──────────────────────── 3 pendentes ──┐
  │  08:00  ADRIANA NASS      RLN1J19 · STRADA           │
  │         Visita cliente X                [ Lançar KM ]│
  │  09:30  ADRIANO BODNAR    SXB9B09 · CRONOS           │
  │                                         [ Lançar KM ]│
  └──────────────────────────────────────────────────────┘

  Grade do mês (cards compactos, visão de supervisão)
```

1. Operador clica em **Lançar KM** → `/viagens/reservas/<pk>/lancar/`
2. Tela em "modo reserva": colaborador, veículo e data como **texto fixo**
   (não como campos de formulário). Só KM inicial e final são editáveis.
3. Ao salvar: cria a `Viagem`, vincula à reserva, marca `LANCADA` — tudo numa
   transação.
4. Redireciona **de volta para a agenda**, com toast do tipo
   *"Viagem de ADRIANA NASS lançada (740 km) — restam 2 pendentes"*.

O passo 4 é o que muda a rotina: o operador volta para a fila, não para um
formulário vazio.

### URLs novas

| URL | Nome | Descrição |
|---|---|---|
| `/viagens/agenda/` | `agenda` | Calendário; aceita `?ano=&mes=&dia=` |
| `/viagens/reservas/<pk>/lancar/` | `lancar_reserva` | Conclusão da reserva |

---

## 6. Ponto crítico: nunca confie no POST para os dados da reserva

Se `funcionario`, `veiculo` e `data` forem renderizados como campos `hidden`
ou `disabled`, qualquer um edita o HTML e lança a viagem em nome de outra
pessoa, em outro carro. (`disabled` sequer é enviado no POST — o Django veria
o campo vazio e recusaria.)

O servidor relê a reserva e copia os valores dela. O usuário só contribui com
a quilometragem:

```python
# esboço
class ConcluirReservaForm(forms.Form):
    km_inicial = forms.IntegerField(min_value=0)
    km_final   = forms.IntegerField(min_value=0)


class LancarReservaView(LoginRequiredMixin, View):
    def post(self, request, pk):
        form = ConcluirReservaForm(request.POST)
        if not form.is_valid():
            return render(...)

        with transaction.atomic():
            reserva = get_object_or_404(
                ReservaViagem.objects.select_for_update()
                .select_related("funcionario", "veiculo"),
                pk=pk, status=ReservaViagem.Status.PENDENTE,
            )
            viagem = Viagem(
                funcionario=reserva.funcionario,   # ← da reserva, não do POST
                veiculo=reserva.veiculo,
                data=reserva.data,
                km_inicial=form.cleaned_data["km_inicial"],
                km_final=form.cleaned_data["km_final"],
                lancada_por=request.user,
            )
            viagem.full_clean()      # piso, teto, data futura continuam valendo
            viagem.save()

            reserva.viagem = viagem
            reserva.status = ReservaViagem.Status.LANCADA
            reserva.save(update_fields=["viagem", "status", "atualizada_em"])
```

Três detalhes que não podem ser perdidos:

- **`full_clean()` explícito.** Sem ModelForm não existe `_post_clean()`, e
  `save()` não valida. Os erros de `ValidationError` precisam ser capturados e
  devolvidos ao formulário (`form.add_error`), senão viram erro 500.
- **`status=PENDENTE` no lookup.** Se o operador abrir a mesma reserva em duas
  abas, a segunda dá 404 em vez de criar viagem duplicada.
- **`select_for_update()` dentro da transação**, mesmo padrão do
  `confirmar_fechamento()`, para o caso de dois operadores simultâneos.

---

## 7. Calendário sem dependência nova

Coerente com a decisão 3.6 do DEVELOPMENT.md (nada de biblioteca externa
quando o problema é simples): grade renderizada no servidor, navegação por
htmx — o mesmo padrão de `viagens/templates/viagens/partials/_rateio.html` e
`colaboradores/templates/partials/_tabela_colaboradores.html`.

**Na view — uma query para o mês inteiro**, agrupada em Python (uma query por
dia seriam 30+ queries: o mesmo N+1 já pego duas vezes neste projeto):

```python
import calendar
from collections import defaultdict

semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(ano, mes)
primeiro, ultimo = semanas[0][0], semanas[-1][-1]

reservas = (
    ReservaViagem.objects
    .filter(data__range=(primeiro, ultimo))
    .exclude(status=ReservaViagem.Status.CANCELADA)
    .select_related("funcionario", "veiculo")
    .order_by("hora_inicio", "id")
)

agrupadas = defaultdict(list)
for reserva in reservas:
    agrupadas[reserva.data].append(reserva)

# O template Django não acessa dict por chave dinâmica: monte listas prontas.
semanas_render = [[(dia, agrupadas.get(dia, [])) for dia in semana]
                  for semana in semanas]
```

**No template**, `grid grid-cols-7` puro, com o bloco isolado em
`viagens/templates/viagens/partials/_calendario.html` para o htmx trocar:

```html
<div id="calendario" class="hidden sm:grid grid-cols-7 gap-px bg-base-300">
  {% for semana in semanas_render %}
    {% for dia, reservas_do_dia in semana %}
      <div class="min-h-28 bg-base-100 p-1 {% if dia.month != mes %}opacity-40{% endif %}">
        <span class="text-xs">{{ dia.day }}</span>
        {% for reserva in reservas_do_dia %}
          <a href="{% url 'lancar_reserva' reserva.pk %}"
             class="badge badge-sm w-full justify-start truncate">
            {{ reserva.hora_inicio|time:"H:i" }} {{ reserva.veiculo.placa }}
          </a>
        {% endfor %}
      </div>
    {% endfor %}
  {% endfor %}
</div>
```

Navegação de mês: `hx-get="?ano=…&mes=…" hx-target="#calendario"
hx-push-url="true"`.

**Mobile:** grade de 7 colunas é ilegível em celular. `hidden sm:grid` na
grade e uma lista vertical `sm:hidden` dos próximos dias.

**Cuidado com o comentário de template:** `{# … #}` é de **uma linha só**; para
várias linhas, `{% comment %}…{% endcomment %}`. Um `{# #}` quebrado em duas
linhas vaza o texto para o HTML.

---

## 8. Fronteira da integração (definir agora, custo zero)

O mock e o futuro cliente do Graph chamam **a mesma função**. Todo código
específico da Microsoft fica na borda, traduzindo para este formato:

```python
# viagens/services.py
def sincronizar_reservas(eventos: list[dict]) -> dict:
    """
    Faz upsert de reservas a partir de eventos já normalizados.
    Idempotente: a chave é (origem, id_externo).
    Retorna um resumo {"criadas": n, "atualizadas": n, "ignoradas": n}.
    """
```

Payload normalizado **como ficou implementado** (`normalizar_evento`):

```python
{
    "id_externo":        "AAMkAG...",                    # event id — idempotência
    "email_recurso":     "autenticidade@empresa.com",    # minúsculo — chave do veículo
    "solicitante_email": "fulano@grupoflexivel.com.br",  # minúsculo, "" se ausente
    "solicitante_nome":  "Fulano de Tal",                # texto cru, já com .strip()
    "data":              date(2026, 8, 10),
    "hora_inicio":       time(8, 0),                     # None em evento de dia inteiro
    "hora_fim":          time(12, 0),
    "cancelado":         False,
}
```

A chave do veículo é o **`email_recurso`**, não a placa: é o `scheduleId` que o
Graph devolve, e a placa não existe do lado da Microsoft.

Regras do upsert a definir na implementação: evento cancelado no Outlook →
`status=CANCELADA` (mas **não** mexer na reserva já `LANCADA`, o fato
aconteceu); evento remarcado → atualizar data/hora apenas se ainda
`PENDENTE`.

### O que a POC revelou (e mudou no desenho)

`poc_microsoft_graph.py` usa **`POST /users/{conta}/calendar/getSchedule`** com
a lista de caixas de recurso. O retorno real, por sala:

```
scheduleId: "autenticidade@grupoflexivel.com.br"
scheduleItems:
  - subject: "Tamara Suelen Köpp "      ← nome digitado, texto livre
    start/end: dateTime + timeZone
  - subject: ausente em algumas salas   ← vira "Sem assunto/Requerente"
```

Três consequências, todas já refletidas no código das fases 1–2:

1. **O solicitante não vem estruturado.** `getSchedule` devolve apenas o
   *assunto* do evento — nome digitado à mão, com acentos, espaços sobrando e,
   em várias salas, ausente. Por isso `ReservaViagem.funcionario` é
   **opcional** e existe o campo `solicitante_nome` com o texto cru. O
   casamento com o cadastro será por normalização de nome
   (`colaboradores.forms.normalizar_texto`), sempre com margem de erro — o
   operador resolve o que sobrar, na tela.
2. **Não há id de evento.** `getSchedule` não devolve `id`, então não dá para
   fazer upsert idempotente com ele. **Recomendação para a fase 5:** trocar
   para `GET /users/{emailDoRecurso}/calendarView?startDateTime=…&endDateTime=…`,
   que devolve o evento completo — `id`, `organizer.emailAddress.address`,
   `subject`, `start`, `end`, `isCancelled`. Resolve o item 1 **e** o 2 de uma
   vez, ao custo de uma chamada por veículo e da permissão de aplicação
   `Calendars.Read` nas caixas de recurso.
3. **A chave do veículo é o `scheduleId`.** Já implementado:
   `Veiculo.email_recurso`, único entre os preenchidos.

### Chave do funcionário — implementado

Usamos o campo **`email` nativo** do `AbstractUser`. As três exigências abaixo
**já estão no código**: constraint parcial em `Funcionario.Meta`, normalização
no `Funcionario.save()` e o campo exposto em `CadastroFuncionario`.

Falta apenas o **preenchimento** dos cadastros existentes — enquanto o e-mail
estiver vazio, a reserva importada fica sem colaborador identificado (o que a
agenda já sinaliza) e o operador escolhe na hora de lançar. O
`ReservaViagem.solicitante_email` guarda o e-mail do organizador mesmo quando
o casamento falha, então dá para reconciliar depois com a chave confiável em
vez de tentar casar por nome.

1. **Unicidade parcial.** `AbstractUser.email` não é único. Sem isso, dois
   colaboradores com o mesmo e-mail fazem uma reserva desaparecer
   silenciosamente do mapa em memória:

   ```python
   # colaboradores/models.py, Funcionario.Meta
   constraints = [
       models.UniqueConstraint(
           fields=["email"],
           condition=~models.Q(email=""),
           name="uniq_funcionario_por_email",
       )
   ]
   ```

2. **Normalização em caixa baixa.** O Graph devolve o e-mail com a grafia do
   Active Directory (`Jacson.Maia@…` hoje, `jacson.maia@…` amanhã) e o `IN`
   do Postgres é *case-sensitive* — o sync não casaria ninguém, sem erro
   nenhum. Normalizar nas duas pontas: `self.email = self.email.strip().lower()`
   no `Funcionario.save()` **e** `.lower()` nos e-mails vindos da API.

3. **Expor o campo no cadastro.** `CadastroFuncionario`
   (`colaboradores/forms.py`) precisa incluir `email` na lista de campos.

---

## 8.1 Algoritmo do sync (revisado)

**Janela: hoje até +30 dias.** A janela não é detalhe de configuração — é o
que torna possível detectar eventos excluídos (passo 5).

```
1. Mapa de veículos            {email_recurso.lower(): Veiculo}   1 query
   → só as caixas com veículo cadastrado entram no passo 2.

2. Para cada caixa de recurso: GET /users/{email}/calendarView
   ?startDateTime=hoje&endDateTime=hoje+30d
   → try/except por caixa: um 403 numa sala não pode derrubar o sync inteiro.
   → normalizar: id, organizer.email.lower(), subject.strip(),
     start/end → date + time (naive, horário de São Paulo).

3. Mapa de funcionários        {email.lower(): Funcionario}       1 query
   Funcionario.objects.filter(email__in=emails_do_payload)

4. Mapa de reservas existentes {id_externo: ReservaViagem}        1 query
   ReservaViagem.objects.filter(origem=OUTLOOK, id_externo__in=ids_do_payload)

5. Diferença em memória, aplicada em três grupos:
   - id_externo novo                     → criar (status=PENDENTE)
   - id_externo conhecido e PENDENTE     → atualizar data/hora/veículo/solicitante
   - id_externo conhecido e LANCADA      → NÃO TOCAR
   - isCancelled=true e PENDENTE         → status=CANCELADA
   - PENDENTE, origem=OUTLOOK, data na janela, ausente do payload
                                         → status=CANCELADA  (evento excluído)

6. Gravar em transaction.atomic() — bulk_create + bulk_update, ou
   update_or_create em laço enquanto o volume for pequeno.
```

### Regras de estado (o que o sync pode e não pode fazer)

| Estado atual | Evento no Outlook | Ação |
|---|---|---|
| `PENDENTE` | alterado | atualiza data, hora, veículo, solicitante |
| `PENDENTE` | `isCancelled` ou ausente | `CANCELADA` |
| `LANCADA` | qualquer coisa | **nada** — a viagem aconteceu, o passado não se reescreve |
| `CANCELADA` | reapareceu | volta para `PENDENTE` |

### Duas armadilhas de identidade

**A identidade da reserva é o `id_externo`, nunca a combinação
(veículo, solicitante, período).** Uma reunião remarcada de 10h para 14h
mantém o mesmo `id` e muda o período: com chave natural, o sync entenderia
"sumiu uma, nasceu outra", perderia o vínculo e duplicaria o registro.

**Evento excluído não vem marcado — some.** `isCancelled: true` só aparece
para reunião *cancelada*; evento *excluído* simplesmente não está na resposta.
Daí a regra dos "ausentes na janela".

### Colaborador não encontrado

`funcionario = None` e `solicitante_nome` com o texto cru. **Nunca criar um
"funcionário genérico":** `Viagem.save()` copia o centro de custo do
funcionário, então todo km lançado por um genérico seria rateado para o centro
de custo dele — dinheiro atribuído ao lugar errado, com cara de dado legítimo.
A agenda já sinaliza o caso, e o operador escolhe o colaborador na fase 3.

---

## 8.2 Execução em produção (Docker no Ubuntu)

Um serviço a mais no `docker-compose.yml`, reaproveitando a mesma imagem:

```yaml
  scheduler:
    build: .
    container_name: controle_veiculos_scheduler
    # Anula o ENTRYPOINT: quem roda migrate/collectstatic é o `web`.
    # Dois containers migrando ao mesmo tempo é corrida garantida.
    entrypoint: []
    command: >
      sh -c 'while true; do
               python manage.py sincronizar_reservas || echo "[scheduler] sync falhou";
               sleep "${SYNC_INTERVALO_SEGUNDOS:-900}";
             done'
    env_file:
      - .env
    depends_on:
      - db
    restart: always
```

Por que este formato, e não outros:

- **`sleep` depois de terminar, e não cron:** com cron, um sync lento pode
  começar por cima do anterior. Com `sleep` no fim do laço, sobreposição é
  impossível por construção.
- **`|| echo`:** falha de rede não pode matar o laço. O container fica de pé e
  tenta de novo no próximo ciclo.
- **`restart: always` + `depends_on: db`:** o banco subindo depois faz o
  primeiro ciclo falhar e o segundo funcionar. Sem intervenção.
- **Logs:** `docker compose logs -f scheduler`. Sem arquivo de log para
  rotacionar, sem cron mudo.
- **Não usar Celery + Redis** neste momento: são dois serviços e uma
  dependência operacional inteira para um job a cada 15 minutos. Quando
  houver filas de verdade (envio de e-mail, relatórios pesados), reavalia-se.

Alternativa igualmente boa, se você preferir controle no host: um **systemd
timer** chamando `docker compose run --rm web python manage.py
sincronizar_reservas`, com logs no journald e `systemctl list-timers` para
inspeção. Custa configuração fora do repositório — o serviço no compose viaja
junto com a aplicação.

**Lock contra execução concorrente.** Com um único scheduler não há
sobreposição, mas nada impede alguém de rodar o comando à mão durante um
ciclo. O jeito barato no Postgres é um *advisory lock*: se não conseguir o
lock, o comando sai sem fazer nada.

```python
with connection.cursor() as cursor:
    cursor.execute("SELECT pg_try_advisory_lock(%s)", [HASH_DO_JOB])
    if not cursor.fetchone()[0]:
        self.stdout.write("Outro sync em andamento. Saindo.")
        return
```

**Fuso do container.** Defina `TZ=America/Sao_Paulo` no `.env` para que os
logs saiam no horário local. O Django já usa `TIME_ZONE` do settings para
`timezone.localdate()`, então a regra de data futura não depende disso — mas
ler log em UTC atrapalha o diagnóstico.

---

## 9. Fases de entrega

| Fase | Entrega | Situação |
|---|---|---|
| 1 | Modelo + migration + admin + management command de mock | **feita** (migration `0006_reserva_viagem`) |
| 2 | Tela de agenda (dia + mês), somente leitura | **feita** (`/viagens/agenda/`) |
| 3 | Conclusão da reserva (form restrito, vínculo atômico, redirect) | **feita** (migration `0007_viagem_em_andamento`) — ver §11 |
| 4 | `sincronizar_reservas()` + testes | **feita** — 15 testes, sem tocar a rede |
| 5 | Cliente do Microsoft Graph | **feita** — `viagens/integracoes/microsoft_graph.py` (`calendarView`) |

### O que já existe (fases 4 e 5)

```
viagens/integracoes/microsoft_graph.py               borda: token, calendarView, normalizar_evento()
viagens/services.py                                  sincronizar_reservas()
viagens/management/commands/sincronizar_reservas.py  cola entre as duas (--dias, --dry-run)
viagens/management/commands/cadastrar_veiculos_salas.py  andaime de validação
colaboradores/models.py                              Funcionario.email único + normalizado
viagens/models.py                                    ReservaViagem.solicitante_email
```

```powershell
python manage.py cadastrar_veiculos_salas     # salas de reunião como veículos de teste
python manage.py sincronizar_reservas --dry-run
python manage.py sincronizar_reservas --dias 7
```

**Validação com dado real:** 8 caixas, 77 eventos importados, segunda execução
com 0 duplicatas. As reservas mockadas (veículos sem `email_recurso`) ficaram
intactas, provando a proteção de `caixas_consultadas`.

### O que já existe (fases 1 e 2)

```
viagens/models.py                                    ReservaViagem, Veiculo.email_recurso
viagens/services.py                                  reservas_no_periodo(), montar_calendario()
viagens/views.py                                     AgendaView
viagens/urls.py                                      /viagens/agenda/  (name="agenda")
viagens/templates/agenda.html                        fila do dia + panorama
viagens/templates/viagens/partials/_calendario.html  grade mensal (htmx)
viagens/admin.py                                     ReservaViagemAdmin
viagens/tests.py                                     12 testes das fases 1 e 2
```

Para popular o ambiente local, importe as reservas de verdade do Outlook
(fase 4): `python manage.py sincronizar_reservas --dias 30`. O comando
`criar_reservas_mock`, que gerava reservas fictícias enquanto a integração
não existia, foi removido — ele imitava o formato do `getSchedule`, que
acabou descartado, e nunca gravava `solicitante_email`.

### Testes a escrever (fase 3, antes do código)

- reserva já `LANCADA` não pode ser lançada de novo (404 / mensagem);
- KM inválido **não** marca a reserva como lançada (a transação reverte);
- a `Viagem` criada tem os dados da **reserva**, não os do POST adulterado;
- a reserva lançada aponta para a viagem criada (`reserva.viagem_id`);
- as regras de piso/teto/data futura continuam valendo neste caminho.

---

## 10. Decisões tomadas

| Questão | Decisão |
|---|---|
| Janela do sync | **hoje até +30 dias** |
| Chave do funcionário | **`email` nativo** do `AbstractUser` (não criar campo novo) |
| Agendamento em produção | **serviço `scheduler` no docker-compose**, laço com `sleep` |
| Reserva × viagem | **1:1** (`OneToOneField`) — uma reserva gera no máximo uma viagem |
| Lançamento do KM | **dois fluxos** (ver §11) |

---

## 11. Viagem em andamento (fase 3)

A portaria opera de duas formas, e ambas passam pelo mesmo código:

- **Fluxo A — duas etapas.** Saída: informa só o `km_inicial`; a viagem fica
  *em andamento*. Retorno: informa o `km_final` e ela é concluída.
- **Fluxo B — retrospectivo.** O veículo já voltou; os dois KMs são
  informados de uma vez.

O que distingue os dois é um único campo opcional no formulário: `km_final`
em branco = Fluxo A.

### Estado derivado, não armazenado

`Viagem` **não** ganhou campo `status`. São apenas dois estados e eles já
estão contidos no dado: `km_final IS NULL` é a viagem em andamento. As
propriedades `em_andamento`, `concluida` e `status_descricao` leem daí.

Guardar um `status` redundante permitiria o registro contraditório
("concluída" com `km_final` vazio). É o mesmo critério de `Viagem.fechada`
(dois estados → derivado) e o oposto de `ReservaViagem.status` (três estados,
sendo "cancelada" irrepresentável pela ausência de viagem → campo real).

### O que precisou ser blindado

Uma viagem sem `km_final` é exatamente o cenário que a §3 descartou. Ela só é
segura porque:

| Ponto | Proteção |
|---|---|
| `viagens_em_aberto()` | filtra `km_final__isnull=False` — **viagem em andamento nunca entra em fechamento** |
| `confirmar_fechamento()` | passou a reutilizar `viagens_em_aberto()`; antes repetia o filtro e as duas regras podiam divergir |
| `km_percorrida` | zero enquanto em andamento — o rateio jamais soma km que ninguém percorreu |
| piso do hodômetro | `Max(Coalesce(km_final, km_inicial))`: o `MAX()` do SQL ignora nulos, e sem o Coalesce o carro que saiu e não voltou deixaria de contar como piso |
| `Veiculo.km_atual` | mesmo Coalesce, pela mesma razão |
| `CheckConstraint` | `km_final IS NULL OR km_final > km_inicial` |
| saída duplicada | `viagem_em_andamento_do_veiculo()` impede o mesmo carro sair duas vezes |

### Fluxo de telas

```
/viagens/agenda/                    card "Lançar KM"
   └─> /viagens/reservas/<pk>/lancar/
          km_final vazio  → viagem em andamento → volta para a agenda
          km_final preenchido → viagem concluída → volta para a agenda

/viagens/agenda/                    card "Registrar chegada (saiu em NNNNN)"
   └─> /viagens/chegada/<pk>/       conclui a viagem
```

O lançamento avulso (`/viagens/lancar/`) também aceita `km_final` em branco, e
a tabela de últimas viagens oferece o link de chegada — os dois fluxos valem
com ou sem reserva.

### Garantias de concorrência

- `select_for_update(of=("self",))` na reserva e na viagem. O `of=("self",)`
  não é detalhe: `funcionario` é FK opcional, o `select_related` gera LEFT
  OUTER JOIN e o Postgres recusa `FOR UPDATE` no lado nulável de uma junção
  externa.
- O filtro de estado vai **no próprio lookup** (`status=PENDENTE`,
  `km_final__isnull=True`): a segunda aba recebe 404 em vez de criar viagem
  duplicada.
- Tudo dentro de `transaction.atomic`: KM inválido reverte também a mudança de
  status da reserva.

### Aviso no fechamento

`calcular_rateio()` devolve também `quantidade_em_andamento`, e o modal de
confirmação exibe *"Há N viagem(ns) em andamento neste período, tem certeza
que gostaria de realizar o fechamento?"*. Elas não entram no fechamento por
construção — mas como a ação é irreversível, o operador precisa decidir com a
informação na tela (pode ser que o certo seja esperar o veículo voltar).

---

## 11.1 Alternativa considerada e descartada

> Registrada porque é uma boa alternativa, não uma ideia ruim. Sem isto
> documentado, o raciocínio inteiro seria refeito do zero daqui a seis meses.

**A proposta:** em vez de `Viagem` com `km_final` nulável, o estado
intermediário viveria na **reserva**. `ReservaViagem` receberia o
`km_inicial` na saída (status `EM_ANDAMENTO`) e só ao receber o `km_final` é
que uma `Viagem` — sempre completa — seria criada. No fechamento existiriam
dois conjuntos: viagens (fechavéis) e reservas em aberto (pendentes).

**O que ela tem de melhor.** Preserva um invariante forte: *toda `Viagem` no
banco tem quilometragem completa*. Isso é mais fiel à §3 deste documento
("reserva é intenção, viagem é fato consumado") — uma viagem em andamento não
é um fato consumado, é um fato pela metade. E, principalmente: as sete
blindagens da tabela acima **não existiriam**. O risco de o fechamento
consumir uma viagem incompleta desapareceria por não haver o que consumir.
Perigo inexistente é melhor que perigo bem tratado.

**Por que foi descartada.**

1. **As regras de hodômetro atravessariam duas tabelas.** O carro que saiu
   com 107.000 e não voltou precisa participar do piso, do teto e do
   `km_atual`. Com esse km na tabela `reserva_viagem`, cada uma das três
   regras viraria *"o maior entre `Max(viagem.km_final)` e
   `Max(reserva.km_inicial)`"* — dois agregados em tabelas diferentes,
   combinados em Python. A complexidade não sumiria: mudaria para o pior
   lugar possível, a parte mais intrincada e mais testada do sistema.

2. **A viagem avulsa não teria onde morar.** O fluxo em duas etapas também
   vale sem reserva (saída de emergência, sem agendamento no Outlook). Seria
   preciso criar uma "reserva sintética" só para segurar o `km_inicial`, e aí
   `ReservaViagem` deixaria de significar "pré-agendamento vindo do Outlook"
   para significar "qualquer viagem não terminada" — dois conceitos disputando
   a mesma tabela, e o sync da fase 4 teria que distinguir "pendente de
   verdade" de "carro na rua".

3. **Campos duplicados.** `km_inicial`, `lancada_por` e `criada_em` existiriam
   nos dois modelos, com cópia de um para o outro.

**A regra geral que decidiu.** Diante de um estado "pela metade", escolhe-se
entre (a) uma entidade com campo nulável e (b) duas entidades, uma que vira a
outra. A pergunta que resolve é **quantas regras precisam enxergar os dois
estados ao mesmo tempo**: poucas → (b) ganha; muitas → (a) ganha, porque cada
regra em (b) vira consulta a duas tabelas. Aqui são três regras de hodômetro,
justamente as mais delicadas.

**Se um dia for revista:** exige migration com dados e reescrita de
`validar_quilometragem`. Decisão para tomar antes da fase 4, não depois.

### Nada em aberto

As duas perguntas que restavam foram respondidas: relação **1:1** e **dois
fluxos de lançamento**.
