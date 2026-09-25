# Integração de autenticação de usuários com Active Directory

## Objetivo

Permitir que contas individuais cadastradas na aplicação autentiquem com a
senha de rede do Active Directory, preservando a administração local de
permissões por grupos Django e uma conta local de emergência para
superusuários.

## Contexto encontrado

- A aplicação usa Django 6.0 e o usuário customizado `colaboradores.Funcionario`,
  que herda `AbstractUser`.
- O login atual usa `django.contrib.auth.views.LoginView` e os backends padrão;
  não existe integração LDAP.
- Os grupos locais `Portaria` e `Financeiro` já concentram permissões do
  sistema. Eles continuarão sendo a fonte local das permissões.
- `Funcionario.ativo` é um atributo de negócio distinto de `is_active`, usado
  pelo Django para controlar acesso ao login.
- O Compose usado no servidor publica nginx na porta 5009, e o nginx atual
  recebe HTTP na porta 80.
- A configuração Django atual não fixa idade de sessão e deixa os cookies
  seguros desativados por padrão.
- O projeto fixa versões em `requirements.txt`; outra aplicação usa
  `ldap3>=2.9,<3.0`.

## Decisões aprovadas

1. Cada pessoa que fará login terá um cadastro local `Funcionario` e vínculo
   explícito com uma conta do AD. O AD não cria nem sincroniza cadastros.
2. Para contas `DIRECTORY`, `Funcionario.username` será o
   `sAMAccountName` correspondente.
3. As permissões serão locais e concedidas por grupos Django. Novas permissões
   serão adicionadas aos grupos e os grupos serão associados aos usuários.
4. As contas genéricas atuais de portaria e financeiro serão substituídas por
   contas individuais. O usuário fará a remoção manual dessas contas depois da
   transição.
5. Superusuários continuarão com autenticação local e poderão operar quando o
   AD estiver indisponível.
6. O perfil LDAP será `validated`, com LDAPS, cadeia confiável e verificação do
   hostname. A CA PEM existente é `etc/flexivel-root-ca.crt`.
7. A conta de serviço será dedicada e somente leitura. A senha e os demais
   valores de ambiente serão preenchidos pelo usuário, não versionados.
8. O HAProxy terminará HTTPS antes do nginx. A aplicação confiará no protocolo
   encaminhado somente pela cadeia de proxies configurada.
9. O diretório terá clientes próprios com `ldap3>=2.9,<3.0`, mantendo o
   `DirectoryClient` desacoplado do Django.
10. Sessões terão no máximo 8 horas e expirarão ao fechar o navegador.

## Arquitetura

### Componentes

- **Configuração:** lê e valida URI/FQDN do DC, Base DN, usuário e senha de
  serviço, perfil TLS, caminho da CA, timeouts, parâmetros DNS do container e
  política de sessão. Configuração obrigatória ausente ou inválida deve impedir
  a inicialização; não há defaults silenciosos para endpoint, credenciais ou
  perfil TLS.
- **DirectoryClient:** usa `ldap3` para fazer bind da conta de serviço, buscar
  um usuário com filtro LDAP escapado e limite de duas entradas, ler o DN e o
  `objectGUID` bruto, e validar a senha por uma conexão separada. Usa TLS
  validado, timeouts de conexão e operação, rejeita senha vazia antes do bind e
  traduz falhas de rede/TLS separadamente de credenciais inválidas.
- **AuthenticationService e backend Django:** consulta o cadastro local antes
  de qualquer operação LDAP; roteia `LOCAL` e `DIRECTORY`; verifica o GUID;
  registra o primeiro GUID somente depois de autenticação AD bem-sucedida; e
  não faz fallback entre fontes de autenticação.
- **Administração:** cria e edita contas locais e vínculos AD, exibe origem e
  GUID, mantém grupos/permissões locais e oferece religação do GUID após revisão
  administrativa.
- **Sessão e auditoria:** aplica duração de sessão de 8 horas, expiração ao
  fechar o navegador e logs sem credenciais ou respostas LDAP completas.

### Fluxo `DIRECTORY`

1. Rejeitar login ou senha vazios antes de qualquer bind.
2. Localizar `Funcionario` pelo login normalizado; negar usuário ausente ou
   `is_active=False` sem consultar o AD.
3. Se a origem for `LOCAL`, validar apenas a senha Django e encerrar o fluxo.
4. Se a origem for `DIRECTORY`, procurar exatamente um `sAMAccountName` via
   busca LDAP escapada e obter DN mais `objectGUID`.
5. Tratar falha de transporte, TLS, bind de serviço ou busca como AD
   indisponível. Não contar como erro de senha, não alterar estado local e não
   tentar senha local.
6. Se o cadastro já tiver GUID e o GUID retornado divergir, negar e registrar
   evento de auditoria; exigir revisão administrativa.
7. Fazer bind com o DN e a senha do usuário. Um bind bem-sucedido grava o GUID
   quando ainda estiver vazio e autentica a sessão.
8. O AD não altera nome, e-mail, unidade, centro de custo, estado local, grupos
   ou permissões.

Mensagens de credencial serão genéricas. Indisponibilidade do AD terá mensagem
própria. O bloqueio da conta de rede fica com o AD; o cadastro local só será
desativado manualmente.

### Modelo e administração de usuários

