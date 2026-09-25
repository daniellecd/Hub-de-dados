"""Publicação da Silver.

Aplica transformações, tipos, domínios literais, chave e regras
declarados. Cada violação carrega a ação declarada no contrato; o motor
não tem ação implícita. Linhas retiradas vão para a quarentena com
todos os motivos; BLOQUEIA_PUBLICACAO impede publicar qualquer linha.
"""

from __future__ import annotations

from functools import reduce
from operator import or_

from pyspark import StorageLevel
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from hub import decisoes
from hub import vocabulario as v
from hub.erros import exigir
from hub.execucao import RegistroExecucao
from hub.plano import ColunaSilver, PlanoSilver
from hub.spark import publicacao, quarentena, transformacoes

MOTIVOS = "_hub_motivos"
RETIRAR = "_hub_retirar"
ALERTAR = "_hub_alertar"
BLOQUEAR = "_hub_bloquear"
CONTAGEM_CHAVE = "_hub_contagem_chave"
TIPO_MOTIVOS = (
    "array<struct<classe:string,regra:string,coluna:string,"
    "valor:string,acao:string,dimensao:string>>"
)
LIMITE_EXEMPLOS = 10


def _origem(nome: str) -> str:
    """Nome interno do valor original (texto da Bronze)."""
    return f"_hub_origem_{nome}"


def _texto(nome: str) -> str:
    """Nome interno do valor transformado, ainda como texto."""
    return f"_hub_texto_{nome}"


def _motivo(
    condicao: Column,
    classe: str,
    acao: str,
    dimensao: str,
    coluna: str | None = None,
    regra: str | None = None,
    valor: Column | None = None,
) -> Column:
    """Motivo de violação quando a condição é verdadeira; nulo caso não."""
    return F.when(
        condicao,
        F.struct(
            F.lit(classe).alias("classe"),
            F.lit(regra).cast("string").alias("regra"),
            F.lit(coluna).cast("string").alias("coluna"),
            (F.lit(None) if valor is None else valor)
            .cast("string")
            .alias("valor"),
            F.lit(acao).alias("acao"),
            F.lit(dimensao).alias("dimensao"),
        ),
    )


def _motivos_coluna(coluna: ColunaSilver, acoes: dict) -> list[Column]:
    """Conversão, nulidade e domínio literal de uma coluna."""
    tipada = F.col(coluna.nome)
    original = F.col(_origem(coluna.nome))
    motivos = []
    if coluna.tipo != v.TEXTO:
        motivos.append(
            _motivo(
                F.col(_texto(coluna.nome)).isNotNull() & tipada.isNull(),
                v.CONVERSAO,
                acoes[v.CONVERSAO],
                v.DIMENSAO_POR_CLASSE[v.CONVERSAO],
                coluna=coluna.nome,
                valor=original,
            )
        )
    if coluna.verificar_nulidade:
        motivos.append(
            _motivo(
                tipada.isNull(),
                v.NULIDADE,
                acoes[v.NULIDADE],
                v.DIMENSAO_POR_CLASSE[v.NULIDADE],
                coluna=coluna.nome,
                valor=original,
            )
        )
    if coluna.valores_dominio is not None:
        fora = tipada.isNotNull() & ~tipada.isin(list(coluna.valores_dominio))
        motivos.append(
            _motivo(
                fora,
                v.DOMINIO,
                acoes[v.DOMINIO],
                v.DIMENSAO_POR_CLASSE[v.DOMINIO],
                coluna=coluna.nome,
                valor=original,
            )
        )
    return motivos


def _motivos_chave(plano: PlanoSilver) -> list[Column]:
    """Chave nula e chave duplicada (todo o grupo sai, sem vencedor)."""
    if not plano.chave:
        return []
    nomes = ",".join(plano.chave)
    alguma_nula = reduce(or_, [F.col(nome).isNull() for nome in plano.chave])
    valor_original = F.concat_ws(
        "|", *[F.col(_origem(nome)) for nome in plano.chave]
    )
    nula = _motivo(
        alguma_nula,
        v.CHAVE_NULA,
        plano.acoes[v.CHAVE_NULA],
        v.DIMENSAO_POR_CLASSE[v.CHAVE_NULA],
        coluna=nomes,
        valor=valor_original,
    )
    duplicada = _motivo(
        ~alguma_nula & (F.col(CONTAGEM_CHAVE) > 1),
        v.CHAVE_DUPLICADA,
        plano.acoes[v.CHAVE_DUPLICADA],
        v.DIMENSAO_POR_CLASSE[v.CHAVE_DUPLICADA],
        coluna=nomes,
        valor=valor_original,
    )
    return [nula, duplicada]


