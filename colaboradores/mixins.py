"""
Mixin de controle de acesso das views.

Separado de `permissoes.py` porque importar `django.contrib.auth.mixins`
acaba importando `django.contrib.auth.models`, e a política precisa ser
legível durante a carga dos apps (ver o comentário no topo de permissoes.py).
"""

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect

from .permissoes import pagina_inicial_de


class PerfilRequeridoMixin(AccessMixin):
    """
    Exige autenticação e uma permissão.

    Por que não `PermissionRequiredMixin` puro: quando `raise_exception` é
    False ele manda para o login **um usuário já autenticado**, que volta para
    a mesma página e roda em círculo; quando é True, entrega um 403 seco. Aqui
    o usuário autenticado sem permissão vai para a página inicial *do perfil
    dele*, com uma mensagem explicando o que houve.

    Anônimo continua indo para o login, que é o comportamento correto — ele
    não tem perfil ainda.
    """

    permissao_requerida: str | None = None
    mensagem_sem_permissao = "Seu perfil não tem acesso a essa tela."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            # `handle_no_permission` do AccessMixin manda anônimo para o login
            # e levanta PermissionDenied para quem já está autenticado.
            return self.handle_no_permission()

        if self.permissao_requerida and not request.user.has_perm(
            self.permissao_requerida
        ):
            destino = pagina_inicial_de(request.user)
            if destino == request.resolver_match.url_name:
                # A página inicial do usuário é justamente a que ele não pode
                # ver: redirecionar criaria um laço, então 403 é a resposta.
                return self.handle_no_permission()

            messages.error(request, self.mensagem_sem_permissao)
            return redirect(destino)

        return super().dispatch(request, *args, **kwargs)
