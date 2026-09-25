# Operação no Microsoft Fabric

Guia para implantar, operar e comprovar o aceite físico do Hub. A
evidência de execução é o registro em `controle.execucoes`, e não a saída
das células.

## 1. Pré-requisitos por ambiente

- Workspaces distintos para DEV, HML e PROD.
- Em cada workspace, um Lakehouse chamado `lh_hub` com schemas
  habilitados. O mesmo nome vale nos três; está em
  `configuracao/ambientes.yaml`.
- Runtime Spark com Spark 3.4 ou superior (Fabric Runtime 1.2 ou 1.3).
- Para o modo `download`: saída de internet habilitada para os notebooks.
  Se o tenant bloquear, use o modo `deposito` (seção 4.1).

Os schemas `bronze`, `silver` e `controle` e a tabela `controle.execucoes`
são criados pelo motor na primeira execução. A tabela `controle.quarentena`
só é criada quando houver registros.

## 2. Implantação

1. Obtenha os notebooks gerados em `notebooks/`. São versionados e
   reproduzíveis com `python ferramentas/gerar_notebooks.py`.
2. No workspace: **Import > Notebook > From this computer**, selecionando
   os nove arquivos `.ipynb`.
3. Não é preciso anexar lakehouse: a primeira célula de cada notebook
   (`%%configure`) define `lh_hub` pelo nome.
4. Não edite os notebooks no Fabric.
   - `nb_hub_biblioteca` confere a própria assinatura e recusa conteúdo
     alterado.
   - Para mudar algo, altere o repositório, gere de novo e reimporte.

| Notebook | Função |
|---|---|
| `nb_hub_biblioteca` | Motor e contratos embutidos; usado por `%run` |
| `nb_hub_adquirir` | Traz a publicação para a Raw |
| `nb_hub_inspecionar` | Inspeção física sob demanda (evidência de `VALIDADO_FISICO`) |
| `nb_hub_bronze` | Publica a Bronze de uma entidade |
| `nb_hub_silver` | Publica a Silver de uma entidade |
| `nb_hub_executar_base` | Aquisição, Bronze e Silver de todas as entidades da base |
| `nb_hub_diagnosticar` | Integridade referencial sob demanda |
| `nb_hub_catalogo` | Sincroniza o catálogo e os comentários físicos |
| `nb_hub_aprovar` | Registra a aprovação nominal do contrato |

Todos recebem parâmetros pela célula marcada como `parameters`, que pode
ser sobrescrita por pipeline.

## 3. Fluxo de uma fonte nova (exemplo: CNO)

1. **Adquirir:** `nb_hub_adquirir` com `fonte=rfb`, `base=cno` e
   `competencia=2026-09`.
2. **Inspecionar** cada entidade: `nb_hub_inspecionar` com
   `entidade=rfb_cno_obras` (depois cnaes, vinculos, areas, totais).
   - O relatório mostra codificação, separador provável, cabeçalho
     encontrado, larguras e amostras.
   - Com `INCOMPATIVEL`, ajuste o contrato no repositório, incremente a
     `versao`, gere de novo, reimporte a biblioteca e inspecione outra vez.
3. **Promover o contrato:** com o veredito `COMPATIVEL`, resolva as
   pendências que impedem `VALIDADO_FISICO` e declare o estado
   `VALIDADO_FISICO` no contrato. O estado fica fora do hash, e a
   inspeção registrada continua valendo.
4. **Publicar:** `nb_hub_bronze` e depois `nb_hub_silver` para cada
   entidade (ou `nb_hub_executar_base`).
5. **Catálogo:** `nb_hub_catalogo`.
6. **Referências:** `nb_hub_diagnosticar`. No CNO, o esperado é
   `REFERENCIA_AUSENTE` até o CNPJ ser publicado.
7. **Aprovar:**
   - Obtenha o `hash_contrato` em `controle.catalogo_ativos` ou com
     `python ferramentas/gerar_notebooks.py --hashes`.
   - Execute `nb_hub_aprovar` com o nome do responsável.
   - Declare `APROVADO` no contrato.
   - Repita em HML e PROD: o lastro é de cada ambiente.

Contrato em `VALIDADO_FISICO` ou `APROVADO` sem o lastro correspondente
no ambiente é recusado na publicação.

## 4. Operação recorrente

Agende `nb_hub_executar_base` (pipeline ou agendamento do notebook) com a
competência do mês. Entidades são independentes: a falha de uma não
impede as demais, e o notebook termina com erro listando as falhas.

### 4.1 Depósito manual (contingência)

1. Crie a pasta `Files/raw/<fonte>/<base>/<competencia>/<pasta>` (ex.:
   `deposito-20260925`).
2. Copie para ela os arquivos declarados no descritor da base.
3. Execute `nb_hub_adquirir` com `modo=deposito` e `pasta_deposito`
   igual ao nome da pasta.

