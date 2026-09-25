"""Pontos de entrada chamados pelos notebooks finos de orquestração.

Cada função recebe ambiente, entidade (ou base) e competência, registra a
tentativa em ``controle.execucoes`` e chama o motor. As verificações de
governança (lastro, versão, competência, procedência) acontecem dentro
do registro, para que a tentativa bloqueada também fique documentada.
"""

from __future__ import annotations

import json

from pyspark.sql import SparkSession

from hub import aquisicao, arquivos, ciclo_vida, decisoes, hashes, inspecao
from hub import vocabulario as v
from hub.ambiente import Ambiente
from hub.contrato import Contrato
from hub.erros import exigir
from hub.execucao import RegistroExecucao, novo_id_execucao
from hub.historico import Historico
from hub.plano import plano_bronze, plano_silver
from hub.registro import Registro
from hub.spark import (
    bronze,
    controle,
    diagnostico,
    publicacao,
    quarentena,
    sessao,
    silver,
)
from hub.spark import catalogo as catalogo_spark


def _preparar(
    spark: SparkSession, registro: Registro, nome_ambiente: str
) -> Ambiente:
    """Resolve o ambiente e garante sessão, schemas e tabela de controle."""
    ambiente = registro.ambiente(nome_ambiente)
    sessao.preparar(spark, ambiente)
    controle.garantir_tabela(spark, ambiente)
    return ambiente


def _nova_execucao(
    registro: Registro,
    ambiente: Ambiente,
    tipo: str,
    identificador: str,
    contrato: Contrato | None = None,
    competencia: str | None = None,
) -> RegistroExecucao:
    """Cria o registro da tentativa com a identificação do contrato."""
    execucao = RegistroExecucao(
        id_execucao=novo_id_execucao(),
        identificador=identificador,
        tipo=tipo,
        ambiente=ambiente.nome,
        versao_motor=registro.versao_motor,
        competencia=competencia,
    )
    if contrato is not None:
        execucao.fonte = contrato.identidade.fonte
        execucao.base = contrato.identidade.base
        execucao.entidade = contrato.identidade.entidade
        execucao.versao_contrato = contrato.versao
        execucao.estado_contrato = contrato.documentacao.estado
        execucao.hash_leitura = hashes.hash_leitura(contrato)
        execucao.hash_contrato = hashes.hash_contrato(contrato)
    return execucao


def _exigir_governanca(
    contrato: Contrato,
    execucao: RegistroExecucao,
    historico: Historico,
    permitir_anterior: bool,
) -> None:
    """Lastro do estado, coerência de versão e regressão de competência."""
    problemas = ciclo_vida.verificar_lastro(
        contrato.documentacao.estado,
        execucao.hash_leitura,
        execucao.hash_contrato,
        historico.evidencias(),
    )
    problemas += decisoes.verificar_versao(
        contrato.versao, execucao.hash_contrato, historico.hashes_por_versao()
    )
    vigente = historico.ultima_efetiva(execucao.tipo)
    problemas += decisoes.verificar_competencia(
        execucao.competencia,
        vigente["competencia"] if vigente else None,
        permitir_anterior,
    )
    if permitir_anterior:
        execucao.detalhes["permitir_competencia_anterior"] = True
    exigir(problemas)


def _aquisicao_efetiva(
    spark: SparkSession, ambiente: Ambiente, contrato: Contrato, competencia
) -> tuple[dict, dict]:
    """Registro e detalhes da aquisição efetiva da base na competência."""
    historico = controle.ler_historico(
        spark, ambiente, contrato.identidade.identificador_base
    )
    registro = historico.aquisicao_efetiva(competencia)
    if registro is None:
        exigir([f"não há aquisição efetiva da base para {competencia}"])
    return registro, json.loads(registro["detalhes"])


def _partes_da_entidade(
    contrato: Contrato, detalhes_aquisicao: dict
) -> list[decisoes.Parte]:
    """Partes da aquisição selecionadas pelo contrato."""
    partes = decisoes.selecionar_partes(
        detalhes_aquisicao["partes"], contrato.selecao.arquivo
    )
    exigir(
        decisoes.verificar_quantidade_partes(
            partes, contrato.selecao.quantidade_partes
        )
    )
    return partes


