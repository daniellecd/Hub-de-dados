"""Aquisição: download, depósito, extração e preservação da Raw."""

import hashlib
import io
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path

from hub import aquisicao
from hub.ambiente import carregar_configuracao
from hub.bases import carregar_base
from testes import apoio

ID_AQUISICAO = "20260925T100000Z-abcd1234"
CONTEUDO_CSV = b"CODIGO;VALOR\n1;2,50\n"


def sha256(dados: bytes) -> str:
    """SHA-256 hexadecimal de bytes."""
    return hashlib.sha256(dados).hexdigest()


class TestAquisicao(unittest.TestCase):
    """Aquisição a partir de URLs file:// e de pasta de depósito."""

    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        raiz = Path(self.temporario.name)
        self.origem = raiz / "origem"
        self.origem.mkdir()
        with zipfile.ZipFile(self.origem / "itens.zip", "w") as pacote:
            pacote.writestr("interno/itens.csv", CONTEUDO_CSV)
            pacote.writestr("../../fuga.csv", b"x\n")
        (self.origem / "notas.txt").write_bytes(b"nota\n")
        self.montagem = raiz / "lakehouse"
        configuracao = apoio.configuracao_minima(str(self.montagem))
        self.ambiente = carregar_configuracao(configuracao).ambiente("dev")
        base = apoio.base_minima()
        base["aquisicao"] = {
            "url_base": self.origem.as_uri() + "/",
            "arquivos": ["itens.zip", "notas.txt"],
        }
        self.descritor = carregar_base(base)

    def local(self, caminho: str) -> Path:
        return Path(self.ambiente.local(caminho))

    def test_download_registra_arquivos_e_partes(self):
        detalhes = aquisicao.adquirir(
            self.descritor, self.ambiente, "2026-09", ID_AQUISICAO
        )
        pasta = f"Files/raw/fonte/base/2026-09/{ID_AQUISICAO}"
        self.assertEqual(detalhes["pasta"], pasta)
        zip_bytes = (self.origem / "itens.zip").read_bytes()
        self.assertEqual(detalhes["arquivos"][0]["sha256"], sha256(zip_bytes))
        partes = {p["parte"]: p for p in detalhes["partes"]}
        self.assertEqual(
            set(partes), {"itens/itens.csv", "itens/fuga.csv", "notas.txt"}
        )
        csv = partes["itens/itens.csv"]
        self.assertEqual(csv["sha256"], sha256(CONTEUDO_CSV))
        self.assertEqual(csv["origem"], "itens.zip")
        self.assertEqual(self.local(csv["caminho"]).read_bytes(), CONTEUDO_CSV)

    def test_membro_com_caminho_relativo_fica_dentro_da_pasta(self):
        detalhes = aquisicao.adquirir(
            self.descritor, self.ambiente, "2026-09", ID_AQUISICAO
        )
        fuga = next(
            p for p in detalhes["partes"] if p["parte"].endswith("fuga.csv")
        )
        self.assertTrue(fuga["caminho"].startswith(detalhes["pasta"] + "/"))

    def test_raw_nunca_e_sobrescrita(self):
        aquisicao.adquirir(
            self.descritor, self.ambiente, "2026-09", ID_AQUISICAO
        )
        with self.assertRaises(aquisicao.ErroAquisicao):
            aquisicao.adquirir(
                self.descritor, self.ambiente, "2026-09", ID_AQUISICAO
            )
        destino = self.montagem / "existente.bin"
        destino.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            aquisicao.gravar_fluxo(io.BytesIO(b"novo"), str(destino))
        self.assertEqual(destino.read_bytes(), b"original")

    def test_deposito_registra_e_reaproveita_extracao(self):
        pasta = self.montagem / "Files/raw/fonte/base/2026-09/deposito-1"
        pasta.mkdir(parents=True)
        for nome in ("itens.zip", "notas.txt"):
            (pasta / nome).write_bytes((self.origem / nome).read_bytes())
        argumentos = (self.descritor, self.ambiente, "2026-09", ID_AQUISICAO)
        primeira = aquisicao.adquirir(
            *argumentos, modo=aquisicao.DEPOSITO, pasta_deposito="deposito-1"
        )
        segunda = aquisicao.adquirir(
            *argumentos, modo=aquisicao.DEPOSITO, pasta_deposito="deposito-1"
        )
        self.assertEqual(primeira["partes"], segunda["partes"])
        self.assertIsNone(primeira["arquivos"][0]["url"])

    def test_deposito_sem_arquivo_declarado(self):
        pasta = self.montagem / "Files/raw/fonte/base/2026-09/deposito-2"
        pasta.mkdir(parents=True)
        with self.assertRaises(aquisicao.ErroAquisicao):
            aquisicao.adquirir(
                self.descritor,
                self.ambiente,
                "2026-09",
                ID_AQUISICAO,
                modo=aquisicao.DEPOSITO,
                pasta_deposito="deposito-2",
            )

    def test_pasta_de_deposito_invalida(self):
        with self.assertRaises(aquisicao.ErroAquisicao):
            aquisicao.adquirir(
                self.descritor,
                self.ambiente,
                "2026-09",
                ID_AQUISICAO,
                modo=aquisicao.DEPOSITO,
                pasta_deposito="../fora",
            )


class TestDownload(unittest.TestCase):
    """Retentativa de rede e erro HTTP definitivo."""

    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporario.cleanup)
        self.destino = str(Path(self.temporario.name) / "arquivo.zip")

    def test_repete_falha_de_rede(self):
        chamadas = []

        def abrir(requisicao, timeout):
            chamadas.append(requisicao.full_url)
            if len(chamadas) == 1:
                raise urllib.error.URLError("rede indisponível")
            return io.BytesIO(b"conteudo")

        total, resumo = aquisicao.baixar(
            "https://exemplo/arquivo.zip", self.destino, espera=0, abrir=abrir
        )
        self.assertEqual((total, resumo), (8, sha256(b"conteudo")))
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(Path(self.destino).read_bytes(), b"conteudo")

    def test_erro_http_4xx_nao_e_repetido(self):
        chamadas = []

        def abrir(requisicao, timeout):
            chamadas.append(requisicao.full_url)
            raise urllib.error.HTTPError(
                requisicao.full_url, 404, "Not Found", None, None
            )

        with self.assertRaises(aquisicao.ErroAquisicao):
            aquisicao.baixar(
                "https://exemplo/x.zip", self.destino, espera=0, abrir=abrir
            )
        self.assertEqual(len(chamadas), 1)
        self.assertFalse(Path(self.destino).exists())


if __name__ == "__main__":
    unittest.main()
