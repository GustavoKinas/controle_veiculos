from django import forms
from django.utils.text import slugify

from .models import Funcionario


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    return "".join(texto.lower().split())


def gerar_username(nome: str) -> str:
    """
    Gera um username único a partir do nome. Funcionários cadastrados nesta
    etapa não fazem login (senha inutilizável), mas AbstractUser exige um
    username único.
    """
    base = slugify(nome).replace("-", ".") or "colaborador"
    username = base
    contador = 1
    while Funcionario.objects.filter(username=username).exists():
        contador += 1
        username = f"{base}.{contador}"
    return username


class CadastroFuncionario(forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = ["nome", "email", "unidade_fabril", "centro_custo"]

        widgets = {
            "nome": forms.TextInput(attrs={"class": "input"}),
            "email": forms.EmailInput(
                attrs={
                    "class": "input",
                    "placeholder": "nome.sobrenome@grupoflexivel.com.br",
                }
            ),
            "unidade_fabril": forms.Select(attrs={"class": "select"}),
            "centro_custo": forms.Select(attrs={"class": "select"}),
        }

        labels = {
            "nome": "Nome do Colaborador",
            "email": "E-mail corporativo",
            "unidade_fabril": "Unidade Fabril",
            "centro_custo": "Centro de Custo",
        }

        help_texts = {
            # É a chave que liga o colaborador ao organizador do evento no
            # Outlook. Sem ele, a reserva importada fica sem colaborador
            # identificado e o operador precisa escolher na hora de lançar.
            "email": "Usado para identificar o colaborador nas reservas vindas do Outlook.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unidade_fabril"].empty_label = "Selecione uma unidade fabril"
        self.fields["centro_custo"].empty_label = "Selecione um centro de custo"
        # Regra de negócio: todo colaborador que viaja pertence a exatamente
        # um centro de custo.
        self.fields["centro_custo"].required = True

    def clean_nome(self):
        nome = self.cleaned_data.get("nome")

        if nome:
            novo_normalizado = normalizar_texto(nome)
            for funcionario in Funcionario.objects.all():
                if normalizar_texto(funcionario.nome) == novo_normalizado:
                    raise forms.ValidationError("Este colaborador já está cadastrado")
            return nome.strip()

        return nome

    def save(self, commit=True):
        funcionario = super().save(commit=False)
        if not funcionario.username:
            funcionario.username = gerar_username(funcionario.nome)
        # Sem login nesta etapa: senha inutilizável até o colaborador ganhar
        # acesso próprio no futuro.
        funcionario.set_unusable_password()
        if commit:
            funcionario.save()
        return funcionario


class InativarFuncionarioForm(forms.Form):
    funcionario = forms.ModelChoiceField(
        queryset=Funcionario.objects.none(),
        label="Colaborador",
        empty_label="Selecione um colaborador",
        widget=forms.Select(attrs={"class": "select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["funcionario"].queryset = Funcionario.objects.filter(
            ativo=True
        ).order_by("nome")

    def inativar_funcionario(self):
        funcionario = self.cleaned_data["funcionario"]
        funcionario.ativo = False
        funcionario.save(update_fields=["ativo"])
        return funcionario
