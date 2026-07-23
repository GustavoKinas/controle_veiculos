#!/bin/sh

echo "Aguardando banco de dados..."

while ! nc -z db 5432; do
    sleep 1
done

echo "Banco de dados disponível."

echo "Aplicando migrations..."
python manage.py migrate --noinput

echo "Coletando estáticos..."
python manage.py collectstatic --noinput

echo "Iniciando aplicação..."
exec "$@"