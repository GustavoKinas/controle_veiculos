# Roteiro de estudo — backend

Guia para revisar e entender o backend desta aplicação. Complementa o
[DEVELOPMENT.md](DEVELOPMENT.md): lá está *o que* foi decidido, aqui está
*em que ordem estudar* e *o que exercitar*.

O material de exercício é o [viagens/tests.py](viagens/tests.py) — um
esqueleto com ~30 testes, dois já implementados como referência e o resto
marcado com `# TODO` e `self.skipTest(...)`.

**Ritmo sugerido:** Etapas 0–2 no primeiro dia, 3–4 no segundo, Etapa 5 no
terceiro (é a que mais rende), Etapa 6 e a caça aos bugs ao longo da semana.

---

## Etapa 0 · Preparar o terreno

Aprender a ler o próprio histórico é parte do ofício.

```bash
git diff viagens/services.py viagens/models.py viagens/forms.py
git diff --stat
git log --oneline
```

**Exercício:** divida o trabalho pendente em commits com propósito único —
higiene do repositório (`.gitignore` + remoção dos `.pyc`), feature (cadastro
de veículos) e correção (validação de quilometragem). Commit grande é commit
que ninguém revisa.

> Migrations **vão** para o repositório. Não são artefato de build como
> `.pyc` ou `staticfiles/`: são a descrição versionada da evolução do schema,
> e o [entrypoint.sh](entrypoint.sh) roda `migrate` a cada deploy.

---

## Etapa 1 · O caminho de uma requisição

Leia nesta ordem, que é a ordem em que o Django executa:

1. [controle_veiculos/urls.py](controle_veiculos/urls.py) → [viagens/urls.py](viagens/urls.py)
2. [viagens/views.py](viagens/views.py) — `LancarViagemView.post`
3. [viagens/forms.py](viagens/forms.py)
4. [viagens/models.py](viagens/models.py) — `Viagem.clean` e `Viagem.save`

**Pergunte-se:** onde o `request.POST` vira um objeto `Viagem`? Quem preenche
`centro_custo`, se ele nem aparece no formulário? O que muda com o
`form.save(commit=False)` da view?

**Exercício:** desenhe no papel a sequência
`URL → View.post → Form(request.POST) → is_valid() → save(commit=False) → save()`.

---

## Etapa 2 · O pipeline de validação — **a etapa mais importante**

Foi aqui que o bug do `validar_quilometragem` nasceu: a regra existia, mas era
chamada dentro de um `if` que só era verdadeiro quando a viagem já era
inválida por outro motivo. Resultado: nenhuma viagem real era validada.

Ordem de execução de `form.is_valid()`:

```
full_clean()
 ├─ _clean_fields()   → to_python / validate de cada campo + clean_<campo>()
 ├─ _clean_form()     → seu Form.clean()        ← só campos, sem instância
 └─ _post_clean()     → construct_instance() + instance.full_clean()
                                                ← aqui roda Model.clean()
```

Três lições que este projeto ilustra:

**1. `Model.save()` não valida.** `full_clean()` só é chamado por formulários
e pelo admin. `Viagem.objects.create(...)`, um `loaddata` ou um import CSV
passam direto por qualquer regra escrita em Python. Por isso as regras
críticas também deveriam existir como constraint no banco.

**2. Regra de negócio no formulário é regra que o admin não enxerga.** A
validação de quilometragem vive hoje em `Model.clean()`; o ModelForm continua
exibindo os erros nos campos certos de graça, via `_post_clean`.

**3. O formato do `ValidationError` importa:**

```python
raise ValidationError("mensagem")                  # erro não associado a campo
raise ValidationError({"km_inicial": "mensagem"})  # erro DO campo
```

**Exercício:** no `manage.py shell`, crie uma viagem inválida com
`Viagem.objects.create(...)` (grava!) e depois com `v = Viagem(...);
v.full_clean()` (levanta `ValidationError`). Sentir essa diferença na mão vale
mais que dez artigos.

---

## Etapa 3 · ORM: o que gera qual SQL

[viagens/services.py](viagens/services.py) é um catálogo pequeno e denso.
Estude função por função:

| Trecho | Conceito |
|---|---|
| `aggregate(km=Max("km_final"))` | agregação → devolve **dict**, não queryset |
| `.values(...).annotate(km=Sum(...))` | `GROUP BY` no ORM |
| `select_related` em `views.py` e `exports.py` | evitar N+1 (JOIN vs. 1 query por linha) |
| `prefetch_related("rateios__centro_custo")` | N+1 em relação reversa / many-to-many |
| `select_for_update()` + `@transaction.atomic` | `SELECT … FOR UPDATE`, corrida entre dois fechamentos |
| `.filter(...).update(...)` | UPDATE em massa que **não** chama `save()` nem dispara signals |

**Exercício:** rode com o SQL à vista (precisa de `DEBUG=True`):

```python
from django.db import connection, reset_queries
reset_queries()
list(Viagem.objects.all()[:15])
[q["sql"] for q in connection.queries]
```

