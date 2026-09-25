"""Descritor de base: como a publicação de uma fonte é adquirida.

Uma base (ex.: fonte_base) agrupa as entidades que chegam na mesma
publicação. O descritor declara a URL e a lista de arquivos; as entidades
declaram, em seus contratos, qual arquivo da publicação cada uma lê.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hub.contrato import PADRAO_FONTE
from hub.leitor import Leitor

FORMATO_BASE = 1
MARCADOR_COMPETENCIA = "{competencia}"
_ESQUEMAS_URL = ("https://", "http://", "file://")
_NOME_ARQUIVO = re.compile(r"^[^/\\]+$")


@dataclass(frozen=True)
class DescritorBase:
    """Aquisição declarada de uma base."""

    fonte: str
    base: str
    descricao: str | None
    url_base: str
    arquivos: tuple[str, ...]
    fonte_documental: str | None
    pendencias: tuple[str, ...]

    @property
    def identificador(self) -> str:
        """Nome lógico da base: fonte_base."""
        return f"{self.fonte}_{self.base}"

    def url(self, arquivo: str, competencia: str) -> str:
        """Monta a URL de um arquivo para a competência informada."""
        raiz = self.url_base.replace(MARCADOR_COMPETENCIA, competencia)
        if not raiz.endswith("/"):
            raiz += "/"
        return raiz + arquivo


def carregar_base(dados: Any, origem: str = "base") -> DescritorBase:
    """Lê e valida o descritor de uma base.

    Raises:
        ContratoInvalido: com todos os problemas encontrados.
    """
    leitor = Leitor()
    raiz = leitor.mapa(
        dados,
        "base",
        ("formato_base", "identidade", "aquisicao"),
        ("descricao", "documentacao"),
    )
    formato = leitor.inteiro(raiz.get("formato_base"), "formato_base")
    if formato is not None and formato != FORMATO_BASE:
        leitor.erro("formato_base", f"formato não suportado: {formato}")
    identidade = leitor.mapa(
        raiz.get("identidade"), "identidade", ("fonte", "base")
    )
    fonte = leitor.texto(
        identidade.get("fonte"), "identidade.fonte", PADRAO_FONTE
    )
    base = leitor.texto(
        identidade.get("base"), "identidade.base", PADRAO_FONTE
    )
    aquisicao = leitor.mapa(
        raiz.get("aquisicao"), "aquisicao", ("url_base", "arquivos")
    )
    url_base = leitor.texto(aquisicao.get("url_base"), "aquisicao.url_base")
    if url_base is not None and not url_base.startswith(_ESQUEMAS_URL):
        leitor.erro("aquisicao.url_base", "use https://, http:// ou file://")
    arquivos = [
        leitor.texto(nome, f"aquisicao.arquivos[{indice}]", _NOME_ARQUIVO)
        for indice, nome in enumerate(
            leitor.lista(
                aquisicao.get("arquivos"), "aquisicao.arquivos", opcional=False
            )
        )
    ]
    if aquisicao.get("arquivos") == []:
        leitor.erro("aquisicao.arquivos", "lista vazia")
    leitor.unicos([a for a in arquivos if a], "aquisicao.arquivos")
    documentacao = leitor.mapa(
        raiz.get("documentacao", {}),
        "documentacao",
        opcionais=("fonte_documental", "pendencias"),
    )
    pendencias = [
        leitor.texto(item, f"documentacao.pendencias[{indice}]")
        for indice, item in enumerate(
            leitor.lista(documentacao.get("pendencias"), "pendencias")
        )
    ]
    descritor = DescritorBase(
        fonte=fonte,
        base=base,
        descricao=leitor.texto(
            raiz.get("descricao"), "descricao", opcional=True
        ),
        url_base=url_base,
        arquivos=tuple(a for a in arquivos if a is not None),
        fonte_documental=leitor.texto(
            documentacao.get("fonte_documental"),
            "documentacao.fonte_documental",
            opcional=True,
        ),
        pendencias=tuple(p for p in pendencias if p is not None),
    )
    nome = f"{fonte}_{base}" if fonte and base else origem
    leitor.concluir(nome)
    return descritor
