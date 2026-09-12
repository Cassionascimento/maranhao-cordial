-- Liga mi_eventos a mi_skus por código (sku), quando informado.
-- Aditiva: não altera a migration 007 nem nenhuma tabela existente
-- além de adicionar uma coluna nova em mi_eventos.
ALTER TABLE mi_eventos ADD COLUMN IF NOT EXISTS sku TEXT REFERENCES mi_skus(sku);
CREATE INDEX IF NOT EXISTS mi_eventos_sku_idx ON mi_eventos(sku);
