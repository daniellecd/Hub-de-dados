# Registro de decisões

Documento único e datado das decisões do Hub de Dados (seção 6.8 do
briefing). Guias e relatórios apontam para este registro e não criam
decisão divergente. Uma decisão revista ganha entrada nova, que informa o
que mudou e por quê. Entradas antigas não são apagadas.

---

## 2026-09-25 — Primeiro entregável: motor genérico, CNO ponta a ponta e contratos CNPJ

### Contexto

- **Repositório:** estava vazio no início da sessão.
- **Ambiente de desenvolvimento:** Python 3.11 com PyYAML, sem PySpark.
- **Rede:** a política bloqueava o PyPI e os domínios da Receita Federal
  (`arquivos.receitafederal.gov.br`, `dadosabertos.rfb.gov.br`). Por isso
  não houve inspeção dos arquivos reais nem execução Spark local.
- **Consequência:** todos os contratos nascem `PROVISORIO_DOCUMENTAL`,
  escritos a partir dos layouts oficiais (CNO e novo layout do CNPJ de
  dez/2021).

### Escopo e critérios de aceite do entregável

O escopo foi definido com a responsável pelo projeto antes da edição:

- motor genérico;
- CNO ponta a ponta;
- contratos do CNPJ apenas como prova local de generalidade (validam e
  compilam em plano sem alterar o motor).

A execução do CNPJ no Fabric é o próximo entregável.

| Critério (seção 9) | Situação |
|---|---|
| Geradores em clone limpo reproduzem os notebooks byte a byte | Atendido localmente (teste e CI) |
| Suíte local sem Spark cobrindo contrato, plano, fronteira dos motores e decisões puras | Atendido (157 testes, `unittest`) |
| Contrato válido, hash determinístico, documentação fora do hash | Atendido (testes de hash) |
| Reconciliação comprovada na execução real | Pendente: exige execução no Fabric (roteiro em `docs/operacao.md`) |
| Comentários físicos de tabela e coluna derivados do contrato | Implementado; comprovação física pendente |
| Execução registrada em tabela única de controle, com escrita idempotente | Implementado; comprovação física pendente |

O teste textual sobre o JSON do notebook verifica estrutura; não é aceite
de comportamento.

### Avaliação do briefing por seção

| Seção | Parecer |
|---|---|
| 1. Problema | Adotado. 50 a 70 tabelas por camada inviabilizam um notebook por tabela. |
| 2. Framework dirigido por contrato | Adotado. CNO e CNPJ formam um bom par de prova: diferem em cabeçalho, separador, codificação, número de partes, formato de data e tipo de domínio. |
| 3. Camadas | Adotado, com os ajustes C2, C3 e A4. |
| 4. Responsabilidades | Adotado. Lacuna preenchida: a aquisição não tinha dono (A5). |
| 5. Qualidade | Adotado, com os ajustes C2, C3, C4, A1, A2 e A3. |
| 6. Governança | Adotado, com os ajustes C1, C5 e A7. |
| 7. Regras invioláveis | Adotado. Cada regra virou verificação automática (`testes/test_regras_inviolaveis.py`). |
| 8. O que não construir | Adotado integralmente. |
| 9. Critérios de aceite | Adotado (quadro acima). |
| 10–11. Regime e primeiro entregável | Conflito com o pedido (C7), resolvido pelo escopo acima. |

### Contradições encontradas e resolução

**C1. Procedência × custo de reprocessamento (seções 6.3 e 6.4).**

- **Contradição:** com hash único, qualquer ajuste de regra da Silver
  invalida a Bronze e obriga a reler os CSVs.
- **Decisão:** um contrato por entidade, com dois hashes da parte
  executável:
  - `hash_leitura`: seleção, dialeto, layout de origem, ação para linha
    malformada e total declarado;
  - `hash_contrato`: toda a parte executável.
- **Efeito:** a Silver só lê a Bronze publicada com o mesmo
  `hash_leitura`.

**C2. Reconciliação tautológica (seção 5.5).**

- **Contradição:** se a origem for contada pelo mesmo parser que separa
  válidas e malformadas, a identidade é verdadeira por construção.
- **Decisão:** cada termo da reconciliação tem medida independente.

