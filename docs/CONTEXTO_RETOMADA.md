# Contexto para retomar o trabalho

> **Leia este arquivo primeiro.** Ele não descreve a arquitetura (isso está nos
> outros documentos) — ele diz **onde o trabalho parou**, o que já foi decidido
> e não deve ser rediscutido, e as armadilhas que já custaram tempo.

Atualizado em **13/08/2026**.

---

## 1. O que é o projeto

Aplicação Django para **controle de viagens de veículos** e **rateio do custo
de combustível por centro de custo**. O operador da portaria lança as viagens
de todos os colaboradores; periodicamente um **fechamento** soma a
quilometragem do período e distribui o custo proporcionalmente.

Em cima disso foi construído o **pré-cadastro de viagens**: as reservas de
veículo nascem no Outlook (cada veículo é uma caixa de recurso) e são
importadas pela Microsoft Graph, para que a portaria só precise preencher a
quilometragem.

Django 6.0.5 · PostgreSQL · templates server-side com Tailwind (CDN) + DaisyUI
+ htmx · sem build de JS · Docker Compose para deploy.

---

## 2. Ordem de leitura

| Documento | O que traz |
|---|---|
| **este arquivo** | estado atual, decisões fechadas, armadilhas, o que vem a seguir |
| [`../DEVELOPMENT.md`](../DEVELOPMENT.md) | arquitetura, modelos, URLs, decisões de projeto e o porquê de cada uma |
| [`PRE_CADASTRO_VIAGENS.md`](PRE_CADASTRO_VIAGENS.md) | desenho completo do pré-cadastro/agenda e da integração (5 fases) |
| [`../ESTUDO.md`](../ESTUDO.md) | roteiro de estudo do backend + caça aos bugs conhecidos |

---

## 3. Estado atual

**Todas as 5 fases do pré-cadastro estão implementadas.** 91 testes passando
(27 são esqueletos de estudo com `skipTest`, 1 é `@expectedFailure`
documentando dívida conhecida).

```
python manage.py test          →  OK (91 testes)
python manage.py check         →  sem problemas
makemigrations --check         →  No changes detected
```

Migrations aplicadas: `viagens` até `0008_reserva_solicitante_email`,
`colaboradores` até `0002_funcionario_uniq_funcionario_por_email`.

### Banco de desenvolvimento

O banco foi **zerado e repovoado em 13/08**. Estado:

| | |
|---|---|
| colaboradores | 188 (136 com e-mail, 159 podem viajar) |
| centros de custo | 54 |
| veículos | 3 — os carros reais, **todos com caixa de recurso** |
| viagens / reservas / fechamentos | 0 |
| superusuário | `administrador` |

**Os carros reais ganharam caixa de recurso no Outlook** e o `email_recurso`
já está preenchido no banco:

| Placa | Modelo | Caixa de recurso |
|---|---|---|
| `SXK9G85` | CRONOS | `cronossxk9g85@puflexivel.com.br` |
| `SXB9B09` | CRONOS | `cronossxb9b09@puflexivel.com.br` |
| `RLN1J19` | STRADA | `stradarln1j19@puflexivel.com.br` |

Note o domínio: `@puflexivel.com.br`, diferente do `@grupoflexivel.com.br` dos
colaboradores. **Ainda não houve um sync bem-sucedido contra essas caixas** —
se forem de outro tenant, o token atual pode não enxergá-las. É a primeira
coisa a verificar (ver Pendências).

O andaime que validou a integração (as 8 salas de reunião cadastradas como
veículos) **já foi removido**. O comando `cadastrar_veiculos_salas` continua
no repositório caso seja preciso reproduzir aquela validação.

⚠️ Os hodômetros (`Veiculo.km_atual`) carregam resíduo das viagens de teste
apagadas (ex.: `RLN1J19` com 110.588 km). É o comportamento projetado — o
recompute preserva o valor do cadastro quando não há viagens — mas hoje é
lixo, e vira o **piso** da primeira viagem real de cada veículo.

### Nada foi commitado ainda

O último commit é `6829cb8`. Tudo da fase 3 em diante está no diretório de
trabalho, incluindo os diretórios novos `docs/` e `viagens/integracoes/`.

