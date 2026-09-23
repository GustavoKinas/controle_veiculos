FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev netcat-traditional cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app/

COPY entrypoint.sh /entrypoint.sh
COPY scheduler.sh /scheduler.sh
COPY docker/cron/sincronizar-funcionarios-erp /etc/cron.d/sincronizar-funcionarios-erp
COPY docker/cron/run-sincronizar-funcionarios-erp /usr/local/bin/run-sincronizar-funcionarios-erp
# `sed` remove o CR: os arquivos são editados no Windows e um `\r` no fim do
# shebang faz o Linux procurar o interpretador "/bin/sh\r", que não existe —
# o container morre com "exec format error" antes de rodar qualquer linha.
# O arquivo de cron também passa pelo sed: um `\r` sobrando quebra o parser
# do cron do mesmo jeito.
RUN sed -i 's/\r$//' /entrypoint.sh /scheduler.sh \
        /etc/cron.d/sincronizar-funcionarios-erp \
        /usr/local/bin/run-sincronizar-funcionarios-erp \
    && chmod +x /entrypoint.sh /scheduler.sh /usr/local/bin/run-sincronizar-funcionarios-erp \
    && chmod 0644 /etc/cron.d/sincronizar-funcionarios-erp

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