"""Configuração de ambiente: traduz identidade lógica em nome físico.

DEV, HML e PROD são workspaces distintos. O nome do objeto é igual nos
três; o ambiente resolve apenas o schema de cada camada e a raiz de
caminho. Nenhum identificador de tenant (GUID) é aceito aqui.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hub import vocabulario as v
from hub.leitor import Leitor

FORMATO_CONFIGURACAO = 1
_NOME_AMBIENTE = re.compile(r"^[a-z][a-z0-9]*$")
_NOME_SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")
_NOME_LAKEHOUSE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_CAMINHO_RELATIVO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-/]*$")


@dataclass(frozen=True)
class Ambiente:
    """Resolução física de um ambiente (DEV, HML ou PROD)."""

    nome: str
    schemas: Mapping[str, str]
    raiz_raw: str
    montagem_local: str

    def tabela(self, camada: str, identificador: str) -> str:
        """Nome físico: <schema da camada>.<identificador lógico>."""
        return f"{self.schemas[camada]}.{identificador}"

    def tabela_controle(self, nome: str) -> str:
        """Nome físico de uma tabela operacional do motor."""
        return self.tabela(v.CONTROLE, nome)

    def caminho_raw(self, *partes: str) -> str:
        """Caminho relativo ao lakehouse padrão, usado pelo Spark."""
        return posixpath.join(self.raiz_raw, *partes)

    def local(self, caminho: str) -> str:
        """Converte caminho relativo em caminho local para E/S em Python."""
        return posixpath.join(self.montagem_local, caminho)


@dataclass(frozen=True)
class Configuracao:
    """Configuração global: lakehouse padrão e ambientes."""

    lakehouse: str
    ambientes: Mapping[str, Ambiente]

    def ambiente(self, nome: str) -> Ambiente:
        """Retorna o ambiente pelo nome.

        Raises:
            KeyError: se o ambiente não estiver configurado.
        """
        if nome not in self.ambientes:
            disponiveis = ", ".join(sorted(self.ambientes))
            raise KeyError(f"ambiente {nome!r} fora de: {disponiveis}")
        return self.ambientes[nome]


def _ambiente(
    leitor: Leitor, nome: str, valor: Any, caminho: str
) -> Ambiente | None:
    """Lê a resolução física de um ambiente."""
    dados = leitor.mapa(
        valor, caminho, ("schemas", "raiz_raw", "montagem_local")
    )
    schemas = leitor.mapa(
        dados.get("schemas"), f"{caminho}.schemas", v.CAMADAS_DE_SCHEMA
    )
    resolvidos = {}
    for camada in v.CAMADAS_DE_SCHEMA:
        schema = leitor.texto(
            schemas.get(camada), f"{caminho}.schemas.{camada}", _NOME_SCHEMA
        )
        if schema is not None:
            resolvidos[camada] = schema
    raiz = leitor.texto(
        dados.get("raiz_raw"), f"{caminho}.raiz_raw", _CAMINHO_RELATIVO
    )
    if raiz is not None and ".." in raiz.split("/"):
        leitor.erro(f"{caminho}.raiz_raw", "não use '..'")
    montagem = leitor.texto(
        dados.get("montagem_local"), f"{caminho}.montagem_local"
    )
    if montagem is not None and not (
        posixpath.isabs(montagem) or ntpath.isabs(montagem)
    ):
        leitor.erro(f"{caminho}.montagem_local", "use caminho absoluto")
        montagem = None
    completos = len(resolvidos) == len(v.CAMADAS_DE_SCHEMA)
    if not completos or raiz is None or montagem is None:
        return None
    return Ambiente(nome, resolvidos, raiz, montagem)


def carregar_configuracao(dados: Any) -> Configuracao:
    """Lê e valida a configuração de ambientes.

    Raises:
        ContratoInvalido: com todos os problemas encontrados.
    """
    leitor = Leitor()
    raiz = leitor.mapa(
        dados,
        "configuracao",
        ("formato_configuracao", "lakehouse", "ambientes"),
    )
    formato = leitor.inteiro(
        raiz.get("formato_configuracao"), "formato_configuracao"
    )
    if formato is not None and formato != FORMATO_CONFIGURACAO:
        leitor.erro("formato_configuracao", f"não suportado: {formato}")
    lakehouse = leitor.texto(
        raiz.get("lakehouse"), "lakehouse", _NOME_LAKEHOUSE
    )
    declarados = raiz.get("ambientes")
    ambientes = {}
    if not isinstance(declarados, Mapping) or not declarados:
        leitor.erro("ambientes", "declare ao menos um ambiente")
        declarados = {}
    for nome, valor in declarados.items():
        caminho = f"ambientes.{nome}"
        if not isinstance(nome, str) or not _NOME_AMBIENTE.match(nome):
            leitor.erro(caminho, "nome de ambiente inválido")
            continue
        ambiente = _ambiente(leitor, nome, valor, caminho)
        if ambiente is not None:
            ambientes[nome] = ambiente
    leitor.concluir("configuracao")
    return Configuracao(lakehouse, ambientes)
