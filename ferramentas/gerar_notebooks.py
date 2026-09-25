"""Gerador dos notebooks do Fabric.

Todo notebook do projeto é saída deste gerador e é reproduzível byte a
byte: rodar de novo em clone limpo produz os mesmos arquivos. Os
notebooks não têm saída de célula, contagem de execução, GUID nem
metadado de lakehouse; o lakehouse padrão é resolvido pelo nome.

Uso::

    python ferramentas/gerar_notebooks.py              # grava notebooks/
    python ferramentas/gerar_notebooks.py --verificar  # falha se divergir
    python ferramentas/gerar_notebooks.py --hashes     # hashes dos contratos
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from ferramentas.repositorio import carregar_dados  # noqa: E402
from hub import __version__  # noqa: E402
from hub.hashes import (  # noqa: E402
    canonico,
    hash_contrato,
    hash_leitura,
    sha256_texto,  # noqa: E402
)
from hub.registro import Registro  # noqa: E402

PASTA_NOTEBOOKS = "notebooks"
BIBLIOTECA = "nb_hub_biblioteca"
DELIMITADOR = "'''"

METADADOS_NOTEBOOK = {
    "kernel_info": {"name": "synapse_pyspark"},
    "kernelspec": {
        "display_name": "Synapse PySpark",
        "language": "Python",
        "name": "synapse_pyspark",
    },
    "language_info": {"name": "python"},
}

AVISO_GERADO = (
    "Gerado por `ferramentas/gerar_notebooks.py`. Não edite no Fabric: "
    "altere o repositório, gere novamente e reimporte."
)

CABECALHO_BIBLIOTECA = """import hashlib
import json
import os
import sys
import tempfile

