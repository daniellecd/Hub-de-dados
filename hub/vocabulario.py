"""Vocabulário fechado do motor.

Fonte única para ações, classes de violação, tipos, transformações,
estados de contrato, dimensões de qualidade, status de execução e nomes
reservados. Qualquer termo fora destas listas é recusado na validação.
"""

from typing import NamedTuple

# Ações declaradas no contrato (seção 5.3 do briefing).
QUARENTENA = "QUARENTENA"
QUARENTENA_E_ALERTA = "QUARENTENA_E_ALERTA"
QUARENTENA_GRUPO = "QUARENTENA_GRUPO"
ALERTA = "ALERTA"
BLOQUEIA_PUBLICACAO = "BLOQUEIA_PUBLICACAO"

ACOES = (
    QUARENTENA,
    QUARENTENA_E_ALERTA,
    QUARENTENA_GRUPO,
    ALERTA,
    BLOQUEIA_PUBLICACAO,
)
ACOES_QUE_RETIRAM = frozenset(
    {QUARENTENA, QUARENTENA_E_ALERTA, QUARENTENA_GRUPO}
)
ACOES_QUE_ALERTAM = frozenset({ALERTA, QUARENTENA_E_ALERTA})

# Classes de violação.
LINHA_MALFORMADA = "linha_malformada"
NULIDADE = "nulidade"
CONVERSAO = "conversao"
CHAVE_NULA = "chave_nula"
CHAVE_DUPLICADA = "chave_duplicada"
DOMINIO = "dominio"
REGRA = "regra"

# Classes cuja ação é declarada em acoes_padrao (todas obrigatórias).
CLASSES_PADRAO = (
    LINHA_MALFORMADA,
    NULIDADE,
    CONVERSAO,
    CHAVE_NULA,
    CHAVE_DUPLICADA,
    DOMINIO,
)

_ACOES_DE_LINHA = frozenset(
    {QUARENTENA, QUARENTENA_E_ALERTA, ALERTA, BLOQUEIA_PUBLICACAO}
)

# Matriz de ações permitidas. ALERTA em chave duplicada publicaria
# duplicidade; QUARENTENA simples exigiria eleger um vencedor.
ACOES_PERMITIDAS = {
    LINHA_MALFORMADA: frozenset(
        {QUARENTENA, QUARENTENA_E_ALERTA, BLOQUEIA_PUBLICACAO}
    ),
    NULIDADE: _ACOES_DE_LINHA,
    CONVERSAO: _ACOES_DE_LINHA,
    CHAVE_NULA: frozenset(
        {QUARENTENA, QUARENTENA_E_ALERTA, BLOQUEIA_PUBLICACAO}
    ),
    CHAVE_DUPLICADA: frozenset({QUARENTENA_GRUPO, BLOQUEIA_PUBLICACAO}),
    DOMINIO: _ACOES_DE_LINHA,
    REGRA: _ACOES_DE_LINHA,
}

# Dimensões de qualidade (vocabulário do Microsoft Purview).
COMPLETENESS = "Completeness"
CONSISTENCY = "Consistency"
CONFORMITY = "Conformity"
ACCURACY = "Accuracy"
UNIQUENESS = "Uniqueness"

# Freshness é lacuna conhecida: não há periodicidade, tolerância e ação.
DIMENSOES = (COMPLETENESS, CONSISTENCY, CONFORMITY, ACCURACY, UNIQUENESS)

DIMENSAO_POR_CLASSE = {
    LINHA_MALFORMADA: CONFORMITY,
    NULIDADE: COMPLETENESS,
    CONVERSAO: COMPLETENESS,
    CHAVE_NULA: COMPLETENESS,
    CHAVE_DUPLICADA: UNIQUENESS,
    DOMINIO: CONSISTENCY,
}

# Tipos lógicos de coluna e seus parâmetros obrigatórios.
TEXTO = "texto"
INTEIRO = "inteiro"
INTEIRO_LONGO = "inteiro_longo"
DECIMAL = "decimal"
DATA = "data"

TIPOS = {
    TEXTO: (),
    INTEIRO: (),
    INTEIRO_LONGO: (),
    DECIMAL: ("precisao", "escala", "separador_decimal"),
    DATA: ("formato",),
}
PARAMETROS_DE_TIPO = ("formato", "precisao", "escala", "separador_decimal")
SEPARADORES_DECIMAIS = (".", ",")
PRECISAO_MAXIMA = 38

