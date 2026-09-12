-- Núcleo do Maranhão Intelligence (Fase 1): eventos aditivos e idempotentes.
-- lote/unidade/estabelecimento permanecem texto solto nesta fase, sem tabelas
-- normalizadas ainda (mi_lotes/mi_unidades/mi_estabelecimentos ficam para depois).
-- Não altera nenhuma tabela ou migration anterior.
CREATE TABLE IF NOT EXISTS mi_skus (
    id UUID PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    produto_nome TEXT NOT NULL,
    categoria TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mi_eventos (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    tipo_evento TEXT NOT NULL CHECK (tipo_evento IN ('ativacao','scan','venda','feedback','presenca')),
    canal TEXT NOT NULL,
    lote TEXT,
    unidade TEXT,
    estabelecimento TEXT,
    origem_tipo TEXT CHECK (origem_tipo IS NULL OR origem_tipo ~ '^[a-z][a-z0-9_]{0,63}$'),
    origem_id TEXT,
    ocorrido_em TIMESTAMPTZ,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_eventos_ocorrido_idx ON mi_eventos(ocorrido_em);
CREATE INDEX IF NOT EXISTS mi_eventos_canal_idx ON mi_eventos(canal);

CREATE TABLE IF NOT EXISTS mi_eventos_auditoria (
    id BIGSERIAL PRIMARY KEY,
    evento_id UUID NOT NULL REFERENCES mi_eventos(id),
    evento TEXT NOT NULL,
    ator TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
