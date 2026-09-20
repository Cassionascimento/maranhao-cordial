-- Ciclo de vida da mensagem enviada: sent -> delivered -> read, ou failed.
-- Aditiva e idempotente. Requer migrations 002 e 006. Não cria job nem envia.
--
-- Por que uma tabela própria: os eventos de status da Meta chegam fora de
-- ordem e podem ser reentregues. Guardar o estado atual por message_id
-- permite aplicar a regra de monotonicidade em um lugar só, sem depender
-- da ordem de chegada do webhook.
--
-- `codigo_erro` guarda apenas o CÓDIGO numérico da Meta. A mensagem de erro
-- pode conter dado do destinatário e por isso não é persistida.
CREATE TABLE IF NOT EXISTS whatsapp_status_mensagem (
    message_id TEXT PRIMARY KEY,
    resposta_id UUID REFERENCES fila_respostas_omnichannel(id),
    estado TEXT NOT NULL CHECK (estado IN ('sent','delivered','read','failed')),
    codigo_erro INTEGER,
    ocorrido_em TIMESTAMPTZ,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS whatsapp_status_mensagem_resposta_idx
    ON whatsapp_status_mensagem(resposta_id);

CREATE INDEX IF NOT EXISTS whatsapp_status_mensagem_falhas_idx
    ON whatsapp_status_mensagem(atualizado_em DESC)
    WHERE estado = 'failed';
