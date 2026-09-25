"""Hashes determinísticos do Hub.

Modelo deliberadamente simples:

- ``arquivo_hash``: SHA-256 de cada arquivo preservado na Raw;
- ``publication_fingerprint``: SHA-256 do conjunto ordenado de partes;
- ``hash_leitura``: parte executável que a Bronze usa (seleção, dialeto,
  layout de origem, ação para linha malformada e total declarado);
- ``hash_contrato``: toda a parte executável do contrato.

Documentação (descrições, estado, pendências) e ``versao`` ficam fora dos
hashes. Não existe hash semântico, físico, de plano ou de DataFrame.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from hub import vocabulario as v
from hub.contrato import Contrato, Identidade, Transformacao

TAMANHO_BLOCO = 1 << 20


def canonico(valor: Any) -> str:
    """Serializa em JSON canônico: chaves ordenadas e sem espaços."""
    return json.dumps(
        valor, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def sha256_texto(texto: str) -> str:
    """SHA-256 hexadecimal de um texto em UTF-8."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def sha256_arquivo(caminho: str, tamanho_bloco: int = TAMANHO_BLOCO) -> str:
    """SHA-256 hexadecimal de um arquivo, lido em blocos."""
    resumo = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(tamanho_bloco), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _identidade(identidade: Identidade) -> dict:
    """Representação canônica da identidade lógica."""
    return {
        "fonte": identidade.fonte,
        "base": identidade.base,
        "entidade": identidade.entidade,
        "especificacao": identidade.especificacao,
    }


def _transformacoes(transformacoes: Iterable[Transformacao]) -> list:
    """Representação canônica de uma lista de transformações."""
    return [
        {"tipo": t.tipo, "parametros": dict(t.parametros)}
        for t in transformacoes
    ]


def parte_leitura(contrato: Contrato) -> dict:
    """Parte executável usada pela Bronze."""
    total = contrato.total_declarado
    return {
        "formato_contrato": contrato.formato_contrato,
        "identidade": _identidade(contrato.identidade),
        "selecao": {
            "arquivo": contrato.selecao.arquivo,
            "quantidade_partes": contrato.selecao.quantidade_partes,
        },
        "leitura": {
            "separador": contrato.leitura.separador,
            "aspas": contrato.leitura.aspas,
            "escape": contrato.leitura.escape,
            "codificacao": contrato.leitura.codificacao,
            "cabecalho": contrato.leitura.cabecalho,
            "tolerancia_malformadas": contrato.leitura.tolerancia_malformadas,
        },
        "layout": [
            {
                "nome": coluna.nome,
                "cabecalho": coluna.cabecalho,
                "aliases": list(coluna.aliases),
                "ausente_na_origem": coluna.ausente_na_origem,
            }
            for coluna in contrato.colunas
        ],
        "linha_malformada": contrato.acoes_padrao[v.LINHA_MALFORMADA],
        "total_declarado": (
            None
            if total is None
            else {"entidade": total.entidade, "coluna": total.coluna}
        ),
    }


def parte_executavel(contrato: Contrato) -> dict:
    """Parte executável completa (Bronze e Silver)."""
    parte = parte_leitura(contrato)
    parte["transformacoes_padrao"] = _transformacoes(
        contrato.transformacoes_padrao
    )
    parte["colunas"] = [
        {
            "nome": coluna.nome,
            "tipo": coluna.tipo,
            "nulavel": coluna.nulavel,
            "formato": coluna.formato,
            "precisao": coluna.precisao,
            "escala": coluna.escala,
            "separador_decimal": coluna.separador_decimal,
            "transformacoes": _transformacoes(coluna.transformacoes),
            "dominio": coluna.dominio,
        }
        for coluna in contrato.colunas
    ]
    parte["chave"] = list(contrato.chave)
    parte["dominios"] = {
        nome: {
            "tipo": dominio.tipo,
            "valores": dict(dominio.valores),
            "coluna_descricao": dominio.coluna_descricao,
            "tabela": (
                None if dominio.tabela is None else _identidade(dominio.tabela)
            ),
            "coluna": dominio.coluna,
        }
        for nome, dominio in contrato.dominios.items()
    }
    parte["regras"] = [
        {
            "id": regra.id,
            "expressao": regra.expressao,
            "colunas_referenciadas": list(regra.colunas_referenciadas),
            "acao": regra.acao,
            "dimensao": regra.dimensao,
        }
        for regra in contrato.regras
    ]
    parte["acoes_padrao"] = dict(contrato.acoes_padrao)
    return parte


def hash_leitura(contrato: Contrato) -> str:
    """Hash da parte executável usada pela Bronze."""
    return sha256_texto(canonico(parte_leitura(contrato)))


def hash_contrato(contrato: Contrato) -> str:
    """Hash da parte executável completa do contrato."""
    return sha256_texto(canonico(parte_executavel(contrato)))


def fingerprint(partes: Iterable[tuple[str, str]]) -> str:
    """Fingerprint da publicação: partes ordenadas por identificador.

    Args:
        partes: pares (identificador da parte, SHA-256 do arquivo).
    """
    linhas = [f"{parte}|{resumo}" for parte, resumo in sorted(partes)]
    return sha256_texto("\n".join(linhas))