HUB_ASSINATURA = (
    "{assinatura}"
)
_HUB_MODULOS = {{}}"""

INSTALADOR = '''def _hub_conteudo(modulos):
    """Fontes dos módulos sem a quebra de linha inicial da célula."""
    return {
        caminho: fonte.removeprefix("\\n")
        for caminho, fonte in modulos.items()
    }


def _hub_conferir(modulos, dados, esperada):
    """Recusa biblioteca alterada fora do gerador."""
    texto = json.dumps(
        {"dados": dados, "modulos": modulos},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    calculada = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    if calculada != esperada:
        raise RuntimeError(
            "nb_hub_biblioteca foi alterado fora do gerador "
            f"(assinatura {calculada[:12]}, esperada {esperada[:12]})"
        )


def _hub_instalar(modulos, assinatura):
    """Materializa o pacote hub em diretório temporário e o importa."""
    destino = os.path.join(tempfile.gettempdir(), "hub_" + assinatura[:16])
    for caminho, fonte in modulos.items():
        arquivo = os.path.join(destino, caminho)
        os.makedirs(os.path.dirname(arquivo), exist_ok=True)
        with open(arquivo, "w", encoding="utf-8") as saida:
            saida.write(fonte)
    carregados = [m for m in sys.modules if m.split(".")[0] == "hub"]
    for nome in carregados:
        del sys.modules[nome]
    if destino not in sys.path:
        sys.path.insert(0, destino)


_hub_modulos = _hub_conteudo(_HUB_MODULOS)
_hub_conferir(_hub_modulos, _HUB_DADOS, HUB_ASSINATURA)
_hub_instalar(_hub_modulos, HUB_ASSINATURA)

import hub  # noqa: E402
import hub.orquestracao  # noqa: E402
from hub.registro import Registro  # noqa: E402

REGISTRO = Registro.de_dicionario(
    _HUB_DADOS, versao_motor=hub.__version__ + "+" + HUB_ASSINATURA[:12]
)
print(
    f"hub {REGISTRO.versao_motor}: {len(REGISTRO.contratos)} contratos, "
    f"{len(REGISTRO.bases)} bases"
)'''


@dataclass(frozen=True)
class Parametro:
    """Parâmetro de notebook: nome, valor de exemplo e descrição."""

    nome: str
    exemplo: object
    descricao: str


@dataclass(frozen=True)
class Orquestracao:
    """Notebook fino: parâmetros e a função do motor que ele chama.

    ``argumentos`` são pares ``nome=expressão`` repassados à função, além
    de ``spark`` e ``REGISTRO``. Com ``exibir_json``, o resultado é
    impresso como JSON indentado.
    """

    nome: str
    titulo: str
    descricao: str
    parametros: tuple[Parametro, ...]
    funcao: str
    argumentos: tuple[str, ...]
    exibir_json: bool = False


AMBIENTE = Parametro("ambiente", "dev", "dev, hml ou prod.")
ENTIDADE = Parametro(
    "entidade", "rfb_cno_obras", "identificador fonte_base_entidade."
)
COMPETENCIA = Parametro("competencia", "2026-09", "competência AAAA-MM.")
PERMITIR_ANTERIOR = Parametro(
    "permitir_competencia_anterior",
    False,
    "True apenas para reverter o snapshot a uma competência anterior.",
)
FONTE = Parametro("fonte", "rfb", "fonte da base.")
BASE = Parametro("base", "cno", "base da fonte.")

ORQUESTRACOES = (
    Orquestracao(
        nome="nb_hub_adquirir",
        titulo="Aquisição",
        descricao=(
            "Traz a publicação da base para a Raw (download ou depósito) e "
            "registra os arquivos com SHA-256. A Raw nunca é sobrescrita."
        ),
        parametros=(
            AMBIENTE,
            FONTE,
            BASE,
            COMPETENCIA,
            Parametro("modo", "download", "download ou deposito."),
            Parametro(
                "pasta_deposito",
                "",
                "pasta sob a competência, no modo deposito.",
            ),
            Parametro(
                "forcar", False, "True para adquirir de novo a competência."
            ),
        ),
        funcao="adquirir",
        argumentos=(
            "ambiente=ambiente",
            "fonte=fonte",
            "base=base",
            "competencia=competencia",
            "modo=modo",
            "pasta_deposito=pasta_deposito or None",
            "forcar=forcar",
        ),
    ),
    Orquestracao(
        nome="nb_hub_inspecionar",
        titulo="Inspeção física",
        descricao=(
            "Sob demanda: na descoberta ou diante de mudança detectada. "
            "Compara o início de cada arquivo com o contrato; o veredito "
            "(COMPATIVEL ou INCOMPATIVEL) é evidência para VALIDADO_FISICO."
        ),
        parametros=(AMBIENTE, ENTIDADE, COMPETENCIA),
        funcao="inspecionar",
        argumentos=(
            "ambiente=ambiente",
            "entidade=entidade",
            "competencia=competencia",
        ),
        exibir_json=True,
    ),
    Orquestracao(
        nome="nb_hub_bronze",
        titulo="Publicação Bronze",
        descricao=(
            "Lê a aquisição efetiva conforme o contrato, mantém tudo como "
            "texto, envia linhas malformadas à quarentena, reconcilia e "
            "publica o snapshot."
        ),
        parametros=(AMBIENTE, ENTIDADE, COMPETENCIA, PERMITIR_ANTERIOR),
        funcao="publicar_bronze",
        argumentos=(
            "ambiente=ambiente",
            "entidade=entidade",
            "competencia=competencia",
            "permitir_competencia_anterior=permitir_competencia_anterior",
        ),
    ),
    Orquestracao(
        nome="nb_hub_silver",
        titulo="Publicação Silver",
        descricao=(
            "Confirma a procedência da Bronze, aplica tipos, domínios, chave "
            "e regras, separa inválidos na quarentena, reconcilia e publica "
            "o snapshot."
        ),
        parametros=(AMBIENTE, ENTIDADE, COMPETENCIA, PERMITIR_ANTERIOR),
        funcao="publicar_silver",
        argumentos=(
            "ambiente=ambiente",
            "entidade=entidade",
            "competencia=competencia",
            "permitir_competencia_anterior=permitir_competencia_anterior",
        ),
    ),
    Orquestracao(
        nome="nb_hub_executar_base",
        titulo="Execução da base",
        descricao=(
            "Aquisição, Bronze e Silver de todas as entidades da base, em "
            "sequência. Entidades são independentes; falhas são reportadas "
            "ao final."
        ),
        parametros=(
            AMBIENTE,
            FONTE,
            BASE,
            COMPETENCIA,
            Parametro(
                "forcar_aquisicao",
                False,
                "True para adquirir de novo a competência.",
            ),
        ),
        funcao="executar_base",
        argumentos=(
            "ambiente=ambiente",
            "fonte=fonte",
            "base=base",
            "competencia=competencia",
            "forcar_aquisicao=forcar_aquisicao",
        ),
    ),
    Orquestracao(
        nome="nb_hub_aprovar",
        titulo="Aprovação do contrato",
        descricao=(
            "Registra autorização nominal e datada para o hash do contrato "
            "neste ambiente. Exige inspeção COMPATIVEL e nenhuma pendência. "
            "Obtenha o hash em controle.catalogo_ativos ou com "
            "`python ferramentas/gerar_notebooks.py --hashes`."
        ),
        parametros=(
            AMBIENTE,
            ENTIDADE,
            Parametro("responsavel", "", "nome de quem autoriza."),
            Parametro("hash_contrato", "", "hash_contrato autorizado."),
        ),
        funcao="aprovar",
        argumentos=(
            "ambiente=ambiente",
            "entidade=entidade",
            "responsavel=responsavel",
            "hash_contrato=hash_contrato",
        ),
    ),
    Orquestracao(
        nome="nb_hub_diagnosticar",
        titulo="Diagnóstico de referências",
        descricao=(
            "Diagnóstico dirigido, fora do fluxo obrigatório: confere os "
            "domínios por referência da entidade contra as tabelas oficiais. "
            "Não bloqueia a entidade de negócio."
        ),
        parametros=(AMBIENTE, ENTIDADE),
        funcao="diagnosticar_referencias",
        argumentos=(
            "ambiente=ambiente",
            "entidade=entidade",
        ),
        exibir_json=True,
    ),
    Orquestracao(
        nome="nb_hub_catalogo",
        titulo="Sincronização do catálogo",
        descricao=(
            "Atualiza a parte estrutural do catálogo a partir dos contratos, "
            "preserva a curadoria e aplica os comentários físicos."
        ),
        parametros=(AMBIENTE,),
        funcao="sincronizar_catalogo",
        argumentos=("ambiente=ambiente",),
    ),
)


def _linhas(texto: str) -> list[str]:
    """Texto no formato de linhas do nbformat."""
    linhas = texto.split("\n")
    resultado = [linha + "\n" for linha in linhas[:-1]]
    if linhas[-1]:
        resultado.append(linhas[-1])
    return resultado


def celula_codigo(texto: str, parametros: bool = False) -> dict:
    """Célula de código sem saída nem contagem de execução."""
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["parameters"]} if parametros else {},
        "outputs": [],
        "source": _linhas(texto),
    }


def celula_texto(texto: str) -> dict:
    """Célula markdown."""
    return {"cell_type": "markdown", "metadata": {}, "source": _linhas(texto)}


def notebook(celulas: list[dict]) -> dict:
    """Notebook nbformat 4.5 com identificadores de célula determinísticos."""
    numeradas = []
    for indice, celula in enumerate(celulas, start=1):
        numeradas.append({**celula, "id": f"celula-{indice:02d}"})
    return {
        "cells": numeradas,
        "metadata": METADADOS_NOTEBOOK,
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def serializar(conteudo: dict) -> str:
    """JSON determinístico, com quebra de linha final."""
    return (
        json.dumps(conteudo, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n"
    )


def fontes_do_pacote(raiz: Path = RAIZ) -> dict[str, str]:
    """Código-fonte do pacote hub, em ordem de caminho.

    Raises:
        ValueError: se algum módulo contiver o delimitador da célula.
    """
    fontes = {}
    for caminho in sorted((raiz / "hub").rglob("*.py")):
        relativo = caminho.relative_to(raiz).as_posix()
        texto = caminho.read_text(encoding="utf-8")
        if DELIMITADOR in texto:
            raise ValueError(f"{relativo} contém {DELIMITADOR}")
        fontes[relativo] = texto
    return fontes


def assinatura(fontes: dict[str, str], dados: dict) -> str:
    """Assinatura do conteúdo embutido (motor e registro)."""
    return sha256_texto(canonico({"dados": dados, "modulos": fontes}))


def notebook_biblioteca(fontes: dict[str, str], dados: dict) -> dict:
    """Notebook com o motor e o registro declarativo embutidos."""
    marca = assinatura(fontes, dados)
    registro_json = json.dumps(
        dados, ensure_ascii=False, indent=1, sort_keys=True
    )
    if DELIMITADOR in registro_json:
        raise ValueError(f"conteúdo declarativo contém {DELIMITADOR}")
    celulas = [
        celula_texto(
            f"# {BIBLIOTECA}\n\n{AVISO_GERADO}\n\n"
            f"Motor `hub` {__version__} ({len(fontes)} módulos) e registro "
            f"declarativo ({len(dados['contratos'])} contratos). Assinatura "
            f"`{marca}`.\n\n"
            "Use com `%run nb_hub_biblioteca`. Define `hub` e `REGISTRO`."
        ),
        celula_codigo(CABECALHO_BIBLIOTECA.format(assinatura=marca)),
    ]
    for caminho, fonte in fontes.items():
        celulas.append(
            celula_codigo(
                f'_HUB_MODULOS["{caminho}"] = r{DELIMITADOR}\n'
                f"{fonte}{DELIMITADOR}"
            )
        )
    celulas.append(
        celula_codigo(
            f"_HUB_DADOS = json.loads(\n    r{DELIMITADOR}"
            f"{registro_json}{DELIMITADOR}\n)"
        )
    )
    celulas.append(celula_codigo(INSTALADOR))
    return notebook(celulas)


def chamada(orquestracao: Orquestracao) -> str:
    """Código da célula que chama o motor."""
    linhas = []
    if orquestracao.exibir_json:
        linhas += ["import json", ""]
    linhas.append(f"resultado = hub.orquestracao.{orquestracao.funcao}(")
    linhas += ["    spark,", "    REGISTRO,"]
    linhas += [f"    {argumento}," for argumento in orquestracao.argumentos]
    linhas.append(")")
    if orquestracao.exibir_json:
        linhas.append(
            "print(json.dumps(resultado, ensure_ascii=False, indent=2))"
        )
    else:
        linhas.append("resultado")
    return "\n".join(linhas)


def _documentacao_parametros(parametros: tuple[Parametro, ...]) -> str:
    """Lista de parâmetros em markdown."""
    return "\n".join(f"- `{p.nome}`: {p.descricao}" for p in parametros)


def notebook_orquestracao(orquestracao: Orquestracao, lakehouse: str) -> dict:
    """Notebook fino: lakehouse por nome, parâmetros, biblioteca e chamada."""
    configuracao = json.dumps(
        {"defaultLakehouse": {"name": lakehouse}}, indent=4
    )
    parametros = "\n".join(
        f"{p.nome} = {p.exemplo!r}" for p in orquestracao.parametros
    )
    return notebook(
        [
            celula_codigo(f"%%configure -f\n{configuracao}"),
            celula_texto(
                f"# {orquestracao.titulo}\n\n{orquestracao.descricao}\n\n"
                f"Parâmetros:\n\n"
                f"{_documentacao_parametros(orquestracao.parametros)}\n\n"
                f"{AVISO_GERADO}"
            ),
            celula_codigo(parametros, parametros=True),
            celula_codigo(f"%run {BIBLIOTECA}"),
            celula_codigo(chamada(orquestracao)),
        ]
    )


def gerar(raiz: Path = RAIZ) -> dict[str, str]:
    """Conteúdo de todos os notebooks, por nome de arquivo.

    Raises:
        ContratoInvalido: se o conteúdo declarativo não for válido.
    """
    dados = carregar_dados(raiz)
    registro = Registro.de_dicionario(dados)
    fontes = fontes_do_pacote(raiz)
    conteudos = {
        f"{BIBLIOTECA}.ipynb": serializar(notebook_biblioteca(fontes, dados))
    }
    for orquestracao in ORQUESTRACOES:
        conteudos[f"{orquestracao.nome}.ipynb"] = serializar(
            notebook_orquestracao(
                orquestracao, registro.configuracao.lakehouse
            )
        )
    return conteudos


def divergencias(raiz: Path, conteudos: dict[str, str]) -> list[str]:
    """Diferenças entre os notebooks gravados e os gerados."""
    pasta = raiz / PASTA_NOTEBOOKS
    problemas = []
    existentes = (
        {p.name for p in pasta.glob("*.ipynb")} if pasta.is_dir() else set()
    )
    for nome, conteudo in sorted(conteudos.items()):
        arquivo = pasta / nome
        if not arquivo.exists():
            problemas.append(f"ausente: {nome}")
        elif arquivo.read_bytes() != conteudo.encode("utf-8"):
            problemas.append(f"divergente: {nome}")
    for nome in sorted(existentes - set(conteudos)):
        problemas.append(f"não gerado pelo gerador: {nome}")
    return problemas


def gravar(raiz: Path, conteudos: dict[str, str]) -> None:
    """Grava os notebooks gerados (sobrescreve apenas os gerados)."""
    pasta = raiz / PASTA_NOTEBOOKS
    pasta.mkdir(exist_ok=True)
    for nome, conteudo in conteudos.items():
        (pasta / nome).write_bytes(conteudo.encode("utf-8"))


def tabela_hashes(raiz: Path = RAIZ) -> str:
    """Versão, estado e hashes de cada contrato, em texto tabular."""
    registro = Registro.de_dicionario(carregar_dados(raiz))
    linhas = ["identificador\tversao\testado\thash_leitura\thash_contrato"]
    for identificador, contrato in sorted(registro.contratos.items()):
        linhas.append(
            f"{identificador}\t{contrato.versao}\t"
            f"{contrato.documentacao.estado}\t{hash_leitura(contrato)}\t"
            f"{hash_contrato(contrato)}"
        )
    return "\n".join(linhas)


def main(argumentos: list[str] | None = None) -> int:
    """Ponto de entrada da linha de comando."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--verificar",
        action="store_true",
        help="compara com notebooks/ sem gravar; falha se divergir",
    )
    grupo.add_argument(
        "--hashes", action="store_true", help="imprime os hashes"
    )
    opcoes = parser.parse_args(argumentos)
    if opcoes.hashes:
        print(tabela_hashes())
        return 0
    conteudos = gerar()
    if opcoes.verificar:
        problemas = divergencias(RAIZ, conteudos)
        for problema in problemas:
            print(problema)
        return 1 if problemas else 0
    gravar(RAIZ, conteudos)
    print(f"{len(conteudos)} notebooks gerados em {PASTA_NOTEBOOKS}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
