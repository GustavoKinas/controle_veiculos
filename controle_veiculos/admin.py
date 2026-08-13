"""
Site do /admin com a porta fechada para os perfis operacionais.

O portão padrão do Django para o /admin é `is_staff`. Ele resolve o caso
normal, mas depende de ninguém marcar a caixinha por engano — e a exigência
aqui é que a portaria não entre **sob nenhuma hipótese**. Uma caixa de
seleção no próprio /admin não é garantia suficiente para isso.

Então a checagem passa a ser dupla: além de `is_staff`, quem pertence a um
perfil operacional (Portaria, Financeiro) é recusado mesmo com a flag ligada.
Para dar acesso a alguém, tire a pessoa do grupo operacional — não marque
`is_staff` por cima.

Instalado via `AdminConfig.default_site` (settings.INSTALLED_APPS), o que faz
deste o `django.contrib.admin.site` do projeto: os `admin.py` de cada app
continuam registrando com `@admin.register` sem saber que a troca aconteceu.
"""

from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig

from colaboradores.permissoes import PERFIS_SEM_ADMIN


class ControleVeiculosAdminSite(AdminSite):
    site_header = "Controle de Veículos — Administração"
    site_title = "Controle de Veículos"
    index_title = "Administração do sistema"

    def has_permission(self, request) -> bool:
        """
        `is_staff` **e** não pertencer a um perfil operacional.

        Vale para toda a árvore do /admin, inclusive a tela de login: um
        usuário da portaria que digite a senha certa em /admin/login/ recebe
        de volta o próprio formulário, sem sessão de admin.
        """
        if not super().has_permission(request):
            return False

        return not request.user.groups.filter(name__in=PERFIS_SEM_ADMIN).exists()


class ControleVeiculosAdminConfig(AdminConfig):
    default_site = "controle_veiculos.admin.ControleVeiculosAdminSite"
