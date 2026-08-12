"""
Gera reservas de viagem fictícias para desenvolver a agenda sem depender do
Microsoft Graph.

Os dados imitam o que a API devolve hoje (ver `poc_microsoft_graph.py`):
cada veículo é uma caixa de recurso e cada reserva traz apenas o **assunto do
evento** como identificação do solicitante — texto livre, que às vezes não
casa com nenhum cadastro e às vezes nem existe. O mock reproduz esses três
casos de propósito, porque são eles que quebram a tela.

Uso:
    python manage.py criar_reservas_mock                 # 7 dias a partir de hoje
    python manage.py criar_reservas_mock --dias 14
    python manage.py criar_reservas_mock --limpar        # remove os mocks antes
"""

import random
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from colaboradores.models import Funcionario
from viagens.models import ReservaViagem, Veiculo

# Faixas de horário típicas de uma reserva de veículo.
JANELAS: list[tuple[time, time]] = [
    (time(7, 30), time(9, 0)),
    (time(8, 0), time(12, 0)),
    (time(9, 0), time(11, 0)),
    (time(13, 0), time(14, 30)),
    (time(13, 15), time(17, 30)),
    (time(15, 30), time(17, 0)),
]

DESTINOS: list[str] = [
    "Visita a cliente",
    "Unidade Fabril II",
    "Aeroporto",
    "Fornecedor",
    "Treinamento externo",
    "",
]

# Nomes que NÃO existem no cadastro: simulam o assunto do evento que o sync
# não conseguirá casar com um Funcionario.
SOLICITANTES_DESCONHECIDOS: list[str] = [
    "Tamara Suelen Köpp",
    "Jacson Roberto de Maia",
    "Bernard Sandrin",
]


class Command(BaseCommand):
    help = "Cria reservas de viagem fictícias para desenvolvimento da agenda."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dias",
            type=int,
            default=7,
            help="Quantos dias a partir de hoje devem receber reservas (padrão: 7).",
        )
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove as reservas mockadas ainda pendentes antes de gerar.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Semente do gerador — mesma semente, mesmos dados (padrão: 42).",
        )

    @transaction.atomic
    def handle(self, *args, **opcoes) -> None:
        dias: int = opcoes["dias"]
        if dias < 1:
            raise CommandError("--dias precisa ser pelo menos 1.")

        veiculos = list(Veiculo.objects.filter(ativo=True).order_by("placa"))
        if not veiculos:
            raise CommandError(
                "Nenhum veículo ativo cadastrado. Cadastre ao menos um no admin."
            )

        funcionarios = list(
            Funcionario.objects.filter(
                ativo=True, centro_custo__isnull=False
            ).order_by("nome")[:20]
        )
        if not funcionarios:
            raise CommandError(
                "Nenhum colaborador ativo com centro de custo. "
                "Cadastre em /colaboradores/ antes de gerar reservas."
            )

        if opcoes["limpar"]:
            removidas, _ = ReservaViagem.objects.filter(
                origem=ReservaViagem.Origem.OUTLOOK,
                status=ReservaViagem.Status.PENDENTE,
            ).delete()
            self.stdout.write(f"Removidas {removidas} reserva(s) mockada(s).")

        sorteio = random.Random(opcoes["seed"])
        hoje = timezone.localdate()
        criadas = atualizadas = 0

        for deslocamento in range(dias):
            dia = hoje + timedelta(days=deslocamento)
            if dia.weekday() >= 5:            # sem reservas em fim de semana
                continue

            for veiculo in veiculos:
                # Nem todo veículo é reservado todo dia.
                for _ in range(sorteio.choice([0, 0, 1, 1, 2])):
                    hora_inicio, hora_fim = sorteio.choice(JANELAS)
                    funcionario, solicitante = self._sortear_solicitante(
                        sorteio, funcionarios
                    )

                    # `update_or_create` na chave de idempotência: rodar o
                    # comando duas vezes atualiza, não duplica — exatamente o
                    # comportamento que o sync real precisará ter.
                    _, foi_criada = ReservaViagem.objects.update_or_create(
                        origem=ReservaViagem.Origem.OUTLOOK,
                        id_externo=self._id_externo(veiculo, dia, hora_inicio),
                        defaults={
                            "funcionario": funcionario,
                            "solicitante_nome": solicitante,
                            "veiculo": veiculo,
                            "data": dia,
                            "hora_inicio": hora_inicio,
                            "hora_fim": hora_fim,
                            "destino": sorteio.choice(DESTINOS),
                        },
                    )
                    criadas += foi_criada
                    atualizadas += not foi_criada

        self.stdout.write(
            self.style.SUCCESS(
                f"{criadas} reserva(s) criada(s), {atualizadas} atualizada(s) "
                f"em {dias} dia(s) a partir de {hoje:%d/%m/%Y}."
            )
        )

    @staticmethod
    def _sortear_solicitante(
        sorteio: random.Random, funcionarios: list[Funcionario]
    ) -> tuple[Funcionario | None, str]:
        """
        Devolve (funcionario, nome_no_assunto).

        Um em cada quatro eventos não casa com o cadastro — é o caso real que
        a tela precisa exibir sem quebrar.
        """
        if sorteio.random() < 0.25:
            return None, sorteio.choice(SOLICITANTES_DESCONHECIDOS)
        funcionario = sorteio.choice(funcionarios)
        return funcionario, funcionario.nome

    @staticmethod
    def _id_externo(veiculo: Veiculo, dia: date, hora_inicio: time) -> str:
        """Imita o id de evento do Outlook, estável para o mesmo horário."""
        return f"mock-{veiculo.placa}-{dia:%Y%m%d}-{hora_inicio:%H%M}"
