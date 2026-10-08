# Histórico do projeto

> Arquivo de referência com histórico, decisões fechadas, procedimentos e
> contexto operacional detalhado. Para saber o estado atual e os próximos
> passos, consulte [`CONTEXTO_RETOMADA.md`](CONTEXTO_RETOMADA.md). Registros
> abaixo preservam o contexto em que foram escritos; em caso de divergência de
> estado, prevalece o resumo de retomada atualizado.

Conteúdo arquivado a partir do contexto atualizado em **24/09/2026**.

---

## 1. O que é o projeto

Aplicação Django para **controle de viagens de veículos** e **rateio do custo
de combustível por centro de custo**. O operador da portaria lança as viagens
de todos os colaboradores; periodicamente um **fechamento** soma a
quilometragem do período e distribui o custo proporcionalmente.

Em cima disso foi construído o **pré-cadastro de viagens**: as reservas de
veículo nascem no Outlook (cada veículo é uma caixa de recurso) e são
importadas pela Microsoft Graph, para que a portaria só precise preencher a
quilometragem.

Django 6.0.5 · PostgreSQL · templates server-side com Tailwind (CDN) + DaisyUI
+ htmx · sem build de JS · Docker Compose para deploy.

---

## 2. Documentos relacionados

| Documento | O que traz |
|---|---|
| **este arquivo** | resumo histórico, decisões fechadas, armadilhas e procedimentos |
| [`superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md`](superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md) | desenho aprovado da sincronização ERP |
| [`superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md`](superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md) | plano detalhado de implementação da sincronização ERP — **aprovado, é o que está em andamento agora** |
| [`../DEVELOPMENT.md`](../DEVELOPMENT.md) | arquitetura, modelos, URLs, decisões de projeto e o porquê de cada uma |
| [`PRE_CADASTRO_VIAGENS.md`](PRE_CADASTRO_VIAGENS.md) | desenho completo do pré-cadastro/agenda e da integração (5 fases) |
| [`UTILIZACOES_DO_SISTEMA.md`](UTILIZACOES_DO_SISTEMA.md) | manual de operação: usuários, permissões, sync, lançamento, fechamento |
| [`DEPLOY.md`](DEPLOY.md) | subir no servidor Ubuntu: compose, porta 5009, scheduler de 15 min |
| [`SINCRONIZACAO.md`](SINCRONIZACAO.md) | guia rápido de sincronizar reservas pelo shell/CLI |
| [`../ESTUDO.md`](../ESTUDO.md) | roteiro de estudo do backend + caça aos bugs conhecidos |

---

## 3. Estado atual

**As 5 fases do pré-cadastro estão implementadas, e sobre elas foram
construídos: perfis de acesso, reserva manual, sync pela tela, exportação em
CSV para o ERP e o deploy dockerizado.** A estrutura inicial da sincronização
de funcionários pelo ERP também foi iniciada: identidade ERP, código da
empresa nas unidades fabris, catálogos de departamento/seção e carga pelo
CSV real já estão implementados.

A suíte completa executada em SQLite teve 176 testes: 27 esqueletos de estudo
com `skipTest`, 1 `@expectedFailure` e 1 falha antiga no teste
`ViagemEmAndamentoTest.test_aviso_aparece_no_modal_de_confirmacao`, que também
falha isoladamente com resposta 302. Os testes focados da frente ERP passam.

```
python manage.py test          →  1 falha antiga (ver acima)
python manage.py check         →  sem problemas
makemigrations --check         →  No changes detected
docker compose config          →  válido
```

Migrations existentes no código: `viagens` até `0009_permissoes_de_perfil`,
`colaboradores` até `0005_departamento_secao_funcionario_catalogos`. O banco
real precisa executar `python manage.py migrate` antes de usar os novos
campos.

### O que foi feito em 14/08

| Frente | Onde |
|---|---|
| **Perfis de acesso** — Portaria e Financeiro, `/admin` fechado para os dois | `colaboradores/permissoes.py`, `mixins.py`, `controle_veiculos/admin.py` |
| **Reserva manual** pelo painel + botão **Sincronizar** na agenda | `NovaReservaView`, `SincronizarReservasView`, `viagens/sincronizacao.py` |
| **Exportação em CSV** (era `.xlsx`), rateio e viagens em arquivos separados | `viagens/exports.py` |
| **Bug corrigido:** veículo podia ser reservado duas vezes no mesmo horário | `ReservaViagem.clean()`, `periodos_se_sobrepoem()` |
| **Aviso de reservas pendentes** no fechamento | `_pendencias_do_periodo.html` |
| **Deploy dockerizado** — nginx :5009 + scheduler de 15 min | `docker-compose.yml`, `scheduler.sh`, `docs/DEPLOY.md` |

