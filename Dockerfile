FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app/

COPY entrypoint.sh /entrypoint.sh
COPY scheduler.sh /scheduler.sh
# `sed` remove o CR: os arquivos são editados no Windows e um `\r` no fim do
# shebang faz o Linux procurar o interpretador "/bin/sh\r", que não existe —
# o container morre com "exec format error" antes de rodar qualquer linha.
RUN sed -i 's/\r$//' /entrypoint.sh /scheduler.sh \
    && chmod +x /entrypoint.sh /scheduler.sh

# Prova, na hora do build, que a aplicação sobe com o que está no
# requirements.txt — e só com isso.
#
# Existe porque essa falha já aconteceu: `requests` era usado pelo cliente do
# Graph mas nunca entrou no requirements. Nos testes passava, porque o venv de
# desenvolvimento tinha o pacote instalado por outro caminho; no container o
# import quebrava e derrubava as views inteiras. Agora uma dependência
# esquecida falha o `docker compose build`, não o deploy.
#
# `check` não abre conexão com o banco, então roda sem serviço nenhum de pé.
RUN python manage.py check

ENTRYPOINT ["/entrypoint.sh"]