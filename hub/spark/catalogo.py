"""Sincronização do catálogo e dos comentários físicos.

A parte estrutural é atualizada a cada sincronização; a curatorial só é
escrita na inserção (A_CONFIRMAR) e depois preservada.
"""

from __future__ import annotations

from collections.abc import Sequence

from pyspark.sql import SparkSession

from hub import catalogo
from hub.ambiente import Ambiente
from hub.contrato import Contrato
from hub.plano import plano_bronze, plano_silver
from hub.spark import delta


def _tabelas_existentes(
    spark: SparkSession, contratos: Sequence[Contrato], ambiente: Ambiente
) -> set[str]:
    """Tabelas Bronze e Silver dos contratos que existem no ambiente."""
    existentes = set()
    for contrato in contratos:
        for plano in (
            plano_bronze(contrato, ambiente),
            plano_silver(contrato, ambiente),
        ):
            if delta.tabela_existe(spark, plano.tabela):
                existentes.add(plano.tabela)
    return existentes


def _aplicar_comentarios(
    spark: SparkSession,
    contratos: Sequence[Contrato],
    ambiente: Ambiente,
    existentes: set[str],
) -> None:
    """Comentários físicos de tabela e coluna derivados do contrato."""
    for contrato in contratos:
        for plano in (
            plano_bronze(contrato, ambiente),
            plano_silver(contrato, ambiente),
        ):
            if plano.tabela in existentes:
                delta.aplicar_comentarios(
                    spark,
                    plano.tabela,
                    plano.comentario_tabela,
                    dict(plano.comentarios_colunas),
                )


def sincronizar(
    spark: SparkSession, ambiente: Ambiente, contratos: Sequence[Contrato]
) -> dict[str, int]:
    """Atualiza as tabelas de catálogo e os comentários físicos.

    Returns:
        Quantidade de linhas estruturais por tabela de catálogo.
    """
    existentes = _tabelas_existentes(spark, contratos, ambiente)
    linhas = catalogo.linhas_catalogo(contratos, ambiente, existentes)
    for nome, registros in linhas.items():
        esquema = catalogo.ESQUEMAS[nome]
        tabela = ambiente.tabela_controle(nome)
        delta.criar_tabela(spark, tabela, esquema)
        origem = spark.createDataFrame(
            [tuple(r[coluna] for coluna, _ in esquema) for r in registros],
            delta.estrutura(esquema),
        )
        condicao = " AND ".join(
            f"t.{coluna} <=> s.{coluna}" for coluna in catalogo.CHAVES[nome]
        )
        delta.mesclar(
            spark,
            tabela,
            origem,
            condicao,
            atualizar=catalogo.colunas_estruturais(nome),
        )
    _aplicar_comentarios(spark, contratos, ambiente, existentes)
    return {nome: len(registros) for nome, registros in linhas.items()}
