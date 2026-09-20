-- Identidade do mesmo contato em cada canal externo.
-- Aditiva e idempotente. Não migra dado existente, não apaga nada.
--
-- Problema que resolve: hoje o WhatsApp acha o contato pelo telefone e o
-- Gmail pelo e-mail. Um mesmo bar que escreveu pelos dois vira dois
-- contatos, e nada liga o wa_id ao endereço de e-mail. Esta tabela guarda
-- o identificador EXTERNO por canal, que é o único dado estável que cada
-- plataforma fornece.
--
-- A chave única é (canal, identificador_externo): o mesmo número pode
-- existir no WhatsApp e no Instagram sem colidir, e o mesmo identificador
-- nunca aponta para dois contatos no mesmo canal.
CREATE TABLE IF NOT EXISTS crm_identidades_canal (
    id UUID PRIMARY KEY,
    lead_id UUID NOT NULL REFERENCES leads_crm(id) ON DELETE CASCADE,
    canal TEXT NOT NULL,
    identificador_externo TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('telefone','email','usuario','id_plataforma')),
    verificado BOOLEAN NOT NULL DEFAULT FALSE,
    primeira_vez_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultima_vez_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS crm_identidades_canal_unica
    ON crm_identidades_canal(canal, identificador_externo);

CREATE INDEX IF NOT EXISTS crm_identidades_canal_lead_idx
    ON crm_identidades_canal(lead_id);

-- Fusão de contatos duplicados: registro auditável, nunca DELETE silencioso.
-- O contato absorvido permanece na base marcado como fundido, para que
-- qualquer referência antiga continue resolvendo.
ALTER TABLE leads_crm ADD COLUMN IF NOT EXISTS fundido_em_lead_id UUID;
ALTER TABLE leads_crm ADD COLUMN IF NOT EXISTS fundido_em TIMESTAMPTZ;
ALTER TABLE leads_crm ADD COLUMN IF NOT EXISTS fundido_por VARCHAR(220);

CREATE INDEX IF NOT EXISTS leads_crm_fundido_idx
    ON leads_crm(fundido_em_lead_id) WHERE fundido_em_lead_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS crm_fusao_auditoria (
    id BIGSERIAL PRIMARY KEY,
    lead_destino UUID NOT NULL,
    lead_absorvido UUID NOT NULL,
    motivo TEXT NOT NULL,
    ator VARCHAR(220),
    identidades_movidas INTEGER NOT NULL DEFAULT 0,
    interacoes_movidas INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
