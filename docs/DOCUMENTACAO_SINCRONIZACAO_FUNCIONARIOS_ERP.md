# Documentação da Sincronização de Funcionários com o ERP

## Escopo e fonte da documentação

Este documento descreve a implementação existente no sistema Django de sorteio de
brindes deste repositório. A análise foi feita a partir do código-fonte, configurações
Docker, migrations e testes disponíveis no projeto.

As marcações abaixo distinguem os tipos de informação:

- **Confirmado pelo código:** comportamento implementado e observável nos arquivos analisados.
- **Específico da aplicação atual:** decisão de domínio, empresa, banco ou agenda que não deve ser copiada sem avaliação.
- **Reutilizável:** estrutura ou regra que pode ser transportada para outra aplicação.
- **Não identificado na implementação analisada:** informação que não está disponível no código e não deve ser presumida.

O documento não propõe uma nova integração nem altera a aplicação atual. Ele serve como
referência para reproduzir a arquitetura em outro projeto.

## 1. Visão Geral

A integração sincroniza funcionários retornados pelo ERP com o cadastro local. Ela
suporta duas operações:

- **admissão:** consulta funcionários admitidos em um período e cria ou atualiza o cadastro local;
- **demissão:** consulta funcionários desligados em um período e marca o cadastro local como inativo.

O ERP é tratado como origem dos dados sincronizados. O banco PostgreSQL da aplicação é
o destino. A sincronização não exclui fisicamente funcionários e não inativa um
funcionário apenas porque ele não apareceu em uma resposta.

| Componente | Responsabilidade |
|---|---|
| ERP | Fornecer listas de admitidos e demitidos por empresa e período. |
| `ERPClient` | Fazer chamadas HTTP, montar parâmetros e validar a resposta. |
| `FuncionarioSyncService` | Aplicar normalização, identidade, regras de criação/atualização/inativação e transações. |
| Management command | Expor a sincronização para execução manual ou pelo cron. |
| PostgreSQL/Django ORM | Persistir funcionários, unidades, departamentos e seções. |
| Cron no container `scheduler` | Disparar o command em horários definidos. |
| Admin Django | Permitir execução manual protegida para diagnóstico e reprocessamento. |

Há dois pontos de entrada confirmados: o scheduler Docker e a tela customizada do
Admin. O command também pode ser executado diretamente:

```bash
python manage.py sincronizar_funcionarios
python manage.py sincronizar_funcionarios --periodo 202608
```

O período padrão é o mês corrente no timezone `America/Sao_Paulo`. A frequência atual
é específica deste projeto e deve ser escolhida separadamente na nova aplicação.

## 2. Arquitetura da Integração

O fluxo efetivamente implementado é:

```text
Cron dentro do container scheduler
        │
        ▼
Wrapper que repassa o ambiente do processo principal
        │
        ▼
python manage.py sincronizar_funcionarios --operacao ...
        │
        ▼
FuncionarioSyncService
        │
        ├── lock global PostgreSQL
        ├── seleção das empresas e operações
        ├── normalização e comparação com o banco local
        └── transaction.atomic() por funcionário
                │
                ├── ERPClient
                │       └── GET para o ERP
                │
                └── Django ORM / PostgreSQL
                        └── inclusão, atualização ou inativação
```

Existe também o caminho alternativo:

```text
Admin Django
    ▼
SincronizarFuncionariosERPForm
    ▼
FuncionarioSyncService.sincronizar()
```

### Responsabilidade das camadas

`ERPClient` conhece HTTP e o contrato da resposta, mas não conhece os models. Ele não
persiste dados e não decide se um funcionário é novo ou demitido.

`FuncionarioSyncService` coordena o lote completo: empresas, operações, normalização,
identidade, persistência e resultado. O command valida argumentos, chama o serviço,
imprime JSON e retorna erro operacional quando há falhas.

O scheduler não contém regra de negócio; apenas chama o command com a operação correta.
Assim, execução manual e automática usam o mesmo serviço.

**Não foram identificados repositories, managers específicos, Celery, RQ, APScheduler
ou tasks assíncronas.** A persistência é feita diretamente pelo Django ORM dentro de
`FuncionarioSyncService`.

## 3. Arquivos e Componentes Envolvidos

### Núcleo

#### `funcionarios/services/erp_client.py`

Contém `ERPClient.buscar(empresa, periodo, tipo)` e as exceções
`ERPClientError`, `ERPConfigurationError`, `ERPConnectionError`, `ERPHTTPError` e
`ERPResponseError`. O cliente monta a URL, envia headers, executa `GET`, valida status,
decodifica JSON e devolve `payload["data"]`.

#### `funcionarios/services/funcionario_sync.py`

Contém `FuncionarioSyncService`, `SyncResult`, o mapa `EMPRESAS_UNIDADES`, as
operações `OPERACOES`, o lock `_lock_de_sincronizacao()` e as funções de normalização.

