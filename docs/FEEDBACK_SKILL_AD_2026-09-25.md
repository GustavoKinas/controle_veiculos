# Registro para melhorar a skill de integração com AD

**Data:** 25/09/2026  
**Escopo:** conversa iniciada pelo pedido para integrar os usuários desta
aplicação ao Active Directory usando a skill `active-directory-integration`.
O pedido anterior de leitura de `docs/CONTEXTO_RETOMADA.md` não faz parte deste
registro.

## Objetivo do usuário

Integrar contas individuais da aplicação ao AD. Hoje existem contas locais
genéricas (`portaria`, `financeiro`) associadas a grupos locais. Após a
implementação, os usuários individuais serão vinculados ao AD e receberão
permissões por grupos. O usuário pediu que dúvidas fossem esclarecidas antes da
implementação; depois direcionou o trabalho para um plano por sprints/tarefas,
com escolha entre execução inline ou subagents antes de cada sprint.

## Decisões confirmadas

- As permissões continuarão locais e serão concedidas pelos grupos existentes.
  Permissões novas serão acrescentadas aos grupos antes de associá-los aos
  usuários.
- As contas genéricas serão substituídas por contas individuais. O usuário
  removerá as contas genéricas manualmente após a transição.
- Superusuários administradores continuarão autenticando localmente para
  contingência quando o AD estiver indisponível.
- Para contas AD, `Funcionario.username` corresponderá a
  `sAMAccountName`.
- O perfil escolhido foi TLS `validated`.
- O certificado está em
  `etc/flexivel-root-ca.crt`; é PEM e pode ser montado somente leitura no
  container. O usuário pretende versionar a CA para que o servidor a receba no
  `git pull`.
- Existe uma conta de serviço. O usuário pediu campos de configuração vazios
  para preencher, sem enviar a senha pelo chat.
- A infraestrutura fornecerá IP de DNS interno e sufixo DNS para os campos de
  configuração do container.
- O HAProxy será usado para terminar HTTPS antes do nginx.
- Outra aplicação usa `ldap3>=2.9,<3.0`; o usuário indicou essa faixa para esta
  integração.
- Contas `DIRECTORY` não devem sequer oferecer campos ou fluxo de definição de
  senha. A criação terá formulário próprio sem senha; contas `LOCAL` usarão um
  fluxo separado.
- O usuário pediu para não executar operações Git; ele próprio cuidará delas.

## Descobertas relevantes no repositório

- `Funcionario` herda `AbstractUser`, então já possui identidade Django,
  senha, grupos e permissões por usuário.
- O projeto usa Django 6.0 e não tinha backend LDAP instalado.
- O login usava o `LoginView` padrão.
- Os grupos locais `Portaria` e `Financeiro` já concentram permissões.
- `Funcionario.ativo` é status de negócio, diferente de `is_active`, que
  controla o login.
- O nginx do Compose escuta apenas HTTP na porta 80, publicada como 5009; as
  opções de cookies seguros estão desativadas por padrão no Django. O uso do
  HAProxy precisa preservar o protocolo original e limitar a confiança ao
  proxy conhecido.
- A definição atual do Compose não configura DNS para o container.
- A CA encontrada também veio acompanhada por `etc/flexivel-root-ca.crt:Zone.Identifier`,
  que não faz parte do certificado.

## Linha do tempo da interação

1. O usuário pediu integração AD, descreveu a estrutura atual de usuários e
   grupos, e pediu perguntas antes da implementação.
2. O assistente leu a skill e inspecionou o modelo Django, login, grupos,
   configurações de sessão e Compose antes de perguntar.
3. O usuário redirecionou para um plano com sprints/tarefas e pediu escolha de
   execução inline ou com subagents antes de cada sprint.
4. A descoberta de requisitos aconteceu em várias rodadas: grupos locais,
   remoção manual das contas genéricas, admins locais, chave `username`, perfil
   TLS/CA, conta de serviço, DNS interno, HTTPS pelo HAProxy e versão de
   `ldap3`.
5. O assistente propôs `DirectoryClient` próprio com `ldap3`; o usuário aprovou
   essa direção e aprovou em seções o desenho de autenticação, cadastro/admin,
   configuração/transporte e sessão/auditoria.
6. O usuário acrescentou que usuários `DIRECTORY` não podem ter opção de
   cadastrar senha. O desenho foi ajustado para separar os fluxos de criação
   `DIRECTORY` e `LOCAL`, sem senha no primeiro.
7. Foi criado o documento de desenho
   `docs/superpowers/specs/2026-09-25-integracao-ad-usuarios-design.md`.
   Ainda não foi escrito o plano de sprints; o fluxo aguardava revisão do
   desenho.
