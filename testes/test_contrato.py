"""Validação do contrato: formato, matriz de ações e consistência."""

import unittest

from hub.erros import ContratoInvalido
from hub.registro import Registro
from testes import apoio


class TestContratoValido(unittest.TestCase):
    """Contratos aceitos e propriedades derivadas."""

    def test_contratos_do_repositorio_sao_validos(self):
        registro = apoio.registro_repositorio()
        self.assertEqual(len(registro.contratos), 15)
        self.assertEqual(set(registro.bases), {"rfb_cno", "rfb_cnpj"})

    def test_contrato_minimo_carrega(self):
        contrato = apoio.carregar(apoio.contrato_minimo())
        self.assertEqual(contrato.identificador, "fonte_base_itens")
        self.assertEqual(contrato.chave, ("codigo",))

    def test_descricao_de_dominio_vem_apos_a_coluna(self):
        contrato = apoio.carregar(apoio.contrato_minimo())
        self.assertEqual(
            contrato.colunas_saida,
            ("codigo", "valor", "data", "situacao", "situacao_descricao"),
        )

    def test_coluna_ausente_na_origem_fica_fora_do_layout(self):
        dados = apoio.contrato_minimo()
        dados["colunas"].append(
            {"nome": "antiga", "tipo": "texto", "ausente_na_origem": True}
        )
        contrato = apoio.carregar(dados)
        self.assertNotIn("antiga", [c.nome for c in contrato.colunas_origem])
        self.assertIn("antiga", contrato.colunas_saida)


