# Implantação e operação da autenticação com Active Directory

Este documento cobre a configuração do AD, a criação individual dos acessos,
a verificação do container e a transição das contas genéricas. A aplicação
autentica contas cadastradas localmente; ela não cria usuários nem sincroniza
atributos ou grupos do AD.

## Configuração do ambiente

Preencha no `.env` local do servidor, sem copiar segredos para este documento
ou para o repositório:

| Variável | Valor a fornecer | Uso |
|---|---|---|
| `LDAP_URI` | URI `ldaps://<FQDN-do-DC>:636` | Endpoint LDAP. Use o FQDN presente no certificado. |
| `LDAP_BASE_DN` | Base DN/OU de busca | Escopo limitado de pesquisa de usuários. |
| `LDAP_BIND_USER` | UPN da conta de serviço | Conta dedicada, somente leitura. |
| `LDAP_BIND_PASSWORD` | Senha da conta de serviço | Segredo; nunca registrar em logs ou versionar. |
| `LDAP_TLS_PROFILE` | `validated` | Exige validação da CA e do hostname. |
| `LDAP_CA_CERT_FILE` | `/run/certs/flexivel-root-ca.crt` | Caminho no container web. |
| `LDAP_NETWORK_TIMEOUT` | `5` | Timeout de abertura da conexão, em segundos. |
| `LDAP_OPERATION_TIMEOUT` | `10` | Timeout das operações LDAP, em segundos. |
| `AD_DNS_PRIMARY` | IP do DNS corporativo | Resolver o FQDN do Domain Controller no serviço web. |
| `AD_DNS_SEARCH` | Sufixo DNS corporativo | Escopo DNS do serviço web. |
| `SESSION_MAX_AGE` | `28800` | Limite fixo da sessão: oito horas. |

As seis variáveis de infraestrutura (`LDAP_URI`, `LDAP_BASE_DN`,
`LDAP_BIND_USER`, `LDAP_BIND_PASSWORD`, `AD_DNS_PRIMARY` e `AD_DNS_SEARCH`)
foram deixadas vazias no `.env` do desenvolvedor para preenchimento. O
`.env.example` é apenas um modelo sem credenciais. O serviço web falha no
startup se a configuração LDAP obrigatória estiver ausente ou inválida.

A CA pública fica versionada em `etc/flexivel-root-ca.crt` e é montada no
container como `/run/certs/flexivel-root-ca.crt:ro`. Não substitua o FQDN por
um IP e não desative a validação TLS para contornar erro de certificado.

