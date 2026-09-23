# Plano de implementação: sincronização de funcionários com o ERP

**Data:** 2026-09-23
**Baseado em:** [`specs/2026-09-22-sincronizacao-funcionarios-erp-design.md`](../specs/2026-09-22-sincronizacao-funcionarios-erp-design.md) (desenho aprovado)
**Referência de padrão arquitetural (não copiar decisões de negócio):** `docs/DOCUMENTACAO_SINCRONIZACAO_FUNCIONARIOS_ERP.md`

Este plano segue os **padrões já existentes neste projeto** (não os do projeto
de referência, que usa `urllib` e nomes diferentes). Os pares a seguir são o
molde:

| Papel | Padrão já existente (Outlook) | Novo (ERP) |
|---|---|---|
| Cliente da API externa ("borda") | `viagens/integracoes/microsoft_graph.py` | `colaboradores/integracoes/erp.py` |
| Orquestração/regra de negócio | `viagens/sincronizacao.py` | `colaboradores/sincronizacao_erp.py` |
| Comando de linha de comando | `viagens/management/commands/sincronizar_reservas.py` | `colaboradores/management/commands/sincronizar_funcionarios_erp.py` |
| Agendamento em produção | `scheduler.sh` (laço `sleep`) | **cron real** (decisão desta sessão — ver §6) |

Decisão de agendamento tomada nesta sessão: como o desenho pede 4 horários
fixos de relógio (07:15/18:15 admissão, 07:20/18:20 demissão), optou-se por
instalar cron real no container em vez de estender o laço `sleep`. Isso
reintroduz um padrão que o projeto não usava (o sync do Outlook é por
intervalo, não por horário de relógio) — ver §6.

---

## 1. Migration — campos novos em `Funcionario`

Arquivo: `colaboradores/migrations/0006_funcionario_datas_erp.py`

```python
data_admissao = models.DateField(null=True, blank=True, verbose_name="Data de admissão")
data_demissao = models.DateField(null=True, blank=True, verbose_name="Data de demissão")
```

Sem dado inicial — `null=True` cobre os cadastros legados, como já decidido
no desenho. Rodar `makemigrations --check` depois de editar `models.py` para
confirmar que não sobrou mais nada implícito.

**Arquivo tocado:** `colaboradores/models.py` (adiciona os dois campos à
classe `Funcionario`, com docstring curta explicando que só o ERP escreve
neles — nome, e-mail, cargo etc. continuam fora do escopo sincronizado).

---

## 2. Configuração — variáveis de ambiente

Adicionar ao `.env` (e documentar em `docs/DEPLOY.md` quando chegar a hora):

```env
ERP_FUNCIONARIOS_API_URL=https://10.1.1.220/api/funcionarios/v10/informacoes
ERP_FUNCIONARIOS_API_TOKEN=
ERP_FUNCIONARIOS_API_TIMEOUT=300
```

Não há variável de SSL: a desabilitação é uma decisão fixa do desenho, não
configurável (evita alguém ligar validação sem cuidar do bundle de CA em
produção). O mapa empresa→unidade (`1/2/20 → Matriz/Filial MG/EVO`) fica no
código, como já é feito para os catálogos — não precisa de variável.

---

## 3. Cliente HTTP — `colaboradores/integracoes/erp.py`

Espelha `viagens/integracoes/microsoft_graph.py`: só fala HTTP, não conhece
models. Usa `requests` (já é dependência do projeto — não introduzir
`urllib`, que é o que o projeto de referência usa).

```python
class ERPIndisponivel(Exception):
    """Falha ao falar com a API do ERP (rede, credencial, resposta inválida)."""

def buscar_funcionarios(empresa: int, ano_mes: str, operacao: str) -> list[dict]:
    """
    operacao: "admissao" ou "demissao" → parâmetro dataAdmissao/dataDemissao.
    Levanta ERPIndisponivel em timeout, erro de conexão, status != 2xx,
    JSON inválido ou corpo sem `data` como lista.
    """
```

Detalhes fixados pelo desenho:
- `verify=False` explícito na chamada `requests.get(...)` (não é o padrão do
  `requests` — precisa estar visível no código, não escondido em config).
- `timeout=int(os.environ["ERP_FUNCIONARIOS_API_TIMEOUT"])`.
- Headers: `accept: application/json`, `empresa: <código>`,
  `Authorization: <token cru>` (sem `Bearer`).
