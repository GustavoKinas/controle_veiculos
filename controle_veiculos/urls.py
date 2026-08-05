"""
URL configuration do projeto controle_veiculos.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from colaboradores.views import logout_usuario

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", logout_usuario, name="logout"),
    # Raiz redireciona para a tela principal (lançamento de viagens).
    path("", RedirectView.as_view(pattern_name="lancar_viagem", permanent=False)),
    path("viagens/", include("viagens.urls")),
    path("colaboradores/", include("colaboradores.urls")),
]
