"""Decisões puras: destino, reconciliação, procedência, competência,
versão, cabeçalho, seleção de partes e evolução de schema."""

import unittest

from hub import decisoes
from hub import vocabulario as v


class TestDestino(unittest.TestCase):
    """O contrato decide a ação; o motor só executa."""

    def test_semantica_das_acoes(self):
        casos = [
            ([], decisoes.PUBLICAR),
            ([v.ALERTA], decisoes.PUBLICAR),
            ([v.QUARENTENA], decisoes.RETIRAR),
            ([v.QUARENTENA_E_ALERTA, v.ALERTA], decisoes.RETIRAR),
            ([v.QUARENTENA_GRUPO], decisoes.RETIRAR),
            ([v.ALERTA, v.BLOQUEIA_PUBLICACAO], decisoes.BLOQUEAR),
        ]
        for acoes, esperado in casos:
            with self.subTest(acoes=acoes):
                self.assertEqual(decisoes.destino_da_linha(acoes), esperado)

    def test_alerta(self):
        self.assertTrue(decisoes.gera_alerta([v.QUARENTENA_E_ALERTA]))
        self.assertTrue(decisoes.gera_alerta([v.ALERTA]))
        self.assertFalse(decisoes.gera_alerta([v.QUARENTENA]))


class TestReconciliacao(unittest.TestCase):
    """origem = publicadas + quarentena, com origem independente."""

    def test_identidade(self):
        self.assertEqual(decisoes.verificar_reconciliacao(10, 7, 3), [])
        self.assertTrue(decisoes.verificar_reconciliacao(10, 7, 2))

    def test_linhas_origem_descontam_cabecalho(self):
        fisicas = {"a": 11, "b": 6}
        self.assertEqual(decisoes.linhas_origem(fisicas, ["a", "b"], True), 15)
        self.assertEqual(
            decisoes.linhas_origem(fisicas, ["a", "b"], False), 17
        )

    def test_partes_conciliadas(self):
        problemas = decisoes.verificar_partes_lidas(
            ["a", "b"],
            {"a": 11, "b": 6},
            {"a": 10, "b": 5},
            {"a": 9, "b": 5},
            True,
        )
        self.assertEqual(problemas, [])

    def test_parser_que_engole_linhas_e_detectado(self):
        problemas = decisoes.verificar_partes_lidas(
            ["a"], {"a": 100}, {"a": 60}, {"a": 60}, False
        )
        self.assertIn(
            "parte a: 100 linhas físicas e 60 registros lidos", problemas
        )

    def test_parte_sem_linha_valida_e_anomalia(self):
        problemas = decisoes.verificar_partes_lidas(
            ["a", "b"],
            {"a": 3, "b": 1},
            {"a": 3, "b": 1},
            {"a": 3, "b": 0},
            False,
        )
        self.assertIn("parte b sem nenhuma linha válida", problemas)

    def test_parte_nao_contratada(self):
        problemas = decisoes.verificar_partes_lidas(
            ["a"], {"a": 1, "x": 1}, {"a": 1, "x": 1}, {"a": 1}, False
        )
        self.assertIn("parte não contratada foi lida: x", problemas)

    def test_tolerancia_de_malformadas(self):
        self.assertEqual(decisoes.verificar_tolerancia(1, 1000, 0.001), [])
        self.assertTrue(decisoes.verificar_tolerancia(2, 1000, 0.001))
        self.assertTrue(decisoes.verificar_tolerancia(1, 10, 0.0))

    def test_total_declarado(self):
        self.assertEqual(decisoes.verificar_total_declarado(5, 5), [])
        self.assertTrue(decisoes.verificar_total_declarado(5, 4))


class TestGovernanca(unittest.TestCase):
    """Competência, versão, procedência e snapshot da Bronze."""

    def test_competencia(self):
        self.assertEqual(decisoes.validar_competencia("2026-09"), [])
        for invalida in ("2026-13", "202609", "26-09", None):
            self.assertTrue(decisoes.validar_competencia(invalida))

    def test_regressao_de_competencia(self):
        self.assertEqual(
            decisoes.verificar_competencia("2026-09", None, False), []
        )
        self.assertEqual(
            decisoes.verificar_competencia("2026-09", "2026-09", False), []
        )
        self.assertTrue(
            decisoes.verificar_competencia("2026-08", "2026-09", False)
        )
        self.assertEqual(
            decisoes.verificar_competencia("2026-08", "2026-09", True), []
        )

    def test_mesma_versao_com_hash_diferente(self):
        publicados = {1: {"h1"}}
        self.assertEqual(decisoes.verificar_versao(1, "h1", publicados), [])
        self.assertTrue(decisoes.verificar_versao(1, "h2", publicados))
        self.assertEqual(decisoes.verificar_versao(2, "h2", publicados), [])

    def test_procedencia(self):
        bronze = {"competencia": "2026-09", "hash_leitura": "hl"}
        self.assertEqual(
            decisoes.verificar_procedencia(bronze, "2026-09", "hl"), []
        )
        self.assertTrue(decisoes.verificar_procedencia(None, "2026-09", "hl"))
        self.assertTrue(
            decisoes.verificar_procedencia(bronze, "2026-10", "hl")
        )
        self.assertTrue(
            decisoes.verificar_procedencia(bronze, "2026-09", "outro")
        )

    def test_snapshot_bronze(self):
        publicacao = {
            "id_execucao": "e1",
            "competencia": "2026-09",
            "linhas_publicadas": 10,
        }
        self.assertEqual(
            decisoes.verificar_snapshot_bronze(
                {("e1", "2026-09"): 10}, publicacao
            ),
            [],
        )
        self.assertTrue(
            decisoes.verificar_snapshot_bronze(
                {("e1", "2026-09"): 9, ("e0", "2026-08"): 1}, publicacao
            )
        )
        self.assertTrue(decisoes.verificar_snapshot_bronze({}, publicacao))


