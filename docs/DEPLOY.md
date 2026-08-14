# Deploy no servidor Ubuntu interno

Passo a passo completo, do servidor limpo até a aplicação no ar.

```
                    :5009
  navegador  ──────────────►  nginx  ──►  web (gunicorn)  ──►  db (postgres)
                                                ▲                    ▲
                                          scheduler  ────────────────┘
                                     (sincroniza a cada 15 min)
```

| Serviço | O que faz | Porta no host |
|---|---|---|
| `nginx` | recebe as requisições e serve os estáticos | **5009** |
| `web` | gunicorn com a aplicação Django | nenhuma |
| `scheduler` | importa as reservas do Outlook a cada 15 min | nenhuma |
| `db` | PostgreSQL 16 | nenhuma |

**Só o nginx publica porta.** O gunicorn é alcançável apenas pela rede interna
do compose: publicar 8000 no host criaria um caminho paralelo que contorna o
nginx, sem os arquivos estáticos e sem os cabeçalhos de proxy.

---

## Roteiro

1. [Instalar o Docker](#1-instalar-o-docker)
2. [Clonar o repositório](#2-clonar-o-repositório)
3. [Colocar o `.env` no servidor](#3-colocar-o-env-no-servidor) ← **os ajustes obrigatórios estão aqui**
4. [Subir os containers](#4-subir-os-containers)
5. [Carregar os cadastros base](#5-carregar-os-cadastros-base)
6. [Criar os usuários](#6-criar-os-usuários)
7. [Cadastrar os veículos](#7-cadastrar-os-veículos)
8. [Validar](#8-validar)
9. [Operação do dia a dia](#9-operação-do-dia-a-dia)
10. [Quando dá errado](#10-quando-dá-errado)
11. [HTTPS](#11-https-quando-for-a-hora)

---

## 1. Instalar o Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                        docker-buildx-plugin docker-compose-plugin
```

Para usar o docker sem `sudo` (exige sair e entrar de novo na sessão):

```bash
sudo usermod -aG docker $USER
```

Conferir:

```bash
docker --version
docker compose version     # tem que ser `docker compose`, com espaço
```

---

## 2. Clonar o repositório

```bash
sudo mkdir -p /opt/controle_veiculos
sudo chown $USER:$USER /opt/controle_veiculos
git clone https://github.com/GustavoKinas/controle_veiculos.git /opt/controle_veiculos
cd /opt/controle_veiculos
```

Todos os comandos deste guia rodam a partir desse diretório — é onde está o
`docker-compose.yml`.

---

## 3. Colocar o `.env` no servidor

O `.env` está no `.gitignore` e **não vem no clone**, de propósito. Transfira o
seu por FTP/SCP para `/opt/controle_veiculos/.env` e proteja o arquivo:

```bash
chmod 600 .env
```

### ⚠️ O `.env` de desenvolvimento NÃO funciona como está

Quatro linhas precisam mudar. As três primeiras impedem a aplicação de
funcionar; a quarta é segurança.

```ini
# 1. DEBUG — em produção expõe traceback com dados internos a qualquer visitante
DEBUG=False

# 2. ALLOWED_HOSTS — o IP/nome pelo qual o navegador acessa. SEM esquema, SEM porta.
#    Se ficar em "localhost,127.0.0.1", o acesso pelo IP devolve 400 DisallowedHost.
ALLOWED_HOSTS=10.0.0.50,controle-veiculos.local

# 3. CSRF_TRUSTED_ORIGINS — COM esquema e COM porta. Se ficar vazio, a tela de
#    login abre normalmente e o POST volta 403 CSRF verification failed.
CSRF_TRUSTED_ORIGINS=http://10.0.0.50:5009,http://controle-veiculos.local:5009

# 4. DJANGO_SECRET_KEY — outra, diferente da de desenvolvimento:
#    python3 -c "import secrets; print(secrets.token_urlsafe(64))"
DJANGO_SECRET_KEY=...
```

Troque `10.0.0.50` pelo IP real do servidor (`hostname -I`).

### O que **não** precisa mudar

`DATABASE_URL` pode continuar apontando para `localhost`: o
`docker-compose.yml` sobrepõe essa variável nos serviços `web` e `scheduler`,
trocando o host por `db` e reaproveitando as credenciais do `POSTGRES_*`. É o
que permite o mesmo arquivo servir à sua máquina e ao servidor.

`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` e `SECURE_SSL_REDIRECT` ficam em
`False` enquanto o acesso for HTTP puro. Marcar `True` sem HTTPS **impede o
login**: o navegador descarta o cookie de sessão.

### Sobre as senhas

| Variável | Observação |
|---|---|
| `POSTGRES_DB` `POSTGRES_USER` `POSTGRES_PASSWORD` | criam o banco na **primeira** subida |
| `DJANGO_PORTARIA_PASSWORD` | padrão do `--senha` em `criar_portaria` |
| `DJANGO_FINANCEIRO_PASSWORD` | idem para `criar_financeiro` — acrescente, se ainda não existir |

⚠️ **`POSTGRES_*` só tem efeito na primeira subida**, quando o volume é criado.
Mudar a senha no `.env` depois não muda a senha do banco existente — a
aplicação passa a falhar autenticação. Para trocar mais tarde: `ALTER USER` no
banco, ou `docker compose down -v` (que **apaga todos os dados**).

⚠️ **Senha do Postgres sem caracteres especiais.** Ela é interpolada dentro de
uma URL; `@`, `/`, `#`, `?` e `:` quebram a leitura. Gere assim:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

---

## 4. Subir os containers

```bash
docker compose up -d --build
docker compose ps
```

Os quatro serviços devem aparecer como `running`, e o `db` como `healthy`.

Na primeira subida o `web` executa, pelo `entrypoint.sh`:

1. espera o banco aceitar conexões;
2. `migrate`;
3. `configurar_perfis` — cria os grupos Portaria e Financeiro;
4. `collectstatic` para o volume que o nginx serve.

O `scheduler` **não** repete esses passos (`RUN_SETUP=false`): dois `migrate`
simultâneos disputariam o lock de migração do Postgres.

O build roda `python manage.py check` como etapa final — uma dependência
faltando no `requirements.txt` falha aqui, e não em produção.

---

## 5. Carregar os cadastros base

O banco sobe **vazio**. A ordem importa, cada passo depende do anterior:

```bash
# 1. Unidades fabris. NÃO existe comando para isto, e sem elas o passo 3 pula
#    TODOS os colaboradores ("unidade fabril 'Matriz' não encontrada"),
#    terminando com "0 cadastrados" e sem erro no código de saída.
docker compose exec web python manage.py shell -c \
  "from colaboradores.models import UnidadeFabril; \
   [UnidadeFabril.objects.get_or_create(nome=n) for n in ['Matriz','Filial MG','EVO']]"

# 2. Centros de custo
docker compose exec web python manage.py cadastro_centro_custo \
    colaboradores/management/commands/cc.csv

# 3. Colaboradores — confira o rodapé: "cadastrados" tem que ser > 0
docker compose exec web python manage.py cadastro_funcionarios \
    colaboradores/management/commands/funcionarios_total_com_email.csv
```

As unidades do CSV atual são `Matriz`, `Filial MG` e `EVO`. Se o arquivo
mudar, confira os valores da coluna `unidade_fabril` antes de importar.

O e-mail do colaborador é a **chave de junção com o Outlook**: quem estiver
sem e-mail aparece nas reservas importadas como "não identificado", e o
operador escolhe a pessoa na hora de lançar.

---

## 6. Criar os usuários

Os grupos já existem (passo 4), mas ninguém está neles:

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py criar_portaria
docker compose exec web python manage.py criar_financeiro
```

Com `DJANGO_PORTARIA_PASSWORD` e `DJANGO_FINANCEIRO_PASSWORD` no `.env`, os
dois últimos dispensam `--senha` — e a senha não fica no histórico do shell.

Conferir:

```bash
docker compose exec web python manage.py configurar_perfis --listar
```

Quem pode o quê está em
[`UTILIZACOES_DO_SISTEMA.md`](UTILIZACOES_DO_SISTEMA.md).

---

## 7. Cadastrar os veículos

Pelo `/admin`, com o superusuário. Cada veículo precisa do **`email_recurso`**
preenchido — é ele que liga o veículo à caixa de recurso no Outlook. Veículo
sem esse campo simplesmente não é sincronizado.

| Placa | Modelo | Caixa de recurso |
|---|---|---|
| `SXK9G85` | CRONOS | `cronossxk9g85@puflexivel.com.br` |
| `SXB9B09` | CRONOS | `cronossxb9b09@puflexivel.com.br` |
| `RLN1J19` | STRADA | `stradarln1j19@puflexivel.com.br` |

O `km_atual` de cada um é o **piso da primeira viagem**: informe o hodômetro
real do carro, ou deixe 0 e o primeiro lançamento define a régua.

Pela linha de comando, se preferir:

```bash
docker compose exec web python manage.py shell -c "
from viagens.models import Veiculo
for placa, modelo, email in [
    ('SXK9G85','CRONOS','cronossxk9g85@puflexivel.com.br'),
    ('SXB9B09','CRONOS','cronossxb9b09@puflexivel.com.br'),
    ('RLN1J19','STRADA','stradarln1j19@puflexivel.com.br'),
]:
    Veiculo.objects.update_or_create(placa=placa, defaults={
        'modelo': modelo, 'marca': 'FIAT', 'email_recurso': email,
        'ativo': True, 'km_atual': 0})
"
```

---

## 8. Validar

```bash
# A aplicação responde
curl -I http://localhost:5009/          # 302 para /login/

# As caixas de recurso estão visíveis
docker compose exec web python manage.py shell -c \
  "from viagens.sincronizacao import caixas_de_recurso; print(caixas_de_recurso())"

# A sincronização funciona (não grava nada)
docker compose exec web python manage.py sincronizar_reservas --dry-run

# O scheduler está no ar
docker compose logs --tail=20 scheduler
```

Log de uma rodada saudável:

```
[scheduler] intervalo=900s janela=30d
[scheduler] 2026-08-14 08:15:02 iniciando sincronização
Janela: 2026-08-14T00:00:00-03:00 a 2026-09-13T00:00:00-03:00
Caixas de recurso: 3
3 evento(s) em 3 caixa(s) consultada(s) com sucesso.
[scheduler] sincronização concluída
[scheduler] dormindo 900s
```

Por fim, abra `http://<ip-do-servidor>:5009` e entre com a portaria.

---

## 9. Operação do dia a dia

### A sincronização automática

O serviço `scheduler` roda `scheduler.sh`: um laço que executa
`sincronizar_reservas` e dorme 15 minutos. Ajustável no `docker-compose.yml`:

| Variável | Padrão | O que faz |
|---|---|---|
| `SYNC_INTERVALO_SEGUNDOS` | `900` (15 min) | espera entre rodadas |
| `SYNC_DIAS` | `30` | tamanho da janela consultada |
| `SYNC_ATRASO_INICIAL_SEGUNDOS` | `30` | espera antes da primeira rodada |

```bash
docker compose up -d scheduler     # aplica a mudança
```

Três decisões do laço, para quem for mexer:

- **`sleep` depois do comando, não antes.** O intervalo conta a partir do
  *fim* de uma rodada, então duas sincronizações nunca se sobrepõem, mesmo que
  a API da Microsoft demore mais que 15 minutos.
- **Falha não derruba o serviço.** O comando sai com código diferente de zero
  quando alguma caixa não responde; o laço registra e segue. Caixa fora do ar
  costuma ser transitório.
- **Laço em vez de cron:** cron exigiria um segundo processo no container (e
  um supervisor), não herda o ambiente do `env_file` sem gambiarra, e mandaria
  a saída para um arquivo em vez do stdout — perdendo o `docker compose logs`.

Guia de sincronização pelo shell: [`SINCRONIZACAO.md`](SINCRONIZACAO.md).

### Atualizar a aplicação

```bash
cd /opt/controle_veiculos
git pull
docker compose up -d --build
docker compose logs -f web
```

O `entrypoint.sh` reaplica `migrate`, `configurar_perfis` e `collectstatic` a
cada subida — os três são idempotentes.

### Backup

```bash
docker compose exec db pg_dump -U controle_veiculos controle_veiculos \
  > backup_$(date +%F).sql
```

Restaurar:

```bash
cat backup_2026-08-14.sql \
  | docker compose exec -T db psql -U controle_veiculos -d controle_veiculos
```

Vale um cron no host para o backup diário.

### Parar

```bash
docker compose down          # mantém os dados
```

⚠️ `docker compose down -v` **apaga o volume do Postgres** — todo o histórico
de viagens e fechamentos vai junto. Só use com um backup na mão.

### Logs

```bash
docker compose logs -f              # todos
docker compose logs -f scheduler    # só a sincronização
docker compose logs --tail=40 web
```

---

## 10. Quando dá errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `400 Bad Request` / `DisallowedHost` | IP fora de `ALLOWED_HOSTS` | acrescente e `docker compose up -d web` |
| `403 CSRF verification failed` no login | `CSRF_TRUSTED_ORIGINS` vazio ou sem esquema/porta | use `http://ip:5009` |
| Login aceita a senha e volta para o login | cookie `Secure` sem HTTPS | `SESSION_COOKIE_SECURE=False` |
| `connection to server at "localhost" ... refused` | `DATABASE_URL` apontando para localhost | o compose já sobrepõe com `@db`; rode `docker compose up -d` |
| `password authentication failed` | senha mudou no `.env` depois do volume criado | `ALTER USER` no banco, ou recriar o volume |
| Página sem CSS | `collectstatic` não rodou | `docker compose up -d --force-recreate web` |
| `ModuleNotFoundError` | dependência ausente do `requirements.txt` | acrescente e `docker compose build` |
| `exec /entrypoint.sh: no such file or directory` | arquivo salvo com CRLF | o Dockerfile já remove com `sed` |
| `cadastro_funcionarios` diz `0 cadastrados` | unidades fabris não existem | passo 5.1 |
| `Nenhum veículo ativo com caixa de recurso` | veículo sem `email_recurso` | passo 7 |
| `scheduler` termina com código 1 | **leia a linha ACIMA do aviso** — ela traz a causa | `docker compose logs --tail=40 scheduler` |
| `falhou: <caixa> — 403` | aplicação sem permissão naquela caixa no Azure | as demais caixas seguem importando |
| `GraphIndisponivel` | credencial ausente ou expirada | renove o segredo no Azure e atualize o `.env` |
| Porta 5009 ocupada | outro serviço no host | `sudo ss -lptn 'sport = :5009'` |

---

## 11. HTTPS (quando for a hora)

A configuração atual serve **HTTP puro** na 5009, adequado a uma rede interna.
Para colocar TLS na frente:

1. ponha o certificado em `nginx/` e monte-o no serviço `nginx`;
2. acrescente um `server` na 443 no `nginx/default.conf`;
3. no `.env`, mude para `True`: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`
   e `SECURE_SSL_REDIRECT`;
4. atualize `CSRF_TRUSTED_ORIGINS` para `https://...`.

O `proxy_set_header X-Forwarded-Proto $scheme` já está no lugar, que é o que
o Django precisa para saber que a requisição original era HTTPS.
