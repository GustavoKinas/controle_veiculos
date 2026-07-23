# Controle de Veículos — Viagens e Rateio de Combustível

Documento de contexto do desenvolvimento. Serve tanto para retomar o trabalho
quanto para ser reenviado como contexto para futuros modelos de LLM.

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
- **Deploy:** Docker Compose (web gunicorn + db postgres + nginx)

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
| `requirements.txt` corrompido (UTF-16) | Reescrito em UTF-8 |
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
(select2/jQuery não estão de fato carregados no projeto, apesar de existirem
classes CSS residuais do clone original) e por ser suficiente para a escala
esperada (algumas centenas de colaboradores).

### 3.7 Exportação de fechamento em Excel (`viagens/exports.py`)
`exportar_fechamento_excel(fechamento)` gera um `.xlsx` com **openpyxl** (nova
dependência, ver `requirements.txt`) contendo duas abas: **"Resumo do Rateio"**
(por Centro de Custo, igual ao que é exibido na tela) e **"Viagens"**
(detalhamento de cada viagem incluída naquele fechamento). Reaproveitado em
dois pontos: (1) banner exibido em `/viagens/fechamento/` logo após confirmar
um novo fechamento (via redirect com `?concluido=<id>`), e (2) botão em cada
linha de `/viagens/fechamentos/`.

**Performance:** as queries usam `select_related` (evita N+1 em
`centro_custo`/`funcionario`); o workbook é gerado em memória (`io.BytesIO`) no
modo padrão do openpyxl (não `write_only`) para permitir autofit de colunas —
adequado ao volume real (um fechamento tem, tipicamente, dezenas a algumas
centenas de viagens). Note que `.xlsx` é um contêiner ZIP, então não há streaming
byte-a-byte real possível; o ganho de performance que importa aqui é evitar
N+1 queries, não streaming da resposta.

---

## 4. Estrutura de arquivos (o que foi criado/alterado)

```
controle_veiculos/                 # raiz (contém manage.py)
├── .env.example                   # (NOVO) modelo de variáveis de ambiente
├── DEVELOPMENT.md                 # (NOVO) este documento
├── requirements.txt               # (corrigido)
├── docker-compose.yml             # (corrigido)
├── controle_veiculos/            # pacote de configuração (renomeado de controle_viagens)
│   ├── settings.py               # (reescrito) Postgres, AUTH_USER_MODEL, apps, estáticos
│   ├── urls.py                   # (reescrito) login/logout + include dos apps
│   ├── templates/base.html       # (menu reescrito + mensagens)
│   ├── templates/login.html      # (ajustado p/ LoginView nativa)
│   └── static/css/base.css       # (+ estilos de tabela e barra de percentual)
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
    ├── models.py                 # Viagem, Fechamento, FechamentoRateio
    ├── forms.py                  # LancamentoViagemForm, FechamentoFiltroForm
    ├── services.py               # calcular_rateio, confirmar_fechamento (regras de negócio)
    ├── exports.py                # (NOVO) exportar_fechamento_excel (openpyxl)
    ├── views.py                  # LancarViagem, Fechamento, FechamentoExportar, HistoricoFechamentos
    ├── urls.py
    ├── admin.py
    ├── migrations/0001_initial.py
    └── templates/                # lancar_viagem.html, fechamento.html, historico_fechamentos.html
```

---

## 5. Modelos (resumo)

- **UnidadeFabril**: `nome`.
- **CentroCusto**: `codigo` (10 dígitos, único), `descricao`.
- **Funcionario** (`AbstractUser`): + `nome`, `unidade_fabril?`, `centro_custo?`,
  `ativo`.
- **Viagem**: `funcionario`, `data`, `km_inicial`, `km_final`,
  `km_percorrida` (calculado no save), `centro_custo` (congelado),
  `fechamento?`, `lancada_por?`, `criada_em`. Propriedade `fechada`.
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
| `/viagens/lancar/` | `lancar_viagem` | Lançar viagem + últimas 15 (com busca de colaborador por nome) |
| `/viagens/fechamento/` | `fechamento` | Filtro de período → prévia do rateio → confirmar → link de exportação |
| `/viagens/fechamentos/` | `historico_fechamentos` | Fechamentos já realizados, cada um com botão de exportação |
| `/viagens/fechamentos/<id>/exportar/` | `fechamento_exportar` | Download do .xlsx de um fechamento |
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

Com Docker: `docker compose up --build` (o `entrypoint.sh` roda `migrate` e
`collectstatic` automaticamente).

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
- **Exportação Excel** (`exports.py`): fechamento com Centro Alpha 80km/40% e
  Centro Beta 120km/60% gera `.xlsx` com as abas "Resumo do Rateio" e
  "Viagens"; reabrindo o arquivo com `openpyxl.load_workbook`, os valores
  batem exatamente com o rateio calculado. Rota de download exige login (302
  se anônimo) e retorna 404 para um fechamento inexistente.
- **Busca de colaborador e link de exportação**: confirmado via HTML
  renderizado que `funcionario-busca` aparece em `lancar_viagem.html`, que o
  banner "Baixar Excel" aparece em `/viagens/fechamento/?concluido=<id>`, e
  que o botão "Exportar Excel" aparece em cada linha de
  `/viagens/fechamentos/`.

---

## 9. Próximos passos sugeridos

- Login individual por colaborador (a base já suporta: `Funcionario` é o user).
- Valor do combustível/custo por km no fechamento, para gerar o rateio em R$
  (hoje o rateio é por percentual de km — base para aplicar qualquer custo).
- Vínculo com veículo (placa) na viagem, se necessário.
- Testes automatizados em `viagens/tests.py` a partir dos cenários da seção 8.
- Relatório/exportação em PDF do fechamento (Excel já implementado).
