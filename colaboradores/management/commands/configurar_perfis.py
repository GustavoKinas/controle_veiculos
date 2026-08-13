"""
Cria os grupos de acesso e aplica as permissões de cada perfil.

A política vive em `colaboradores/permissoes.py`; este comando é só o que a
grava no banco. Rode depois de toda migration que mexa em permissões e
sempre que a lista de `PERMISSOES_POR_PERFIL` mudar.

    python manage.py configurar_perfis
    python manage.py configurar_perfis --listar
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from colaboradores.permissoes import PERMISSOES_POR_PERFIL, sincronizar_perfis


class Command(BaseCommand):
    help = "Cria os grupos Portaria e Financeiro com suas permissões."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--listar",
            action="store_true",
            help="Só mostra o que está gravado hoje, sem alterar nada.",
        )

    def handle(self, *args, **opcoes) -> None:
        if opcoes["listar"]:
            return self._listar()

        resumo = sincronizar_perfis()
        for grupo, quantidade in resumo.items():
            self.stdout.write(
                self.style.SUCCESS(f"{grupo}: {quantidade} permissão(ões) aplicada(s).")
            )
        self.stdout.write(
            "Perfis sincronizados. Use --listar para conferir o estado no banco."
        )

    def _listar(self) -> None:
        for nome in PERMISSOES_POR_PERFIL:
            grupo = Group.objects.filter(name=nome).first()
            if grupo is None:
                self.stdout.write(self.style.WARNING(f"{nome}: grupo não existe."))
                continue

            permissoes = grupo.permissions.select_related("content_type").order_by(
                "content_type__app_label", "codename"
            )
            self.stdout.write(f"\n{nome} ({grupo.user_set.count()} usuário(s)):")
            for permissao in permissoes:
                self.stdout.write(
                    f"  {permissao.content_type.app_label}.{permissao.codename}"
                )
