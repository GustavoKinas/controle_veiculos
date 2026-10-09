"""
Configurações do projeto controle_veiculos.

Sistema de controle de viagens e rateio de custos de combustível por
Centro de Custo. Consulte DEVELOPMENT.md na raiz do repositório para o
histórico de decisões de arquitetura.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "chave-insegura-local")

SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False") == "True"
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False") == "True"
SESSION_COOKIE_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

TRUST_PROXY_SSL_HEADER = os.getenv("TRUST_PROXY_SSL_HEADER", "False") == "True"
if TRUST_PROXY_SSL_HEADER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# Application definition

INSTALLED_APPS = [
    # Troca o AdminSite padrão pelo nosso, que também recusa quem pertence a
    # um perfil operacional (ver controle_veiculos/admin.py). Substitui
    # "django.contrib.admin" — as duas entradas não podem coexistir.
    "controle_veiculos.admin.ControleVeiculosAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "colaboradores",
    "viagens",
]

# Funcionário é o nosso model de usuário (estende AbstractUser).
# IMPORTANTE: definido antes da primeira migração; trocar depois exige
# recriar o banco.
AUTH_USER_MODEL = "colaboradores.Funcionario"
AUTHENTICATION_BACKENDS = ["colaboradores.auth_backends.HybridAuthBackend"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "controle_veiculos.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # base.html e login.html ficam no pacote de configuração (templates
        # compartilhados). Os templates de cada app são achados via APP_DIRS.
        "DIRS": [BASE_DIR / "controle_veiculos" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "controle_veiculos.wsgi.application"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "auth_audit": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "auth_audit_console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "auth_audit",
        },
    },
    "loggers": {
        "colaboradores.auth": {
            "handlers": ["auth_audit_console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
# A conexão vem 100% da variável de ambiente DATABASE_URL (PostgreSQL).
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL"),
        conn_max_age=600,
    )
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "pt-br"

TIME_ZONE = "America/Sao_Paulo"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
# collectstatic escreve aqui; o Nginx (docker-compose) serve este diretório.
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "controle_veiculos" / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
# Destino único que reparte por perfil: a portaria vai para a consulta de
# viagens, o financeiro para o fechamento.
LOGIN_REDIRECT_URL = "pagina_inicial"
LOGOUT_REDIRECT_URL = "login"
