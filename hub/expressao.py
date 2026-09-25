"""Validação das expressões SQL declaradas nas regras do contrato.

A expressão só é executada depois de aprovada aqui. Ela pode usar apenas:

- colunas listadas em ``colunas_referenciadas``;
- palavras e funções do vocabulário fechado (``hub.vocabulario``);
- literais numéricos e de texto entre aspas simples;
- operadores de comparação, aritméticos, parênteses e vírgula.

Comentário, ponto e vírgula, ponto (encadeamento), aspas duplas, crase e
qualquer identificador fora da lista reprovam a regra.
"""

import re
from collections.abc import Iterable

from hub.vocabulario import FUNCOES_EXPRESSAO, PALAVRAS_EXPRESSAO

_TOKEN = re.compile(
    r"""
      (?P<espaco>\s+)
    | (?P<texto>'(?:[^']|'')*')
    | (?P<numero>\d+(?:\.\d+)?)
    | (?P<palavra>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<operador><=|>=|<>|!=|=|<|>|\+|-|\*|/|%|\(|\)|,)
    """,
    re.VERBOSE,
)
_TEXTO_LITERAL = re.compile(r"'(?:[^']|'')*'")
_MARCADORES_PROIBIDOS = ("--", "/*", "*/", ";")


def tokenizar(expressao: str) -> list[tuple[str, str]]:
    """Divide a expressão em tokens ``(tipo, valor)``, sem espaços.

    Raises:
        ValueError: se houver caractere fora do vocabulário léxico.
    """
    tokens = []
    posicao = 0
    while posicao < len(expressao):
        encontrado = _TOKEN.match(expressao, posicao)
        if encontrado is None:
            caractere = expressao[posicao]
            raise ValueError(
                f"caractere não permitido na posição {posicao}: "
                f"{caractere!r}"
            )
        if encontrado.lastgroup != "espaco":
            tokens.append((encontrado.lastgroup, encontrado.group()))
        posicao = encontrado.end()
    return tokens


def _marcadores_proibidos(expressao: str) -> list[str]:
    """Procura comentário e separador de comando fora de literais."""
    sem_literais = _TEXTO_LITERAL.sub("''", expressao)
    return [
        f"marcador proibido: {marcador!r}"
        for marcador in _MARCADORES_PROIBIDOS
        if marcador in sem_literais
    ]


def _parenteses_balanceados(tokens: list[tuple[str, str]]) -> bool:
    """Confere se os parênteses abrem e fecham na ordem correta."""
    profundidade = 0
    for tipo, valor in tokens:
        if tipo != "operador":
            continue
        if valor == "(":
            profundidade += 1
        elif valor == ")":
            profundidade -= 1
            if profundidade < 0:
                return False
    return profundidade == 0


def identificadores_usados(tokens: list[tuple[str, str]]) -> list[str]:
    """Lista, em ordem, os identificadores que não são palavra nem função."""
    usados = []
    for indice, (tipo, valor) in enumerate(tokens):
        if tipo != "palavra" or valor.upper() in PALAVRAS_EXPRESSAO:
            continue
        seguinte = tokens[indice + 1][1] if indice + 1 < len(tokens) else ""
        if seguinte == "(":
            continue
        usados.append(valor)
    return usados


def _funcoes_nao_permitidas(tokens: list[tuple[str, str]]) -> list[str]:
    """Lista problemas de funções fora do vocabulário."""
    problemas = []
    for indice, (tipo, valor) in enumerate(tokens):
        if tipo != "palavra" or valor.upper() in PALAVRAS_EXPRESSAO:
            continue
        seguinte = tokens[indice + 1][1] if indice + 1 < len(tokens) else ""
        if seguinte == "(" and valor.lower() not in FUNCOES_EXPRESSAO:
            problemas.append(f"função não permitida: {valor}")
    return problemas


def validar_expressao(
    expressao: str,
    colunas_referenciadas: Iterable[str],
    colunas_existentes: Iterable[str],
) -> list[str]:
    """Valida uma expressão de regra antes de qualquer execução.

    Args:
        expressao: predicado SQL declarado no contrato.
        colunas_referenciadas: colunas que a regra declara usar.
        colunas_existentes: colunas de saída disponíveis na entidade.

    Returns:
        Lista de problemas; vazia quando a expressão é aceita.
    """
    if not isinstance(expressao, str) or not expressao.strip():
        return ["expressão vazia"]
    referenciadas = list(colunas_referenciadas)
    existentes = set(colunas_existentes)
    problemas = _marcadores_proibidos(expressao)
    try:
        tokens = tokenizar(expressao)
    except ValueError as erro:
        return problemas + [str(erro)]
    if not _parenteses_balanceados(tokens):
        problemas.append("parênteses desbalanceados")
    problemas.extend(_funcoes_nao_permitidas(tokens))
    usados = identificadores_usados(tokens)
    for nome in dict.fromkeys(usados):
        if nome not in referenciadas:
            problemas.append(
                f"identificador fora de colunas_referenciadas: {nome}"
            )
    for nome in referenciadas:
        if nome not in existentes:
            problemas.append(f"coluna referenciada inexistente: {nome}")
        if nome not in usados:
            problemas.append(f"coluna referenciada e não usada: {nome}")
    return problemas