| Termo | Como é medido |
|---|---|
| Origem | Linhas físicas não vazias por parte, lidas sem o parser CSV. Quando o contrato declara `reconciliacao.total_declarado`, também o total publicado pela fonte (`CNO_TOTAIS.CSV`) |
| Publicadas | Métrica do commit Delta |
| Quarentena | Leitura da tabela após a escrita |

**C3. Bronze tolerante × "mudança silenciosa bloqueia" (seções 5.1 e
6.5).**

- **Contradição:** em arquivo sem cabeçalho, uma coluna nova torna todas
  as linhas malformadas, e a Bronze seria publicada vazia sem bloquear.
- **Decisão:** `leitura.tolerancia_malformadas` é obrigatória no contrato.
  Acima dela, a divergência é estrutural e bloqueia.

**C4. Domínio por tabela externa (seção 5.7 × seção 8 × item 12 do
gate).**

- **Contradição:** conferir no gate da Silver cria dependência de ordem de
  carga e torna a reexecução não idempotente.
- **Decisão:** a referência é declarada no contrato, entra no catálogo
  como dependência e é conferida apenas no diagnóstico sob demanda
  (`nb_hub_diagnosticar`).
- **Efeito:** a ausência da referência resulta em `REFERENCIA_AUSENTE`,
  sem bloquear a entidade.

**C5. Lastro do ciclo de vida (seção 6.2 × seção 6.7).**

- **Contradição:** a evidência deve ser o registro operacional, mas esse
  registro é de cada ambiente.
- **Decisão:** o lastro fica em `controle.execucoes` de cada ambiente, e a
  inspeção e a aprovação são repetidas em DEV, HML e PROD.

**C6. Integração Git do Fabric × regra 4.**

- **Contradição:** o formato Git do Fabric grava `logicalId` e os GUIDs
  de lakehouse e workspace.
- **Decisão:** os notebooks são gerados em `.ipynb` sem metadado de
  lakehouse e implantados por importação.
- **Efeito:** o lakehouse padrão é resolvido pelo nome (`%%configure`).

**C7. Escopo (seções 10 e 11 × pedido).**

- **Contradição:** o briefing prevê uma fonte por entregável; o pedido
  cita framework, CNO e CNPJ.
- **Decisão:** CNO ponta a ponta mais contratos do CNPJ como prova de
  generalidade.

### Ajustes adotados

- **A1. Matriz de ações por classe de violação.**
  - `chave_duplicada` aceita só `QUARENTENA_GRUPO` ou `BLOQUEIA_PUBLICACAO`.
  - `QUARENTENA_GRUPO` só vale para chave duplicada.
  - As seis classes de `acoes_padrao` são obrigatórias: não existe ação
    implícita.
- **A2. Expressões de regra determinísticas.**
  - Sem `current_date`, `now` ou `rand`.
  - TRUE aprova; FALSE e NULL violam, e o autor trata nulo explicitamente.
- **A3. Somente colunas escalares nas tabelas publicadas e de controle.**
  Listas ficam como texto ou JSON.
- **A4. Arquivo corrompido não gera linha de quarentena.** É falha
  estrutural da parte.
- **A5. Descritor de base** (`contratos/<fonte>/<base>/base.yaml`) com URL
  e arquivos da publicação.
- **A6. Raw por aquisição:** `raw/<fonte>/<base>/<competencia>/<id>/`.
  Nunca há sobrescrita.
- **A7. Evolução de schema explícita.**
  - Mudança exige versão de contrato maior que a vigente.
  - Mesma versão com hash diferente bloqueia.
- **A8. Testes com `unittest`, sem Spark nem instalação extra.** Incluem
  verificação de nome de fonte no motor e de GUID no repositório.
- **A9.** Este registro de decisões.

### Decisões tomadas com a responsável pelo projeto

| Pergunta | Decisão |
|---|---|
| Escopo do entregável | CNO ponta a ponta + contratos CNPJ como prova de generalidade |
| Organização dos Lakehouses | Um Lakehouse por workspace (`lh_hub`), schemas `bronze`, `silver` e `controle`, Raw em `Files/raw` |
| Distribuição do motor | Notebook-biblioteca gerado, usado por `%run` |
| Aquisição | Download pelo notebook, com modo de depósito como contingência |
| Histórico por competência | Só a última competência nas duas camadas (snapshot); histórico na Raw |
| Procedência entre camadas | Hash por seção (`hash_leitura` e `hash_contrato`) |
| Domínio por referência | Declarado; conferido apenas em diagnóstico |
| Lastro do ciclo de vida | Tabela de controle de cada ambiente; sem política de estado mínimo por ambiente |

