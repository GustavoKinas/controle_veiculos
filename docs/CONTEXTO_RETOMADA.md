# Contexto para retomar o trabalho

Atualizado em **25/09/2026**. Este é o resumo operacional; histórico, decisões
já fechadas e procedimentos detalhados estão em [`HISTORICO.md`](HISTORICO.md)
e nos documentos específicos listados ao final.

## Estado atual

### Integração com Active Directory

As quatro sprints de implementação foram concluídas. O código está pronto para
validação operacional, mas ainda não foi autenticado contra um Domain
Controller real.

| Área | Status atual |
| --- | --- |
| Implementação | Cadastro LOCAL/DIRECTORY, vínculo por `objectGUID`, autenticação híbrida, permissões por grupos Django, administração e auditoria implementados. |
| Verificação local | 258 testes executados: 27 ignorados, 1 falha esperada e nenhuma falha. `manage.py check`, verificação de migrações e build Docker passaram. |
| Configuração AD | Variáveis LDAP/DNS permanecem vazias no `.env`, conforme combinado. Preenchê-las no ambiente de produção; a aplicação web não inicia com configuração obrigatória ausente ou inválida. |
| Infraestrutura | Ainda faltam validar DNS, TCP/636 e certificado TLS de dentro do container, confirmar a ACL da porta publicada `5009` para o HAProxy e testar uma conta AD real. |
| Contas genéricas | Nenhuma conta ou grupo genérico foi removido. Migrar as permissões para grupos e validar os usuários individuais antes; a remoção será feita manualmente pelo usuário. |

- O checklist de configuração, validação e corte está em
  [`DEPLOY_AD.md`](DEPLOY_AD.md); o plano concluído está em
  [`superpowers/plans/2026-09-25-integracao-ad-usuarios.md`](superpowers/plans/2026-09-25-integracao-ad-usuarios.md).
- O teste de contingência para superusuário LOCAL com AD indisponível também
  deve ser feito no ambiente implantado.

- Aplicação Django de controle de viagens, reservas de veículos e rateio por
  centro de custo. As cinco fases do pré-cadastro de viagens, perfis de acesso,
  deploy Dockerizado e sincronização de reservas pelo Outlook estão
  implementados.
- A sincronização de funcionários pelo ERP também está implementada. A
  execução manual contra a API real foi confirmada na máquina local em
  23/09/2026 e no Docker de produção em **24/09/2026**.
- A aplicação foi subida no Docker de produção. No início, o nginx registrou
  respostas 502 por recusa de conexão em `web:8000`; o erro desapareceu cerca
  de quatro minutos depois. O padrão é compatível com o Gunicorn ainda não
  estar pronto durante a inicialização, mas os logs do `web` precisam confirmar
  a sequência antes de tratar isso como causa comprovada.
- O Dockerfile inclui OpenSSL para conferir o certificado do DC dentro do
  container.
- A primeira execução automática de `scheduler-erp` foi observada em produção,
  mas falhou porque o ambiente do cron não encontrava `python`. A configuração
  do `PATH` no arquivo de crontab foi corrigida no código; ainda é necessário
  publicar a imagem atualizada e confirmar uma execução bem-sucedida.

## Próximos passos

1. Preencher as variáveis AD/DNS no ambiente de produção e validar DNS,
   TCP/636 e TLS dentro do serviço `web`, conforme `DEPLOY_AD.md`.
2. Confirmar o IP/CIDR do HAProxy, restringir a porta 5009 no firewall e
   verificar que acesso direto é bloqueado antes de confiar no
   `X-Forwarded-Proto`.
3. Fazer login de teste com uma conta AD individual, confirmar GUID e grupos,
   e validar acesso de um superusuário LOCAL com o AD indisponível.
4. Migrar permissões diretas para grupos e só então fazer a transição e remoção
   manual das contas genéricas, conforme o plano de corte.
5. Após publicar a correção, confirmar uma execução bem-sucedida do cron
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
