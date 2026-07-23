from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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

    def __str__(self):
        return f"{self.funcionario} — {self.data:%d/%m/%Y} ({self.km_percorrida} km)"

    @property
    def fechada(self) -> bool:
        return self.fechamento_id is not None

    def clean(self):
        if self.km_inicial is not None and self.km_final is not None:
            if self.km_final < self.km_inicial:
                raise ValidationError(
                    {"km_final": "A quilometragem final não pode ser menor que a inicial."}
                )

    def save(self, *args, **kwargs):
        # Congela o centro de custo a partir do funcionário se ainda não veio.
        if self.centro_custo_id is None and self.funcionario_id is not None:
            self.centro_custo_id = self.funcionario.centro_custo_id
        # Campo calculado persistido.
        if self.km_inicial is not None and self.km_final is not None:
            self.km_percorrida = max(self.km_final - self.km_inicial, 0)
        super().save(*args, **kwargs)
