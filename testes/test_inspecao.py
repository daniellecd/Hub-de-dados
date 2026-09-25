"""Inspeção física e leitura de cabeçalho e total declarado."""

import tempfile
import unittest
from pathlib import Path

from hub import arquivos, inspecao
from hub import vocabulario as v
from testes import apoio

CABECALHO = "CODIGO;VALOR;DATA;SITUACAO\n"


class TestInspecao(unittest.TestCase):
    """Veredito da inspeção contra o contrato."""

    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.pasta = Path(self.temporario.name)
        self.contrato = apoio.carregar(apoio.contrato_minimo())

    def arquivo(self, nome: str, conteudo: bytes) -> str:
        caminho = self.pasta / nome
        caminho.write_bytes(conteudo)
        return str(caminho)

    def inspecionar(self, conteudo: bytes, contrato=None) -> dict:
        caminho = self.arquivo("parte.csv", conteudo)
        return inspecao.inspecionar(
            [("parte.csv", caminho)], contrato or self.contrato
        )

    def test_arquivo_compativel(self):
        relatorio = self.inspecionar(
            (CABECALHO + "1;2,50;20260901;A\n2;3,00;20260902;I\n").encode()
        )
        parte = relatorio["partes"][0]
        self.assertEqual(
            relatorio["veredito"], v.COMPATIVEL, parte["problemas"]
        )
        self.assertEqual(parte["larguras"], {"4": 2})
        self.assertEqual(parte["amostras"]["codigo"], ["1", "2"])
        self.assertEqual(parte["terminador"], "LF")

    def test_mudanca_de_posicao_no_cabecalho(self):
        relatorio = self.inspecionar(
            b"CODIGO;VALOR;SITUACAO;DATA\n1;2,50;A;20260901\n"
        )
        self.assertEqual(relatorio["veredito"], v.INCOMPATIVEL)
        self.assertIn(
            "coluna 'SITUACAO' na posição 3; contrato declara 4",
            relatorio["partes"][0]["problemas"],
        )

    def test_codificacao_que_nao_decodifica(self):
        conteudo = (CABECALHO + "1;2,50;20260901;Ação\n").encode("latin-1")
        relatorio = self.inspecionar(conteudo)
        self.assertEqual(relatorio["veredito"], v.INCOMPATIVEL)
        self.assertFalse(relatorio["partes"][0]["decodifica_declarada"])

    def test_utf8_declarado_como_latin1_e_acusado(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["codificacao"] = "iso-8859-1"
        conteudo = (CABECALHO + "1;2,50;20260901;Ação\n").encode("utf-8")
        relatorio = self.inspecionar(conteudo, apoio.carregar(dados))
        self.assertEqual(relatorio["veredito"], v.INCOMPATIVEL)

    def test_largura_divergente_sem_cabecalho(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["cabecalho"] = False
        for coluna in dados["colunas"]:
            coluna.pop("cabecalho")
        relatorio = self.inspecionar(
            b"1;2,50;20260901;A\n2;3,00\n", apoio.carregar(dados)
        )
        parte = relatorio["partes"][0]
        self.assertEqual(parte["larguras"], {"2": 1, "4": 1})
        self.assertEqual(relatorio["veredito"], v.INCOMPATIVEL)

    def test_separador_diferente_do_declarado(self):
        relatorio = self.inspecionar(
            b"CODIGO,VALOR,DATA,SITUACAO\n1,2.5,20260901,A\n"
        )
        parte = relatorio["partes"][0]
        self.assertEqual(parte["separador_provavel"], ",")
        self.assertEqual(relatorio["veredito"], v.INCOMPATIVEL)

    def test_terminador_crlf(self):
        relatorio = self.inspecionar(
            (CABECALHO + "1;2,50;20260901;A\n").replace("\n", "\r\n").encode()
        )
        self.assertEqual(relatorio["partes"][0]["terminador"], "CRLF")
        self.assertEqual(relatorio["veredito"], v.COMPATIVEL)

    def test_sem_partes_e_incompativel(self):
        self.assertEqual(
            inspecao.inspecionar([], self.contrato)["veredito"],
            v.INCOMPATIVEL,
        )


class TestArquivos(unittest.TestCase):
    """Leitura no driver: cabeçalho e total declarado pela fonte."""

    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.pasta = Path(self.temporario.name)
        dados = apoio.contrato_minimo()
        dados["identidade"]["entidade"] = "totais"
        dados["leitura"]["separador"] = ","
        dados["colunas"] = [
            {
                "nome": "total_obras",
                "cabecalho": "Total de obras",
                "tipo": "inteiro_longo",
            },
            {
                "nome": "total_cnaes",
                "cabecalho": "Total de cnaes",
                "tipo": "inteiro_longo",
            },
        ]
        for chave in ("chave", "dominios", "regras"):
            dados.pop(chave)
        self.totais = apoio.carregar(dados)

    def total(self, conteudo: str, coluna: str = "total_cnaes"):
        caminho = self.pasta / "totais.csv"
        caminho.write_text(conteudo, encoding="utf-8")
        return arquivos.ler_total_declarado(str(caminho), self.totais, coluna)

    def test_le_o_total_da_coluna(self):
        self.assertEqual(
            self.total("Total de obras,Total de cnaes\n10,20\n"), (20, [])
        )

    def test_total_nao_numerico(self):
        total, problemas = self.total("Total de obras,Total de cnaes\n10,x\n")
        self.assertIsNone(total)
        self.assertTrue(problemas)

    def test_totais_com_mais_de_um_registro(self):
        total, problemas = self.total(
            "Total de obras,Total de cnaes\n10,20\n11,21\n"
        )
        self.assertIsNone(total)
        self.assertIn("arquivo de totais com 2 registros", problemas)

    def test_cabecalho_divergente_nos_totais(self):
        total, problemas = self.total("Obras,Cnaes\n10,20\n")
        self.assertIsNone(total)
        self.assertTrue(problemas)

    def test_ler_cabecalho(self):
        caminho = self.pasta / "dados.csv"
        caminho.write_text('"A";"B;C"\n1;2\n', encoding="utf-8")
        leitura = apoio.carregar(apoio.contrato_minimo()).leitura
        self.assertEqual(
            arquivos.ler_cabecalho(str(caminho), leitura), ["A", "B;C"]
        )


if __name__ == "__main__":
    unittest.main()