### Decisões de implementação

| Nº | Decisão | Motivo |
|---|---|---|
| D1 | Snapshot sobrescrito a cada publicação; a coluna `competencia` permanece nas linhas | Decisão de histórico; identifica a competência vigente |
| D2 | Publicar competência anterior à vigente bloqueia, salvo `permitir_competencia_anterior=True` | Snapshot não regride por engano |
| D3 | Aquisição já efetiva não é repetida sem `forcar=True` | Evita duplicar dezenas de GB na Raw |
| D4 | Divergência após a escrita restaura a versão anterior; se a tabela nasceu na tentativa, é removida | "Falha de reconciliação preserva o snapshot vigente" |
| D5 | `BLOQUEIA_PUBLICACAO` não escreve tabela nem quarentena; contagens e exemplos vão ao registro | "Nenhuma linha é publicada" |
| D6 | Violações sem regra própria usam `acoes_padrao`; chave nula é verificada só como `chave_nula` | Evita motivo duplicado para a mesma causa |
| D7 | Dimensões: linha malformada → Conformity; nulidade, conversão e chave nula → Completeness; domínio → Consistency; duplicidade → Uniqueness; regras declaram a sua | Vocabulário do briefing; Freshness segue lacuna |
| D8 | Na Bronze, campo vazio é nulo (comportamento do leitor); a Silver aplica `vazio_como_nulo` quando declarado | Representação uniforme entre fontes |
| D9 | Linhagem mínima: `competencia`, `_arquivo_origem`, `_id_execucao` | O resto está no controle, via `_id_execucao` |
| D10 | `controle.execucoes` e `controle.quarentena` particionadas por `identificador`, com MERGE e retentativa em conflito | Execuções paralelas de entidades diferentes não disputam arquivos |
| D11 | Id da quarentena = hash de publicação, seção executada, conteúdo e índice de ocorrência | Reexecução não duplica evidência; duplicatas idênticas sem vencedora |
| D12 | `id_execucao` no formato `AAAAMMDDTHHMMSSZ-<8 hex>` | Não é GUID; distingue tentativas |
| D13 | Sessão Spark: `csv.parser.columnPruning` desligado e `timeParserPolicy=CORRECTED`; conversões por `try_cast` e `try_to_timestamp` | Largura divergente sempre detectada; valor inválido vira nulo com ou sem ANSI |
| D14 | Notebook-biblioteca com motor e registro embutidos (YAML convertido em JSON) e assinatura conferida ao carregar | Fabric sem PyYAML; recusa edição fora do gerador |
| D15 | Contratos em PROVISORIO declaram UTF-8 quando a codificação é desconhecida | Codificação errada falha de forma visível na inspeção |
| D16 | Código Spark limitado a funções nativas (sem UDF Python) | Desempenho e execução no executor sem dependências |
| D17 | PEP 8 com 79 colunas, verificado por teste; CI em GitHub Actions roda testes e `--verificar` | Regra do projeto aplicada sem ferramenta extra no Fabric |

### Lacunas conhecidas e limites

- **Freshness (Atualidade)** permanece lacuna. Não será implementada sem
  periodicidade, tolerância e ação operacional.
- **Contratos ainda sem evidência física.** Todos estão em
  `PROVISORIO_DOCUMENTAL`. Destaques das pendências (lista completa em cada
  contrato):
  - **CNO:** separador, codificação e cabeçalho desconhecidos; o layout
    declara datas com tamanho 8 e formato AAAA-MM-DD, o que é
    contraditório; campos de áreas com tamanho 150 podem trazer descrição
    em vez de código.
  - **CNPJ:** o layout informa a situação cadastral com preenchimento
    inconsistente; `Motivos` não consta do layout; datas nulas e vírgula
    decimal não estão documentadas.
- **Código Spark (`hub/spark`, `hub/orquestracao.py`) não foi executado.**
  Foi validado por compilação, pela execução da biblioteca com Spark
  simulado e por revisão. O aceite físico exige execução no Fabric.
- **URLs de aquisição não foram confirmadas** (rede bloqueada nesta
  sessão). O modo de depósito cobre a contingência.
- **Diagnóstico de referências do CNO:** até o CNPJ ser publicado no
  Fabric, o resultado esperado é `REFERENCIA_AUSENTE`.
