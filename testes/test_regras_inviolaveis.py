"""Regras que não podem ser violadas (seção 7 do briefing).

Cada regra vira uma verificação automática: estrutural quando o
comportamento só pode ser observado no Fabric.
"""

import ast
import re
import unittest

from ferramentas.repositorio import RAIZ
from hub import vocabulario as v
from testes import apoio

GUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
NOMES_DE_FONTE = re.compile(
    r"\b(rfb|cnpj|cno|ibge|inep|mte|rais|receita)\b", re.IGNORECASE
)
EXTENSOES_TEXTO = {".py", ".yaml", ".yml", ".md", ".ipynb", ".toml", ".txt"}
LIMITE_LINHA = 79


IGNORADOS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".venv"}


def arquivos_do_repositorio():
    """Arquivos de texto versionáveis, sem .git e caches locais."""
    for caminho in sorted(RAIZ.rglob("*")):
        if IGNORADOS & set(caminho.relative_to(RAIZ).parts):
            continue
        if caminho.is_file() and caminho.suffix in EXTENSOES_TEXTO:
            yield caminho


def fontes(pasta: str, padrao: str = "*.py"):
    """Arquivos Python de uma pasta do repositório."""
    return sorted((RAIZ / pasta).rglob(padrao))


def texto(caminho) -> str:
    """Conteúdo de um arquivo em UTF-8."""
    return caminho.read_text(encoding="utf-8")


class TestRegrasInviolaveis(unittest.TestCase):
    """Verificações automáticas das regras do projeto."""

    def test_1_matriz_de_acoes_sem_acao_implicita(self):
        self.assertEqual(
            set(v.ACOES_PERMITIDAS), set(v.CLASSES_PADRAO) | {v.REGRA}
        )
        for acoes in v.ACOES_PERMITIDAS.values():
            self.assertLessEqual(acoes, set(v.ACOES))
        self.assertEqual(
            v.ACOES_PERMITIDAS[v.CHAVE_DUPLICADA],
            {v.QUARENTENA_GRUPO, v.BLOQUEIA_PUBLICACAO},
        )
        for contrato in apoio.registro_repositorio().contratos.values():
            self.assertEqual(set(contrato.acoes_padrao), set(v.CLASSES_PADRAO))

    def test_2_contrato_nao_declara_nome_fisico_nem_caminho(self):
        qualificado = re.compile(r"\b(bronze|silver|controle)\.[a-z]")
        proibidos = ("files/", "abfss", "onelake", "lakehouse", "workspace")
        for caminho in fontes("contratos", "*.yaml"):
            conteudo = texto(caminho)
            with self.subTest(caminho.name):
                self.assertIsNone(qualificado.search(conteudo))
                for termo in proibidos:
                    self.assertNotIn(termo, conteudo.lower())

    def test_3_nenhum_sufixo_de_ambiente(self):
        sufixo = re.compile(r"_(dev|hml|prod)$")
        registro = apoio.registro_repositorio()
        for identificador in registro.contratos:
            self.assertIsNone(sufixo.search(identificador))
        for ambiente in registro.configuracao.ambientes.values():
            for schema in ambiente.schemas.values():
                self.assertIsNone(sufixo.search(schema))

    def test_4_nenhum_guid_versionado(self):
        for caminho in arquivos_do_repositorio():
            with self.subTest(str(caminho.relative_to(RAIZ))):
                self.assertIsNone(GUID.search(texto(caminho)))

    def test_6_silver_confere_procedencia(self):
        orquestracao = texto(RAIZ / "hub" / "orquestracao.py")
        self.assertIn("decisoes.verificar_procedencia(", orquestracao)
        silver = texto(RAIZ / "hub" / "spark" / "silver.py")
        self.assertIn("verificar_snapshot_bronze", silver)

    def test_7_toda_escrita_de_snapshot_e_reconciliada(self):
        chamadas = {
            caminho.name
            for caminho in fontes("hub")
            if "publicar_snapshot(" in texto(caminho)
        }
        self.assertEqual(chamadas, {"delta.py", "publicacao.py"})
        publicacao = texto(RAIZ / "hub" / "spark" / "publicacao.py")
        self.assertIn("verificar_reconciliacao(", publicacao)
        self.assertIn("delta.restaurar(", publicacao)

    def test_8_quarentena_nunca_elimina(self):
        quarentena = texto(RAIZ / "hub" / "spark" / "quarentena.py").lower()
        for termo in ("delete", "overwrite", "truncate", "drop"):
            self.assertNotIn(termo, quarentena)

    def test_9_toda_tentativa_e_registrada(self):
        arvore = ast.parse(texto(RAIZ / "hub" / "orquestracao.py"))
        publicas = [
            no
            for no in arvore.body
            if isinstance(no, ast.FunctionDef)
            and not no.name.startswith("_")
            and no.name != "executar_base"
        ]
        self.assertGreaterEqual(len(publicas), 7)
        for funcao in publicas:
            with self.subTest(funcao.name):
                self.assertIn("controle.execucao(", ast.unparse(funcao))

    def test_10_expressao_validada_no_carregamento(self):
        contrato = texto(RAIZ / "hub" / "contrato.py")
        self.assertIn("validar_expressao(", contrato)
        silver = texto(RAIZ / "hub" / "spark" / "silver.py")
        self.assertEqual(silver.count("F.expr("), 1)

    def test_motor_generico_sem_nome_de_fonte(self):
        for caminho in fontes("hub"):
            with self.subTest(caminho.name):
                self.assertEqual(NOMES_DE_FONTE.findall(texto(caminho)), [])

    def test_modulos_puros_nao_importam_spark(self):
        importa_spark = re.compile(
            r"^\s*(from|import) (pyspark|delta)\b", re.M
        )
        for caminho in (RAIZ / "hub").glob("*.py"):
            if caminho.name == "orquestracao.py":
                continue
            with self.subTest(caminho.name):
                self.assertIsNone(importa_spark.search(texto(caminho)))

    def test_transformacoes_tem_implementacao_spark(self):
        arvore = ast.parse(texto(RAIZ / "hub" / "spark" / "transformacoes.py"))
        implementadas = set()
        for no in ast.walk(arvore):
            alvos = getattr(no, "targets", [])
            if any(getattr(a, "id", "") == "IMPLEMENTACOES" for a in alvos):
                implementadas = {chave.value for chave in no.value.keys}
        self.assertEqual(implementadas, set(v.TRANSFORMACOES))

    def test_todos_os_modulos_compilam(self):
        for caminho in fontes("hub") + fontes("ferramentas"):
            with self.subTest(caminho.name):
                compile(texto(caminho), str(caminho), "exec")

    def test_pep8_linhas_com_ate_79_caracteres(self):
        for pasta in ("hub", "ferramentas", "testes"):
            for caminho in fontes(pasta):
                for numero, linha in enumerate(texto(caminho).splitlines(), 1):
                    local = f"{caminho.relative_to(RAIZ)}:{numero}"
                    self.assertLessEqual(len(linha), LIMITE_LINHA, local)


if __name__ == "__main__":
    unittest.main()
