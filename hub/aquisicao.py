"""Aquisição: traz a publicação para a Raw e registra a evidência.

A Raw nunca é sobrescrita. Cada aquisição grava numa pasta própria:

    <raiz_raw>/<fonte>/<base>/<competencia>/<pasta da aquisição>/

ZIPs são extraídos em ``<pasta da aquisição>/<nome do zip sem extensão>/``
e cada arquivo tem SHA-256 calculado durante a escrita. Há dois modos:

- ``download``: baixa as URLs declaradas no descritor da base;
- ``deposito``: registra arquivos depositados por fora (upload, Data
  Pipeline, Power Automate) numa pasta informada pelo operador.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from typing import BinaryIO

from hub.ambiente import Ambiente
from hub.bases import DescritorBase
from hub.hashes import TAMANHO_BLOCO, sha256_arquivo

DOWNLOAD = "download"
DEPOSITO = "deposito"
MODOS = (DOWNLOAD, DEPOSITO)

AGENTE = "hub-de-dados/0.1"
TEMPO_LIMITE = 300
_NOME_PASTA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


class ErroAquisicao(RuntimeError):
    """Falha ao obter ou registrar os arquivos da publicação."""


def gravar_fluxo(fluxo: BinaryIO, destino: str) -> tuple[int, str]:
    """Grava um fluxo em arquivo novo, calculando bytes e SHA-256.

    Raises:
        FileExistsError: se o destino já existir (a Raw não sobrescreve).
    """
    if os.path.exists(destino):
        raise FileExistsError(destino)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    resumo = hashlib.sha256()
    total = 0
    with open(destino, "wb") as arquivo:
        for bloco in iter(lambda: fluxo.read(TAMANHO_BLOCO), b""):
            arquivo.write(bloco)
            resumo.update(bloco)
            total += len(bloco)
    return total, resumo.hexdigest()


def _sha256_fluxo(fluxo: BinaryIO) -> str:
    """SHA-256 de um fluxo sem gravá-lo."""
    resumo = hashlib.sha256()
    for bloco in iter(lambda: fluxo.read(TAMANHO_BLOCO), b""):
        resumo.update(bloco)
    return resumo.hexdigest()


def baixar(
    url: str,
    destino: str,
    tentativas: int = 3,
    espera: float = 5.0,
    abrir: Callable = urllib.request.urlopen,
) -> tuple[int, str]:
    """Baixa a URL para um arquivo novo; repete em falha transitória.

    O conteúdo é gravado em ``<destino>.parcial<n>`` e renomeado ao fim,
    de modo que um download interrompido nunca aparece com o nome final.

    Raises:
        ErroAquisicao: após esgotar as tentativas ou em erro HTTP 4xx.
    """
    if os.path.exists(destino):
        raise FileExistsError(destino)
    for tentativa in range(1, tentativas + 1):
        parcial = f"{destino}.parcial{tentativa}"
        requisicao = urllib.request.Request(
            url, headers={"User-Agent": AGENTE}
        )
        try:
            with abrir(requisicao, timeout=TEMPO_LIMITE) as resposta:
                total, resumo = gravar_fluxo(resposta, parcial)
            os.replace(parcial, destino)
            return total, resumo
        except urllib.error.HTTPError as erro:
            if 400 <= erro.code < 500 or tentativa == tentativas:
                raise ErroAquisicao(f"{url}: HTTP {erro.code}") from erro
        except (urllib.error.URLError, TimeoutError, ConnectionError) as erro:
            if tentativa == tentativas:
                raise ErroAquisicao(f"{url}: {erro}") from erro
        time.sleep(espera * tentativa)
    raise AssertionError("inalcançável")


def extrair_zip(caminho_zip: str, pasta_destino: str) -> list[dict]:
    """Extrai os membros do ZIP em pasta plana, sem sobrescrever.

    O caminho interno do membro é descartado (evita path traversal).
    Membro já extraído com o mesmo SHA-256 é reaproveitado; com conteúdo
    diferente, a extração falha.

    Returns:
        Lista com nome, membro original, bytes e SHA-256 de cada arquivo.
    """
    extraidos = []
    nomes: set[str] = set()
    with zipfile.ZipFile(caminho_zip) as pacote:
        for membro in pacote.infolist():
            nome = posixpath.basename(membro.filename)
            if membro.is_dir() or not nome:
                continue
            if nome in nomes:
                raise ErroAquisicao(f"{caminho_zip}: membro repetido {nome}")
            nomes.add(nome)
            destino = os.path.join(pasta_destino, nome)
            with pacote.open(membro) as fluxo:
                if os.path.exists(destino):
                    resumo = _sha256_fluxo(fluxo)
                    if resumo != sha256_arquivo(destino):
                        raise ErroAquisicao(f"conteúdo divergente: {destino}")
                    total = os.path.getsize(destino)
                else:
                    total, resumo = gravar_fluxo(fluxo, destino)
            extraidos.append(
                {
                    "nome": nome,
                    "membro": membro.filename,
                    "bytes": total,
                    "sha256": resumo,
                }
            )
    return extraidos


def _registrar_arquivo(
    descritor: DescritorBase,
    ambiente: Ambiente,
    relativo: str,
    nome: str,
    competencia: str,
    modo: str,
    baixar_arquivo: Callable,
) -> dict:
    """Baixa ou confere um arquivo declarado e devolve sua evidência."""
    caminho = posixpath.join(relativo, nome)
    local = ambiente.local(caminho)
    url = None
    if modo == DOWNLOAD:
        url = descritor.url(nome, competencia)
        total, resumo = baixar_arquivo(url, local)
    elif not os.path.exists(local):
        raise ErroAquisicao(f"arquivo declarado não depositado: {caminho}")
    else:
        total, resumo = os.path.getsize(local), sha256_arquivo(local)
    return {
        "nome": nome,
        "caminho": caminho,
        "bytes": total,
        "sha256": resumo,
        "url": url,
    }


def _partes_do_arquivo(
    arquivo: dict, relativo: str, ambiente: Ambiente
) -> list[dict]:
    """Arquivos legíveis gerados por um arquivo adquirido."""
    nome = arquivo["nome"]
    if not nome.lower().endswith(".zip"):
        return [
            {
                "parte": nome,
                "caminho": arquivo["caminho"],
                "bytes": arquivo["bytes"],
                "sha256": arquivo["sha256"],
                "origem": None,
            }
        ]
    pasta = posixpath.splitext(nome)[0]
    destino = posixpath.join(relativo, pasta)
    partes = []
    for membro in extrair_zip(
        ambiente.local(arquivo["caminho"]), ambiente.local(destino)
    ):
        partes.append(
            {
                "parte": f"{pasta}/{membro['nome']}",
                "caminho": posixpath.join(destino, membro["nome"]),
                "bytes": membro["bytes"],
                "sha256": membro["sha256"],
                "origem": nome,
            }
        )
    return partes


def adquirir(
    descritor: DescritorBase,
    ambiente: Ambiente,
    competencia: str,
    id_aquisicao: str,
    modo: str = DOWNLOAD,
    pasta_deposito: str | None = None,
    baixar_arquivo: Callable = baixar,
) -> dict:
    """Traz a publicação para a Raw e devolve a evidência da aquisição.

    Args:
        descritor: descritor da base.
        ambiente: resolução física do ambiente.
        competencia: competência no formato AAAA-MM.
        id_aquisicao: identificador da execução (nome da pasta no download).
        modo: ``download`` ou ``deposito``.
        pasta_deposito: pasta já existente sob a competência (depósito).
        baixar_arquivo: função de download (injetável em testes).

    Returns:
        Detalhes com a pasta, os arquivos adquiridos e as partes legíveis.
    """
    if modo not in MODOS:
        raise ErroAquisicao(f"modo inválido: {modo}")
    pasta = id_aquisicao if modo == DOWNLOAD else pasta_deposito
    if not pasta or not _NOME_PASTA.match(pasta):
        raise ErroAquisicao(f"pasta de aquisição inválida: {pasta!r}")
    relativo = ambiente.caminho_raw(
        descritor.fonte, descritor.base, competencia, pasta
    )
    if modo == DOWNLOAD and os.path.exists(ambiente.local(relativo)):
        raise ErroAquisicao(f"pasta de aquisição já existe: {relativo}")
    arquivos = [
        _registrar_arquivo(
            descritor,
            ambiente,
            relativo,
            nome,
            competencia,
            modo,
            baixar_arquivo,
        )
        for nome in descritor.arquivos
    ]
    partes = [
        parte
        for arquivo in arquivos
        for parte in _partes_do_arquivo(arquivo, relativo, ambiente)
    ]
    return {
        "modo": modo,
        "pasta": relativo,
        "arquivos": arquivos,
        "partes": partes,
    }
