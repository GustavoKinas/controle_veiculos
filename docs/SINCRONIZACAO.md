# Sincronizar reservas pelo shell — guia rápido

Como disparar e inspecionar a importação das reservas do Outlook pela linha
de comando, para validar e testar na mão. O equivalente do `tinker` do Laravel
aqui é o `python manage.py shell`.

Todos os comandos rodam a partir de `controle_veiculos/` (onde está o
`manage.py`), com o virtualenv ativo.

---

## 1. O caminho curto

```powershell
# Ver o que aconteceria, sem gravar nada. Comece sempre por aqui.
python manage.py sincronizar_reservas --dry-run

# Importar de verdade (janela padrão: hoje até +30 dias)
python manage.py sincronizar_reservas

# Janela menor, para um teste rápido
python manage.py sincronizar_reservas --dias 7
```

Saída típica:

```
Janela: 2026-08-13T00:00:00-03:00 a 2026-09-12T00:00:00-03:00
Caixas de recurso: 3
3 evento(s) em 3 caixa(s) consultada(s) com sucesso.
  criadas                        0
  atualizadas                    3
  canceladas                     0
  reabertas                      0
  ignoradas sem veiculo          0
  intocadas lancadas             0
```

**`--dry-run` não simula.** Ele roda o serviço de verdade dentro de uma
transação e faz rollback ao final. Por isso o resumo é exato, inclusive o
número de cancelamentos — um cálculo "a seco" só chegaria lá reimplementando
as regras, e aí estaria conferindo a cópia, não o original.

### Código de saída

O comando sai com código diferente de zero quando **alguma caixa falha**,
mesmo que as outras tenham sido importadas. É o que o serviço `scheduler` usa
para perceber a falha parcial. Para conferir no PowerShell:

```powershell
python manage.py sincronizar_reservas; $LASTEXITCODE
```

---

## 2. Pela tela

A portaria tem o botão **🔄 Sincronizar reservas** em `/viagens/agenda/`, que
faz exatamente o mesmo trabalho (mesma função, `executar_sincronizacao`).

Diferenças que importam:

| | comando | botão |
|---|---|---|
| janela | `--dias`, padrão 30 | sempre 30 dias |
| dry-run | sim | não |
| falha parcial | código de saída ≠ 0 | aviso amarelo na tela |
| permissão | quem tem shell no servidor | `viagens.gerenciar_reservas` |

---

## 3. Pelo shell, peça por peça

Útil quando o comando falha e você quer saber **qual** das duas metades
quebrou: a que fala com a Microsoft ou a que grava no banco.

```powershell
python manage.py shell
```

### 3.1 Quais caixas seriam consultadas

```python
from viagens.sincronizacao import caixas_de_recurso

caixas_de_recurso()
# ['cronossxk9g85@puflexivel.com.br', 'cronossxb9b09@puflexivel.com.br', ...]
```

Lista vazia significa que nenhum veículo ativo tem `email_recurso`
preenchido — e é por isso que o comando aborta com `SemCaixasCadastradas`.

### 3.2 Só a borda: falar com o Graph sem tocar no banco

```python
from viagens.integracoes.microsoft_graph import MicrosoftGraphClient
from viagens.sincronizacao import caixas_de_recurso

coleta = MicrosoftGraphClient().coletar(caixas_de_recurso(), dias=30)

len(coleta.eventos)          # quantos eventos vieram
coleta.caixas_consultadas    # as que responderam
coleta.erros                 # {caixa: motivo} das que falharam
coleta.eventos[0]            # o dicionário já normalizado
```

Se `coleta.erros` estiver cheio e `caixas_consultadas` vazio, o problema é de
credencial ou permissão da aplicação no Azure — **não** é código.

### 3.3 Uma caixa só

```python
from viagens.integracoes.microsoft_graph import MicrosoftGraphClient

cliente = MicrosoftGraphClient()
coleta = cliente.coletar(["stradarln1j19@puflexivel.com.br"], dias=7)
coleta.erros
```

### 3.4 Só o gravador: aplicar eventos falsos, sem rede

É assim que a suíte testa as regras de sincronização sem mock de HTTP.