def _destino(
    plano, ambiente: Ambiente, versao_vigente: int | None
) -> publicacao.Destino:
    """Destino físico do snapshot a partir do plano."""
    return publicacao.Destino(
        tabela=plano.tabela,
        schema_fisico=plano.schema_fisico,
        comentario_tabela=plano.comentario_tabela,
        comentarios_colunas=dict(plano.comentarios_colunas),
        tabela_quarentena=plano.tabela_quarentena,
        identificador=plano.identificador,
        versao_contrato=plano.versao,
        versao_vigente=versao_vigente,
    )


def _contexto(
    execucao: RegistroExecucao, camada: str, hash_decisao: str
) -> quarentena.ContextoQuarentena:
    """Identificação da publicação para os registros de quarentena."""
    return quarentena.ContextoQuarentena(
        identificador=execucao.identificador,
        camada=camada,
        fonte=execucao.fonte,
        base=execucao.base,
        entidade=execucao.entidade,
        competencia=execucao.competencia,
        publication_fingerprint=execucao.publication_fingerprint,
        versao_contrato=execucao.versao_contrato,
        hash_leitura=execucao.hash_leitura,
        hash_contrato=execucao.hash_contrato,
        hash_decisao=hash_decisao,
        id_execucao=execucao.id_execucao,
    )


def adquirir(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    fonte: str,
    base: str,
    competencia: str,
    modo: str = aquisicao.DOWNLOAD,
    pasta_deposito: str | None = None,
    forcar: bool = False,
) -> dict:
    """Adquire a publicação de uma base para a Raw.

    Sem ``forcar``, uma competência já adquirida não é baixada de novo.
    """
    amb = _preparar(spark, registro, ambiente)
    descritor = registro.base(f"{fonte}_{base}")
    execucao = _nova_execucao(
        registro, amb, v.AQUISICAO, descritor.identificador
    )
    execucao.fonte, execucao.base = fonte, base
    execucao.competencia = competencia
    with controle.execucao(spark, amb, execucao):
        exigir(decisoes.validar_competencia(competencia))
        historico = controle.ler_historico(spark, amb, descritor.identificador)
        existente = historico.aquisicao_efetiva(competencia)
        if existente is not None and not forcar:
            execucao.resultado = v.EXISTENTE
            execucao.id_execucao_origem = existente["id_execucao"]
            execucao.publication_fingerprint = existente[
                "publication_fingerprint"
            ]
        else:
            detalhes = aquisicao.adquirir(
                descritor,
                amb,
                competencia,
                execucao.id_execucao,
                modo,
                pasta_deposito,
            )
            execucao.detalhes.update(detalhes)
            execucao.tabela_destino = detalhes["pasta"]
            execucao.publication_fingerprint = hashes.fingerprint(
                (parte["parte"], parte["sha256"])
                for parte in detalhes["partes"]
            )
            execucao.resultado = v.ADQUIRIDA
    return execucao.resumo()


def inspecionar(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    entidade: str,
    competencia: str,
) -> dict:
    """Inspeção física sob demanda; o veredito vira evidência."""
    amb = _preparar(spark, registro, ambiente)
    contrato = registro.contrato(entidade)
    execucao = _nova_execucao(
        registro,
        amb,
        v.INSPECAO,
        contrato.identificador,
        contrato,
        competencia,
    )
    with controle.execucao(spark, amb, execucao):
        exigir(decisoes.validar_competencia(competencia))
        aquisicao_efetiva, detalhes = _aquisicao_efetiva(
            spark, amb, contrato, competencia
        )
        partes = _partes_da_entidade(contrato, detalhes)
        execucao.id_execucao_origem = aquisicao_efetiva["id_execucao"]
        execucao.publication_fingerprint = hashes.fingerprint(
            (parte.parte, parte.sha256) for parte in partes
        )
        relatorio = inspecao.inspecionar(
            [(parte.parte, amb.local(parte.caminho)) for parte in partes],
            contrato,
        )
        execucao.resultado = relatorio["veredito"]
        execucao.detalhes["inspecao"] = relatorio
    return {**execucao.resumo(), "relatorio": relatorio}


