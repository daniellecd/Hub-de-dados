"""Consultas puras sobre o histórico de execuções de um identificador.

O executor Spark lê as linhas de ``controle.execucoes`` de um
identificador e as entrega aqui como dicionários. Assim, as decisões de
lastro, procedência, versão e competência são testáveis sem Spark.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from hub import vocabulario as v


@dataclass(frozen=True)
class Evidencias:
    """Evidências registradas no ambiente para o ciclo de vida."""

    inspecoes_compativeis: frozenset[str]
    aprovacoes: frozenset[str]


def _momento(registro: Mapping) -> datetime:
    """Instante de ordenação: fim da execução ou, na falta, o início."""
    momento = registro.get("finalizado_em") or registro.get("iniciado_em")
    return momento or datetime.min


class Historico:
    """Execuções de um identificador, da mais recente para a mais antiga."""

    def __init__(self, registros: Iterable[Mapping]) -> None:
        self._registros = sorted(
            (dict(registro) for registro in registros),
            key=_momento,
            reverse=True,
        )

    def efetivos(self, tipo: str) -> list[dict]:
        """Execuções do tipo com status de publicação efetiva."""
        return [
            registro
            for registro in self._registros
            if registro["tipo"] == tipo
            and registro["status"] in v.STATUS_EFETIVOS
        ]

    def ultima_efetiva(self, tipo: str) -> dict | None:
        """Execução efetiva mais recente do tipo, se houver."""
        efetivos = self.efetivos(tipo)
        return efetivos[0] if efetivos else None

    def aquisicao_efetiva(self, competencia: str) -> dict | None:
        """Aquisição mais recente que trouxe arquivos para a competência."""
        for registro in self.efetivos(v.AQUISICAO):
            if (
                registro["competencia"] == competencia
                and registro["resultado"] == v.ADQUIRIDA
            ):
                return registro
        return None

    def evidencias(self) -> Evidencias:
        """Inspeções compatíveis e aprovações registradas."""
        inspecoes = {
            registro["hash_leitura"]
            for registro in self.efetivos(v.INSPECAO)
            if registro["resultado"] == v.COMPATIVEL
        }
        aprovacoes = {
            registro["hash_contrato"]
            for registro in self.efetivos(v.APROVACAO)
            if registro["resultado"] == v.APROVADA
        }
        return Evidencias(frozenset(inspecoes), frozenset(aprovacoes))

    def hashes_por_versao(self) -> dict[int, set[str]]:
        """hash_contrato de cada versão já publicada (Bronze ou Silver)."""
        resultado: dict[int, set[str]] = {}
        for tipo in (v.PUBLICACAO_BRONZE, v.PUBLICACAO_SILVER):
            for registro in self.efetivos(tipo):
                versao = registro["versao_contrato"]
                resultado.setdefault(versao, set()).add(
                    registro["hash_contrato"]
                )
        return resultado
