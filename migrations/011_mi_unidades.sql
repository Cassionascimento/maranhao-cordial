-- Terceira camada de rastreabilidade física: LOTE -> UNIDADE.
-- codigo_publico é o identificador público (etiqueta/QR/NFC futuros): opaco,
-- gerado por CSPRNG na aplicação, nunca derivado de sku/lote/timestamp aqui.
-- Sem PII. Aditiva: não altera nenhuma migration anterior.
CREATE TABLE IF NOT EXISTS mi_unidades (
    id UUID PRIMARY KEY,
    lote_id UUID NOT NULL REFERENCES mi_lotes(id),
    codigo_publico TEXT NOT NULL UNIQUE,
    estado TEXT NOT NULL DEFAULT 'emitida' CHECK (estado IN ('emitida','ativa','revogada')),
    revogada_em TIMESTAMPTZ,
    motivo_revogacao TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((estado = 'revogada') = (revogada_em IS NOT NULL)),
    CHECK (estado = 'revogada' OR motivo_revogacao IS NULL)
);
CREATE INDEX IF NOT EXISTS mi_unidades_lote_idx ON mi_unidades(lote_id);
