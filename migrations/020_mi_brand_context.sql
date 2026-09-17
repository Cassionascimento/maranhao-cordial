-- Brand Visual Context (P5.X, Milestone 7) -- estrutura versionada de
-- identidade visual que Pirret usa em vez de confiar só em prompt
-- genérico. Nunca sobrescrita: cada mudança é uma NOVA versão (mesmo
-- princípio de nunca apagar histórico usado em toda a plataforma).
-- Visual Memory NÃO tem tabela própria: reaproveita mi_artefatos (019)
-- filtrando por status='aprovado'/'rejeitado' -- ver mi_brand_context.py.
CREATE TABLE IF NOT EXISTS mi_brand_context (
    id UUID PRIMARY KEY,
    versao INTEGER NOT NULL,
    campos JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(campos) = 'object'),
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (versao)
);
CREATE INDEX IF NOT EXISTS mi_brand_context_versao_idx ON mi_brand_context(versao DESC);

-- Esta migration é somente um arquivo versionado, na mesma convenção de
-- 014_mi_fila_operacional.sql/019_mi_artefatos.sql: não foi executada
-- contra nenhum banco (nem produção, nem homologação) nesta etapa.
