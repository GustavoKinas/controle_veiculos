"""
Sincroniza as reservas de veículo a partir das agendas do Outlook.

A orquestração vive em `viagens/sincronizacao.py`, compartilhada com o botão
"Sincronizar" da agenda. Este comando é a casca de linha de comando dela:
converte argumentos, imprime e escolhe o código de saída.

    python manage.py sincronizar_reservas
    python manage.py sincronizar_reservas --dias 7
    python manage.py sincronizar_reservas --dry-run

É este o comando que o serviço `scheduler` do docker-compose roda em laço
(ver docs/PRE_CADASTRO_VIAGENS.md §8.2). Ele sai com código diferente de zero
quando alguma caixa falha, para o scheduler perceber a falha parcial.
"""

from django.core.management.base import BaseCommand, CommandError

from viagens.sincronizacao import (
    JANELA_PADRAO_DIAS,
    GraphIndisponivel,
    SemCaixasCadastradas,
    executar_sincronizacao,
)


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

        try:
            resultado = executar_sincronizacao(dias=dias, dry_run=opcoes["dry_run"])
        except SemCaixasCadastradas as erro:
            raise CommandError(str(erro)) from erro
        except GraphIndisponivel as erro:
            # Credencial ausente/inválida derruba tudo — não há o que sincronizar.
            raise CommandError(str(erro)) from erro

        inicio_iso, fim_iso = resultado.janela
        self.stdout.write(f"Janela: {inicio_iso} a {fim_iso}")
        self.stdout.write(f"Caixas de recurso: {resultado.caixas_pedidas}")

        for email, mensagem in resultado.erros.items():
            self.stderr.write(self.style.WARNING(f"  falhou: {email} — {mensagem}"))

        self.stdout.write(
            f"{resultado.total_eventos} evento(s) em "
            f"{len(resultado.caixas_consultadas)} caixa(s) consultada(s) com sucesso."
        )

        if resultado.dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN — nada foi gravado."))

        for rotulo, quantidade in resultado.resumo.items():
            self.stdout.write(f"  {rotulo.replace('_', ' '):24} {quantidade:>4}")

        if resultado.erros:
            raise CommandError(f"{len(resultado.erros)} caixa(s) falharam.")