8. A skill de brainstorming pedia commit do desenho. O assistente tentou
   staging, mas o `.git` estava somente para leitura; ao solicitar elevação, o
   usuário interrompeu e instruiu: “Você não mexe com git, eu faço tudo”. Não
   houve commit. A especificação segue como arquivo não staged; operações Git
   devem ficar com o usuário.

## Observações para melhorar a skill

### 1. Conciliar perguntas em lote com perguntas uma a uma

A skill AD recomenda agrupar perguntas por bloco, enquanto a skill de
brainstorming recomenda uma pergunta por mensagem. Na prática, a descoberta se
espalhou por muitas rodadas, mesmo com vários itens operacionais relacionados.

**Sugestão:** a skill AD deve indicar quais decisões são realmente bloqueantes
e permitir apresentar uma única ficha curta com perguntas independentes por
bloco (identidades/permissões, TLS/rede, conta de serviço e operação). Fazer
perguntas subsequentes apenas quando uma resposta depender de outra ou quando a
resposta mudar a arquitetura.

### 2. Distinguir valores de infraestrutura de decisões de arquitetura

O usuário preferiu preencher campos vazios no `.env` em vez de enviar FQDN,
Base DN, UPN, senha da conta de serviço, DNS e sufixo no chat.

**Sugestão:** permitir que a skill registre os nomes das variáveis necessárias
como pendências operacionais e prossiga com implementação quando a arquitetura
estiver definida. A falta de valores reais só deve bloquear etapas que
dependam deles, como conexão de produção; não deve obrigar o usuário a divulgar
segredos na conversa.

### 3. Tornar explícito o contrato de senha para contas DIRECTORY

A skill já determina que usuários de diretório não tenham senha local
utilizável e não vejam telas de troca/recuperação. Nesta conversa, o usuário
esperava algo mais estrito: nem mesmo campos de senha no cadastro.

**Sugestão:** explicitar no checklist de administração que a criação/edição de
usuários `DIRECTORY` não deve oferecer campos, links ou endpoints de definição
de senha local; a validação do servidor também deve rejeitar senha em payloads
`DIRECTORY`. Descrever separadamente os formulários `LOCAL` e `DIRECTORY`.

### 4. Respeitar escolha de execução por sprint

O usuário não escolheu um método único para o trabalho inteiro; pediu ser
consultado antes da execução de cada sprint.

**Sugestão:** registrar preferências de execução com escopo explícito. Uma
preferência “por sprint” deve gerar a pergunta inline/subagents no início de
cada sprint, sem convertê-la em uma escolha global no handoff do plano.

### 5. Respeitar o controle Git do usuário

A skill de brainstorming usada no fluxo mandava commitar a especificação,
apesar de o usuário ter pedido planejamento e não ter autorizado operações
Git. O sandbox também bloqueou escrita em `.git`; a tentativa de elevação foi
interrompida pelo usuário, que declarou que fará todo o trabalho Git.

**Sugestão:** incluir uma regra de precedência clara: preferências explícitas
do usuário sobre Git (não usar Git, não stagear, não commitar ou não fazer
push) prevalecem sobre instruções genéricas da skill. Criar o artefato pedido
no workspace não implica autorização para stage/commit/push. Registrar o
estado como não commitado e entregar o caminho para revisão.

### 6. Apoiar a transição de usuários genéricos sem desativação automática

O plano precisa manter os registros existentes como `LOCAL` na migração, criar
os cadastros individuais como `DIRECTORY` manualmente e preservar as contas
genéricas até o usuário removê-las.

**Sugestão:** acrescentar ao modelo de rollout um caso de transição em que
contas genéricas são removidas pelo administrador humano após validar as
contas individuais e os grupos; nunca automatizar a remoção como parte da
migração.

### 7. Cobrir proxies externos na verificação de HTTPS

A configuração local mostrava somente HTTP, mas o usuário esclareceu que um
HAProxy externo termina HTTPS.

**Sugestão:** adicionar à descoberta perguntas sobre terminação TLS fora do
projeto e instruções para preservar `X-Forwarded-Proto` através de todos os
proxies, confiar apenas nos proxies conhecidos e verificar cookies/CSRF no
runtime efetivo. Não concluir que falta HTTPS apenas olhando o nginx da
aplicação.

## Estado ao encerrar esta conversa

- Desenho aprovado pelo usuário, salvo em
  `docs/superpowers/specs/2026-09-25-integracao-ad-usuarios-design.md`.
- Nenhum código de integração foi implementado.
- Nenhum plano por sprint foi criado ainda; o desenho deveria ser revisado
  antes do plano.
- Nenhuma operação Git foi concluída; o usuário fará stage, commit e demais
  operações.
- Valores de AD/DNS permanecem para preenchimento pelo usuário e a
  conectividade precisa ser validada dentro do runtime de produção.
