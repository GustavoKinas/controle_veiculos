# Contexto para retomar o trabalho

Atualizado em **07/10/2026**. Este é o resumo operacional; histórico, decisões
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

- A agenda mensal representa reservas de vários dias como uma barra contínua
  pelo período reservado. O seletor de veículo filtra o panorama mensal e as
  reservas do dia; também existe a opção de todos os veículos.
- A integração da agenda foi restaurada na branch
  `codex/restore-agenda-multidias`, que está publicada e aponta para o commit
  `e0e2286`. A branch inclui o merge local dos três commits da antiga branch
  `codex/agenda-multidias-veiculo` (`3dc9f08`, `af737b2` e `7a446da`) sobre o
  commit `5f00279` da `main`.
- O usuário informou que a branch de restauração funcionou no servidor. Depois
  desse relato, foram adicionados os commits `83f292e` e `e0e2286`; confirmar
  qual commit está implantado antes de orientar uma atualização de produção.
- Há uma divergência a esclarecer no histórico remoto: o usuário viu no GitHub
  que o PR foi marcado como mergeado no commit `7c72243` para `main`, mas as
  referências locais consultadas mostram `origin/main` em `5f00279`, e o
  commit `7a446da` não aparece como ancestral dessa referência. Isso pode
  indicar referência/repositório diferente ou atualização remota pendente;
  confirmar repositório e executar `git fetch` antes de concluir o que está
  contido na `main` do GitHub.
- A rota `/viagens/lancar/` foi removida para impedir a criação de viagens sem
  reserva. O menu agora leva a “Consultar Viagens lançadas”, uma tela GET de
  consulta das 15 viagens mais recentes. O painel foi centralizado, ampliado e
  não exibe a coluna Centro de Custo.
- Após essa remoção, a entrada da Portaria ainda tentava redirecionar para o
  nome de rota `lancar_viagem`, causando HTTP 500 ao iniciar uma sessão. A causa
  estava em `colaboradores.permissoes.pagina_inicial_de()`: o Django não
  conseguia resolver o nome removido. A correção foi apontar esse redirect para
  `consultar_viagens`, a nova tela de consulta.
- A lógica/formulário de lançamento pela tela antiga foi removida. A criação
  direta continua disponível pelo Django Admin: o `ViagemAdmin` usa o modelo e
  a validação (`full_clean`) apropriada. O formulário de lançamento vinculado
  a reserva continua em uso.
- A migration `viagens/migrations/0010_reserva_viagem_data_fim.py` faz parte do
  código restaurado; aplicar `python manage.py migrate` no ambiente se ainda
  não tiver sido executada.
- O erro de sincronização que tentava gravar `data_fim` nula foi tratado no
  código restaurado, usando a data inicial quando a origem não informa o fim.
  Conferir a versão implantada antes de reexecutar a sincronização.
- A correção de um registro de viagem pendente mencionado pelo usuário foi
  feita manualmente por ele; não há alteração de código pendente para esse
  caso.
- A documentação `GUIA_MERGE_GITHUB.md` explica o processo de recuperação e
  integração. Os arquivos de plano e especificação da agenda ainda aparecem
  como não rastreados no status local, assim como o guia; não foram incluídos
  nos commits de código até a última inspeção.

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

1. Resolver a divergência entre o PR `7c72243` exibido no GitHub e as
   referências locais (`origin/main` em `5f00279`). Conferir a URL do remoto,
   executar `git fetch --all --prune` no repositório correto e inspecionar os
   logs antes de abrir outro PR ou afirmar que a `main` já contém a agenda.
2. Confirmar o commit da branch `codex/restore-agenda-multidias` implantado no
   servidor. Os commits `83f292e` e `e0e2286` foram feitos após o relato de que
   a restauração já funcionava.
3. Caso necessário, atualizar o servidor para o commit aprovado e executar
   `docker compose up -d --build`; aplicar as migrations pendentes com
   `docker compose exec web python manage.py migrate` (incluindo
   `0010_reserva_viagem_data_fim`, se ainda pendente).
4. Confirmar o IP/CIDR do HAProxy, restringir a porta 5009 no firewall e
   verificar que acesso direto é bloqueado antes de confiar no
   `X-Forwarded-Proto`.
5. Testar o superusuário LOCAL com o AD indisponível no ambiente implantado.
6. Migrar permissões diretas para grupos e só então fazer a transição e remoção
   manual das contas genéricas, conforme o plano de corte.
7. Após publicar a imagem atualizada, confirmar uma execução bem-sucedida do
   cron `scheduler-erp` (admissões às 07:15 e 18:15; demissões às 07:20 e
   18:20, de segunda a sexta, horário de São Paulo). A execução manual no
   Docker de produção já foi validada.
8. Confirmar com o usuário a regra implementada para demissão de código ERP
   desconhecido: criar o funcionário já inativo. A decisão ainda está
   assinalada no topo de `colaboradores/sincronizacao_erp.py`.
9. Testar as telas com um usuário real do grupo Portaria. Os testes anteriores
   usaram administrador/superusuário, que ignora as permissões do grupo.
10. Antes de confiar nos dados de desenvolvimento, revisar os 7 registros de
    viagens e 2 fechamentos de teste e corrigir os hodômetros que ainda carregam
    valores residuais.
11. Retomar os bugs listados em `ESTUDO.md`, principalmente viagem retroativa
    após fechamento e fechamentos com períodos sobrepostos.
12. Avaliar as pendências operacionais restantes: colaboradores da EVO sem
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
- [`../GUIA_MERGE_GITHUB.md`](../GUIA_MERGE_GITHUB.md) — recuperação da agenda e explicação de branches, PRs e merges.
- [`SINCRONIZACAO.md`](SINCRONIZACAO.md) — sync de reservas pelo shell/CLI.
- [`ESTUDO.md`](../ESTUDO.md) — roteiro de estudo e bugs conhecidos.