def _verificar_cabecalhos(
    partes: list[decisoes.Parte], contrato: Contrato, ambiente: Ambiente
) -> list[str]:
    """Cabeçalho físico de cada parte contra o layout do contrato."""
    esperado = [(c.cabecalho, *c.aliases) for c in contrato.colunas_origem]
    problemas = []
    for parte in partes:
        encontrado = arquivos.ler_cabecalho(
            ambiente.local(parte.caminho), contrato.leitura
        )
        problemas += [
            f"{parte.parte}: {problema}"
            for problema in decisoes.verificar_cabecalho(encontrado, esperado)
        ]
    return problemas


def _total_declarado(
    registro: Registro,
    contrato: Contrato,
    detalhes_aquisicao: dict,
    ambiente: Ambiente,
) -> int | None:
    """Total publicado pela fonte, lido direto da Raw (sem ordem de carga)."""
    contrato_total = registro.contrato_do_total(contrato)
    if contrato_total is None:
        return None
    partes = _partes_da_entidade(contrato_total, detalhes_aquisicao)
    exigir(decisoes.verificar_quantidade_partes(partes, 1))
    total, problemas = arquivos.ler_total_declarado(
        ambiente.local(partes[0].caminho),
        contrato_total,
        contrato.total_declarado.coluna,
    )
    exigir(problemas)
    return total


def publicar_bronze(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    entidade: str,
    competencia: str,
    permitir_competencia_anterior: bool = False,
) -> dict:
    """Publica a Bronze da entidade para a competência."""
    amb = _preparar(spark, registro, ambiente)
    contrato = registro.contrato(entidade)
    plano = plano_bronze(contrato, amb)
    execucao = _nova_execucao(
        registro,
        amb,
        v.PUBLICACAO_BRONZE,
        contrato.identificador,
        contrato,
        competencia,
    )
    execucao.tabela_destino = plano.tabela
    with controle.execucao(spark, amb, execucao):
        exigir(decisoes.validar_competencia(competencia))
        historico = controle.ler_historico(spark, amb, contrato.identificador)
        _exigir_governanca(
            contrato, execucao, historico, permitir_competencia_anterior
        )
        aquisicao_efetiva, detalhes = _aquisicao_efetiva(
            spark, amb, contrato, competencia
        )
        partes = _partes_da_entidade(contrato, detalhes)
        execucao.id_execucao_origem = aquisicao_efetiva["id_execucao"]
        execucao.publication_fingerprint = hashes.fingerprint(
            (parte.parte, parte.sha256) for parte in partes
        )
        if contrato.leitura.cabecalho:
            exigir(_verificar_cabecalhos(partes, contrato, amb))
        total = _total_declarado(registro, contrato, detalhes, amb)
        vigente = historico.ultima_efetiva(v.PUBLICACAO_BRONZE)
        bronze.publicar(
            spark,
            plano,
            _destino(
                plano, amb, vigente["versao_contrato"] if vigente else None
            ),
            execucao,
            _contexto(execucao, v.BRONZE, execucao.hash_leitura),
            partes,
            detalhes["pasta"],
            total,
        )
    return execucao.resumo()


def publicar_silver(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    entidade: str,
    competencia: str,
    permitir_competencia_anterior: bool = False,
) -> dict:
    """Publica a Silver da entidade a partir da Bronze vigente."""
    amb = _preparar(spark, registro, ambiente)
    contrato = registro.contrato(entidade)
    plano = plano_silver(contrato, amb)
    execucao = _nova_execucao(
        registro,
        amb,
        v.PUBLICACAO_SILVER,
        contrato.identificador,
        contrato,
        competencia,
    )
    execucao.tabela_destino = plano.tabela
    with controle.execucao(spark, amb, execucao):
        exigir(decisoes.validar_competencia(competencia))
        historico = controle.ler_historico(spark, amb, contrato.identificador)
        _exigir_governanca(
            contrato, execucao, historico, permitir_competencia_anterior
        )
        publicacao_bronze = historico.ultima_efetiva(v.PUBLICACAO_BRONZE)
        exigir(
            decisoes.verificar_procedencia(
                publicacao_bronze, competencia, execucao.hash_leitura
            )
        )
        execucao.id_execucao_origem = publicacao_bronze["id_execucao"]
        execucao.publication_fingerprint = publicacao_bronze[
            "publication_fingerprint"
        ]
        vigente = historico.ultima_efetiva(v.PUBLICACAO_SILVER)
        silver.publicar(
            spark,
            plano,
            _destino(
                plano, amb, vigente["versao_contrato"] if vigente else None
            ),
            execucao,
            _contexto(execucao, v.SILVER, execucao.hash_contrato),
            publicacao_bronze,
        )
    return execucao.resumo()