### Avanço em 15–16/09/2026 — base da sincronização ERP

| Frente | Onde |
|---|---|
| **Código ERP do funcionário** — campo opcional/indexado; identidade composta com a unidade | `Funcionario.codigo_funcionario_erp`, migration `0003` |
| **Código ERP da empresa** — campo opcional e único por Unidade Fabril | `UnidadeFabril.codigo_empresa_erp`, migration `0004` |
| **Catálogos ERP** — Departamento e Seção; seção é única dentro do departamento | `Departamento`, `Secao`, migration `0005` |
| **Vínculos no funcionário** — Departamento e Seção opcionais para legados | `Funcionario.departamento`, `Funcionario.secao` |
| **Admin** — códigos, catálogos e novos vínculos visíveis | `colaboradores/admin.py` |
| **Carga inicial pelo CSV** — aceita `funcionarios.csv` real e o formato antigo | `cadastro_funcionarios.py`, `colaboradores/tests.py` |

O arquivo `colaboradores/management/commands/funcionarios.csv` tem 207
registros e está em UTF-8 com BOM. O command resolve `Código Empresa` pelo
`UnidadeFabril.codigo_empresa_erp`, grava `Funcionário` em
`codigo_funcionario_erp`, cria automaticamente 4 departamentos e 38 seções e
permite códigos de funcionário repetidos em empresas diferentes. O nome
duplicado de LEODATO CHRISTIANO JUNKES foi mantido em dois cadastros, conforme
decisão operacional do usuário.

Uma segunda execução no mesmo banco temporário produziu 0 cadastros, 0
atualizações e 207 registros já existentes.

### Avanço em 22/09/2026 — desenho da sincronização ERP aprovado

Foi lida e discutida a documentação de referência
`DOCUMENTACAO_SINCRONIZACAO_FUNCIONARIOS_ERP.md`. O desenho específico para
este projeto foi aprovado, mas **a sincronização pela API ainda não foi
implementada**.

A especificação está em
[`superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md`](superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md).
O arquivo é novo e ainda não foi commitado porque o `.git` estava montado
como somente leitura; não tentar incluir as alterações pré-existentes do
usuário no commit.

### Avanço em 23/09/2026 — sincronização ERP implementada

O plano detalhado está em
[`superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md`](superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md).
**A implementação foi concluída nesta sessão** (a pedido explícito do
usuário — "quem vai implementar é você" —, uma exceção ao padrão geral do
projeto descrito na §8; ver [`superpowers/plans/...-plano.md`](superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md)
§10–12 para o detalhamento das decisões tomadas ao codar).

| Frente | Onde |
|---|---|
| Migration `data_admissao`/`data_demissao` em `Funcionario` | `colaboradores/migrations/0006_...py` |
| Cliente HTTP do ERP (borda, sem conhecer models) | `colaboradores/integracoes/erp.py` |
| Serviço de sincronização (regra de negócio) | `colaboradores/sincronizacao_erp.py` |
| Comando de linha de comando | `colaboradores/management/commands/sincronizar_funcionarios_erp.py` |
| Botão protegido no Admin (GET confirma, POST executa) | `colaboradores/admin.py`, `colaboradores/templates/admin/colaboradores/funcionario/` |
| Cron real no container (4 horários fixos, seg-sex) | `docker/cron/`, `Dockerfile`, serviço `scheduler-erp` em `docker-compose.yml` |
| Variáveis novas | `.env` — `ERP_FUNCIONARIOS_API_URL`, `ERP_FUNCIONARIOS_API_TOKEN` (vazio, falta preencher), `ERP_FUNCIONARIOS_API_TIMEOUT` |

Decisão fechada nesta sessão: o agendamento usa **cron real** dentro de um
container novo (`scheduler-erp`), não o laço `sleep` do `scheduler.sh` — o
laço serve bem para intervalo (Outlook, a cada 15 min), mas não para
horário de relógio fixo. É a primeira vez que o projeto usa cron.