Métodos principais:

- `sincronizar()`: valida período, adquire lock e percorre empresas;
- `_sincronizar_empresa()`: consulta cada operação e trata falhas da API;
- `_processar_registros()`: processa cada item em transação própria;
- `_persistir_funcionario()`: localiza, cria ou atualiza o funcionário;
- `_garantir_unidade()`: resolve empresa ERP para `UnidadeFabril`;
- `_garantir_catalogo()`: cria/recupera departamentos e seções;
- `_normalizar_registro()`: valida payload;
- `validar_operacoes()` e `validar_periodo()`: validam execução.

#### `funcionarios/management/commands/sincronizar_funcionarios.py`

Define o command e os argumentos `--periodo` e `--operacao`, com valores `admissao`,
`demissao` ou `todas`. Sem operação explícita, passa `operacoes=None` e o serviço
processa admissão e demissão.

#### `funcionarios/models.py`

Models diretamente envolvidos:

- `UnidadeFabril.codigo_empresa_erp`, único e opcional;
- `Funcionario.codigo_funcionario_erp`, `unidade_fabril`, `departamento`, `secao` e `ativo`;
- `Departamento.descricao_normalizada` e sua constraint única;
- `Secao.descricao_normalizada` e sua constraint única.

`preparar_descricao_catalogo()` e `normalizar_descricao_catalogo()` estabilizam as
chaves dos catálogos.

#### `funcionarios/migrations/0006_identidade_erp_catalogos.py`

Adiciona a identidade ERP, as chaves normalizadas e as constraints. `preencher_chaves()`
mapa unidades por nome, sem depender dos IDs locais:

```python
{"matriz": 1, "filial mg": 2, "evo": 20}
```

Também preenche as chaves de departamentos e seções. A migration
`0007_alter_funcionariossorteados_unidade_fabril.py` não implementa a sincronização;
apenas remove o `default=1` do histórico de sorteios.

### Entrada manual e bootstrap

`funcionarios/forms.py` contém `SincronizarFuncionariosERPForm`, que valida período
reutilizando `FuncionarioSyncService.validar_periodo()`.

Em `sorteador/admin.py`, `FuncionarioAdmin.get_urls()` registra `sincronizar-erp/` e
`sincronizar_erp_view()` valida o formulário, chama o serviço, mostra o resultado e
trata erros conhecidos/inesperados.

Os templates são:

- `sorteio/templates/admin/funcionarios/funcionario/change_list.html`, link para a execução;
- `sorteio/templates/admin/funcionarios/funcionario/sincronizar_erp.html`, formulário, resumo e falhas.

`funcionarios/management/commands/cadastro_funcionarios.py` é uma carga inicial por CSV,
não o fluxo periódico da API. Ela usa a mesma identidade, catálogos e vinculação de
legados e deve ser tratada como bootstrap.

### Infraestrutura e testes

- `sorteio/settings.py`: variáveis da API, banco, timezone e logging;
- `docker-compose.yml`: serviços `web`, `scheduler`, `db` e `nginx`;
- `Dockerfile`: instala cron e copia cron/wrapper para a imagem;
- `docker/cron/sincronizar-funcionarios`: entradas de agendamento;
- `docker/cron/run-sincronizar-funcionarios`: repasse controlado do ambiente;
- `entrypoint.sh`: migrations e inicialização do `web`, não do scheduler;
- `funcionarios/tests_sincronizacao.py`: testes do cliente, models, service, carga e command;
- `funcionarios/tests.py`: testes do wrapper, cron e Admin;
- `requirements.txt`: dependências de Django, PostgreSQL e configuração.

## 4. Sincronização de Funcionários

### 4.1 Início

`FuncionarioSyncService.sincronizar(periodo=None)`:

1. valida o período;
2. cria `SyncResult` com período e operações;
3. registra o início;
4. tenta o lock global PostgreSQL;
5. percorre empresas, por padrão `1`, `2` e `20`;
6. percorre as operações selecionadas;
7. atualiza contadores/erros;
8. libera o lock e registra encerramento.

O período deve ser exatamente `AAAAMM` e representar um mês válido. Sem período, usa
`timezone.localdate().strftime("%Y%m")`.

### 4.2 Consulta ao ERP

`ERPClient.buscar()` escolhe o parâmetro:

```python
{"admissao": "dataAdmissao", "demissao": "dataDemissao"}[tipo]
```

As chamadas são:

```http
GET {ERP_FUNCIONARIOS_API_URL}?dataAdmissao=AAAAMM
GET {ERP_FUNCIONARIOS_API_URL}?dataDemissao=AAAAMM
```

Parâmetros preexistentes na URL são preservados. Headers:

