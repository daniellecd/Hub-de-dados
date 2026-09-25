"""Diagnóstico dirigido de integridade referencial.

Fora do fluxo obrigatório: roda sob demanda e não bloqueia a entidade de
negócio. Para cada domínio por referência, conta valores sem
correspondência na tabela oficial. Se a referência não existe, o
relacionamento é marcado como REFERENCIA_AUSENTE.
"""

from __future__ import annotations

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from hub import vocabulario as v
from hub.ambiente import Ambiente
from hub.contrato import REFERENCIA, Contrato
from hub.erros import exigir
from hub.spark import delta

LIMITE_EXEMPLOS = 10


def referencias(
    spark: SparkSession, contrato: Contrato, ambiente: Ambiente
) -> list[dict]:
    """Confere cada coluna com domínio por referência.

    Raises:
        BloqueioPublicacao: se a própria tabela Silver não existir.
    """
    tabela = ambiente.tabela(v.SILVER, contrato.identificador)
    if not delta.tabela_existe(spark, tabela):
        exigir([f"tabela Silver inexistente: {tabela}"])
    itens = []
    for coluna in contrato.colunas:
        dominio = contrato.dominios.get(coluna.dominio or "")
        if dominio is None or dominio.tipo != REFERENCIA:
            continue
        alvo = ambiente.tabela(v.SILVER, dominio.tabela.identificador)
        item = {
            "coluna": coluna.nome,
            "dominio": dominio.nome,
            "referencia": alvo,
            "coluna_referenciada": dominio.coluna,
        }
        if not delta.tabela_existe(spark, alvo):
            item["resultado"] = v.REFERENCIA_AUSENTE
            itens.append(item)
            continue
        valores = (
            spark.table(tabela)
            .select(F.col(coluna.nome).alias("valor"))
            .where(F.col("valor").isNotNull())
            .distinct()
        )
        oficiais = (
            spark.table(alvo).select(F.col(dominio.coluna).alias("valor"))
        ).distinct()
        orfaos = valores.join(oficiais, "valor", "left_anti")
        item["orfaos_distintos"] = orfaos.count()
        item["exemplos"] = [
            linha["valor"]
            for linha in orfaos.orderBy("valor")
            .limit(LIMITE_EXEMPLOS)
            .collect()
        ]
        item["resultado"] = (
            v.CONFERIDA if item["orfaos_distintos"] == 0 else v.COM_ORFAOS
        )
        itens.append(item)
    return itens
