-- Registro de tentativa antes de transporte; não habilita cobrança nem agenda jobs.
CREATE TABLE IF NOT EXISTS c6_checkout_tentativas (
    chave_hash TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    codigo TEXT NOT NULL UNIQUE,
    resposta JSONB,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS c6_pix_auditoria (
    id BIGSERIAL PRIMARY KEY,
    codigo TEXT NOT NULL,
    evento TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (codigo, evento)
);
