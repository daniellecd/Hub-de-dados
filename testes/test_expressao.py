"""Validação das expressões de regra antes da execução."""

import unittest

from hub.expressao import tokenizar, validar_expressao

COLUNAS = ["valor", "data_inicio", "data_fim", "codigo", "nome"]


class TestExpressao(unittest.TestCase):
    """Só vocabulário fechado e colunas declaradas passam."""

    def validar(self, expressao, referenciadas):
        return validar_expressao(expressao, referenciadas, COLUNAS)

    def test_aceita_predicado_com_funcoes_e_literais(self):
        problemas = self.validar(
            "(valor IS NULL OR valor >= 0) AND length(trim(codigo)) = 8 "
            "AND codigo IN ('A', 'B') AND nome LIKE 'X%'",
            ["valor", "codigo", "nome"],
        )
        self.assertEqual(problemas, [])

    def test_aceita_literal_de_data(self):
        problemas = self.validar(
            "data_inicio >= DATE '1900-01-01'", ["data_inicio"]
        )
        self.assertEqual(problemas, [])

    def test_marcador_dentro_de_literal_e_aceito(self):
        problemas = self.validar("nome LIKE '%--%;'", ["nome"])
        self.assertEqual(problemas, [])

    def test_identificador_nao_declarado(self):
        problemas = self.validar("valor > 0 AND codigo = 'X'", ["valor"])
        self.assertIn(
            "identificador fora de colunas_referenciadas: codigo", problemas
        )

    def test_funcao_fora_do_vocabulario(self):
        for funcao in ("current_date", "rand", "now", "uuid"):
            problemas = self.validar(
                f"data_inicio <= {funcao}()", ["data_inicio"]
            )
            self.assertIn(f"função não permitida: {funcao}", problemas)

    def test_comentario_e_separador_de_comando(self):
        for expressao in (
            "valor > 0 -- comentario",
            "valor > 0 /* comentario */",
        ):
            problemas = self.validar(expressao, ["valor"])
            self.assertTrue(
                any("marcador proibido" in p for p in problemas), expressao
            )

    def test_encadeamento_e_aspas_duplas_sao_recusados(self):
        for expressao in (
            "valor > 0; DROP TABLE x",
            "t.valor > 0",
            'codigo = "A"',
            "`valor` > 0",
        ):
            self.assertNotEqual(self.validar(expressao, ["valor"]), [])

    def test_subconsulta_e_recusada(self):
        problemas = self.validar(
            "valor IN (SELECT valor FROM tabela)", ["valor"]
        )
        self.assertIn(
            "identificador fora de colunas_referenciadas: SELECT", problemas
        )

    def test_parenteses_desbalanceados(self):
        problemas = self.validar("(valor > 0", ["valor"])
        self.assertIn("parênteses desbalanceados", problemas)

    def test_coluna_declarada_e_nao_usada(self):
        problemas = self.validar("valor > 0", ["valor", "codigo"])
        self.assertIn("coluna referenciada e não usada: codigo", problemas)

    def test_coluna_referenciada_inexistente(self):
        problemas = self.validar("saldo > 0", ["saldo"])
        self.assertIn("coluna referenciada inexistente: saldo", problemas)

    def test_expressao_vazia(self):
        self.assertEqual(self.validar("  ", []), ["expressão vazia"])

    def test_tokenizacao(self):
        self.assertEqual(
            tokenizar("valor >= 10.5"),
            [("palavra", "valor"), ("operador", ">="), ("numero", "10.5")],
        )


if __name__ == "__main__":
    unittest.main()
