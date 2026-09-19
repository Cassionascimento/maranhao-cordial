-- Central Empresarial -- seção 1.D da ordem "Central Empresarial:
-- Operações Vivas" (ciclo de vida de Contatos/Profissionais/Fábricas).
-- profissionais_rede e fabricas_parceiras já têm arquivamento e workflow
-- de status (ver admin_arquivamento_profissional/admin_workflow_
-- profissional/admin_workflow_fabrica em main.py) -- não duplicados
-- aqui. contatos_estrategicos só tinha LISTAR/CRIAR: esta migration
-- aditiva fecha a lacuna real (nunca mudava de status, nunca tinha
-- histórico, nunca podia ser arquivado/excluído).
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS arquivado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS arquivado_em TIMESTAMPTZ;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS arquivado_por VARCHAR(220);
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS ultimo_contato_em TIMESTAMPTZ;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS ultima_resposta_em TIMESTAMPTZ;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS proxima_acao TEXT;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS data_followup DATE;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS observacoes TEXT;
ALTER TABLE contatos_estrategicos ADD COLUMN IF NOT EXISTS tentativas_contato INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS contatos_estrategicos_historico_status (
    id BIGSERIAL PRIMARY KEY,
    contato_id UUID NOT NULL REFERENCES contatos_estrategicos(id) ON DELETE CASCADE,
    status_anterior VARCHAR(50),
    status_novo VARCHAR(50) NOT NULL,
    motivo TEXT,
    ator VARCHAR(220) NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS contatos_estrategicos_historico_contato_idx
    ON contatos_estrategicos_historico_status(contato_id, criado_em DESC);

-- Esta migration é somente um arquivo versionado, mesma convenção das
-- anteriores: não foi executada contra nenhum banco (nem produção, nem
-- homologação) nesta etapa.
