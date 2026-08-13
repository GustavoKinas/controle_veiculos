"""
Cadastra as salas de reunião como veículos, para validar a integração com o
Microsoft Graph antes de existirem caixas de recurso para os carros de verdade.

**Isto é andaime de validação, não dado de produção.** As salas viram veículos
apenas porque já têm agenda no Outlook e reservas reais acontecendo — é o que
permite exercitar o sync ponta a ponta com dado vivo. Quando os veículos
ganharem suas próprias caixas de recurso, rode com `--remover`.

    python manage.py cadastrar_veiculos_salas
    python manage.py cadastrar_veiculos_salas --remover
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from viagens.models import Veiculo

# As mesmas caixas consultadas na POC. Placa é sintética (o modelo exige uma,
# única e com no máximo 7 caracteres) e o nome da sala vai em `modelo`.
SALAS = [
    ("SALA001", "Autenticidade", "autenticidade@grupoflexivel.com.br"),
    ("SALA002", "Integridade", "integridade@grupoflexivel.com.br"),
    ("SALA003", "Humanismo", "humanismo@grupoflexivel.com.br"),
    ("SALA004", "Sustentabilidade", "sustentabilidade@grupoflexivel.com.br"),
    ("SALA005", "Produtividade", "produtividade@grupoflexivel.com.br"),
    ("SALA006", "Integracao", "integracao@grupoflexivel.com.br"),
    ("SALA007", "Eficiencia", "eficiencia@grupoflexivel.com.br"),
    ("SALA008", "Inovacao", "inovacao@grupoflexivel.com.br"),
]

MARCA = "SALA DE REUNIÃO"


class Command(BaseCommand):
    help = "Cadastra (ou remove) as salas de reunião como veículos de teste."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--remover",
            action="store_true",
            help="Remove os veículos-sala em vez de criá-los.",
        )

    @transaction.atomic
    def handle(self, *args, **opcoes) -> None:
        if opcoes["remover"]:
            return self._remover()

        criados = atualizados = 0
        for placa, nome, email in SALAS:
            # A placa é a chave natural aqui: rodar o comando de novo atualiza
            # o cadastro em vez de estourar na unicidade.
            _, foi_criado = Veiculo.objects.update_or_create(
                placa=placa,
                defaults={
                    "modelo": nome,
                    "marca": MARCA,
                    "email_recurso": email,
                    "ativo": True,
                },
            )
            criados += foi_criado
            atualizados += not foi_criado

        self.stdout.write(
            self.style.SUCCESS(
                f"{criados} veículo(s)-sala criado(s), {atualizados} atualizado(s). "
                "Rode `python manage.py sincronizar_reservas` em seguida."
            )
        )

    def _remover(self) -> None:
        placas = [placa for placa, _, _ in SALAS]
        # PROTECT na FK de Viagem/ReservaViagem: se houver algo vinculado, o
        # delete estoura — de propósito. Melhor falhar do que apagar histórico.
        removidos, _ = Veiculo.objects.filter(placa__in=placas).delete()
        self.stdout.write(self.style.SUCCESS(f"{removidos} registro(s) removido(s)."))
