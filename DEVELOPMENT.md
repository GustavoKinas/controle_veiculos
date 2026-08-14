# Controle de Veículos — Viagens e Rateio de Combustível

Documento de **arquitetura**: modelos, telas e o porquê de cada decisão de
projeto.

> Para **retomar o trabalho** (estado atual, pendências, armadilhas já pagas),
> comece por [docs/CONTEXTO_RETOMADA.md](docs/CONTEXTO_RETOMADA.md).

---

## 1. Visão geral

Aplicação Django para **controle de viagens** e **rateio de custos de
combustível por Centro de Custo**. O usuário-operador (`portaria`) lança as
viagens de todos os colaboradores; periodicamente é feito um **fechamento** que
soma a quilometragem do período e distribui o custo proporcionalmente entre os
Centros de Custo.

- **Framework:** Django 6.0.5 (Python 3.12+)
- **Banco:** PostgreSQL 16 (conexão via `DATABASE_URL` / `dj-database-url`)
- **Servir estáticos:** WhiteNoise
- **Deploy:** Docker Compose (nginx :5009 + web gunicorn + scheduler + db postgres)

---

## 2. Estado inicial e o que foi reestruturado

O repositório foi clonado de outro projeto (um sistema de **sorteio**) e estava
**quebrado / no meio de uma migração**. Correções aplicadas:

| Problema encontrado | Ação |
|---|---|
| Pasta de config chamava-se `controle_viagens`, mas `manage.py`/`wsgi.py`/`settings.py` referenciavam `controle_veiculos` (projeto não subia) | **Renomeada** a pasta para `controle_veiculos` |
| `INSTALLED_APPS` listava apps inexistentes (`controle_veiculos`, `funcionarios`) e não registrava `colaboradores` | Corrigido para `colaboradores` + `viagens` |
| `views.py` importava `FuncionariosSorteados` (não existia) | Removido; views reescritas |
| `base.html` apontava para URLs de sorteio (`sorteio`, `cadastro_sorteio`, `reseta_sorteio`) | Menu lateral reescrito para Viagens/Colaboradores |
| `colaboradores` sem pasta `migrations/` | Criada (obrigatório para custom user model) |
| `requirements.txt` corrompido (UTF-16) | Reescrito em UTF-8 — **regrediu e foi refeito em 08/2026**; salvar com `>` do PowerShell reintroduz o problema |
| `docker-compose.yml` referenciava `sorteio.wsgi` e nomes `sorteio_*` | Ajustado para `controle_veiculos` |
| `STATIC_ROOT` (`/app/static`) divergia do Nginx/Compose (`/app/staticfiles`) | Alinhado para `staticfiles` |

> **Nota importante:** a pasta `controle_veiculos/` (com `settings.py`, `urls.py`,
> `wsgi.py`, `asgi.py`, templates e estáticos) **é o pacote de configuração do
> Django — não um app**. Não apague.

---

## 3. Decisões de arquitetura

### 3.1 Funcionário = Usuário (`AUTH_USER_MODEL`)
`colaboradores.Funcionario` **estende `AbstractUser`** e é o modelo de usuário do
projeto (`AUTH_USER_MODEL = "colaboradores.Funcionario"`).

- **Por quê:** o requisito pede que o Funcionário também sirva de usuário do
  sistema. Trocar o `AUTH_USER_MODEL` depois, com dados em produção, é
  praticamente inviável — então foi definido já na primeira migração.
- **Etapa 1:** apenas o operador `portaria` faz login e lança as viagens de
  todos. Os demais colaboradores existem como cadastro (username gerado
  automaticamente + senha inutilizável via `set_unusable_password()`) e **ainda
  não logam**. No futuro, cada colaborador recebe login próprio.
- `unidade_fabril` e `centro_custo` são **opcionais no banco** (o operador
  `portaria` não pertence a um centro de custo), mas **obrigatórios para quem
  viaja** — isso é garantido no formulário de viagem, que só lista colaboradores
  ativos e com centro de custo.
- Campo `ativo` (regra de negócio: colaborador ativo para viagens) é
  **intencionalmente separado** do `is_active` de autenticação do Django.

