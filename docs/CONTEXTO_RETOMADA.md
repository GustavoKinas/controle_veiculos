# Contexto para retomar o trabalho

Atualizado em **30/09/2026**. Este é o resumo operacional; histórico, decisões
já fechadas e procedimentos detalhados estão em [`HISTORICO.md`](HISTORICO.md)
e nos documentos específicos listados ao final.

## Estado atual

### Integração com Active Directory

As quatro sprints de implementação e a validação operacional com o Active
Directory foram concluídas.

| Área | Status atual |
| --- | --- |
| Implementação | Cadastro LOCAL/DIRECTORY, vínculo por `objectGUID`, autenticação híbrida, permissões por grupos Django, administração e auditoria implementados. |
| Verificação local | 258 testes executados: 27 ignorados, 1 falha esperada e nenhuma falha. `manage.py check`, verificação de migrações e build Docker passaram. |
| Configuração AD | O `.env` local continua vazio conforme combinado. As credenciais de bind no `.env` de produção foram corrigidas e o usuário confirmou que a integração com o AD está validada. |
| Aplicação e HTTPS | O `web` voltou a iniciar e a página abriu depois de deixar o redirect HTTP→HTTPS a cargo do HAProxy (`SECURE_SSL_REDIRECT=False` no Compose). Os cookies continuam seguros e o Django confia em `X-Forwarded-Proto`. |
| Infraestrutura | A integração AD foi validada em produção. Ainda falta confirmar a ACL da porta publicada `5009` para o HAProxy e testar a contingência de superusuário LOCAL com o AD indisponível. |
| Contas genéricas | Nenhuma conta ou grupo genérico foi removido. Migrar as permissões para grupos e validar os usuários individuais antes; a remoção será feita manualmente pelo usuário. |

- O checklist de configuração, validação e corte está em
  [`DEPLOY_AD.md`](DEPLOY_AD.md); o plano concluído está em
  [`superpowers/plans/2026-09-25-integracao-ad-usuarios.md`](superpowers/plans/2026-09-25-integracao-ad-usuarios.md).
- O teste de contingência para superusuário LOCAL com AD indisponível ainda
  deve ser feito no ambiente implantado.

### Agenda de viagens e reservas de veículos

- A visualização mensal agora representa reservas de vários dias como uma
  barra contínua pelo período reservado. O seletor de veículo carrega o
  panorama do mês e as reservas do veículo escolhido.
- Os ajustes mais recentes mostram `MODELO - PLACA` no cabeçalho do panorama e
  o nome do funcionário alinhado à esquerda nos cards de um dia. Reservas de
  vários dias mantêm o nome centralizado.
- O usuário atualizou o servidor após `git pull`, executou `docker compose up
  -d --build` e confirmou que testou em produção. A implementação está
  aprovada pelo usuário.
- O trabalho está na branch `codex/agenda-multidias-veiculo`, publicada no
  GitHub, com três commits: `3dc9f08` (agenda multidias), `af737b2` (ajustes
  visuais) e `7a446da` (nome do requisitante e veículo no cabeçalho). Ainda
  falta integrar a branch em `main`; o usuário fará o merge pelo GitHub.
- A branch contém os arquivos de plano e especificação da agenda como arquivos
  não rastreados; eles não fazem parte dos três commits. A cópia local de
  `main` também tem alterações não commitadas em `CONTEXTO_RETOMADA.md`,
  `DEPLOY_AD.md` e `HISTORICO.md`, além desses dois arquivos não rastreados.
  Considerar esse estado ao preparar o merge para não misturar documentação
  local com os commits da funcionalidade.

- Aplicação Django de controle de viagens, reservas de veículos e rateio por
  centro de custo. As cinco fases do pré-cadastro de viagens, perfis de acesso,
  deploy Dockerizado e sincronização de reservas pelo Outlook estão
  implementados.
- A sincronização de funcionários pelo ERP também está implementada. A
  execução manual contra a API real foi confirmada na máquina local em
  23/09/2026 e no Docker de produção em **24/09/2026**.
- A implantação em produção teve dois problemas distintos já diagnosticados:
  uma `LDAP_URI` malformada impediu o Gunicorn de iniciar e causou os 502 do
  nginx; depois de corrigida, a aplicação iniciou. Em seguida, o redirect HTTPS
  repetia porque o Compose forçava `SECURE_SSL_REDIRECT=True`; a configuração
  foi alinhada ao HAProxy e o usuário confirmou que a página abriu.
- O Dockerfile inclui OpenSSL para conferir o certificado do DC dentro do
  container.
- O loop de redirects HTTPS foi rastreado até `SECURE_SSL_REDIRECT=True` no
  Compose: o HAProxy é quem termina TLS e deve fazer o redirect. O Compose foi
  alinhado ao padrão da outra aplicação (`SECURE_SSL_REDIRECT=False`), mantendo
  a confiança em `X-Forwarded-Proto` e cookies seguros. Após recriar o serviço,
  o usuário confirmou que a página abriu.
- O primeiro login DIRECTORY falhou com `DIRECTORY_UNAVAILABLE`: o bind
  retornou LDAP `49`, `invalidCredentials`, subcódigo AD `52e`. As credenciais
  foram corrigidas no `.env` de produção e o usuário confirmou que a integração
  com o AD está validada. Não registrar os valores das credenciais neste
  repositório.
