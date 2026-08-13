# UTILIZAÇÕES DO SISTEMA

Manual de operação do Controle de Veículos: como criar usuários, mexer em
permissões, sincronizar agendas, lançar viagens e fechar períodos.

Escrito para quem vai **operar e administrar** o sistema. O desenho interno
está em [`../DEVELOPMENT.md`](../DEVELOPMENT.md) e
[`PRE_CADASTRO_VIAGENS.md`](PRE_CADASTRO_VIAGENS.md); os detalhes de
sincronização pelo shell estão em [`SINCRONIZACAO.md`](SINCRONIZACAO.md).

Todos os comandos rodam a partir da pasta `controle_veiculos/` (onde está o
`manage.py`), com o virtualenv ativo.

---

## Índice

1. [Perfis de acesso — o mapa](#1-perfis-de-acesso--o-mapa)
2. [Criar usuários](#2-criar-usuários)
3. [Mexer em permissões](#3-mexer-em-permissões)
4. [Sincronizar agendas do Outlook](#4-sincronizar-agendas-do-outlook)
5. [Reservas](#5-reservas)
6. [Lançar viagens](#6-lançar-viagens)
7. [Fechamento e rateio](#7-fechamento-e-rateio)
8. [Cadastros](#8-cadastros)
9. [Veículos e caixas de recurso](#9-veículos-e-caixas-de-recurso)
10. [Mapa de telas](#10-mapa-de-telas)
11. [Instalar do zero](#11-instalar-do-zero)
12. [Problemas comuns](#12-problemas-comuns)

---

## 1. Perfis de acesso — o mapa

Três perfis. A política inteira mora em `colaboradores/permissoes.py` — é o
**único** lugar onde "quem pode o quê" está escrito.

| Perfil | Para quem | Pode | Não pode |
|---|---|---|---|
| **Portaria** | operador que lança as viagens | agenda, lançar viagem, criar/sincronizar reservas, cadastrar colaboradores, fechar períodos | `/admin` |
| **Financeiro** | setor financeiro | fechamento e histórico de fechamentos | lançar viagem, agenda, reservas, colaboradores, `/admin` |
| **Administrador** | quem administra o sistema | tudo, inclusive `/admin` | — |

As permissões por trás disso:

| Permissão | O que libera |
|---|---|
| `viagens.lancar_viagem` | agenda, lançar viagem, lançar reserva, registrar chegada |
| `viagens.gerenciar_reservas` | criar reserva manual, botão Sincronizar |
| `viagens.realizar_fechamento` | fechamento, histórico, exportação em Excel |
| `colaboradores.view_funcionario` | lista de colaboradores |
| `colaboradores.add/change_funcionario` | cadastrar e inativar colaborador |

> **A portaria mantém o fechamento.** Se quiser segregação de funções
> (financeiro fecha, portaria não), veja a
> [§3.3](#33-tirar-uma-permissão-de-um-perfil).

### O acesso é verificado em três camadas

1. **Menu** — esconde o que o perfil não pode abrir. É conveniência: a URL
   continua existindo.
2. **View** — recusa a requisição. É **aqui** que o acesso é decidido.
3. **Admin** — o `/admin` recusa quem está em perfil operacional, mesmo com
   `is_staff` marcado.

Esconder o botão nunca é o controle. Quem digitar a URL na mão esbarra na
camada 2.

---

## 2. Criar usuários

### 2.1 Antes de tudo: criar os grupos

Os grupos precisam existir **antes** dos usuários. Rode uma vez por ambiente
(e de novo depois de qualquer migration que mexa em permissões):

```powershell
python manage.py configurar_perfis
```

Saída esperada:

```
Portaria: 6 permissão(ões) aplicada(s).
Financeiro: 1 permissão(ões) aplicada(s).
Perfis sincronizados. Use --listar para conferir o estado no banco.
```

### 2.2 Criar um usuário do Financeiro

```powershell
python manage.py criar_financeiro --senha "SenhaForte123"
```

Com nome e login próprios:

```powershell
python manage.py criar_financeiro --username maria.silva --nome "Maria Silva" --senha "SenhaForte123"
```

| Opção | Padrão | Para quê |
|---|---|---|
| `--username` | `financeiro` | login |
| `--nome` | `Financeiro` | nome de exibição |
| `--senha` | lê de `DJANGO_FINANCEIRO_PASSWORD` | senha |

A senha também pode vir do ambiente, o que evita deixá-la no histórico do
terminal:

```powershell
$env:DJANGO_FINANCEIRO_PASSWORD = "SenhaForte123"
python manage.py criar_financeiro
```

O usuário entra no grupo **Financeiro**, com `is_staff=False` e
`is_superuser=False`. Ao logar, cai direto em `/viagens/fechamento/`.

### 2.3 Criar um usuário da Portaria

```powershell
python manage.py criar_portaria --senha "SenhaForte123"
```

Vários operadores, um login cada:

```powershell
python manage.py criar_portaria --username portaria.noite --nome "Portaria - Noite" --senha "..."
```

| Opção | Padrão |
|---|---|
| `--username` | `portaria` |
| `--nome` | `Portaria` |
| `--senha` | lê de `DJANGO_PORTARIA_PASSWORD` |

> ⚠️ **Não existe mais `--superuser`.** A portaria nunca recebe acesso ao
> `/admin`. Ver [§3.5](#35-a-portaria-não-entra-no-admin).

### 2.4 Criar o administrador

Quem administra o sistema é um superusuário comum do Django, **fora** dos
grupos operacionais:

```powershell
python manage.py createsuperuser
```

Ele acessa o `/admin` e todas as telas.

### 2.5 Trocar a senha de alguém

Os dois comandos servem para criar **e** para redefinir senha — rodar de novo
sobre um usuário existente troca a senha e mantém o resto:

```powershell
python manage.py criar_portaria --username portaria --senha "NovaSenha456"
```

Pelo Django, para qualquer usuário:

```powershell
python manage.py changepassword nome.do.usuario
```

### 2.6 Bloquear o acesso de alguém

Inativar o login sem apagar o histórico de viagens da pessoa:

```powershell
python manage.py shell
```
```python
from colaboradores.models import Funcionario

u = Funcionario.objects.get(username="portaria.noite")
u.is_active = False      # bloqueia o LOGIN
u.save()
```

> `is_active` (login) e `ativo` (colaborador pode viajar) são campos
> **diferentes**, de propósito. Inativar para viagens não bloqueia o login, e
> vice-versa:
> ```python
> u.ativo = False   # some das listas de colaborador que pode viajar
> u.save()
> ```

### 2.7 Ver quem existe e com qual perfil

```powershell
python manage.py configurar_perfis --listar
```
```python
from colaboradores.models import Funcionario

for u in Funcionario.objects.all():
    if u.has_usable_password():
        print(u.username, u.is_staff, u.is_superuser, [g.name for g in u.groups.all()])
```

---

## 3. Mexer em permissões

### 3.1 Ver o que cada perfil tem hoje

```powershell
python manage.py configurar_perfis --listar
```

```
Portaria (1 usuário(s)):
  colaboradores.add_funcionario
  colaboradores.change_funcionario
  colaboradores.view_funcionario
  viagens.gerenciar_reservas
  viagens.lancar_viagem
  viagens.realizar_fechamento

Financeiro (1 usuário(s)):
  viagens.realizar_fechamento
```

### 3.2 Trocar o perfil de um usuário

```python
from colaboradores.permissoes import GRUPO_FINANCEIRO, criar_usuario_de_perfil

criar_usuario_de_perfil(
    username="joao.portaria",
    senha="NovaSenha123",
    nome="João",
    grupo=GRUPO_FINANCEIRO,
)
```

O grupo antigo é **substituído**, não acumulado — ninguém fica com permissão
sobrando do perfil anterior.

### 3.3 Tirar uma permissão de um perfil

**Este é o jeito certo.** Edite `colaboradores/permissoes.py` e rode o
comando; não mexa pelo `/admin`, senão o arquivo e o banco divergem e é o
banco que decide na hora de negar acesso.

Exemplo — tirar o fechamento da portaria (segregação de funções):

```python
# colaboradores/permissoes.py
PERMISSOES_POR_PERFIL = {
    GRUPO_PORTARIA: [
        PERM_LANCAR_VIAGEM,
        PERM_GERENCIAR_RESERVAS,
        # PERM_REALIZAR_FECHAMENTO,   <- removida
        PERM_VER_COLABORADOR,
        PERM_ADICIONAR_COLABORADOR,
        PERM_ALTERAR_COLABORADOR,
    ],
    ...
}
```

```powershell
python manage.py configurar_perfis
```

O comando **reescreve** o conjunto de permissões (`set`, não `add`), então
tirar da lista tira de verdade de quem já tinha. Confira com `--listar`.

### 3.4 Acrescentar uma permissão a um perfil

Mesmo caminho, ao contrário: acrescente o `PERM_...` na lista do grupo e rode
`configurar_perfis`. Para uma permissão que ainda não existe, declare-a em
`Meta.permissions` do modelo, gere a migration e só então referencie-a.

### 3.5 A portaria não entra no `/admin`

Duas travas independentes:

1. `criar_portaria` e `criar_financeiro` forçam `is_staff=False` e
   `is_superuser=False` **a cada execução** — rodar o comando sobre um
   usuário que ganhou acesso indevidamente também serve para rebaixá-lo;
2. o `/admin` recusa qualquer usuário que pertença a um perfil operacional,
   **mesmo com `is_staff` marcado na mão**.

Para dar `/admin` a alguém, tire a pessoa do grupo operacional — marcar
`is_staff` por cima não funciona, e é intencional.

Conferir quem tem acesso hoje:

```python
from colaboradores.models import Funcionario

Funcionario.objects.filter(is_superuser=True).values_list("username", flat=True)
```

---

## 4. Sincronizar agendas do Outlook

Cada veículo é uma caixa de recurso no Outlook; cada reserva, um evento na
agenda dela. O sync importa esses eventos como reservas.

### 4.1 Pela tela (portaria)

Em **`/viagens/agenda/`**, botão **🔄 Sincronizar reservas**. Importa a
janela de 30 dias a partir de hoje e volta para o mesmo dia que estava
aberto.

Leva alguns segundos (uma requisição por caixa). O botão se desabilita
sozinho durante a espera.

Resultado possível:

- **verde** — "Agenda sincronizada: 2 criada(s), 1 atualizada(s)…";
- **amarelo** — "Sincronização parcial… Não foi possível ler: `<caixa>`".
  Alguma caixa não respondeu, então a agenda pode estar **incompleta**. As
  reservas dessa caixa não foram atualizadas nem canceladas;
- **vermelho** — problema de credencial ou nenhum veículo com caixa
  cadastrada. É configuração, não erro do operador.

### 4.2 Pela linha de comando

```powershell
# Ver o que aconteceria, sem gravar nada
python manage.py sincronizar_reservas --dry-run

# Importar de verdade (janela padrão: hoje até +30 dias)
python manage.py sincronizar_reservas

# Janela menor
python manage.py sincronizar_reservas --dias 7
```

O `--dry-run` **não simula**: roda o serviço de verdade numa transação e
desfaz ao final, então os números são exatos.

O comando sai com código diferente de zero quando alguma caixa falha — é o
que o agendador usa para perceber falha parcial.

Guia completo, incluindo inspeção peça por peça pelo shell:
[`SINCRONIZACAO.md`](SINCRONIZACAO.md).

### 4.3 O que o sync faz com cada reserva

| Situação | Resultado |
|---|---|
| evento novo | cria reserva pendente |
| evento remarcado | atualiza a existente (não duplica) |
| evento cancelado ou apagado | cancela a reserva |
| evento que reaparece | volta para pendente |
| reserva **já lançada** | intocável — o fato consumado não volta atrás |
| reserva **criada à mão** | intocável — não veio do Outlook |
| caixa que falhou na consulta | nada é cancelado ali |

Rodar duas vezes seguidas não duplica nada: a identidade da reserva é o id do
evento no Outlook.

### 4.4 Automatizar

Em produção o comando roda em laço no serviço `scheduler` do
`docker-compose.yml` (ver `PRE_CADASTRO_VIAGENS.md` §8.2).

---

## 5. Reservas

### 5.1 Ver a agenda

**`/viagens/agenda/`** — o dia selecionado com a fila de trabalho à esquerda e
o panorama do mês à direita. Clique num dia da grade para trocar a fila.

Estados dos cartões:

| Selo | Significado |
|---|---|
| **Pendente** | esperando o lançamento da quilometragem |
| **Atrasada** | pendente com a data já passada — precisa de atenção |
| **Na rua** | saída lançada, veículo ainda não voltou |
| **Lançada** | virou viagem, entra no rateio |

### 5.2 Criar uma reserva manualmente

**`/viagens/reservas/nova/`**, ou o botão **➕ Nova reserva** na agenda.

Para o que não nasceu no Outlook: pedido por telefone, carro solicitado na
hora, caixa de recurso fora do ar.

| Campo | Obrigatório |
|---|---|
| Colaborador | sim — só aparecem ativos e com centro de custo |
| Veículo | sim — só veículos ativos |
| Data | sim |
| Horários | os dois, ou nenhum (reserva de dia inteiro) |
| Destino | não |

Reserva criada assim **nunca é cancelada pelo sync**, porque não veio do
Outlook.

### 5.3 Cancelar uma reserva

Pelo `/admin` (perfil administrador), mudando o status para "Cancelada".
Cancelar não apaga: reserva cancelada continua no histórico.

---

## 6. Lançar viagens

Duas portas para o mesmo resultado.

### 6.1 A partir de uma reserva (caminho normal)

Na agenda, botão **Lançar KM** do cartão. Colaborador, veículo e data vêm da
reserva e não são editáveis — só a quilometragem é digitada.

Dois fluxos, um formulário:

- **Fluxo A — saída e chegada em duas etapas:** preencha só o KM inicial. A
  viagem fica *em andamento* e o cartão passa a oferecer **Registrar
  chegada**;
- **Fluxo B — tudo de uma vez:** preencha KM inicial e final. A viagem já
  nasce concluída.

Se a reserva veio do Outlook sem colaborador identificado, o formulário pede
que o operador escolha quem foi.

> O botão fica **bloqueado** em reserva de data futura: a viagem é lançada
> depois de acontecer, nunca antes.

### 6.2 Sem reserva

**`/viagens/lancar/`** — o formulário completo, com colaborador, veículo,
data e quilometragem. É o caminho para a viagem que ninguém reservou.

### 6.3 Regras que o sistema aplica

| Regra | Motivo |
|---|---|
| KM final > KM inicial | viagem não anda para trás |
| KM inicial ≥ maior KM já registrado do veículo | o hodômetro não retrocede |
| KM final não invade o lançamento posterior | viagem retroativa não pode atropelar o que já existe |
| data não pode ser futura | a viagem é registrada depois de acontecer |
| colaborador precisa de centro de custo | é ele que recebe o rateio |

Viagem *em andamento* (sem KM final) **não entra no rateio** — só entra
quando a chegada é registrada.

---

## 7. Fechamento e rateio

Perfis: **Financeiro** e **Portaria**.

### 7.1 Fechar um período

**`/viagens/fechamento/`**

1. Informe data de início e fim → o sistema mostra a **prévia** do rateio,
   somente leitura;
2. confira o total de quilômetros e a distribuição por centro de custo;
3. confirme. O fechamento é gravado de forma atômica e as viagens do período
   passam a pertencer a ele.

Só entram viagens **concluídas e ainda não fechadas**. Se houver viagem em
andamento no período, a tela avisa.

### 7.2 Consultar e exportar

**`/viagens/fechamentos/`** — histórico paginado, com o rateio por centro de
custo de cada fechamento e o link de **exportação em Excel** (resumo +
detalhamento das viagens).

### 7.3 O que o fechamento congela

O centro de custo é gravado na viagem no momento do lançamento, não lido na
hora do fechamento. Colaborador que mudar de setor depois **não** altera
rateios já feitos — o histórico permanece como era.

---

## 8. Cadastros

### 8.1 Colaboradores pela tela

- **`/colaboradores/`** — cadastrar e inativar;
- **`/colaboradores/cadastrados/`** — lista com busca e ordenação.

| Campo | Obrigatório | Observação |
|---|---|---|
| Nome | sim | |
| E-mail corporativo | não | **é a chave** que liga a pessoa às reservas do Outlook |
| Unidade fabril | não | |
| Centro de custo | não | mas **obrigatório para viajar** |

E-mail e centro de custo são opcionais porque quem trabalha na produção não
viaja e não precisa de nenhum dos dois.

> Colaborador **sem e-mail** não é reconhecido nas reservas importadas: a
> reserva chega "não identificada" e o operador escolhe a pessoa na hora de
> lançar.

### 8.2 Carga em massa por CSV

```powershell
python manage.py cadastro_centro_custo colaboradores/management/commands/cc.csv
python manage.py cadastro_funcionarios colaboradores/management/commands/funcionarios_total_com_email.csv
```

Ambos aceitam `--encoding` (o padrão do `cadastro_funcionarios` é `cp1252`,
que é o do Excel em português). Linhas inválidas são reportadas e puladas, em
vez de derrubar a importação no meio.

---

## 9. Veículos e caixas de recurso

Veículos são cadastrados pelo `/admin` (perfil administrador).

| Campo | Para quê |
|---|---|
| Placa | identificação, única |
| Modelo / marca | exibição |
| `km_atual` | hodômetro — vira o **piso** da primeira viagem |
| `email_recurso` | a caixa de recurso no Outlook |
| `ativo` | veículo inativo não aceita reserva nem lançamento |

**Sem `email_recurso` preenchido, o veículo não é sincronizado** — o sync só
consulta caixas de veículo ativo cadastrado, porque cada caixa custa uma
requisição.

Corrigir um hodômetro errado:

```python
from viagens.models import Veiculo

v = Veiculo.objects.get(placa="RLN1J19")
v.km_atual = 110588
v.save()
```

---

## 10. Mapa de telas

| URL | Tela | Quem acessa |
|---|---|---|
| `/` | redireciona para a inicial do perfil | qualquer um logado |
| `/login/` · `/logout/` | entrar e sair | todos |
| `/viagens/agenda/` | agenda de reservas | Portaria |
| `/viagens/reservas/nova/` | criar reserva manual | Portaria |
| `/viagens/reservas/sincronizar/` | botão Sincronizar (só POST) | Portaria |
| `/viagens/reservas/<id>/lancar/` | lançar KM de uma reserva | Portaria |
| `/viagens/chegada/<id>/` | registrar chegada | Portaria |
| `/viagens/lancar/` | lançar viagem sem reserva | Portaria |
| `/viagens/fechamento/` | fechamento e rateio | Financeiro, Portaria |
| `/viagens/fechamentos/` | histórico | Financeiro, Portaria |
| `/viagens/fechamentos/<id>/exportar/` | Excel do fechamento | Financeiro, Portaria |
| `/colaboradores/` | cadastrar / inativar | Portaria |
| `/colaboradores/cadastrados/` | lista | Portaria |
| `/admin/` | administração | **só administrador** |

Cada perfil cai numa página inicial diferente ao entrar: Portaria em
`/viagens/lancar/`, Financeiro em `/viagens/fechamento/`.

---

## 11. Instalar do zero

```powershell
# 1. Banco e estrutura
python manage.py migrate

# 2. Perfis de acesso (ANTES dos usuários)
python manage.py configurar_perfis

# 3. Usuários
python manage.py createsuperuser                  # administrador
python manage.py criar_portaria --senha "..."
python manage.py criar_financeiro --senha "..."

# 4. Cadastros base
python manage.py cadastro_centro_custo colaboradores/management/commands/cc.csv
python manage.py cadastro_funcionarios colaboradores/management/commands/funcionarios_total_com_email.csv

# 5. Veículos com email_recurso, pelo /admin

# 6. Primeira sincronização
python manage.py sincronizar_reservas --dry-run
python manage.py sincronizar_reservas
```

O `.env` precisa de `CLIENT_ID`, `SECRETY_VALUE` (sic) e `URL_MICROSOFT` para
a integração com o Outlook.

Conferência da instalação:

```powershell
python manage.py check
python manage.py test
python manage.py configurar_perfis --listar
```

---

## 12. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "Seu perfil não tem acesso a essa tela" | perfil errado para aquela URL | confira com `configurar_perfis --listar` |
| Usuário loga e não vê menu nenhum | não está em grupo nenhum | rode `criar_portaria`/`criar_financeiro`, ou veja [§3.2](#32-trocar-o-perfil-de-um-usuário) |
| Portaria não acessa o `/admin` | é o comportamento projetado | use o administrador |
| `Nenhum veículo ativo com caixa de recurso cadastrada` | `email_recurso` vazio | preencha no `/admin` |
| Sincronização com aviso amarelo | uma caixa não respondeu | permissão da aplicação no Azure; a agenda está incompleta |
| Reserva importada sem colaborador | e-mail ausente ou diferente no cadastro | preencha o e-mail corporativo do colaborador |
| Colaborador não aparece no formulário | inativo ou sem centro de custo | corrija em `/colaboradores/` |
| "A quilometragem inicial não pode ser menor que…" | hodômetro do veículo já passou disso | confira o `km_atual` e as viagens anteriores |
| Fechamento vazio | não há viagem concluída e aberta no período | viagem em andamento não entra |
| `permission denied to create database` ao rodar testes | usuário do banco sem `CREATEDB` | `psql -U postgres -c "ALTER ROLE controle_veiculos CREATEDB;"` |

---

## Onde a política está escrita

| Arquivo | O que define |
|---|---|
| `colaboradores/permissoes.py` | perfis, permissões de cada um, página inicial |
| `colaboradores/mixins.py` | recusa de acesso nas views |
| `controle_veiculos/admin.py` | trava do `/admin` |
| `viagens/sincronizacao.py` | orquestração do sync (comando **e** botão) |

Mudou a política? Edite `permissoes.py` e rode `configurar_perfis`.
