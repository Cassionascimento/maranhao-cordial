-- Fila operacional de decisões do Maranhão Intelligence (ETAPA 5.0).
-- Distinta de mi_sinais (007-013, log de fatos/recomendações imutável):
-- esta tabela é o único lugar com estado mutável (uma decisão pode avançar
-- de planejada -> concluída/bloqueada/precisa_diretor ao longo do tempo).
-- Alimentará o calendário da ETAPA 5.1. Aditiva: não altera mi_sinais,
-- mi_eventos ou qualquer tabela anterior.
CREATE TABLE IF NOT EXISTS mi_fila_operacional (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    origem TEXT NOT NULL CHECK (origem ~ '^[a-z][a-z0-9_]{0,63}$'),
    origem_id TEXT,
    tipo_decisao TEXT NOT NULL CHECK (tipo_decisao ~ '^[a-z][a-z0-9_]{0,63}$'),
    fatos JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(fatos) = 'array'),
    inferencia TEXT,
    prioridade TEXT NOT NULL CHECK (prioridade IN ('baixa','normal','alta','urgente')),
    confianca NUMERIC CHECK (confianca IS NULL OR (confianca >= 0 AND confianca <= 1)),
    proxima_acao TEXT NOT NULL,
    exige_aprovacao BOOLEAN NOT NULL,
    estado TEXT NOT NULL DEFAULT 'planejada'
        CHECK (estado IN ('planejada','aguardando','concluida','bloqueada','precisa_diretor')),
    resultado JSONB,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    concluido_em TIMESTAMPTZ,
    CHECK ((estado IN ('concluida','bloqueada')) = (concluido_em IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS mi_fila_estado_idx ON mi_fila_operacional(estado);
CREATE INDEX IF NOT EXISTS mi_fila_prioridade_idx ON mi_fila_operacional(prioridade);
CREATE INDEX IF NOT EXISTS mi_fila_origem_idx ON mi_fila_operacional(origem, tipo_decisao);
CREATE INDEX IF NOT EXISTS mi_fila_criado_idx ON mi_fila_operacional(criado_em);

CREATE TABLE IF NOT EXISTS mi_fila_operacional_auditoria (
    id BIGSERIAL PRIMARY KEY,
    item_id UUID NOT NULL REFERENCES mi_fila_operacional(id),
    estado_anterior TEXT,
    estado_novo TEXT NOT NULL,
    ator TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Esta migration é somente um arquivo versionado: não foi executada contra
-- nenhum banco (nem produção, nem homologação) nesta etapa. A ETAPA 5.0
-- também não executou a migration 013 (mi_sinais), que continua pendente.
