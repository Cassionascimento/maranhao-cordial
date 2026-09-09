-- Aditiva: apenas o cursor da varredura da única conta Gmail configurada.
-- Rollback de código preserva este estado; não altera OAuth nem mensagens.
CREATE TABLE IF NOT EXISTS gmail_sync_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    page_token TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO gmail_sync_cursor (id) VALUES (1) ON CONFLICT DO NOTHING;