- **Sem retry** — uma falha é uma falha, sobe para quem chamou.
- O token nunca entra em mensagem de exceção nem em log (mesmo cuidado já
  tomado com o `.env` do Graph).

---

## 4. Serviço — `colaboradores/sincronizacao_erp.py`

Espelha `viagens/sincronizacao.py`: é aqui que mora a regra de negócio,
compartilhada pelo command, pelo botão do Admin e (indiretamente) pelo cron.

Funções principais, na ordem em que o desenho as descreve:

```python
EMPRESAS_UNIDADES = {1: "Matriz", 2: "Filial MG", 20: "EVO"}  # nome, resolvido via codigo_empresa_erp

def mes_corrente() -> str:
    """AAAAMM em America/Sao_Paulo — mesmo cuidado do timezone.localdate() já documentado."""

def sincronizar(operacoes: tuple[str, ...] = ("admissao", "demissao")) -> ResultadoSincronizacaoERP:
    """Processa as empresas configuradas, admissão antes de demissão."""

def _processar_empresa(empresa: int, operacao: str, periodo: str, resultado) -> None: ...
def _processar_registro(registro: dict, operacao: str, unidade, resultado) -> None: ...
def _garantir_catalogo(modelo, descricao) -> tuple[obj, bool]: ...  # reaproveita preparar_descricao_catalogo/normalizar_descricao_catalogo já existentes em models.py
```

Regras a implementar (todas já fechadas no desenho, não rediscutir):

- Identidade: `unidade_fabril + codigo_funcionario_erp` — nunca por nome.
- Admissão: `situacao == "Ativo"` → `ativo=True, is_active=True`; qualquer
  outra situação não vazia → `False`; situação vazia → registro inválido,
  ignorado com erro.
- Demissão: sempre inativa, independente de `situacao`.
- Admissão escreve só `data_admissao`; demissão só `data_demissao`; data
  vazia limpa o campo (`None`).
- Centro de custo: cria se não existir, atualiza descrição se divergente,
  preserva o vínculo local se o ERP mandar código vazio. Validar os 10
  dígitos com a mesma função `normalizar_codigo` de
  `cadastro_centro_custo.py` (não duplicar a regra).
- Departamento/seção: mesma função `_garantir_catalogo` que
  `cadastro_funcionarios.py` já usa via
  `Departamento.objects.get_or_create(descricao_normalizada=...)` —
  reaproveitar, não reescrever.
- Cada registro em `transaction.atomic()` próprio; erro de um não aborta o
  lote nem a empresa.
- Novo funcionário: `username=gerar_username(nome)` (de `colaboradores/forms.py`,
  já usado por `cadastro_funcionarios.py`) + `set_unusable_password()`.
- Resultado estruturado (dataclass `ResultadoSincronizacaoERP`, seguindo o
  molde de `viagens/sincronizacao.py`): período, empresas processadas/com
  falha, recebidos, criados, criados-inativos, atualizados, inativados,
  catálogos criados, ignorados, erros por empresa/operação/registro. Sem
  segredo nenhum dentro do resultado.

Este projeto **não usa lock de PostgreSQL nem `select_for_update()`** hoje em
nenhum sync existente (o do Outlook também não usa). Avaliar se é necessário
aqui: como o cron pode disparar admissão e demissão em execuções separadas
(minuto 15 e minuto 20), e o comando também pode ser rodado manualmente a
qualquer momento, existe uma janela pequena de corrida real. Recomendação:
adicionar `select_for_update()` na busca do funcionário dentro da transação
do registro (barato, já resolve o caso comum) e não trazer
`pg_try_advisory_lock` — seria a primeira vez que o projeto usa esse
mecanismo, para um risco que a transação por registro já reduz bastante.
Se o usuário preferir o lock global, é o próximo ponto a decidir antes de
codar o serviço.

---

## 5. Management command — `colaboradores/management/commands/sincronizar_funcionarios_erp.py`

Casca fina, no molde de `sincronizar_reservas.py`:

```bash
python manage.py sincronizar_funcionarios_erp
python manage.py sincronizar_funcionarios_erp --operacao admissao
python manage.py sincronizar_funcionarios_erp --operacao demissao
```

Sem operação: roda as duas, admissão antes de demissão (o serviço já impõe
essa ordem internamente, mas o command não deve depender disso por acidente).
Sai com código diferente de zero e `CommandError` quando há erros — mesmo
contrato do `sincronizar_reservas`, para o cron perceber falha nos logs.

