"""Quarentena: tabela única para todas as entidades.

A tabela é criada apenas quando há registros. Cada linha preserva o
registro (linha original na Bronze, JSON transformado na Silver), a
chave, o grupo do problema, todos os motivos e a identificação da
publicação. A quarentena nunca altera nem exclui registro da Bronze.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from hub.execucao import COLUNA_PARTICAO, COLUNAS_QUARENTENA
from hub.spark import delta


@dataclass(frozen=True)
class ContextoQuarentena:
    """Identificação da publicação que retirou os registros.

    ``hash_decisao`` é o hash da seção executada pela camada
    (hash_leitura na Bronze, hash_contrato na Silver).
    """

    identificador: str
    camada: str
    fonte: str
    base: str
    entidade: str
    competencia: str
    publication_fingerprint: str
    versao_contrato: int
    hash_leitura: str
    hash_contrato: str
    hash_decisao: str
    id_execucao: str


def montar(
    df: DataFrame,
    contexto: ContextoQuarentena,
    registro: Column,
    hash_registro: Column,
    motivos: Column,
    chave: Column,
    grupo: Column,
    arquivo: Column,
) -> DataFrame:
    """Padroniza os registros retirados no formato da quarentena.

    O identificador é determinístico (publicação, seção executada,
    conteúdo e índice de ocorrência): reexecutar a mesma publicação sob o
    mesmo contrato não duplica evidência. Duplicatas idênticas recebem
    índices distintos, sem eleger vencedora.
    """
    base = df.select(
        registro.alias("registro"),
        hash_registro.alias("_hash_registro"),
        motivos.alias("motivos"),
        chave.alias("chave"),
        grupo.alias("grupo_problema"),
        arquivo.alias("arquivo_origem"),
    )
    janela = Window.partitionBy("_hash_registro").orderBy("_hash_registro")
    base = base.withColumn("ocorrencia", F.row_number().over(janela))
    identificacao = F.sha2(
        F.concat_ws(
            "|",
            F.lit(contexto.identificador),
            F.lit(contexto.camada),
            F.lit(contexto.competencia),
            F.lit(contexto.publication_fingerprint),
            F.lit(contexto.hash_decisao),
            F.col("_hash_registro"),
            F.col("ocorrencia").cast("string"),
        ),
        256,
    )
    valores = {
        "id_quarentena": identificacao,
        "identificador": F.lit(contexto.identificador),
        "camada": F.lit(contexto.camada),
        "fonte": F.lit(contexto.fonte),
        "base": F.lit(contexto.base),
        "entidade": F.lit(contexto.entidade),
        "competencia": F.lit(contexto.competencia),
        "publication_fingerprint": F.lit(contexto.publication_fingerprint),
        "versao_contrato": F.lit(contexto.versao_contrato).cast("int"),
        "hash_leitura": F.lit(contexto.hash_leitura),
        "hash_contrato": F.lit(contexto.hash_contrato),
        "id_execucao": F.lit(contexto.id_execucao),
        "chave": F.col("chave"),
        "grupo_problema": F.col("grupo_problema"),
        "motivos": F.col("motivos"),
        "registro": F.col("registro"),
        "arquivo_origem": F.col("arquivo_origem"),
        "ocorrencia": F.col("ocorrencia").cast("int"),
        "registrado_em": F.current_timestamp(),
    }
    return base.select(
        *[valores[nome].alias(nome) for nome, _ in COLUNAS_QUARENTENA]
    )


def gravar(
    spark: SparkSession, tabela: str, registros: DataFrame, identificador: str
) -> int:
    """Insere os registros novos e confere a presença de todos.

    Returns:
        Quantidade de registros desta publicação presentes na tabela,
        medida por leitura após a escrita.
    """
    if not delta.tabela_existe(spark, tabela):
        delta.criar_tabela(spark, tabela, COLUNAS_QUARENTENA, COLUNA_PARTICAO)
    literal = delta.literal_sql(identificador)
    condicao = (
        f"t.identificador = '{literal}' "
        "AND t.id_quarentena = s.id_quarentena"
    )
    delta.mesclar(spark, tabela, registros, condicao)
    return (
        spark.table(tabela)
        .where(F.col("identificador") == identificador)
        .join(registros.select("id_quarentena"), "id_quarentena", "left_semi")
        .count()
    )