### 3.2 Centro de Custo "congelado" na viagem
`Viagem.centro_custo` é uma FK preenchida **no momento do lançamento** a partir
de `funcionario.centro_custo` (em `Viagem.save()`). Assim, se o colaborador
mudar de centro de custo depois, o histórico e os fechamentos antigos
permanecem consistentes.

### 3.3 Status de fechamento via FK (não booleano)
Em vez de um booleano, `Viagem.fechamento` é uma FK para `Fechamento`
(`null=True`). Vantagens:
- `fechamento IS NULL` ⇒ viagem **em aberto** (propriedade `Viagem.fechada`).
- Dá **rastreabilidade**: sabe-se exatamente qual fechamento consumiu a viagem.

### 3.4 Snapshot do rateio (`FechamentoRateio`)
Ao confirmar um fechamento, o rateio por Centro de Custo (km e percentual) é
**gravado** em `FechamentoRateio`. O fechamento fica auditável e imune a
mudanças futuras nos dados.

### 3.5 Fechamento atômico e à prova de concorrência
`viagens/services.py::confirmar_fechamento` roda em `transaction.atomic` e usa
`select_for_update()` para travar as viagens em aberto do período antes de
calcular e marcar. Isso evita que dois fechamentos simultâneos processem a mesma
viagem (garantia de "nunca contar duas vezes").

### 3.6 Busca de colaborador por nome (lançamento de viagem)
O `<select>` de colaborador em `lancar_viagem.html` é filtrado **no cliente**
por um campo de busca (JS puro, sem dependências novas): digitar esconde as
`<option>` cujo texto não contém o termo (comparação acento-insensível via
`normalize("NFD")`, mesmo princípio de `normalizar_texto` usado em
`colaboradores/forms.py`). Escolhido por não exigir bibliotecas externas
(select2/jQuery não estão carregados no projeto) e por ser suficiente para a
escala esperada (algumas centenas de colaboradores).

### 3.7 Exportação em CSV (`viagens/exports.py`)
**Dois arquivos, dois botões:** `exportar_rateio_csv` (o rateio por centro de
custo) e `exportar_viagens_csv` (o detalhamento). Ambos aparecem no banner de
`/viagens/fechamento/?concluido=<id>` e em cada linha de
`/viagens/fechamentos/`.

A geração do texto (`montar_csv_rateio`, `montar_csv_viagens`) é separada da
resposta HTTP, o que permite conferi-la em teste sem fabricar request nem
decodificar `HttpResponse`.

**O rateio é importado no ERP, e isso define a forma do arquivo:** uma linha
de cabeçalho e linhas de dado, cada coluna com um único tipo de informação.
Sem título, sem linha em branco, **sem linha de total** — numa importação,
"Total" na coluna Centro de Custo entra como se fosse mais um centro. O total
é de quem soma a coluna.

Foi por essa exigência que as duas tabelas se separaram: empilhadas no mesmo
arquivo (como eram as duas abas do `.xlsx`, e depois os dois blocos do
primeiro CSV), o arquivo deixava de ser uma tabela.

As datas do período viajam em **coluna**, não num título no topo: é o que
mantém cada linha auto-suficiente na importação.

**Era `.xlsx` com openpyxl até 08/2026.** A troca eliminou a única
dependência binária do projeto — `openpyxl` saiu do `requirements.txt`.

**Três decisões que o formato exige.** O destino do arquivo é o Excel em
português, e um CSV ingênuo abre ilegível nele:

| Escolha | Sem ela |
|---|---|
| `;` como separador | a vírgula é separador decimal no pt-BR; com `,` tudo cai numa coluna só |
| UTF-8 **com BOM** (`utf-8-sig`) | o Excel assume ANSI e "Descrição" vira "DescriÃ§Ã£o" — ele não lê o charset do cabeçalho HTTP |
| decimal com vírgula (`25,00`) | lido como texto; a coluna não soma |

Linhas terminam em `\r\n` (RFC 4180).

