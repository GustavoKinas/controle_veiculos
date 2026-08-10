from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.utils import timezone
from colaboradores.models import CentroCusto


class Fechamento(models.Model):
    """
    Fechamento financeiro de um período. Ao ser confirmado, "consome" todas
    as viagens em aberto dentro do intervalo, marcando-as para que nunca
    entrem em outro fechamento (evita duplicidade de rateio).
    """

    id = models.AutoField(primary_key=True)
    data_inicio = models.DateField()
    data_fim = models.DateField()
    total_km = models.PositiveIntegerField(default=0)

    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fechamentos_criados",
    )

    class Meta:
        verbose_name = "Fechamento"
        verbose_name_plural = "Fechamentos"
        ordering = ["-criado_em"]
        db_table = "fechamento"

    def __str__(self):
        return f"Fechamento {self.data_inicio:%d/%m/%Y} a {self.data_fim:%d/%m/%Y}"


class FechamentoRateio(models.Model):
    """
    Snapshot do rateio por Centro de Custo no momento do fechamento. Guardar
    o resultado torna o fechamento auditável e imune a mudanças futuras nos
    dados (ex.: um funcionário trocar de centro de custo depois).
    """

    id = models.AutoField(primary_key=True)
    fechamento = models.ForeignKey(
        Fechamento,
        on_delete=models.CASCADE,
        related_name="rateios",
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.PROTECT,
        related_name="rateios",
    )
    km_percorrida = models.PositiveIntegerField(default=0)
    percentual = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Rateio do Fechamento"
        verbose_name_plural = "Rateios do Fechamento"
        ordering = ["-km_percorrida"]
        db_table = "fechamento_rateio"
        constraints = [
            models.UniqueConstraint(
                fields=["fechamento", "centro_custo"],
                name="uniq_rateio_por_centro_custo",
            )
        ]

    def __str__(self):
        return f"{self.centro_custo} — {self.km_percorrida} km ({self.percentual}%)"

class Veiculo(models.Model):

    id = models.AutoField(primary_key=True)
    placa = models.CharField(max_length=7,unique=True)
    modelo = models.CharField(max_length=125, blank=True, default="")
    marca = models.CharField(max_length=40, blank=True, default="")
    km_atual = models.PositiveBigIntegerField(default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Veículo"
        verbose_name_plural = "Veículos"
        ordering = ["modelo"]
        db_table = "veiculos"
        

    def __str__(self):
        return f"{self.marca} - {self.modelo} - {self.placa}"
    
class Viagem(models.Model):
    """
    Registro de uma viagem realizada por um funcionário. O Centro de Custo é
    "congelado" no momento do lançamento (a partir do funcionário) para manter
    o histórico consistente caso ele mude de centro de custo no futuro.
    """

    id = models.AutoField(primary_key=True)

    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="viagens",
    )

    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.PROTECT,
        related_name="viagens",
    )
    data = models.DateField()

    km_inicial = models.PositiveIntegerField()
    km_final = models.PositiveIntegerField()
    # Campo salvo (calculado no save): km_final - km_inicial.
    km_percorrida = models.PositiveIntegerField(default=0, editable=False)

    # Snapshot do centro de custo do funcionário no momento do lançamento.
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.PROTECT,
        related_name="viagens",
    )

    # Vínculo com o fechamento que já processou esta viagem. Nulo = em aberto.
    # Serve como o "status de fechamento" (booleano) e como rastreabilidade.
    fechamento = models.ForeignKey(
        Fechamento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="viagens",
    )

    criada_em = models.DateTimeField(auto_now_add=True)
    lancada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="viagens_lancadas",
    )

    class Meta:
        verbose_name = "Viagem"
        verbose_name_plural = "Viagens"
        ordering = ["-data", "-id"]
        db_table = "viagem"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(km_final__gt=models.F('km_inicial')),
                name='km_final_gt_km_inicial',
                violation_error_message="A quilometragem final deve ser maior que a inicial.",
            )
        ]


    def __str__(self):
        return f"{self.funcionario} — {self.data:%d/%m/%Y} ({self.km_percorrida} km)"

    @property
    def fechada(self) -> bool:
        return self.fechamento_id is not None

    def clean(self):
        erros = {}
        # Import tardio: services importa models (evita import circular).
        from .services import validar_quilometragem

        # Vale para qualquer caminho de validação (ModelForm, admin,
        # full_clean() em scripts), não só para a tela de lançamento.
        #
        # clean() roda mesmo quando um campo já falhou na validação de campo, e
        # aí o atributo chega vazio (o construct_instance não o preenche). Daí
        # os `is not None` antes de cada comparação, e os valores em lista —
        # é o formato que update_error_dict() espera para acumular.
        if self.data is not None and self.data > timezone.localdate():
            erros["data"] = ["A data da viagem não pode ser maior que a data atual."]

        try:
            validar_quilometragem(
                # `self.veiculo` LEVANTA RelatedObjectDoesNotExist quando a FK
                # é obrigatória e não foi preenchida — não devolve None. Por
                # isso perguntamos à coluna (`veiculo_id`) antes de tocar no
                # objeto: sem veículo, a validação de hodômetro não se aplica.
                self.veiculo if self.veiculo_id else None,
                self.data,
                self.km_inicial,
                self.km_final,
                viagem_id=self.pk,
            )
        except ValidationError as e:
            erros = e.update_error_dict(erros)

        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        # Congela o centro de custo a partir do funcionário se ainda não veio.
        if self.centro_custo_id is None and self.funcionario_id is not None:
            self.centro_custo_id = self.funcionario.centro_custo_id
        # Campo calculado persistido.
        if self.km_inicial is not None and self.km_final is not None:
            self.km_percorrida = self.km_final - self.km_inicial
        super().save(*args, **kwargs)
        from .services import atualizar_km_veiculo
        atualizar_km_veiculo(self.veiculo)


@receiver(post_delete, sender=Viagem)
def _recalcular_km_ao_excluir_viagem(sender, instance, **kwargs):
    """
    Excluir a maior viagem de um veículo tem que baixar o hodômetro — senão o
    `km_atual` fica inflado e passa a barrar lançamentos legítimos.
    """
    from .services import atualizar_km_veiculo

    atualizar_km_veiculo(instance.veiculo)
