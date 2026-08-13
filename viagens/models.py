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

    # Caixa de recurso do veículo no Outlook. É o `scheduleId` devolvido pela
    # Microsoft Graph e a única chave confiável para ligar uma reserva ao
    # veículo. Fica opcional: veículo sem agenda no Outlook continua válido.
    email_recurso = models.EmailField(blank=True, default="")

    class Meta:
        verbose_name = "Veículo"
        verbose_name_plural = "Veículos"
        ordering = ["modelo"]
        db_table = "veiculos"
        constraints = [
            # Unicidade só entre os veículos que têm caixa de recurso: vários
            # podem ficar com o campo em branco.
            models.UniqueConstraint(
                fields=["email_recurso"],
                condition=~models.Q(email_recurso=""),
                name="uniq_veiculo_por_email_recurso",
            )
        ]


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
    # NULO = viagem em andamento (veículo na rua). O operador registra a saída
    # com o km inicial e só informa o final no retorno. Ver `em_andamento`.
    #
    # ATENÇÃO: viagem em andamento NÃO pode entrar em fechamento — ela ainda
    # não tem quilometragem. Quem garante isso é `services.viagens_em_aberto`.
    km_final = models.PositiveIntegerField(null=True, blank=True)
    # Campo salvo (calculado no save): km_final - km_inicial, ou 0 enquanto a
    # viagem não foi concluída.
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
                # A cláusula `km_final IS NULL` libera a viagem em andamento.
                # Em SQL ela seria dispensável (NULL > x é UNKNOWN, e UNKNOWN
                # satisfaz uma CHECK), mas deixar implícito obrigaria quem lê
                # a conhecer lógica de três valores para entender a regra.
                condition=models.Q(km_final__isnull=True)
                | models.Q(km_final__gt=models.F("km_inicial")),
                name="km_final_gt_km_inicial",
                violation_error_message="A quilometragem final deve ser maior que a inicial.",
            )
        ]


    def __str__(self):
        return f"{self.funcionario} — {self.data:%d/%m/%Y} ({self.km_percorrida} km)"

    @property
    def fechada(self) -> bool:
        return self.fechamento_id is not None

    # -- Estado da viagem -------------------------------------------------
    # O estado é DERIVADO de `km_final`, não guardado num campo `status`.
    # São só dois estados, e a mesma informação em dois lugares acabaria
    # divergindo (status="concluída" com km_final vazio). Mesma lógica do
    # `fechada` acima. Em `ReservaViagem` são três estados, e por isso lá o
    # campo `status` existe de verdade.

    @property
    def em_andamento(self) -> bool:
        """Saída registrada, chegada ainda não: o veículo está na rua."""
        return self.km_final is None

    @property
    def concluida(self) -> bool:
        return self.km_final is not None

    @property
    def status_descricao(self) -> str:
        """Rótulo para telas e admin — a fonte da verdade continua sendo o km."""
        if self.em_andamento:
            return "Em andamento"
        return "Fechada" if self.fechada else "Concluída"

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

    def congelar_centro_custo(self) -> None:
        """
        Copia o centro de custo do funcionário, se ainda não houver um.

        Método próprio (e não só uma linha dentro do `save()`) porque quem
        monta a viagem fora de um ModelForm precisa chamá-lo **antes** do
        `full_clean()`: a validação de campo roda primeiro e acusaria
        `centro_custo` nulo, já que o preenchimento só aconteceria no `save()`.
        Pelo ModelForm o problema não aparece — `centro_custo` não é campo do
        formulário e fica fora da validação.
        """
        if self.centro_custo_id is None and self.funcionario_id is not None:
            self.centro_custo_id = self.funcionario.centro_custo_id

    def save(self, *args, **kwargs):
        self.congelar_centro_custo()
        # Campo calculado persistido. Enquanto a viagem está em andamento não
        # há distância conhecida — zero, e não "km_inicial", para que o rateio
        # jamais some quilômetro que ninguém percorreu.
        if self.km_inicial is not None and self.km_final is not None:
            self.km_percorrida = self.km_final - self.km_inicial
        else:
            self.km_percorrida = 0
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


