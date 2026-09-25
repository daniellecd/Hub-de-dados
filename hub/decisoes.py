"""Decisões puras do motor.

Nenhuma função aqui depende de Spark. Cada verificação devolve a lista
de problemas encontrados (vazia quando aprovada); o executor converte os
problemas em ``BloqueioPublicacao`` e registra a tentativa.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from hub import vocabulario as v

_COMPETENCIA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

PUBLICAR = "PUBLICAR"
RETIRAR = "QUARENTENA"
BLOQUEAR = "BLOQUEIO"


def validar_competencia(competencia: str) -> list[str]:
    """Confere o formato AAAA-MM da competência."""
    if not isinstance(competencia, str) or not _COMPETENCIA.match(competencia):
        return [f"competência inválida {competencia!r}; use AAAA-MM"]
    return []


def destino_da_linha(acoes: Iterable[str]) -> str:
    """Destino de uma linha a partir das ações de suas violações.

    Qualquer BLOQUEIA_PUBLICACAO bloqueia a publicação inteira; qualquer
    ação de quarentena retira a linha; ALERTA (ou nenhuma violação)
    mantém a linha publicada.
    """
    acoes = set(acoes)
    if v.BLOQUEIA_PUBLICACAO in acoes:
        return BLOQUEAR
    if acoes & v.ACOES_QUE_RETIRAM:
        return RETIRAR
    return PUBLICAR


def gera_alerta(acoes: Iterable[str]) -> bool:
    """Indica se alguma ação registra alerta na execução."""
    return bool(set(acoes) & v.ACOES_QUE_ALERTAM)


@dataclass(frozen=True)
class Parte:
    """Arquivo físico lido por uma entidade.

    ``parte`` é o caminho relativo à pasta da aquisição (ex.: nome do
    arquivo ou <zip sem extensão>/<membro>), estável entre aquisições.
    """

    parte: str
    caminho: str
    sha256: str
    bytes: int


def selecionar_partes(arquivos: Iterable[Mapping], padrao: str) -> list[Parte]:
    """Filtra os arquivos legíveis da aquisição pelo padrão da entidade.

    A comparação usa só o nome do arquivo e ignora maiúsculas.
    """
    selecionadas = []
    for arquivo in arquivos:
        nome = posixpath.basename(arquivo["caminho"])
        if fnmatch.fnmatchcase(nome.lower(), padrao.lower()):
            selecionadas.append(
                Parte(
                    parte=arquivo["parte"],
                    caminho=arquivo["caminho"],
                    sha256=arquivo["sha256"],
                    bytes=arquivo["bytes"],
                )
            )
    return sorted(selecionadas, key=lambda parte: parte.parte)


def verificar_quantidade_partes(
    partes: Sequence[Parte], esperada: int | None
) -> list[str]:
    """Confere se a seleção encontrou as partes contratadas."""
    if not partes:
        return ["nenhum arquivo da aquisição corresponde ao contrato"]
    if esperada is not None and len(partes) != esperada:
        return [
            f"{len(partes)} partes encontradas; contrato espera {esperada}"
        ]
    return []


def verificar_cabecalho(
    encontrado: Sequence[str], esperado: Sequence[Sequence[str]]
) -> list[str]:
    """Compara o cabeçalho físico com o layout declarado (nome e posição).

    Args:
        encontrado: nomes lidos na primeira linha do arquivo.
        esperado: por posição, o nome declarado seguido dos aliases.
    """
    nomes = [nome.strip().lstrip("﻿").strip() for nome in encontrado]
    problemas = []
    if len(nomes) != len(esperado):
        problemas.append(
            f"cabeçalho com {len(nomes)} colunas; contrato declara "
            f"{len(esperado)}"
        )
    posicao_declarada = {
        nome: posicao
        for posicao, aceitos in enumerate(esperado)
        for nome in aceitos
    }
    for posicao, nome in enumerate(nomes):
        declarada = posicao_declarada.get(nome)
        if declarada is None:
            problemas.append(f"coluna não declarada: {nome!r}")
        elif declarada != posicao:
            problemas.append(
                f"coluna {nome!r} na posição {posicao + 1}; contrato "
                f"declara {declarada + 1}"
            )
    presentes = set(nomes)
    for aceitos in esperado:
        if not presentes.intersection(aceitos):
            problemas.append(f"coluna ausente no arquivo: {aceitos[0]!r}")
    return problemas


def linhas_origem(
    fisicas: Mapping[str, int], partes: Iterable[str], cabecalho: bool
) -> int:
    """Registros esperados pela contagem física (independente do parser)."""
    desconto = 1 if cabecalho else 0
    return sum(max(fisicas.get(parte, 0) - desconto, 0) for parte in partes)


def verificar_partes_lidas(
    partes: Sequence[str],
    fisicas: Mapping[str, int],
    lidas: Mapping[str, int],
    validas: Mapping[str, int],
    cabecalho: bool,
) -> list[str]:
    """Reconcilia cada parte: linhas físicas × registros lidos.

    Também exige que toda parte contratada contribua com ao menos uma
    linha válida: arquivo sem registros é anomalia, não sucesso.
    """
    problemas = []
    desconto = 1 if cabecalho else 0
    for parte in partes:
        esperado = max(fisicas.get(parte, 0) - desconto, 0)
        encontrado = lidas.get(parte, 0)
        if encontrado != esperado:
            problemas.append(
                f"parte {parte}: {esperado} linhas físicas e {encontrado} "
                "registros lidos"
            )
        if validas.get(parte, 0) == 0:
            problemas.append(f"parte {parte} sem nenhuma linha válida")
    for parte in sorted((set(lidas) | set(fisicas)) - set(partes)):
        problemas.append(f"parte não contratada foi lida: {parte}")
    return problemas


def verificar_tolerancia(
    malformadas: int, lidas: int, tolerancia: float
) -> list[str]:
    """Acima da tolerância, linhas malformadas são divergência estrutural."""
    if lidas == 0 or malformadas / lidas <= tolerancia:
        return []
    return [
        f"{malformadas} de {lidas} linhas malformadas excedem a tolerância "
        f"de {tolerancia:.4%}: divergência estrutural"
    ]


def verificar_total_declarado(total: int, lidas: int) -> list[str]:
    """Compara os registros lidos com o total publicado pela fonte."""
    if total == lidas:
        return []
    return [f"total declarado pela fonte ({total}) difere do lido ({lidas})"]


def verificar_reconciliacao(
    origem: int, publicadas: int, quarentena: int
) -> list[str]:
    """Identidade obrigatória: origem = publicadas + quarentena."""
    if origem == publicadas + quarentena:
        return []
    return [
        f"reconciliação falhou: origem {origem} != publicadas {publicadas}"
        f" + quarentena {quarentena}"
    ]


def verificar_competencia(
    solicitada: str, vigente: str | None, permitir_anterior: bool
) -> list[str]:
    """Snapshot não regride de competência sem pedido explícito."""
    if vigente is None or solicitada >= vigente or permitir_anterior:
        return []
    return [
        f"competência {solicitada} é anterior à vigente {vigente}; use "
        "permitir_competencia_anterior para reverter"
    ]


def verificar_versao(
    versao: int, hash_contrato: str, hashes_por_versao: Mapping[int, set]
) -> list[str]:
    """Mesma versão com parte executável diferente é mudança silenciosa."""
    publicados = set(hashes_por_versao.get(versao, set()))
    if publicados - {hash_contrato}:
        return [
            f"versão {versao} já foi publicada com outro hash_contrato; "
            "incremente a versão do contrato"
        ]
    return []


def verificar_procedencia(
    publicacao_bronze: Mapping | None, competencia: str, hash_leitura: str
) -> list[str]:
    """A Silver só lê Bronze publicada pela mesma seção de leitura."""
    if publicacao_bronze is None:
        return ["não há publicação Bronze efetiva neste ambiente"]
    problemas = []
    if publicacao_bronze["competencia"] != competencia:
        problemas.append(
            f"Bronze vigente é da competência "
            f"{publicacao_bronze['competencia']}; solicitada {competencia}"
        )
    if publicacao_bronze["hash_leitura"] != hash_leitura:
        problemas.append(
            "Bronze vigente foi publicada com outro hash_leitura; "
            "reprocesse a Bronze"
        )
    return problemas


def verificar_snapshot_bronze(
    contagens: Mapping[tuple[str, str], int], publicacao_bronze: Mapping
) -> list[str]:
    """Confere se a tabela Bronze contém exatamente a publicação registrada.

    Args:
        contagens: linhas por (id_execucao, competencia) lidas da tabela.
        publicacao_bronze: registro da publicação Bronze efetiva.
    """
    esperado = (
        publicacao_bronze["id_execucao"],
        publicacao_bronze["competencia"],
    )
    problemas = []
    if set(contagens) != {esperado}:
        problemas.append(
            f"tabela Bronze contém {sorted(contagens)}; esperado {esperado}"
        )
    total = sum(contagens.values())
    if total != publicacao_bronze["linhas_publicadas"]:
        problemas.append(
            f"tabela Bronze tem {total} linhas; publicação registrou "
            f"{publicacao_bronze['linhas_publicadas']}"
        )
    return problemas


@dataclass(frozen=True)
class DiferencaSchema:
    """Diferença entre o schema físico atual e o planejado."""

    adicionadas: tuple[str, ...]
    removidas: tuple[str, ...]
    alteradas: tuple[str, ...]
    reordenada: bool

    @property
    def vazia(self) -> bool:
        """Indica schemas equivalentes."""
        return not (
            self.adicionadas
            or self.removidas
            or self.alteradas
            or self.reordenada
        )

    def descrever(self) -> str:
        """Descrição legível da diferença."""
        partes = []
        if self.adicionadas:
            partes.append(f"adicionadas {list(self.adicionadas)}")
        if self.removidas:
            partes.append(f"removidas {list(self.removidas)}")
        if self.alteradas:
            partes.append(f"tipo alterado {list(self.alteradas)}")
        if self.reordenada:
            partes.append("ordem alterada")
        return "; ".join(partes)


def diferenca_schema(
    atual: Sequence[tuple[str, str]], planejado: Sequence[tuple[str, str]]
) -> DiferencaSchema:
    """Compara nomes, tipos e ordem das colunas."""
    tipos_atuais = dict(atual)
    tipos_planejados = dict(planejado)
    comuns_atual = [nome for nome, _ in atual if nome in tipos_planejados]
    comuns_planejado = [nome for nome, _ in planejado if nome in tipos_atuais]
    return DiferencaSchema(
        adicionadas=tuple(
            nome for nome, _ in planejado if nome not in tipos_atuais
        ),
        removidas=tuple(
            nome for nome, _ in atual if nome not in tipos_planejados
        ),
        alteradas=tuple(
            nome
            for nome, tipo in planejado
            if nome in tipos_atuais and tipos_atuais[nome] != tipo
        ),
        reordenada=comuns_atual != comuns_planejado,
    )


def verificar_mudanca_schema(
    diferenca: DiferencaSchema,
    versao_contrato: int,
    versao_vigente: int | None,
) -> list[str]:
    """Mudança de schema só entra com nova versão de contrato."""
    if diferenca.vazia:
        return []
    if versao_vigente is None:
        return [
            "tabela existente diverge do contrato e não tem publicação "
            f"registrada: {diferenca.descrever()}"
        ]
    if versao_contrato <= versao_vigente:
        return [
            f"schema diverge do publicado pela versão {versao_vigente} sem "
            f"nova versão de contrato: {diferenca.descrever()}"
        ]
    return []


_GRAVIDADE_DIAGNOSTICO = (v.CONFERIDA, v.COM_ORFAOS, v.REFERENCIA_AUSENTE)


def resultado_diagnostico(itens: Iterable[Mapping]) -> str:
    """Resultado geral do diagnóstico: o relacionamento mais grave."""
    resultados = [item["resultado"] for item in itens]
    if not resultados:
        return v.CONFERIDA
    return max(resultados, key=_GRAVIDADE_DIAGNOSTICO.index)
