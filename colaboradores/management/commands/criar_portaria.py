import os

from django.core.management.base import BaseCommand

from colaboradores.models import Funcionario


class Command(BaseCommand):
    help = (
        "Cria (ou atualiza a senha do) usuário-operador 'portaria', responsável "
        "por lançar as viagens de todos nesta primeira etapa."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="portaria")
        parser.add_argument(
            "--senha",
            default=os.environ.get("DJANGO_PORTARIA_PASSWORD"),
            help="Senha do operador. Também lida de DJANGO_PORTARIA_PASSWORD.",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Cria como superusuário (acesso ao /admin).",
        )

    def handle(self, *args, **options):
        username = options["username"]
        senha = options["senha"]

        if not senha:
            self.stderr.write(
                self.style.ERROR(
                    "Informe a senha via --senha ou a variável DJANGO_PORTARIA_PASSWORD."
                )
            )
            return

        funcionario, criado = Funcionario.objects.get_or_create(
            username=username,
            defaults={"nome": "Portaria", "is_staff": True},
        )

        funcionario.set_password(senha)
        funcionario.is_active = True
        if options["superuser"]:
            funcionario.is_staff = True
            funcionario.is_superuser = True
        funcionario.save()

        acao = "criado" if criado else "atualizado"
        self.stdout.write(
            self.style.SUCCESS(f"Usuário-operador '{username}' {acao} com sucesso.")
        )