---

## 6. Admin — botão protegido para superusuário

Em `colaboradores/admin.py`, `FuncionarioAdmin` ganha:

- `get_urls()` registrando `sincronizar-erp/`;
- a view chama `sincronizar()` do serviço e mostra um resumo (mesmo texto que
  o command imprime, adaptado para HTML) — sem token, sem corpo de resposta.
- Proteção **dupla**, como já é costume no projeto
  (`controle_veiculos/admin.py`): decorator `staff_member_required` do Django
  **e** checagem explícita de `request.user.is_superuser`, porque
  `is_staff=True` sozinho não deveria bastar para disparar uma sincronização
  que grava no banco de produção.
- Um botão/link na `change_list.html` de Funcionario (sobrescrever o
  template, como o projeto de referência faz) ou, mais simples e sem tocar
  template, um item na barra superior do Admin — decidir na implementação,
  não é uma decisão de arquitetura que precise travar o plano.

---

## 7. Docker e cron

Decisão desta sessão: cron real, não o laço `sleep` do `scheduler.sh`.

### Dockerfile

Adicionar `cron` ao `apt-get install` (ao lado de `gcc`, `libpq-dev`,
`netcat-traditional`), copiar o arquivo de cron e um wrapper de ambiente, com
o mesmo tratamento de CRLF que `entrypoint.sh`/`scheduler.sh` já recebem via
`sed`.

### `docker/cron/sincronizar-funcionarios-erp`

```cron
CRON_TZ=America/Sao_Paulo

15 7,18 * * 1-5 root /usr/local/bin/run-sincronizar-funcionarios-erp python manage.py sincronizar_funcionarios_erp --operacao admissao
20 7,18 * * 1-5 root /usr/local/bin/run-sincronizar-funcionarios-erp python manage.py sincronizar_funcionarios_erp --operacao demissao
```

### `docker/cron/run-sincronizar-funcionarios-erp`

Wrapper que lê `/proc/1/environ`, repassa a allowlist
(`DATABASE_URL`, `ERP_FUNCIONARIOS_API_URL`, `ERP_FUNCIONARIOS_API_TOKEN`,
`ERP_FUNCIONARIOS_API_TIMEOUT`) e executa `exec "$@"` de dentro de `/app`
(`cd /app` antes do `exec`, já que o cron não herda o `WORKDIR` da imagem).
Não grava nem imprime o token — mesmo cuidado do wrapper do projeto de
referência.

### `docker-compose.yml`

O serviço `scheduler` já existe para o Outlook. Decisão a bater com o
usuário na implementação: **um novo serviço `scheduler-erp`** com
`entrypoint: ["cron", "-f", "-L", "8"]`, ou **cron dentro do mesmo container
`scheduler`** ao lado do laço `sleep`. Um container por processo é o padrão
mais comum em Docker (mais fácil de depurar logs separadamente) — recomendo
serviço novo, mas é uma escolha de custo baixo de reverter.

Stdout/stderr do cron precisam ir para `/proc/1/fd/1`/`/proc/1/fd/2` no
arquivo de cron, senão `docker compose logs` não mostra nada (armadilha já
documentada no projeto de referência, vale evitar de origem).

---

## 8. Testes

Em `colaboradores/tests.py` (ou um novo `colaboradores/tests_sincronizacao_erp.py`
se a suíte crescer demais — decidir no momento, seguindo o costume de manter
um arquivo por enquanto). Lista adaptada do desenho para os casos reais deste
projeto:

**Cliente (`erp.py`)** — usar `responses` ou mock de `requests.get`, sem
depender de rede:
- URL, parâmetros (`dataAdmissao`/`dataDemissao`) e headers corretos;
- `timeout` aplicado; `verify=False` aplicado;
- resposta 2xx com `data` válida, vazia, JSON inválido, `data` ausente/não-lista;
- erro de conexão/timeout não expõe o token na mensagem.

**Serviço (`sincronizacao_erp.py`)**, usando o banco de teste real:
- identidade por unidade + código, inclusive código repetido em empresas
  diferentes (caso real do CSV, já teve teste equivalente em
  `cadastro_funcionarios`);