def _motivos_regras(plano: PlanoSilver) -> list[Column]:
    """Regras declaradas: só TRUE aprova; FALSE e NULL violam."""
    motivos = []
    for regra in plano.regras:
        valores = F.to_json(
            F.struct(*[F.col(nome) for nome in regra.colunas_referenciadas])
        )
        motivos.append(
            _motivo(
                ~F.coalesce(F.expr(regra.expressao), F.lit(False)),
                v.REGRA,
                regra.acao,
                regra.dimensao,
                coluna=",".join(regra.colunas_referenciadas),
                regra=regra.id,
                valor=valores,
            )
        )
    return motivos


def avaliar(bronze: DataFrame, plano: PlanoSilver) -> DataFrame:
    """Transforma, converte e anexa motivos e destino de cada linha."""
    etapa = bronze.select(
        *[F.col(c.nome).alias(_origem(c.nome)) for c in plano.colunas],
        F.col(v.COLUNA_ARQUIVO),
    )
    etapa = etapa.select(
        "*",
        *[
            transformacoes.aplicar(
                F.col(_origem(c.nome)), c.transformacoes
            ).alias(_texto(c.nome))
            for c in plano.colunas
        ],
    )
    etapa = etapa.select(
        "*",
        *[
            transformacoes.converter(_texto(c.nome), c).alias(c.nome)
            for c in plano.colunas
        ],
    )
    descricoes = [
        transformacoes.descrever(c).alias(c.coluna_descricao)
        for c in plano.colunas
        if c.coluna_descricao
    ]
    if descricoes:
        etapa = etapa.select("*", *descricoes)
    if plano.chave:
        janela = Window.partitionBy(*plano.chave)
        etapa = etapa.withColumn(
            CONTAGEM_CHAVE, F.count(F.lit(1)).over(janela)
        )
    motivos = [
        m for c in plano.colunas for m in _motivos_coluna(c, plano.acoes)
    ]
    motivos += _motivos_chave(plano) + _motivos_regras(plano)
    if motivos:
        lista = F.filter(F.array(*motivos), lambda m: m.isNotNull())
    else:
        lista = F.array().cast(TIPO_MOTIVOS)
    retirar = sorted(v.ACOES_QUE_RETIRAM)
    alertar = sorted(v.ACOES_QUE_ALERTAM)
    return (
        etapa.withColumn(MOTIVOS, lista)
        .withColumn(
            RETIRAR, F.exists(MOTIVOS, lambda m: m["acao"].isin(retirar))
        )
        .withColumn(
            ALERTAR, F.exists(MOTIVOS, lambda m: m["acao"].isin(alertar))
        )
        .withColumn(
            BLOQUEAR,
            F.exists(MOTIVOS, lambda m: m["acao"] == v.BLOQUEIA_PUBLICACAO),
        )
    )


def _resumo(avaliado: DataFrame) -> dict:
    """Totais por destino e contagem de violações por motivo."""
    totais = avaliado.agg(
        F.count(F.lit(1)).alias("total"),
        F.sum(F.col(RETIRAR).cast("int")).alias("retirar"),
        F.sum(F.col(ALERTAR).cast("int")).alias("alertar"),
        F.sum(F.col(BLOQUEAR).cast("int")).alias("bloquear"),
    ).first()
    violacoes = (
        avaliado.select(F.explode(MOTIVOS).alias("m"))
        .groupBy("m.classe", "m.regra", "m.coluna", "m.acao")
        .count()
        .collect()
    )
    return {
        "total": totais["total"],
        "retirar": totais["retirar"] or 0,
        "alertar": totais["alertar"] or 0,
        "bloquear": totais["bloquear"] or 0,
        "violacoes": sorted(
            (linha.asDict() for linha in violacoes),
            key=lambda item: (item["classe"], item["coluna"] or ""),
        ),
    }


def _exemplos_bloqueio(avaliado: DataFrame) -> list[dict]:
    """Alguns valores que dispararam BLOQUEIA_PUBLICACAO."""
    linhas = (
        avaliado.where(F.col(BLOQUEAR))
        .select(F.explode(MOTIVOS).alias("m"))
        .where(F.col("m.acao") == v.BLOQUEIA_PUBLICACAO)
        .select("m.classe", "m.regra", "m.coluna", "m.valor")
        .limit(LIMITE_EXEMPLOS)
        .collect()
    )
    return [linha.asDict() for linha in linhas]


