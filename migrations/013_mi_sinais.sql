-- Barramento comum de sinais do Maranhão Intelligence (ETAPA 4.9).
-- Domínio distinto de mi_eventos (007-012, rastreabilidade física SKU/lote/
-- unidade via QR/NFC): mi_sinais observa processos de negócio internos
-- (CRM, prospecção, ações comerciais, pedidos, e futuramente
-- Gmail/Instagram/WhatsApp/TikTok), sem duplicar os dados de origem --
-- apenas referência (origem+origem_id) suficiente para, quando necessário,
-- consultar o registro original. Aditiva: não altera nenhuma tabela ou
-- migration anterior, inclusive mi_eventos e mi_eventos_auditoria.
--
-- tipo_evento é validado só por formato (não por enum fechado como em
-- mi_eventos), porque esta camada é deliberadamente extensível a novos
-- produtores sem migration nova a cada domínio conectado.
CREATE TABLE IF NOT EXISTS mi_sinais (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    natureza TEXT NOT NULL CHECK (natureza IN ('fato','inferencia','recomendacao','acao','resultado')),
    origem TEXT NOT NULL CHECK (origem ~ '^[a-z][a-z0-9_]{0,63}$'),
    origem_id TEXT,
    tipo_evento TEXT NOT NULL CHECK (tipo_evento ~ '^[a-z][a-z0-9_]{0,63}$'),
    canal TEXT,
    sku TEXT REFERENCES mi_skus(sku),
    estabelecimento_id UUID REFERENCES mi_estabelecimentos(id),
    unidade_id UUID REFERENCES mi_unidades(id),
    lote_id UUID REFERENCES mi_lotes(id),
    territorio_uf TEXT CHECK (territorio_uf IS NULL OR territorio_uf ~ '^[A-Z]{2}$'),
    territorio_cidade TEXT,
    confianca NUMERIC CHECK (confianca IS NULL OR (confianca >= 0 AND confianca <= 1)),
    resultado TEXT,
    ocorrido_em TIMESTAMPTZ,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_sinais_natureza_idx ON mi_sinais(natureza);
CREATE INDEX IF NOT EXISTS mi_sinais_origem_idx ON mi_sinais(origem, tipo_evento);
CREATE INDEX IF NOT EXISTS mi_sinais_ocorrido_idx ON mi_sinais(ocorrido_em);
CREATE INDEX IF NOT EXISTS mi_sinais_criado_idx ON mi_sinais(criado_em);
CREATE INDEX IF NOT EXISTS mi_sinais_sku_idx ON mi_sinais(sku);
CREATE INDEX IF NOT EXISTS mi_sinais_estabelecimento_idx ON mi_sinais(estabelecimento_id);
CREATE INDEX IF NOT EXISTS mi_sinais_territorio_idx ON mi_sinais(territorio_uf, territorio_cidade);

CREATE TABLE IF NOT EXISTS mi_sinais_auditoria (
    id BIGSERIAL PRIMARY KEY,
    sinal_id UUID NOT NULL REFERENCES mi_sinais(id),
    evento TEXT NOT NULL,
    ator TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Esta migration é somente um arquivo versionado: não foi executada contra
-- nenhum banco (nem produção, nem homologação) nesta etapa.
