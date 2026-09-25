# Hub de Dados

Framework de ingestão dirigido por contrato para o Microsoft Fabric.
Publica dados abertos nas camadas Bronze e Silver com quarentena,
reconciliação, registro operacional e catálogo.

Cada fonte é descrita declarativamente, em YAML versionado, e um motor
genérico a executa. Regra específica de fonte não fica espalhada em
notebooks.

## Estado deste entregável

- **Motor genérico** (`hub/`): núcleo puro testado localmente;
  executores Spark e Delta em `hub/spark/`.
- **CNO ponta a ponta:** descritor da base e cinco contratos.
- **CNPJ:** descritor e dez contratos, usados como prova local de
  generalidade. Eles validam e compilam sem alteração do motor.
- **Estado dos contratos:** todos em `PROVISORIO_DOCUMENTAL`, sem
  evidência física ainda. O aceite físico depende de execução no Fabric
  (`docs/operacao.md`, seção 5).

## Estrutura

```text
hub/                     motor genérico (sem nome de fonte)
  contrato.py            modelo e validação do contrato
  expressao.py           validação das expressões de regra
  hashes.py              hash_leitura, hash_contrato, fingerprint
  plano.py               contrato -> planos Bronze e Silver
  decisoes.py            reconciliação, procedência, competência, schema
  ciclo_vida.py          estado declarado x evidência registrada
  aquisicao.py           download/depósito, SHA-256, extração sem sobrescrita
  inspecao.py            inspeção física sob demanda
  catalogo.py            linhas estruturais do catálogo
  orquestracao.py        pontos de entrada chamados pelos notebooks
  spark/                 executores finos (Bronze, Silver, quarentena, controle)
contratos/<fonte>/<base> descritor da base e contratos de entidade
configuracao/            ambientes (schemas e raiz; nenhum GUID)
ferramentas/             carga do YAML e gerador de notebooks
notebooks/               notebooks gerados (não editar)
testes/                  suíte local sem Spark
docs/                    decisões, formato do contrato e operação
```

## Uso local

Requer Python 3.11 e PyYAML (`pip install -r requirements-dev.txt`).

```bash
python -m unittest discover -s testes -t .       # suíte local, sem Spark
python ferramentas/gerar_notebooks.py            # gera notebooks/
python ferramentas/gerar_notebooks.py --verificar  # falha se divergir
python ferramentas/gerar_notebooks.py --hashes     # versão, estado e hashes
```

O CI (`.github/workflows/testes.yml`) roda a suíte e a verificação dos
notebooks em clone limpo a cada push.

## Camadas

| Camada | Onde | Faz |
|---|---|---|
| Raw | `Files/raw/<fonte>/<base>/<competencia>/<aquisição>/` | Preserva os arquivos com SHA-256; nunca sobrescreve |
| Bronze | `bronze.<fonte>_<base>_<entidade>` | Tudo como texto e linhagem mínima; separa só linhas malformadas |
| Silver | `silver.<fonte>_<base>_<entidade>` | Tipos, transformações, domínios, chave e regras declarados |
| Quarentena | `controle.quarentena` | Registro retirado com todos os motivos; nunca altera a Bronze |
| Controle | `controle.execucoes` | Toda tentativa, inclusive falhas e bloqueios |
| Catálogo | `controle.catalogo_*` | Estrutura derivada do contrato e curadoria preservada |

Bronze e Silver guardam o snapshot da última competência publicada. O
histórico fica na Raw.

## Regras verificadas automaticamente

| Regra | Verificação |
|---|---|
| Nenhuma ação implícita no motor | Contrato sem as seis ações padrão é inválido; matriz de ações por classe |
| Contrato não declara nome físico | Teste sobre `contratos/` |
| Nenhum sufixo de ambiente | Teste sobre identificadores e schemas |
| Nenhum GUID versionado | Teste sobre todos os arquivos do repositório |
| Todo notebook é saída do gerador | Reprodução byte a byte, inclusive em clone limpo; assinatura conferida no Fabric |
| Procedência entre camadas | Mesmo `hash_leitura` e mesma execução Bronze registrada |
| Reconciliação em toda escrita | Origem independente do parser; restauração em divergência |
| Quarentena preserva | Sem exclusão ou sobrescrita no módulo de quarentena |
| A tentativa que falha é registrada | Toda operação pública roda dentro do registro de execução |
| Expressão validada antes de executar | Vocabulário fechado na carga do contrato |

## Documentação

- `docs/decisoes.md`: avaliação do briefing, contradições e decisões
  datadas.
- `docs/contratos.md`: formato do contrato e inclusão de nova fonte.
- `docs/operacao.md`: implantação no Fabric, fluxo, aceite físico e
  bloqueios.