# Notação de data do layout oficial convertida para o padrão do motor.
TOKENS_DATA = {"AAAA": "yyyy", "MM": "MM", "DD": "dd"}
SEPARADORES_DATA = ("-", "/", ".")

# Transformações e a especificação de seus parâmetros.
LISTA_TEXTO = "lista_texto"
INTEIRO_POSITIVO = "inteiro_positivo"
CARACTERE = "caractere"

TRANSFORMACOES = {
    "aparar": {},
    "maiusculas": {},
    "somente_digitos": {},
    "vazio_como_nulo": {},
    "nulo_se": {"valores": LISTA_TEXTO},
    "preencher_esquerda": {
        "tamanho": INTEIRO_POSITIVO,
        "caractere": CARACTERE,
    },
}


class Codificacao(NamedTuple):
    """Nome do codec no Python e do charset no leitor do Spark."""

    python: str
    spark: str


CODIFICACOES = {
    "utf-8": Codificacao("utf-8", "UTF-8"),
    "iso-8859-1": Codificacao("iso-8859-1", "ISO-8859-1"),
    "windows-1252": Codificacao("cp1252", "windows-1252"),
}

# Ciclo de vida do contrato.
PROVISORIO_DOCUMENTAL = "PROVISORIO_DOCUMENTAL"
VALIDADO_FISICO = "VALIDADO_FISICO"
APROVADO = "APROVADO"
OBSOLETO = "OBSOLETO"

ESTADOS = (PROVISORIO_DOCUMENTAL, VALIDADO_FISICO, APROVADO, OBSOLETO)
ORDEM_ESTADOS = {PROVISORIO_DOCUMENTAL: 0, VALIDADO_FISICO: 1, APROVADO: 2}
ESTADOS_IMPEDIVEIS = (VALIDADO_FISICO, APROVADO)

# Vocabulário das expressões de regra. Funções não determinísticas
# (current_date, now, rand) ficam de fora para preservar a idempotência.
PALAVRAS_EXPRESSAO = frozenset(
    {
        "AND",
        "OR",
        "NOT",
        "IS",
        "NULL",
        "IN",
        "BETWEEN",
        "LIKE",
        "TRUE",
        "FALSE",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "DATE",
    }
)
FUNCOES_EXPRESSAO = frozenset(
    {
        "abs",
        "coalesce",
        "day",
        "length",
        "lower",
        "month",
        "regexp_like",
        "round",
        "substring",
        "trim",
        "upper",
        "year",
    }
)

# Camadas e tipos de execução.
BRONZE = "bronze"
SILVER = "silver"
CONTROLE = "controle"
CAMADAS_DE_SCHEMA = (BRONZE, SILVER, CONTROLE)

AQUISICAO = "AQUISICAO"
INSPECAO = "INSPECAO"
PUBLICACAO_BRONZE = "BRONZE"
PUBLICACAO_SILVER = "SILVER"
APROVACAO = "APROVACAO"
DIAGNOSTICO = "DIAGNOSTICO"
CATALOGO = "CATALOGO"

# Status de execução.
EM_EXECUCAO = "EM_EXECUCAO"
SUCESSO = "SUCESSO"
SUCESSO_COM_ALERTA = "SUCESSO_COM_ALERTA"
BLOQUEADA = "BLOQUEADA"
FALHA = "FALHA"
STATUS_EFETIVOS = frozenset({SUCESSO, SUCESSO_COM_ALERTA})

# Resultados registrados por tipo de execução.
ADQUIRIDA = "ADQUIRIDA"
EXISTENTE = "EXISTENTE"
COMPATIVEL = "COMPATIVEL"
INCOMPATIVEL = "INCOMPATIVEL"
APROVADA = "APROVADA"
CONFERIDA = "CONFERIDA"
COM_ORFAOS = "COM_ORFAOS"
REFERENCIA_AUSENTE = "REFERENCIA_AUSENTE"

# Colunas de linhagem mínima acrescentadas pelo motor.
COLUNA_COMPETENCIA = "competencia"
COLUNA_ARQUIVO = "_arquivo_origem"
COLUNA_EXECUCAO = "_id_execucao"
COLUNAS_LINHAGEM = (COLUNA_COMPETENCIA, COLUNA_ARQUIVO, COLUNA_EXECUCAO)

# Valor dos campos de curadoria que ainda não foram preenchidos.
A_CONFIRMAR = "A_CONFIRMAR"

# Identificador das execuções que não pertencem a uma entidade ou base.
IDENTIFICADOR_GLOBAL = "hub"
SINCRONIZADO = "SINCRONIZADO"
