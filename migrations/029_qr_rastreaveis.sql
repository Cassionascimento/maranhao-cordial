-- QR Codes rastreáveis: código -> origem -> avaliação -> contato opcional.
-- Aditiva e idempotente. Não altera nenhuma tabela existente, não cria job e
-- não dispara transporte. Requer 007 (mi_sinais é escrito pela aplicação, não
-- por esta migration) e 027 (crm_identidades_canal, usada no vínculo do lead).
--
-- Decisões de desenho que valem ser lidas antes de mexer aqui:
--
-- 1. O código impresso NUNCA muda. `codigo_publico` é único e imutável; o que
--    muda é o destino (destino_tipo/destino_url) e o estado. É isso que
--    permite corrigir um QR já impresso sem reimprimir.
-- 2. Avaliação anônima não guarda nada que identifique a pessoa: sem IP, sem
--    user-agent, sem identificador de aparelho. `chave` é gerada no navegador
--    só para não contar duas vezes o mesmo envio (retry de rede, reenvio).
-- 3. O contato vive em UM lugar — leads_crm. Aqui só ficam os dois
--    consentimentos (contato e marketing), separados, com a versão do texto
--    que a pessoa viu.
-- 4. Nada de PII em qr_eventos nem em qr_avaliacoes. Comentário livre é a
--    exceção e fica só em qr_avaliacoes.comentario, nunca em sinais.

CREATE TABLE IF NOT EXISTS qr_codigos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_publico TEXT NOT NULL,
    slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    -- Frase impressa junto do QR ("Provou? Conte o que achou.").
    chamada TEXT NOT NULL,
    finalidade TEXT NOT NULL CHECK (finalidade IN
        ('avaliacao_feira','avaliacao_produto','comercial','divulgacao')),
    origem TEXT NOT NULL,
    campanha TEXT,
    canal TEXT NOT NULL DEFAULT 'qr',
    -- Onde o QR está fisicamente ou digitalmente (estande, embalagem, slide 3).
    posicao TEXT,
    -- Vínculo opcional com a rastreabilidade física já existente.
    sku TEXT,
    lote_id UUID,
    unidade_id UUID,
    destino_tipo TEXT NOT NULL DEFAULT 'pagina'
        CHECK (destino_tipo IN ('pagina','redirecionar')),
    destino_url TEXT,
    estado TEXT NOT NULL DEFAULT 'ativo' CHECK (estado IN ('ativo','pausado','revogado')),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (destino_tipo <> 'redirecionar' OR destino_url IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS qr_codigos_codigo_publico_unico ON qr_codigos(codigo_publico);
CREATE UNIQUE INDEX IF NOT EXISTS qr_codigos_slug_unico ON qr_codigos(slug);

-- Funil: só o que aconteceu, por código. Uma linha por (código, tipo, chave),
-- então o mesmo envio repetido não conta duas vezes.
CREATE TABLE IF NOT EXISTS qr_eventos (
    id BIGSERIAL PRIMARY KEY,
    qr_id UUID NOT NULL REFERENCES qr_codigos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('qr_scan','avaliacao_iniciada')),
    chave UUID NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (qr_id, tipo, chave)
);

CREATE INDEX IF NOT EXISTS qr_eventos_qr_tipo_idx ON qr_eventos(qr_id, tipo, criado_em DESC);

CREATE TABLE IF NOT EXISTS qr_avaliacoes (
    id UUID PRIMARY KEY,
    qr_id UUID NOT NULL REFERENCES qr_codigos(id),
    chave UUID NOT NULL,
    perfil TEXT NOT NULL,
    aplicacao TEXT NOT NULL,
    nota SMALLINT NOT NULL CHECK (nota BETWEEN 0 AND 10),
    guarana TEXT NOT NULL CHECK (guarana IN ('baixo','ideal','alto')),
    docura TEXT NOT NULL CHECK (docura IN ('baixo','ideal','alto')),
    acidez TEXT NOT NULL CHECK (acidez IN ('baixo','ideal','alto')),
    gengibre TEXT NOT NULL CHECK (gengibre IN ('baixo','ideal','alto')),
    textura TEXT NOT NULL CHECK (textura IN ('baixo','ideal','alto')),
    intencao_compra TEXT NOT NULL CHECK (intencao_compra IN
        ('certamente','provavelmente','talvez','nao')),
    -- Teto que a pessoa pagaria por 200 mL. `aceita_59` é DERIVADO no servidor
    -- (ver qr_rastreavel.FAIXAS_PRECO); o navegador nunca o informa.
    faixa_preco TEXT NOT NULL CHECK (faixa_preco IN
        ('ate_39','40_49','50_58','59_69','70_ou_mais')),
    aceita_59 BOOLEAN NOT NULL,
    formas_uso TEXT[] NOT NULL DEFAULT '{}',
    comentario TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (qr_id, chave)
);