**Performance:** as queries usam `select_related` (evita N+1 em
`centro_custo`/`funcionario`) e o texto é montado em memória (`io.StringIO`).
Adequado ao volume real — um fechamento tem, tipicamente, dezenas a algumas
centenas de viagens. Ao contrário do `.xlsx` (contêiner ZIP), CSV *permitiria*
streaming com `StreamingHttpResponse`; não vale a complexidade nesta escala.

### 3.8 Quilometragem validada no modelo (`Viagem.clean`)
As regras de hodômetro vivem em `services.validar_quilometragem` e são
disparadas por `Viagem.clean()` — **não** pelo `clean()` do formulário. Assim
valem para a tela de lançamento, para o admin e para qualquer `full_clean()`
em script/import; o `_post_clean()` do ModelForm já leva os erros para os
campos certos (a função levanta `ValidationError` com dicionário
`{"km_inicial"/"km_final": ...}`).

A regra vive em **três camadas**, de propósito: o formulário decide o que a
tela oferece, o `Model.clean()` dá a mensagem boa no campo certo, e o banco
garante a integridade contra qualquer caminho que não passe por `full_clean()`
(`objects.create()`, `bulk_create()`, import, SQL direto).

Regras, sempre **por veículo**:
1. `km_final > km_inicial` — também gravada como `CheckConstraint`
   (`km_final_gt_km_inicial`) em `Viagem.Meta.constraints`;
2. **piso** — `km_inicial` não pode ser menor que o maior `km_final` já
   registrado para o veículo **até aquela data** (o hodômetro não anda para
   trás). Se o veículo ainda não tem nenhuma viagem, o piso é o `km_atual` do
   cadastro; se só tem viagens *posteriores* à data, não há piso (quem limita
   é a regra 3);
3. **teto** — `km_final` não pode invadir a faixa de um lançamento posterior
   já existente (`Min(km_inicial)` das viagens com `data` maior).

`Viagem.clean()` também recusa **data futura** (a portaria lança a viagem
depois que ela aconteceu). Usa `timezone.localdate()`, e não `date.today()`:
em container UTC, o `today()` do sistema vira o dia seguinte às 21h de
Brasília e rejeitaria lançamentos legítimos da noite. Essa regra fica só na
camada 2 de propósito — uma `CheckConstraint` que consulta o relógio faz o
veredito da mesma linha mudar com o tempo, o que contraria a premissa de que
uma `CHECK` depende apenas dos dados da própria linha.

`Viagem.veiculo` é **obrigatório** desde a migration `0004` (era opcional
apenas porque o cadastro de veículos nasceu depois do de viagens). Isso muda o
comportamento do atributo e é uma armadilha real: com `null=True`,
`self.veiculo` devolvia `None` quando a FK estava vazia; com `null=False`, ele
**levanta `RelatedObjectDoesNotExist`**. Como `Model.clean()` roda antes de
qualquer INSERT — inclusive sobre um objeto pela metade, quando o campo falhou
na validação de campo —, `Viagem.clean()` passa
`self.veiculo if self.veiculo_id else None` para o validador: pergunta à
coluna antes de tocar no objeto. Sem isso, enviar o formulário sem escolher
veículo dá **erro 500** em vez de "este campo é obrigatório".

Pelo mesmo motivo, `validar_quilometragem` e `Viagem.clean()` **acumulam** os
erros num dicionário (`{campo: [mensagens]}`) e têm um único ponto de saída, em
vez de levantar no primeiro problema encontrado — o operador corrige tudo de
uma vez. O `clean()` usa `ValidationError.update_error_dict()`, o mesmo helper
que o `Model.full_clean()` usa internamente para juntar os erros de
`clean_fields()`, `clean()` e `validate_constraints()`.

### 3.9 Veículo não pode ser reservado duas vezes (`ReservaViagem.clean`)
**Bug corrigido em 08/2026.** A tela de reserva manual aceitava reservar um
veículo que já tinha reserva **pendente** no mesmo horário — duas pessoas
saíam com o mesmo carro.

A regra vive em `ReservaViagem.clean()`, não no formulário, para valer também
no admin e em qualquer `full_clean()`. A decisão de sobreposição está em
`periodos_se_sobrepoem()`, função de módulo, testável com pares de horários
soltos, sem montar reserva nem tocar no banco.

