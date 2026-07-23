from django.urls import path

from .views import FuncionariosCadastradosView, FuncionariosView

urlpatterns = [
    path("", FuncionariosView.as_view(), name="funcionarios"),
    path(
        "cadastrados/",
        FuncionariosCadastradosView.as_view(),
        name="funcionarios_cadastrados",
    ),
]
