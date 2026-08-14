"""
Geração dos relatórios de fechamento em CSV.

Mantido fora das views pelo mesmo motivo de services.py: reuso (link direto
após concluir o fechamento e botão na listagem) e testabilidade isolada.

Dois arquivos, não um
---------------------
São **dois relatórios separados**, cada um com seu botão:

- `exportar_rateio_csv`  — o rateio por centro de custo (o que vai ao ERP);
- `exportar_viagens_csv` — o detalhamento das viagens do fechamento.

Antes eram duas abas de um `.xlsx` e, na primeira conversão, dois blocos
empilhados no mesmo CSV. Empilhar não serve para importação: o arquivo
deixava de ser uma tabela e passava a ter títulos de seção e linhas em branco
no meio, que o ERP leria como dados.

Cada arquivo é uma tabela e nada mais: **uma linha de cabeçalho e linhas de
dado**, sem título, sem linha em branco, sem totais. Toda coluna carrega um
único tipo de informação, em todas as linhas.

Por que o formato é o que é
---------------------------
O arquivo é lido pelo ERP e, eventualmente, conferido no Excel em português.
Três escolhas decidem se ele abre legível:

- **`;` como separador.** No Excel pt-BR a vírgula é separador decimal, então
  o separador de lista é o ponto e vírgula. Com `,` a planilha inteira cai
  numa coluna só.
- **UTF-8 com BOM (`utf-8-sig`).** Sem o BOM, o Excel assume a codificação
  ANSI do sistema e "Descrição" vira "DescriÃ§Ã£o". O BOM é o que faz o
  Excel reconhecer UTF-8 — e é ignorado por qualquer leitor decente.
- **Decimal com vírgula.** `33.33` com separador `;` seria lido como texto,
  e a coluna não somaria.

Também escrevemos `\\r\\n` no fim das linhas, como manda a RFC 4180.
"""

import csv
import io
from decimal import Decimal

from django.http import HttpResponse

from .models import Fechamento

# O Excel pt-BR usa ponto e vírgula como separador de lista.
SEPARADOR = ";"

# As datas do período viajam em coluna, e não num título no topo do arquivo:
# é o que mantém cada linha auto-suficiente para a importação, sem depender
# de contexto que uma tabela não sabe carregar.
CABECALHO_RATEIO = [
    "Data Inicio",
    "Data Fim",
    "Centro de Custo",
    "Descricao",
    "KM Percorrida",
    "Participacao (%)",
]
CABECALHO_VIAGENS = [
    "Data",
    "Colaborador",
    "Centro de Custo",
    "Veiculo",
    "KM Inicial",
    "KM Final",
    "KM Percorrida",
]


def _decimal_br(valor: Decimal | float) -> str:
    """Duas casas, vírgula decimal — o que o Excel pt-BR entende como número."""
    return f"{Decimal(valor):.2f}".replace(".", ",")


def _escritor(buffer: io.StringIO):
    # `lineterminator` explícito: o padrão do csv já é \r\n, mas deixá-lo
    # escrito evita que alguém "conserte" para \n sem saber que é a RFC.
    return csv.writer(buffer, delimiter=SEPARADOR, lineterminator="\r\n")


def montar_csv_rateio(fechamento: Fechamento) -> str:
    """
    Rateio por centro de custo: uma linha por centro, e nada além disso.

    **Sem linha de total.** Ela existia na versão em planilha, onde um humano
    lia o arquivo. Numa importação, "Total" na coluna Centro de Custo entra
    como se fosse mais um centro — o total é responsabilidade de quem soma a
    coluna, não do arquivo.
    """
    buffer = io.StringIO()
    escritor = _escritor(buffer)
    escritor.writerow(CABECALHO_RATEIO)

    rateios = fechamento.rateios.select_related("centro_custo").order_by(
        "-km_percorrida"
    )
    for rateio in rateios:
        escritor.writerow(
            [
                f"{fechamento.data_inicio:%d/%m/%Y}",
                f"{fechamento.data_fim:%d/%m/%Y}",
                rateio.centro_custo.codigo,
                rateio.centro_custo.descricao,
                rateio.km_percorrida,
                _decimal_br(rateio.percentual),
            ]
        )

    return buffer.getvalue()


def montar_csv_viagens(fechamento: Fechamento) -> str:
    """Detalhamento: uma linha por viagem incluída no fechamento."""
    buffer = io.StringIO()
    escritor = _escritor(buffer)
    escritor.writerow(CABECALHO_VIAGENS)

    viagens = fechamento.viagens.select_related(
        "funcionario", "centro_custo", "veiculo"
    ).order_by("data", "id")
    for viagem in viagens:
        escritor.writerow(
            [
                f"{viagem.data:%d/%m/%Y}",
                str(viagem.funcionario),
                viagem.centro_custo.codigo,
                viagem.veiculo.placa,
                viagem.km_inicial,
                viagem.km_final,
                viagem.km_percorrida,
            ]
        )

    return buffer.getvalue()


def _resposta_csv(conteudo: str, nome_arquivo: str) -> HttpResponse:
    """
    Embrulha o texto numa resposta de download.

    `utf-8-sig` acrescenta o BOM. Sem ele o Excel lê como ANSI e destrói os
    acentos — o charset declarado no cabeçalho não é consultado por ele.
    """
    response = HttpResponse(
        conteudo.encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response


def _sufixo(fechamento: Fechamento) -> str:
    return f"{fechamento.data_inicio:%Y%m%d}_{fechamento.data_fim:%Y%m%d}"


def exportar_rateio_csv(fechamento: Fechamento) -> HttpResponse:
    """Download do rateio por centro de custo — o arquivo que vai ao ERP."""
    return _resposta_csv(
        montar_csv_rateio(fechamento), f"rateio_{_sufixo(fechamento)}.csv"
    )


def exportar_viagens_csv(fechamento: Fechamento) -> HttpResponse:
    """Download do detalhamento das viagens do fechamento."""
    return _resposta_csv(
        montar_csv_viagens(fechamento), f"viagens_{_sufixo(fechamento)}.csv"
    )
