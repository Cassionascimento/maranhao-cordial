-- Liga mi_eventos a mi_unidades por id (unidade_id), quando informado.
-- SKU/lote continuam alcançados por junção (unidade_id -> mi_unidades.lote_id
-- -> mi_lotes.sku), nunca duplicados em mi_eventos.
-- Aditiva: não altera nenhuma migration anterior.
ALTER TABLE mi_eventos ADD COLUMN IF NOT EXISTS unidade_id UUID REFERENCES mi_unidades(id);
CREATE INDEX IF NOT EXISTS mi_eventos_unidade_idx ON mi_eventos(unidade_id);