```http
Accept: application/json
Empresa: <código da empresa ERP>
Authorization: <ERP_FUNCIONARIOS_API_TOKEN>
```

O token é enviado exatamente como configurado; não há prefixo automático `Bearer`.
O código não fixa o endpoint produtivo: o valor completo vem de
`ERP_FUNCIONARIOS_API_URL`. **O caminho produtivo exato não foi identificado no código.**
Os testes usam `/informacoes` apenas como URL de exemplo.

### 4.3 Resposta e normalização

O cliente exige status 2xx, corpo UTF-8, objeto JSON, chave `data` e `data` como lista.
Lista vazia é válida. Paginação, cursor ou total de registros **não foram identificados**.

Payload usado:

```json
{
  "data": [
    {
      "codFuncionario": 518,
      "nome": "Ana Souza",
      "departamento": "Produção",
      "secao": "Impressão",
      "situacao": "Ativo"
    }
  ]
}
```

`codFuncionario` aceita inteiro ou string, converte inteiro para string, aplica
`strip()` e rejeita nulo, booleano, vazio ou mais de 125 caracteres. `nome` é string
obrigatória, recebe `strip()` e também tem limite de 125.

Departamento e seção são opcionais; `null`/vazio vira `None`, espaços consecutivos são
reduzidos e o limite é 125. Em admissões, `situacao` é obrigatória e aceita, após
`casefold()`, `ativo`, `inativo`, `demitido` ou `desligado`. Só `ativo` resulta em
`Funcionario.ativo=True`. Em demissões, a situação não é usada e `ativo=False` é forçado.

### 4.4 Identificação e legado

A identidade permanente é:

```text
UnidadeFabril vinculada à empresa ERP + codigo_funcionario_erp
```

O lookup usa `select_for_update()` nessa combinação. O `id` local e o nome não são
identidade permanente. A constraint `unique_funcionario_codigo_erp_por_unidade` bloqueia
o mesmo código na mesma unidade, mas permite o mesmo código em empresas diferentes.

Se não houver código correspondente, o serviço procura legados com código `NULL` ou
vazio na mesma unidade. Compara:

```python
" ".join(nome.split()).casefold()
```

Exatamente um candidato é vinculado; nenhum candidato resulta em criação; mais de um
gera `AmbiguousLegacyEmployee`, registro ignorado e erro reportado. Depois do vínculo,
as execuções usam somente empresa + código ERP.

### 4.5 Unidade e catálogos

`EMPRESAS_UNIDADES` é:

| Código ERP | Unidade esperada |
|---:|---|
| 1 | Matriz |
| 2 | Filial MG |
| 20 | EVO |

`_garantir_unidade()` primeiro busca pelo código, valida o nome normalizado, depois
procura pelo nome, preenche código em unidade sem código ou cria a unidade. Duplicidade
ou conflito de mapeamento gera `SyncConfigurationError`.

`_garantir_catalogo()` usa `get_or_create()` por `descricao_normalizada`, criada com
espaços reduzidos e `casefold()`. `Departamento` e `Secao` são catálogos independentes;
quando ausentes, a FK do funcionário fica nula.

### 4.6 Criação, atualização e inativação

Se não houver funcionário identificado, `objects.create()` grava código, nome, unidade,
departamento, seção e status. Admissão cria conforme `situacao`; demissão de código
desconhecido cria um registro inativo e incrementa `funcionarios_criados_inativos`.

Se existir, compara e pode atualizar somente os campos alterados:

- `codigo_funcionario_erp`;
- `nome`;
- `unidade_fabril`;
- `departamento`;
- `secao`;
- `ativo`.

O save usa `update_fields`. Execução repetida com o mesmo payload não duplica nem conta
atualização indevida.

Na demissão, um existente recebe `ativo=False`, sem exclusão física. Só a transição de
ativo para inativo incrementa `funcionarios_inativados`; um novo inativo conta como
`funcionarios_criados_inativos`.

### 4.7 Ausência e duplicidades

Funcionários presentes no ERP são criados se os dados obrigatórios forem válidos.
Funcionários locais ausentes da resposta permanecem como estão: não existe
reconciliação por ausência nem varredura de inativação.

A idempotência resulta de lookup composto, atualização diferencial, vínculo único de
legado, constraint no banco, `select_for_update()` e advisory lock. Não há retry interno
para resolver automaticamente uma corrida terminada em `IntegrityError`.

### 4.8 Transações e resultado

Chamadas HTTP ficam fora de transações. Cada registro é persistido dentro de sua própria
`transaction.atomic()`, permitindo falha parcial. O serviço retorna `SyncResult`, que
inclui período, operações, empresas processadas/com falhas, recebidos por operação,
criados, criados inativos, atualizados, inativados, catálogos criados, ignorados, erros
e detalhamento por empresa.

