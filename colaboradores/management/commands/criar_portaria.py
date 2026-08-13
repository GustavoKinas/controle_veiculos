"""
Cria (ou atualiza a senha do) usuário-operador da portaria.

**A opção `--superuser` foi removida.** A portaria opera o dia a dia e não
administra o sistema: `is_staff` e `is_superuser` são forçados a False a cada
execução, então rodar este comando também serve para rebaixar um usuário que
tenha ganhado acesso ao /admin em algum momento.

Quem administra o sistema é o superusuário criado com `createsuperuser`.

    python manage.py criar_portaria --senha ...
    python manage.py criar_portaria --username portaria2 --senha ...
"""

import os

from django.core.management.base import BaseCommand

from colaboradores.permissoes import GRUPO_PORTARIA, criar_usuario_de_perfil


class Command(BaseCommand):
    help = (
        "Cria (ou atualiza a senha do) usuário-operador 'portaria', responsável "
        "por lançar as viagens de todos. Nunca dá acesso ao /admin."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="portaria")
        parser.add_argument("--nome", default="Portaria")
        parser.add_argument(
            "--senha",
            default=os.environ.get("DJANGO_PORTARIA_PASSWORD"),
            help="Senha do operador. Também lida de DJANGO_PORTARIA_PASSWORD.",
        )

    def handle(self, *args, **options):
        senha = options["senha"]

        if not senha:
            self.stderr.write(
                self.style.ERROR(
                    "Informe a senha via --senha ou a variável DJANGO_PORTARIA_PASSWORD."
                )
            )
            return

        funcionario, criado = criar_usuario_de_perfil(
            username=options["username"],
            senha=senha,
            nome=options["nome"],
            grupo=GRUPO_PORTARIA,
        )

        acao = "criado" if criado else "atualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Usuário-operador '{funcionario.username}' {acao} no perfil "
                f"{GRUPO_PORTARIA}, sem acesso ao /admin."
            )
        )
        self.stdout.write(
            "Se os grupos ainda não existirem, rode `python manage.py configurar_perfis`."
        )
