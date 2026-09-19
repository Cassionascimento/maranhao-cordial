-- Central Empresarial -- seção 11 da ordem (Visão Investidor). Um
-- compartilhamento é sempre uma ação humana explícita (nunca criado
-- automaticamente): gera um token opaco, nunca a ADMIN_API_KEY, para
-- uma visão somente leitura e sanitizada de UMA operação. Revogável a
-- qualquer momento; todo acesso via token atualiza ultimo_acesso_em,
-- dando trilha auditável de quando o link foi de fato usado. Aditiva:
-- não altera migrations 019-023.
CREATE TABLE IF NOT EXISTS mi_operacao_compartilhamentos (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revogado_em TIMESTAMPTZ,
    revogado_por TEXT,
    ultimo_acesso_em TIMESTAMPTZ,
    total_acessos INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS mi_operacao_compartilhamentos_operacao_idx ON mi_operacao_compartilhamentos(operacao_id);

-- Esta migration é somente um arquivo versionado, mesma convenção das
-- anteriores: não foi executada contra nenhum banco (nem produção, nem
-- homologação) nesta etapa.