---

## 4. Decisões fechadas — não rediscutir

Cada uma custou discussão e está justificada no documento indicado.

| Decisão | Onde está o porquê |
|---|---|
| `ReservaViagem` é entidade separada de `Viagem` (intenção × fato consumado) | `PRE_CADASTRO_VIAGENS.md` §3 |
| A alternativa (km inicial na reserva) foi avaliada e descartada | §11.1 — **leia antes de propor de novo** |
| Estado da viagem é **derivado** de `km_final IS NULL`, não um campo `status` | §11 |
| `ReservaViagem.status` é campo real (três estados, "cancelada" não é ausência) | §4 |
| Relação reserva × viagem é **1:1** | §10 |
| Dois fluxos de lançamento: saída/chegada em duas etapas, ou tudo de uma vez | §11 |
| Janela do sync: **hoje até +30 dias** | §10 |
| Chave de junção com o Outlook: campo **`email` nativo** do `AbstractUser` | §8 |
| Identidade da reserva importada: **`id_externo`**, nunca chave natural | §8.1 |
| Endpoint: **`calendarView`**, não `getSchedule` (só ele traz `id` e organizador) | §8 |
| Agendamento em produção: serviço `scheduler` no compose, laço com `sleep` | §8.2 |
| Validação em **três camadas** (formulário / `Model.clean()` / banco) | `DEVELOPMENT.md` §3.8 |
| Centro de custo e e-mail são **opcionais** no cadastro (produção não viaja) | docstring de `cadastro_funcionarios` |

---

## 5. Armadilhas já pagas

Coisas que quebraram de verdade neste projeto. Não repita.

**`Model.save()` não valida.** `full_clean()` só é chamado por formulários e
pelo admin. Todo código que monta uma `Viagem` fora de um ModelForm precisa
chamar `full_clean()` explicitamente — e chamar `congelar_centro_custo()`
antes, porque o `save()` é que preencheria o centro de custo e a validação de
campo roda primeiro.

**`date.today()` usa o relógio do sistema.** Em container UTC, das 21h de
Brasília em diante já é o dia seguinte. Use `timezone.localdate()` no Django e
`datetime.now(FUSO)` na integração. Isso já causou dois bugs.

**`clean()` recebe objeto pela metade.** Roda mesmo quando outro campo falhou
na validação de campo, então todo `clean()` precisa de `is not None` antes de
comparar. Um `None > date` derruba a tela com 500.

**FK obrigatória levanta em vez de devolver `None`.** Com `null=False`,
`self.veiculo` levanta `RelatedObjectDoesNotExist` quando o campo não foi
preenchido — não devolve `None`. Pergunte à coluna (`self.veiculo_id`) antes
de tocar no objeto.

**`add_error` recusa campo que não existe no formulário.** Os formulários de
reserva não têm `data`/`veiculo`/`funcionario` de propósito (vêm da reserva),
então erros do modelo endereçados a eles precisam virar erro geral. É o que
`_aplicar_erros_do_modelo()` em `views.py` faz.

**`select_for_update()` + `select_related()` em FK nulável = erro no Postgres.**
"FOR UPDATE não pode ser aplicado ao lado nulável de uma junção externa". Use
`select_for_update(of=("self",))`.

**Comentário `{# #}` é de uma linha só.** Quebrado em duas, vaza o texto para
o HTML. Para várias linhas, `{% comment %}`.

**Validadores de campo não rodam no `save()`.** O `^\d{10}$` de
`CentroCusto.codigo` nunca foi executado; quem barrou código inválido foi o
`varchar(10)` do Postgres. Normalize na entrada.

**Testes rodam com `DEBUG=False`**, e aí o storage do WhiteNoise exige o
`staticfiles.json` do `collectstatic`. Todo teste que renderiza template usa
`@override_settings(STORAGES=STORAGES_DE_TESTE)` (constante no topo de
`tests.py`).

---

## 6. Como rodar

