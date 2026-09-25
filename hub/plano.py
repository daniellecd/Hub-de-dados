"""Plano de execução: tradução pura do contrato para cada camada.

O plano resolve nome físico (via ambiente), ordem de colunas,
transformações efetivas, tipos físicos, padrões de data, opções do leitor
CSV e comentários. Os executores Spark apenas interpretam o plano, o que
mantém toda a decisão testável sem Spark.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hub import hashes
from hub import vocabulario as v
from hub.ambiente import Ambiente
from hub.contrato import Coluna, Contrato, Regra, TotalDeclarado, Transformacao
from hub.execucao import TABELA_QUARENTENA

COLUNA_MALFORMADA = "_hub_linha_malformada"

_TIPOS_FISICOS = {
    v.TEXTO: "string",
    v.INTEIRO: "int",
    v.INTEIRO_LONGO: "bigint",
    v.DATA: "date",
}

LINHAGEM_FISICA = tuple((nome, "string") for nome in v.COLUNAS_LINHAGEM)

COMENTARIOS_LINHAGEM = {
    v.COLUNA_COMPETENCIA: "Competência da publicação de origem (AAAA-MM).",
    v.COLUNA_ARQUIVO: "Parte física de origem na Raw (<pasta>/<arquivo>).",
    v.COLUNA_EXECUCAO: "Execução que publicou a linha (controle.execucoes).",
}


def tipo_fisico(coluna: Coluna) -> str:
    """Tipo físico da coluna na Silver."""
    if coluna.tipo == v.DECIMAL:
        return f"decimal({coluna.precisao},{coluna.escala})"
    return _TIPOS_FISICOS[coluna.tipo]


def padrao_data(formato: str) -> str:
    """Converte a notação do layout (AAAA-MM-DD) no padrão yyyy-MM-dd."""
    padrao = formato
    for token, equivalente in v.TOKENS_DATA.items():
        padrao = padrao.replace(token, equivalente)
    return padrao


def opcoes_leitor_csv(contrato: Contrato) -> dict[str, str]:
    """Traduz o dialeto do contrato em opções do leitor CSV do Spark.

    Linha com número de campos diferente do layout é marcada como
    malformada (modo PERMISSIVE com coluna de registro corrompido).
    """
    leitura = contrato.leitura
    return {
        "sep": leitura.separador,
        "quote": leitura.aspas,
        "escape": leitura.escape,
        "encoding": v.CODIFICACOES[leitura.codificacao].spark,
        "header": "true" if leitura.cabecalho else "false",
        "mode": "PERMISSIVE",
        "columnNameOfCorruptRecord": COLUNA_MALFORMADA,
        "multiLine": "false",
        "ignoreLeadingWhiteSpace": "false",
        "ignoreTrailingWhiteSpace": "false",
    }


def _comentario_tabela(contrato: Contrato, camada: str) -> str:
    """Comentário físico da tabela derivado do contrato."""
    papel = {
        v.BRONZE: "Bronze: valores textuais conforme o arquivo de origem.",
        v.SILVER: "Silver: tipos, domínios e regras do contrato aplicados.",
    }[camada]
    partes = [contrato.descricao or "", papel]
    partes.append(
        f"Contrato {contrato.identificador} versão {contrato.versao}."
    )
    return " ".join(parte for parte in partes if parte)


def _comentarios_colunas(contrato: Contrato, camada: str) -> dict[str, str]:
    """Comentários físicos de coluna derivados do contrato."""
    comentarios = {}
    for coluna in contrato.colunas:
        comentarios[coluna.nome] = coluna.descricao or ""
        dominio = contrato.dominio_literal(coluna)
        if camada == v.SILVER and dominio and dominio.coluna_descricao:
            comentarios[dominio.coluna_descricao] = (
                f"Descrição de {coluna.nome} conforme o domínio "
                f"{dominio.nome}."
            )
    comentarios.update(COMENTARIOS_LINHAGEM)
    return comentarios


@dataclass(frozen=True)
class PlanoBronze:
    """O que a Bronze executa para uma entidade."""

    identificador: str
    tabela: str
    tabela_quarentena: str
    padrao_arquivo: str
    quantidade_partes: int | None
    colunas_origem: tuple[str, ...]
    colunas_saida: tuple[str, ...]
    cabecalho_esperado: tuple[tuple[str, ...], ...] | None
    opcoes_csv: Mapping[str, str]
    cabecalho: bool
    tolerancia: float
    acao_malformada: str
    total_declarado: TotalDeclarado | None
    schema_fisico: tuple[tuple[str, str], ...]
    comentario_tabela: str
    comentarios_colunas: Mapping[str, str]
    versao: int
    hash_leitura: str
    hash_contrato: str


@dataclass(frozen=True)
class ColunaSilver:
    """Tratamento de uma coluna na Silver."""

    nome: str
    tipo: str
    tipo_fisico: str
    padrao_data: str | None
    separador_decimal: str | None
    transformacoes: tuple[Transformacao, ...]
    verificar_nulidade: bool
    na_chave: bool
    valores_dominio: Mapping[str, str] | None
    coluna_descricao: str | None


@dataclass(frozen=True)
class PlanoSilver:
    """O que a Silver executa para uma entidade."""

    identificador: str
    tabela: str
    tabela_bronze: str
    tabela_quarentena: str
    colunas: tuple[ColunaSilver, ...]
    chave: tuple[str, ...]
    regras: tuple[Regra, ...]
    acoes: Mapping[str, str]
    colunas_negocio: tuple[str, ...]
    schema_fisico: tuple[tuple[str, str], ...]
    comentario_tabela: str
    comentarios_colunas: Mapping[str, str]
    versao: int
    hash_leitura: str
    hash_contrato: str


def plano_bronze(contrato: Contrato, ambiente: Ambiente) -> PlanoBronze:
    """Compila o plano da Bronze."""
    origem = contrato.colunas_origem
    cabecalho = None
    if contrato.leitura.cabecalho:
        cabecalho = tuple(
            (coluna.cabecalho, *coluna.aliases) for coluna in origem
        )
    return PlanoBronze(
        identificador=contrato.identificador,
        tabela=ambiente.tabela(v.BRONZE, contrato.identificador),
        tabela_quarentena=ambiente.tabela_controle(TABELA_QUARENTENA),
        padrao_arquivo=contrato.selecao.arquivo,
        quantidade_partes=contrato.selecao.quantidade_partes,
        colunas_origem=tuple(coluna.nome for coluna in origem),
        colunas_saida=tuple(coluna.nome for coluna in contrato.colunas),
        cabecalho_esperado=cabecalho,
        opcoes_csv=opcoes_leitor_csv(contrato),
        cabecalho=contrato.leitura.cabecalho,
        tolerancia=contrato.leitura.tolerancia_malformadas,
        acao_malformada=contrato.acoes_padrao[v.LINHA_MALFORMADA],
        total_declarado=contrato.total_declarado,
        schema_fisico=tuple(
            (coluna.nome, "string") for coluna in contrato.colunas
        )
        + LINHAGEM_FISICA,
        comentario_tabela=_comentario_tabela(contrato, v.BRONZE),
        comentarios_colunas=_comentarios_colunas(contrato, v.BRONZE),
        versao=contrato.versao,
        hash_leitura=hashes.hash_leitura(contrato),
        hash_contrato=hashes.hash_contrato(contrato),
    )


def _coluna_silver(contrato: Contrato, coluna: Coluna) -> ColunaSilver:
    """Compila o tratamento Silver de uma coluna."""
    dominio = contrato.dominio_literal(coluna)
    return ColunaSilver(
        nome=coluna.nome,
        tipo=coluna.tipo,
        tipo_fisico=tipo_fisico(coluna),
        padrao_data=padrao_data(coluna.formato) if coluna.formato else None,
        separador_decimal=coluna.separador_decimal,
        transformacoes=contrato.transformacoes_padrao + coluna.transformacoes,
        verificar_nulidade=(
            not coluna.nulavel and coluna.nome not in contrato.chave
        ),
        na_chave=coluna.nome in contrato.chave,
        valores_dominio=dict(dominio.valores) if dominio else None,
        coluna_descricao=dominio.coluna_descricao if dominio else None,
    )


def plano_silver(contrato: Contrato, ambiente: Ambiente) -> PlanoSilver:
    """Compila o plano da Silver."""
    colunas = tuple(_coluna_silver(contrato, c) for c in contrato.colunas)
    schema: list[tuple[str, str]] = []
    for coluna in colunas:
        schema.append((coluna.nome, coluna.tipo_fisico))
        if coluna.coluna_descricao:
            schema.append((coluna.coluna_descricao, "string"))
    return PlanoSilver(
        identificador=contrato.identificador,
        tabela=ambiente.tabela(v.SILVER, contrato.identificador),
        tabela_bronze=ambiente.tabela(v.BRONZE, contrato.identificador),
        tabela_quarentena=ambiente.tabela_controle(TABELA_QUARENTENA),
        colunas=colunas,
        chave=contrato.chave,
        regras=contrato.regras,
        acoes=dict(contrato.acoes_padrao),
        colunas_negocio=contrato.colunas_saida,
        schema_fisico=tuple(schema) + LINHAGEM_FISICA,
        comentario_tabela=_comentario_tabela(contrato, v.SILVER),
        comentarios_colunas=_comentarios_colunas(contrato, v.SILVER),
        versao=contrato.versao,
        hash_leitura=hashes.hash_leitura(contrato),
        hash_contrato=hashes.hash_contrato(contrato),
    )
