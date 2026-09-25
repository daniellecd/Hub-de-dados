"""Modelo, leitura e validação do contrato de entidade.

O contrato declara o que deve existir: identidade lógica, seleção de
arquivos, dialeto de leitura, colunas, tipos, nulabilidade, chave,
transformações, domínios, regras e a ação de cada violação.

Não declara nome físico, caminho de ambiente, estado de execução,
contagem, timestamp nem detalhe de implementação Spark.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hub import vocabulario as v
from hub.expressao import validar_expressao
from hub.leitor import Leitor

FORMATO_CONTRATO = 1
LIMITE_DOMINIO_LITERAL = 15

PADRAO_FONTE = re.compile(r"^[a-z][a-z0-9]*$")
PADRAO_NOME = re.compile(r"^[a-z][a-z0-9_]*$")
_PADRAO_DATA = re.compile(r"^(AAAA|MM|DD|[-/.])+$")

LITERAL = "literal"
REFERENCIA = "referencia"


@dataclass(frozen=True)
class Identidade:
    """Identidade lógica: fonte, base, entidade e especificação opcional."""

    fonte: str
    base: str
    entidade: str
    especificacao: str | None = None

    @property
    def identificador(self) -> str:
        """Nome lógico do objeto: fonte_base_entidade[_especificacao]."""
        partes = [self.fonte, self.base, self.entidade]
        if self.especificacao:
            partes.append(self.especificacao)
        return "_".join(partes)

    @property
    def identificador_base(self) -> str:
        """Nome lógico da base: fonte_base."""
        return f"{self.fonte}_{self.base}"


@dataclass(frozen=True)
class Selecao:
    """Padrão do arquivo lido pela entidade dentro da publicação."""

    arquivo: str
    quantidade_partes: int | None


@dataclass(frozen=True)
class Leitura:
    """Dialeto físico do arquivo."""

    separador: str
    aspas: str
    escape: str
    codificacao: str
    cabecalho: bool
    tolerancia_malformadas: float


@dataclass(frozen=True)
class Transformacao:
    """Transformação do vocabulário fechado com seus parâmetros."""

    tipo: str
    parametros: Mapping[str, Any]


@dataclass(frozen=True)
class Coluna:
    """Coluna da entidade: layout de origem e tratamento na Silver."""

    nome: str
    tipo: str
    cabecalho: str | None
    aliases: tuple[str, ...]
    ausente_na_origem: bool
    nulavel: bool
    formato: str | None
    precisao: int | None
    escala: int | None
    separador_decimal: str | None
    transformacoes: tuple[Transformacao, ...]
    dominio: str | None
    descricao: str | None


@dataclass(frozen=True)
class Dominio:
    """Domínio literal (valores no contrato) ou por referência a tabela."""

    nome: str
    tipo: str
    valores: Mapping[str, str]
    coluna_descricao: str | None
    tabela: Identidade | None
    coluna: str | None
    descricao: str | None


@dataclass(frozen=True)
class Regra:
    """Regra de negócio expressa como predicado SQL validado."""

    id: str
    expressao: str
    colunas_referenciadas: tuple[str, ...]
    acao: str
    dimensao: str
    descricao: str | None


@dataclass(frozen=True)
class TotalDeclarado:
    """Total de registros publicado pela própria fonte em outra entidade."""

    entidade: str
    coluna: str


@dataclass(frozen=True)
class Pendencia:
    """Pendência explícita e o estado que ela impede."""

    descricao: str
    impede: str


@dataclass(frozen=True)
class Documentacao:
    """Parte documental do contrato; fica fora do hash."""

    estado: str
    fonte_documental: str | None
    pendencias: tuple[Pendencia, ...]
    observacoes: str | None


@dataclass(frozen=True)
class Contrato:
    """Contrato validado de uma entidade."""

    formato_contrato: int
    identidade: Identidade
    versao: int
    descricao: str | None
    selecao: Selecao
    leitura: Leitura
    transformacoes_padrao: tuple[Transformacao, ...]
    colunas: tuple[Coluna, ...]
    chave: tuple[str, ...]
    dominios: Mapping[str, Dominio]
    regras: tuple[Regra, ...]
    acoes_padrao: Mapping[str, str]
    total_declarado: TotalDeclarado | None
    documentacao: Documentacao

    @property
    def identificador(self) -> str:
        """Nome lógico da entidade."""
        return self.identidade.identificador

    @property
    def colunas_origem(self) -> tuple[Coluna, ...]:
        """Colunas presentes no arquivo, na ordem física."""
        return tuple(c for c in self.colunas if not c.ausente_na_origem)

    def coluna(self, nome: str) -> Coluna:
        """Retorna a coluna pelo nome.

        Raises:
            KeyError: se a coluna não existir.
        """
        for coluna in self.colunas:
            if coluna.nome == nome:
                return coluna
        raise KeyError(nome)

    def dominio_literal(self, coluna: Coluna) -> Dominio | None:
        """Domínio literal da coluna, se houver."""
        dominio = self.dominios.get(coluna.dominio or "")
        if dominio is not None and dominio.tipo == LITERAL:
            return dominio
        return None

    @property
    def colunas_saida(self) -> tuple[str, ...]:
        """Colunas de negócio da Silver, com as descrições de domínio."""
        nomes: list[str] = []
        for coluna in self.colunas:
            nomes.append(coluna.nome)
            dominio = self.dominio_literal(coluna)
            if dominio is not None and dominio.coluna_descricao:
                nomes.append(dominio.coluna_descricao)
        return tuple(nomes)


def ler_identidade(leitor: Leitor, valor: Any, caminho: str):
    """Lê uma identidade lógica (fonte, base, entidade, especificação)."""
    dados = leitor.mapa(
        valor, caminho, ("fonte", "base", "entidade"), ("especificacao",)
    )
    fonte = leitor.texto(dados.get("fonte"), f"{caminho}.fonte", PADRAO_FONTE)
    base = leitor.texto(dados.get("base"), f"{caminho}.base", PADRAO_FONTE)
    entidade = leitor.texto(
        dados.get("entidade"), f"{caminho}.entidade", PADRAO_NOME
    )
    especificacao = leitor.texto(
        dados.get("especificacao"),
        f"{caminho}.especificacao",
        PADRAO_NOME,
        opcional=True,
    )
    if fonte is None or base is None or entidade is None:
        return None
    return Identidade(fonte, base, entidade, especificacao)


def _caractere(leitor: Leitor, valor: Any, caminho: str) -> str | None:
    """Lê um único caractere (separador, aspas, escape)."""
    if not isinstance(valor, str) or len(valor) != 1:
        leitor.erro(caminho, "deve ser um único caractere")
        return None
    return valor


def _selecao(leitor: Leitor, valor: Any) -> Selecao | None:
    """Lê a seção de seleção de arquivos."""
    dados = leitor.mapa(valor, "selecao", ("arquivo",), ("quantidade_partes",))
    arquivo = leitor.texto(dados.get("arquivo"), "selecao.arquivo")
    if arquivo is not None and "/" in arquivo:
        leitor.erro("selecao.arquivo", "use apenas o nome do arquivo")
    partes = leitor.inteiro(
        dados.get("quantidade_partes"),
        "selecao.quantidade_partes",
        minimo=1,
        opcional=True,
    )
    if arquivo is None:
        return None
    return Selecao(arquivo, partes)


def _leitura(leitor: Leitor, valor: Any) -> Leitura | None:
    """Lê o dialeto físico do arquivo."""
    obrigatorias = (
        "separador",
        "aspas",
        "escape",
        "codificacao",
        "cabecalho",
        "tolerancia_malformadas",
    )
    dados = leitor.mapa(valor, "leitura", obrigatorias)
    separador = _caractere(leitor, dados.get("separador"), "leitura.separador")
    aspas = _caractere(leitor, dados.get("aspas"), "leitura.aspas")
    escape = _caractere(leitor, dados.get("escape"), "leitura.escape")
    codificacao = leitor.escolha(
        dados.get("codificacao"), "leitura.codificacao", v.CODIFICACOES
    )
    cabecalho = leitor.booleano_obrigatorio(
        dados.get("cabecalho"), "leitura.cabecalho"
    )
    tolerancia = leitor.fracao(
        dados.get("tolerancia_malformadas"), "leitura.tolerancia_malformadas"
    )
    valores = (separador, aspas, escape, codificacao, cabecalho, tolerancia)
    if any(valor is None for valor in valores):
        return None
    if separador == aspas:
        leitor.erro("leitura", "separador e aspas devem ser diferentes")
    return Leitura(*valores)


def _parametro_valido(valor: Any, especie: str) -> bool:
    """Confere o valor de um parâmetro de transformação."""
    if especie == v.LISTA_TEXTO:
        return (
            isinstance(valor, list)
            and bool(valor)
            and all(isinstance(item, str) for item in valor)
        )
    if especie == v.INTEIRO_POSITIVO:
        return (
            isinstance(valor, int)
            and not isinstance(valor, bool)
            and valor > 0
        )
    if especie == v.CARACTERE:
        return isinstance(valor, str) and len(valor) == 1
    return False


def _transformacao(
    leitor: Leitor, valor: Any, caminho: str
) -> Transformacao | None:
    """Lê uma transformação: nome simples ou {nome: parâmetros}."""
    if isinstance(valor, str):
        nome, parametros = valor, {}
    elif isinstance(valor, Mapping) and len(valor) == 1:
        nome, parametros = next(iter(valor.items()))
        parametros = {} if parametros is None else parametros
    else:
        leitor.erro(caminho, "use o nome ou {nome: parâmetros}")
        return None
    especificacao = v.TRANSFORMACOES.get(nome)
    if especificacao is None:
        leitor.erro(caminho, f"transformação desconhecida: {nome}")
        return None
    dados = leitor.mapa(parametros, f"{caminho}.{nome}", tuple(especificacao))
    validos = True
    for chave, especie in especificacao.items():
        if chave in dados and not _parametro_valido(dados[chave], especie):
            leitor.erro(f"{caminho}.{nome}.{chave}", f"esperado {especie}")
            validos = False
    if not validos or set(dados) != set(especificacao):
        return None
    return Transformacao(nome, dict(dados))


def _transformacoes(
    leitor: Leitor, valor: Any, caminho: str
) -> tuple[Transformacao, ...]:
    """Lê uma lista de transformações, preservando a ordem."""
    resultado = []
    for indice, item in enumerate(leitor.lista(valor, caminho)):
        transformacao = _transformacao(leitor, item, f"{caminho}[{indice}]")
        if transformacao is not None:
            resultado.append(transformacao)
    return tuple(resultado)


def _formato_data(leitor: Leitor, valor: Any, caminho: str) -> str | None:
    """Lê o formato de data na notação do layout (ex.: AAAA-MM-DD)."""
    texto = leitor.texto(valor, caminho)
    if texto is None:
        return None
    tokens_unicos = all(texto.count(token) == 1 for token in v.TOKENS_DATA)
    if not _PADRAO_DATA.match(texto) or not tokens_unicos:
        leitor.erro(caminho, "combine AAAA, MM e DD uma vez cada")
        return None
    return texto


def _parametros_tipo(
    leitor: Leitor, dados: dict, tipo: str | None, caminho: str
) -> tuple:
    """Lê os parâmetros exigidos pelo tipo e recusa os que não se aplicam."""
    if tipo is None:
        return None, None, None, None
    exigidos = v.TIPOS[tipo]
    for chave in v.PARAMETROS_DE_TIPO:
        if chave in dados and chave not in exigidos:
            leitor.erro(caminho, f"{chave} não se aplica ao tipo {tipo}")
        elif chave in exigidos and chave not in dados:
            leitor.erro(caminho, f"o tipo {tipo} exige {chave}")
    formato = precisao = escala = separador = None
    if tipo == v.DATA and "formato" in dados:
        formato = _formato_data(leitor, dados["formato"], f"{caminho}.formato")
    if tipo == v.DECIMAL:
        precisao = leitor.inteiro(
            dados.get("precisao"),
            f"{caminho}.precisao",
            minimo=1,
            maximo=v.PRECISAO_MAXIMA,
        )
        escala = leitor.inteiro(
            dados.get("escala"), f"{caminho}.escala", minimo=0
        )
        if precisao is not None and escala is not None and escala > precisao:
            leitor.erro(caminho, "escala maior que a precisão")
        separador = leitor.escolha(
            dados.get("separador_decimal"),
            f"{caminho}.separador_decimal",
            v.SEPARADORES_DECIMAIS,
        )
    return formato, precisao, escala, separador


_CHAVES_COLUNA = (
    "cabecalho",
    "aliases",
    "ausente_na_origem",
    "nulavel",
    "formato",
    "precisao",
    "escala",
    "separador_decimal",
    "transformacoes",
    "dominio",
    "descricao",
)


def _coluna(leitor: Leitor, valor: Any, caminho: str) -> Coluna | None:
    """Lê uma coluna da entidade."""
    dados = leitor.mapa(valor, caminho, ("nome", "tipo"), _CHAVES_COLUNA)
    nome = leitor.texto(dados.get("nome"), f"{caminho}.nome", PADRAO_NOME)
    if nome is not None:
        caminho = f"colunas.{nome}"
    tipo = leitor.escolha(dados.get("tipo"), f"{caminho}.tipo", v.TIPOS)
    aliases = [
        leitor.texto(alias, f"{caminho}.aliases[{indice}]")
        for indice, alias in enumerate(
            leitor.lista(dados.get("aliases"), f"{caminho}.aliases")
        )
    ]
    formato, precisao, escala, separador = _parametros_tipo(
        leitor, dados, tipo, caminho
    )
    coluna = Coluna(
        nome=nome,
        tipo=tipo,
        cabecalho=leitor.texto(
            dados.get("cabecalho"), f"{caminho}.cabecalho", opcional=True
        ),
        aliases=tuple(alias for alias in aliases if alias is not None),
        ausente_na_origem=leitor.booleano(
            dados.get("ausente_na_origem"),
            f"{caminho}.ausente_na_origem",
            False,
        ),
        nulavel=leitor.booleano(
            dados.get("nulavel"), f"{caminho}.nulavel", True
        ),
        formato=formato,
        precisao=precisao,
        escala=escala,
        separador_decimal=separador,
        transformacoes=_transformacoes(
            leitor, dados.get("transformacoes"), f"{caminho}.transformacoes"
        ),
        dominio=leitor.texto(
            dados.get("dominio"), f"{caminho}.dominio", PADRAO_NOME, True
        ),
        descricao=leitor.texto(
            dados.get("descricao"), f"{caminho}.descricao", opcional=True
        ),
    )
    if nome is None or tipo is None:
        return None
    return coluna


def _colunas(leitor: Leitor, valor: Any) -> tuple[Coluna, ...]:
    """Lê a lista de colunas na ordem física do arquivo."""
    itens = leitor.lista(valor, "colunas", opcional=False)
    if valor is not None and not itens:
        leitor.erro("colunas", "a entidade precisa de ao menos uma coluna")
    colunas = [
        _coluna(leitor, item, f"colunas[{indice}]")
        for indice, item in enumerate(itens)
    ]
    return tuple(coluna for coluna in colunas if coluna is not None)


def _chave(leitor: Leitor, valor: Any) -> tuple[str, ...]:
    """Lê a chave declarada (lista de colunas)."""
    if valor is None:
        return ()
    itens = leitor.lista(valor, "chave")
    if not itens:
        leitor.erro("chave", "lista vazia; omita a chave quando não houver")
    nomes = [
        leitor.texto(nome, f"chave[{indice}]", PADRAO_NOME)
        for indice, nome in enumerate(itens)
    ]
    return tuple(nome for nome in nomes if nome is not None)


def _valores_literais(
    leitor: Leitor, valor: Any, caminho: str
) -> dict[str, str]:
    """Lê o mapa código -> descrição de um domínio literal."""
    if not isinstance(valor, Mapping) or not valor:
        leitor.erro(caminho, "informe o mapa código: descrição")
        return {}
    if len(valor) > LIMITE_DOMINIO_LITERAL:
        leitor.erro(
            caminho,
            f"{len(valor)} valores excedem o limite de "
            f"{LIMITE_DOMINIO_LITERAL}; use domínio por referência",
        )
    valores = {}
    for codigo, descricao in valor.items():
        if not isinstance(codigo, str):
            leitor.erro(caminho, f"código {codigo!r} deve ser texto (aspas)")
        elif not isinstance(descricao, str) or not descricao:
            leitor.erro(caminho, f"descrição de {codigo!r} deve ser texto")
        else:
            valores[codigo] = descricao
    return valores


def _dominio(
    leitor: Leitor, nome: str, valor: Any, caminho: str
) -> Dominio | None:
    """Lê um domínio literal ou por referência."""
    dados = leitor.mapa(
        valor,
        caminho,
        ("tipo",),
        ("valores", "coluna_descricao", "tabela", "coluna", "descricao"),
    )
    tipo = leitor.escolha(
        dados.get("tipo"), f"{caminho}.tipo", (LITERAL, REFERENCIA)
    )
    descricao = leitor.texto(
        dados.get("descricao"), f"{caminho}.descricao", opcional=True
    )
    proprias = {
        LITERAL: ("valores", "coluna_descricao"),
        REFERENCIA: ("tabela", "coluna"),
    }
    for outro, chaves in proprias.items():
        for chave in chaves:
            if tipo is not None and outro != tipo and chave in dados:
                leitor.erro(caminho, f"{chave} não se aplica a {tipo}")
    if tipo == LITERAL:
        return Dominio(
            nome=nome,
            tipo=tipo,
            valores=_valores_literais(
                leitor, dados.get("valores"), f"{caminho}.valores"
            ),
            coluna_descricao=leitor.texto(
                dados.get("coluna_descricao"),
                f"{caminho}.coluna_descricao",
                PADRAO_NOME,
                opcional=True,
            ),
            tabela=None,
            coluna=None,
            descricao=descricao,
        )
    if tipo == REFERENCIA:
        tabela = ler_identidade(
            leitor, dados.get("tabela"), f"{caminho}.tabela"
        )
        coluna = leitor.texto(
            dados.get("coluna"), f"{caminho}.coluna", PADRAO_NOME
        )
        if tabela is not None and coluna is not None:
            return Dominio(nome, tipo, {}, None, tabela, coluna, descricao)
    return None


def _dominios(leitor: Leitor, valor: Any) -> dict[str, Dominio]:
    """Lê o mapa de domínios nomeados."""
    if valor is None:
        return {}
    if not isinstance(valor, Mapping):
        leitor.erro("dominios", "deve ser um mapa")
        return {}
    dominios = {}
    for nome, definicao in valor.items():
        if not isinstance(nome, str) or not PADRAO_NOME.match(nome):
            leitor.erro("dominios", f"nome de domínio inválido: {nome!r}")
            continue
        dominio = _dominio(leitor, nome, definicao, f"dominios.{nome}")
        if dominio is not None:
            dominios[nome] = dominio
    return dominios


def _regra(leitor: Leitor, valor: Any, caminho: str) -> Regra | None:
    """Lê uma regra de negócio."""
    dados = leitor.mapa(
        valor,
        caminho,
        ("id", "expressao", "colunas_referenciadas", "acao", "dimensao"),
        ("descricao",),
    )
    identificador = leitor.texto(dados.get("id"), f"{caminho}.id", PADRAO_NOME)
    if identificador is not None:
        caminho = f"regras.{identificador}"
    colunas = [
        leitor.texto(nome, f"{caminho}.colunas_referenciadas[{indice}]")
        for indice, nome in enumerate(
            leitor.lista(
                dados.get("colunas_referenciadas"),
                f"{caminho}.colunas_referenciadas",
                opcional=False,
            )
        )
    ]
    regra = Regra(
        id=identificador,
        expressao=leitor.texto(dados.get("expressao"), f"{caminho}.expressao"),
        colunas_referenciadas=tuple(c for c in colunas if c is not None),
        acao=leitor.escolha(
            dados.get("acao"),
            f"{caminho}.acao",
            sorted(v.ACOES_PERMITIDAS[v.REGRA]),
        ),
        dimensao=leitor.escolha(
            dados.get("dimensao"), f"{caminho}.dimensao", v.DIMENSOES
        ),
        descricao=leitor.texto(
            dados.get("descricao"), f"{caminho}.descricao", opcional=True
        ),
    )
    if None in (regra.id, regra.expressao, regra.acao, regra.dimensao):
        return None
    return regra


def _regras(leitor: Leitor, valor: Any) -> tuple[Regra, ...]:
    """Lê a lista de regras de negócio."""
    regras = [
        _regra(leitor, item, f"regras[{indice}]")
        for indice, item in enumerate(leitor.lista(valor, "regras"))
    ]
    return tuple(regra for regra in regras if regra is not None)


def _acoes_padrao(leitor: Leitor, valor: Any) -> dict[str, str]:
    """Lê as ações das violações que não pertencem a uma regra própria."""
    dados = leitor.mapa(valor, "acoes_padrao", v.CLASSES_PADRAO)
    acoes = {}
    for classe in v.CLASSES_PADRAO:
        if classe not in dados:
            continue
        acao = leitor.escolha(
            dados[classe],
            f"acoes_padrao.{classe}",
            sorted(v.ACOES_PERMITIDAS[classe]),
        )
        if acao is not None:
            acoes[classe] = acao
    return acoes


def _reconciliacao(leitor: Leitor, valor: Any) -> TotalDeclarado | None:
    """Lê a reconciliação com total declarado pela fonte, se houver."""
    if valor is None:
        return None
    dados = leitor.mapa(valor, "reconciliacao", ("total_declarado",))
    total = leitor.mapa(
        dados.get("total_declarado"),
        "reconciliacao.total_declarado",
        ("entidade", "coluna"),
    )
    entidade = leitor.texto(
        total.get("entidade"),
        "reconciliacao.total_declarado.entidade",
        PADRAO_NOME,
    )
    coluna = leitor.texto(
        total.get("coluna"),
        "reconciliacao.total_declarado.coluna",
        PADRAO_NOME,
    )
    if entidade is None or coluna is None:
        return None
    return TotalDeclarado(entidade, coluna)


def ler_pendencias(leitor: Leitor, valor: Any, caminho: str) -> tuple:
    """Lê pendências com o estado que cada uma impede."""
    pendencias = []
    for indice, item in enumerate(leitor.lista(valor, caminho)):
        local = f"{caminho}[{indice}]"
        dados = leitor.mapa(item, local, ("descricao", "impede"))
        descricao = leitor.texto(dados.get("descricao"), f"{local}.descricao")
        impede = leitor.escolha(
            dados.get("impede"), f"{local}.impede", v.ESTADOS_IMPEDIVEIS
        )
        if descricao is not None and impede is not None:
            pendencias.append(Pendencia(descricao, impede))
    return tuple(pendencias)


def _documentacao(leitor: Leitor, valor: Any) -> Documentacao | None:
    """Lê a parte documental: estado, fonte documental e pendências."""
    dados = leitor.mapa(
        valor,
        "documentacao",
        ("estado",),
        ("fonte_documental", "pendencias", "observacoes"),
    )
    estado = leitor.escolha(
        dados.get("estado"), "documentacao.estado", v.ESTADOS
    )
    documentacao = Documentacao(
        estado=estado,
        fonte_documental=leitor.texto(
            dados.get("fonte_documental"),
            "documentacao.fonte_documental",
            opcional=True,
        ),
        pendencias=ler_pendencias(
            leitor, dados.get("pendencias"), "documentacao.pendencias"
        ),
        observacoes=leitor.texto(
            dados.get("observacoes"), "documentacao.observacoes", opcional=True
        ),
    )
    return documentacao if estado is not None else None


def _validar_cabecalhos(leitor: Leitor, contrato: Contrato) -> None:
    """Confere cabeçalho e aliases contra o dialeto declarado."""
    com_cabecalho = contrato.leitura.cabecalho
    for coluna in contrato.colunas:
        caminho = f"colunas.{coluna.nome}"
        declarou = bool(coluna.cabecalho or coluna.aliases)
        if coluna.ausente_na_origem and declarou:
            leitor.erro(caminho, "coluna ausente na origem não tem cabeçalho")
        elif not coluna.ausente_na_origem:
            if com_cabecalho and not coluna.cabecalho:
                leitor.erro(caminho, "arquivo com cabeçalho exige 'cabecalho'")
            if not com_cabecalho and declarou:
                leitor.erro(
                    caminho, "arquivo sem cabeçalho: remova 'cabecalho'"
                )
    nomes = [
        nome
        for coluna in contrato.colunas_origem
        for nome in (coluna.cabecalho, *coluna.aliases)
        if nome
    ]
    leitor.unicos(nomes, "colunas.cabecalho")


def _validar_chave(leitor: Leitor, contrato: Contrato) -> None:
    """Confere se a chave usa colunas existentes e presentes na origem."""
    leitor.unicos(contrato.chave, "chave")
    nomes = {coluna.nome: coluna for coluna in contrato.colunas}
    for nome in contrato.chave:
        coluna = nomes.get(nome)
        if coluna is None:
            leitor.erro("chave", f"coluna inexistente: {nome}")
        elif coluna.ausente_na_origem:
            leitor.erro("chave", f"coluna ausente na origem: {nome}")


def _validar_dominios(leitor: Leitor, contrato: Contrato) -> None:
    """Confere o uso dos domínios e as colunas de descrição geradas."""
    usados = set()
    for coluna in contrato.colunas:
        if coluna.dominio is None:
            continue
        caminho = f"colunas.{coluna.nome}.dominio"
        if coluna.dominio not in contrato.dominios:
            leitor.erro(caminho, f"domínio inexistente: {coluna.dominio}")
            continue
        usados.add(coluna.dominio)
        if coluna.tipo != v.TEXTO:
            leitor.erro(caminho, "domínio exige coluna do tipo texto")
    for nome in contrato.dominios:
        if nome not in usados:
            leitor.erro(f"dominios.{nome}", "domínio declarado e não usado")
    saida = contrato.colunas_saida
    leitor.unicos(saida, "colunas de saída")
    for nome in saida:
        if nome in v.COLUNAS_LINHAGEM or nome.startswith("_"):
            leitor.erro("colunas", f"nome reservado ao motor: {nome}")


def _validar_regras(leitor: Leitor, contrato: Contrato) -> None:
    """Valida identificadores e expressões das regras."""
    leitor.unicos([regra.id for regra in contrato.regras], "regras")
    saida = contrato.colunas_saida
    for regra in contrato.regras:
        problemas = validar_expressao(
            regra.expressao, regra.colunas_referenciadas, saida
        )
        for problema in problemas:
            leitor.erro(f"regras.{regra.id}.expressao", problema)


def _validar_documentacao(leitor: Leitor, contrato: Contrato) -> None:
    """Recusa estado declarado que uma pendência impede."""
    documentacao = contrato.documentacao
    if documentacao.estado == v.OBSOLETO:
        return
    ordem = v.ORDEM_ESTADOS[documentacao.estado]
    for pendencia in documentacao.pendencias:
        if ordem >= v.ORDEM_ESTADOS[pendencia.impede]:
            leitor.erro(
                "documentacao",
                f"estado {documentacao.estado} impedido pela pendência: "
                f"{pendencia.descricao}",
            )


def _validar_consistencia(leitor: Leitor, contrato: Contrato) -> None:
    """Validações que cruzam seções do contrato."""
    if not contrato.colunas_origem:
        leitor.erro("colunas", "ao menos uma coluna deve existir na origem")
    _validar_cabecalhos(leitor, contrato)
    _validar_chave(leitor, contrato)
    _validar_dominios(leitor, contrato)
    _validar_regras(leitor, contrato)
    total = contrato.total_declarado
    if total is not None and total.entidade == contrato.identidade.entidade:
        leitor.erro("reconciliacao", "total declarado aponta para si mesmo")
    _validar_documentacao(leitor, contrato)


_OBRIGATORIAS = (
    "formato_contrato",
    "identidade",
    "versao",
    "selecao",
    "leitura",
    "colunas",
    "acoes_padrao",
    "documentacao",
)
_OPCIONAIS = (
    "descricao",
    "transformacoes_padrao",
    "chave",
    "dominios",
    "regras",
    "reconciliacao",
)


def carregar_contrato(dados: Any, origem: str = "contrato") -> Contrato:
    """Lê e valida um contrato a partir do mapa declarativo.

    Args:
        dados: conteúdo do contrato (YAML ou JSON já desserializado).
        origem: nome usado nas mensagens quando a identidade é inválida.

    Returns:
        Contrato validado.

    Raises:
        ContratoInvalido: com todos os problemas encontrados.
    """
    leitor = Leitor()
    raiz = leitor.mapa(dados, "contrato", _OBRIGATORIAS, _OPCIONAIS)
    formato = leitor.inteiro(raiz.get("formato_contrato"), "formato_contrato")
    if formato is not None and formato != FORMATO_CONTRATO:
        leitor.erro("formato_contrato", f"formato não suportado: {formato}")
    identidade = ler_identidade(leitor, raiz.get("identidade"), "identidade")
    partes = {
        "formato_contrato": formato,
        "identidade": identidade,
        "versao": leitor.inteiro(raiz.get("versao"), "versao", minimo=1),
        "descricao": leitor.texto(
            raiz.get("descricao"), "descricao", opcional=True
        ),
        "selecao": _selecao(leitor, raiz.get("selecao")),
        "leitura": _leitura(leitor, raiz.get("leitura")),
        "transformacoes_padrao": _transformacoes(
            leitor, raiz.get("transformacoes_padrao"), "transformacoes_padrao"
        ),
        "colunas": _colunas(leitor, raiz.get("colunas")),
        "chave": _chave(leitor, raiz.get("chave")),
        "dominios": _dominios(leitor, raiz.get("dominios")),
        "regras": _regras(leitor, raiz.get("regras")),
        "acoes_padrao": _acoes_padrao(leitor, raiz.get("acoes_padrao")),
        "total_declarado": _reconciliacao(leitor, raiz.get("reconciliacao")),
        "documentacao": _documentacao(leitor, raiz.get("documentacao")),
    }
    nome = identidade.identificador if identidade is not None else origem
    leitor.concluir(nome)
    contrato = Contrato(**partes)
    _validar_consistencia(leitor, contrato)
    leitor.concluir(nome)
    return contrato