CREATE INDEX IF NOT EXISTS qr_avaliacoes_qr_idx ON qr_avaliacoes(qr_id, criado_em DESC);
CREATE INDEX IF NOT EXISTS qr_avaliacoes_perfil_idx ON qr_avaliacoes(perfil);

-- Consentimentos SEPARADOS: contato (sobre este pedido) e marketing
-- (novidades). O contato em si não é copiado para cá — fica em leads_crm.
CREATE TABLE IF NOT EXISTS qr_contatos (
    id UUID PRIMARY KEY,
    qr_id UUID NOT NULL REFERENCES qr_codigos(id),
    chave UUID NOT NULL,
    avaliacao_id UUID REFERENCES qr_avaliacoes(id),
    lead_id UUID,
    interesse TEXT NOT NULL CHECK (interesse IN
        ('comprar','servir','amostra','proposta','revenda','distribuicao','parceria')),
    perfil TEXT,
    consentimento_contato BOOLEAN NOT NULL CHECK (consentimento_contato),
    consentimento_marketing BOOLEAN NOT NULL DEFAULT FALSE,
    texto_consentimento_versao TEXT NOT NULL,
    -- TRUE quando o telefone/e-mail já pertencia a mais de um cadastro (ou a
    -- um cadastro arquivado): o lead foi criado sem vínculo automático e a
    -- duplicata aparece em /api/admin/crm/duplicados para decisão humana.
    identidade_pendente BOOLEAN NOT NULL DEFAULT FALSE,
    lead_ja_existia BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (qr_id, chave)
);

CREATE INDEX IF NOT EXISTS qr_contatos_qr_idx ON qr_contatos(qr_id, criado_em DESC);
CREATE INDEX IF NOT EXISTS qr_contatos_lead_idx ON qr_contatos(lead_id) WHERE lead_id IS NOT NULL;

-- Os quatro QRs iniciais. Os códigos foram gerados uma única vez com fonte
-- criptográfica e já estão impressos nos arquivos de artes/qr; ON CONFLICT
-- garante que reaplicar esta migration nunca troque um código em uso.
INSERT INTO qr_codigos (codigo_publico, slug, nome, chamada, finalidade, origem, campanha, canal, posicao)
VALUES
 ('p8qp3av4g5', 'softdrinks_tech_2026', 'Softdrinks Tech 2026 — avaliação e contatos da feira',
  'Provou? Conte o que achou.', 'avaliacao_feira', 'feira', 'softdrinks_tech_2026', 'qr', 'estande'),
 ('wrn2hkps5b', 'produto_embalagem', 'Produto — avaliações posteriores à compra',
  'Conte sua experiência com Maranhão.', 'avaliacao_produto', 'embalagem', 'produto_permanente', 'qr', 'embalagem'),
 ('272j7fy6my', 'material_comercial', 'Material comercial — compra, amostra, proposta, revenda ou distribuição',
  'Quer comprar, servir ou representar Maranhão?', 'comercial', 'material_comercial', 'comercial_permanente', 'qr', 'material_impresso'),
 ('gcy3t5drzj', 'divulgacao_digital', 'Divulgação digital — apresentações, redes e campanhas',
  'Conheça o universo Maranhão Cordial.', 'divulgacao', 'digital', 'divulgacao_permanente', 'qr', 'apresentacoes_e_redes')
ON CONFLICT (slug) DO NOTHING;
