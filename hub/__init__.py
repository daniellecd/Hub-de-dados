"""Motor genérico de ingestão dirigido por contrato do Hub de Dados.

O pacote tem duas partes:

- módulos puros (sem Spark): contrato, plano, decisões, hashes, ciclo de
  vida, histórico, aquisição e inspeção. São cobertos pela suíte local;
- ``hub.spark``: executores finos que interpretam os planos no Spark e no
  Delta Lake. Só são exercitados por execução no Fabric.

Nenhum módulo deste pacote contém nome de fonte, base ou entidade.
"""

__version__ = "0.1.0"
