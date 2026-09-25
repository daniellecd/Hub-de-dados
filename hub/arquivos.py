"""Leitura de arquivos no driver, em Python puro.

Usada para conferir cabeçalho, ler o total declarado pela fonte e
inspecionar amostras. Lê apenas o início de cada arquivo.
"""

from __future__ import annotations

import csv
import io

from hub import vocabulario as v
from hub.contrato import Contrato, Leitura
from hub.decisoes import verificar_cabecalho

LIMITE_AMOSTRA = 1 << 20


def argumentos_csv(leitura: Leitura) -> dict:
    """Dialeto do contrato no formato do módulo csv."""
    dobra_aspas = leitura.escape == leitura.aspas
    return {
        "delimiter": leitura.separador,
        "quotechar": leitura.aspas,
        "doublequote": dobra_aspas,
        "escapechar": None if dobra_aspas else leitura.escape,
        "strict": False,
    }


def ler_inicio(caminho: str, limite: int = LIMITE_AMOSTRA) -> bytes:
    """Lê até ``limite`` bytes, cortando na última quebra de linha."""
    with open(caminho, "rb") as arquivo:
        dados = arquivo.read(limite + 1)
    if len(dados) > limite:
        corte = dados.rfind(b"\n", 0, limite)
        dados = dados[: corte + 1] if corte >= 0 else dados[:limite]
    return dados


def decodificar(dados: bytes, codificacao: str) -> tuple[str, bool]:
    """Decodifica com o codec do contrato e indica se houve erro."""
    codec = v.CODIFICACOES[codificacao].python
    try:
        return dados.decode(codec), True
    except UnicodeDecodeError:
        return dados.decode(codec, errors="replace"), False


def registros_csv(texto: str, leitura: Leitura) -> list[list[str]]:
    """Registros do texto conforme o dialeto, sem linhas vazias."""
    leitor = csv.reader(
        io.StringIO(texto, newline=""), **argumentos_csv(leitura)
    )
    return [registro for registro in leitor if registro]


def ler_cabecalho(caminho: str, leitura: Leitura) -> list[str]:
    """Nomes da primeira linha do arquivo."""
    texto, _ = decodificar(ler_inicio(caminho, 1 << 16), leitura.codificacao)
    registros = registros_csv(texto, leitura)
    return registros[0] if registros else []


def ler_total_declarado(
    caminho: str, contrato_total: Contrato, coluna: str
) -> tuple[int | None, list[str]]:
    """Lê o total de registros publicado pela fonte.

    Args:
        caminho: caminho local do arquivo de totais.
        contrato_total: contrato da entidade de totais.
        coluna: coluna do contrato de totais com o valor desejado.

    Returns:
        Par (total, problemas); total é None quando há problemas.
    """
    leitura = contrato_total.leitura
    texto, decodificou = decodificar(ler_inicio(caminho), leitura.codificacao)
    if not decodificou:
        return None, [f"arquivo de totais não decodifica: {caminho}"]
    registros = registros_csv(texto, leitura)
    origem = contrato_total.colunas_origem
    if leitura.cabecalho:
        esperado = [(c.cabecalho, *c.aliases) for c in origem]
        primeiro = registros[0] if registros else []
        problemas = verificar_cabecalho(primeiro, esperado)
        if problemas:
            return None, [f"arquivo de totais: {p}" for p in problemas]
        registros = registros[1:]
    if len(registros) != 1:
        return None, [f"arquivo de totais com {len(registros)} registros"]
    indice = [c.nome for c in origem].index(coluna)
    registro = registros[0]
    valor = registro[indice].strip() if indice < len(registro) else ""
    if not valor.isdigit():
        return None, [f"total declarado não numérico: {valor!r}"]
    return int(valor), []