class ReservaViagem(models.Model):
    """
    Pré-cadastro de viagem: a *intenção* de usar um veículo numa data.

    Não confundir com `Viagem`, que é o fato consumado e a única fonte do
    rateio. Reserva pode ser cancelada, remarcada ou nunca virar viagem, e
    nada disso pode tocar no fechamento (ver docs/PRE_CADASTRO_VIAGENS.md §3).

    A origem final é o Outlook, via Microsoft Graph: cada veículo é uma caixa
    de recurso e cada reserva, um evento na agenda dela.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        LANCADA = "lancada", "Lançada"
        CANCELADA = "cancelada", "Cancelada"

    class Origem(models.TextChoices):
        MANUAL = "manual", "Manual"
        OUTLOOK = "outlook", "Outlook"

    id = models.AutoField(primary_key=True)

    # Opcional de propósito: o Graph devolve o solicitante como texto livre no
    # assunto do evento (ver `solicitante_nome`), que nem sempre casa com um
    # cadastro. Reserva sem colaborador identificado ainda é útil — o operador
    # resolve na hora de lançar.
    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservas",
        null=True,
        blank=True,
    )
    # Texto cru vindo do assunto do evento, preservado mesmo quando o
    # `funcionario` foi identificado: é o rastro da origem.
    solicitante_nome = models.CharField(max_length=200, blank=True, default="")

    veiculo = models.ForeignKey(
        Veiculo,
        on_delete=models.PROTECT,
        related_name="reservas",
    )

    data = models.DateField()
    hora_inicio = models.TimeField(null=True, blank=True)
    hora_fim = models.TimeField(null=True, blank=True)
    destino = models.CharField(max_length=200, blank=True, default="")

    origem = models.CharField(
        max_length=20, choices=Origem.choices, default=Origem.MANUAL
    )
    # Id do evento no Outlook. Chave de idempotência do sync (fase 4).
    id_externo = models.CharField(max_length=255, blank=True, default="")

    # Três estados, então status explícito — a FK `viagem` sozinha não
    # distingue "cancelada" de "pendente" (ao contrário de Viagem.fechamento,
    # onde dois estados cabem na presença/ausência da FK).
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDENTE
    )

    # Rastreabilidade: qual lançamento nasceu desta reserva.
    viagem = models.OneToOneField(
        Viagem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserva",
    )

    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reserva de Viagem"
        verbose_name_plural = "Reservas de Viagem"
        ordering = ["data", "hora_inicio", "id"]
        db_table = "reserva_viagem"
        indexes = [
            # A consulta da agenda é sempre "reservas deste intervalo, por status".
            models.Index(fields=["data", "status"], name="idx_reserva_data_status"),
        ]
        constraints = [
            # Idempotência do sync: rodar duas vezes não duplica. A condição
            # libera as reservas manuais, que não têm id externo.
            models.UniqueConstraint(
                fields=["origem", "id_externo"],
                condition=~models.Q(id_externo=""),
                name="uniq_reserva_por_evento_externo",
            ),
        ]

    def __str__(self) -> str:
        quem = self.funcionario or self.solicitante_nome or "Solicitante não identificado"
        return f"{quem} — {self.data:%d/%m/%Y} ({self.veiculo})"

    @property
    def pendente(self) -> bool:
        return self.status == self.Status.PENDENTE

    @property
    def atrasada(self) -> bool:
        """Pendente com a data já passada: precisa de atenção do operador."""
        return self.pendente and self.data < timezone.localdate()

    @property
    def descricao_solicitante(self) -> str:
        """Nome a exibir, com fallback para o texto cru vindo do Outlook."""
        if self.funcionario_id:
            return str(self.funcionario)
        return self.solicitante_nome or "Não identificado"