⚠️ **Lacuna do desenho resolvida por decisão própria, não pelo usuário:**
o desenho aprovado em 22/09 não dizia o que fazer quando uma **demissão**
retorna um código ERP que não existe localmente. Foi implementado criar o
registro já inativo (simétrico à admissão). **Precisa ser confirmado com o
usuário** — ver a nota no topo de `colaboradores/sincronizacao_erp.py`.

Verificação rodada nesta sessão: `python manage.py test` (206 testes, 30
novos — só a falha antiga documentada continua falhando),
`python manage.py check`, `makemigrations --check` (sem mudanças) e
`docker compose build web` (a imagem builda, `check` roda dentro dela,
`docker compose config` valida o `scheduler-erp`).

### Validações em 23 e 24/09/2026 — máquina local e Docker de produção OK

O usuário preencheu `ERP_FUNCIONARIOS_API_TOKEN` no `.env` e **validou a
sincronização na própria máquina, contra a API real do ERP** — resultado
confirmado por ele, não pelo Claude (o `10.1.1.220` é um IP interno,
inacessível desta sessão). Comandos usados (ver seção "Como rodar" abaixo):
`python manage.py sincronizar_funcionarios_erp`, com `--operacao` para
rodar admissão/demissão separadas.

Em **24/09/2026**, o usuário confirmou que a sincronização de funcionários
com o ERP foi executada com sucesso dentro do Docker **em produção**. Isso
valida a execução manual da integração a partir do container nesse ambiente.

Ainda falta observar uma execução automática real do cron `scheduler-erp` nos
4 horários (07:15/18:15 admissão, 07:20/18:20 demissão, de segunda a sexta);
até aqui só o formato do arquivo de cron dentro da imagem tinha sido
conferido. A confirmação da execução manual não confirma, por si só, que o
cron já disparou.

Decisões confirmadas para a API:

| Item | Decisão |
|---|---|
| Endpoint | `https://10.1.1.220/api/funcionarios/v10/informacoes` |
| Consultas | `dataAdmissao=AAAAMM` e `dataDemissao=AAAAMM`, sempre as duas |
| Header | `empresa` com `1` Matriz, `2` Filial MG ou `20` EVO; `Authorization` com token bruto |
| Segurança | token no `.env`; SSL explicitamente desabilitado; timeout de 300 s; sem retry |
| Agenda | `America/Sao_Paulo`; admissões 07:15 e 18:15; demissões 07:20 e 18:20, segunda a sexta |
| Admin | botão apenas para superusuários; executa as duas operações do mês corrente e mostra resumo/erros |
| Identidade | `unidade_fabril + codigo_funcionario_erp`; sem vínculo por nome |
| Legados | CLT recebe código manualmente; PJ sem código ERP e manutenção manual |
| Novos usuários | reutilizam `gerar_username(nome)` e recebem senha inutilizável; username existente não muda |

Campos novos planejados em `Funcionario`: `data_admissao` e
`data_demissao`, ambos `null=True, blank=True`. O ERP não atualizará e-mail,
cargo, carteira de saúde ou dependentes.

Regras principais: admissões são processadas antes de demissões; admissão
atualiza apenas `data_admissao`, demissão apenas `data_demissao`; data vazia
limpa o campo correspondente; funcionário retornado em `dataDemissao` é
inativado; ausência na resposta não inativa ninguém; falha de uma empresa,
operação ou registro não interrompe os demais.

Centros de custo usam `codCentroCusto` como `CentroCusto.codigo` e
`centroCusto` como descrição. Centros inexistentes são criados e descrições
divergentes são atualizadas. Centro de custo, departamento ou seção vazios
preservam o vínculo local; departamentos e seções também são criados ou
atualizados quando presentes.

### Banco de desenvolvimento

Zerado e repovoado em 13/08, e usado para os testes de tela em 14/08:

| | |
|---|---|
| colaboradores | 190 |
| centros de custo | 54 |
| unidades fabris | 3 — Matriz, Filial MG, EVO |
| veículos | 3 — os carros reais, **todos com caixa de recurso** |
| reservas | 10 (importadas do Outlook + manuais de teste) |
| viagens / fechamentos | 7 / 2 — resíduo dos testes de tela |
| usuários | `administrador` (superusuário) e 1 no grupo Financeiro |

⚠️ **O grupo Portaria está vazio.** Os testes de tela foram feitos com o
`administrador`, que é superusuário e passa por qualquer permissão — ou seja,
**o caminho da portaria ainda não foi exercitado com um usuário real de
perfil**. Rode `python manage.py criar_portaria --senha ...` antes de concluir
que as telas dela funcionam.

