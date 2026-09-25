"""Configuração de sessão exigida pelo motor."""

from pyspark.sql import SparkSession

from hub.ambiente import Ambiente

CONFIGURACOES = {
    # Linha com número de campos diferente do layout é marcada como
    # malformada mesmo quando a consulta lê só parte das colunas.
    "spark.sql.csv.parser.columnPruning.enabled": "false",
    # Data inválida vira nulo (violação de conversão), não exceção.
    "spark.sql.legacy.timeParserPolicy": "CORRECTED",
}


def preparar(spark: SparkSession, ambiente: Ambiente) -> None:
    """Aplica as configurações de sessão e garante os schemas do ambiente."""
    for chave, valor in CONFIGURACOES.items():
        spark.conf.set(chave, valor)
    for schema in sorted(set(ambiente.schemas.values())):
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
