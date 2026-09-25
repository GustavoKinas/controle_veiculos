"""
WSGI config for controle_veiculos project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'controle_veiculos.settings')

from controle_veiculos.directory_config import get_directory_config
from colaboradores.auth_logging import log_directory_transport

directory_config = get_directory_config()
application = get_wsgi_application()
log_directory_transport(transport="LDAPS", tls_profile=directory_config.tls_profile)