- A primeira execução automática de `scheduler-erp` foi observada em produção,
  mas falhou porque o ambiente do cron não encontrava `python`. A configuração
  do `PATH` no arquivo de crontab foi corrigida no código; ainda é necessário
  publicar a imagem atualizada e confirmar uma execução bem-sucedida.

## Próximos passos

1. Integrar pelo GitHub a branch `codex/agenda-multidias-veiculo` em `main`;
   o usuário já confirmou o teste em produção e aprovou as alterações.
2. Confirmar o IP/CIDR do HAProxy, restringir a porta 5009 no firewall e
   verificar que acesso direto é bloqueado antes de confiar no
   `X-Forwarded-Proto`.
3. Testar o superusuário LOCAL com o AD indisponível no ambiente implantado.
4. Migrar permissões diretas para grupos e só então fazer a transição e remoção
   manual das contas genéricas, conforme o plano de corte.
5. Após o rebuild em produção, confirmar uma execução bem-sucedida do cron
   `scheduler-erp` (admissões às 07:15 e 18:15; demissões às 07:20 e 18:20,
   de segunda a sexta, horário de São Paulo). A execução manual no Docker de
   produção já foi validada.
6. Confirmar com o usuário a regra implementada para demissão de código ERP
   desconhecido: criar o funcionário já inativo. A decisão ainda está
   assinalada no topo de `colaboradores/sincronizacao_erp.py`.
7. Testar as telas com um usuário real do grupo Portaria. Os testes anteriores
   usaram administrador/superusuário, que ignora as permissões do grupo.
8. Antes de confiar nos dados de desenvolvimento, revisar os 7 registros de
   viagens e 2 fechamentos de teste e corrigir os hodômetros que ainda carregam
   valores residuais.
9. Retomar os bugs listados em `ESTUDO.md`, principalmente viagem retroativa
   após fechamento e fechamentos com períodos sobrepostos.
10. Avaliar as pendências operacionais restantes: colaboradores da EVO sem
   centro de custo, reservas de dia inteiro que atravessam vários dias e
   backup automatizado do Postgres em produção.

## Decisão pendente

O desenho aprovado da sincronização ERP não especificava o que fazer quando
uma demissão retorna código ERP desconhecido. A implementação cria o registro
já inativo, simetricamente à admissão. Essa regra foi escolhida durante a
implementação e aguarda confirmação do usuário.

## Armadilhas críticas

- `Model.save()` não chama validação. Código que cria `Viagem` fora de um
  ModelForm deve chamar `full_clean()`; congele o centro de custo antes da
  validação.
- Use `timezone.localdate()` para a data local do Django e
  `datetime.now(FUSO)` nas integrações. `date.today()` pode avançar o dia antes
  da meia-noite em São Paulo quando o container usa UTC.
- `clean()` pode receber instância incompleta. Verifique `None` antes de
  comparar campos; para FK obrigatória não preenchida, consulte `campo_id`
  antes de acessar `campo`.
- `add_error()` só aceita campos presentes no formulário. Erros de campos
  ausentes devem virar erros gerais do formulário.
- No Postgres, combine `select_for_update()` com FK nullable usando
  `of=("self",)` quando houver `select_related()`.
- Validadores de campo não rodam em `save()`. Normalize os dados na entrada;
  não dependa do validador para proteger gravações diretas.
- Dentro do Docker, `localhost` aponta para o próprio container. O Compose
  sobrescreve `DATABASE_URL` para usar o serviço `db`; não altere o `.env` para
  contornar isso.
- Código ERP de funcionário não é globalmente único: sempre use
  `unidade_fabril + codigo_funcionario_erp`. Nomes também podem se repetir
  quando representam identidades ERP distintas.
- O CSV de funcionários usa UTF-8 com BOM; a coluna `Código Empresa` resolve
  `UnidadeFabril.codigo_empresa_erp`, não o nome da unidade. Crie as unidades
  antes de carregar funcionários.
- Scripts com CRLF podem falhar no Linux com `exec format error`; o Dockerfile
  normaliza os scripts copiados para a imagem. Mantenha `requirements.txt` em
  UTF-8.
- Testes que renderizam templates rodam com `DEBUG=False`; precisam do storage
  de teste que dispensa `staticfiles.json`.

## Documentos de referência

- [`HISTORICO.md`](HISTORICO.md) — histórico, decisões fechadas, procedimentos
  e contexto operacional anterior.
- [`superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md`](superpowers/specs/2026-09-22-sincronizacao-funcionarios-erp-design.md)
  — desenho aprovado da sincronização ERP.
- [`superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md`](superpowers/plans/2026-09-23-sincronizacao-funcionarios-erp-plano.md)
  — plano de implementação ERP.
- [`DEVELOPMENT.md`](../DEVELOPMENT.md) — arquitetura e decisões do projeto.
- [`PRE_CADASTRO_VIAGENS.md`](PRE_CADASTRO_VIAGENS.md) — desenho do
  pré-cadastro e da integração Outlook.
- [`UTILIZACOES_DO_SISTEMA.md`](UTILIZACOES_DO_SISTEMA.md) — manual de operação.
- [`DEPLOY_AD.md`](DEPLOY_AD.md) — configuração AD, validação no runtime e corte.
- [`SINCRONIZACAO.md`](SINCRONIZACAO.md) — sync de reservas pelo shell/CLI.
- [`ESTUDO.md`](../ESTUDO.md) — roteiro de estudo e bugs conhecidos.
