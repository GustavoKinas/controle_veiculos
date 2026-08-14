#!/bin/sh
#
# Laço de sincronização das reservas com o Outlook.
#
# Roda `sincronizar_reservas` a cada intervalo, indefinidamente. É o serviço
# `scheduler` do docker-compose (ver docs/PRE_CADASTRO_VIAGENS.md §8.2).
#
# Por que um laço com `sleep`, e não cron:
#   - o cron do container exigiria um segundo processo (cron + a aplicação),
#     e um container com dois processos precisa de supervisor;
#   - o cron não herda o ambiente do container sem gambiarra — as credenciais
#     do Graph vêm do `.env` via env_file;
#   - a saída do comando vai direto para o stdout do container, então
#     `docker compose logs scheduler` já é o histórico de execução.
#
# O `sleep` vem DEPOIS do comando, de propósito: o intervalo conta a partir do
# fim de uma rodada, não do início. Assim duas sincronizações nunca se
# sobrepõem, mesmo que a API da Microsoft demore mais que o intervalo.

set -u

INTERVALO="${SYNC_INTERVALO_SEGUNDOS:-900}"      # 900s = 15 minutos
DIAS="${SYNC_DIAS:-30}"                          # janela: hoje até +30 dias
ATRASO_INICIAL="${SYNC_ATRASO_INICIAL_SEGUNDOS:-30}"

echo "[scheduler] intervalo=${INTERVALO}s janela=${DIAS}d"

# O web aplica as migrations na subida. Sem esta espera, a primeira rodada
# pegaria o banco ainda sem tabelas e só tentaria de novo 15 minutos depois.
echo "[scheduler] aguardando ${ATRASO_INICIAL}s pela preparação do banco..."
sleep "$ATRASO_INICIAL"

while true; do
    echo "[scheduler] $(date '+%Y-%m-%d %H:%M:%S') iniciando sincronização"

    # O comando sai com código != 0 quando alguma caixa de recurso falha.
    # Isso NÃO pode derrubar o laço: uma caixa fora do ar é problema
    # transitório, e a rodada seguinte tende a resolver. Registramos e
    # seguimos — o `docker compose logs` guarda o histórico.
    #
    # O código é capturado numa variável em vez de lido com `$?` mais adiante:
    # qualquer comando entre um e outro sobrescreveria o valor.
    codigo=0
    python manage.py sincronizar_reservas --dias "$DIAS" || codigo=$?

    if [ "$codigo" -eq 0 ]; then
        echo "[scheduler] sincronização concluída"
    else
        echo "[scheduler] AVISO: sincronização terminou com código ${codigo}"
    fi

    echo "[scheduler] dormindo ${INTERVALO}s"
    sleep "$INTERVALO"
done
