from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager
from django.core.validators import RegexValidator
from django.db import models


def preparar_descricao_catalogo(descricao: str) -> str:
    """Remove espaços excedentes sem alterar a grafia exibida."""
    return " ".join((descricao or "").split())


def normalizar_descricao_catalogo(descricao: str) -> str:
    """Gera a chave de comparação de um catálogo sem distinção de caixa."""
    return preparar_descricao_catalogo(descricao).casefold()


class FuncionarioManager(UserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        if (
            extra_fields.get("auth_source", Funcionario.AuthSource.DIRECTORY)
            == Funcionario.AuthSource.DIRECTORY
            and password is not None
        ):
            raise ValueError("Não é permitido definir senha local para usuários do Active Directory.")
        return super().create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        if extra_fields.get("auth_source", Funcionario.AuthSource.LOCAL) != Funcionario.AuthSource.LOCAL:
            raise ValueError("Superusuários devem usar autenticação local.")
        extra_fields["auth_source"] = Funcionario.AuthSource.LOCAL
        return super().create_superuser(username, email, password, **extra_fields)


class UnidadeFabril(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.CharField(max_length=125, null=False, blank=False)
    codigo_empresa_erp = models.PositiveIntegerField(
        null=True,
        blank=True,
        unique=True,
        verbose_name="Código empresa ERP",
    )

    class Meta:
        verbose_name = "Unidade Fabril"
        verbose_name_plural = "Unidades Fabris"
        ordering = ["nome"]
        db_table = "unidade_fabril"

    def __str__(self):
        return self.nome


class Departamento(models.Model):
    id = models.AutoField(primary_key=True)
    descricao = models.CharField(max_length=125, null=False, blank=False)
    descricao_normalizada = models.CharField(
        max_length=125,
        unique=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"
        ordering = ["descricao"]
        db_table = "departamento"

    def __str__(self):
        return self.descricao

    def save(self, *args, **kwargs):
        self.descricao = preparar_descricao_catalogo(self.descricao)
        self.descricao_normalizada = normalizar_descricao_catalogo(self.descricao)
        super().save(*args, **kwargs)


class Secao(models.Model):
    id = models.AutoField(primary_key=True)
    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.PROTECT,
        related_name="secoes",
    )
    descricao = models.CharField(max_length=125, null=False, blank=False)
    descricao_normalizada = models.CharField(max_length=125, editable=False)

    class Meta:
        verbose_name = "Seção"
        verbose_name_plural = "Seções"
        ordering = ["descricao"]
        db_table = "secao"
        constraints = [
            models.UniqueConstraint(
                fields=["departamento", "descricao_normalizada"],
                name="uniq_secao_por_departamento",
            )
        ]

    def __str__(self):
        return self.descricao

    def save(self, *args, **kwargs):
        self.descricao = preparar_descricao_catalogo(self.descricao)
        self.descricao_normalizada = normalizar_descricao_catalogo(self.descricao)
        super().save(*args, **kwargs)


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

    Apenas o usuário-operador `portaria` faz login (ele lança as
    viagens de todos). Os demais funcionários existem como cadastro/base
    para as viagens e ainda não fazem login — por isso `unidade_fabril` e
    `centro_custo` são opcionais no banco (o operador não pertence a um
    centro de custo), mas obrigatórios para quem viaja (validado no
    formulário de viagem).
    """

    class AuthSource(models.TextChoices):
        LOCAL = "LOCAL", "Local"
        DIRECTORY = "DIRECTORY", "Active Directory"

    objects = FuncionarioManager()

    auth_source = models.CharField(
        max_length=10,
        choices=AuthSource.choices,
        default=AuthSource.DIRECTORY,
    )
    directory_guid = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )

    # `nome` é o nome de exibição do colaborador (distinto de username).
    nome = models.CharField(max_length=125, null=False, blank=True, default="")

    codigo_funcionario_erp = models.CharField(
        max_length=125,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Código ERP",
    )

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

    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.PROTECT,
        related_name="funcionarios",
        null=True,
        blank=True,
    )

    secao = models.ForeignKey(
        Secao,
        on_delete=models.PROTECT,
        related_name="funcionarios",
        null=True,
        blank=True,
    )

    # Flag de negócio: colaborador ativo para viagens. É intencionalmente
    # separado do `is_active` de autenticação do Django (que controla login).
    ativo = models.BooleanField(default=True)
    pode_receber_reserva_manual = models.BooleanField(
        default=False,
        verbose_name="Pode receber reserva manual",
    )

    # Escritos exclusivamente pela sincronização com o ERP (admissão grava
    # só data_admissao, demissão só data_demissao — nunca as duas na mesma
    # operação). PJs, fora do fluxo automático, ficam
    # com os dois em branco.
    data_admissao = models.DateField(
        null=True, blank=True, verbose_name="Data de admissão"
    )
    data_demissao = models.DateField(
        null=True, blank=True, verbose_name="Data de demissão"
    )

    # Só pedimos username + senha no createsuperuser; o resto é editável depois.
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Funcionário"
        verbose_name_plural = "Funcionários"
        ordering = ["nome"]
        db_table = "funcionarios"
        constraints = [
            # `email` (herdado do AbstractUser) é a chave de junção com o
            # Outlook: o sync casa o organizador do evento com o cadastro por
            # este campo. Dois colaboradores com o mesmo e-mail fariam uma
            # reserva sumir silenciosamente do mapa em memória.
            # Parcial porque a maioria dos cadastros ainda está sem e-mail.
            models.UniqueConstraint(
                fields=["email"],
                condition=~models.Q(email=""),
                name="uniq_funcionario_por_email",
            ),
            models.UniqueConstraint(
                fields=["unidade_fabril", "codigo_funcionario_erp"],
                condition=(
                    models.Q(unidade_fabril__isnull=False)
                    & models.Q(codigo_funcionario_erp__isnull=False)
                    & ~models.Q(codigo_funcionario_erp="")
                ),
                name="uniq_funcionario_codigo_erp_por_unidade",
            ),
        ]

    def __str__(self):
        return self.nome or self.username

    def save(self, *args, **kwargs):
        if self.auth_source == self.AuthSource.DIRECTORY and self.has_usable_password():
            self.set_unusable_password()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"password"}
        # Mantém o nome de exibição preenchido mesmo para usuários criados
        # apenas com username (ex.: portaria via createsuperuser).
        if not self.nome:
            self.nome = self.get_full_name() or self.username
        # Normaliza a chave de junção. O Graph devolve o e-mail com a grafia
        # do Active Directory ("Jacson.Maia@..." hoje, "jacson.maia@..."
        # amanhã) e o `IN` do Postgres é case-sensitive: sem isto o sync não
        # casaria ninguém, e sem erro nenhum.
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)
