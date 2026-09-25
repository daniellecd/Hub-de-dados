"""Hashes determinísticos, documentação fora do hash e seções."""

import unittest

from hub.hashes import canonico, fingerprint, hash_contrato, hash_leitura
from testes import apoio


class TestHashes(unittest.TestCase):
    """O hash identifica apenas a parte executável."""

    def setUp(self):
        self.base = apoio.carregar(apoio.contrato_minimo())

    def hashes(self, dados):
        contrato = apoio.carregar(dados)
        return hash_leitura(contrato), hash_contrato(contrato)

    def test_hash_e_deterministico(self):
        self.assertEqual(
            self.hashes(apoio.contrato_minimo()),
            (hash_leitura(self.base), hash_contrato(self.base)),
        )

    def test_ordem_das_chaves_nao_altera_o_hash(self):
        dados = apoio.contrato_minimo()
        invertido = dict(reversed(list(dados.items())))
        self.assertEqual(self.hashes(invertido), self.hashes(dados))

    def test_documentacao_e_versao_ficam_fora_do_hash(self):
        dados = apoio.contrato_minimo()
        dados["versao"] = 7
        dados["descricao"] = "Outra descrição."
        dados["colunas"][0]["descricao"] = "Código do item."
        dados["documentacao"] = {
            "estado": "PROVISORIO_DOCUMENTAL",
            "fonte_documental": "Manual.",
            "pendencias": [
                {"descricao": "confirmar", "impede": "VALIDADO_FISICO"}
            ],
        }
        self.assertEqual(
            self.hashes(dados), self.hashes(apoio.contrato_minimo())
        )

    def test_regra_da_silver_nao_altera_hash_de_leitura(self):
        dados = apoio.contrato_minimo()
        dados["regras"][0]["acao"] = "QUARENTENA"
        leitura, contrato = self.hashes(dados)
        self.assertEqual(leitura, hash_leitura(self.base))
        self.assertNotEqual(contrato, hash_contrato(self.base))

    def test_tipo_da_silver_nao_altera_hash_de_leitura(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][1]["precisao"] = 12
        leitura, contrato = self.hashes(dados)
        self.assertEqual(leitura, hash_leitura(self.base))
        self.assertNotEqual(contrato, hash_contrato(self.base))

    def test_dialeto_altera_os_dois_hashes(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["separador"] = ","
        leitura, contrato = self.hashes(dados)
        self.assertNotEqual(leitura, hash_leitura(self.base))
        self.assertNotEqual(contrato, hash_contrato(self.base))

    def test_alias_altera_hash_de_leitura(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["aliases"] = ["COD"]
        self.assertNotEqual(self.hashes(dados)[0], hash_leitura(self.base))

    def test_fingerprint_independe_da_ordem_e_depende_do_conteudo(self):
        partes = [("b/2.csv", "bb"), ("a/1.csv", "aa")]
        self.assertEqual(fingerprint(partes), fingerprint(reversed(partes)))
        self.assertNotEqual(
            fingerprint(partes), fingerprint([("a/1.csv", "aa")])
        )
        self.assertNotEqual(
            fingerprint(partes),
            fingerprint([("a/1.csv", "aa"), ("b/2.csv", "cc")]),
        )

    def test_canonico_ordena_chaves_sem_espacos(self):
        self.assertEqual(
            canonico({"b": 1, "a": [1, "ç"]}), '{"a":[1,"ç"],"b":1}'
        )


if __name__ == "__main__":
    unittest.main()
