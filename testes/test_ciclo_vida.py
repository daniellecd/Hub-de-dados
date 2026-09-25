"""Ciclo de vida do contrato e histórico operacional."""

import unittest
from datetime import datetime

from hub import vocabulario as v
from hub.ciclo_vida import verificar_aprovavel, verificar_lastro
from hub.contrato import Pendencia
from hub.historico import Evidencias, Historico

VAZIO = Evidencias(frozenset(), frozenset())


def execucao(tipo, status=v.SUCESSO, minuto=0, **campos):
    """Linha de controle.execucoes para os testes."""
    linha = {
        "id_execucao": f"{tipo}-{minuto}",
        "tipo": tipo,
        "status": status,
        "competencia": "2026-09",
        "resultado": None,
        "hash_leitura": "hl",
        "hash_contrato": "hc",
        "versao_contrato": 1,
        "iniciado_em": datetime(2026, 9, 25, 10, minuto),
        "finalizado_em": datetime(2026, 9, 25, 10, minuto, 30),
    }
    linha.update(campos)
    return linha


class TestLastro(unittest.TestCase):
    """O estado declarado precisa de evidência no ambiente."""

    def test_provisorio_nao_exige_evidencia(self):
        self.assertEqual(
            verificar_lastro(v.PROVISORIO_DOCUMENTAL, "hl", "hc", VAZIO), []
        )

    def test_validado_exige_inspecao_do_mesmo_layout(self):
        self.assertTrue(verificar_lastro(v.VALIDADO_FISICO, "hl", "hc", VAZIO))
        outra = Evidencias(frozenset({"outro"}), frozenset())
        self.assertTrue(verificar_lastro(v.VALIDADO_FISICO, "hl", "hc", outra))
        mesma = Evidencias(frozenset({"hl"}), frozenset())
        self.assertEqual(
            verificar_lastro(v.VALIDADO_FISICO, "hl", "hc", mesma), []
        )

    def test_aprovado_exige_aprovacao_do_mesmo_hash(self):
        inspecionado = Evidencias(frozenset({"hl"}), frozenset({"antigo"}))
        self.assertTrue(verificar_lastro(v.APROVADO, "hl", "hc", inspecionado))
        aprovado = Evidencias(frozenset({"hl"}), frozenset({"hc"}))
        self.assertEqual(
            verificar_lastro(v.APROVADO, "hl", "hc", aprovado), []
        )

    def test_obsoleto_nao_publica(self):
        self.assertTrue(verificar_lastro(v.OBSOLETO, "hl", "hc", VAZIO))

    def test_aprovacao_exige_inspecao_e_nenhuma_pendencia(self):
        inspecionado = Evidencias(frozenset({"hl"}), frozenset())
        self.assertEqual(
            verificar_aprovavel(v.VALIDADO_FISICO, (), "hl", inspecionado), []
        )
        self.assertTrue(
            verificar_aprovavel(v.VALIDADO_FISICO, (), "hl", VAZIO)
        )
        pendencia = Pendencia("calibrar tolerância", v.APROVADO)
        problemas = verificar_aprovavel(
            v.VALIDADO_FISICO, (pendencia,), "hl", inspecionado
        )
        self.assertIn("pendência aberta: calibrar tolerância", problemas)


class TestHistorico(unittest.TestCase):
    """Consultas sobre as execuções registradas."""

    def test_efetivas_em_ordem_decrescente(self):
        historico = Historico(
            [
                execucao(v.PUBLICACAO_BRONZE, minuto=1),
                execucao(v.PUBLICACAO_BRONZE, v.FALHA, minuto=3),
                execucao(v.PUBLICACAO_BRONZE, v.SUCESSO_COM_ALERTA, minuto=2),
            ]
        )
        efetivas = historico.efetivos(v.PUBLICACAO_BRONZE)
        self.assertEqual(
            [e["id_execucao"] for e in efetivas], ["BRONZE-2", "BRONZE-1"]
        )
        self.assertEqual(
            historico.ultima_efetiva(v.PUBLICACAO_BRONZE)["id_execucao"],
            "BRONZE-2",
        )
        self.assertIsNone(historico.ultima_efetiva(v.PUBLICACAO_SILVER))

    def test_execucao_em_andamento_nao_e_efetiva(self):
        historico = Historico(
            [execucao(v.PUBLICACAO_SILVER, v.EM_EXECUCAO, finalizado_em=None)]
        )
        self.assertEqual(historico.efetivos(v.PUBLICACAO_SILVER), [])

    def test_aquisicao_efetiva_exige_arquivos_adquiridos(self):
        historico = Historico(
            [
                execucao(v.AQUISICAO, minuto=1, resultado=v.ADQUIRIDA),
                execucao(v.AQUISICAO, minuto=2, resultado=v.EXISTENTE),
            ]
        )
        self.assertEqual(
            historico.aquisicao_efetiva("2026-09")["id_execucao"],
            "AQUISICAO-1",
        )
        self.assertIsNone(historico.aquisicao_efetiva("2026-10"))

    def test_evidencias(self):
        historico = Historico(
            [
                execucao(v.INSPECAO, resultado=v.COMPATIVEL, hash_leitura="a"),
                execucao(
                    v.INSPECAO,
                    minuto=1,
                    resultado=v.INCOMPATIVEL,
                    hash_leitura="b",
                ),
                execucao(v.APROVACAO, resultado=v.APROVADA, hash_contrato="c"),
                execucao(
                    v.APROVACAO,
                    v.BLOQUEADA,
                    minuto=2,
                    resultado=None,
                    hash_contrato="d",
                ),
            ]
        )
        evidencias = historico.evidencias()
        self.assertEqual(evidencias.inspecoes_compativeis, {"a"})
        self.assertEqual(evidencias.aprovacoes, {"c"})

    def test_hashes_por_versao(self):
        historico = Historico(
            [
                execucao(v.PUBLICACAO_BRONZE, hash_contrato="h1"),
                execucao(v.PUBLICACAO_SILVER, minuto=1, hash_contrato="h1"),
                execucao(
                    v.PUBLICACAO_SILVER,
                    minuto=2,
                    versao_contrato=2,
                    hash_contrato="h2",
                ),
                execucao(
                    v.PUBLICACAO_SILVER, v.FALHA, minuto=3, hash_contrato="x"
                ),
            ]
        )
        self.assertEqual(historico.hashes_por_versao(), {1: {"h1"}, 2: {"h2"}})


if __name__ == "__main__":
    unittest.main()
