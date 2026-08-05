from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import ListView

from .forms import CadastroFuncionario, InativarFuncionarioForm
from .models import Funcionario


def logout_usuario(request: HttpRequest) -> HttpResponse:
    """
    Encerra a sessão e redireciona para o login.

    Feito como view própria (em vez do LogoutView nativo) porque, a partir do
    Django 5, o LogoutView aceita apenas POST — os links "Sair" do menu são
    GET (`<a href>`), o que resultaria em HTTP 405. Aqui aceitamos GET e POST.
    """
    logout(request)
    return redirect("login")


class FuncionariosView(LoginRequiredMixin, View):
    template_name = "funcionarios.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        acao = request.GET.get("acao")

        return render(
            request,
            self.template_name,
            {
                "acao": acao,
                "cadastro_form": CadastroFuncionario(),
                "inativar_form": InativarFuncionarioForm(),
                "mensagem": None,
                "tipo_mensagem": None,
                "funcionario_mensagem": None,
                "mensagem_acao": None,
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        acao = request.POST.get("acao")

        funcionario_mensagem = None
        mensagem_acao = None
        tipo_mensagem = None
        mensagem = None

        cadastro_form = CadastroFuncionario()
        inativar_form = InativarFuncionarioForm()

        if acao == "cadastrar":
            cadastro_form = CadastroFuncionario(request.POST)

            if cadastro_form.is_valid():
                funcionario = cadastro_form.save()
                cadastro_form = CadastroFuncionario()

                funcionario_mensagem = funcionario.nome
                mensagem_acao = "cadastrado com sucesso."
                tipo_mensagem = "success"

        elif acao == "inativar":
            inativar_form = InativarFuncionarioForm(request.POST)

            if inativar_form.is_valid():
                funcionario = inativar_form.inativar_funcionario()
                inativar_form = InativarFuncionarioForm()

                funcionario_mensagem = funcionario.nome
                mensagem_acao = "inativado com sucesso."
                tipo_mensagem = "success"
            else:
                mensagem = "Não foi possível inativar o funcionário."
                tipo_mensagem = "danger"

        else:
            mensagem = "Ação inválida."
            tipo_mensagem = "danger"

        return render(
            request,
            self.template_name,
            {
                "acao": acao,
                "cadastro_form": cadastro_form,
                "inativar_form": inativar_form,
                "funcionario_mensagem": funcionario_mensagem,
                "mensagem": mensagem,
                "mensagem_acao": mensagem_acao,
                "tipo_mensagem": tipo_mensagem,
            },
        )


class FuncionariosCadastradosView(LoginRequiredMixin, ListView):
    model = Funcionario
    template_name = "funcionarios_cadastrados.html"
    context_object_name = "funcionarios_cadastrados"
    paginate_by = 20

    def get_queryset(self):
        self.ordenar = self.request.GET.get("ordenar", "-id")
        self.busca = self.request.GET.get("q", "").strip()

        ordenacoes_permitidas = {
            "id": "id",
            "-id": "-id",
            "nome": "nome",
            "-nome": "-nome",
        }
        ordenacao = ordenacoes_permitidas.get(self.ordenar, "-id")

        queryset = Funcionario.objects.select_related("centro_custo")
        if self.busca:
            queryset = queryset.filter(nome__icontains=self.busca)

        return queryset.order_by(ordenacao)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ordenar"] = getattr(self, "ordenar", "-id")
        context["busca"] = getattr(self, "busca", "")
        return context
