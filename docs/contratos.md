# Formato do contrato

Referência do módulo declarativo versionado em `contratos/`. O motor
recusa qualquer chave, tipo, transformação ou ação fora deste vocabulário.
Todos os problemas de um contrato são reportados de uma vez.

## Organização dos arquivos

```text
configuracao/ambientes.yaml                ambientes e lakehouse
contratos/<fonte>/<base>/base.yaml         aquisição da base
contratos/<fonte>/<base>/<entidade>.yaml   contrato da entidade
```

O nome físico nunca é declarado. Ele é derivado da identidade:
`<schema da camada>.<fonte>_<base>_<entidade>[_<especificacao>]`, por
exemplo `silver.rfb_cno_obras`. O schema vem da configuração de ambiente.

## Seções do contrato de entidade

| Chave | Obrigatória | Hash | Conteúdo |
|---|---|---|---|
| `formato_contrato` | sim | leitura | Versão do formato (hoje `1`) |
| `identidade` | sim | leitura | `fonte`, `base`, `entidade` e `especificacao` opcional |
| `versao` | sim | fora | Versão do contrato; incrementa quando a parte executável muda |
| `descricao` | não | fora | Descrição da entidade (vira comentário físico) |
| `selecao` | sim | leitura | `arquivo` (padrão do nome, sem diferenciar maiúsculas) e `quantidade_partes` opcional |
| `leitura` | sim | leitura | `separador`, `aspas`, `escape`, `codificacao`, `cabecalho`, `tolerancia_malformadas` |
| `reconciliacao` | não | leitura | `total_declarado: {entidade, coluna}`: total publicado pela fonte |
| `transformacoes_padrao` | não | contrato | Transformações aplicadas a todas as colunas, antes das específicas |
| `colunas` | sim | leitura e contrato | Lista na ordem física do arquivo |
| `chave` | não | contrato | Lista de colunas; verifica chave nula e duplicada |
| `dominios` | não | contrato | Domínios literais ou por referência |
| `regras` | não | contrato | Regras de negócio com expressão validada |
| `acoes_padrao` | sim | leitura e contrato | Ação de cada classe de violação |
| `documentacao` | sim | fora | `estado`, `fonte_documental`, `pendencias`, `observacoes` |

A coluna "Hash" indica onde a chave pesa:

- `leitura`: `hash_leitura` e `hash_contrato`;
- `contrato`: somente `hash_contrato`;
- `fora`: nenhum dos dois.

Descrições, estado, pendências e versão ficam fora dos hashes.

### Dialeto (`leitura`)

| Campo | Valores |
|---|---|
| `separador`, `aspas`, `escape` | Um caractere cada. `escape` igual a `aspas` significa aspas duplicadas (RFC 4180) |
| `codificacao` | `utf-8`, `iso-8859-1`, `windows-1252` |
| `cabecalho` | `true` ou `false` (obrigatório) |
| `tolerancia_malformadas` | Fração em [0, 1). Acima dela, linhas com largura divergente são divergência estrutural e bloqueiam |

### Colunas

| Campo | Uso |
|---|---|
| `nome` | Nome em snake_case, igual na Bronze e na Silver. Não pode começar com `_` nem ser `competencia` |
| `tipo` | `texto`, `inteiro`, `inteiro_longo`, `decimal`, `data` |
| `cabecalho`, `aliases` | Nome no cabeçalho e nomes históricos aceitos. Obrigatório quando `leitura.cabecalho` é `true`; proibido quando é `false` |
| `ausente_na_origem` | `true` para coluna mantida por histórico e que não existe mais no arquivo (sai nula) |
| `nulavel` | Padrão `true`. Com `false`, nulo viola `nulidade` (colunas da chave usam `chave_nula`) |
| `formato` | Tipo `data`: combinação de `AAAA`, `MM` e `DD` com `-`, `/` ou `.` (ex.: `AAAAMMDD`, `AAAA-MM-DD`) |
| `precisao`, `escala`, `separador_decimal` | Tipo `decimal`: os três são obrigatórios; separador `.` ou `,` |
| `transformacoes` | Lista aplicada depois de `transformacoes_padrao` |
| `dominio` | Nome de um domínio declarado (só para coluna `texto`) |
| `descricao` | Comentário físico da coluna |

### Transformações

Todas preservam nulo.

| Nome | Parâmetros | Efeito |
|---|---|---|
| `aparar` | — | Remove espaços nas extremidades |
| `maiusculas` | — | Converte para maiúsculas |
| `somente_digitos` | — | Remove todo caractere não numérico |
| `vazio_como_nulo` | — | Texto vazio passa a nulo |
| `nulo_se` | `valores: [lista]` | Valores sentinela passam a nulo (ex.: `"00000000"`) |
| `preencher_esquerda` | `tamanho`, `caractere` | Completa à esquerda; nunca trunca valor maior |

Exemplo:

```yaml
transformacoes:
  - somente_digitos
  - nulo_se: {valores: ["0", "00000000"]}
  - preencher_esquerda: {tamanho: 2, caractere: "0"}
```

