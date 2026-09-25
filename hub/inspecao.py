"""Inspeção física sob demanda: na descoberta ou diante de mudança.

Não é etapa mensal. Lê apenas o início de cada parte, no driver, e
compara com o contrato: codificação, terminador de linha, separador
provável, cabeçalho, largura dos registros e amostras de valores. O
resultado é registrado como evidência (COMPATIVEL ou INCOMPATIVEL).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from hub import vocabulario as v
from hub.arquivos import decodificar, ler_inicio, registros_csv
from hub.contrato import Contrato
from hub.decisoes import verificar_cabecalho

CANDIDATOS_SEPARADOR = (";", ",", "|", "\t")
LIMITE_REGISTROS = 1000
AMOSTRAS_POR_COLUNA = 3
TAMANHO_AMOSTRA = 60
_BOM_UTF8 = b"\xef\xbb\xbf"


def terminador_linha(dados: bytes) -> str:
    """Classifica o terminador de linha predominante na amostra."""
    crlf = dados.count(b"\r\n")
    lf = dados.count(b"\n") - crlf
    if crlf and lf:
        return "misto"
    if crlf:
        return "CRLF"
    return "LF" if lf else "indefinido"


def separador_provavel(linhas: Iterable[str]) -> str | None:
    """Candidato presente em todas as linhas com a contagem mais estável.

    Heurística apenas informativa: conta ocorrências sem considerar aspas.
    """
    linhas = [linha for linha in linhas if linha][:50]
    melhor, melhor_nota = None, (0, 0)
    for candidato in CANDIDATOS_SEPARADOR:
        contagens = [linha.count(candidato) for linha in linhas]
        if not contagens or min(contagens) == 0:
            continue
        valor, frequencia = Counter(contagens).most_common(1)[0]
        nota = (frequencia, valor)
        if nota > melhor_nota:
            melhor, melhor_nota = candidato, nota
    return melhor


def _amostras(
    registros: list[list[str]], nomes: list[str]
) -> dict[str, list[str]]:
    """Até três valores distintos e não vazios por coluna."""
    amostras: dict[str, list[str]] = {nome: [] for nome in nomes}
    for registro in registros:
        if len(registro) != len(nomes):
            continue
        for nome, valor in zip(nomes, registro, strict=True):
            valores = amostras[nome]
            valor = valor[:TAMANHO_AMOSTRA]
            if valor and valor not in valores:
                if len(valores) < AMOSTRAS_POR_COLUNA:
                    valores.append(valor)
    return amostras


def inspecionar_parte(caminho: str, parte: str, contrato: Contrato) -> dict:
    """Inspeciona o início de uma parte contra o contrato.

    Args:
        caminho: caminho local do arquivo.
        parte: identificador da parte na aquisição.
        contrato: contrato da entidade.

    Returns:
        Relatório da parte, com a lista de problemas e o veredito.
    """
    leitura = contrato.leitura
    dados = ler_inicio(caminho)
    texto, decodificou = decodificar(dados, leitura.codificacao)
    _, utf8 = decodificar(dados, "utf-8")
    registros = registros_csv(texto, leitura)[: LIMITE_REGISTROS + 1]
    problemas = []
    if not decodificou:
        problemas.append(f"amostra não decodifica como {leitura.codificacao}")
    nao_ascii = any(byte > 127 for byte in dados)
    if leitura.codificacao != "utf-8" and utf8 and nao_ascii:
        problemas.append(
            "amostra com acentuação válida em UTF-8; a codificação "
            f"declarada ({leitura.codificacao}) corromperia os acentos"
        )
    provavel = separador_provavel(texto.splitlines())
    if provavel is not None and provavel != leitura.separador:
        problemas.append(
            f"separador provável {provavel!r} difere do declarado "
            f"{leitura.separador!r}"
        )
    origem = contrato.colunas_origem
    cabecalho = None
    if leitura.cabecalho and registros:
        cabecalho = registros.pop(0)
        esperado = [(c.cabecalho, *c.aliases) for c in origem]
        problemas.extend(verificar_cabecalho(cabecalho, esperado))
    if not registros:
        problemas.append("amostra sem registros de dados")
    larguras = Counter(len(registro) for registro in registros)
    divergentes = sum(
        quantidade
        for largura, quantidade in larguras.items()
        if largura != len(origem)
    )
    if divergentes:
        problemas.append(
            f"{divergentes} de {len(registros)} registros da amostra com "
            f"largura diferente de {len(origem)}"
        )
    return {
        "parte": parte,
        "bytes_lidos": len(dados),
        "codificacao_declarada": leitura.codificacao,
        "decodifica_declarada": decodificou,
        "decodifica_utf8": utf8,
        "bom_utf8": dados.startswith(_BOM_UTF8),
        "terminador": terminador_linha(dados),
        "separador_declarado": leitura.separador,
        "separador_provavel": provavel,
        "cabecalho_encontrado": cabecalho,
        "registros_amostra": len(registros),
        "largura_esperada": len(origem),
        "larguras": {str(k): n for k, n in sorted(larguras.items())},
        "amostras": _amostras(registros, [c.nome for c in origem]),
        "problemas": problemas,
        "veredito": v.INCOMPATIVEL if problemas else v.COMPATIVEL,
    }


def inspecionar(partes: Iterable[tuple[str, str]], contrato: Contrato) -> dict:
    """Inspeciona todas as partes selecionadas para a entidade.

    Args:
        partes: pares (identificador da parte, caminho local).
        contrato: contrato da entidade.

    Returns:
        Relatório com o veredito geral e o relatório de cada parte.
    """
    relatorios = [
        inspecionar_parte(caminho, parte, contrato)
        for parte, caminho in partes
    ]
    compativel = bool(relatorios) and all(
        relatorio["veredito"] == v.COMPATIVEL for relatorio in relatorios
    )
    return {
        "veredito": v.COMPATIVEL if compativel else v.INCOMPATIVEL,
        "partes": relatorios,
    }