`SyncResult.to_dict()` vira JSON no command com indentação, chaves ordenadas e
`ensure_ascii=False`.

## 5. Fluxo de Admitidos e Desligados

### Admissões

```http
GET {ERP_FUNCIONARIOS_API_URL}?dataAdmissao=AAAAMM
Empresa: <empresa>
```

`codFuncionario`, `nome` e `situacao` são obrigatórios. O registro é criado ou
atualizado, catálogos são resolvidos, e `ativo` é calculado pela situação. Legados podem
ser vinculados por nome único.

### Desligamentos

```http
GET {ERP_FUNCIONARIOS_API_URL}?dataDemissao=AAAAMM
Empresa: <empresa>
```

`codFuncionario` e `nome` são obrigatórios; `situacao` não é necessária. O serviço força
`ativo=False`. Se existir, inativa; se não existir, cria inativo. Histórico e vínculos
não são removidos.

### Período

O intervalo é enviado apenas como mês `AAAAMM`. O código não calcula primeiro/último
dia, não envia data completa e não persiste data de admissão/demissão. Esses comportamentos
**não foram identificados na implementação analisada**.

### Ordem

Quando as duas operações são executadas, `validar_operacoes()` impõe:

```text
admissao → demissao
```

Assim, um funcionário presente nos dois retornos termina inativo.

## 6. Mapeamento ERP → Aplicação

| Campo ERP ou requisição | Campo da aplicação | Tipo | Obrigatório | Transformação/Regra |
|---|---|---|---|---|
| Código da empresa no header `Empresa` | `UnidadeFabril.codigo_empresa_erp` e `Funcionario.unidade_fabril` | `int` → `PositiveIntegerField`/FK | Sim | `1 → Matriz`, `2 → Filial MG`, `20 → EVO`; o ID local não é usado. |
| `codFuncionario` | `Funcionario.codigo_funcionario_erp` | `int` ou `str` → `CharField(max_length=125)` | Sim | Inteiro vira string; string recebe `strip()`; nulo, booleano, vazio e valor maior que 125 são rejeitados. |
| `nome` | `Funcionario.nome` | `str` → `CharField(max_length=125)` | Sim | Recebe `strip()`; vazio ou valor maior que 125 são rejeitados. |
| `departamento` | `Funcionario.departamento` → `Departamento.descricao` | `str` → FK | Não | Espaços são reduzidos; chave usa `casefold()` em `descricao_normalizada`; nulo/vazio vira FK nula. |
| `secao` | `Funcionario.secao` → `Secao.descricao` | `str` → FK | Não | Mesma regra de departamento; catálogo independente. |
| `situacao` em admissão | `Funcionario.ativo` | `str` → `BooleanField` | Sim em admissão | `ativo` resulta em `True`; `inativo`, `demitido` e `desligado` resultam em `False`. |
| `situacao` em demissão | `Funcionario.ativo` | Não utilizado | Não | O serviço força `False`. |
| `dataAdmissao=AAAAMM` | Nenhum campo local | `str` | Parâmetro | Filtra admissões; não é persistido. |
| `dataDemissao=AAAAMM` | Nenhum campo local | `str` | Parâmetro | Filtra demissões; não é persistido. |
| Header `Authorization` | Nenhum campo local | `str` | Sim para API | Token é enviado sem prefixo automático e não é persistido/logado. |

### Transformações de texto

`preparar_descricao_catalogo()` reduz espaços consecutivos e remove espaços nas
extremidades. `normalizar_descricao_catalogo()` aplica também `casefold()` para gerar a
chave única do catálogo. `normalizar_nome()` reduz espaços e aplica `casefold()` para a
reconciliação de legados; não há remoção de acentos.

### Campos locais não sincronizados

O model `Funcionario` possui `id`, código ERP, nome, unidade, departamento, seção e
status. O fluxo atual não define campos para data de admissão, data de demissão, e-mail,
telefone ou outros atributos. **Não identificados na implementação analisada.**

Na nova aplicação, cada campo adicional deve ser classificado como sincronizável,
calculado localmente, manual ou preservado após inativação.

## 7. Scheduler

### Tecnologia e processo

O scheduler é o **cron do sistema operacional**, executado em foreground dentro do
container `scheduler`. Não há biblioteca Python de agendamento.

O processo é:

```yaml
entrypoint: ["cron", "-f", "-L", "8"]
```

`-f` mantém o processo em primeiro plano e `-L 8` define o nível de log do cron da
imagem.

### Frequência atual

O arquivo `docker/cron/sincronizar-funcionarios` contém:

```cron
CRON_TZ=America/Sao_Paulo

0 7 * * 1-5 root ... sincronizar_funcionarios --operacao demissao
0 19 * * 1-5 root ... sincronizar_funcionarios --operacao demissao
0 7 * * 0 root ... sincronizar_funcionarios --operacao admissao
```

