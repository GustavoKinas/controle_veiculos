# Integração de usuários com Active Directory — Plano de Implementação

> **Para agentes executores:** usar `superpowers:subagent-driven-development` se o usuário escolher subagents para a sprint; usar `superpowers:executing-plans` se escolher execução inline. Antes de cada sprint, perguntar qual método usar. O usuário faz todas as operações Git.

**Objetivo:** permitir login de usuários individuais com credenciais AD, mantendo cadastro, autorização por grupos e superusuários de contingência locais.

**Arquitetura:** um `HybridAuthBackend` Django roteia pelo cadastro local antes de qualquer chamada LDAP. Um `AuthenticationService` coordena o fluxo e um `DirectoryClient` próprio usa `ldap3` com LDAPS validado, consulta escapada, timeouts e vínculo estável por `objectGUID`. Formulários distintos impedem que contas `DIRECTORY` recebam senha local; grupos Django continuam definindo permissões.

**Stack:** Django 6.0, Python 3.12, PostgreSQL, `ldap3==2.9.1` (dentro da faixa `>=2.9,<3.0` indicada pelo usuário).

**Especificação:** `docs/superpowers/specs/2026-09-25-integracao-ad-usuarios-design.md`.

## Restrições globais

- Usuários existentes recebem `auth_source=LOCAL` na migração; nenhum usuário é criado, alterado ou removido automaticamente pelo AD.
- Novas instâncias `Funcionario` usam `auth_source=DIRECTORY` como default aprovado pelo usuário; formulários locais e `createsuperuser` definem `LOCAL` explicitamente. Comandos legados de perfil criam somente contas `LOCAL` e recusam alterar senha de conta `DIRECTORY`.
- Para `DIRECTORY`, o login cadastrado corresponde a `sAMAccountName`; o primeiro login AD bem-sucedido grava o `objectGUID`, e divergência nega acesso.
- O código consulta o AD somente depois de localizar um usuário local ativo marcado como `DIRECTORY`; não existe fallback de `DIRECTORY` para senha local.
- Permissões vêm somente dos grupos locais Django. Grupos e atributos do AD não são sincronizados.
- A administração mostra seleção de grupos para atribuir permissões; não usa `user_permissions` diretamente para conceder novas permissões.
- Uma conta `DIRECTORY` não tem campo, link ou endpoint de criação/troca de senha local. Contas `LOCAL` usam formulário próprio com senha.
- O perfil LDAP é `validated` e o transporte é LDAPS por FQDN, com a CA `etc/flexivel-root-ca.crt`; nunca desligar validação automaticamente.
- FQDN, Base DN, UPN, senha de serviço, DNS interno e sufixo DNS ficam em variáveis de ambiente; senhas nunca entram no repositório nem nos logs.
- O serviço web do Compose monta a CA em modo somente leitura e declara `dns`/`dns_search` obrigatórios. A aplicação falha no startup quando a configuração LDAP está vazia ou inválida.
- Conexão LDAP tem timeout de 5 segundos e operação tem timeout de 10 segundos. Sessão dura no máximo 28.800 segundos e expira ao fechar o navegador.
- HAProxy termina HTTPS; nginx preserva o protocolo encaminhado por ele e Django confia apenas na cadeia de proxy permitida. Cookies de sessão e CSRF são seguros em produção.
- O agente não executa `git add`, `commit`, `push` nem outras operações Git; o usuário gerencia o repositório.
- Esta execução do plano não altera código nem executa testes. Os comandos de teste abaixo são para as sprints de implementação.

## Arquivos e responsabilidades

- `colaboradores/models.py`: origem de autenticação e GUID da conta AD.
- `colaboradores/migrations/`: migração com origem `LOCAL` por padrão.
- `colaboradores/auth_admin_forms.py`: formulários separados para criar e converter contas `LOCAL` e `DIRECTORY`.
- `colaboradores/admin.py` e `colaboradores/templates/admin/colaboradores/funcionario/`: fluxos de administração, grupos, exibição do vínculo e ação de religação.
- `colaboradores/directory.py`: `DirectoryClient`, resultados tipados, busca e validação de senha.
- `colaboradores/authentication.py`: `AuthenticationService` e resultados do fluxo de login.
- `colaboradores/auth_backends.py`: backend Django único para rotear `LOCAL`/`DIRECTORY` sem fallback entre backends.
- `colaboradores/auth_views.py` e `controle_veiculos/urls.py`: mensagens da tela de login para indisponibilidade e negação AD.
- `controle_veiculos/settings.py`, `controle_veiculos/wsgi.py` e `controle_veiculos/directory_config.py`: configuração LDAP validada no startup do servidor web, backend, sessão e confiança no proxy HTTPS.
- `colaboradores/tests_auth_ad.py`: testes de modelo, formulários, cliente LDAP, roteamento, login e sessão.
- `colaboradores/tests_auth_admin.py`: testes do admin de usuários e transições.
- `requirements.txt`: dependência `ldap3` fixada dentro da faixa aprovada.
- `.env` e `.env.example`: campos da integração; preservar as entradas existentes no `.env`, acrescentar somente chaves ausentes e criar `.env.example` sem segredos.
- `docker-compose.yml`: DNS do serviço web e montagem somente leitura da CA.
- `nginx/default.conf`: encaminhar o protocolo original do HAProxy ao Gunicorn.
- `docs/DEPLOY_AD.md`, `docs/UTILIZACOES_DO_SISTEMA.md` e `docs/CONTEXTO_RETOMADA.md`: operação, configuração e corte para contas individuais.

