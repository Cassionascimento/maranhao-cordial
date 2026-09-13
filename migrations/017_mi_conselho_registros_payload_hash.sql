-- Corrige divergência entre migration 016 e mi_conselho.py: registrar_registro
-- e nova_versao_registro sempre gravam/leem payload_hash em
-- mi_conselho_registros (mesma disciplina chave+payload_hash usada em
-- mi_sinais, mi_fila_operacional, mi_eventos e territorio_registros), mas a
-- migration 016 nunca criou essa coluna. Aditiva e idempotente: não altera
-- nenhuma outra tabela/coluna.

ALTER TABLE mi_conselho_registros ADD COLUMN IF NOT EXISTS payload_hash TEXT;

-- Backfill defensivo: nenhuma linha real deveria existir com payload_hash
-- nulo (o INSERT já falhava sem a coluna, então nada teria sido
-- commitado) -- mas se alguma linha aparecer aqui, marca com um hash
-- inválido em vez de deixar NULL, para nunca mascarar dado incompleto
-- como se fosse igual a um digest real.
UPDATE mi_conselho_registros SET payload_hash = 'migracao_017_sem_hash_original'
WHERE payload_hash IS NULL;

ALTER TABLE mi_conselho_registros ALTER COLUMN payload_hash SET NOT NULL;
