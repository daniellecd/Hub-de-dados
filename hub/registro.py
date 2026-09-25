"""Registro dos artefatos declarativos carregados: ambientes, bases e
contratos, com as validações que cruzam arquivos diferentes.

O mesmo dicionário é produzido pelo gerador a partir do YAML versionado
e embutido no notebook-biblioteca; por isso o Fabric não precisa de YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hub import vocabulario as v
from hub.ambiente import Ambiente, Configuracao, carregar_configuracao
from hub.bases import DescritorBase, carregar_base
from hub.contrato import REFERENCIA, Contrato, carregar_contrato
from hub.erros import ContratoInvalido

_TIPOS_TOTAL = (v.INTEIRO, v.INTEIRO_LONGO)


@dataclass(frozen=True)
class Registro:
    """Contratos, bases e ambientes validados."""

    configuracao: Configuracao
    bases: Mapping[str, DescritorBase]
    contratos: Mapping[str, Contrato]
    versao_motor: str

    @classmethod
    def de_dicionario(
        cls, dados: Mapping[str, Any], versao_motor: str = "local"
    ) -> Registro:
        """Carrega e valida todo o conteúdo declarativo.

        Args:
            dados: mapa com as chaves configuracao, bases e contratos.
            versao_motor: identificação do código do motor em execução.

        Raises:
            ContratoInvalido: com os problemas de todos os artefatos.
        """
        problemas: list[str] = []
        configuracao = _carregar(
            problemas, carregar_configuracao, dados.get("configuracao")
        )
        bases = {}
        for chave, conteudo in sorted(dados.get("bases", {}).items()):
            base = _carregar(problemas, carregar_base, conteudo, chave)
            if base is not None:
                _conferir_chave(problemas, chave, base.identificador)
                bases[base.identificador] = base
        contratos = {}
        for chave, conteudo in sorted(dados.get("contratos", {}).items()):
            contrato = _carregar(problemas, carregar_contrato, conteudo, chave)
            if contrato is not None:
                _conferir_chave(problemas, chave, contrato.identificador)
                contratos[contrato.identificador] = contrato
        if configuracao is not None:
            _validar_cruzamentos(problemas, bases, contratos)
        if problemas:
            raise ContratoInvalido("registro", problemas)
        return cls(configuracao, bases, contratos, versao_motor)

    def ambiente(self, nome: str) -> Ambiente:
        """Resolução física do ambiente informado."""
        return self.configuracao.ambiente(nome)

    def contrato(self, identificador: str) -> Contrato:
        """Contrato pelo identificador lógico (fonte_base_entidade)."""
        if identificador not in self.contratos:
            raise KeyError(f"contrato inexistente: {identificador}")
        return self.contratos[identificador]

    def base(self, identificador: str) -> DescritorBase:
        """Descritor da base pelo identificador (fonte_base)."""
        if identificador not in self.bases:
            raise KeyError(f"base inexistente: {identificador}")
        return self.bases[identificador]

    def contratos_da_base(self, identificador_base: str) -> list[Contrato]:
        """Contratos de uma base, em ordem de identificador."""
        return [
            contrato
            for nome, contrato in sorted(self.contratos.items())
            if contrato.identidade.identificador_base == identificador_base
        ]

    def contrato_do_total(self, contrato: Contrato) -> Contrato | None:
        """Contrato da entidade que publica o total declarado."""
        total = contrato.total_declarado
        if total is None:
            return None
        base = contrato.identidade.identificador_base
        return self.contrato(f"{base}_{total.entidade}")


def _carregar(problemas: list[str], carregar, conteudo, *argumentos):
    """Executa um carregador acumulando os problemas encontrados."""
    try:
        return carregar(conteudo, *argumentos)
    except ContratoInvalido as erro:
        problemas.extend(f"{erro.origem}: {p}" for p in erro.problemas)
        return None


def _conferir_chave(problemas: list[str], chave: str, esperado: str) -> None:
    """A chave do dicionário precisa ser o identificador do artefato."""
    if chave != esperado:
        problemas.append(f"{chave}: identificador declarado é {esperado}")


def _validar_cruzamentos(
    problemas: list[str],
    bases: Mapping[str, DescritorBase],
    contratos: Mapping[str, Contrato],
) -> None:
    """Validações que dependem de mais de um artefato."""
    for identificador, contrato in contratos.items():
        base = contrato.identidade.identificador_base
        if base not in bases:
            problemas.append(f"{identificador}: base {base} não declarada")
        for dominio in contrato.dominios.values():
            if dominio.tipo == REFERENCIA:
                _validar_referencia(problemas, contrato, dominio, contratos)
        if contrato.total_declarado is not None:
            _validar_total(problemas, contrato, contratos)


def _validar_referencia(problemas, contrato, dominio, contratos) -> None:
    """A referência precisa apontar para coluna texto de contrato existente."""
    alvo = dominio.tabela.identificador
    origem = f"{contrato.identificador}: domínio {dominio.nome}"
    if alvo not in contratos:
        problemas.append(f"{origem} referencia contrato inexistente {alvo}")
        return
    try:
        coluna = contratos[alvo].coluna(dominio.coluna)
    except KeyError:
        problemas.append(f"{origem}: coluna {dominio.coluna} não existe")
        return
    if coluna.tipo != v.TEXTO:
        problemas.append(f"{origem}: coluna referenciada deve ser texto")


def _validar_total(problemas, contrato, contratos) -> None:
    """O total declarado aponta para coluna inteira da mesma base."""
    total = contrato.total_declarado
    alvo = f"{contrato.identidade.identificador_base}_{total.entidade}"
    origem = f"{contrato.identificador}: reconciliacao"
    if alvo not in contratos:
        problemas.append(f"{origem} aponta para contrato inexistente {alvo}")
        return
    try:
        coluna = contratos[alvo].coluna(total.coluna)
    except KeyError:
        problemas.append(f"{origem}: coluna {total.coluna} não existe")
        return
    if coluna.tipo not in _TIPOS_TOTAL:
        problemas.append(f"{origem}: coluna do total deve ser inteira")
    if coluna.ausente_na_origem:
        problemas.append(f"{origem}: coluna do total ausente na origem")