**Os carros reais ganharam caixa de recurso no Outlook** e o `email_recurso`
já está preenchido no banco:

| Placa | Modelo | Caixa de recurso |
|---|---|---|
| `SXK9G85` | CRONOS | `cronossxk9g85@puflexivel.com.br` |
| `SXB9B09` | CRONOS | `cronossxb9b09@puflexivel.com.br` |
| `RLN1J19` | STRADA | `stradarln1j19@puflexivel.com.br` |

Note o domínio: `@puflexivel.com.br`, diferente do `@grupoflexivel.com.br` dos
colaboradores. **O sync contra essas caixas roda com sucesso** — validado em
13/08 pela CLI e em 14/08 **de dentro do container**, pelo scheduler: 5
eventos em 3 caixas, todos casando com um colaborador pelo e-mail. Um segundo
`--dry-run` devolveu `criadas 0 / atualizadas 3`, o que valida a idempotência
pelo `id_externo` contra a API de verdade, e não só em teste.

O andaime que validou a integração (as 8 salas de reunião cadastradas como
veículos) **já foi removido**. O comando `cadastrar_veiculos_salas` continua
no repositório, mas não serve mais para revalidar o caminho real: as salas são
`@grupoflexivel.com.br` e os carros `@puflexivel.com.br`, então ele não
exercita o mesmo caminho de permissão que o sync de produção usa.

⚠️ Os hodômetros (`Veiculo.km_atual`) carregam resíduo das viagens de teste
apagadas (ex.: `RLN1J19` com 110.588 km). É o comportamento projetado — o
recompute preserva o valor do cadastro quando não há viagens — mas hoje é
lixo, e vira o **piso** da primeira viagem real de cada veículo.

### Avanço em 14/09/2026 — integração com o AD adiada

Foi iniciada a descoberta técnica para a integração com o Active Directory,
seguindo o padrão corporativo documentado na skill
`active-directory-integration`. A investigação confirmou que a aplicação ainda
usa o login local nativo do Django: não há dependência LDAP, backend de
autenticação de diretório, campos de vínculo no model ou configuração de
LDAPS. **Nenhuma alteração de código, modelo ou infraestrutura foi feita para
o AD.**

A decisão para a retomada é implementar primeiro a **sincronização de
funcionários com a API do ERP**. O objetivo é manter o cadastro local o mais
atualizado possível com a lista de funcionários antes de iniciar a integração
com o AD. A sincronização com o AD fica deliberadamente adiada até essa etapa
ser concluída; não reabrir a implementação do AD antes disso.

### Estado do Git

