"""Gerador: notebooks reproduzíveis byte a byte e biblioteca executável.

Teste textual sobre o JSON verifica estrutura; não é aceite de
comportamento, que exige execução no Fabric.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ferramentas import gerar_notebooks
from ferramentas.repositorio import RAIZ
from testes.test_regras_inviolaveis import GUID

EXECUTAR_BIBLIOTECA = textwrap.dedent("""
    import json
    import sys
    from unittest.mock import MagicMock

    for nome in (
        "pyspark",
        "pyspark.sql",
        "pyspark.sql.functions",
        "pyspark.sql.types",
        "delta",
        "delta.tables",
    ):
        sys.modules[nome] = MagicMock()
    with open(sys.argv[1], encoding="utf-8") as arquivo:
        notebook = json.load(arquivo)
    espaco = {}
    for celula in notebook["cells"]:
        fonte = "".join(celula["source"])
        if celula["cell_type"] == "code" and not fonte.startswith("%"):
            exec(compile(fonte, "celula", "exec"), espaco)
    registro = espaco["REGISTRO"]
    print(len(registro.contratos), registro.versao_motor)
    """)


def executar_biblioteca(conteudo: str) -> subprocess.CompletedProcess:
    """Executa a biblioteca fora do repositório, com Spark simulado."""
    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "nb_hub_biblioteca.ipynb"
        caminho.write_text(conteudo, encoding="utf-8")
        ambiente = {**os.environ, "TMPDIR": pasta, "TEMP": pasta, "TMP": pasta}
        ambiente.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-c", EXECUTAR_BIBLIOTECA, str(caminho)],
            cwd=pasta,
            env=ambiente,
            capture_output=True,
            text=True,
            check=False,
        )


class TestGerador(unittest.TestCase):
    """Reprodutibilidade e estrutura dos notebooks gerados."""

    @classmethod
    def setUpClass(cls):
        cls.conteudos = gerar_notebooks.gerar()

    def test_notebooks_versionados_sao_reproduzidos_byte_a_byte(self):
        self.assertEqual(
            gerar_notebooks.divergencias(RAIZ, self.conteudos), []
        )

    def test_geracao_e_deterministica(self):
        self.assertEqual(gerar_notebooks.gerar(), self.conteudos)

    def test_clone_limpo_reproduz_os_notebooks(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta)
            for nome in ("hub", "contratos", "configuracao"):
                shutil.copytree(
                    RAIZ / nome,
                    destino / nome,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            self.assertEqual(gerar_notebooks.gerar(destino), self.conteudos)

    def test_notebooks_sem_saida_contagem_ou_guid(self):
        for nome, conteudo in self.conteudos.items():
            with self.subTest(nome):
                self.assertIsNone(GUID.search(conteudo))
                for celula in json.loads(conteudo)["cells"]:
                    if celula["cell_type"] == "code":
                        self.assertEqual(celula["outputs"], [])
                        self.assertIsNone(celula["execution_count"])

    def test_orquestracao_e_fina(self):
        for orquestracao in gerar_notebooks.ORQUESTRACOES:
            with self.subTest(orquestracao.nome):
                notebook = json.loads(
                    self.conteudos[f"{orquestracao.nome}.ipynb"]
                )
                fontes = ["".join(c["source"]) for c in notebook["cells"]]
                self.assertTrue(fontes[0].startswith("%%configure -f"))
                self.assertIn('"name": "lh_hub"', fontes[0])
                marcadas = [
                    c
                    for c in notebook["cells"]
                    if c["metadata"].get("tags") == ["parameters"]
                ]
                self.assertEqual(len(marcadas), 1)
                self.assertIn("%run nb_hub_biblioteca", fontes)
                compile(fontes[-1], orquestracao.nome, "exec")
                self.assertLessEqual(len(notebook["cells"]), 5)

    def test_chamadas_existem_na_orquestracao(self):
        arvore = ast.parse(
            (RAIZ / "hub" / "orquestracao.py").read_text(encoding="utf-8")
        )
        funcoes = {
            no.name: {argumento.arg for argumento in no.args.args}
            for no in arvore.body
            if isinstance(no, ast.FunctionDef)
        }
        for orquestracao in gerar_notebooks.ORQUESTRACOES:
            with self.subTest(orquestracao.funcao):
                self.assertIn(orquestracao.funcao, funcoes)
                for argumento in orquestracao.argumentos:
                    nome = argumento.split("=")[0]
                    self.assertIn(nome, funcoes[orquestracao.funcao])

    def test_biblioteca_executa_fora_do_repositorio(self):
        resultado = executar_biblioteca(
            self.conteudos["nb_hub_biblioteca.ipynb"]
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        linhas = resultado.stdout.splitlines()
        self.assertTrue(linhas[0].startswith("hub 0.1.0+"), linhas)
        self.assertTrue(linhas[-1].startswith("15 0.1.0+"), linhas)

    def test_biblioteca_alterada_fora_do_gerador_e_recusada(self):
        notebook = json.loads(self.conteudos["nb_hub_biblioteca.ipynb"])
        for celula in notebook["cells"]:
            fonte = "".join(celula["source"])
            if fonte.startswith('_HUB_MODULOS["hub/decisoes.py"]'):
                alterada = fonte.replace("PUBLICAR = ", "PUBLICAR  = ", 1)
                celula["source"] = [alterada]
        resultado = executar_biblioteca(json.dumps(notebook))
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("alterado fora do gerador", resultado.stderr)

    def test_modulo_com_delimitador_e_recusado(self):
        with tempfile.TemporaryDirectory() as pasta:
            pacote = Path(pasta) / "hub"
            pacote.mkdir()
            (pacote / "x.py").write_text("a = '''x'''\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                gerar_notebooks.fontes_do_pacote(Path(pasta))

    def test_tabela_de_hashes(self):
        linhas = gerar_notebooks.tabela_hashes().splitlines()
        self.assertEqual(len(linhas), 16)
        self.assertTrue(linhas[1].startswith("rfb_cno_areas\t1\t"))


if __name__ == "__main__":
    unittest.main()