O que ocupa o veículo:

| Situação | Bloqueia? |
|---|---|
| reserva **pendente** que se sobrepõe | sim |
| reserva **cancelada** | não — o horário está livre |
| reserva **lançada** | não — já virou viagem |
| períodos que apenas se encostam (08–12 e 12–14) | não |
| reserva de **dia inteiro** (horas nulas) | conflita com qualquer outra do dia |
| mesmo horário, **outro veículo** ou **outro dia** | não |

A comparação é estrita (`<`, não `<=`): 08:00–12:00 e 12:00–14:00 se tocam
mas não disputam o carro, e recusar isso engessaria o uso normal da frota.

**A importação do Outlook não é barrada por esta regra** — o sync usa
`update_or_create`, que não chama `full_clean()`. É proposital: o Outlook é a
fonte da verdade para o que veio dele, e a própria caixa de recurso já recusa
reserva sobreposta na origem. Há teste garantindo que isso continue assim.

**Camada 3 ausente, de propósito declarado.** Ao contrário da quilometragem,
não há constraint de banco: barrar sobreposição em SQL exigiria uma
`ExclusionConstraint` com `btree_gist` e uma coluna de intervalo, mudando o
modelo por causa de uma janela de corrida estreita (dois envios simultâneos
para o mesmo veículo e horário). Se a portaria passar a ter vários operadores
lançando em paralelo, é aqui que se mexe.

O hodômetro (`Veiculo.km_atual`) é recalculado por
`services.atualizar_km_veiculo` no `save()` da viagem e num `post_delete`.
É um recompute (`Max(km_final)`) e não um "só sobe": editar uma viagem para
menos ou excluí-la **abaixa** o `km_atual` — sem isso o valor ficaria inflado
e barraria lançamentos legítimos. Com o veículo sem nenhuma viagem, o
`km_atual` do cadastro é preservado. Atenção: exclusões feitas direto no banco
(SQL) não passam pelo signal e exigem recálculo manual.

---

## 4. Estrutura de arquivos (o que foi criado/alterado)

```
controle_veiculos/                 # raiz (contém manage.py)
├── .env.example                   # (NOVO) modelo de variáveis de ambiente
├── DEVELOPMENT.md                 # (NOVO) este documento
├── ESTUDO.md                      # (NOVO) roteiro de estudo do backend
├── docs/
│   └── PRE_CADASTRO_VIAGENS.md    # (NOVO) desenho da agenda/pré-cadastro (proposta)
├── requirements.txt               # (corrigido)
├── docker-compose.yml             # (corrigido)
├── controle_veiculos/            # pacote de configuração (renomeado de controle_viagens)
│   ├── settings.py               # (reescrito) Postgres, AUTH_USER_MODEL, apps, estáticos
│   ├── urls.py                   # (reescrito) login/logout + include dos apps
│   ├── templates/base.html       # layout (Tailwind CDN + DaisyUI + HTMX), tema "flexivel"
│   ├── templates/login.html      # (ajustado p/ LoginView nativa)
│   └── static/                   # logo.png e images/background.jpg
├── colaboradores/                 # app de colaboradores (= usuários)
│   ├── models.py                 # Funcionario(AbstractUser), CentroCusto, UnidadeFabril
│   ├── forms.py                  # cadastro (gera username), inativar
│   ├── views.py                  # cadastro/inativar + listagem
│   ├── admin.py                  # (NOVO) UserAdmin + centros/unidades
│   ├── urls.py                   # (NOVO)
│   ├── migrations/0001_initial.py# (NOVO)
│   ├── templates/                # (NOVO) funcionarios.html, funcionarios_cadastrados.html
│   └── management/commands/
│       ├── cadastro_funcionarios.py  # (ajustado) importa CSV
│       └── criar_portaria.py         # (NOVO) cria o operador padrão
└── viagens/                       # (NOVO APP) controle de viagens
    ├── models.py                 # Viagem, Veiculo, Fechamento, FechamentoRateio
    ├── forms.py                  # LancamentoViagemForm, FechamentoFiltroForm
    ├── services.py               # validar_quilometragem, atualizar_km_veiculo,
    │                             #   calcular_rateio, confirmar_fechamento
    ├── exports.py                # (NOVO) exportar_fechamento_csv
    ├── views.py                  # LancarViagem, Fechamento, FechamentoExportar, HistoricoFechamentos
    ├── urls.py
    ├── admin.py
    ├── tests.py                  # (NOVO) suíte/esqueleto de estudo — ver ESTUDO.md
    ├── migrations/               # 0001_initial, 0002_veiculo, 0003_check_km,
    │                             #   0004_veiculo_obrigatorio
    └── templates/                # lancar_viagem.html, fechamento.html, historico_fechamentos.html
```