def aprovar(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    entidade: str,
    responsavel: str,
    hash_contrato: str,
) -> dict:
    """Registra aprovação nominal e datada do contrato neste ambiente.

    O hash informado precisa ser o da parte executável carregada: a
    aprovação vale só para aquele conteúdo.
    """
    amb = _preparar(spark, registro, ambiente)
    contrato = registro.contrato(entidade)
    execucao = _nova_execucao(
        registro, amb, v.APROVACAO, contrato.identificador, contrato
    )
    with controle.execucao(spark, amb, execucao):
        problemas = []
        if not responsavel or not responsavel.strip():
            problemas.append("informe o responsável pela aprovação")
        if hash_contrato != execucao.hash_contrato:
            problemas.append(
                f"hash informado {str(hash_contrato)[:12]} difere do "
                f"contrato carregado {execucao.hash_contrato[:12]}"
            )
        historico = controle.ler_historico(spark, amb, contrato.identificador)
        problemas += ciclo_vida.verificar_aprovavel(
            contrato.documentacao.estado,
            contrato.documentacao.pendencias,
            execucao.hash_leitura,
            historico.evidencias(),
        )
        exigir(problemas)
        execucao.responsavel = responsavel.strip()
        execucao.resultado = v.APROVADA
    return execucao.resumo()


def diagnosticar_referencias(
    spark: SparkSession, registro: Registro, ambiente: str, entidade: str
) -> dict:
    """Diagnóstico de integridade referencial; não bloqueia a entidade."""
    amb = _preparar(spark, registro, ambiente)
    contrato = registro.contrato(entidade)
    execucao = _nova_execucao(
        registro, amb, v.DIAGNOSTICO, contrato.identificador, contrato
    )
    with controle.execucao(spark, amb, execucao):
        itens = diagnostico.referencias(spark, contrato, amb)
        execucao.detalhes["referencias"] = itens
        execucao.resultado = decisoes.resultado_diagnostico(itens)
    return {**execucao.resumo(), "referencias": itens}


def sincronizar_catalogo(
    spark: SparkSession, registro: Registro, ambiente: str
) -> dict:
    """Sincroniza o catálogo estrutural e os comentários físicos."""
    amb = _preparar(spark, registro, ambiente)
    execucao = _nova_execucao(
        registro, amb, v.CATALOGO, v.IDENTIFICADOR_GLOBAL
    )
    with controle.execucao(spark, amb, execucao):
        execucao.detalhes["linhas"] = catalogo_spark.sincronizar(
            spark, amb, list(registro.contratos.values())
        )
        execucao.resultado = v.SINCRONIZADO
    return execucao.resumo()


def executar_base(
    spark: SparkSession,
    registro: Registro,
    ambiente: str,
    fonte: str,
    base: str,
    competencia: str,
    forcar_aquisicao: bool = False,
) -> list[dict]:
    """Aquisição, Bronze e Silver de todas as entidades da base.

    Entidades são independentes: a falha de uma não impede as demais.
    Ao final, qualquer falha ou bloqueio é reportado como erro.
    """
    resultados = [
        adquirir(
            spark,
            registro,
            ambiente,
            fonte,
            base,
            competencia,
            forcar=forcar_aquisicao,
        )
    ]
    falhas = []
    for contrato in registro.contratos_da_base(f"{fonte}_{base}"):
        for etapa in (publicar_bronze, publicar_silver):
            try:
                resultados.append(
                    etapa(
                        spark,
                        registro,
                        ambiente,
                        contrato.identificador,
                        competencia,
                    )
                )
            except Exception as erro:
                falhas.append(
                    f"{contrato.identificador} ({etapa.__name__}): {erro}"
                )
                break
    if falhas:
        raise RuntimeError("falhas na execução da base:\n" + "\n".join(falhas))
    return resultados
