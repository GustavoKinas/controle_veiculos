"""
Sincroniza funcionários (admissão/demissão) a partir da API do ERP.

A orquestração vive em `colaboradores/sincronizacao_erp.py`, compartilhada
com o botão do Admin. Este comando é a casca de linha de comando dela —
mesmo papel que `sincronizar_reservas.py` cumpre para o Outlook.

    python manage.py sincronizar_funcionarios_erp
    python manage.py sincronizar_funcionarios_erp --operacao admissao
    python manage.py sincronizar_funcionarios_erp --operacao demissao
    python manage.py sincronizar_funcionarios_erp --periodo 202609

Sem --operacao, roda as duas — admissão de todas as empresas antes de
qualquer demissão. É este o comando que o cron do container dispara nos 4
horários definidos no desenho. Sai com código diferente de zero quando há
falhas, para o cron perceber pelo log.
"""

from django.core.management.base import BaseCommand, CommandError

from colaboradores.sincronizacao_erp import mes_corrente, sincronizar

OPERACOES_VALIDAS = ("admissao", "demissao")


class Command(BaseCommand):
    help = "Sincroniza admissões e demissões de funcionários com a API do ERP."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--operacao",
            choices=OPERACOES_VALIDAS,
            default=None,
            help="Roda só admissão ou só demissão. Sem isto, roda as duas.",
        )
        parser.add_argument(
            "--periodo",
            default=None,
            help="Mês AAAAMM a consultar (padrão: mês corrente em America/Sao_Paulo).",
        )

    def handle(self, *args, **opcoes) -> None:
        periodo = opcoes["periodo"] or mes_corrente()
        if len(periodo) != 6 or not periodo.isdecimal():
            raise CommandError(f"--periodo precisa ser AAAAMM, recebido '{periodo}'.")

        operacoes = (opcoes["operacao"],) if opcoes["operacao"] else OPERACOES_VALIDAS

        resultado = sincronizar(periodo=periodo, operacoes=operacoes)

        self.stdout.write(f"Período: {resultado.periodo} — operações: {', '.join(resultado.operacoes)}")
        self.stdout.write(
            f"Empresas processadas: {resultado.empresas_processadas} — "
            f"com falha: {resultado.empresas_com_falha}"
        )
        for rotulo, quantidade in resultado.resumo().items():
            self.stdout.write(f"  {rotulo.replace('_', ' '):20} {quantidade:>4}")

        for erro in resultado.erros:
            self.stderr.write(self.style.WARNING(f"  falhou: {erro}"))

        if resultado.houve_falha:
            raise CommandError(f"{len(resultado.erros)} erro(s) na sincronização.")
