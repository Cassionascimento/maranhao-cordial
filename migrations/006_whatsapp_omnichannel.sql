-- Aditiva e idempotente. Requer migration 002. Não executa transportes ou jobs.
CREATE TABLE IF NOT EXISTS whatsapp_processamentos (
    chave TEXT PRIMARY KEY REFERENCES whatsapp_eventos(chave),
    interacao_id UUID REFERENCES interacoes_omnichannel(id),
    resposta_id UUID REFERENCES fila_respostas_omnichannel(id),
    estado TEXT NOT NULL DEFAULT 'recebido',
    tentativas INTEGER NOT NULL DEFAULT 0,
    interpretacao JSONB,
    erro_tipo TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS whatsapp_processamentos_estado_idx ON whatsapp_processamentos(estado,atualizado_em);
CREATE TABLE IF NOT EXISTS whatsapp_entrada_auditoria (
    id BIGSERIAL PRIMARY KEY,
    chave TEXT NOT NULL REFERENCES whatsapp_eventos(chave),
    etapa TEXT NOT NULL,
    dados JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS whatsapp_entrada_auditoria_chave_idx ON whatsapp_entrada_auditoria(chave,id);
