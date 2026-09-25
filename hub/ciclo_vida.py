"""Ciclo de vida do contrato: estado declarado × evidência registrada.

O estado é declarado no contrato (parte documental, fora do hash). A
evidência vive no registro operacional de cada ambiente:

- VALIDADO_FISICO exige inspeção COMPATIVEL com o mesmo hash_leitura;
- APROVADO exige também aprovação nominal com o mesmo hash_contrato.

Mudar a parte executável troca o hash e invalida o lastro anterior.
"""

from __future__ import annotations

from collections.abc import Iterable

from hub import vocabulario as v
from hub.contrato import Pendencia
from hub.historico import Evidencias


def verificar_lastro(
    estado: str,
    hash_leitura: str,
    hash_contrato: str,
    evidencias: Evidencias,
) -> list[str]:
    """Confere se o estado declarado tem lastro no ambiente.

    Returns:
        Lista de problemas; vazia quando o contrato pode publicar.
    """
    if estado == v.OBSOLETO:
        return ["contrato OBSOLETO não publica"]
    problemas = []
    ordem = v.ORDEM_ESTADOS[estado]
    validado = hash_leitura in evidencias.inspecoes_compativeis
    if ordem >= v.ORDEM_ESTADOS[v.VALIDADO_FISICO] and not validado:
        problemas.append(
            f"estado {estado} sem inspeção COMPATIVEL neste ambiente para "
            f"hash_leitura {hash_leitura[:12]}"
        )
    if estado == v.APROVADO and hash_contrato not in evidencias.aprovacoes:
        problemas.append(
            "estado APROVADO sem aprovação neste ambiente para "
            f"hash_contrato {hash_contrato[:12]}"
        )
    return problemas


def verificar_aprovavel(
    estado: str,
    pendencias: Iterable[Pendencia],
    hash_leitura: str,
    evidencias: Evidencias,
) -> list[str]:
    """Confere se o contrato pode receber aprovação neste ambiente.

    Aprovação não decorre de lista de pendências vazia: ela exige
    inspeção compatível e é registrada de forma nominal e datada.
    """
    problemas = []
    if estado == v.OBSOLETO:
        problemas.append("contrato OBSOLETO não pode ser aprovado")
    if hash_leitura not in evidencias.inspecoes_compativeis:
        problemas.append(
            "aprovação exige inspeção COMPATIVEL neste ambiente para "
            f"hash_leitura {hash_leitura[:12]}"
        )
    for pendencia in pendencias:
        problemas.append(f"pendência aberta: {pendencia.descricao}")
    return problemas