## Review Focus

- **Usuário LOCAL com AD fora do ar:** continua entrando sem qualquer conexão LDAP. Testar em Sprint 3, Tarefa 6.
- **Senha vazia ou LDAP indisponível:** senha vazia não abre bind; falha de DNS/rede/TLS não vira erro de senha nem ativa fallback. Testar em Sprint 2, Tarefa 3, e Sprint 3, Tarefa 6.
- **Login LDAP malicioso ou ambíguo:** caracteres de filtro são escapados e zero/mais de um resultado não autentica nem cria usuário. Testar em Sprint 2, Tarefa 3.
- **GUID binário, divergente ou já vinculado:** interpretar os 16 bytes em ordem little-endian, gravar uma vez e negar identidade diferente. Testar em Sprint 2, Tarefa 3, e Sprint 3, Tarefa 6.
- **Conta DIRECTORY e senha local:** formulário de criação/edição não expõe senha e rejeita senha enviada em payload; transição para LOCAL exige senha nova. Testar em Sprint 1, Tarefa 2.
- **Configuração incompleta:** URI/CA/TLS inválidos impedem o startup WSGI; `manage.py check` e o build Docker continuam verificáveis sem valores AD. Testar em Sprint 2, Tarefa 4.
- **HTTPS via HAProxy:** Django recebe o protocolo seguro encaminhado, cookies/CSRF usam `Secure`, e o acesso direto sem proxy não é aceito em produção. Testar em Sprint 2, Tarefa 5, e Sprint 3, Tarefa 7.

---

## Sprint 1 — Cadastro local e administração dos vínculos

**Status:** concluída. Verificação final: 17 testes focados passaram em SQLite, checagem Django sem problemas e `makemigrations --check --dry-run` sem pendências. PostgreSQL local não estava acessível.

**Seleção de execução:** perguntar antes do início desta sprint: execução inline ou com subagents?

### Tarefa 1: Adicionar origem de autenticação e GUID

**Arquivos:**
- Modificar: `colaboradores/models.py`
- Criar: próxima migração gerada em `colaboradores/migrations/` para `auth_source` e `directory_guid`
- Testar: `colaboradores/tests_auth_ad.py`

**Interfaces:**
- Produz: `Funcionario.auth_source` com valores `LOCAL` e `DIRECTORY` e default `DIRECTORY` para novas instâncias; `Funcionario.directory_guid` como UUID opcional, único e não editável. A migração mantém registros existentes como `LOCAL`; os formulários de criação escolhem a origem explicitamente.
- Consome: `Funcionario` atual e a migração inicial do app `colaboradores`.

- [x] **Passo 1: Escrever testes de modelo para o valor padrão e unicidade**

Importar `uuid`, `transaction` e `IntegrityError` no módulo de teste.

```python
def test_novo_funcionario_tem_origem_local(self):
    user = Funcionario.objects.create_user(username="ana.silva", password="local")
    self.assertEqual(user.auth_source, Funcionario.AuthSource.LOCAL)
    self.assertIsNone(user.directory_guid)

def test_guid_ad_nao_pode_ser_repetido(self):
    guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    Funcionario.objects.create_user(username="ana.silva", password="x", directory_guid=guid)
    with self.assertRaises(IntegrityError):
        with transaction.atomic():
            Funcionario.objects.create_user(username="bia.silva", password="x", directory_guid=guid)
```

- [x] **Passo 2: Rodar os testes para confirmar que falham**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.FuncionarioAuthFieldsTests -v 2`  
Esperado: falha porque os campos ainda não existem.

- [x] **Passo 3: Implementar os dois campos com default seguro**

Adicionar os campos no model, sem alterar `ativo`, `is_active`, nomes de usuário ou senhas durante a migração:

```python
class Funcionario(AbstractUser):
    class AuthSource(models.TextChoices):
        LOCAL = "LOCAL", "Local"
        DIRECTORY = "DIRECTORY", "Active Directory"

    auth_source = models.CharField(max_length=10, choices=AuthSource.choices, default=AuthSource.DIRECTORY)
    directory_guid = models.UUIDField(null=True, blank=True, unique=True, editable=False)