| Operação | Frequência atual |
|---|---|
| Demissão | Segunda a sexta às 07:00 e 19:00. |
| Admissão | Domingo às 07:00. |

O contexto operacional registra que as duas execuções diárias de desligamento já foram
confirmadas em produção. A execução dominical de admissões ainda aguarda a primeira
confirmação operacional.

### Timezone

As configurações estão alinhadas em três pontos:

- `TIME_ZONE = "America/Sao_Paulo"` no Django, usado para o período padrão;
- `CRON_TZ=America/Sao_Paulo` no arquivo de cron;
- `TZ: America/Sao_Paulo` no serviço `scheduler` do Compose.

### Inicialização, reinicialização e concorrência

O cron é instalado no build da imagem. Ao iniciar, o Compose substitui o entrypoint
normal por cron em foreground. Com `restart: always`, o Docker reinicia o container se
o processo terminar e a tabela instalada na imagem volta a ser usada.

O scheduler não executa migrations por conta própria. `entrypoint.sh` é usado pelo
`web` para aguardar o banco, aplicar migrations, coletar estáticos e iniciar Gunicorn;
o `scheduler` substitui esse entrypoint por cron. Não há healthcheck nem dependência
condicionada à saúde do banco.

`_lock_de_sincronizacao()` usa no PostgreSQL:

```sql
SELECT pg_try_advisory_lock(9042026)
```

Só uma sincronização completa adquire o lock. Outra execução retorna um `SyncResult`
com erro e não processa empresas. O lock é liberado no bloco `finally`. Em bancos não
PostgreSQL, o helper não cria esse lock global.

### Reutilização e adaptação

Reutilizável:

- arquivo de cron separado do código Python;
- chamada do command com `--operacao`;
- wrapper para repassar ambiente;
- lock global no serviço;
- timezone explícito;
- confirmação por logs.

Específico e adaptável:

- horários, dias e periodicidade;
- operação em cada entrada;
- nome do command;
- timezone da nova aplicação.

O ponto exato para alterar a frequência é `docker/cron/sincronizar-funcionarios`. A
frequência atual não é requisito da nova aplicação.

## 8. Configuração do Scheduler no Docker

### Serviço responsável

O serviço de `docker-compose.yml` é:

```yaml
scheduler:
  build: .
  container_name: sorteio_scheduler
  entrypoint: ["cron", "-f", "-L", "8"]
  env_file:
    - .env
  environment:
    TZ: America/Sao_Paulo
  depends_on:
    - db
  restart: always
```

Características confirmadas:

- usa a mesma imagem do `Dockerfile`;
- recebe o `.env`;
- alcança o banco pelo hostname interno `db`;
- não monta volume específico para código ou cron;
- reinicia com `restart: always`;
- não possui healthcheck próprio;
- `depends_on` controla ordem de inicialização, não readiness.

### Dockerfile e instalação

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron gcc libpq-dev netcat-traditional tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY docker/cron/sincronizar-funcionarios /etc/cron.d/sincronizar-funcionarios
COPY docker/cron/run-sincronizar-funcionarios /usr/local/bin/run-sincronizar-funcionarios
RUN chmod 0644 /etc/cron.d/sincronizar-funcionarios \
    && chmod 0755 /usr/local/bin/run-sincronizar-funcionarios \
    && crontab /etc/cron.d/sincronizar-funcionarios
