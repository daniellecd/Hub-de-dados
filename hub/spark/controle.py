"""Registro operacional: tabela única ``controle.execucoes``.

Cada tentativa é gravada ao iniciar (EM_EXECUCAO) e ao terminar, com
qualquer status. A escrita é um MERGE por ``id_execucao``, idempotente.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from hub import vocabulario as v
from hub.ambiente import Ambiente
from hub.erros import BloqueioPublicacao
from hub.execucao import (
    COLUNA_PARTICAO,
    COLUNAS_EXECUCOES,
    TABELA_EXECUCOES,
    RegistroExecucao,
)
from hub.historico import Historico
from hub.spark import delta


def garantir_tabela(spark: SparkSession, ambiente: Ambiente) -> None:
    """Cria controle.execucoes, se ainda não existir."""
    delta.criar_tabela(
        spark,
        ambiente.tabela_controle(TABELA_EXECUCOES),
        COLUNAS_EXECUCOES,
        COLUNA_PARTICAO,
    )


def gravar(
    spark: SparkSession, ambiente: Ambiente, registro: RegistroExecucao
) -> None:
    """Insere ou atualiza a linha da execução."""
    origem = spark.createDataFrame(
        [registro.para_linha()], delta.estrutura(COLUNAS_EXECUCOES)
    )
    identificador = delta.literal_sql(registro.identificador)
    condicao = (
        f"t.identificador = '{identificador}' "
        "AND t.id_execucao = s.id_execucao"
    )
    delta.mesclar(
        spark,
        ambiente.tabela_controle(TABELA_EXECUCOES),
        origem,
        condicao,
        atualizar=[nome for nome, _ in COLUNAS_EXECUCOES],
    )


def ler_historico(
    spark: SparkSession, ambiente: Ambiente, identificador: str
) -> Historico:
    """Execuções registradas para o identificador neste ambiente."""
    linhas = (
        spark.table(ambiente.tabela_controle(TABELA_EXECUCOES))
        .where(F.col("identificador") == identificador)
        .collect()
    )
    return Historico(linha.asDict() for linha in linhas)


@contextmanager
def execucao(
    spark: SparkSession, ambiente: Ambiente, registro: RegistroExecucao
) -> Iterator[RegistroExecucao]:
    """Registra a tentativa no início e no fim, inclusive em falha.

    BloqueioPublicacao termina como BLOQUEADA; qualquer outra exceção,
    como FALHA. Em ambos os casos a exceção é propagada depois do registro.
    """
    gravar(spark, ambiente, registro)
    try:
        yield registro
    except BloqueioPublicacao as erro:
        registro.finalizar(v.BLOQUEADA, motivo=str(erro))
        raise
    except Exception as erro:
        registro.finalizar(v.FALHA, motivo=f"{type(erro).__name__}: {erro}")
        raise
    else:
        registro.finalizar(registro.status_sucesso())
    finally:
        gravar(spark, ambiente, registro)