O `docker-compose.yml` exige `AD_DNS_PRIMARY` e `AD_DNS_SEARCH` durante a
interpolação. Depois de preencher as variáveis:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose logs --tail=100 web
```

Não use `docker compose config` sem `--quiet` em ambientes que possam exibir
valores interpolados. A saída de inicialização registra somente transporte
`LDAPS` e perfil TLS, sem UPN, senha ou Base DN.

## Validar DNS, TCP e TLS dentro do serviço web

Execute os comandos no host do deploy. Eles extraem e exibem apenas o hostname
da URI, nunca imprimem o ambiente inteiro nem a senha de serviço.

Resolver o hostname:

```sh
docker compose exec web sh -lc 'HOST=$(python -c '\''import os; from urllib.parse import urlsplit; print(urlsplit(os.environ["LDAP_URI"]).hostname)'\''); getent hosts "$HOST"'
```

Verificar TCP/636:

```sh
docker compose exec web python -c 'import os, socket; from urllib.parse import urlsplit; host=urlsplit(os.environ["LDAP_URI"]).hostname; s=socket.create_connection((host, 636), 5); print("TCP/636 conectado"); s.close()'
```

Validar cadeia da CA e hostname do certificado:

```sh
docker compose exec web sh -lc 'HOST=$(python -c '\''import os; from urllib.parse import urlsplit; print(urlsplit(os.environ["LDAP_URI"]).hostname)'\''); openssl s_client -connect "$HOST:636" -servername "$HOST" -CAfile /run/certs/flexivel-root-ca.crt -verify_hostname "$HOST" -verify_return_error </dev/null'
```

O resultado TLS precisa indicar verificação bem-sucedida. Um teste feito fora
do container não comprova que o DNS, a rota, o certificado e a CA estão
corretos no runtime da aplicação. Não publique a saída completa se a política
interna tratar dados do certificado como informação restrita.

## Proxy HTTPS e firewall

O HAProxy termina HTTPS e precisa enviar `X-Forwarded-Proto: https`; nginx
preserva esse valor para o Django. O serviço web ativa redirect HTTPS e
cookies `Secure`, `HttpOnly` e `SameSite=Lax` no Compose de produção.

A porta publicada `5009` do nginx deve aceitar conexão somente da origem do
HAProxy por regra de firewall no host/rede. Sem essa ACL, um cliente que alcance
a porta diretamente pode forjar `X-Forwarded-Proto`. O código e o Compose não
conseguem aplicar nem comprovar essa regra. Antes da produção, a infraestrutura
deve confirmar o IP/CIDR do HAProxy, aplicar a ACL e testar que um acesso direto
é bloqueado. O endereço de origem ainda depende da infraestrutura.

## Criar usuários e atribuir permissões

1. Confirme que os grupos locais existem e têm as permissões corretas:

   ```sh
   python manage.py configurar_perfis --listar
   ```

2. No Django Admin, escolha **Novo vínculo AD** para uma nova pessoa. O campo
   `username` deve ser o `sAMAccountName` do AD. Associe os grupos locais
   `Portaria`, `Financeiro` ou ambos conforme as responsabilidades. O usuário
   não recebe senha local.
3. Se o cadastro já existir como `LOCAL`, revise o username e use a ação de
   conversão para `DIRECTORY`. A conversão apaga a senha local e limpa o GUID;
   no primeiro login AD válido, o `objectGUID` é vinculado. Uma identidade
   divergente ou GUID já associado a outra pessoa é negado e exige revisão
   administrativa.
4. Novas permissões continuam sendo declaradas em
   `colaboradores/permissoes.py`, atribuídas a um grupo e aplicadas por
   `python manage.py configurar_perfis`. Não atribua permissões diretas a um
   usuário nem sincronize grupos do AD.

Antes do corte, inventarie permissões diretas existentes e migre-as para os
grupos apropriados. Este comando apenas lista usuário e permissão; rode-o em
um shell Django antes de desativar as contas antigas:

```sh
python manage.py shell -c 'from colaboradores.models import Funcionario; [(print(u.username, ",".join(f"{p.content_type.app_label}.{p.codename}" for p in u.user_permissions.all()))) for u in Funcionario.objects.filter(user_permissions__isnull=False).distinct().prefetch_related("user_permissions", "user_permissions__content_type")]'
```

Os comandos `criar_portaria` e `criar_financeiro` são legados para provisionar
as antigas contas genéricas locais. Eles definem autenticação `LOCAL`, recebem
senha e não devem ser usados para contas `DIRECTORY`. `entrypoint.sh` executa
somente migrações, `configurar_perfis` e `collectstatic`; não cria nem altera
usuários operacionais.

## Corte, desligamento e contingência

- Teste cada acesso individual no AD e confirme o grupo e a página inicial
  resultante antes de remover as contas genéricas. A remoção/desativação das
  contas antigas é manual e fica a cargo do administrador.
- Desabilitar a conta no AD bloqueia novos logins. Uma sessão já aberta não
  consulta o AD a cada request e pode permanecer válida até expirar, no máximo
  oito horas; ela também expira ao fechar o navegador.
- `is_active` local permanece uma trava manual independente da conta AD e do
  campo de negócio `ativo`. Nenhum cadastro é desativado automaticamente.
- Mantenha ao menos um superusuário `LOCAL` funcional para administração se o
  DC estiver indisponível. Usuários `LOCAL` continuam autenticando sem chamar
  o AD.
- Não há autenticação em cache quando o AD está fora do ar. Contas DIRECTORY
  recebem mensagem de indisponibilidade; usuários locais e a administração de
  contingência permanecem disponíveis.

## Auditoria e diagnóstico

Os eventos do logger `colaboradores.auth` vão para stdout/stderr do container
web, com horário e nível. Consulte-os com:

```sh
docker compose logs --since=1h web
```

Os eventos incluem resultado de autenticação, origem, login, IP peer visto
pelo Django quando disponível, vínculo/divergência de GUID, criação de conta,
alteração de origem e grupos selecionados. `REMOTE_ADDR` atrás do nginx pode
ser o endereço interno do proxy; o sistema não confia em `X-Forwarded-For` para
preencher esse campo. Senhas, hashes, senha de serviço, filtros e respostas LDAP
completas não são registrados. Restrinja acesso e retenção dos logs conforme a
política corporativa.
