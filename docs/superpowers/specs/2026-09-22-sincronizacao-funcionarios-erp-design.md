# Desenho: sincronização de funcionários com o ERP

**Data:** 2026-09-22  
**Status:** aprovado em conversa; aguardando revisão do documento antes do plano de implementação

## Objetivo

Integrar o projeto `controle_veiculos` ao endpoint de funcionários do ERP para
sincronizar admissões e desligamentos por empresa e pelo mês corrente. A mesma
regra de negócio será reutilizada pelo command manual, pelo botão protegido do
Admin e pelo scheduler Docker.

O ERP será a fonte dos dados sincronizados. A sincronização não fará reconciliação
por ausência: um funcionário local que não apareça nas respostas do mês não será
alterado.

## Decisões confirmadas

### Contrato do ERP

- Endpoint: `https://10.1.1.220/api/funcionarios/v10/informacoes`.
- Admissões: `GET ?dataAdmissao=AAAAMM`.
- Demissões: `GET ?dataDemissao=AAAAMM`.
- O header `empresa` recebe o código da empresa.
- O header `Authorization` recebe o token sem prefixo automático.
- O header `accept` será `application/json`.
- A resposta contém todos os registros em `data`; não há paginação.
- Datas chegam sempre no formato `AAAA-MM-DD`.
- O token ficará no `.env` e não poderá aparecer em logs, telas ou resultados.
- A validação SSL será desabilitada explicitamente.
- Timeout por chamada: 300 segundos.
- Não haverá retry automático.

### Empresas

| Código ERP | Unidade local |
|---:|---|
| 1 | Matriz |
| 2 | Filial MG |
| 20 | EVO |

Códigos de empresa diferentes desses serão ignorados, sem interromper as outras
empresas.

### Identidade e cadastros

- A identidade permanente é `unidade_fabril + codigo_funcionario_erp`.
- Não haverá vínculo automático por nome.
- Funcionários antigos receberão o código ERP manualmente.
- Funcionários PJ permanecerão sem código ERP e terão manutenção manual.
- Novos funcionários usarão a função atual `gerar_username(nome)`.
- O username de um funcionário existente nunca será alterado pela API.
- A senha de novos registros será inutilizável, como no cadastro atual.

### Campos sincronizados

Serão adicionados ao model `Funcionario`:

- `data_admissao`: `DateField(null=True, blank=True)`;
- `data_demissao`: `DateField(null=True, blank=True)`.

A API não sincronizará `email`, `cargo`, `carteiraSaude` nem `dependentes`.
E-mails já cadastrados serão preservados.

O nome será atualizado quando diferir do ERP. O código ERP, a unidade, os
catálogos, o centro de custo, as datas e os indicadores de atividade seguirão
as regras abaixo.

### Situação e datas

- Na operação de admissão, `situacao == "Ativo"` define `ativo=True` e
  `is_active=True`.
- Na operação de admissão, qualquer situação não vazia diferente de `Ativo`
  define `ativo=False` e `is_active=False`.
- Situação ausente ou vazia torna o registro inválido; o registro é ignorado
  com erro.
- Qualquer funcionário retornado pela operação de demissão será inativado,
  independentemente de `situacao`.
- A operação de admissão atualiza somente `data_admissao`.
- A operação de demissão atualiza somente `data_demissao`.
- Data vazia limpa a data correspondente (`NULL`).
- Campos obrigatórios ausentes ou inválidos fazem o registro ser ignorado com
  erro, sem interromper o lote.
- Admissões são processadas antes de demissões.

### Centro de custo, departamento e seção

- `codCentroCusto` é o valor de `CentroCusto.codigo`.
- `centroCusto` é o valor de `CentroCusto.descricao`.
- Centros de custo inexistentes serão criados.
- Descrição divergente de um centro existente será atualizada pelo ERP.
- O centro de custo local será preservado quando o ERP retornar código vazio.
- O código de centro de custo é considerado válido quando possui 10 dígitos.
- Departamentos e seções inexistentes serão criados.
- Descrições de departamentos e seções serão atualizadas quando diferirem.
- Departamento ou seção vazio preservará o vínculo local.

## Arquitetura proposta

```text
ERPClient
    ↓ HTTP e validação da resposta
FuncionarioSyncService
    ↓ identidade, normalização, transações e resultado
Management command ─── Admin superusuário
    ↓                         ↓
Scheduler Docker         execução manual
```

O cliente HTTP não conhecerá os models. O serviço concentrará as regras de
negócio e será chamado pelos três pontos de entrada. O scheduler apenas chamará
o command e não conterá lógica de sincronização.

### Cliente HTTP

