"""Exceções do motor."""


class ContratoInvalido(ValueError):
    """Contrato, descritor de base ou configuração fora do formato."""

    def __init__(self, origem: str, problemas: list[str]) -> None:
        self.origem = origem
        self.problemas = list(problemas)
        detalhe = "\n".join(f"  - {p}" for p in self.problemas)
        super().__init__(
            f"{origem}: {len(self.problemas)} problema(s)\n{detalhe}"
        )


class BloqueioPublicacao(Exception):
    """Interrupção decidida pelo motor; a execução fica BLOQUEADA."""

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = list(problemas)
        super().__init__("; ".join(self.problemas))


def exigir(problemas: list[str]) -> None:
    """Interrompe a publicação quando a lista de problemas não é vazia.

    Args:
        problemas: resultado de uma verificação pura (vazio = aprovado).

    Raises:
        BloqueioPublicacao: se houver ao menos um problema.
    """
    if problemas:
        raise BloqueioPublicacao(problemas)
