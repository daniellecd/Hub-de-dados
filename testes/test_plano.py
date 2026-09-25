"""Plano: fronteira entre o contrato e os executores Spark.

A mesma compilação serve às duas fontes, que diferem em cabeçalho,
separador, codificação, partes, formato de data e tipo de domínio. Não
há ramo por fonte no motor.
"""

import unittest
from dataclasses import replace

from hub import vocabulario as v
from hub.plano import (
    LINHAGEM_FISICA,
    padrao_data,
    plano_bronze,
    plano_silver,
    tipo_fisico,
)
from testes import apoio


class TestPlano(unittest.TestCase):
    """Compilação dos planos Bronze e Silver."""

    @classmethod
    def setUpClass(cls):
        cls.registro = apoio.registro_repositorio()
        cls.dev = cls.registro.ambiente("dev")

    def test_todos_os_contratos_compilam(self):
        for contrato in self.registro.contratos.values():
            with self.subTest(contrato.identificador):
                bronze = plano_bronze(contrato, self.dev)
                silver = plano_silver(contrato, self.dev)
                self.assertTrue(bronze.tabela.startswith("bronze."))
                self.assertTrue(silver.tabela.startswith("silver."))
                self.assertEqual(bronze.hash_leitura, silver.hash_leitura)

    def test_bronze_cno_com_cabecalho(self):
        plano = plano_bronze(self.registro.contrato("rfb_cno_obras"), self.dev)
        self.assertEqual(plano.tabela, "bronze.rfb_cno_obras")
        self.assertEqual(plano.opcoes_csv["header"], "true")
        self.assertEqual(plano.opcoes_csv["sep"], ",")
        self.assertEqual(plano.opcoes_csv["mode"], "PERMISSIVE")
        self.assertEqual(len(plano.cabecalho_esperado), 26)
        self.assertEqual(plano.total_declarado.entidade, "totais")
        self.assertEqual(plano.tabela_quarentena, "controle.quarentena")

    def test_bronze_cnpj_sem_cabecalho_e_multiplas_partes(self):
        contrato = self.registro.contrato("rfb_cnpj_estabelecimentos")
        plano = plano_bronze(contrato, self.dev)
        self.assertIsNone(plano.cabecalho_esperado)
        self.assertEqual(plano.opcoes_csv["header"], "false")
        self.assertEqual(plano.opcoes_csv["sep"], ";")
        self.assertEqual(plano.opcoes_csv["encoding"], "ISO-8859-1")
        self.assertEqual(plano.quantidade_partes, 10)
        self.assertEqual(len(plano.colunas_origem), 30)

    def test_bronze_mantem_tudo_como_texto_com_linhagem(self):
        plano = plano_bronze(self.registro.contrato("rfb_cno_obras"), self.dev)
        tipos = {tipo for _, tipo in plano.schema_fisico}
        self.assertEqual(tipos, {"string"})
        self.assertEqual(plano.schema_fisico[-3:], LINHAGEM_FISICA)

    def test_silver_tipos_formatos_e_transformacoes(self):
        contrato = self.registro.contrato("rfb_cnpj_estabelecimentos")
        plano = plano_silver(contrato, self.dev)
        colunas = {c.nome: c for c in plano.colunas}
        data = colunas["data_situacao_cadastral"]
        self.assertEqual(data.tipo_fisico, "date")
        self.assertEqual(data.padrao_data, "yyyyMMdd")
        self.assertEqual(
            [t.tipo for t in data.transformacoes],
            ["aparar", "vazio_como_nulo", "nulo_se"],
        )
        self.assertTrue(colunas["cnpj_basico"].na_chave)
        self.assertFalse(colunas["cnpj_basico"].verificar_nulidade)
        self.assertEqual(
            colunas["situacao_cadastral"].coluna_descricao,
            "situacao_cadastral_descricao",
        )
        self.assertIsNone(colunas["municipio"].valores_dominio)

    def test_silver_decimal_com_virgula(self):
        contrato = self.registro.contrato("rfb_cnpj_empresas")
        coluna = next(
            c
            for c in plano_silver(contrato, self.dev).colunas
            if c.nome == "capital_social"
        )
        self.assertEqual(coluna.tipo_fisico, "decimal(18,2)")
        self.assertEqual(coluna.separador_decimal, ",")

    def test_silver_schema_com_descricao_apos_a_coluna(self):
        plano = plano_silver(self.registro.contrato("rfb_cno_obras"), self.dev)
        nomes = [nome for nome, _ in plano.schema_fisico]
        indice = nomes.index("situacao")
        self.assertEqual(nomes[indice + 1], "situacao_descricao")
        self.assertEqual(plano.schema_fisico[-3:], LINHAGEM_FISICA)

    def test_nome_fisico_igual_nos_tres_ambientes(self):
        contrato = self.registro.contrato("rfb_cno_obras")
        tabelas = {
            plano_silver(contrato, self.registro.ambiente(nome)).tabela
            for nome in ("dev", "hml", "prod")
        }
        self.assertEqual(tabelas, {"silver.rfb_cno_obras"})

    def test_comentarios_derivados_do_contrato(self):
        contrato = self.registro.contrato("rfb_cno_obras")
        plano = plano_silver(contrato, self.dev)
        self.assertIn(
            "Contrato rfb_cno_obras versão 1", plano.comentario_tabela
        )
        self.assertEqual(
            plano.comentarios_colunas["cno"],
            "Número de inscrição da obra no CNO.",
        )
        self.assertIn(v.COLUNA_EXECUCAO, plano.comentarios_colunas)

    def test_padrao_de_data(self):
        self.assertEqual(padrao_data("AAAA-MM-DD"), "yyyy-MM-dd")
        self.assertEqual(padrao_data("DD/MM/AAAA"), "dd/MM/yyyy")

    def test_todo_tipo_tem_tipo_fisico(self):
        coluna = apoio.carregar(apoio.contrato_minimo()).colunas[1]
        for tipo in v.TIPOS:
            self.assertTrue(tipo_fisico(replace(coluna, tipo=tipo)))


if __name__ == "__main__":
    unittest.main()
