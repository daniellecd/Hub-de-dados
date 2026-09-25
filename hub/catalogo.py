"""Catálogo: o que existe fisicamente e como usar.

Separa o conteúdo estrutural (derivado do mesmo plano que o motor executa
e atualizado a cada sincronização) do curatorial (eixo de informação,
data steward, descrições organizacionais), que é preservado entre
sincronizações e nasce como ``A_CONFIRMAR``. Nada é inferido pelo nome
da fonte, e o catálogo não guarda métrica de execução.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from hub import vocabulario as v
from hub.ambiente import Ambiente
from hub.contrato import Contrato
from hub.hashes import hash_contrato
from hub.plano import plano_bronze, plano_silver

TABELA_ATIVOS = "catalogo_ativos"
TABELA_COLUNAS = "catalogo_colunas"
TABELA_DEPENDENCIAS = "catalogo_dependencias"

ESQUEMAS = {
    TABELA_ATIVOS: (
        ("ativo", "STRING"),
        ("camada", "STRING"),
        ("identificador", "STRING"),
        ("fonte", "STRING"),
        ("base", "STRING"),
        ("entidade", "STRING"),
        ("descricao", "STRING"),
        ("chave", "STRING"),
        ("versao_contrato", "INT"),
        ("estado_contrato", "STRING"),
        ("hash_contrato", "STRING"),
        ("fonte_documental", "STRING"),
        ("existe", "BOOLEAN"),
        ("eixo_informacao", "STRING"),
        ("data_steward", "STRING"),
        ("descricao_organizacional", "STRING"),
    ),
    TABELA_COLUNAS: (
        ("ativo", "STRING"),
        ("coluna", "STRING"),
        ("ordem", "INT"),
        ("tipo", "STRING"),
        ("nulavel", "BOOLEAN"),
        ("chave", "BOOLEAN"),
        ("dominio", "STRING"),
        ("descricao", "STRING"),
        ("descricao_organizacional", "STRING"),
    ),
    TABELA_DEPENDENCIAS: (
        ("ativo", "STRING"),
        ("depende_de", "STRING"),
        ("tipo", "STRING"),
        ("coluna", "STRING"),
        ("coluna_referenciada", "STRING"),
    ),
}

CHAVES = {
    TABELA_ATIVOS: ("ativo",),
    TABELA_COLUNAS: ("ativo", "coluna"),
    TABELA_DEPENDENCIAS: ("ativo", "depende_de", "tipo", "coluna"),
}

CURATORIAIS = {
    TABELA_ATIVOS: (
        "eixo_informacao",
        "data_steward",
        "descricao_organizacional",
    ),
    TABELA_COLUNAS: ("descricao_organizacional",),
    TABELA_DEPENDENCIAS: (),
}

ORIGEM = "ORIGEM"
CAMADA = "CAMADA"
REFERENCIA = "REFERENCIA"


def colunas_estruturais(tabela: str) -> tuple[str, ...]:
    """Colunas que a sincronização atualiza (todas menos a curadoria)."""
    return tuple(
        nome for nome, _ in ESQUEMAS[tabela] if nome not in CURATORIAIS[tabela]
    )


def _ativo(
    contrato: Contrato, camada: str, tabela: str, existentes: set[str]
) -> dict:
    """Linha de um ativo; a curadoria nasce A_CONFIRMAR."""
    linha = {
        "ativo": tabela,
        "camada": camada,
        "identificador": contrato.identificador,
        "fonte": contrato.identidade.fonte,
        "base": contrato.identidade.base,
        "entidade": contrato.identidade.entidade,
        "descricao": contrato.descricao,
        "chave": ",".join(contrato.chave) or None,
        "versao_contrato": contrato.versao,
        "estado_contrato": contrato.documentacao.estado,
        "hash_contrato": hash_contrato(contrato),
        "fonte_documental": contrato.documentacao.fonte_documental,
        "existe": tabela in existentes,
    }
    linha.update({c: v.A_CONFIRMAR for c in CURATORIAIS[TABELA_ATIVOS]})
    return linha


def _colunas(
    contrato: Contrato,
    camada: str,
    tabela: str,
    schema: Iterable[tuple[str, str]],
    comentarios: Mapping[str, str],
) -> list[dict]:
    """Linhas de coluna a partir do schema físico planejado."""
    declaradas = {coluna.nome: coluna for coluna in contrato.colunas}
    linhas = []
    for ordem, (nome, tipo) in enumerate(schema, start=1):
        coluna = declaradas.get(nome)
        if nome in v.COLUNAS_LINHAGEM:
            nulavel = False
        elif camada == v.SILVER and coluna is not None:
            nulavel = coluna.nulavel and nome not in contrato.chave
        else:
            nulavel = True
        linhas.append(
            {
                "ativo": tabela,
                "coluna": nome,
                "ordem": ordem,
                "tipo": tipo,
                "nulavel": nulavel,
                "chave": nome in contrato.chave,
                "dominio": (
                    coluna.dominio
                    if camada == v.SILVER and coluna is not None
                    else None
                ),
                "descricao": comentarios.get(nome) or None,
                "descricao_organizacional": v.A_CONFIRMAR,
            }
        )
    return linhas


def _dependencias(
    contrato: Contrato, ambiente: Ambiente, bronze: str, silver: str
) -> list[dict]:
    """Dependências: origem na Raw, camada anterior e referências."""
    identidade = contrato.identidade
    linhas = [
        {
            "ativo": bronze,
            "depende_de": ambiente.caminho_raw(
                identidade.fonte, identidade.base
            ),
            "tipo": ORIGEM,
            "coluna": None,
            "coluna_referenciada": None,
        },
        {
            "ativo": silver,
            "depende_de": bronze,
            "tipo": CAMADA,
            "coluna": None,
            "coluna_referenciada": None,
        },
    ]
    for coluna in contrato.colunas:
        dominio = contrato.dominios.get(coluna.dominio or "")
        if dominio is None or dominio.tabela is None:
            continue
        linhas.append(
            {
                "ativo": silver,
                "depende_de": ambiente.tabela(
                    v.SILVER, dominio.tabela.identificador
                ),
                "tipo": REFERENCIA,
                "coluna": coluna.nome,
                "coluna_referenciada": dominio.coluna,
            }
        )
    return linhas


def linhas_catalogo(
    contratos: Iterable[Contrato], ambiente: Ambiente, existentes: set[str]
) -> dict[str, list[dict]]:
    """Linhas estruturais das três tabelas de catálogo.

    Args:
        contratos: contratos do registro.
        ambiente: resolução física do ambiente.
        existentes: nomes físicos das tabelas que existem no ambiente.
    """
    linhas: dict[str, list[dict]] = {nome: [] for nome in ESQUEMAS}
    for contrato in contratos:
        bronze = plano_bronze(contrato, ambiente)
        silver = plano_silver(contrato, ambiente)
        for camada, plano in ((v.BRONZE, bronze), (v.SILVER, silver)):
            linhas[TABELA_ATIVOS].append(
                _ativo(contrato, camada, plano.tabela, existentes)
            )
            linhas[TABELA_COLUNAS].extend(
                _colunas(
                    contrato,
                    camada,
                    plano.tabela,
                    plano.schema_fisico,
                    plano.comentarios_colunas,
                )
            )
        linhas[TABELA_DEPENDENCIAS].extend(
            _dependencias(contrato, ambiente, bronze.tabela, silver.tabela)
        )
    return linhas