```

Como o cron é copiado para a imagem, mudanças exigem rebuild:

```bash
docker compose up -d --build scheduler
```

### Wrapper de ambiente

O daemon cron não repassa automaticamente o ambiente recebido pelo processo principal.
`run-sincronizar-funcionarios` lê, por padrão, `/proc/1/environ`, extrai uma allowlist
e exporta:

```sh
DATABASE_URL
ERP_FUNCIONARIOS_API_URL
ERP_FUNCIONARIOS_API_TOKEN
ERP_FUNCIONARIOS_API_TIMEOUT
ERP_FUNCIONARIOS_API_VERIFY_SSL
ERP_FUNCIONARIOS_API_CA_BUNDLE
```

Depois executa o command com `exec "$@"`. Não grava nem imprime o token.
`SCHEDULER_ENVIRON_PATH` permite substituir o caminho, principalmente em testes.

### Banco e dependências entre containers

O command usa `DATABASE_URL` e o Django ORM para acessar o PostgreSQL; o scheduler não
tem banco separado. Não há espera explícita por migrations no scheduler, e não há
healthcheck configurado. Essa estratégia deve ser revista se a nova aplicação tiver
requisitos de readiness mais rígidos.

### Partes copiáveis e partes adaptáveis

Podem ser reutilizados conceitualmente o serviço dedicado, cron na imagem, wrapper,
allowlist, redirecionamento para stdout/stderr do container e `restart: always`.

Devem ser adaptados a imagem, caminhos, nome do command, variáveis do wrapper,
hostname do banco, frequência, timezone, readiness e política de healthcheck.

## 9. Variáveis de Ambiente

| Variável | Finalidade | Obrigatória | Exemplo seguro |
|---|---|---:|---|
| `ERP_FUNCIONARIOS_API_URL` | URL completa do endpoint configurável | Sim | `https://erp.exemplo.local/api/funcionarios` |
| `ERP_FUNCIONARIOS_API_TOKEN` | Valor enviado no header `Authorization` | Sim | `<ERP_TOKEN>` |
| `ERP_FUNCIONARIOS_API_TIMEOUT` | Timeout HTTP em segundos | Não; padrão `10` | `10` |
| `ERP_FUNCIONARIOS_API_VERIFY_SSL` | Habilita validação do certificado SSL | Não; padrão `True` | `True` |
| `ERP_FUNCIONARIOS_API_CA_BUNDLE` | Caminho opcional do bundle de CA | Não | `/etc/ssl/certs/erp-ca.pem` |
| `DATABASE_URL` | Conexão Django com PostgreSQL | Sim | `postgresql://<DATABASE_USER>:<DATABASE_PASSWORD>@db:5432/<DATABASE_NAME>` |
| `SCHEDULER_ENVIRON_PATH` | Sobrescreve arquivo lido pelo wrapper | Não; padrão `/proc/1/environ` | `/proc/1/environ` |

O serviço Compose define `TZ=America/Sao_Paulo` diretamente em `environment`. Essa
variável não é lida pelo `ERPClient`.

### `.env.example` atual

```env
ERP_FUNCIONARIOS_API_URL=
ERP_FUNCIONARIOS_API_TOKEN=
ERP_FUNCIONARIOS_API_TIMEOUT=10
ERP_FUNCIONARIOS_API_VERIFY_SSL=True
ERP_FUNCIONARIOS_API_CA_BUNDLE=
DJANGO_ADMIN_URL=painel-interno/
```

Embora não esteja no `.env.example`, `DATABASE_URL` é necessária para executar Django e
o command. Credenciais reais nunca devem ser versionadas.

### Exemplo para a nova aplicação

```env
# Banco usado pelo Django e pelo scheduler
DATABASE_URL=postgresql://<DATABASE_USER>:<DATABASE_PASSWORD>@db:5432/<DATABASE_NAME>

# ERP
ERP_FUNCIONARIOS_API_URL=https://erp.exemplo.local/api/funcionarios
ERP_FUNCIONARIOS_API_TOKEN=<ERP_TOKEN>
ERP_FUNCIONARIOS_API_TIMEOUT=10
ERP_FUNCIONARIOS_API_VERIFY_SSL=True
ERP_FUNCIONARIOS_API_CA_BUNDLE=

# Outras configurações da aplicação, se aplicáveis
DJANGO_SECRET_KEY=<DJANGO_SECRET_KEY>
```

O código tem SSL habilitado por padrão. O contexto operacional registra que um ambiente
de produção precisou operar com validação desabilitada devido à cadeia intermediária
incompleta do servidor ERP; isso é uma exceção de infraestrutura, não recomendação para
a nova aplicação.

## 10. Tratamento de Erros e Logs

### Exceções do cliente

| Situação | Exceção |
|---|---|
| URL/token ausente, timeout inválido, booleano inválido ou operação desconhecida | `ERPConfigurationError` |
| Timeout, `socket.timeout`, `URLError`, `OSError` ou `ssl.SSLError` | `ERPConnectionError` |
| HTTP 4xx/5xx ou status fora de 2xx | `ERPHTTPError` |
| UTF-8/JSON inválido, raiz não objeto, `data` ausente ou `data` não lista | `ERPResponseError` |

`ERPHTTPError` preserva o status HTTP, mas não inclui o corpo da resposta. O token não
é incluído na mensagem da exceção.

### Falha parcial

Em `_sincronizar_empresa()`:

- falha conhecida da API é registrada para empresa e operação;
- o serviço continua na próxima operação e nas demais empresas;
- falha inesperada de consulta também é registrada;
- a empresa é marcada com falha quando a consulta falha ou ocorre falha de configuração
  tratada no nível externo.

Em `_processar_registros()` cada item é independente. São capturados
`InvalidEmployeeRecord`, `AmbiguousLegacyEmployee`, `IntegrityError` e exceções
inesperadas de persistência. O registro é contado em `ignorados`, recebe empresa,
operação, detalhe e posição na lista, e o próximo item continua.

Uma exceção genérica surgida durante persistência é classificada como erro inesperado
no nível do registro. Uma `SyncConfigurationError` levantada nessa persistência também
fica abrangida pelo tratamento genérico do registro; portanto, não necessariamente
incrementa `empresas_com_falha`. Essa é uma nuance do código atual que deve ser
considerada ao reproduzir ou melhorar a implementação.

