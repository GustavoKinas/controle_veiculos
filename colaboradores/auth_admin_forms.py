from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserChangeForm

from .models import Funcionario


CREATION_FIELDS = (
    "username", "nome", "first_name", "last_name", "email", "groups",
    "is_active", "is_staff", "is_superuser", "unidade_fabril", "centro_custo",
    "departamento", "secao", "ativo",
)


class UsernameCaseInsensitiveMixin:
    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if Funcionario.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username


class DirectoryFuncionarioCreationForm(UsernameCaseInsensitiveMixin, forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = CREATION_FIELDS

    def clean(self):
        cleaned = super().clean()
        if any(key.lower().startswith("password") for key in self.data):
            raise forms.ValidationError("Senha não pode ser enviada para vínculo AD.")
        if cleaned.get("is_superuser"):
            raise forms.ValidationError("Superusuários devem usar autenticação local.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.auth_source = Funcionario.AuthSource.DIRECTORY
        user.directory_guid = None
        user.set_unusable_password()
        if commit:
            user.save()
            self.save_m2m()
        return user


class VincularFuncionarioADForm(DirectoryFuncionarioCreationForm):
    pass


class LocalFuncionarioCreationForm(UsernameCaseInsensitiveMixin, forms.ModelForm):
    password1 = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput)

    class Meta:
        model = Funcionario
        fields = CREATION_FIELDS

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "As senhas não coincidem.")
            else:
                password_validation.validate_password(password1, self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.auth_source = Funcionario.AuthSource.LOCAL
        user.directory_guid = None
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class LocalFuncionarioChangeForm(UsernameCaseInsensitiveMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Funcionario
        exclude = ("auth_source", "directory_guid", "user_permissions")


class DirectoryFuncionarioChangeForm(UsernameCaseInsensitiveMixin, forms.ModelForm):
    class Meta:
        model = Funcionario
        exclude = ("password", "auth_source", "directory_guid", "user_permissions")

    def clean(self):
        cleaned = super().clean()
        if any(key.lower().startswith("password") for key in self.data):
            raise forms.ValidationError("Senha não pode ser enviada para vínculo AD.")
        if cleaned.get("is_superuser"):
            raise forms.ValidationError("Superusuários devem usar autenticação local.")
        return cleaned


class ConverterFuncionarioLocalForm(forms.Form):
    password1 = forms.CharField(label="Nova senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput)

    def __init__(self, *args, funcionario=None, **kwargs):
        self.funcionario = funcionario
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "As senhas não coincidem.")
            else:
                password_validation.validate_password(password1, self.funcionario)
        return cleaned

    def save(self):
        user = self.funcionario
        user.auth_source = Funcionario.AuthSource.LOCAL
        user.directory_guid = None
        user.set_password(self.cleaned_data["password1"])
        user.save(update_fields=["auth_source", "directory_guid", "password"])
        return user