### Domínios

- **Literal:** mapa código → descrição, com no máximo 15 valores. Os
  códigos são sempre texto entre aspas: sem aspas, o YAML transforma
  `"01"` em número e o contrato é recusado. `coluna_descricao` opcional
  gera a descrição na Silver, logo após a coluna de origem.
- **Referência:** `tabela: {fonte, base, entidade}` e `coluna`. É apenas
  declarada: vira dependência no catálogo e é conferida pelo diagnóstico
  sob demanda. Nunca bloqueia a entidade.

Domínio historicamente mutável deve preferir referência, mesmo com poucos
valores.

### Regras

```yaml
regras:
  - id: fim_nao_anterior_ao_inicio
    dimensao: Accuracy
    expressao: data_fim IS NULL OR data_inicio IS NULL OR data_fim >= data_inicio
    colunas_referenciadas: [data_fim, data_inicio]
    acao: ALERTA
```

A expressão é validada antes de executar:

- **Pode referenciar:** exatamente as colunas de `colunas_referenciadas`,
  já tipadas.
- **Palavras aceitas:** `AND OR NOT IS NULL IN BETWEEN LIKE TRUE FALSE
  CASE WHEN THEN ELSE END DATE`.
- **Funções aceitas:** `abs coalesce day length lower month regexp_like
  round substring trim upper year`.
- **Recusados:** comentário, `;`, `.`, aspas duplas, crase, subconsulta e
  funções não determinísticas.

Só TRUE aprova a linha. FALSE e NULL violam, então trate nulo
explicitamente na expressão.

### Ações

| Ação | Efeito |
|---|---|
| `QUARENTENA` | A linha sai; as demais publicam |
| `QUARENTENA_E_ALERTA` | A linha sai e a execução termina `SUCESSO_COM_ALERTA` |
| `QUARENTENA_GRUPO` | Todo o grupo da chave duplicada sai, sem eleger vencedor |
| `ALERTA` | A linha publica e a execução termina `SUCESSO_COM_ALERTA` |
| `BLOQUEIA_PUBLICACAO` | Nenhuma linha é publicada; a execução termina `BLOQUEADA` |

As seis classes de `acoes_padrao` são obrigatórias. Não existe ação
implícita. Cada classe aceita apenas as ações abaixo:

| Classe | Ações permitidas |
|---|---|
| `linha_malformada` (Bronze) | QUARENTENA, QUARENTENA_E_ALERTA, BLOQUEIA_PUBLICACAO |
| `nulidade`, `conversao`, `dominio` | QUARENTENA, QUARENTENA_E_ALERTA, ALERTA, BLOQUEIA_PUBLICACAO |
| `chave_nula` | QUARENTENA, QUARENTENA_E_ALERTA, BLOQUEIA_PUBLICACAO |
| `chave_duplicada` | QUARENTENA_GRUPO, BLOQUEIA_PUBLICACAO |
| regra (`regras[].acao`) | QUARENTENA, QUARENTENA_E_ALERTA, ALERTA, BLOQUEIA_PUBLICACAO |

### Documentação e ciclo de vida

| Estado | Lastro exigido no ambiente |
|---|---|
| `PROVISORIO_DOCUMENTAL` | Nenhum |
| `VALIDADO_FISICO` | Inspeção COMPATIVEL com o mesmo `hash_leitura` |
| `APROVADO` | Também uma aprovação nominal com o mesmo `hash_contrato` |
| `OBSOLETO` | Não publica |

Cada pendência declara o estado que impede (`VALIDADO_FISICO` ou
`APROVADO`). O contrato não pode declarar um estado que uma pendência
impede. Toda pendência aberta impede a aprovação.

## Descritor de base

```yaml
formato_base: 1
identidade: {fonte: rfb, base: cnpj}
aquisicao:
  url_base: https://.../dados_abertos_cnpj/{competencia}/
  arquivos: [Empresas0.zip, ...]
documentacao:
  fonte_documental: ...
  pendencias: [texto, ...]
```

`{competencia}` é substituído na aquisição. ZIPs são extraídos em
`<pasta da aquisição>/<zip sem extensão>/`. Cada contrato seleciona seus
arquivos por `selecao.arquivo`.

## Como incluir uma nova fonte sem alterar o motor

1. Criar `contratos/<fonte>/<base>/base.yaml` e um contrato por entidade,
   com estado `PROVISORIO_DOCUMENTAL` e as pendências conhecidas.
2. Rodar `python ferramentas/gerar_notebooks.py`. Contrato inválido
   interrompe a geração com a lista de problemas.
3. Rodar a suíte (`python -m unittest discover -s testes -t .`) e
   versionar contratos e notebooks juntos.
4. No Fabric: reimportar `nb_hub_biblioteca`, adquirir, inspecionar,
   ajustar o contrato e seguir o fluxo de `docs/operacao.md`.

Se a nova fonte exigir tipo, transformação ou ação inexistente, a mudança
é no motor (genérica) e entra no registro de decisões com a necessidade
que a justifica.