### Transações

As chamadas HTTP ficam fora de `transaction.atomic()`. Cada registro válido é persistido
em transação própria. `select_for_update()` bloqueia funcionário e unidade durante a
persistência. Assim, erro de uma linha não desfaz todo o lote.

### Retry e próxima execução

**Não há retries automáticos.** Falhas ficam no resultado da execução. Reprocessamento
manual ou nova execução pode tentar novamente; não há checkpoint persistido e o fluxo
é idempotente para registros já processados.

Adicionar retry com backoff é **Recomendação para a nova aplicação**, não comportamento
atual. Se adotado, deve respeitar timeout total e não repetir indefinidamente falhas 4xx.

### Logs

`settings.py` configura o logger `funcionarios.services` no nível `INFO`, com console e
formato:

```text
{asctime} {levelname} {name}: {message}
```

O serviço registra início/fim, operações, lock ocupado, falhas de consulta, registros
ignorados, violações de integridade, erros inesperados e contadores. Usa `INFO` para
fluxo normal, `WARNING` para lock/ignorados, `ERROR` para falhas controladas e
`logger.exception()` para traceback de erros inesperados.

O command imprime JSON no stdout e lança `CommandError` quando há erros, resultando em
falha operacional. O cron envia stdout/stderr para `/proc/1/fd/1` e `/proc/1/fd/2`,
permitindo coleta pelo Docker. Token, Authorization e secrets não são exibidos.

## 11. Dependências

| Componente | Versão/configuração atual | Uso |
|---|---|---|
| Python | `3.12` na imagem | Runtime. |
| Django | `6.0.5` | Command, ORM, Admin e transações. |
| PostgreSQL | `16` no Compose | Banco. |
| `psycopg2-binary` | `2.9.12` | Driver PostgreSQL. |
| `urllib.request` | Biblioteca padrão | HTTP. |
| `ssl` | Biblioteca padrão | SSL/CA. |
| `json` | Biblioteca padrão | Resposta JSON. |
| `dj-database-url` | `3.1.2` | `DATABASE_URL`. |
| `python-dotenv` | `1.2.2` | `.env`. |
| `cron` | Pacote Debian do Dockerfile | Scheduler. |
| `tzdata` | Pacote Debian/dependência Python | Timezone. |
| Docker Compose | `docker-compose.yml` | Orquestração. |

Não foram identificados Celery, Redis, RabbitMQ, APScheduler, biblioteca de retry,
`requests`, `httpx` ou fila de mensagens. O cliente HTTP usa somente a biblioteca
 padrão.

## 12. Como Reutilizar na Nova Aplicação

### Componentes que podem ser reutilizados

1. Separação entre cliente HTTP e serviço de domínio.
2. Parâmetros distintos para admissão e demissão.
3. Identidade estável por empresa + código ERP.
4. Constraint no banco combinada com lookup idempotente.
5. Vínculo de legado por nome normalizado somente com candidato único.
6. Transação independente por funcionário.
7. `select_for_update()` e lock global PostgreSQL.
8. Resultado estruturado com contadores, erros e detalhamento por empresa.
9. Um mesmo service para command, Admin e scheduler.
10. Wrapper de ambiente sem gravar token em arquivo.

### Componentes que precisam ser adaptados

- models e nomes dos campos da nova aplicação;
- empresas, unidades e códigos ERP;
- endpoint e contrato do ERP, se diferentes;
- campos obrigatórios, opcionais e valores de situação;
- lista de campos que o ERP pode atualizar;
- regra para mudança de empresa;
- efeito de desligamento sobre veículo, escala ou operação;
- nome do command, imagem e caminhos Docker;
- allowlist do wrapper;
- frequência, timezone, readiness e healthcheck.

### Configurações específicas da nova aplicação

Definir antes da implementação:

1. model que representa funcionário/motorista e models de unidade;
2. possibilidade de repetir código em empresas diferentes;
3. campos sob autoridade do ERP;
4. significado de `ativo`;
5. persistência de datas do ERP;
6. política para demitido associado a recurso operacional;
7. operação em cada frequência;
8. política para ausência no retorno;
9. resolução de conflitos legados;
10. política de retry;
11. estratégia de migrations e readiness;
12. evidências necessárias para confirmar o cron.

### Ordem recomendada

