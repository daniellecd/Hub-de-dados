"""Apoio aos testes: dados do repositório e artefatos mínimos válidos."""

from __future__ import annotations

import copy

from ferramentas.repositorio import RAIZ, carregar_dados
from hub.contrato import Contrato, carregar_contrato
from hub.registro import Registro

_CONTRATO_MINIMO = {
    "formato_contrato": 1,
    "identidade": {"fonte": "fonte", "base": "base", "entidade": "itens"},
    "versao": 1,
    "descricao": "Itens de teste.",
    "selecao": {"arquivo": "itens.csv", "quantidade_partes": 1},
    "leitura": {
        "separador": ";",
        "aspas": '"',
        "escape": '"',
        "codificacao": "utf-8",
        "cabecalho": True,
        "tolerancia_malformadas": 0.01,
    },
    "transformacoes_padrao": ["aparar", "vazio_como_nulo"],
    "colunas": [
        {
            "nome": "codigo",
            "cabecalho": "CODIGO",
            "tipo": "texto",
            "nulavel": False,
        },
        {
            "nome": "valor",
            "cabecalho": "VALOR",
            "tipo": "decimal",
            "precisao": 10,
            "escala": 2,
            "separador_decimal": ",",
        },
        {
            "nome": "data",
            "cabecalho": "DATA",
            "tipo": "data",
            "formato": "AAAAMMDD",
        },
        {
            "nome": "situacao",
            "cabecalho": "SITUACAO",
            "tipo": "texto",
            "dominio": "situacao",
        },
    ],
    "chave": ["codigo"],
    "dominios": {
        "situacao": {
            "tipo": "literal",
            "valores": {"A": "Ativo", "I": "Inativo"},
            "coluna_descricao": "situacao_descricao",
        }
    },
    "regras": [
        {
            "id": "valor_positivo",
            "expressao": "valor IS NULL OR valor > 0",
            "colunas_referenciadas": ["valor"],
            "acao": "ALERTA",
            "dimensao": "Accuracy",
        }
    ],
    "acoes_padrao": {
        "linha_malformada": "QUARENTENA",
        "nulidade": "QUARENTENA",
        "conversao": "QUARENTENA",
        "chave_nula": "QUARENTENA",
        "chave_duplicada": "QUARENTENA_GRUPO",
        "dominio": "QUARENTENA_E_ALERTA",
    },
    "documentacao": {"estado": "PROVISORIO_DOCUMENTAL", "pendencias": []},
}

_CONFIGURACAO_MINIMA = {
    "formato_configuracao": 1,
    "lakehouse": "lh_teste",
    "ambientes": {
        "dev": {
            "schemas": {
                "bronze": "bronze",
                "silver": "silver",
                "controle": "controle",
            },
            "raiz_raw": "Files/raw",
            "montagem_local": "/lakehouse/default",
        }
    },
}

_BASE_MINIMA = {
    "formato_base": 1,
    "identidade": {"fonte": "fonte", "base": "base"},
    "aquisicao": {"url_base": "file:///origem/", "arquivos": ["itens.zip"]},
}


def contrato_minimo() -> dict:
    """Cópia de um contrato pequeno e válido."""
    return copy.deepcopy(_CONTRATO_MINIMO)


def configuracao_minima(montagem: str = "/lakehouse/default") -> dict:
    """Cópia de uma configuração com o ambiente dev."""
    configuracao = copy.deepcopy(_CONFIGURACAO_MINIMA)
    configuracao["ambientes"]["dev"]["montagem_local"] = montagem
    return configuracao


def base_minima() -> dict:
    """Cópia de um descritor de base válido."""
    return copy.deepcopy(_BASE_MINIMA)


def carregar(dados: dict) -> Contrato:
    """Carrega um contrato a partir do mapa declarativo."""
    return carregar_contrato(dados)


def dados_repositorio() -> dict:
    """Conteúdo declarativo versionado no repositório."""
    return carregar_dados(RAIZ)


def registro_repositorio() -> Registro:
    """Registro validado com os contratos do repositório."""
    return Registro.de_dicionario(dados_repositorio())


def registro_minimo(contrato: dict | None = None) -> Registro:
    """Registro com a configuração, a base e um contrato mínimos."""
    contrato = contrato or contrato_minimo()
    identidade = contrato["identidade"]
    chave = f"{identidade['fonte']}_{identidade['base']}"
    return Registro.de_dicionario(
        {
            "configuracao": configuracao_minima(),
            "bases": {chave: base_minima()},
            "contratos": {f"{chave}_{identidade['entidade']}": contrato},
        }
    )
