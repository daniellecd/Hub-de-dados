"""Transformações e conversões do vocabulário fechado.

Somente funções nativas do Spark (sem UDF Python). Toda transformação
preserva nulo: valor nulo continua nulo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pyspark.sql import Column
from pyspark.sql import functions as F

from hub import vocabulario as v
from hub.contrato import Transformacao
from hub.plano import ColunaSilver


def _nulo() -> Column:
    """Literal nulo do tipo texto (criado sob demanda, com sessão ativa)."""
    return F.lit(None).cast("string")


def _aparar(coluna: Column, parametros: Mapping[str, Any]) -> Column:
    """Remove espaços nas extremidades."""
    return F.trim(coluna)


def _maiusculas(coluna: Column, parametros: Mapping[str, Any]) -> Column:
    """Converte para maiúsculas."""
    return F.upper(coluna)


def _somente_digitos(coluna: Column, parametros: Mapping[str, Any]) -> Column:
    """Remove todo caractere que não seja dígito."""
    return F.regexp_replace(coluna, r"[^0-9]", "")


def _vazio_como_nulo(coluna: Column, parametros: Mapping[str, Any]) -> Column:
    """Texto vazio passa a nulo."""
    return F.when(coluna == "", _nulo()).otherwise(coluna)


def _nulo_se(coluna: Column, parametros: Mapping[str, Any]) -> Column:
    """Valores sentinela declarados passam a nulo."""
    return F.when(coluna.isin(list(parametros["valores"])), _nulo()).otherwise(
        coluna
    )


def _preencher_esquerda(
    coluna: Column, parametros: Mapping[str, Any]
) -> Column:
    """Completa à esquerda até o tamanho; nunca trunca valor maior."""
    tamanho = parametros["tamanho"]
    preenchida = F.lpad(coluna, tamanho, parametros["caractere"])
    return F.when(F.length(coluna) < tamanho, preenchida).otherwise(coluna)


IMPLEMENTACOES = {
    "aparar": _aparar,
    "maiusculas": _maiusculas,
    "somente_digitos": _somente_digitos,
    "vazio_como_nulo": _vazio_como_nulo,
    "nulo_se": _nulo_se,
    "preencher_esquerda": _preencher_esquerda,
}


def aplicar(coluna: Column, transformacoes: Iterable[Transformacao]) -> Column:
    """Aplica as transformações na ordem declarada."""
    for transformacao in transformacoes:
        implementacao = IMPLEMENTACOES[transformacao.tipo]
        coluna = implementacao(coluna, transformacao.parametros)
    return coluna


def converter(nome_texto: str, coluna: ColunaSilver) -> Column:
    """Converte a coluna textual transformada para o tipo do contrato.

    Usa try_cast e try_to_timestamp: valor inválido vira nulo, com ou
    sem modo ANSI, e é tratado depois como violação de conversão.
    """
    referencia = f"`{nome_texto}`"
    if coluna.tipo == v.TEXTO:
        return F.col(nome_texto)
    if coluna.tipo == v.DATA:
        return F.expr(
            f"to_date(try_to_timestamp({referencia}, "
            f"'{coluna.padrao_data}'))"
        )
    if coluna.tipo == v.DECIMAL and coluna.separador_decimal != ".":
        referencia = (
            f"replace({referencia}, '{coluna.separador_decimal}', '.')"
        )
    return F.expr(f"try_cast({referencia} AS {coluna.tipo_fisico.upper()})")


def descrever(coluna: ColunaSilver) -> Column:
    """Descrição do código conforme o domínio literal (nulo se ausente)."""
    expressao = None
    for codigo, descricao in sorted(coluna.valores_dominio.items()):
        condicao = F.col(coluna.nome) == codigo
        if expressao is None:
            expressao = F.when(condicao, descricao)
        else:
            expressao = expressao.when(condicao, descricao)
    return expressao