1. Inspecionar models e status da nova aplicação.
2. Confirmar contrato do endpoint com exemplos não sensíveis.
3. Criar identidade ERP e constraints.
4. Criar cliente HTTP com timeout, SSL, headers e validações.
5. Implementar normalização e validação de payload.
6. Implementar resolução de unidade e catálogos.
7. Implementar criação, atualização e inativação.
8. Adicionar lock, `select_for_update()` e transações.
9. Criar resultado estruturado e falha parcial.
10. Criar command com período e operações.
11. Escrever testes unitários, de banco e de concorrência.
12. Executar carga inicial controlada e revisar ambiguidades.
13. Configurar container, cron e wrapper.
14. Definir a nova frequência no arquivo de cron.
15. Validar execução manual e depois execução automática real.

### O que não copiar sem decisão

- mapa `1/2/20` e nomes `Matriz`, `Filial MG` e `EVO`;
- frequência de dias úteis/domingo;
- nomes e campos dos models;
- criação de demitido inexistente;
- regra de não inativar por ausência;
- desabilitação de SSL;
- departamentos/seções;
- vínculos operacionais da aplicação de destino.

## 13. Checklist de Implementação

### Contrato e configuração

- [ ] Confirmar endpoint e caminho reais do ERP.
- [ ] Confirmar headers, autorização e códigos de empresa.
- [ ] Criar `ERP_FUNCIONARIOS_API_URL`.
- [ ] Criar `ERP_FUNCIONARIOS_API_TOKEN` fora do código/Git.
- [ ] Definir timeout positivo.
- [ ] Configurar SSL e, se necessário, bundle de CA.
- [ ] Configurar `DATABASE_URL` no scheduler.
- [ ] Definir timezone.

### Models e identidade

- [ ] Criar código estável do funcionário no ERP.
- [ ] Mapear empresa ERP para unidade/filial.
- [ ] Criar constraint empresa + código ERP.
- [ ] Definir tratamento de legados sem código.
- [ ] Criar chaves normalizadas para catálogos.
- [ ] Definir campos atualizáveis e preservados após desligamento.

### Cliente ERP

- [ ] Isolar cliente HTTP do ORM.
- [ ] Implementar parâmetros de admissão e demissão.
- [ ] Enviar `Accept`, `Empresa` e `Authorization`.
- [ ] Aplicar timeout.
- [ ] Validar status, UTF-8, JSON e `data` como lista.
- [ ] Classificar configuração, conexão, HTTP e resposta.
- [ ] Decidir política de retry.

### Serviço

- [ ] Validar período `AAAAMM`.
- [ ] Validar cada registro.
- [ ] Resolver empresa/unidade.
- [ ] Criar/recuperar catálogos.
- [ ] Buscar por empresa + código ERP.
- [ ] Vincular legado por nome único, se aplicável.
- [ ] Implementar criação de admitidos.
- [ ] Implementar atualização idempotente.
- [ ] Implementar inativação explícita por demissão.
- [ ] Decidir demitido inexistente.
- [ ] Decidir comportamento para ausência no retorno.
- [ ] Usar `transaction.atomic()` por registro.
- [ ] Usar `select_for_update()`.
- [ ] Usar lock global em PostgreSQL.
- [ ] Preservar falha parcial.
- [ ] Produzir resultado sem secrets.

### Command e Admin

- [ ] Criar command manual.
- [ ] Aceitar período explícito e padrão.
- [ ] Aceitar operações individuais e completas.
- [ ] Imprimir JSON com contadores e erros.
- [ ] Retornar código não zero quando houver falhas.
- [ ] Criar tela Admin protegida, se necessária.
- [ ] Não exibir token ou corpo sensível.

### Docker e scheduler

- [ ] Criar processo/container do scheduler.
- [ ] Instalar cron ou mecanismo escolhido.
- [ ] Copiar configuração para a imagem.
- [ ] Copiar wrapper, se necessário.
- [ ] Definir allowlist de variáveis.
- [ ] Definir a nova frequência.
- [ ] Configurar timezone.
- [ ] Configurar restart e dependências.
- [ ] Definir readiness e migrations.
- [ ] Rebuildar após mudanças no cron.
- [ ] Confirmar execução automática real nos logs.

### Testes e operação

- [ ] Testar URL, headers e parâmetros de admissão.
- [ ] Testar URL, headers e parâmetros de demissão.
- [ ] Testar timeout, conexão, SSL, HTTP e JSON inválido.
- [ ] Testar resposta vazia válida.
- [ ] Testar criação, atualização e repetição.
- [ ] Testar demissão e preservação de histórico.
- [ ] Testar mesmo código em empresas diferentes.
- [ ] Testar duplicidade na mesma empresa.
- [ ] Testar legado único e ambíguo.
- [ ] Testar falha de uma empresa sem interromper as demais.
- [ ] Testar lock concorrente.
- [ ] Testar ordem admissão → demissão.
- [ ] Confirmar que token/secrets não aparecem em logs, JSON ou telas.
- [ ] Executar carga inicial controlada.
- [ ] Conferir criados, atualizados, inativados e ignorados.
- [ ] Confirmar o primeiro ciclo automático de cada operação.
