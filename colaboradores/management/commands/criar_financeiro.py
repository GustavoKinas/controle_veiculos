"""
Cria (ou atualiza a senha de) um usuário do setor financeiro.

O perfil financeiro fecha períodos e consulta o histórico. Não lança viagem,
não vê a agenda, não cadastra colaborador e não entra no /admin.

    python manage.py criar_financeiro --senha ...
    python manage.py criar_financeiro --username maria.financeiro --nome "Maria" --senha ...
"""

import os

from django.core.management.base import BaseCommand

from colaboradores.permissoes import GRUPO_FINANCEIRO, criar_usuario_de_perfil


class Command(BaseCommand):
    help = "Cria (ou atualiza a senha de) um usuário do perfil Financeiro."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="financeiro")
        parser.add_argument("--nome", default="Financeiro")
        parser.add_argument(
            "--senha",
            default=os.environ.get("DJANGO_FINANCEIRO_PASSWORD"),
            help="Senha do usuário. Também lida de DJANGO_FINANCEIRO_PASSWORD.",
        )

    def handle(self, *args, **options):
        senha = options["senha"]

        if not senha:
            self.stderr.write(
                self.style.ERROR(
                    "Informe a senha via --senha ou a variável "
                    "DJANGO_FINANCEIRO_PASSWORD."
                )
            )
            return

        funcionario, criado = criar_usuario_de_perfil(
            username=options["username"],
            senha=senha,
            nome=options["nome"],
            grupo=GRUPO_FINANCEIRO,
        )

        acao = "criado" if criado else "atualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Usuário '{funcionario.username}' {acao} no perfil "
                f"{GRUPO_FINANCEIRO}, com acesso apenas ao fechamento."
            )
        )
        self.stdout.write(
            "Se os grupos ainda não existirem, rode `python manage.py configurar_perfis`."
        )
