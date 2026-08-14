#!/bin/sh
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "Aguardando banco de dados em ${DB_HOST}:${DB_PORT}..."

while ! nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
done

echo "Banco de dados disponível."

# O `scheduler` compartilha esta imagem e este entrypoint, mas NÃO pode rodar
# a preparação: dois `migrate` simultâneos na subida disputam o lock de
# migração do Postgres, e o collectstatic escreveria no mesmo volume que o
# web está escrevendo. Quem prepara o ambiente é o serviço web, uma vez só.
if [ "${RUN_SETUP:-true}" = "true" ]; then
    echo "Aplicando migrations..."
    python manage.py migrate --noinput

    # Sem os grupos de acesso, um servidor recém-provisionado sobe com todas
    # as telas negando entrada — nem a portaria nem o financeiro têm
    # permissão. É idempotente: rodar a cada deploy só reaplica a política
    # descrita em colaboradores/permissoes.py.
    echo "Sincronizando perfis de acesso..."
    python manage.py configurar_perfis

    echo "Coletando estáticos..."
    python manage.py collectstatic --noinput
else
    echo "RUN_SETUP=false — pulando migrate/collectstatic."
fi

echo "Iniciando: $*"
exec "$@"
