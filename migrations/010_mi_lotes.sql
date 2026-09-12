-- Primeira camada de rastreabilidade física: SKU -> LOTE.
-- codigo_lote é único por sku (não globalmente): dois produtos podem
-- reaproveitar o mesmo código de lote em convenções de origem diferentes.
-- Aditiva: não altera nenhuma migration anterior nem mi_eventos.
CREATE TABLE IF NOT EXISTS mi_lotes (
    id UUID PRIMARY KEY,
    sku TEXT NOT NULL REFERENCES mi_skus(sku),
    codigo_lote TEXT NOT NULL,
    fabricado_em DATE,
    validade DATE,
    quantidade_produzida NUMERIC CHECK (quantidade_produzida IS NULL OR quantidade_produzida > 0),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sku, codigo_lote)
);
CREATE INDEX IF NOT EXISTS mi_lotes_sku_idx ON mi_lotes(sku);
