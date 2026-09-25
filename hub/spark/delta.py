"""Operações Delta Lake usadas pelo motor."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from hub.retentativa import com_retentativa

_TIPOS = {
    "STRING": StringType(),
    "INT": IntegerType(),
    "BIGINT": LongType(),
    "BOOLEAN": BooleanType(),
    "TIMESTAMP": TimestampType(),
}


@dataclass(frozen=True)
class Escrita:
    """Resultado da escrita de um snapshot."""

    versao_anterior: int | None
    versao: int
    linhas: int


def estrutura(colunas: Iterable[tuple[str, str]]) -> StructType:
    """StructType a partir de pares (nome, tipo SQL)."""
    return StructType(
        [StructField(nome, _TIPOS[tipo], True) for nome, tipo in colunas]
    )


def literal_sql(texto: str) -> str:
    """Escapa texto para uso entre aspas simples no Spark SQL."""
    return texto.replace("\\", "\\\\").replace("'", "\\'")


def tabela_existe(spark: SparkSession, tabela: str) -> bool:
    """Indica se a tabela existe no catálogo."""
    return spark.catalog.tableExists(tabela)


def versao_atual(spark: SparkSession, tabela: str) -> int:
    """Versão Delta mais recente da tabela."""
    ultima = DeltaTable.forName(spark, tabela).history(1)
    return ultima.select("version").first()[0]


def schema_fisico(spark: SparkSession, tabela: str) -> list[tuple[str, str]]:
    """Pares (coluna, tipo) do schema atual da tabela."""
    return [
        (campo.name, campo.dataType.simpleString())
        for campo in spark.table(tabela).schema.fields
    ]


def criar_tabela(
    spark: SparkSession,
    tabela: str,
    colunas: Iterable[tuple[str, str]],
    particao: str | None = None,
) -> None:
    """Cria a tabela Delta com schema explícito, se ainda não existir."""
    definicao = ", ".join(f"`{nome}` {tipo}" for nome, tipo in colunas)
    clausula = f" PARTITIONED BY (`{particao}`)" if particao else ""
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {tabela} ({definicao}) "
        f"USING DELTA{clausula}"
    )


def publicar_snapshot(
    spark: SparkSession, df: DataFrame, tabela: str, sobrescrever_schema: bool
) -> Escrita:
    """Substitui o conteúdo da tabela pelo DataFrame (snapshot vigente).

    As linhas escritas vêm da métrica do commit de escrita. Se outro commit
    vier logo depois (ex.: compactação automática) ou a métrica faltar, a
    contagem é feita na tabela após a escrita.
    """
    existia = tabela_existe(spark, tabela)
    anterior = versao_atual(spark, tabela) if existia else None
    escritor = df.write.format("delta").mode("overwrite")
    if sobrescrever_schema:
        escritor = escritor.option("overwriteSchema", "true")
    escritor.saveAsTable(tabela)
    commits = (
        DeltaTable.forName(spark, tabela)
        .history(5)
        .select("version", "operationMetrics")
        .collect()
    )
    novos = [c for c in commits if anterior is None or c["version"] > anterior]
    escritas = [
        c for c in novos if "numOutputRows" in (c["operationMetrics"] or {})
    ]
    if escritas:
        commit = max(escritas, key=lambda c: c["version"])
        return Escrita(
            anterior,
            commit["version"],
            int(commit["operationMetrics"]["numOutputRows"]),
        )
    versao = max(c["version"] for c in novos)
    return Escrita(anterior, versao, spark.table(tabela).count())


def restaurar(
    spark: SparkSession, tabela: str, versao_anterior: int | None
) -> None:
    """Desfaz a escrita: volta à versão anterior ou remove a tabela nova."""
    if versao_anterior is None:
        spark.sql(f"DROP TABLE IF EXISTS {tabela}")
    else:
        DeltaTable.forName(spark, tabela).restoreToVersion(versao_anterior)


def mesclar(
    spark: SparkSession,
    tabela: str,
    origem: DataFrame,
    condicao: str,
    atualizar: Iterable[str] = (),
) -> None:
    """MERGE com retentativa em conflito de concorrência.

    Linhas novas são inseridas; linhas existentes têm apenas as colunas
    em ``atualizar`` sobrescritas (nenhuma, se vazio).
    """
    colunas = tuple(atualizar)

    def operacao() -> None:
        fusao = (
            DeltaTable.forName(spark, tabela)
            .alias("t")
            .merge(origem.alias("s"), condicao)
        )
        if colunas:
            fusao = fusao.whenMatchedUpdate(
                set={coluna: f"s.{coluna}" for coluna in colunas}
            )
        fusao.whenNotMatchedInsertAll().execute()

    com_retentativa(operacao)


def aplicar_comentarios(
    spark: SparkSession,
    tabela: str,
    comentario_tabela: str,
    comentarios_colunas: dict[str, str],
) -> None:
    """Aplica comentários de tabela e coluna que divergem do contrato."""
    detalhe = DeltaTable.forName(spark, tabela).detail()
    atual = detalhe.select("description").first()[0] or ""
    if atual != comentario_tabela:
        spark.sql(
            f"COMMENT ON TABLE {tabela} IS "
            f"'{literal_sql(comentario_tabela)}'"
        )
    campos = {
        campo.name: campo.metadata.get("comment", "")
        for campo in spark.table(tabela).schema.fields
    }
    for coluna, comentario in comentarios_colunas.items():
        if coluna in campos and campos[coluna] != comentario:
            spark.sql(
                f"ALTER TABLE {tabela} ALTER COLUMN `{coluna}` "
                f"COMMENT '{literal_sql(comentario)}'"
            )
