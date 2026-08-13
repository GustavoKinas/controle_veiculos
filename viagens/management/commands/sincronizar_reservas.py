"""
Sincroniza as reservas de veículo a partir das agendas do Outlook.

Este comando é a cola entre as duas metades da integração — ele não conhece
nem o protocolo da Microsoft nem as regras do banco:

    integracoes.microsoft_graph  →  (eventos normalizados)  →  services.sincronizar_reservas

É este o comando que o serviço `scheduler` do docker-compose roda em laço
(ver docs/PRE_CADASTRO_VIAGENS.md §8.2).

    python manage.py sincronizar_reservas
    python manage.py sincronizar_reservas --dias 7
    python manage.py sincronizar_reservas --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from viagens.integracoes.microsoft_graph import (
    GraphIndisponivel,
    MicrosoftGraphClient,
    janela_de_consulta,
    periodo_da_janela,
)
from viagens.models import Veiculo
from viagens.services import sincronizar_reservas

JANELA_PADRAO_DIAS = 30


class Command(BaseCommand):
    help = "Importa as reservas de veículo das agendas do Outlook."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dias",
            type=int,
            default=JANELA_PADRAO_DIAS,
            help=f"Tamanho da janela em dias a partir de hoje (padrão: {JANELA_PADRAO_DIAS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta a API e mostra o que faria, sem gravar nada.",
        )

    def handle(self, *args, **opcoes) -> None:
        dias: int = opcoes["dias"]
        if dias < 1:
            raise CommandError("--dias precisa ser pelo menos 1.")

        # Só consultamos caixas que têm veículo cadastrado: cada caixa é uma
        # requisição HTTP, e chamar a API para uma sala que o sistema ignoraria
        # depois é desperdício puro.
        caixas = list(
            Veiculo.objects.filter(ativo=True)
            .exclude(email_recurso="")
            .values_list("email_recurso", flat=True)
        )
        if not caixas:
            raise CommandError(
                "Nenhum veículo ativo com caixa de recurso cadastrada. "
                "Rode `python manage.py cadastrar_veiculos_salas` para validar "
                "a integração com as salas de reunião."
            )

        inicio_iso, fim_iso = janela_de_consulta(dias)
        self.stdout.write(f"Janela: {inicio_iso} a {fim_iso}")
        self.stdout.write(f"Caixas de recurso: {len(caixas)}")

        cliente = MicrosoftGraphClient()
        try:
            coleta = cliente.coletar(caixas, dias=dias)
        except GraphIndisponivel as erro:
            # Credencial ausente/inválida derruba tudo — não há o que sincronizar.
            raise CommandError(str(erro)) from erro

        for email, mensagem in coleta.erros.items():
            self.stderr.write(self.style.WARNING(f"  falhou: {email} — {mensagem}"))

        self.stdout.write(
            f"{len(coleta.eventos)} evento(s) em "
            f"{len(coleta.caixas_consultadas)} caixa(s) consultada(s) com sucesso."
        )

        data_inicio, data_fim = periodo_da_janela(dias)

        if opcoes["dry_run"]:
            # Roda o serviço de verdade e desfaz: o resumo é exato, incluindo
            # o que seria cancelado — coisa que uma simulação "a seco" não
            # conseguiria calcular sem reimplementar as regras.
            with transaction.atomic():
                resumo = sincronizar_reservas(
                    eventos=coleta.eventos,
                    caixas_consultadas=coleta.caixas_consultadas,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                )
                transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY-RUN — nada foi gravado."))
        else:
            resumo = sincronizar_reservas(
                eventos=coleta.eventos,
                caixas_consultadas=coleta.caixas_consultadas,
                data_inicio=data_inicio,
                data_fim=data_fim,
            )

        for rotulo, quantidade in resumo.items():
            self.stdout.write(f"  {rotulo.replace('_', ' '):24} {quantidade:>4}")

        if coleta.erros:
            # Sai com código != 0 para o scheduler/CI perceberem a falha parcial.
            raise CommandError(f"{len(coleta.erros)} caixa(s) falharam.")