- criação e atualização por admissão; inativação por demissão;
- ordem admissão → demissão quando as duas rodam juntas;
- limpeza de data (`data_admissao`/`data_demissao` vazias no payload);
- preservação de centro de custo/departamento/seção quando o ERP manda vazio;
- criação/atualização de centro de custo pelas regras de
  `codCentroCusto`/`centroCusto`;
- registro inválido isolado não aborta o lote; falha de uma empresa não
  aborta as demais;
- e-mail, cargo e demais campos fora do escopo permanecem intocados.

**Command:** código de saída != 0 com erros; imprime resumo sem token.

**Admin:** botão/URL só acessível a superusuário (mesmo padrão de teste já
usado para validar a trava do `/admin` da portaria — desligar a checagem de
propósito e ver o teste falhar, conforme registrado nas preferências do
usuário).

---

## 9. Ordem recomendada de implementação

1. Migration + campos no model (`data_admissao`, `data_demissao`).
2. Cliente `colaboradores/integracoes/erp.py` + testes do cliente.
3. Serviço `colaboradores/sincronizacao_erp.py` + testes do serviço (é o
   grosso do trabalho — pode ser dividido em: identidade/criação/atualização
   primeiro, depois centro de custo/catálogos, depois datas/inativação).
4. Command `sincronizar_funcionarios_erp` + teste de código de saída.
5. Botão no Admin + teste de permissão.
6. Docker: cron, wrapper, Dockerfile, docker-compose — só depois do command
   já provado localmente com `--operacao` manual.
7. Verificação final: `python manage.py test`, `python manage.py check`,
   `makemigrations --check`, `docker compose config`, depois
   `docker compose up -d --build` e checar `docker compose logs -f
   scheduler-erp` (ou o nome escolhido no passo 6) por uma execução manual
   disparada com `docker compose exec web python manage.py
   sincronizar_funcionarios_erp`.

---

## 10. Decisões tomadas durante a implementação (23/09/2026)

As três ficaram em aberto no plano original; foram decididas ao codar,
sem travar nada:

1. **Lock de concorrência**: `select_for_update()` por registro dentro da
   `transaction.atomic()` de cada linha — sem lock global do Postgres.
2. **Container do cron**: serviço `scheduler-erp` novo (não misturado com o
   `scheduler` do Outlook).
3. **Botão do Admin**: `change_list_template` customizado
   (`admin/colaboradores/funcionario/change_list.html`) com um botão que
   leva a uma tela de confirmação — **GET só mostra a confirmação, o POST
   executa**. Decisão extra tomada aqui (o desenho original não distinguia
   GET/POST): evita que um clique acidental, prefetch de navegador ou
   recarregamento dispare uma sincronização de verdade.

## 11. Lacuna do desenho resolvida na implementação

O desenho aprovado (22/09) não define o que fazer quando uma **demissão**
retorna um `codFuncionario` que não existe localmente. A decisão tomada em
`colaboradores/sincronizacao_erp.py` foi criar o registro já inativo
(simétrico à admissão, que cria ativo) — ver a nota no topo do módulo.
**Revisar com o usuário** se isso é o comportamento desejado, já que o
desenho original ficou silencioso sobre o caso.

## 12. Status: implementado e testado (23/09/2026)

Todos os itens da ordem recomendada (§9) foram concluídos:

- Migration `0006_funcionario_data_admissao_funcionario_data_demissao`.
- `colaboradores/integracoes/erp.py` (cliente) + 12 testes.
- `colaboradores/sincronizacao_erp.py` (serviço) + 16 testes.
- `colaboradores/management/commands/sincronizar_funcionarios_erp.py`.
- Botão protegido no Admin + 2 testes de permissão.
- `docker/cron/sincronizar-funcionarios-erp`, `docker/cron/run-sincronizar-funcionarios-erp`,
  `Dockerfile` (pacote `cron` + cópia dos arquivos), serviço `scheduler-erp`
  no `docker-compose.yml`, variáveis novas no `.env`.

Verificação: `python manage.py test` (206 testes — só a falha antiga já
documentada continua falhando), `python manage.py check`,
`makemigrations --check` (sem mudanças) e `docker compose build web` (build
completo, `python manage.py check` roda dentro da imagem) todos passaram.
`docker compose config` valida o `scheduler-erp` novo.

**Não validado nesta sessão** (exige credencial real e servidor do ERP
acessível): execução de verdade contra `https://10.1.1.220/...`, e o
primeiro disparo real do cron nos 4 horários — só a config e o formato do
arquivo de cron dentro da imagem foram conferidos.
