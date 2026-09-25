"""Leitura validada de estruturas declarativas.

Usado para contratos, descritores de base e configuração de ambiente. O
leitor acumula todos os problemas com o caminho do campo, para que a
validação reporte tudo de uma vez em vez de parar no primeiro erro.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from hub.erros import ContratoInvalido


class Leitor:
    """Acumula problemas de validação com o caminho do campo."""

    def __init__(self) -> None:
        self.problemas: list[str] = []

    def erro(self, caminho: str, mensagem: str) -> None:
        """Registra um problema no campo indicado."""
        self.problemas.append(f"{caminho}: {mensagem}")

    def concluir(self, origem: str) -> None:
        """Encerra a leitura.

        Raises:
            ContratoInvalido: se algum problema foi registrado.
        """
        if self.problemas:
            raise ContratoInvalido(origem, self.problemas)

    def mapa(
        self,
        valor: Any,
        caminho: str,
        obrigatorias: Iterable[str] = (),
        opcionais: Iterable[str] = (),
    ) -> dict:
        """Lê um mapa e confere chaves obrigatórias e desconhecidas."""
        if not isinstance(valor, Mapping):
            self.erro(caminho, "deve ser um mapa")
            return {}
        obrigatorias = tuple(obrigatorias)
        permitidas = set(obrigatorias) | set(opcionais)
        for chave in valor:
            if chave not in permitidas:
                self.erro(caminho, f"chave desconhecida: {chave}")
        for chave in obrigatorias:
            if chave not in valor:
                self.erro(caminho, f"chave obrigatória ausente: {chave}")
        return dict(valor)

    def texto(
        self,
        valor: Any,
        caminho: str,
        padrao: re.Pattern | None = None,
        opcional: bool = False,
    ) -> str | None:
        """Lê um texto não vazio, opcionalmente conferindo um padrão."""
        if valor is None:
            if not opcional:
                self.erro(caminho, "obrigatório")
            return None
        if not isinstance(valor, str) or valor == "":
            self.erro(caminho, "deve ser texto não vazio")
            return None
        if padrao is not None and not padrao.match(valor):
            self.erro(caminho, f"fora do padrão {padrao.pattern}: {valor!r}")
            return None
        return valor

    def inteiro(
        self,
        valor: Any,
        caminho: str,
        minimo: int | None = None,
        maximo: int | None = None,
        opcional: bool = False,
    ) -> int | None:
        """Lê um inteiro (booleano não é aceito) dentro dos limites."""
        if valor is None:
            if not opcional:
                self.erro(caminho, "obrigatório")
            return None
        if isinstance(valor, bool) or not isinstance(valor, int):
            self.erro(caminho, "deve ser inteiro")
            return None
        if minimo is not None and valor < minimo:
            self.erro(caminho, f"deve ser maior ou igual a {minimo}")
            return None
        if maximo is not None and valor > maximo:
            self.erro(caminho, f"deve ser menor ou igual a {maximo}")
            return None
        return valor

    def fracao(self, valor: Any, caminho: str) -> float | None:
        """Lê um número no intervalo [0, 1)."""
        if valor is None:
            self.erro(caminho, "obrigatório")
            return None
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            self.erro(caminho, "deve ser número")
            return None
        if not 0 <= valor < 1:
            self.erro(caminho, "deve estar no intervalo [0, 1)")
            return None
        return float(valor)

    def booleano(self, valor: Any, caminho: str, padrao: bool) -> bool:
        """Lê um booleano; ausência assume o padrão informado."""
        if valor is None:
            return padrao
        if not isinstance(valor, bool):
            self.erro(caminho, "deve ser true ou false")
            return padrao
        return valor

    def booleano_obrigatorio(self, valor: Any, caminho: str) -> bool | None:
        """Lê um booleano que precisa estar declarado."""
        if not isinstance(valor, bool):
            self.erro(caminho, "obrigatório: true ou false")
            return None
        return valor

    def lista(self, valor: Any, caminho: str, opcional: bool = True) -> list:
        """Lê uma lista; ausência retorna lista vazia quando opcional."""
        if valor is None:
            if not opcional:
                self.erro(caminho, "obrigatório")
            return []
        if not isinstance(valor, list):
            self.erro(caminho, "deve ser uma lista")
            return []
        return valor

    def escolha(
        self,
        valor: Any,
        caminho: str,
        opcoes: Iterable[str],
        opcional: bool = False,
    ) -> str | None:
        """Lê um valor que precisa pertencer ao vocabulário informado."""
        opcoes = tuple(opcoes)
        if valor is None:
            if not opcional:
                self.erro(caminho, "obrigatório")
            return None
        if valor not in opcoes:
            self.erro(caminho, f"{valor!r} fora de {', '.join(opcoes)}")
            return None
        return valor

    def unicos(self, valores: Iterable[str], caminho: str) -> None:
        """Registra valores repetidos."""
        vistos: set[str] = set()
        for valor in valores:
            if valor in vistos:
                self.erro(caminho, f"valor repetido: {valor}")
            vistos.add(valor)
