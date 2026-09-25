"""Apresentação do login híbrido sem revelar existência ou estado da conta."""

from django.contrib.auth.views import LoginView

from .authentication import AuthenticationStatus


_MESSAGES = {
    AuthenticationStatus.INVALID: "Usuário ou senha inválidos.",
    AuthenticationStatus.IDENTITY_MISMATCH: "Usuário ou senha inválidos.",
    AuthenticationStatus.DIRECTORY_UNAVAILABLE: (
        "Serviço de autenticação indisponível. Tente em instantes."
    ),
    AuthenticationStatus.ACCOUNT_DISABLED: "Não foi possível autenticar. Contate o suporte de TI.",
    AuthenticationStatus.ACCOUNT_EXPIRED: "Não foi possível autenticar. Contate o suporte de TI.",
    AuthenticationStatus.ACCOUNT_LOCKED: "Não foi possível autenticar. Contate o suporte de TI.",
    AuthenticationStatus.PASSWORD_EXPIRED: "Não foi possível autenticar. Contate o suporte de TI.",
    AuthenticationStatus.MUST_CHANGE_PASSWORD: "Não foi possível autenticar. Contate o suporte de TI.",
}


class HybridLoginView(LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        result = getattr(self.request, "hybrid_auth_result", None)
        context["auth_message"] = _MESSAGES.get(
            getattr(result, "status", None),
            "Usuário ou senha inválidos.",
        )
        return context
