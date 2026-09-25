"""Escrita reconciliada de um snapshot, comum à Bronze e à Silver.

Ordem: confere o schema, grava a quarentena (se houver), sobrescreve o
snapshot, reconcilia com medidas tomadas depois da escrita e, em
divergência, restaura a versão anterior antes de abortar.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession

from hub import decisoes
from hub.erros import exigir
from hub.execucao import RegistroExecucao
from hub.spark import delta, quarentena


@dataclass(frozen=True)
class Destino:
    """Tabela de destino e o que o contrato espera dela."""

    tabela: str
    schema_fisico: tuple[tuple[str, str], ...]
    comentario_tabela: str
    comentarios_colunas: dict[str, str]
    tabela_quarentena: str
    identificador: str
    versao_contrato: int
    versao_vigente: int | None


def sobrescrever_schema(spark: SparkSession, destino: Destino) -> bool:
    """Confere a mudança de schema e indica se ela deve ser aplicada.

    Raises:
        BloqueioPublicacao: mudança sem nova versão de contrato.
    """
    if not delta.tabela_existe(spark, destino.tabela):
        return False
    diferenca = decisoes.diferenca_schema(
        delta.schema_fisico(spark, destino.tabela), destino.schema_fisico
    )
    exigir(
        decisoes.verificar_mudanca_schema(
            diferenca, destino.versao_contrato, destino.versao_vigente
        )
    )
    return not diferenca.vazia


def publicar(
    spark: SparkSession,
    destino: Destino,
    registro: RegistroExecucao,
    saida: DataFrame,
    publicadas_esperadas: int,
    retirados: DataFrame,
    quarentena_esperada: int,
) -> None:
    """Grava quarentena e snapshot e reconcilia depois da escrita.

    Pré-condição: ``registro.linhas_origem`` já medido de forma
    independente do parser.

    Raises:
        BloqueioPublicacao: schema sem nova versão ou reconciliação
            divergente (neste caso, após restaurar o snapshot anterior).
    """
    aplicar_schema = sobrescrever_schema(spark, destino)
    gravadas = 0
    if quarentena_esperada:
        gravadas = quarentena.gravar(
            spark, destino.tabela_quarentena, retirados, destino.identificador
        )
    escrita = delta.publicar_snapshot(
        spark, saida, destino.tabela, aplicar_schema
    )
    registro.versao_delta = escrita.versao
    registro.linhas_publicadas = escrita.linhas
    registro.linhas_quarentena = gravadas
    problemas = decisoes.verificar_reconciliacao(
        registro.linhas_origem, escrita.linhas, gravadas
    )
    if escrita.linhas != publicadas_esperadas:
        problemas.append(
            f"publicadas {escrita.linhas}; esperadas {publicadas_esperadas}"
        )
    if gravadas != quarentena_esperada:
        problemas.append(
            f"quarentena {gravadas}; esperada {quarentena_esperada}"
        )
    if problemas:
        delta.restaurar(spark, destino.tabela, escrita.versao_anterior)
        registro.detalhes["snapshot_restaurado"] = escrita.versao_anterior
        exigir(problemas)
    delta.aplicar_comentarios(
        spark,
        destino.tabela,
        destino.comentario_tabela,
        destino.comentarios_colunas,
    )
