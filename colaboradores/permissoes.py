"""
Perfis de acesso do sistema.

Este módulo é a **fonte única** de "quem pode o quê". Grupos e permissões do
Django já existiam; o que faltava era um lugar onde a política estivesse
escrita por extenso, em vez de espalhada por views e telas do admin.

Três camadas cuidam do acesso, na mesma lógica de validação já usada no
projeto (ver DEVELOPMENT.md §3.8):

1. **Menu** (`base.html`) — esconde o que o usuário não pode usar. É
   conveniência, não segurança: some da vista, mas a URL continua existindo.
2. **View** (`PerfilRequeridoMixin`) — recusa a requisição. É aqui que o
   controle de acesso acontece de verdade.
3. **Admin** (`ControleVeiculosAdminSite`) — nega a entrada no `/admin` a
   quem é operacional, mesmo que alguém marque `is_staff` por engano.

Nenhuma das três substitui as outras.
"""

# Este módulo **não importa nada do Django no topo**, de propósito.
#
# Ele é lido pelo AdminConfig durante a carga dos apps (ver
# controle_veiculos/admin.py), quando o registro de modelos ainda não existe.
# Qualquer import que chegue em `django.contrib.auth.models` — inclusive o
# aparentemente inocente `django.contrib.auth.mixins`, que puxa auth.views →
# auth.forms → auth.models — levanta AppRegistryNotReady na inicialização.
#
# Por isso a política mora aqui (só constantes e funções) e o mixin de view
# mora em `colaboradores/mixins.py`, que só é importado quando as views são.

# --------------------------------------------------------------------------
# Perfis
# --------------------------------------------------------------------------
GRUPO_PORTARIA = "Portaria"
GRUPO_FINANCEIRO = "Financeiro"

# Permissões de negócio, no formato "app_label.codename" que o
# `user.has_perm()` espera. Declaradas em Meta.permissions dos modelos
# (migration 0009) — não são as add/change/delete/view automáticas.
PERM_LANCAR_VIAGEM = "viagens.lancar_viagem"
PERM_GERENCIAR_RESERVAS = "viagens.gerenciar_reservas"
PERM_REALIZAR_FECHAMENTO = "viagens.realizar_fechamento"

# Cadastro de colaboradores usa as permissões automáticas do Django.
PERM_VER_COLABORADOR = "colaboradores.view_funcionario"
PERM_ADICIONAR_COLABORADOR = "colaboradores.add_funcionario"
PERM_ALTERAR_COLABORADOR = "colaboradores.change_funcionario"

PERMISSOES_POR_PERFIL: dict[str, list[str]] = {
    # A portaria mantém tudo o que já fazia — inclusive o fechamento. O pedido
    # foi criar o perfil financeiro e tirar o /admin da portaria, não reduzir
    # as atribuições dela. Para separar funções de verdade (financeiro fecha,
    # portaria não), basta remover PERM_REALIZAR_FECHAMENTO desta lista e
    # rodar `configurar_perfis` de novo.
    GRUPO_PORTARIA: [
        PERM_LANCAR_VIAGEM,
        PERM_GERENCIAR_RESERVAS,
        PERM_REALIZAR_FECHAMENTO,
        PERM_VER_COLABORADOR,
        PERM_ADICIONAR_COLABORADOR,
        PERM_ALTERAR_COLABORADOR,
    ],
    # Exclusivamente fechamento: sem lançamento, sem agenda, sem cadastro.
    GRUPO_FINANCEIRO: [
        PERM_REALIZAR_FECHAMENTO,
    ],
}

# Perfis operacionais nunca entram no /admin, mesmo com `is_staff` marcado.
# O /admin é do administrador do sistema, não de quem opera o dia a dia.
PERFIS_SEM_ADMIN = frozenset({GRUPO_PORTARIA, GRUPO_FINANCEIRO})


def _permissao(rotulo: str):
    """Resolve "app_label.codename" no objeto Permission correspondente."""
    from django.contrib.auth.models import Permission

    app_label, codename = rotulo.split(".", 1)
    return Permission.objects.get(
        content_type__app_label=app_label, codename=codename
    )


def sincronizar_perfis() -> dict[str, int]:
    """
    Cria os grupos e **reescreve** o conjunto de permissões de cada um.

    Reescreve em vez de acrescentar (`set()`, não `add()`): tirar uma
    permissão da lista acima tem que efetivamente tirá-la de quem já a tinha,
    senão a política aqui descrita e a do banco divergem em silêncio — e a do
    banco é a que vale.

    Idempotente: rodar duas vezes deixa o mesmo estado.
    """
    from django.contrib.auth.models import Group

    resumo: dict[str, int] = {}
    for nome_grupo, rotulos in PERMISSOES_POR_PERFIL.items():
        grupo, _ = Group.objects.get_or_create(name=nome_grupo)
        grupo.permissions.set([_permissao(rotulo) for rotulo in rotulos])
        resumo[nome_grupo] = len(rotulos)
    return resumo


def criar_usuario_de_perfil(*, username: str, senha: str, nome: str, grupo: str):
    """
    Cria (ou atualiza) um usuário operacional e o coloca no grupo do perfil.

    Sempre rebaixa: `is_staff` e `is_superuser` viram False a cada execução.
    Um usuário operacional que ganhou acesso ao /admin em algum momento perde
    aqui, sem depender de alguém lembrar de desmarcar na mão.

    Devolve `(funcionario, criado)`.
    """
    from django.contrib.auth.models import Group

    from .models import Funcionario

    funcionario, criado = Funcionario.objects.get_or_create(
        username=username, defaults={"nome": nome}
    )

    funcionario.set_password(senha)
    funcionario.is_active = True
    funcionario.is_staff = False
    funcionario.is_superuser = False
    if not funcionario.nome:
        funcionario.nome = nome
    funcionario.save()

    grupo_obj, _ = Group.objects.get_or_create(name=grupo)
    # `set` e não `add`: trocar o perfil de um usuário existente não pode
    # deixar o grupo antigo pendurado, acumulando permissões silenciosamente.
    funcionario.groups.set([grupo_obj])

    return funcionario, criado


def pagina_inicial_de(usuario) -> str:
    """
    Nome da rota para onde este usuário deve cair ao entrar.

    Sem isto, o financeiro faria login e bateria de cara num 403: a
    `LOGIN_REDIRECT_URL` é uma constante só, e a tela de lançamento — o
    destino natural da portaria — é justamente a que ele não pode ver.
    """
    if usuario.has_perm(PERM_LANCAR_VIAGEM):
        return "lancar_viagem"
    if usuario.has_perm(PERM_REALIZAR_FECHAMENTO):
        return "fechamento"
    # Sem nenhum dos dois: a agenda é somente leitura e serve de aterrissagem
    # neutra. Se nem ela puder, o próprio mixin devolve 403 — que é a resposta
    # honesta para um usuário sem perfil nenhum.
    return "agenda"
