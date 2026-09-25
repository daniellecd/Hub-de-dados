"""Publicação da Bronze.

Lê conforme o contrato, mantém tudo como texto e acrescenta a linhagem
mínima. Só separa o que o parser não representa no layout (linha com
número de campos diferente), sem bloquear as demais, até a tolerância
declarada. Não aplica limpeza semântica, domínio nem regra.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import unquote

from pyspark import StorageLevel
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from hub import decisoes
from hub import vocabulario as v
from hub.decisoes import Parte
from hub.erros import exigir
from hub.execucao import RegistroExecucao
from hub.plano import COLUNA_MALFORMADA, PlanoBronze
from hub.spark import publicacao, quarentena

COLUNA_PARTE = "_hub_parte"


def coluna_parte(pasta_aquisicao: str) -> Column:
    """Identificador da parte: caminho físico relativo à pasta da aquisição."""
    padrao = "/" + re.escape(pasta_aquisicao.strip("/")) + "/(.+)$"
    return F.regexp_extract(F.col("_metadata.file_path"), padrao, 1)


def ler(
    spark: SparkSession,
    plano: PlanoBronze,
    partes: Sequence[Parte],
    pasta: str,
) -> DataFrame:
    """Lê as partes como texto, marcando linhas malformadas."""
    campos = [
        StructField(nome, StringType(), True) for nome in plano.colunas_origem
    ]
    campos.append(StructField(COLUNA_MALFORMADA, StringType(), True))
    return (
        spark.read.format("csv")
        .schema(StructType(campos))
        .options(**plano.opcoes_csv)
        .load([parte.caminho for parte in partes])
        .withColumn(COLUNA_PARTE, coluna_parte(pasta))
    )


def contar_linhas_fisicas(
    spark: SparkSession, partes: Sequence[Parte], pasta: str
) -> dict[str, int]:
    """Linhas não vazias por parte, contadas sem o parser CSV."""
    linhas = (
        spark.read.text([parte.caminho for parte in partes])
        .select(coluna_parte(pasta).alias("parte"), "value")
        .where(F.length("value") > 0)
        .groupBy("parte")
        .count()
        .collect()
    )
    return {unquote(linha["parte"]): linha["count"] for linha in linhas}


def _contagens(df: DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    """Registros lidos e malformados por parte."""
    linhas = (
        df.groupBy(COLUNA_PARTE)
        .agg(
            F.count(F.lit(1)).alias("lidas"),
            F.sum(F.col(COLUNA_MALFORMADA).isNotNull().cast("int")).alias(
                "malformadas"
            ),
        )
        .collect()
    )
    lidas = {unquote(linha[COLUNA_PARTE]): linha["lidas"] for linha in linhas}
    malformadas = {
        unquote(linha[COLUNA_PARTE]): linha["malformadas"] or 0
        for linha in linhas
    }
    return lidas, malformadas


def _saida(
    df: DataFrame, plano: PlanoBronze, competencia: str, id_execucao: str
) -> DataFrame:
    """Linhas válidas no layout do contrato, com a linhagem mínima."""
    colunas = [
        (
            F.col(nome)
            if nome in plano.colunas_origem
            else F.lit(None).cast("string").alias(nome)
        )
        for nome in plano.colunas_saida
    ]
    colunas += [
        F.lit(competencia).alias(v.COLUNA_COMPETENCIA),
        F.col(COLUNA_PARTE).alias(v.COLUNA_ARQUIVO),
        F.lit(id_execucao).alias(v.COLUNA_EXECUCAO),
    ]
    return df.where(F.col(COLUNA_MALFORMADA).isNull()).select(*colunas)


def _retirados(
    df: DataFrame,
    plano: PlanoBronze,
    contexto: quarentena.ContextoQuarentena,
) -> DataFrame:
    """Linhas malformadas no formato da quarentena, com a linha original."""
    original = F.col(COLUNA_MALFORMADA)
    motivo = F.struct(
        F.lit(v.LINHA_MALFORMADA).alias("classe"),
        F.lit(None).cast("string").alias("regra"),
        F.lit(None).cast("string").alias("coluna"),
        F.substring(original, 1, 200).alias("valor"),
        F.lit(plano.acao_malformada).alias("acao"),
        F.lit(v.DIMENSAO_POR_CLASSE[v.LINHA_MALFORMADA]).alias("dimensao"),
    )
    return quarentena.montar(
        df.where(original.isNotNull()),
        contexto=contexto,
        registro=original,
        hash_registro=F.sha2(original, 256),
        motivos=F.to_json(F.array(motivo)),
        chave=F.lit(None).cast("string"),
        grupo=F.lit(v.LINHA_MALFORMADA),
        arquivo=F.col(COLUNA_PARTE),
    )


def _verificar_leitura(
    plano: PlanoBronze,
    registro: RegistroExecucao,
    partes: Sequence[str],
    fisicas: dict[str, int],
    lidas: dict[str, int],
    malformadas: dict[str, int],
    total_declarado: int | None,
) -> list[str]:
    """Reconciliação antes da escrita e limites estruturais."""
    validas = {p: n - malformadas.get(p, 0) for p, n in lidas.items()}
    total_lidas = sum(lidas.values())
    total_malformadas = sum(malformadas.values())
    problemas = decisoes.verificar_partes_lidas(
        partes, fisicas, lidas, validas, plano.cabecalho
    )
    problemas += decisoes.verificar_tolerancia(
        total_malformadas, total_lidas, plano.tolerancia
    )
    if total_declarado is not None:
        registro.detalhes["total_declarado"] = total_declarado
        problemas += decisoes.verificar_total_declarado(
            total_declarado, total_lidas
        )
    if total_malformadas and plano.acao_malformada == v.BLOQUEIA_PUBLICACAO:
        problemas.append(
            f"{total_malformadas} linhas malformadas com ação "
            f"{v.BLOQUEIA_PUBLICACAO}"
        )
    return problemas


def publicar(
    spark: SparkSession,
    plano: PlanoBronze,
    destino: publicacao.Destino,
    registro: RegistroExecucao,
    contexto: quarentena.ContextoQuarentena,
    partes: Sequence[Parte],
    pasta: str,
    total_declarado: int | None,
) -> None:
    """Executa a Bronze de ponta a ponta, preenchendo o registro."""
    df = ler(spark, plano, partes, pasta).persist(StorageLevel.MEMORY_AND_DISK)
    try:
        nomes = [parte.parte for parte in partes]
        lidas, malformadas = _contagens(df)
        fisicas = contar_linhas_fisicas(spark, partes, pasta)
        registro.linhas_origem = decisoes.linhas_origem(
            fisicas, nomes, plano.cabecalho
        )
        registro.detalhes["partes"] = {
            parte: {
                "fisicas": fisicas.get(parte, 0),
                "lidas": lidas.get(parte, 0),
                "malformadas": malformadas.get(parte, 0),
            }
            for parte in sorted(set(nomes) | set(lidas) | set(fisicas))
        }
        exigir(
            _verificar_leitura(
                plano,
                registro,
                nomes,
                fisicas,
                lidas,
                malformadas,
                total_declarado,
            )
        )
        total_malformadas = sum(malformadas.values())
        if total_malformadas and plano.acao_malformada in v.ACOES_QUE_ALERTAM:
            registro.alertar(
                f"{total_malformadas} linhas malformadas na quarentena"
            )
        publicacao.publicar(
            spark,
            destino,
            registro,
            saida=_saida(
                df, plano, contexto.competencia, registro.id_execucao
            ),
            publicadas_esperadas=sum(lidas.values()) - total_malformadas,
            retirados=_retirados(df, plano, contexto),
            quarentena_esperada=total_malformadas,
        )
    finally:
        df.unpersist()