O último commit continua sendo `50e7572` ("Aplicação preparada para
Deploy"), mas a frente ERP desta retomada **ainda não foi commitada**. Há
alterações locais em models, Admin, command, testes e migrations. As
alterações pré-existentes do usuário em `DEVELOPMENT.md`, `ESTUDO.md` e
`docs/CONTEXTO_RETOMADA.md` devem ser preservadas.

Marcos do histórico, do mais recente para o mais antigo:

| Commit | O que entrou |
|---|---|
| `50e7572` | deploy: scheduler, nginx :5009, `requests` no requirements |
| `8c13edc` | ajustes de tela + aviso de reservas pendentes no fechamento |
| `7403857` | CSV separado (rateio/viagens) + bug do veículo reservado duas vezes |
| `3dd8f74` | perfis de acesso, reserva manual e sync pela agenda |
| `ffe613c` | remoção do `criar_reservas_mock` |

O `criar_reservas_mock` **não existe mais**: ele gerava reservas no formato do
`getSchedule` (endpoint descartado) e nunca gravava `solicitante_email`, a
chave que a integração real usa. Para popular um ambiente hoje, rode o sync de
verdade.

---

## 4. Decisões fechadas — não rediscutir

Cada uma custou discussão e está justificada no documento indicado.

| Decisão | Onde está o porquê |
|---|---|
| `ReservaViagem` é entidade separada de `Viagem` (intenção × fato consumado) | `PRE_CADASTRO_VIAGENS.md` §3 |
| A alternativa (km inicial na reserva) foi avaliada e descartada | §11.1 — **leia antes de propor de novo** |
| Estado da viagem é **derivado** de `km_final IS NULL`, não um campo `status` | §11 |
| `ReservaViagem.status` é campo real (três estados, "cancelada" não é ausência) | §4 |
| Relação reserva × viagem é **1:1** | §10 |
| Dois fluxos de lançamento: saída/chegada em duas etapas, ou tudo de uma vez | §11 |
| Janela do sync: **hoje até +90 dias** | §10 |
| Chave de junção com o Outlook: campo **`email` nativo** do `AbstractUser` | §8 |
| Identidade da reserva importada: **`id_externo`**, nunca chave natural | §8.1 |
| Endpoint: **`calendarView`**, não `getSchedule` (só ele traz `id` e organizador) | §8 |
| Agendamento em produção: serviço `scheduler` no compose, laço com `sleep` | §8.2 |
| Validação em **três camadas** (formulário / `Model.clean()` / banco) | `DEVELOPMENT.md` §3.8 |
| Centro de custo e e-mail são **opcionais** no cadastro (produção não viaja) | docstring de `cadastro_funcionarios` |
| Política de acesso mora em **um arquivo só**, aplicada por `configurar_perfis` | `colaboradores/permissoes.py` |
| Portaria **manteve** o fechamento — o pedido era criar o financeiro, não reduzi-la | `permissoes.py`, comentário em `PERMISSOES_POR_PERFIL` |
| Reserva pendente no fechamento **avisa, não bloqueia** (não carrega km) | `DEVELOPMENT.md` §3.7, docstring de `contar_reservas_viagem_pendentes` |
| Exportação: **dois arquivos**, e o do ERP é tabela pura (sem total, sem título) | `DEVELOPMENT.md` §3.7 |
| CSV em `;` + BOM + vírgula decimal (destino é Excel pt-BR) | `DEVELOPMENT.md` §3.7 |
| Sobreposição de reserva vive em `Model.clean()`, **sem** constraint de banco | `DEVELOPMENT.md` §3.9 |
| Sync **não** é barrado pela regra de sobreposição (Outlook é a fonte da verdade) | `DEVELOPMENT.md` §3.9 |
| Deploy: só o nginx publica porta; `DATABASE_URL` sobreposto pelo compose | `DEPLOY.md` §3 |
| `UnidadeFabril.codigo_empresa_erp` é a chave para a coluna `Código Empresa` do CSV | `colaboradores/models.py`, `cadastro_funcionarios.py` |
| Identidade do funcionário ERP é `unidade_fabril + codigo_funcionario_erp`; o código pode repetir entre empresas | migration `0005`, `cadastro_funcionarios.py` |
| Seção é comparada dentro do Departamento; a mesma descrição em departamentos diferentes gera registros distintos | `Secao`, constraint `uniq_secao_por_departamento` |
| O CSV ERP cria Departamento e Seção automaticamente e preserva e-mail/centro de custo quando ausentes em uma atualização | `cadastro_funcionarios.py` |
| Sincronização ERP usa `select_for_update()` por registro, sem lock global do Postgres | `colaboradores/sincronizacao_erp.py` |
| Sincronização ERP: cron real num container próprio (`scheduler-erp`), não o laço `sleep` do `scheduler.sh` | `docker/cron/`, `docker-compose.yml` |
| Botão de sincronização ERP no Admin: GET só confirma, POST executa | `colaboradores/admin.py` |
| Demissão de código ERP desconhecido cria funcionário já inativo (decisão própria, lacuna do desenho — revisar com o usuário) | `colaboradores/sincronizacao_erp.py` |

---

## 5. Armadilhas já pagas

Coisas que quebraram de verdade neste projeto. Não repita.

**`Model.save()` não valida.** `full_clean()` só é chamado por formulários e
pelo admin. Todo código que monta uma `Viagem` fora de um ModelForm precisa
chamar `full_clean()` explicitamente — e chamar `congelar_centro_custo()`
antes, porque o `save()` é que preencheria o centro de custo e a validação de
campo roda primeiro.

**`date.today()` usa o relógio do sistema.** Em container UTC, das 21h de
Brasília em diante já é o dia seguinte. Use `timezone.localdate()` no Django e
`datetime.now(FUSO)` na integração. Isso já causou dois bugs.

**`clean()` recebe objeto pela metade.** Roda mesmo quando outro campo falhou
na validação de campo, então todo `clean()` precisa de `is not None` antes de
comparar. Um `None > date` derruba a tela com 500.

**FK obrigatória levanta em vez de devolver `None`.** Com `null=False`,
`self.veiculo` levanta `RelatedObjectDoesNotExist` quando o campo não foi
preenchido — não devolve `None`. Pergunte à coluna (`self.veiculo_id`) antes
de tocar no objeto.

**`add_error` recusa campo que não existe no formulário.** Os formulários de
reserva não têm `data`/`veiculo`/`funcionario` de propósito (vêm da reserva),
então erros do modelo endereçados a eles precisam virar erro geral. É o que
`_aplicar_erros_do_modelo()` em `views.py` faz.

**`select_for_update()` + `select_related()` em FK nulável = erro no Postgres.**
"FOR UPDATE não pode ser aplicado ao lado nulável de uma junção externa". Use
`select_for_update(of=("self",))`.

**Comentário `{# #}` é de uma linha só.** Quebrado em duas, vaza o texto para
o HTML. Para várias linhas, `{% comment %}`.

**Validadores de campo não rodam no `save()`.** O `^\d{10}$` de
`CentroCusto.codigo` nunca foi executado; quem barrou código inválido foi o
`varchar(10)` do Postgres. Normalize na entrada.

**Testes rodam com `DEBUG=False`**, e aí o storage do WhiteNoise exige o
`staticfiles.json` do `collectstatic`. Todo teste que renderiza template usa
`@override_settings(STORAGES=STORAGES_DE_TESTE)` (constante no topo de
`tests.py`).

**A suíte passa no venv e a imagem quebra.** `requests` era usado pelo cliente
do Graph mas nunca entrou no `requirements.txt`; no venv de desenvolvimento o
pacote existia por outro caminho, então 171 testes passavam com a imagem
Docker inutilizável. Hoje o `Dockerfile` roda `python manage.py check` como
etapa do build — dependência esquecida falha o build, não o deploy.

**`requirements.txt` em UTF-16 não é lido pelo pip.** Já quebrou duas vezes
neste projeto; o redirecionamento `>` do PowerShell reintroduz o problema.
Salve sempre em UTF-8.

**Dentro do container, `localhost` é o próprio container.** O `DATABASE_URL`
do `.env` aponta para `localhost` (correto no `runserver`), e no Docker isso
vira "connection refused". O `docker-compose.yml` sobrepõe a variável trocando
o host por `db` — não edite o `.env` para consertar isso.

**`cadastro_funcionarios` pula todo mundo em silêncio** quando as
`UnidadeFabril` não existem: reporta "0 cadastrados" e sai com código zero.
Não há comando para criar as unidades — em ambiente novo, crie
`Matriz`/`Filial MG`/`EVO` antes (ver `DEPLOY.md` §5).

**Shebang com CRLF mata o container** antes de rodar a primeira linha ("exec
format error"), porque o Linux procura o interpretador `/bin/sh
`. O
`Dockerfile` normaliza com `sed` na cópia dos `.sh`.

**Senha do Postgres com caractere especial quebra o `DATABASE_URL`.** Ela é
interpolada dentro de uma URL; `@`, `/`, `#`, `?` e `:` atrapalham a análise.
A senha atual de desenvolvimento termina com `@` e funciona só porque o
`urlsplit` separa no último `@` — não conte com isso em produção.

**O CSV `funcionarios.csv` é UTF-8 com BOM.** O command
`cadastro_funcionarios` usa `utf-8-sig` por padrão e aceita `--encoding cp1252`
para exportações antigas do Excel. A coluna `Código Empresa` não é o nome da
unidade: ela deve encontrar uma `UnidadeFabril.codigo_empresa_erp` já
cadastrada.

**Código de funcionário ERP não é único globalmente.** O arquivo real repete
códigos em empresas diferentes; nunca faça lookup somente por
`codigo_funcionario_erp`. Use sempre a combinação com a unidade fabril.

**O command de carga inicial pode criar dois funcionários com o mesmo nome.**
Isso ocorre quando as identidades ERP são diferentes, como no caso do
proprietário presente em duas empresas. Não reintroduza uma trava global por
nome sem antes resolver essa regra de negócio.

---

## 6. Como rodar

```powershell
# Testes (o usuário do banco precisa de permissão para criar bancos)
python manage.py test viagens
psql -U postgres -c "ALTER ROLE controle_veiculos CREATEDB;"   # se der permissão negada

# Perfis de acesso — rode ANTES de criar os usuários operacionais
python manage.py configurar_perfis
python manage.py configurar_perfis --listar        # confere o que está no banco

# Popular do zero — A ORDEM IMPORTA
python manage.py createsuperuser                   # quem administra o sistema
python manage.py criar_portaria --senha ...        # nunca dá /admin (o --superuser foi removido)
python manage.py criar_financeiro --senha ...      # só fechamento

# Migrations e unidades fabris ANTES dos colaboradores. Os códigos precisam
# corresponder à coluna Código Empresa do CSV ERP.
python manage.py migrate
python manage.py shell -c "from colaboradores.models import UnidadeFabril; [UnidadeFabril.objects.get_or_create(nome=n, defaults={'codigo_empresa_erp': c}) for n,c in [('Matriz',1),('Filial MG',2),('EVO',20)]]"
python manage.py cadastro_centro_custo colaboradores/management/commands/cc.csv
python manage.py cadastro_funcionarios colaboradores/management/commands/funcionarios.csv

# Integração com o Outlook
python manage.py cadastrar_veiculos_salas          # andaime — ver ressalva na §3
python manage.py sincronizar_reservas --dry-run
python manage.py sincronizar_reservas --dias 30
```

### Dockerizado (é como roda em produção)

```bash
docker compose up -d --build       # nginx em http://localhost:5009
docker compose exec web python manage.py migrate
docker compose logs -f scheduler   # o sync de 15 em 15 min
docker compose exec web python manage.py sincronizar_reservas --dry-run
```

O banco do container é **outro** — não é o da sua máquina. Ele sobe vazio e
precisa dos mesmos cadastros acima (ver `DEPLOY.md` §5). Passo a passo completo
do servidor: [`DEPLOY.md`](DEPLOY.md).

Guia detalhado de sincronização pelo shell: [`SINCRONIZACAO.md`](SINCRONIZACAO.md).

Credenciais do Graph vêm do `.env`: `CLIENT_ID`, `SECRETY_VALUE` (sic),
`URL_MICROSOFT`. O `poc_microsoft_graph.py` na raiz é o laboratório de
exploração da API — **não** é usado pela aplicação, que tem seu próprio
cliente em `viagens/integracoes/microsoft_graph.py`.

### Perfis de acesso

A política mora em `colaboradores/permissoes.py` — é o único lugar onde
"quem pode o quê" está escrito.

| Perfil | Pode | Não pode |
|---|---|---|
| **Portaria** | agenda, lançar viagem, reservas, sync, colaboradores, fechamento | `/admin` |
| **Financeiro** | `/viagens/fechamento/` e `/viagens/fechamentos/` | lançar, agenda, reservas, colaboradores, `/admin` |
| **administrador** | tudo, inclusive `/admin` | — |

⚠️ No banco de desenvolvimento o grupo **Portaria está vazio** (Financeiro tem
1 usuário). Os testes de tela foram feitos com o `administrador`, que é
superusuário e ignora permissão — o caminho da portaria com um usuário de
perfil real ainda não foi exercitado.

A portaria **manteve** o fechamento: o pedido foi criar o perfil financeiro e
tirar o `/admin` dela, não reduzir suas atribuições. Para separar as funções
de verdade, remova `PERM_REALIZAR_FECHAMENTO` da lista do `GRUPO_PORTARIA` em
`permissoes.py` e rode `configurar_perfis` de novo.

---

### Atualização em 30/09/2026 — integração com Active Directory validada

O usuário informou que corrigiu as credenciais de bind no `.env` de produção
e confirmou a validação da integração com o Active Directory. Não registrar
credenciais ou outros segredos nos documentos do projeto. Permanecem pendentes
a confirmação da ACL da porta `5009` para o HAProxy e o teste do superusuário
`LOCAL` com o AD indisponível. O estado operacional mais recente está em
[`CONTEXTO_RETOMADA.md`](CONTEXTO_RETOMADA.md); os procedimentos estão em
[`DEPLOY_AD.md`](DEPLOY_AD.md).

## 7. Pendências

Em ordem aproximada de valor.

1. **Confirmar a primeira execução automática do cron `scheduler-erp`** — a
   sincronização manual com o ERP já foi validada na máquina local em
   23/09/2026 e no Docker de produção em 24/09/2026 (ver avanço da mesma
   seção). Ainda é preciso observar o cron nos horários configurados antes de
   confiar no agendamento. Também **decidir com o usuário** a lacuna do
   desenho sobre demissão de código desconhecido (ver nota acima e no topo de
   `colaboradores/sincronizacao_erp.py`). Manter o cadastro local atualizado
   com o ERP continua sendo necessário para os dados operacionais.
2. **Integração com o AD validada em produção** em 30/09/2026, após correção
   das credenciais no `.env`, conforme atualização acima. Ainda falta testar a
   contingência com superusuário `LOCAL` e AD indisponível. O AD não deve ser
   tratado como mecanismo de sincronização de funcionários.
3. **Subir no servidor Ubuntu.** A base anterior está no GitHub, mas a frente
   ERP desta retomada ainda não foi commitada; falta executar o `DEPLOY.md`
   depois de revisar essas alterações. Ao transferir o `.env` por FTP, **quatro linhas
   precisam mudar** (§3 do DEPLOY): `DEBUG=False`, `ALLOWED_HOSTS` com o IP do
   servidor, `CSRF_TRUSTED_ORIGINS` com `http://IP:5009` e uma
   `DJANGO_SECRET_KEY` nova. Sem elas a aplicação não sobe ou não deixa logar.
4. **Testar as telas com um usuário da portaria de verdade**, e não com o
   `administrador` — superusuário ignora permissão, então o controle de acesso
   da portaria nunca foi exercitado pela porta da frente.
5. **Zerar os hodômetros e os dados de teste** antes de considerar o banco de
   desenvolvimento confiável: há 7 viagens e 2 fechamentos de teste.
6. **Caça aos bugs do `ESTUDO.md`** — 7 itens abertos, sendo os dois primeiros
   os que mais importam: viagem retroativa lançada depois do fechamento fica
   órfã, e nada impede fechamentos com períodos sobrepostos.
7. **Colaboradores da EVO sem centro de custo** (ex.: ADONIRAM AMARAL ROCHA,
   e-mail `@evo.ind.br`). Se essas pessoas reservam carro, precisam de centro
   de custo para conseguir lançar viagem.
8. **Reservas de dia inteiro que cruzam vários dias** viram uma reserva só,
   na data de início. Se isso importar, o modelo precisa de data de fim.
9. **Backup automatizado** do Postgres no servidor (cron no host chamando o
   `pg_dump` do `DEPLOY.md` §9) — hoje não existe.
10. **Investigar a falha isolada da suíte** em
    `ViagemEmAndamentoTest.test_aviso_aparece_no_modal_de_confirmacao`, que
    retorna 302 em SQLite mesmo quando executada sozinha.

---

## 8. Como o usuário trabalha

Gustavo é o desenvolvedor do projeto e está **usando este trabalho para
estudar Django** — o `ESTUDO.md` é o roteiro dele. Etapas 1 e 2 concluídas
(caminho da requisição e pipeline de validação).

O que funciona bem com ele:

- **Ele implementa, você revisa.** Ele pede a explicação, escreve o código e
  traz para revisão. Não escreva por ele o que ele pediu para entender.
- **Explique o porquê, não só o quê.** As melhores conversas desta sessão
  foram sobre *por que* uma decisão é assim, não sobre a sintaxe.
- **Corrija com precisão.** Ele recebe bem correção direta e já pegou erros
  meus mais de uma vez. Não amoleça o diagnóstico — mas corrija a afirmação
  errada, não o raciocínio quando ele está certo.
- **Meça antes de afirmar.** Várias vezes o palpite (meu e dele) estava errado
  e o `manage.py shell` resolveu em 30 segundos. Rode o código.
- **Cuidado com o ritmo.** Uma vez despejei três experimentos e conceitos de
  duas etapas à frente de uma vez, e o efeito foi desânimo, não aprendizado.
  Um conceito por vez, com um experimento curto.
- **Bug encontrado vira teste.** É prática estabelecida aqui e já pegou uma
  regressão real.
- **Documentação atualizada faz parte do "pronto"** — código + teste + doc.
- **Ele escreve funções e pede revisão.** Em 14/08 trouxe a
  `contar_reservas_viagem_pendentes` já pronta. Revise de verdade: se estiver
  certa, diga que está certa em vez de inventar problema — naquele caso só
  faltava a docstring com o *porquê*. E não renomeie o que é dele sem motivo.
- **Verifique o teste, não só o código.** Desligar a regra de propósito e ver
  a suíte falhar pegou coisa que `assertNotContains` mascararia. Foi assim que
  se confirmou que a trava do `/admin` e a do veículo reservado funcionam.
- **Cuidado com mudança não pedida.** Reescrevi a mensagem do aviso de viagem
  em andamento "para melhorar" e quebrei um teste dele. Escopo pedido é o
  escopo entregue.