class TestLayout(unittest.TestCase):
    """Cabeçalho, seleção de partes e evolução de schema."""

    ESPERADO = [("CNO",), ("Nome", "Nome da obra"), ("Situação",)]

    def test_cabecalho_compativel_com_alias_e_bom(self):
        encontrado = ["﻿CNO", " Nome da obra ", "Situação"]
        self.assertEqual(
            decisoes.verificar_cabecalho(encontrado, self.ESPERADO), []
        )

    def test_mudanca_de_posicao(self):
        problemas = decisoes.verificar_cabecalho(
            ["Nome", "CNO", "Situação"], self.ESPERADO
        )
        self.assertIn(
            "coluna 'Nome' na posição 1; contrato declara 2", problemas
        )

    def test_coluna_nova_e_ausente(self):
        problemas = decisoes.verificar_cabecalho(
            ["CNO", "Nome", "Situação", "Novidade"], self.ESPERADO
        )
        self.assertIn("coluna não declarada: 'Novidade'", problemas)
        problemas = decisoes.verificar_cabecalho(
            ["CNO", "Nome"], self.ESPERADO
        )
        self.assertIn("coluna ausente no arquivo: 'Situação'", problemas)

    def test_selecao_de_partes(self):
        arquivos = [
            {
                "parte": f"Empresas{i}/K.D1.EMPRECSV",
                "caminho": f"r/E{i}/K.D1.EMPRECSV",
                "sha256": str(i),
                "bytes": i,
            }
            for i in (1, 0)
        ]
        arquivos.append(
            {
                "parte": "Socios0/K.SOCIOCSV",
                "caminho": "r/S/K.SOCIOCSV",
                "sha256": "s",
                "bytes": 1,
            }
        )
        partes = decisoes.selecionar_partes(arquivos, "*.emprecsv")
        self.assertEqual(
            [p.parte for p in partes],
            ["Empresas0/K.D1.EMPRECSV", "Empresas1/K.D1.EMPRECSV"],
        )
        self.assertEqual(decisoes.verificar_quantidade_partes(partes, 2), [])
        self.assertTrue(decisoes.verificar_quantidade_partes(partes, 10))
        self.assertTrue(decisoes.verificar_quantidade_partes([], None))

    def test_diferenca_de_schema(self):
        atual = [("a", "string"), ("b", "int"), ("c", "date")]
        planejado = [("b", "bigint"), ("a", "string"), ("d", "string")]
        diferenca = decisoes.diferenca_schema(atual, planejado)
        self.assertEqual(diferenca.adicionadas, ("d",))
        self.assertEqual(diferenca.removidas, ("c",))
        self.assertEqual(diferenca.alteradas, ("b",))
        self.assertTrue(diferenca.reordenada)
        self.assertTrue(decisoes.diferenca_schema(atual, atual).vazia)

    def test_mudanca_de_schema_exige_nova_versao(self):
        diferenca = decisoes.diferenca_schema(
            [("a", "int")], [("a", "bigint")]
        )
        self.assertTrue(decisoes.verificar_mudanca_schema(diferenca, 1, 1))
        self.assertTrue(decisoes.verificar_mudanca_schema(diferenca, 2, None))
        self.assertEqual(
            decisoes.verificar_mudanca_schema(diferenca, 2, 1), []
        )

    def test_resultado_do_diagnostico(self):
        itens = [{"resultado": v.CONFERIDA}, {"resultado": v.COM_ORFAOS}]
        self.assertEqual(decisoes.resultado_diagnostico(itens), v.COM_ORFAOS)
        itens.append({"resultado": v.REFERENCIA_AUSENTE})
        self.assertEqual(
            decisoes.resultado_diagnostico(itens), v.REFERENCIA_AUSENTE
        )
        self.assertEqual(decisoes.resultado_diagnostico([]), v.CONFERIDA)


if __name__ == "__main__":
    unittest.main()