```powershell
# Testes (o usuário do banco precisa de permissão para criar bancos)
python manage.py test viagens
psql -U postgres -c "ALTER ROLE controle_veiculos CREATEDB;"   # se der permissão negada

# Popular do zero
python manage.py criar_portaria --superuser
python manage.py cadastro_centro_custo colaboradores/management/commands/cc.csv
python manage.py cadastro_funcionarios colaboradores/management/commands/funcionarios_total_com_email.csv

# Integração com o Outlook
python manage.py cadastrar_veiculos_salas          # andaime — só se precisar revalidar com as salas
python manage.py sincronizar_reservas --dry-run
python manage.py sincronizar_reservas --dias 30
```

Credenciais do Graph vêm do `.env`: `CLIENT_ID`, `SECRETY_VALUE` (sic),
`URL_MICROSOFT`. O `poc_microsoft_graph.py` na raiz é o laboratório de
exploração da API — **não** é usado pela aplicação, que tem seu próprio
cliente em `viagens/integracoes/microsoft_graph.py`.

---

## 7. Pendências

Em ordem aproximada de valor.

1. **Rodar o primeiro sync contra as caixas dos carros reais** — nunca foi
   feito. Comece por `python manage.py sincronizar_reservas --dias 30 --dry-run`.
   Se as caixas `@puflexivel.com.br` estiverem em outro tenant, o comando
   reporta a falha por caixa em vez de quebrar, e aí o problema é de permissão
   da aplicação no Azure, não de código.
2. **Commitar.** Nada da fase 3 em diante está versionado. Vale separar em
   commits com propósito único (ver `ESTUDO.md` Etapa 0).
3. **Serviço `scheduler` no `docker-compose.yml`.** O comando está pronto e
   sai com código diferente de zero quando alguma caixa falha; falta o YAML
   descrito na §8.2.
4. **Zerar os hodômetros** dos veículos, se quiser começar limpo:
   `Veiculo.objects.update(km_atual=0)`.
5. **Aviso de viagens em andamento no fechamento** já existe; o caso "período
   só com viagens em andamento" ainda mostra "nenhuma viagem em aberto" sem o
   aviso (`_rateio.html`).
6. **Caça aos bugs do `ESTUDO.md`** — 7 itens abertos, sendo os dois primeiros
   os que mais importam: viagem retroativa lançada depois do fechamento fica
   órfã, e nada impede fechamentos com períodos sobrepostos.
7. **Colaboradores da EVO sem centro de custo** (ex.: ADONIRAM AMARAL ROCHA,
   e-mail `@evo.ind.br`). Se essas pessoas reservam carro, precisam de centro
   de custo para conseguir lançar viagem.
8. **Reservas de dia inteiro que cruzam vários dias** viram uma reserva só, na
   data de início. Se isso importar, o modelo precisa de data de fim.

---

## 8. Como o usuário trabalha

Gustavo é o desenvolvedor do projeto e está **usando este trabalho para
estudar Django** — o `ESTUDO.md` é o roteiro dele. Etapas 1 e 2 concluídas
(caminho da requisição e pipeline de validação).

O que funciona bem com ele:

- **Ele implementa, você revisa.** Ele pede a explicação, escreve o código e
  traz para revisão. Não escreva por ele o que ele pediu para entender.
- **Explique o porquê, não só o quê.** As melhores conversas desta sessão
  foram sobre *por que* uma decisão é assim, não sobre a sintaxe.
- **Corrija com precisão.** Ele recebe bem correção direta e já pegou erros
  meus mais de uma vez. Não amoleça o diagnóstico — mas corrija a afirmação
  errada, não o raciocínio quando ele está certo.
- **Meça antes de afirmar.** Várias vezes o palpite (meu e dele) estava errado
  e o `manage.py shell` resolveu em 30 segundos. Rode o código.
- **Cuidado com o ritmo.** Uma vez despejei três experimentos e conceitos de
  duas etapas à frente de uma vez, e o efeito foi desânimo, não aprendizado.
  Um conceito por vez, com um experimento curto.
- **Bug encontrado vira teste.** É prática estabelecida aqui e já pegou uma
  regressão real.
- **Documentação atualizada faz parte do "pronto"** — código + teste + doc.