- Adicionar a `Funcionario` uma origem de autenticação, `LOCAL` ou
  `DIRECTORY`. Novas instâncias do modelo usam `DIRECTORY` por padrão, conforme
  decisão posterior do usuário; a migração atribui `LOCAL` aos registros já
  existentes. Os fluxos de criação definem a origem explicitamente: criação
  local e superusuários usam `LOCAL`, vínculos AD usam `DIRECTORY`. O campo
  `directory_guid` é um UUID LDAP opcional, único e não editável diretamente.
- Usar formulários de criação distintos: o formulário `DIRECTORY` não terá
  campos nem link para definir/trocar senha; o formulário `LOCAL` manterá a
  senha local. Tentativas de enviar senha em operação `DIRECTORY` serão
  recusadas no servidor.
- Criar uma conta `DIRECTORY` atribui senha inutilizável. Converter `LOCAL` em
  `DIRECTORY` também inutiliza a senha local. Converter de volta para `LOCAL`
  exige senha nova e limpa o GUID.
- Mudanças de origem ou permissão não criam nem alteram automaticamente grupos.
  O administrador associa os grupos locais apropriados ao usuário.
- A desativação local permanece manual, separada de `Funcionario.ativo`. A
  remoção das contas genéricas será feita pelo usuário após a transição.
- Superusuários locais permanecem disponíveis para contingência do AD.

## Configuração e deploy

- Adicionar a dependência `ldap3>=2.9,<3.0` e fixar no `requirements.txt` uma
  versão concreta validada dentro desse intervalo, mantendo o padrão de versões
  fixas deste projeto.
- Configurar `LDAP_TLS_PROFILE=validated`, LDAPS por FQDN, Base DN, conta de
  serviço UPN, senha, timeouts de conexão/operação, caminho da CA e sessão de
  28.800 segundos. A configuração será validada no startup.
- Acrescentar ao `.env` local os campos de infraestrutura vazios para o usuário
  preencher; não ler nem sobrescrever as demais entradas existentes. Manter um
  `.env.example` sem segredos.
- Montar `./etc/flexivel-root-ca.crt` no serviço web em caminho de container
  somente leitura. O arquivo é uma CA pública, não uma chave privada.
- Declarar `dns` e `dns_search` no escopo do container de produção usando
  variáveis obrigatórias de implantação, sem gravar IPs corporativos no
  repositório. O procedimento de deploy deve carregar essa definição.
- Configurar HAProxy para encaminhar HTTPS de forma confiável e nginx/Django
  para preservar e confiar no protocolo somente vindo do proxy permitido.
  Ativar cookies `Secure`, `HttpOnly`, `SameSite=Lax` e CSRF seguro quando
  HTTPS estiver confirmado.
- No ambiente implantado, verificar resolução do FQDN dentro do container,
  TCP/636 e TLS com validação de CA e hostname. Resultado local não substitui
  essa validação.

## Eventos de auditoria

Registrar login bem-sucedido, credencial inválida, conta AD indisponível ou
negada, GUID gravado, GUID divergente e mudanças administrativas em origem,
estado, GUID e permissões. Incluir horário, login, origem, resultado e IP
quando disponível. Nunca registrar senha, hash, senha de serviço ou atributos
LDAP além do GUID necessário.

## Testes e aceite

- Usuário `LOCAL` autentica sem inicializar conexão LDAP, inclusive quando o
  AD não está acessível.
- Usuário `DIRECTORY` não autentica por senha local e o fluxo recusa senha
  vazia antes de qualquer bind.
- Bind inválido é diferente de indisponibilidade por rede, timeout ou TLS; a
  indisponibilidade não altera estado nem senha local.
- Busca escapa o login e trata nenhum resultado e resultado ambíguo sem criar
  usuários.
- GUID é convertido dos 16 bytes little-endian; primeiro sucesso grava uma
  vez e divergência nega acesso.
- Conta `DIRECTORY` não pode definir nem trocar senha; transição para `LOCAL`
  exige senha nova.
- Grupos Django continuam concedendo permissões localmente, sem consulta ou
  sincronização de grupos do AD.
- Configuração ausente/conflitante falha no startup; TLS `validated` exige CA
  legível e endpoint FQDN.
- Testes de sessão confirmam 8 horas e expiração ao fechar o navegador.
- A implantação confirma DNS, TCP, CA e hostname a partir do container real.

## Pendências operacionais para preenchimento/validação

- [NÃO DETERMINADO] FQDN do DC e Base DN/OU de busca; serão preenchidos no
  `.env` pelo usuário.
- [NÃO DETERMINADO] UPN da conta de serviço e senha; serão preenchidos no
  `.env` pelo usuário, sem registrar a senha no repositório ou em mensagens.
- [NÃO DETERMINADO] IP do DNS interno e sufixo DNS do container; serão
  fornecidos pela infraestrutura e preenchidos no ambiente de deploy.
- [NÃO DETERMINADO] Alcance de DNS, TCP/636 e validação do certificado dentro
  do runtime de produção; só pode ser comprovado após implantação.
- [NÃO DETERMINADO] Configuração concreta de HTTPS e lista de IPs confiáveis
  do HAProxy; dependem do ambiente externo que termina TLS.
- [NÃO DETERMINADO] Se existe mais de um DC e se cada ambiente terá conta de
  serviço distinta; confirmar com a TI antes de preencher configuração final.

## Fora de escopo

- Sincronizar ou mapear grupos do AD para grupos/permissões locais.
- Criar, atualizar ou desativar cadastro local a partir do AD.
- Autenticar em cache quando o AD estiver indisponível.
- Remover automaticamente as contas genéricas de portaria e financeiro.
