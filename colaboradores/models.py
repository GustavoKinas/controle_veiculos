from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models


class UnidadeFabril(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=125, null=False, blank=False)

    class Meta:
        verbose_name = "Unidade Fabril"
        verbose_name_plural = "Unidades Fabris"
        ordering = ["nome"]
        db_table = "unidade_fabril"

    def __str__(self):
        return self.nome


class CentroCusto(models.Model):
    id = models.AutoField(primary_key=True)

    # Garante que o código tenha exatamente 10 dígitos numéricos.
    codigo_validator = RegexValidator(
        regex=r"^\d{10}$",
        message="O código do centro de custo deve conter exatamente 10 números.",
    )

    codigo = models.CharField(
        max_length=10,
        validators=[codigo_validator],
        unique=True,
        null=False,
        blank=False,
    )
    descricao = models.CharField(max_length=125, null=False, blank=False)

    class Meta:
        verbose_name = "Centro de Custo"
        verbose_name_plural = "Centros de Custo"
        ordering = ["codigo"]
        db_table = "centro_custo"

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"


class Funcionario(AbstractUser):
    """
    Funcionário É o usuário do sistema (AUTH_USER_MODEL).

    Herda de AbstractUser, então já possui: username, password, email,
    first_name, last_name, is_staff, is_superuser, is_active, groups,
    user_permissions, last_login e date_joined.

    Etapa 1: apenas o usuário-operador `portaria` faz login (ele lança as
    viagens de todos). Os demais funcionários existem como cadastro/base
    para as viagens e ainda não fazem login — por isso `unidade_fabril` e
    `centro_custo` são opcionais no banco (o operador não pertence a um
    centro de custo), mas obrigatórios para quem viaja (validado no
    formulário de viagem).
    """

    # `nome` é o nome de exibição do colaborador (distinto de username).
    nome = models.CharField(max_length=125, null=False, blank=True, default="")

    unidade_fabril = models.ForeignKey(
        UnidadeFabril,
        on_delete=models.PROTECT,
        related_name="funcionarios",
        null=True,
        blank=True,
    )

    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.PROTECT,
        related_name="funcionarios",
        null=True,
        blank=True,
    )

    # Flag de negócio: colaborador ativo para viagens. É intencionalmente
    # separado do `is_active` de autenticação do Django (que controla login).
    ativo = models.BooleanField(default=True)

    # Só pedimos username + senha no createsuperuser; o resto é editável depois.
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"
        ordering = ["nome"]
        db_table = "funcionarios"

    def __str__(self):
        return self.nome or self.username

    def save(self, *args, **kwargs):
        # Mantém o nome de exibição preenchido mesmo para usuários criados
        # apenas com username (ex.: portaria via createsuperuser).
        if not self.nome:
            self.nome = self.get_full_name() or self.username
        super().save(*args, **kwargs)