def _saida(
    avaliado: DataFrame, plano: PlanoSilver, competencia: str, id_execucao: str
) -> DataFrame:
    """Linhas publicáveis nas colunas de negócio, com a linhagem mínima."""
    return avaliado.where(~F.col(RETIRAR)).select(
        *[F.col(nome) for nome in plano.colunas_negocio],
        F.lit(competencia).alias(v.COLUNA_COMPETENCIA),
        F.col(v.COLUNA_ARQUIVO),
        F.lit(id_execucao).alias(v.COLUNA_EXECUCAO),
    )


def _retirados(
    avaliado: DataFrame,
    plano: PlanoSilver,
    contexto: quarentena.ContextoQuarentena,
) -> DataFrame:
    """Linhas retiradas no formato da quarentena (registro em JSON)."""
    if plano.chave:
        chave = F.to_json(F.struct(*[F.col(nome) for nome in plano.chave]))
    else:
        chave = F.lit(None).cast("string")
    grupo = F.array_join(
        F.array_sort(
            F.array_distinct(
                F.transform(
                    MOTIVOS,
                    lambda m: F.concat_ws(
                        ":", m["classe"], F.coalesce(m["regra"], m["coluna"])
                    ),
                )
            )
        ),
        "|",
    )
    originais = F.struct(*[F.col(_origem(c.nome)) for c in plano.colunas])
    return quarentena.montar(
        avaliado.where(F.col(RETIRAR)),
        contexto=contexto,
        registro=F.to_json(
            F.struct(*[F.col(nome) for nome in plano.colunas_negocio])
        ),
        hash_registro=F.sha2(F.to_json(originais), 256),
        motivos=F.to_json(F.col(MOTIVOS)),
        chave=chave,
        grupo=grupo,
        arquivo=F.col(v.COLUNA_ARQUIVO),
    )


def ler_bronze(
    spark: SparkSession, plano: PlanoSilver, publicacao_bronze: dict
) -> DataFrame:
    """Lê a Bronze após confirmar que ela é exatamente a publicação
    registrada (mesma execução, competência e contagem)."""
    bronze = spark.table(plano.tabela_bronze)
    contagens = {
        (linha[v.COLUNA_EXECUCAO], linha[v.COLUNA_COMPETENCIA]): linha["count"]
        for linha in bronze.groupBy(v.COLUNA_EXECUCAO, v.COLUNA_COMPETENCIA)
        .count()
        .collect()
    }
    exigir(decisoes.verificar_snapshot_bronze(contagens, publicacao_bronze))
    return bronze


def publicar(
    spark: SparkSession,
    plano: PlanoSilver,
    destino: publicacao.Destino,
    registro: RegistroExecucao,
    contexto: quarentena.ContextoQuarentena,
    publicacao_bronze: dict,
) -> None:
    """Executa a Silver de ponta a ponta, preenchendo o registro."""
    bronze = ler_bronze(spark, plano, publicacao_bronze)
    registro.linhas_origem = publicacao_bronze["linhas_publicadas"]
    avaliado = avaliar(bronze, plano).persist(StorageLevel.MEMORY_AND_DISK)
    try:
        resumo = _resumo(avaliado)
        registro.detalhes["violacoes"] = resumo["violacoes"]
        if resumo["total"] != registro.linhas_origem:
            exigir(
                [
                    f"Silver avaliou {resumo['total']} linhas; Bronze "
                    f"publicou {registro.linhas_origem}"
                ]
            )
        if resumo["bloquear"]:
            registro.detalhes["exemplos_bloqueio"] = _exemplos_bloqueio(
                avaliado
            )
            exigir(
                [
                    f"{resumo['bloquear']} linhas com violação de ação "
                    f"{v.BLOQUEIA_PUBLICACAO}"
                ]
            )
        if resumo["alertar"]:
            registro.alertar(
                f"{resumo['alertar']} linhas com violação que gera alerta"
            )
        publicacao.publicar(
            spark,
            destino,
            registro,
            saida=_saida(
                avaliado, plano, contexto.competencia, registro.id_execucao
            ),
            publicadas_esperadas=resumo["total"] - resumo["retirar"],
            retirados=_retirados(avaliado, plano, contexto),
            quarentena_esperada=resumo["retirar"],
        )
    finally:
        avaliado.unpersist()
