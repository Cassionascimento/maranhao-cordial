-- Estabelecimento mínimo para território: nome + cidade/UF/bairro, sem
-- geocodificação. lead_id é ponte opcional explícita para leads_crm; nenhuma
-- heurística automática de vínculo (a FK garante integridade, não inferência).
-- Aditiva: não altera as migrations 007 nem 008 além de uma coluna nova em
-- mi_eventos.
CREATE TABLE IF NOT EXISTS mi_estabelecimentos (
    id UUID PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo TEXT,
    cidade TEXT NOT NULL,
    uf TEXT NOT NULL CHECK (uf ~ '^[A-Z]{2}$'),
    bairro TEXT,
    lead_id UUID REFERENCES leads_crm(id),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_estabelecimentos_local_idx ON mi_estabelecimentos(uf,cidade,bairro);
CREATE INDEX IF NOT EXISTS mi_estabelecimentos_lead_idx ON mi_estabelecimentos(lead_id);

ALTER TABLE mi_eventos ADD COLUMN IF NOT EXISTS estabelecimento_id UUID REFERENCES mi_estabelecimentos(id);
CREATE INDEX IF NOT EXISTS mi_eventos_estabelecimento_idx ON mi_eventos(estabelecimento_id);