class TestContratoInvalido(unittest.TestCase):
    """Cada violação de formato gera problema explícito."""

    def assertInvalido(self, dados, trecho):
        with self.assertRaises(ContratoInvalido) as contexto:
            apoio.carregar(dados)
        mensagens = "\n".join(contexto.exception.problemas)
        self.assertIn(trecho, mensagens)

    def test_chave_desconhecida(self):
        dados = apoio.contrato_minimo()
        dados["tabela_fisica"] = "silver.itens"
        self.assertInvalido(dados, "chave desconhecida: tabela_fisica")

    def test_acao_padrao_ausente_nao_tem_padrao_implicito(self):
        dados = apoio.contrato_minimo()
        del dados["acoes_padrao"]["conversao"]
        self.assertInvalido(dados, "chave obrigatória ausente: conversao")

    def test_chave_duplicada_nao_aceita_alerta(self):
        dados = apoio.contrato_minimo()
        dados["acoes_padrao"]["chave_duplicada"] = "ALERTA"
        self.assertInvalido(dados, "acoes_padrao.chave_duplicada")

    def test_chave_duplicada_nao_aceita_quarentena_simples(self):
        dados = apoio.contrato_minimo()
        dados["acoes_padrao"]["chave_duplicada"] = "QUARENTENA"
        self.assertInvalido(dados, "acoes_padrao.chave_duplicada")

    def test_quarentena_grupo_so_para_chave_duplicada(self):
        dados = apoio.contrato_minimo()
        dados["acoes_padrao"]["nulidade"] = "QUARENTENA_GRUPO"
        self.assertInvalido(dados, "acoes_padrao.nulidade")

    def test_dominio_literal_acima_do_limite(self):
        dados = apoio.contrato_minimo()
        dados["dominios"]["situacao"]["valores"] = {
            str(n): f"valor {n}" for n in range(16)
        }
        self.assertInvalido(dados, "excedem o limite de 15")

    def test_codigo_de_dominio_precisa_ser_texto(self):
        dados = apoio.contrato_minimo()
        dados["dominios"]["situacao"]["valores"] = {1: "Um"}
        self.assertInvalido(dados, "deve ser texto")

    def test_dominio_exige_coluna_texto(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][1]["dominio"] = "situacao"
        self.assertInvalido(dados, "domínio exige coluna do tipo texto")

    def test_dominio_declarado_e_nao_usado(self):
        dados = apoio.contrato_minimo()
        dados["dominios"]["sobra"] = {
            "tipo": "literal",
            "valores": {"X": "Xis"},
        }
        self.assertInvalido(dados, "domínio declarado e não usado")

    def test_arquivo_com_cabecalho_exige_nome(self):
        dados = apoio.contrato_minimo()
        del dados["colunas"][0]["cabecalho"]
        self.assertInvalido(dados, "arquivo com cabeçalho exige")

    def test_arquivo_sem_cabecalho_recusa_nome(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["cabecalho"] = False
        self.assertInvalido(dados, "arquivo sem cabeçalho")

    def test_decimal_exige_separador(self):
        dados = apoio.contrato_minimo()
        del dados["colunas"][1]["separador_decimal"]
        self.assertInvalido(dados, "exige separador_decimal")

    def test_parametro_de_tipo_que_nao_se_aplica(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["formato"] = "AAAAMMDD"
        self.assertInvalido(dados, "formato não se aplica ao tipo texto")

    def test_formato_de_data_incompleto(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][2]["formato"] = "AAAA-MM"
        self.assertInvalido(dados, "combine AAAA, MM e DD")

    def test_transformacao_desconhecida(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["transformacoes"] = ["capitalizar"]
        self.assertInvalido(dados, "transformação desconhecida")

    def test_parametro_de_transformacao_invalido(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["transformacoes"] = [
            {"preencher_esquerda": {"tamanho": 0, "caractere": "0"}}
        ]
        self.assertInvalido(dados, "esperado inteiro_positivo")

    def test_regra_com_coluna_fora_da_lista(self):
        dados = apoio.contrato_minimo()
        dados["regras"][0]["expressao"] = "valor > 0 AND codigo = 'X'"
        self.assertInvalido(dados, "fora de colunas_referenciadas: codigo")

    def test_regra_com_funcao_nao_deterministica(self):
        dados = apoio.contrato_minimo()
        dados["regras"][0]["expressao"] = "data <= current_date()"
        dados["regras"][0]["colunas_referenciadas"] = ["data"]
        self.assertInvalido(dados, "função não permitida: current_date")

    def test_nome_reservado_para_linhagem(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["nome"] = "competencia"
        dados["chave"] = ["competencia"]
        self.assertInvalido(dados, "nome reservado ao motor: competencia")

    def test_chave_com_coluna_inexistente(self):
        dados = apoio.contrato_minimo()
        dados["chave"] = ["inexistente"]
        self.assertInvalido(dados, "coluna inexistente: inexistente")

    def test_pendencia_impede_estado_declarado(self):
        dados = apoio.contrato_minimo()
        dados["documentacao"] = {
            "estado": "VALIDADO_FISICO",
            "pendencias": [
                {"descricao": "confirmar dialeto", "impede": "VALIDADO_FISICO"}
            ],
        }
        self.assertInvalido(dados, "impedido pela pendência")

    def test_tolerancia_fora_do_intervalo(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["tolerancia_malformadas"] = 1.5
        self.assertInvalido(dados, "intervalo [0, 1)")

    def test_codificacao_fora_do_vocabulario(self):
        dados = apoio.contrato_minimo()
        dados["leitura"]["codificacao"] = "ebcdic"
        self.assertInvalido(dados, "leitura.codificacao")

    def test_reporta_todos_os_problemas_de_uma_vez(self):
        dados = apoio.contrato_minimo()
        dados["versao"] = 0
        dados["leitura"]["separador"] = ";;"
        with self.assertRaises(ContratoInvalido) as contexto:
            apoio.carregar(dados)
        self.assertGreaterEqual(len(contexto.exception.problemas), 2)


class TestRegistro(unittest.TestCase):
    """Validações que cruzam arquivos."""

    def test_referencia_a_contrato_inexistente(self):
        dados = apoio.contrato_minimo()
        dados["colunas"][0]["dominio"] = "externo"
        dados["dominios"]["externo"] = {
            "tipo": "referencia",
            "tabela": {"fonte": "fonte", "base": "base", "entidade": "nada"},
            "coluna": "codigo",
        }
        with self.assertRaises(ContratoInvalido) as contexto:
            apoio.registro_minimo(dados)
        self.assertIn("contrato inexistente", str(contexto.exception))

    def test_chave_do_mapa_precisa_ser_o_identificador(self):
        dados = {
            "configuracao": apoio.configuracao_minima(),
            "bases": {"fonte_base": apoio.base_minima()},
            "contratos": {"fonte_base_outro": apoio.contrato_minimo()},
        }
        with self.assertRaises(ContratoInvalido) as contexto:
            Registro.de_dicionario(dados)
        self.assertIn("identificador declarado", str(contexto.exception))

    def test_total_declarado_exige_coluna_inteira(self):
        dados = apoio.contrato_minimo()
        dados["reconciliacao"] = {
            "total_declarado": {"entidade": "totais", "coluna": "total"}
        }
        totais = apoio.contrato_minimo()
        totais["identidade"]["entidade"] = "totais"
        totais["colunas"] = [
            {"nome": "total", "cabecalho": "TOTAL", "tipo": "texto"}
        ]
        totais["chave"] = ["total"]
        totais.pop("dominios")
        totais.pop("regras")
        registro = {
            "configuracao": apoio.configuracao_minima(),
            "bases": {"fonte_base": apoio.base_minima()},
            "contratos": {
                "fonte_base_itens": dados,
                "fonte_base_totais": totais,
            },
        }
        with self.assertRaises(ContratoInvalido) as contexto:
            Registro.de_dicionario(registro)
        self.assertIn(
            "coluna do total deve ser inteira", str(contexto.exception)
        )

    def test_referencias_entre_bases_do_repositorio(self):
        registro = apoio.registro_repositorio()
        obras = registro.contrato("rfb_cno_obras")
        alvo = obras.dominios["municipio_rfb"].tabela.identificador
        self.assertEqual(alvo, "rfb_cnpj_municipios")
        self.assertEqual(
            registro.contrato_do_total(obras).identificador, "rfb_cno_totais"
        )


if __name__ == "__main__":
    unittest.main()