```python
from datetime import date
from viagens.services import sincronizar_reservas

# As oito chaves são obrigatórias: o serviço lê por acesso direto
# (evento["data"]), não com .get() — faltar uma levanta KeyError.
# Não existe "destino" aqui: o Graph não devolve destino, e o campo só é
# preenchido nas reservas criadas à mão pelo painel.
evento = {
    "id_externo": "teste-1",
    "email_recurso": "stradarln1j19@puflexivel.com.br",
    "solicitante_nome": "Fulano de Tal",
    "solicitante_email": "fulano@grupoflexivel.com.br",
    "data": date(2026, 8, 20),
    "hora_inicio": None,   # None nos dois = evento de dia inteiro
    "hora_fim": None,
    "cancelado": False,
}

sincronizar_reservas(
    eventos=[evento],
    caixas_consultadas={"stradarln1j19@puflexivel.com.br"},
    data_inicio=date(2026, 8, 1),
    data_fim=date(2026, 8, 31),
)
# {'criadas': 1, 'atualizadas': 0, 'canceladas': 0, ...}
```

⚠️ **`caixas_consultadas` é o freio do cancelamento.** Só as reservas de
caixas que estão nesse conjunto podem ser canceladas por ausência. Passar um
conjunto errado aqui cancela reservas boas.

### 3.5 A rodada inteira, com rollback

```python
from viagens.sincronizacao import executar_sincronizacao

resultado = executar_sincronizacao(dias=7, dry_run=True)

resultado.resumo               # {'criadas': 0, 'atualizadas': 3, ...}
resultado.erros                # caixas que falharam
resultado.houve_falha_parcial  # True se alguma falhou
resultado.descrever()          # linha pronta para mensagem de tela
```

---

## 4. Conferir o resultado no banco

```python
from viagens.models import ReservaViagem

ReservaViagem.objects.count()

# As pendentes, com o que interessa
for r in ReservaViagem.objects.filter(status="pendente").select_related("veiculo", "funcionario"):
    print(r.data, r.hora_inicio, r.veiculo.placa, r.descricao_solicitante, r.solicitante_email)

# Quantas ficaram sem colaborador identificado (o e-mail não casou com o cadastro)
ReservaViagem.objects.filter(funcionario__isnull=True).count()

# Só as criadas na mão pelo painel (não vieram do Outlook)
ReservaViagem.objects.filter(origem="manual")
```

Reserva importada com `funcionario` nulo quase sempre significa colaborador
sem `email` preenchido no cadastro, ou com e-mail diferente do que o Outlook
devolveu. A junção é por e-mail, normalizado em minúsculo no
`Funcionario.save()`.

---

## 5. Limpar para repetir um teste

```python
# Apaga só o que veio do Outlook e ainda está pendente. Reserva já lançada
# tem viagem vinculada e NÃO deve ser apagada — o rateio depende dela.
from viagens.models import ReservaViagem

ReservaViagem.objects.filter(origem="outlook", status="pendente").delete()
```

Depois é só rodar `python manage.py sincronizar_reservas` de novo: a
importação é idempotente pelo `id_externo`, então o mesmo evento volta com o
mesmo identificador.

---

## 6. Quando dá errado

| Sintoma | Provável causa |
|---|---|
| `Nenhum veículo ativo com caixa de recurso cadastrada` | `Veiculo.email_recurso` vazio — preencha no /admin |
| `GraphIndisponivel` já na primeira linha | falta `CLIENT_ID`/`SECRETY_VALUE`/`URL_MICROSOFT` no `.env`, ou o segredo expirou |
| `falhou: <caixa> — 403` | a aplicação no Azure não tem permissão de ler aquela caixa |
| Importa, mas `funcionario` fica nulo | colaborador sem `email` no cadastro, ou e-mail diferente |
| Reservas somem depois de sincronizar | a caixa respondeu e o evento não estava mais lá — confira a janela (`--dias`) |

As credenciais vêm do `.env`: `CLIENT_ID`, `SECRETY_VALUE` (sic) e
`URL_MICROSOFT`.

---

## 7. Onde cada peça mora

```
viagens/integracoes/microsoft_graph.py   fala HTTP, traduz o evento    (não conhece o banco)
viagens/services.py::sincronizar_reservas grava e aplica as regras     (não conhece a Microsoft)
viagens/sincronizacao.py                  junta as duas               (o orquestrador)
viagens/management/commands/…             casca de linha de comando
viagens/views.py::SincronizarReservasView casca de tela
```

O comando e o botão chamam **a mesma** `executar_sincronizacao`. Corrigir uma
regra num lugar corrige nos dois.

Desenho completo da integração: [`PRE_CADASTRO_VIAGENS.md`](PRE_CADASTRO_VIAGENS.md) §8.
