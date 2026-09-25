"""Retentativa de escritas Delta que perdem disputa de concorrência."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def conflito_concorrente(erro: BaseException) -> bool:
    """Indica se o erro é conflito de concorrência do Delta Lake."""
    texto = f"{type(erro).__name__} {erro}"[:2000]
    return "Concurrent" in texto


def com_retentativa(
    operacao: Callable[[], T],
    tentativas: int = 4,
    espera_inicial: float = 2.0,
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Executa a operação, repetindo apenas em conflito de concorrência.

    A espera dobra a cada tentativa. Qualquer outro erro é propagado de
    imediato.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            return operacao()
        except Exception as erro:
            if tentativa == tentativas or not conflito_concorrente(erro):
                raise
            dormir(espera_inicial * 2 ** (tentativa - 1))
    raise AssertionError("inalcançável")
