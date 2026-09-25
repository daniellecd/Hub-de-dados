"""Registro operacional de execução e esquemas das tabelas do motor.

Cada tentativa (aquisição, inspeção, publicação, aprovação, diagnóstico
ou catálogo) gera uma linha em ``controle.execucoes``, inclusive as que
falham ou são bloqueadas. O ``id_execucao`` distingue tentativas e nunca
é usado para deduplicar publicações.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hub import vocabulario as v

TABELA_EXECUCOES = "execucoes"
TABELA_QUARENTENA = "quarentena"
LIMITE_MOTIVO = 4000

COLUNAS_EXECUCOES = (
    ("id_execucao", "STRING"),
    ("identificador", "STRING"),
    ("tipo", "STRING"),
    ("status", "STRING"),
    ("ambiente", "STRING"),
    ("fonte", "STRING"),
    ("base", "STRING"),
    ("entidade", "STRING"),
    ("competencia", "STRING"),
    ("tabela_destino", "STRING"),
    ("versao_contrato", "INT"),
    ("estado_contrato", "STRING"),
    ("hash_leitura", "STRING"),
    ("hash_contrato", "STRING"),
    ("publication_fingerprint", "STRING"),
    ("id_execucao_origem", "STRING"),
    ("versao_delta", "BIGINT"),
    ("linhas_origem", "BIGINT"),
    ("linhas_publicadas", "BIGINT"),
    ("linhas_quarentena", "BIGINT"),
    ("resultado", "STRING"),
    ("responsavel", "STRING"),
    ("motivo", "STRING"),
    ("detalhes", "STRING"),
    ("versao_motor", "STRING"),
    ("iniciado_em", "TIMESTAMP"),
    ("finalizado_em", "TIMESTAMP"),
)

COLUNAS_QUARENTENA = (
    ("id_quarentena", "STRING"),
    ("identificador", "STRING"),
    ("camada", "STRING"),
    ("fonte", "STRING"),
    ("base", "STRING"),
    ("entidade", "STRING"),
    ("competencia", "STRING"),
    ("publication_fingerprint", "STRING"),
    ("versao_contrato", "INT"),
    ("hash_leitura", "STRING"),
    ("hash_contrato", "STRING"),
    ("id_execucao", "STRING"),
    ("chave", "STRING"),
    ("grupo_problema", "STRING"),
    ("motivos", "STRING"),
    ("registro", "STRING"),
    ("arquivo_origem", "STRING"),
    ("ocorrencia", "INT"),
    ("registrado_em", "TIMESTAMP"),
)

# As duas tabelas são particionadas pelo identificador lógico: execuções
# paralelas de entidades diferentes não disputam os mesmos arquivos Delta.
COLUNA_PARTICAO = "identificador"


def agora_utc() -> datetime:
    """Instante atual em UTC."""
    return datetime.now(UTC)


def novo_id_execucao(
    momento: datetime | None = None, sufixo: str | None = None
) -> str:
    """Identificador da tentativa no formato AAAAMMDDTHHMMSSZ-<8 hex>."""
    momento = momento or agora_utc()
    sufixo = sufixo or secrets.token_hex(4)
    return f"{momento:%Y%m%dT%H%M%SZ}-{sufixo}"


@dataclass
class RegistroExecucao:
    """Estado de uma tentativa, gravado no início e no fim da execução."""

    id_execucao: str
    identificador: str
    tipo: str
    ambiente: str
    versao_motor: str
    fonte: str | None = None
    base: str | None = None
    entidade: str | None = None
    competencia: str | None = None
    status: str = v.EM_EXECUCAO
    tabela_destino: str | None = None
    versao_contrato: int | None = None
    estado_contrato: str | None = None
    hash_leitura: str | None = None
    hash_contrato: str | None = None
    publication_fingerprint: str | None = None
    id_execucao_origem: str | None = None
    versao_delta: int | None = None
    linhas_origem: int | None = None
    linhas_publicadas: int | None = None
    linhas_quarentena: int | None = None
    resultado: str | None = None
    responsavel: str | None = None
    motivo: str | None = None
    detalhes: dict = field(default_factory=dict)
    alertas: list[str] = field(default_factory=list)
    iniciado_em: datetime = field(default_factory=agora_utc)
    finalizado_em: datetime | None = None

    def alertar(self, mensagem: str) -> None:
        """Registra um alerta; a execução termina SUCESSO_COM_ALERTA."""
        self.alertas.append(mensagem)

    def status_sucesso(self) -> str:
        """Status de término sem bloqueio nem falha."""
        return v.SUCESSO_COM_ALERTA if self.alertas else v.SUCESSO

    def finalizar(
        self,
        status: str,
        motivo: str | None = None,
        momento: datetime | None = None,
    ) -> None:
        """Encerra a tentativa com o status e o motivo informados."""
        self.status = status
        if motivo:
            self.motivo = motivo[:LIMITE_MOTIVO]
        self.finalizado_em = momento or agora_utc()

    def detalhes_json(self) -> str | None:
        """Detalhes e alertas serializados como JSON (coluna escalar)."""
        detalhes = dict(self.detalhes)
        if self.alertas:
            detalhes["alertas"] = list(self.alertas)
        if not detalhes:
            return None
        return json.dumps(detalhes, ensure_ascii=False, sort_keys=True)

    def para_linha(self) -> tuple:
        """Valores na ordem de COLUNAS_EXECUCOES."""
        valores = []
        for nome, _ in COLUNAS_EXECUCOES:
            if nome == "detalhes":
                valores.append(self.detalhes_json())
            else:
                valores.append(getattr(self, nome))
        return tuple(valores)

    def resumo(self) -> dict:
        """Resumo exibido no notebook (não é evidência)."""
        return {
            "id_execucao": self.id_execucao,
            "tipo": self.tipo,
            "identificador": self.identificador,
            "competencia": self.competencia,
            "status": self.status,
            "resultado": self.resultado,
            "linhas_origem": self.linhas_origem,
            "linhas_publicadas": self.linhas_publicadas,
            "linhas_quarentena": self.linhas_quarentena,
            "motivo": self.motivo,
        }