### 4.2 Reprocessamento e reversão

- Reexecutar a mesma competência sob o mesmo contrato é idempotente: o
  snapshot é substituído pelo mesmo conteúdo e a quarentena não duplica.
- Publicar uma competência anterior à vigente exige
  `permitir_competencia_anterior=True`. A permissão fica registrada nos
  detalhes da execução.
- Uma mudança só de regra da Silver (mesmo `hash_leitura`) não exige
  reprocessar a Bronze. Incremente a `versao` do contrato.

## 5. Roteiro de aceite físico

Execute no SQL do Lakehouse (ou `spark.sql`) após o fluxo da seção 3.

**Reconciliação em toda publicação:**

```sql
SELECT tipo, identificador, competencia, status,
       linhas_origem, linhas_publicadas, linhas_quarentena,
       linhas_origem = linhas_publicadas + linhas_quarentena AS reconciliada
FROM controle.execucoes
WHERE tipo IN ('BRONZE', 'SILVER')
ORDER BY iniciado_em DESC;
```

**Toda tentativa registrada, inclusive falhas e bloqueios:**

```sql
SELECT tipo, status, COUNT(*) AS execucoes
FROM controle.execucoes
GROUP BY tipo, status
ORDER BY tipo, status;
```

**Procedência:** a Silver aponta para a Bronze vigente.

```sql
SELECT s.identificador, s.id_execucao_origem, b.id_execucao, b.hash_leitura
FROM controle.execucoes s
JOIN controle.execucoes b ON b.id_execucao = s.id_execucao_origem
WHERE s.tipo = 'SILVER' AND s.status IN ('SUCESSO', 'SUCESSO_COM_ALERTA');
```

**Quarentena idempotente.** Reexecute Bronze e Silver da mesma
competência e confira que não há duplicidade:

```sql
SELECT id_quarentena, COUNT(*) FROM controle.quarentena
GROUP BY id_quarentena HAVING COUNT(*) > 1;   -- esperado: nenhuma linha
```

**Motivos da quarentena:**

```sql
SELECT identificador, camada, grupo_problema, COUNT(*) AS linhas
FROM controle.quarentena
GROUP BY identificador, camada, grupo_problema
ORDER BY linhas DESC;
```

**Comentários físicos derivados do contrato:**

```sql
DESCRIBE TABLE EXTENDED silver.rfb_cno_obras;
```

**Reconciliação com o total declarado pela fonte** (CNO): confira
`detalhes.total_declarado` e `detalhes.partes` na execução Bronze.

```sql
SELECT identificador, get_json_object(detalhes, '$.total_declarado') AS total,
       linhas_origem
FROM controle.execucoes
WHERE tipo = 'BRONZE' AND identificador LIKE 'rfb_cno_%';
```

## 6. Interpretação de bloqueios

| Motivo registrado | Causa | Ação |
|---|---|---|
| `estado ... sem inspeção COMPATIVEL neste ambiente` | Estado declarado sem lastro no ambiente | Inspecionar no ambiente ou voltar o estado |
| `versão N já foi publicada com outro hash_contrato` | Parte executável mudou sem nova versão | Incrementar `versao` |
| `competência ... é anterior à vigente` | Tentativa de regredir o snapshot | Conferir a competência ou usar `permitir_competencia_anterior` |
| `não há aquisição efetiva da base` | Competência não adquirida | Executar a aquisição |
| `N partes encontradas; contrato espera M` | Publicação mudou de estrutura | Inspecionar e atualizar o contrato |
| `coluna ... na posição ...`, `coluna não declarada` | Cabeçalho divergente | Inspecionar; alias ou nova versão |
| `... linhas malformadas excedem a tolerância` | Largura divergente em massa (layout mudou) | Inspecionar; nova versão do contrato |
| `parte ...: N linhas físicas e M registros lidos` | Parser não representou todas as linhas | Revisar aspas e escape |
| `total declarado pela fonte ... difere` | Arquivo incompleto ou total com outra semântica | Inspecionar a publicação |
| `Bronze vigente foi publicada com outro hash_leitura` | Leitura mudou desde a última Bronze | Reprocessar a Bronze |
| `schema diverge ... sem nova versão de contrato` | Tabela física difere do contrato | Nova versão ou investigação da alteração externa |
| `reconciliação falhou` | Divergência após a escrita; snapshot restaurado | Investigar antes de reexecutar |

## 7. Manutenção

- `controle.execucoes` e `controle.quarentena` recebem escritas pequenas
  e frequentes. Execute `OPTIMIZE` periodicamente.
- `VACUUM` não interfere no motor: a restauração usa apenas a versão
  imediatamente anterior, dentro da mesma execução.
- A Raw nunca é apagada pelo motor. A retenção de aquisições antigas é
  decisão operacional e deve entrar no registro de decisões.