```

- [x] **Passo 4: Gerar a migração e rodar os testes**

Rodar `venv/bin/python manage.py makemigrations colaboradores` e depois o teste acima.  
Esperado: novas instâncias ficam `DIRECTORY`, os registros existentes continuam `LOCAL` após a migração e GUID duplicado falha pela constraint do banco.

### Tarefa 2: Criar fluxos de admin que separem LOCAL e DIRECTORY

**Arquivos:**
- Criar: `colaboradores/auth_admin_forms.py`
- Modificar: `colaboradores/admin.py`
- Criar: `colaboradores/tests_auth_admin.py`
- Modificar: `colaboradores/permissoes.py` para proteger a criação legada de perfis locais
- Modificar: `colaboradores/models.py` e criar migração de manager para manter `createsuperuser` local
- Criar, se necessário: `colaboradores/templates/admin/colaboradores/funcionario/add_directory.html` e `transition_auth.html`

**Interfaces:**
- Produz: `DirectoryFuncionarioCreationForm`, `LocalFuncionarioCreationForm`, `VincularFuncionarioADForm` e `ConverterFuncionarioLocalForm`.
- Consome: `Funcionario.auth_source`, `Funcionario.directory_guid` e os grupos Django existentes.

- [x] **Passo 1: Testar formulários sem senha para DIRECTORY**

```python
def test_formulario_directory_nao_exibe_ou_aceita_senha(self):
    form = DirectoryFuncionarioCreationForm()
    self.assertNotIn("password", form.fields)
    self.assertNotIn("password1", form.fields)
    self.assertNotIn("password2", form.fields)
    data = {"username": "ana.silva", "nome": "Ana Silva",
            "password1": "tentativa", "password2": "tentativa"}
    form = DirectoryFuncionarioCreationForm(data=data)
    self.assertFalse(form.is_valid())
```

Adicionar testes de que: criar `DIRECTORY` gera senha inutilizável; criar `LOCAL` exige senha; converter `LOCAL` para `DIRECTORY` limpa a senha/GUID; converter de volta exige senha nova e limpa o GUID; grupos permanecem associados até o admin alterá-los.

Verificar ainda que o formulário mostra `groups`, salva o grupo selecionado e não mostra `user_permissions`.

No formulário de vínculo, remover espaços ao redor com `strip()`, preservar a grafia recebida de `sAMAccountName` e recusar outro cadastro local com username igual sem diferenciar maiúsculas/minúsculas. Não alterar os usernames de cadastros existentes em lote.

Os formulários de criação devem expor o campo múltiplo `groups`; ao salvar, persistir os grupos selecionados. Os formulários normais de edição também permitem atualizar `groups`, mas removem `user_permissions` para que concessões novas sempre passem por grupos.

- [x] **Passo 2: Rodar a classe de testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_admin.DirectoryFuncionarioFormTests -v 2`  
Esperado: formulários e transições ainda não existem.

- [x] **Passo 3: Implementar formulários e transições no servidor**

Usar fluxo de criação padrão apenas para `LOCAL`; criar rota/formulário separado `DIRECTORY` sem campos de senha, com `auth_source` fixo e senha inutilizável. Se um POST tentar enviar senha por campos extras, rejeitá-lo explicitamente. Incluir seleção de grupos locais e salvar essa relação ao criar. Para editar usuário `DIRECTORY`, remover campo, link e endpoint local de senha. Para conversões, usar formulário dedicado que não disponibiliza origem mutável junto de campos de senha. A gravação DIRECTORY define a origem e invalida o hash local:

```python
funcionario.auth_source = Funcionario.AuthSource.DIRECTORY
funcionario.set_unusable_password()
funcionario.directory_guid = None
funcionario.save(update_fields=["auth_source", "password", "directory_guid"])
```

- [x] **Passo 4: Integrar os fluxos no admin e preservar grupos**

Adicionar botões separados “Novo usuário local” e “Novo vínculo AD”, manter `auth_source` e `directory_guid` visíveis, tornar GUID somente leitura, exibir grupo associado e adicionar ação “Religar identidade AD” que limpa o GUID com confirmação POST/CSRF. Garantir origem local em `createsuperuser`, criação local explicitamente selecionada e comandos legados recusando aplicar senha local a uma conta DIRECTORY. Recusar colisão de username sem diferenciar caixa nos formulários de criação e edição. Não remover usuários nem grupos genéricos.

- [x] **Passo 5: Rodar os testes do admin**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_admin -v 2`  
Esperado: criação, conversões, grupos e religação funcionam; usuários `DIRECTORY` não recebem controle de senha.

---

## Sprint 2 — Cliente LDAP, configuração e deploy

**Status:** concluída. DirectoryClient, configuração estrita de startup, CA/DNS no Compose e cadeia HTTPS HAProxy→nginx→Django implementados. Suíte completa: 239 testes executados, 27 ignorados e 1 falha esperada; checks Django e de migração sem pendências. A validação de DNS/TLS no runtime e a ACL real do firewall dependem do deploy.

**Seleção de execução:** perguntar antes do início desta sprint: execução inline ou com subagents?

### Tarefa 3: Implementar DirectoryClient tipado com ldap3

**Arquivos:**
- Criar: `colaboradores/directory.py`
- Criar: `colaboradores/tests_auth_ad.py`
- Modificar: `requirements.txt`

**Interfaces:**
- Produz: `DirectoryStatus` (`OK`, `INVALID`, `DISABLED`, `EXPIRED`, `LOCKED`, `PASSWORD_EXPIRED`, `MUST_CHANGE_PASSWORD`, `NOT_FOUND`, `AMBIGUOUS`, `UNAVAILABLE`), `DirectoryEntry(dn, object_guid)`, `DirectoryLookup(status, entry)`, `DirectoryClient.find_user(login)` e `DirectoryClient.verify_password(dn, password)`.
- Construtor: `DirectoryClient(uri, base_dn, bind_user, bind_password, tls_profile, ca_cert_file, connect_timeout, operation_timeout)`.
- Consome: argumentos de conexão passados ao construtor; a Tarefa 4 fornece esses valores via `DirectoryConfig`.

- [x] **Passo 1: Escrever testes do contrato e dos erros LDAP**

Cobrir filtro com `*()\NUL`, nenhum resultado, dois resultados, leitura de `raw_attributes["objectGUID"]`, GUID little-endian, senha vazia sem conexão, bind inválido, subcódigos `532`, `533`, `701`, `773`, `775`, timeout, falha TLS e bind de serviço recusado.

Use `mock.patch("colaboradores.directory.Connection")` com `MagicMock`, configure um resultado com `raw_attributes["objectGUID"]` e chame `DirectoryClient.find_user("*)(objectClass=*)")`. Verifique que o filtro contém `r"\2a\29\28objectClass=\2a\29"`, que `search` usa `size_limit=2` e que a busca solicita somente `objectGUID`.

O filtro usa o padrão abaixo; somente `login` passa por escape RFC 4515:

```python
filtro = "(&(objectCategory=person)(objectClass=user)(sAMAccountName={}))".format(
    escape_filter_chars(login)
)
```

- [x] **Passo 2: Rodar testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.DirectoryClientTests -v 2`  
Esperado: módulo `colaboradores.directory` ainda não existe.

