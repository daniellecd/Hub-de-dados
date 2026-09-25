"""Catálogo: estrutural derivado do contrato, curadoria preservada."""

import unittest

from hub import catalogo
from hub import vocabulario as v
from testes import apoio


class TestCatalogo(unittest.TestCase):
    """Linhas estruturais das tabelas de catálogo."""

    @classmethod
    def setUpClass(cls):
        registro = apoio.registro_repositorio()
        cls.linhas = catalogo.linhas_catalogo(
            list(registro.contratos.values()),
            registro.ambiente("dev"),
            {"silver.rfb_cno_obras"},
        )
        cls.ativos = {
            linha["ativo"]: linha
            for linha in cls.linhas[catalogo.TABELA_ATIVOS]
        }
        cls.colunas = {
            (linha["ativo"], linha["coluna"]): linha
            for linha in cls.linhas[catalogo.TABELA_COLUNAS]
        }

    def test_bronze_e_silver_sao_ativos_distintos(self):
        self.assertEqual(len(self.ativos), 30)
        self.assertEqual(
            self.ativos["bronze.rfb_cno_obras"]["camada"], "bronze"
        )
        self.assertEqual(
            self.ativos["silver.rfb_cno_obras"]["camada"], "silver"
        )

    def test_curadoria_nasce_a_confirmar(self):
        for ativo in self.ativos.values():
            for campo in catalogo.CURATORIAIS[catalogo.TABELA_ATIVOS]:
                self.assertEqual(ativo[campo], v.A_CONFIRMAR)

    def test_existencia_fisica(self):
        self.assertTrue(self.ativos["silver.rfb_cno_obras"]["existe"])
        self.assertFalse(self.ativos["bronze.rfb_cno_obras"]["existe"])

    def test_dependencias(self):
        dependencias = {
            (d["ativo"], d["depende_de"], d["tipo"], d["coluna"])
            for d in self.linhas[catalogo.TABELA_DEPENDENCIAS]
        }
        esperadas = {
            ("bronze.rfb_cno_obras", "Files/raw/rfb/cno", "ORIGEM", None),
            ("silver.rfb_cno_obras", "bronze.rfb_cno_obras", "CAMADA", None),
            (
                "silver.rfb_cno_obras",
                "silver.rfb_cnpj_municipios",
                "REFERENCIA",
                "codigo_municipio",
            ),
        }
        self.assertLessEqual(esperadas, dependencias)

    def test_colunas_com_tipo_dominio_e_chave(self):
        silver = "silver.rfb_cno_obras"
        self.assertEqual(
            self.colunas[(silver, "situacao")]["dominio"], "situacao_obra"
        )
        self.assertEqual(self.colunas[(silver, "data_inicio")]["tipo"], "date")
        self.assertTrue(self.colunas[(silver, "cno")]["chave"])
        self.assertFalse(self.colunas[(silver, "cno")]["nulavel"])
        bronze = "bronze.rfb_cno_obras"
        self.assertEqual(
            self.colunas[(bronze, "data_inicio")]["tipo"], "string"
        )
        self.assertIsNone(self.colunas[(bronze, "situacao")]["dominio"])

    def test_catalogo_nao_guarda_metrica_de_execucao(self):
        metricas = {"linhas_publicadas", "linhas_quarentena", "status"}
        for esquema in catalogo.ESQUEMAS.values():
            self.assertFalse({nome for nome, _ in esquema} & metricas)

    def test_linhas_completas_e_estruturais_sem_curadoria(self):
        for tabela, registros in self.linhas.items():
            nomes = sorted(nome for nome, _ in catalogo.ESQUEMAS[tabela])
            for registro in registros:
                self.assertEqual(sorted(registro), nomes)
            estruturais = set(catalogo.colunas_estruturais(tabela))
            self.assertFalse(estruturais & set(catalogo.CURATORIAIS[tabela]))


if __name__ == "__main__":
    unittest.main()
