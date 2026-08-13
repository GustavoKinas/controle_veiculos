"""
URL configuration do projeto controle_veiculos.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from colaboradores.views import logout_usuario, pagina_inicial

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
    # A raiz não aponta para uma tela fixa: cada perfil tem a sua página
    # inicial (ver colaboradores.views.pagina_inicial).
    path("", pagina_inicial, name="pagina_inicial"),
    path("viagens/", include("viagens.urls")),
    path("colaboradores/", include("colaboradores.urls")),
]
