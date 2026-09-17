-- Fonte regulatória canônica por SKU (P5.X, Milestone 8 -- Label
-- Studio). Camada REGULATORY, separada da camada CREATIVE (Pirret):
-- ingredientes/tabela nutricional/alegações/registro/volume/advertências
-- vêm SEMPRE daqui, nunca de um brief gerado por IA. Mesmo padrão de
-- versionamento de mi_brand_context (020): nunca sobrescrita, cada
-- mudança é uma nova versão.
CREATE TABLE IF NOT EXISTS mi_regulatorio_produto (
    id UUID PRIMARY KEY,
    sku TEXT NOT NULL,
    versao INTEGER NOT NULL,
    campos JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(campos) = 'object'),
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sku, versao)
);
CREATE INDEX IF NOT EXISTS mi_regulatorio_produto_sku_versao_idx ON mi_regulatorio_produto(sku, versao DESC);

-- Esta migration é somente um arquivo versionado, mesma convenção de
-- 019_mi_artefatos.sql/020_mi_brand_context.sql: não foi executada
-- contra nenhum banco (nem produção, nem homologação) nesta etapa.