O cliente receberá a URL, token, timeout e política SSL por configuração. Para
cada empresa e operação, enviará o parâmetro mensal e os headers definidos.

Deverá validar status HTTP, JSON, objeto raiz, existência de `data`, tipo lista,
campos obrigatórios e formato das datas. Erros de uma chamada serão associados
à empresa/operação e não impedirão o processamento das demais.

### Serviço de sincronização

O serviço deverá:

1. obter o mês corrente no timezone `America/Sao_Paulo`;
2. processar admissões para as empresas 1, 2 e 20;
3. processar demissões para as mesmas empresas;
4. ignorar códigos de empresa não configurados;
5. localizar funcionários por unidade e código ERP;
6. criar registros novos sem e-mail e com username gerado pela regra existente;
7. atualizar somente os campos autorizados;
8. criar ou atualizar centros, departamentos e seções conforme as regras;
9. executar cada registro em transação independente;
10. continuar após falha de uma linha, empresa ou operação;
11. produzir resultado estruturado sem segredos.

Se houver funcionário nas duas respostas do mês, o processamento de demissão
posterior prevalecerá sobre a admissão.

### Resultado da execução

O resultado deverá informar, no mínimo:

- período e operações executadas;
- empresas processadas e empresas ignoradas;
- registros recebidos por empresa/operação;
- funcionários criados, atualizados e inativados;
- centros, departamentos e seções criados/atualizados;
- registros ignorados;
- erros por empresa, operação e registro.

## Pontos de entrada

### Command

O command será a entrada comum do scheduler e da execução manual técnica. A
execução automática usará o mês corrente e as duas operações na ordem admissão
→ demissão. O command retornará erro operacional quando houver falhas, mas o
serviço continuará o processamento possível dentro do lote.

### Admin

Será criado um botão protegido, visível somente para superusuários. Ele sempre
executará as duas operações para o mês corrente, exibindo o resumo e os erros
da execução após o processamento.

### Scheduler

O cron usará o timezone `America/Sao_Paulo` e quatro entradas:

- segunda a sexta às 07:15: admissões;
- segunda a sexta às 18:15: admissões;
- segunda a sexta às 07:20: demissões;
- segunda a sexta às 18:20: demissões.

Como o serviço exige admissão antes de demissão para uma execução conjunta, a
ordem também deverá ser respeitada quando as entradas forem independentes. O
lock global existente ou equivalente deverá impedir execuções concorrentes.

## Migrations e carga inicial

A migration dos novos campos será compatível com os cadastros legados, usando
`null=True` e `blank=True`. Não haverá consulta retroativa ao ERP apenas para
preencher datas antigas.

Antes da primeira sincronização, os funcionários CLT legados que devem ser
geridos pelo ERP terão seu código e unidade preenchidos manualmente. PJs não
serão incluídos nessa preparação e continuarão fora do fluxo automático.

## Testes necessários

### Cliente

- URL, parâmetros e headers de admissão;
- URL, parâmetros e headers de demissão;
- timeout de 300 segundos;
- SSL desabilitado conforme configuração;
- resposta válida, vazia, JSON inválido e `data` ausente/não lista;
- datas em formato inválido;
- token ausente sem expor o valor em mensagens.

### Serviço e banco

- identidade por unidade + código;
- código repetido em empresas diferentes;
- username novo e username existente preservado;
- PJs sem código não alterados;
- criação e atualização por admissão;
- inativação por demissão;
- ordem admissão → demissão;
- ausência na resposta sem alteração;
- limpeza e preservação das datas conforme operação;
- criação e atualização de centro de custo;
- preservação de centro/departamento/seção quando o ERP retornar vazio;
- atualização de nome, departamento e seção;
- registro inválido isolado sem abortar o lote;
- falha de empresa/operação sem abortar as demais;
- ausência de retry automático.

### Admin e scheduler

- botão visível somente para superusuários;
- mês corrente e duas operações obrigatórias;
- resumo com contadores e erros;
- horários e timezone do cron;
- token ausente de logs, saída JSON e mensagens do Admin.

## Alternativas descartadas

- **Lógica diretamente no command:** descartada porque duplicaria ou acoplaria
  o comportamento do Admin e do scheduler.
- **Fila assíncrona ou Celery:** descartada por adicionar infraestrutura sem
  necessidade para o volume e o agendamento definidos.
- **Reconciliação por nome:** descartada para proteger PJs e evitar associação
  ambígua; a identidade será exclusivamente ERP + unidade.

## Próximo passo

Após a revisão deste documento, o próximo artefato será o plano detalhado de
implementação, com ordem de arquivos, migrations, testes e verificação Docker.