- [x] **Passo 3: Fixar ldap3 dentro da faixa acordada**

Adicionar `ldap3==2.9.1` ao `requirements.txt`, dentro da faixa `>=2.9,<3.0` indicada pelo usuário e seguindo o padrão de pins exatos já usado pelo projeto. É a versão estável disponível no [PyPI](https://pypi.org/project/ldap3/2.9.1/). Confirmar a API da versão fixada para `Tls`, validação de hostname, timeouts e resposta bruta.

- [x] **Passo 4: Implementar busca e bind sem downgrade**

Criar TLS com `ssl.CERT_REQUIRED`, CA configurada e `valid_names` com o FQDN; usar conexão LDAPS, timeout de conexão 5 s, `receive_timeout=10`, `auto_referrals=False` e `read_only=True` na busca de serviço. Buscar somente `objectGUID`, usar `escape_filter_chars`, `SUBTREE` e `size_limit=2`. Validar senha vazia antes de criar conexão. Fazer bind do usuário em conexão nova; converter rede/TLS/bind de serviço em `UNAVAILABLE`, nunca em credencial inválida.

- [x] **Passo 5: Rodar os testes do DirectoryClient**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.DirectoryClientTests -v 2`  
Esperado: todos os estados, escape, raw GUID e timeouts passam sem contato com AD real.

### Tarefa 4: Validar configuração obrigatória sem segredos

**Arquivos:**
- Criar: `controle_veiculos/directory_config.py`
- Modificar: `controle_veiculos/settings.py`
- Modificar: `controle_veiculos/wsgi.py`
- Criar: `colaboradores/tests_directory_config.py`

**Interfaces:**
- Produz: `DirectoryConfig.from_env(environ)` e `get_directory_config()` com cache, que validam e fornecem configuração imutável ao `DirectoryClient`; o WSGI chama `get_directory_config()` ao iniciar o servidor web.
- Consome: variáveis LDAP, CA e sessão e o `DirectoryClient` da Tarefa 3.

- [x] **Passo 1: Escrever testes de variáveis ausentes e conflitos**

Testar erro claro quando URI/Base DN/UPN/senha/TLS/timeout/CA faltam; rejeição de `ldap://`, IP em modo `validated`, CA ausente/ilegível, URI com hostname vazio e timeout não positivo. Testar sucesso com valores fictícios, URI LDAPS por FQDN e CA existente.

- [x] **Passo 2: Rodar testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_directory_config -v 2`  
Esperado: `DirectoryConfig` não existe.

- [x] **Passo 3: Implementar configuração estrita no startup WSGI**

Ler `LDAP_URI`, `LDAP_BASE_DN`, `LDAP_BIND_USER`, `LDAP_BIND_PASSWORD`, `LDAP_TLS_PROFILE`, `LDAP_CA_CERT_FILE`, `LDAP_NETWORK_TIMEOUT`, `LDAP_OPERATION_TIMEOUT` e `SESSION_MAX_AGE`. Fixar `LDAP_TLS_PROFILE=validated` e `SESSION_MAX_AGE=28800`; não usar perfil padrão nem retry inseguro. No módulo WSGI, validar configuração antes de servir requests para o Gunicorn e `runserver` falharem no startup se valores requeridos estiverem vazios. Deixar `manage.py check`, migrações e testes sem dependência do AD.

`DirectoryConfig.from_env()` deve rejeitar valores vazios, URI que não seja LDAPS, IP literal em `validated`, CA ausente/ilegível, timeouts positivos inválidos e `SESSION_MAX_AGE` diferente de 28.800. A senha deve ficar fora do `repr` da configuração. No WSGI, executar a validação antes de construir a aplicação:

```python
directory_config = get_directory_config()
application = get_wsgi_application()
```

O factory do backend chamará `get_directory_config()` somente quando a origem for `DIRECTORY` e construirá `DirectoryClient` com os oito argumentos definidos na Tarefa 3. A configuração é validada no startup WSGI, mas não abre conexão LDAP.

- [x] **Passo 4: Confirmar que o build não precisa de credenciais AD**

O `.env` não entra na imagem e o Dockerfile roda `manage.py check`, que não importa o WSGI nem tenta abrir LDAP. Manter a configuração estrita no startup do servidor WSGI para que build, migrations e testes não precisem de credenciais AD.

- [x] **Passo 5: Rodar testes de configuração e check de build**

Rodar `venv/bin/python manage.py test colaboradores.tests_directory_config -v 2` e `docker compose build web`.  
Esperado: env válido passa; env ausente/conflitante falha no teste de configuração e no startup WSGI; build roda `manage.py check` sem depender dos valores reais do servidor.

### Tarefa 5: Preparar Compose, CA e cadeia HTTPS do HAProxy

**Arquivos:**
- Modificar: `.env` (acrescentar apenas chaves ausentes; não imprimir ou substituir valores atuais)
- Criar: `.env.example`
- Modificar: `docker-compose.yml`
- Modificar: `nginx/default.conf`
- Modificar: `controle_veiculos/settings.py`
- Testar configuração: `docker compose config`

**Interfaces:**
- Produz: serviço web com CA montada read-only, DNS interno obrigatório e cabeçalhos de proxy seguros.
- Consome: `DirectoryConfig` da Tarefa 4 e o HAProxy que termina HTTPS.

- [x] **Passo 1: Acrescentar campos vazios sem expor o `.env`**

Acrescentar apenas chaves ausentes no `.env` local e mantê-las vazias para preenchimento humano: `LDAP_URI=`, `LDAP_BASE_DN=`, `LDAP_BIND_USER=`, `LDAP_BIND_PASSWORD=`, `AD_DNS_PRIMARY=`, `AD_DNS_SEARCH=`. Em `.env.example`, registrar as mesmas chaves sem credenciais reais; deixar explícito que o servidor web não inicia enquanto campos obrigatórios estiverem vazios. Definir `LDAP_TLS_PROFILE=validated`, `LDAP_CA_CERT_FILE=/run/certs/flexivel-root-ca.crt`, `LDAP_NETWORK_TIMEOUT=5`, `LDAP_OPERATION_TIMEOUT=10` e `SESSION_MAX_AGE=28800`. As flags HTTPS serão definidas no serviço web do Compose, sem mudar o comportamento do `.env` usado pelo `runserver` local.

- [x] **Passo 2: Adicionar CA e DNS apenas ao workload web**

No serviço `web`, montar `./etc/flexivel-root-ca.crt:/run/certs/flexivel-root-ca.crt:ro`; configurar `dns: [${AD_DNS_PRIMARY:?preencha AD_DNS_PRIMARY}]` e `dns_search: [${AD_DNS_SEARCH:?preencha AD_DNS_SEARCH}]`. Não alterar DNS global do host, nem adicionar IP corporativo ao código. A definição de produção atual é `docker-compose.yml`, invocada por `docker compose` sem overlay.

O trecho de Compose deve seguir este formato:

```yaml
services:
  web:
    dns: ["${AD_DNS_PRIMARY:?preencha AD_DNS_PRIMARY}"]
    dns_search: ["${AD_DNS_SEARCH:?preencha AD_DNS_SEARCH}"]
    environment:
      TRUST_PROXY_SSL_HEADER: "True"
      SESSION_COOKIE_SECURE: "True"
      CSRF_COOKIE_SECURE: "True"
      SECURE_SSL_REDIRECT: "True"
    volumes:
      - ./etc/flexivel-root-ca.crt:/run/certs/flexivel-root-ca.crt:ro
```

- [x] **Passo 3: Preservar HTTPS do HAProxy até o Django**

Alterar nginx para encaminhar o `X-Forwarded-Proto` recebido do HAProxy em vez de sobrescrevê-lo com o `$scheme` interno. Em Django, configurar `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY` e `SESSION_COOKIE_SAMESITE="Lax"` para produção. Documentar restrição de rede para que somente HAProxy confiável alcance a porta publicada e que HTTP direto não transporte credenciais.

Configuração correspondente no Django:

```python
if os.getenv("TRUST_PROXY_SSL_HEADER", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False") == "True"
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False") == "True"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
```

No `nginx/default.conf`, usar `proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;` e manter esse header preenchido/normalizado pelo HAProxy. Acrescentar as quatro flags de produção ao bloco `environment` já existente do serviço `web`, sem criar uma segunda chave YAML `environment`.

**Resultado:** nginx, Django e Compose encaminham/configuram o protocolo e os cookies; a restrição da porta publicada está documentada como requisito de firewall. A aplicação não consegue verificar a ACL externa. O endereço/CIDR de origem do HAProxy e a confirmação dessa regra permanecem pendentes no deploy.

- [x] **Passo 4: Validar interpolação do Compose com valores fictícios**

Rodar `docker compose config` com DNS fictício apenas para validar o formato e inspecionar se o serviço `web` contém DNS e volume somente leitura. Rodar também sem `AD_DNS_PRIMARY`/`AD_DNS_SEARCH`.  
Esperado: configuração completa renderiza; configuração vazia falha com mensagem das variáveis obrigatórias; nenhum valor real de produção é exibido ou gravado.

---

## Sprint 3 — Autenticação híbrida, mensagens e sessão

**Seleção de execução:** inline, conforme confirmado pelo usuário.

**Status:** concluída. Serviço/backend híbridos, mensagens de login e sessão de oito horas implementados. Suíte completa: 251 testes executados, 27 ignorados, 1 falha esperada e nenhuma falha; checks Django e de migração sem pendências. Nenhuma conexão com AD real foi feita.

### Tarefa 6: Implementar AuthenticationService e backend único

**Arquivos:**
- Criar: `colaboradores/authentication.py`
- Criar: `colaboradores/auth_backends.py`
- Modificar: `controle_veiculos/settings.py`
- Modificar: `colaboradores/tests_auth_ad.py`

**Interfaces:**
- Produz: `AuthenticationService(directory_client_factory).authenticate(username, password) -> AuthenticationResult`; `HybridAuthBackend.authenticate(request, username, password)`; `AuthenticationResult(user, status)` com `AuthenticationStatus` (`OK`, `INVALID`, `DIRECTORY_UNAVAILABLE`, `ACCOUNT_DISABLED`, `ACCOUNT_EXPIRED`, `ACCOUNT_LOCKED`, `PASSWORD_EXPIRED`, `MUST_CHANGE_PASSWORD`, `IDENTITY_MISMATCH`). `map_directory_status(status)` converte os estados do cliente LDAP em estados de autenticação.
- Consome: `Funcionario.auth_source`, `DirectoryClient.find_user` e `DirectoryClient.verify_password`.

- [x] **Passo 1: Escrever testes do roteamento sem fallback**

Cobrir login local correto com cliente LDAP que falha se chamado; conta `DIRECTORY` com login AD correto; senha vazia; usuário inexistente/inativo; AD indisponível sem `check_password`, alteração de usuário ou fallback; primeiro GUID gravado após sucesso; GUID divergente negado; conta DIRECTORY com hash local inutilizável.

```python
def test_usuario_local_autentica_sem_chamar_directory(self):
    from unittest.mock import Mock
    local = Funcionario.objects.create_user(username="ana.silva", password="SenhaLocal-123")
    directory_factory = Mock()
    result = AuthenticationService(directory_client_factory=directory_factory).authenticate(local.username, "SenhaLocal-123")
    self.assertEqual(result.user.pk, local.pk)
    directory_factory.assert_not_called()
```

- [x] **Passo 2: Rodar testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.AuthenticationServiceTests -v 2`  
Esperado: `AuthenticationService` ainda não existe.

- [x] **Passo 3: Implementar serviço de autenticação**

Remover espaços ao redor do login, rejeitar senha vazia, localizar cadastro por username sem diferenciar maiúsculas/minúsculas e rotear pela origem antes de instanciar/chamar cliente LDAP. Preservar no banco a grafia do `sAMAccountName`. Para `LOCAL`, validar somente hash Django. Para `DIRECTORY`, executar busca e bind, comparar UUID e salvar GUID apenas depois de `OK`. Retornar status tipado para falha inválida, indisponível, conta negada e divergência.

Fluxo mínimo:

```python
if not password:
    return AuthenticationResult(None, AuthenticationStatus.INVALID)
user = get_user_model().objects.filter(username__iexact=username.strip()).first()
if user is None or not user.is_active:
    return AuthenticationResult(None, AuthenticationStatus.INVALID)
if user.auth_source == Funcionario.AuthSource.LOCAL:
    if user.check_password(password):
        return AuthenticationResult(user, AuthenticationStatus.OK)
    return AuthenticationResult(None, AuthenticationStatus.INVALID)
directory_client = directory_client_factory()
lookup = directory_client.find_user(user.username)
if lookup.status != DirectoryStatus.OK:
    return AuthenticationResult(None, map_directory_status(lookup.status))
if user.directory_guid and user.directory_guid != lookup.entry.object_guid:
    return AuthenticationResult(None, AuthenticationStatus.IDENTITY_MISMATCH)
status = directory_client.verify_password(lookup.entry.dn, password)
if status == DirectoryStatus.OK and user.directory_guid is None:
    user.directory_guid = lookup.entry.object_guid
    user.save(update_fields=["directory_guid"])
return AuthenticationResult(
    user if status == DirectoryStatus.OK else None,
    map_directory_status(status),
)
```

Mapear `DirectoryStatus.INVALID`, `NOT_FOUND` e `AMBIGUOUS` para `AuthenticationStatus.INVALID`; `UNAVAILABLE` para `DIRECTORY_UNAVAILABLE`; status de conta para o estado correspondente; `OK` para `OK`. A view não deve distinguir usuário inexistente de senha errada.

- [x] **Passo 4: Registrar um único backend Django híbrido**

Implementar `HybridAuthBackend` derivado de `ModelBackend` para manter autorização `has_perm`; adicionar somente esse backend à lista `AUTHENTICATION_BACKENDS`. O backend grava o resultado tipado no request e retorna usuário apenas em sucesso, de modo que Django não passe a outro backend após falha DIRECTORY.

- [x] **Passo 5: Rodar testes do serviço e backend**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.AuthenticationServiceTests colaboradores.tests_auth_ad.HybridAuthBackendTests -v 2`  
Esperado: LOCAL nunca inicia LDAP, DIRECTORY nunca cai para senha local, GUID é persistido corretamente e indisponibilidade não altera cadastro.

### Tarefa 7: Integrar a tela de login e política de sessão

**Arquivos:**
- Criar: `colaboradores/auth_views.py`
- Modificar: `controle_veiculos/urls.py`
- Modificar: `controle_veiculos/settings.py`
- Testar: `colaboradores/tests_auth_ad.py`
- Usar template existente: `controle_veiculos/templates/login.html`

**Interfaces:**
- Produz: `HybridLoginView` que apresenta mensagem baseada em resultado tipado sem revelar existência da conta.
- Consome: `HybridAuthBackend` e `AuthenticationResult` da Tarefa 6.

- [x] **Passo 1: Escrever testes da tela e da sessão**

Testar: credencial inválida mostra texto genérico; AD indisponível mostra “Serviço de autenticação indisponível. Tente em instantes.”; bloqueio/expiração usa mensagem de suporte; usuário inexistente e senha errada não revelam a existência; sucesso conserva o redirecionamento por grupo existente; configurações de sessão são `SESSION_COOKIE_AGE=28800` e `SESSION_EXPIRE_AT_BROWSER_CLOSE=True`.

- [x] **Passo 2: Rodar testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.HybridLoginViewTests -v 2`  
Esperado: view e mensagens específicas ainda não existem.

- [x] **Passo 3: Implementar view e mensagens**

Substituir o `LoginView` padrão em `/login/` por `HybridLoginView`; ler apenas o status tipado do backend e mostrar mensagem própria para indisponibilidade e mensagem genérica para credencial inválida. Não contar indisponibilidade como tentativa errada e não bloquear usuário `DIRECTORY` na aplicação.

Mapear resultados no ponto de apresentação: `UNAVAILABLE` vira a mensagem de serviço indisponível; `DISABLED`, `EXPIRED`, `LOCKED` e `MUST_CHANGE_PASSWORD` usam a orientação aprovada pela skill; `INVALID`, `NOT_FOUND`, `AMBIGUOUS` e divergência exibem mensagem genérica.

- [x] **Passo 4: Configurar sessão e cookies de produção**

Definir `SESSION_COOKIE_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))`, `SESSION_EXPIRE_AT_BROWSER_CLOSE = True` e rotação do identificador no login. Manter cookies seguros no Compose de produção e HTTP local selecionável sem mudar o `.env` local.

- [x] **Passo 5: Rodar os testes de login e sessão**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.HybridLoginViewTests -v 2`  
Esperado: mensagens não revelam existência/estado indevido; sucesso inicia sessão dentro da política e o fluxo de login preserva página inicial por permissões locais.

---

## Sprint 4 — Auditoria, documentação e corte operacional

**Seleção de execução:** inline, conforme confirmado pelo usuário.

**Status:** concluída. Auditoria estruturada, documentação de deploy/corte e checklist operacional preparados. Suíte completa: 258 testes executados, 27 ignorados, 1 falha esperada e nenhuma falha; checks Django/migrações e build Docker passaram. Teste real no AD e confirmação da ACL do HAProxy permanecem pendentes da infraestrutura.

### Tarefa 8: Registrar eventos de autenticação e administração

**Arquivos:**
- Criar: `colaboradores/auth_logging.py`
- Modificar: `colaboradores/authentication.py`
- Modificar: `colaboradores/admin.py`
- Testar: `colaboradores/tests_auth_ad.py` e `colaboradores/tests_auth_admin.py`

**Interfaces:**
- Produz: eventos estruturados de login e mudanças de origem/GUID/grupos, sem dados secretos.
- Consome: resultado tipado do serviço e eventos do admin.

- [x] **Passo 1: Escrever testes que proíbam dados sensíveis nos logs**

Capturar logs de sucesso, falha, indisponibilidade, GUID gravado/divergente e alteração administrativa. Confirmar inclusão de login, origem, resultado e IP quando disponível; confirmar ausência de senha, hash, senha de serviço e resposta LDAP completa.

- [x] **Passo 2: Rodar testes para confirmar falha**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.AuthLoggingTests colaboradores.tests_auth_admin.AuthAdminAuditTests -v 2`  
Esperado: logger de autenticação estruturado ainda não existe.

- [x] **Passo 3: Implementar logging e conectar os eventos**

Usar logger dedicado `colaboradores.auth`; emitir os eventos definidos na especificação e registrar o perfil TLS/transport no startup. Não registrar filtros LDAP completos, atributos LDAP ou credenciais.

Exemplo de evento sem segredo:

```python
logger.info(
    "authentication_result login=%s source=%s result=%s remote_addr=%s",
    username, source, result.status, remote_addr,
)
```

- [x] **Passo 4: Rodar testes de auditoria**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad.AuthLoggingTests colaboradores.tests_auth_admin.AuthAdminAuditTests -v 2`  
Esperado: eventos têm campos previstos e nenhum segredo aparece.

### Tarefa 9: Documentar configuração, desligamento e transição das contas

**Arquivos:**
- Criar: `docs/DEPLOY_AD.md`
- Modificar: `docs/UTILIZACOES_DO_SISTEMA.md`
- Modificar: `docs/CONTEXTO_RETOMADA.md`

**Interfaces:**
- Produz: instruções de preenchimento de ambiente, deploy seguro, operação e transição manual.
- Consome: nomes finais de variáveis e comandos das Tarefas 4 e 5.

- [x] **Passo 1: Documentar as variáveis e a CA**

Listar `LDAP_URI`, `LDAP_BASE_DN`, `LDAP_BIND_USER`, `LDAP_BIND_PASSWORD`, `LDAP_TLS_PROFILE`, `LDAP_CA_CERT_FILE`, `LDAP_NETWORK_TIMEOUT`, `LDAP_OPERATION_TIMEOUT`, `AD_DNS_PRIMARY`, `AD_DNS_SEARCH` e `SESSION_MAX_AGE`. Dizer quais valores o usuário/infra preenchem, onde montar a CA e que segredo não deve ir ao Git.

- [x] **Passo 2: Documentar fluxo de cadastro e grupos**

Explicar criação de usuário individual `DIRECTORY`, username igual ao `sAMAccountName`, grupos `Portaria`/`Financeiro` locais, usuários `LOCAL` de emergência e ausência de sincronização de grupos/atributos. Antes do corte, listar permissões diretas `user_permissions` existentes e orientar a migrá-las para grupos antes de desativar contas. Marcar `criar_portaria` e `criar_financeiro` como comandos legados para as antigas contas genéricas e orientar a não usá-los para contas `DIRECTORY`; confirmar que `entrypoint.sh` executa apenas `configurar_perfis`.

- [x] **Passo 3: Documentar desligamento e corte**

Explicar: desabilitar a conta no AD impede novos logins; o cadastro local permanece até desativação manual; sessão existente dura no máximo 8h; manter superusuário local; atribuir grupos e testar cada usuário individual antes da remoção manual das contas genéricas.

- [x] **Passo 4: Documentar verificação dentro do runtime**

Incluir sequência para executar dentro do container web: extrair o hostname da `LDAP_URI` preenchida, confirmar resolução com `getent hosts`, testar TCP/636 e executar `openssl s_client` com a CA e verificação do hostname. Confirmar HAProxy encaminhando HTTPS e que acesso direto não contorna TLS. Não registrar valores secretos no documento.

- [x] **Passo 5: Revisar documentos para consistência**

Conferir que os mesmos nomes de variável, caminho `/run/certs/flexivel-root-ca.crt`, duração de sessão e política de grupos aparecem em todos os documentos.

### Tarefa 10: Executar validação integrada e preparar rollout

**Arquivos:**
- Testar: `colaboradores/tests_auth_ad.py`
- Testar: `colaboradores/tests_auth_admin.py`
- Testar: `colaboradores/tests_directory_config.py`
- Revisar: `docker-compose.yml`, `Dockerfile`, `nginx/default.conf`

**Interfaces:**
- Produz: evidência de testes automatizados e checklist operacional pronto para deploy.
- Consome: todas as tarefas anteriores.

- [x] **Passo 1: Rodar testes focados da integração**

Rodar: `venv/bin/python manage.py test colaboradores.tests_auth_ad colaboradores.tests_auth_admin colaboradores.tests_directory_config -v 2`  
Esperado: todos passam sem depender de AD real.

- [x] **Passo 2: Rodar regressão das permissões e login existentes**

Rodar: `venv/bin/python manage.py test viagens.tests colaboradores.tests -v 1`  
Esperado: grupos locais, redirecionamentos por perfil, cadastro de funcionário e login local continuam compatíveis.

- [x] **Passo 3: Rodar checks de Django, migrações e build**

Rodar `venv/bin/python manage.py check`, `venv/bin/python manage.py makemigrations --check` e `AD_DNS_PRIMARY=192.0.2.53 AD_DNS_SEARCH=example.invalid docker compose build web`.  
Esperado: sem erros de configuração, migração pendente ou dependência ausente.

- [x] **Passo 4: Preparar verificação do ambiente real**

A lista de comandos está em `docs/DEPLOY_AD.md`. DNS, TCP/636, TLS real, login AD e ACL de firewall só podem ser confirmados com configuração e acesso ao ambiente de produção.

Com o `.env` preenchido pelo usuário e o deploy carregando `docker-compose.yml`, executar DNS/TCP/TLS dentro do container real. Fazer primeiro login com uma conta AD de teste, conferir grupo e página inicial, testar admin local quando AD está inacessível, e só então liberar a migração individual.

- [x] **Passo 5: Entregar o estado para operações Git do usuário**

Resumir arquivos alterados, testes executados, variáveis ainda vazias e resultados de runtime. Não executar comandos Git.

## Pendências de implantação que permanecem com o usuário/infraestrutura

- Preencher no `.env` o FQDN do DC, Base DN/OU, UPN e senha da conta de serviço.
- Preencher no ambiente de Compose o IP DNS interno e o sufixo DNS.
- Confirmar no servidor que o FQDN resolve e que TCP/636 e TLS validado funcionam de dentro do container.
- Configurar o HAProxy e restringir o caminho de rede para a aplicação aceitar tráfego seguro somente pelo proxy esperado.
- A TI confirmar se existe mais de um DC e se a conta de serviço será distinta por ambiente.

## Handoff por sprint

Antes de iniciar cada sprint, fazer uma única pergunta: **“Para esta sprint, prefere execução inline ou com subagents?”** Respeitar a resposta para aquela sprint; perguntar novamente na sprint seguinte. Não iniciar a próxima sprint sem apresentar resultado da anterior e obter a escolha de execução correspondente.