Repita removendo o `select_related` da view e conte as queries. Ver o N+1
aparecer é o melhor professor.

---

## Etapa 4 · Onde cada regra mora

A pergunta que define a arquitetura: **por que existe `services.py`, se tudo
poderia estar na view?**

Leia a seção 3 do [DEVELOPMENT.md](DEVELOPMENT.md) e confirme no código:

- **congelamento do centro de custo** — histórico imune a mudança de lotação;
- **snapshot do rateio** (`FechamentoRateio`) — por que gravar o resultado em
  vez de recalcular sempre?
- **FK em vez de booleano** para o status de fechamento;
- **`Decimal` com `quantize(ROUND_HALF_UP)`** — por que `float` é proibido em
  cálculo de rateio e de dinheiro;
- **signal `post_delete`** para o hodômetro — e o preço disso: signal é "ação
  à distância", só se justifica quando a regra precisa valer para *qualquer*
  caminho de código.

---

## Etapa 5 · Testes — o maior buraco do projeto

```powershell
python manage.py test viagens              # usa o Postgres do .env (cria e destrói test_<banco>)
python manage.py test viagens --keepdb     # reaproveita o banco de teste (bem mais rápido)
python manage.py test viagens.ValidacaoQuilometragemTest.test_km_final_menor_ou_igual_ao_inicial_e_rejeitada
```

O usuário do banco precisa de permissão para criar bancos, senão o runner
para com *"permissão negada ao criar banco de dados"*:

```powershell
psql -U postgres -c "ALTER ROLE controle_veiculos CREATEDB;"
```

Último recurso, se o Postgres não estiver disponível — lembrando que o ideal é
testar no mesmo banco da produção (constraints e transações têm comportamento
específico por backend):

```powershell
$env:DATABASE_URL = "sqlite://:memory:"
python manage.py test viagens
Remove-Item Env:DATABASE_URL     # senão o runserver deste terminal vai para o SQLite
```

Estado inicial: **2 passando, 28 skipped, 3 expected failures**.

Trabalhe um `# TODO` por vez em [viagens/tests.py](viagens/tests.py). Para
cada um: implemente, veja passar, **depois quebre o código de propósito** e
confirme que o teste acusa. Teste que nunca falhou não é teste, é decoração.

Conceitos que o arquivo exercita: `setUpTestData` vs. `setUp`,
`assertRaises` + `message_dict`, `override_settings`, `self.client.force_login`,
`assertRedirects`, e `@expectedFailure` para documentar dívida técnica em
código executável.

---

## Etapa 6 · Configuração, segurança e deploy

[settings.py](controle_veiculos/settings.py), [Dockerfile](Dockerfile),
[entrypoint.sh](entrypoint.sh), [nginx/default.conf](nginx/default.conf).

Investigue: por que `SECRET_KEY` e `DATABASE_URL` vêm de variável de ambiente;
o que WhiteNoise + `CompressedManifestStaticFilesStorage` fazem no
`collectstatic` (e por que isso quebrou o teste de view antes do
`override_settings`); por que trocar `AUTH_USER_MODEL` depois do primeiro
`migrate` é praticamente inviável; e por que
[colaboradores/views.py](colaboradores/views.py) reimplementa o logout em vez
de usar o `LogoutView` nativo — qual o trade-off de aceitar logout por GET?

---

## Caça aos bugs — o exercício de graduação

Todos os itens abaixo são problemas **reais** que estão no código agora.
Encontre, explique o impacto e proponha a correção. Do mais grave ao mais
sutil:

1. **Viagem retroativa dentro de um período já fechado nunca entra em
   fechamento nenhum.** Releia `viagens_em_aberto` + `confirmar_fechamento`.
2. **Nada impede dois fechamentos com períodos sobrepostos.**
3. **Funcionário sem centro de custo:** o formulário protege; e o admin, o
   shell, um import CSV?
4. **Permissões:** qualquer usuário autenticado confirma fechamento e baixa
   qualquer Excel. Compare `LoginRequiredMixin` com `PermissionRequiredMixin`.
5. **Arredondamento:** a soma dos percentuais pode dar 99,99% ou 100,01%, mas
   `exports.py` escreve `100.0` fixo no total. Qual dos dois está errado?
6. **`km_atual` é `PositiveBigIntegerField` e `km_final` é
   `PositiveIntegerField`.** Incoerência inofensiva ou bomba-relógio?
7. **Custo do patch do hodômetro:** `Viagem.save()` faz um `aggregate` extra
   a cada gravação. Foi uma troca consciente (correção > 1 query). Você
   saberia defender — ou contestar?

O item 2 está escrito como `@expectedFailure` em `tests.py`.

**Resolvidos:** `km_final > km_inicial` como `CheckConstraint` (camada 3), o
clamp `max(..., 0)` que mascarava dado inconsistente, `veiculo` obrigatório no
schema, e o bloqueio de viagem com data futura em `Viagem.clean()`.

---

## Regra geral

**Reproduza no `manage.py shell` antes de mexer no código.** Um bug que você
viu acontecer é um bug que você entendeu; um bug que você só leu é opinião.