---

## 5. Modelos (resumo)

- **UnidadeFabril**: `nome`.
- **CentroCusto**: `codigo` (10 dígitos, único), `descricao`.
- **Funcionario** (`AbstractUser`): + `nome`, `unidade_fabril?`, `centro_custo?`,
  `ativo`.
- **Veiculo**: `placa` (única), `modelo`, `marca`, `km_atual` (hodômetro,
  recalculado a partir das viagens), `ativo`, `email_recurso?` (caixa de
  recurso no Outlook; única entre as preenchidas).
- **ReservaViagem**: pré-cadastro vindo do Outlook — `funcionario?`,
  `solicitante_nome`, `veiculo`, `data`, `hora_inicio?`, `hora_fim?`,
  `destino`, `origem`, `id_externo`, `status` (pendente/lançada/cancelada),
  `viagem?` (1‑para‑1). Ver
  [docs/PRE_CADASTRO_VIAGENS.md](docs/PRE_CADASTRO_VIAGENS.md).
- **Viagem**: `funcionario`, `veiculo`, `data`, `km_inicial`, `km_final?`,
  `km_percorrida` (calculado no save), `centro_custo` (congelado),
  `fechamento?`, `lancada_por?`, `criada_em`. Propriedades `fechada`,
  `em_andamento`, `concluida`, `status_descricao`.
  `CheckConstraint`: `km_final IS NULL OR km_final > km_inicial`.
  **`km_final` nulo = viagem em andamento** (veículo na rua) e **não entra em
  fechamento** — ver `services.viagens_em_aberto`.
- **Fechamento**: `data_inicio`, `data_fim`, `total_km`, `criado_por?`,
  `criado_em`.
- **FechamentoRateio**: `fechamento`, `centro_custo`, `km_percorrida`,
  `percentual` (único por `(fechamento, centro_custo)`).

---

## 6. Telas e URLs

| URL | Nome | Descrição |
|---|---|---|
| `/` | — | Redireciona para `lancar_viagem` |
| `/login/` `/logout/` | `login`/`logout` | Autenticação (views nativas do Django) |
| `/viagens/agenda/` | `agenda` | Agenda de pré-cadastros: fila do dia + grade do mês (`?dia=`, `?ano=&mes=`) |
| `/viagens/lancar/` | `lancar_viagem` | Lançar viagem + últimas 15 (com busca de colaborador por nome) |
| `/viagens/reservas/<id>/lancar/` | `lancar_reserva` | Converte uma reserva em viagem (KM inicial obrigatório, final opcional) |
| `/viagens/chegada/<id>/` | `registrar_chegada` | Conclui uma viagem em andamento com o KM de retorno |
| `/viagens/fechamento/` | `fechamento` | Filtro de período → prévia do rateio → confirmar → link de exportação |
| `/viagens/fechamentos/` | `historico_fechamentos` | Fechamentos já realizados, cada um com botão de exportação |
| `/viagens/fechamentos/<id>/exportar/` | `fechamento_exportar` | Download do rateio em .csv (arquivo do ERP) |
| `/viagens/fechamentos/<id>/exportar/viagens/` | `fechamento_exportar_viagens` | Download do detalhamento das viagens em .csv |
| `/colaboradores/` | `funcionarios` | Cadastrar / inativar colaborador |
| `/colaboradores/cadastrados/` | `funcionarios_cadastrados` | Listagem |
| `/admin/` | — | Django admin |

