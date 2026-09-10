-- Somente fatos registrados e leituras; não altera estoque, pedidos ou jobs.
CREATE TABLE IF NOT EXISTS territorio_registros (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    tipo_registro TEXT NOT NULL CHECK (tipo_registro IN ('relacao','circulacao','midia','evento','resultado')),
    contato_id UUID REFERENCES leads_crm(id),
    estabelecimento TEXT,
    tipo_relacao TEXT,
    bairro TEXT,
    cidade TEXT,
    uf TEXT CHECK (uf IS NULL OR uf ~ '^[A-Z]{2}$'),
    lote TEXT,
    quantidade NUMERIC CHECK (quantidade IS NULL OR quantidade > 0),
    unidade TEXT CHECK (unidade IS NULL OR unidade IN ('garrafas','amostras','litros','unidades')),
    finalidade TEXT,
    ocorrido_em DATE,
    origem TEXT NOT NULL,
    responsavel TEXT NOT NULL,
    status TEXT,
    retorno TEXT,
    resultado TEXT,
    metricas JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metricas)='object'),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS territorio_registros_local_idx ON territorio_registros(uf,cidade,bairro);
CREATE INDEX IF NOT EXISTS territorio_registros_contato_idx ON territorio_registros(contato_id);
CREATE TABLE IF NOT EXISTS territorio_leituras (
    id UUID PRIMARY KEY,
    dados_hash TEXT NOT NULL UNIQUE,
    leitura JSONB NOT NULL,
    modelo TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
