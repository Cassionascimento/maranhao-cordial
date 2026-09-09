-- Aditiva; executar antes de ativar o novo receptor. Rollback de código preserva inbox.
CREATE TABLE IF NOT EXISTS whatsapp_eventos (
    chave TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    tipo_evento TEXT NOT NULL CHECK (tipo_evento IN ('mensagem','status')),
    dados JSONB NOT NULL,
    concluido BOOLEAN NOT NULL DEFAULT FALSE,
    recebido_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    concluido_em TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS whatsapp_eventos_message_id_idx ON whatsapp_eventos(message_id);
ALTER TABLE fila_respostas_omnichannel ADD COLUMN IF NOT EXISTS whatsapp_digest_aprovado TEXT;
ALTER TABLE fila_respostas_omnichannel ADD COLUMN IF NOT EXISTS whatsapp_message_id TEXT;
CREATE TABLE IF NOT EXISTS whatsapp_auditoria (
    id BIGSERIAL PRIMARY KEY,
    resposta_id UUID NOT NULL REFERENCES fila_respostas_omnichannel(id),
    evento TEXT NOT NULL,
    dados JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
