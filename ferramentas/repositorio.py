"""Carga do conteúdo declarativo versionado (YAML) do repositório.

Estrutura esperada::

    configuracao/ambientes.yaml
    contratos/<fonte>/<base>/base.yaml         descritor da base
    contratos/<fonte>/<base>/<entidade>.yaml   contrato da entidade

As chaves do mapa resultante vêm do caminho do arquivo; o registro
confere se coincidem com a identidade declarada em cada arquivo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO_BASE = "base.yaml"
ARQUIVO_AMBIENTES = Path("configuracao") / "ambientes.yaml"


def carregar_yaml(caminho: Path) -> Any:
    """Lê um arquivo YAML com o carregador seguro."""
    with caminho.open(encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo)


def carregar_dados(raiz: Path = RAIZ) -> dict:
    """Configuração, bases e contratos, chaveados por identificador."""
    dados: dict[str, Any] = {
        "configuracao": carregar_yaml(raiz / ARQUIVO_AMBIENTES),
        "bases": {},
        "contratos": {},
    }
    for pasta in sorted((raiz / "contratos").glob("*/*")):
        if not pasta.is_dir():
            continue
        prefixo = f"{pasta.parent.name}_{pasta.name}"
        for arquivo in sorted(pasta.glob("*.yaml")):
            conteudo = carregar_yaml(arquivo)
            if arquivo.name == ARQUIVO_BASE:
                dados["bases"][prefixo] = conteudo
            else:
                dados["contratos"][f"{prefixo}_{arquivo.stem}"] = conteudo
    return dados
