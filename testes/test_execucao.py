"""Registro de execução, esquemas operacionais e retentativa."""

import json
import re
import unittest
from datetime import UTC, datetime

from hub import vocabulario as v
from hub.execucao import (
    COLUNAS_EXECUCOES,
    COLUNAS_QUARENTENA,
    RegistroExecucao,
    novo_id_execucao,
)
from hub.retentativa import com_retentativa, conflito_concorrente

TIPOS_ESCALARES = {"STRING", "INT", "BIGINT", "BOOLEAN", "TIMESTAMP"}


class ConcurrentAppendException(Exception):
    """Imita o conflito de concorrência do Delta Lake."""


class TestRegistroExecucao(unittest.TestCase):
    """A tentativa é registrada de forma escalar e idempotente."""

    def novo(self):
        return RegistroExecucao(
            id_execucao="20260925T100000Z-abcd1234",
            identificador="fonte_base_itens",
            tipo=v.PUBLICACAO_BRONZE,
            ambiente="dev",
            versao_motor="0.1.0+teste",
        )

    def test_id_de_execucao_nao_e_guid(self):
        momento = datetime(2026, 9, 25, 10, 0, 0, tzinfo=UTC)
        identificador = novo_id_execucao(momento, "abcd1234")
        self.assertEqual(identificador, "20260925T100000Z-abcd1234")
        self.assertRegex(novo_id_execucao(), r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")

    def test_status_de_sucesso_considera_alertas(self):
        registro = self.novo()
        self.assertEqual(registro.status_sucesso(), v.SUCESSO)
        registro.alertar("linhas malformadas")
        self.assertEqual(registro.status_sucesso(), v.SUCESSO_COM_ALERTA)

    def test_linha_segue_a_ordem_das_colunas(self):
        registro = self.novo()
        registro.detalhes["partes"] = {"a": 1}
        registro.alertar("aviso")
        registro.finalizar(v.BLOQUEADA, "x" * 5000)
        linha = registro.para_linha()
        self.assertEqual(len(linha), len(COLUNAS_EXECUCOES))
        valores = dict(
            zip([n for n, _ in COLUNAS_EXECUCOES], linha, strict=True)
        )
        self.assertEqual(valores["status"], v.BLOQUEADA)
        self.assertEqual(len(valores["motivo"]), 4000)
        detalhes = json.loads(valores["detalhes"])
        self.assertEqual(detalhes, {"alertas": ["aviso"], "partes": {"a": 1}})

    def test_tabelas_operacionais_so_tem_colunas_escalares(self):
        for nome, tipo in COLUNAS_EXECUCOES + COLUNAS_QUARENTENA:
            with self.subTest(nome):
                self.assertIn(tipo, TIPOS_ESCALARES)
                self.assertRegex(nome, re.compile(r"^[a-z][a-z0-9_]*$"))


class TestRetentativa(unittest.TestCase):
    """Só conflito de concorrência é repetido."""

    def test_repete_conflito_e_depois_conclui(self):
        tentativas = []

        def operacao():
            tentativas.append(1)
            if len(tentativas) < 3:
                raise ConcurrentAppendException("Files were added")
            return "ok"

        esperas = []
        self.assertEqual(
            com_retentativa(operacao, dormir=esperas.append), "ok"
        )
        self.assertEqual(esperas, [2.0, 4.0])

    def test_outro_erro_nao_e_repetido(self):
        tentativas = []

        def operacao():
            tentativas.append(1)
            raise ValueError("erro de dados")

        with self.assertRaises(ValueError):
            com_retentativa(operacao, dormir=lambda _: None)
        self.assertEqual(len(tentativas), 1)

    def test_esgota_as_tentativas(self):
        def operacao():
            raise ConcurrentAppendException("conflito")

        with self.assertRaises(ConcurrentAppendException):
            com_retentativa(operacao, tentativas=2, dormir=lambda _: None)

    def test_identificacao_do_conflito(self):
        self.assertTrue(conflito_concorrente(ConcurrentAppendException()))
        self.assertFalse(conflito_concorrente(RuntimeError("falha")))


if __name__ == "__main__":
    unittest.main()