Fluxo do fechamento: `GET` com `data_inicio`/`data_fim` mostra a prévia
(somente leitura); `POST` (com confirmação via `confirm()`) executa
`confirmar_fechamento` e redireciona ao histórico.

---

## 7. Como rodar (desenvolvimento)

```bash
# 1. Ambiente
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Variáveis de ambiente
cp .env.example .env                # ajuste DATABASE_URL, DJANGO_SECRET_KEY, etc.

# 3. Banco (precisa de um PostgreSQL rodando e acessível pela DATABASE_URL)
python manage.py migrate

# 4. Usuário-operador padrão (lê a senha de DJANGO_PORTARIA_PASSWORD ou --senha)
python manage.py criar_portaria --superuser

# 5. Subir
python manage.py runserver
```

Com Docker: `docker compose up -d --build`. O `entrypoint.sh` do serviço
`web` roda `migrate`, `configurar_perfis` e `collectstatic`; o serviço
`scheduler` sobe com `RUN_SETUP=false` e apenas sincroniza as reservas a cada
15 minutos. A aplicação responde na **porta 5009**, publicada só pelo nginx.

Passo a passo do servidor, variáveis do `.env` e diagnóstico:
[docs/DEPLOY.md](docs/DEPLOY.md).

---

## 8. Verificação já realizada

Validado nesta implementação (com SQLite apenas para teste; produção é Postgres):

- `manage.py check`: sem problemas.
- `makemigrations` + `migrate`: aplicam do zero sem erros.
- **Teste de negócio** (`services`): centro de custo congelado, `km_percorrida`
  calculada, rateio `Centro A 150km=37,50%` / `Centro B 250km=62,50%` sobre 400
  km, fechamento marca as viagens, e uma segunda passada no mesmo período
  retorna **0** (viagem nunca reprocessada). Viagem fora do período permanece em
  aberto.
- **Smoke test de views/templates** (test Client autenticado): todas as rotas
  retornam 200/302; acesso sem login redireciona para `/login/`.
- **POSTs**: cadastro de colaborador gera username (`carlos.souza`) com senha
  inutilizável; lançamento cria a viagem com `lancada_por=portaria`; viagem com
  `km_final < km_inicial` é rejeitada.
- **Exportação CSV** (`exports.py`): o arquivo de rateio é uma tabela pura —
  o teste conta as linhas (cabeçalho + uma por centro de custo) e recusa
  título, linha em branco e linha de total, que numa importação virariam
  registro fantasma. Relendo o texto com o módulo `csv`, os valores batem com
  o rateio calculado. O arquivo começa com BOM, usa `;` e escreve os
  percentuais com vírgula decimal — as três condições para abrir legível no
  Excel pt-BR. As duas rotas exigem a permissão de fechamento e devolvem 404
  para um fechamento inexistente.
- **Busca de colaborador e link de exportação**: confirmado via HTML
  renderizado que `funcionario-busca` aparece em `lancar_viagem.html`, que o
  banner "Baixar CSV" aparece em `/viagens/fechamento/?concluido=<id>`, e
  que o botão "Exportar CSV" aparece em cada linha de
  `/viagens/fechamentos/`.

---

## 9. Próximos passos sugeridos

- **Pré-cadastro de viagens (agenda)** — desenho técnico aprovado e ainda não
  implementado em [docs/PRE_CADASTRO_VIAGENS.md](docs/PRE_CADASTRO_VIAGENS.md):
  novo modelo `ReservaViagem`, tela de calendário e conclusão do lançamento só
  com a quilometragem. Prepara a integração futura com o Outlook (Microsoft
  Graph), hoje simulada com dados mockados.

- Login individual por colaborador (a base já suporta: `Funcionario` é o user).
- Valor do combustível/custo por km no fechamento, para gerar o rateio em R$
  (hoje o rateio é por percentual de km — base para aplicar qualquer custo).
- Vínculo com veículo (placa) na viagem, se necessário.
- Completar `viagens/tests.py` (o esqueleto existe; a maioria dos casos ainda
  está como `skipTest`). Roteiro e exercícios em [ESTUDO.md](ESTUDO.md).
- Relatório/exportação em PDF do fechamento (CSV já implementado).
