-- Catálogo de produtos da Maranhão: a bebida deixa de ser o único produto
-- possível no site e passa a ser o primeiro item de um catálogo que a
-- administradora publica sozinha, sem programar. Aditiva e idempotente;
-- não altera nenhuma tabela existente e não toca no fluxo de checkout/Pix
-- da bebida (checkout.html, c6_pix.py), que continua com suas próprias
-- regras (caixas de 12/24, lotes profissionais).
--
-- Reaproveita mi_artefatos_blobs (migration 019) para os uploads (mesmo
-- BYTEA em Postgres já comprovado em produção) -- nenhum storage externo
-- novo. Uma mídia pode, em vez de um upload, apontar para um arquivo já
-- publicado no site (url_externa) -- é assim que o produto Maranhão
-- Cordial usa a mesma fotografia real que já existe em img/hero/, sem
-- duplicar bytes nem inventar uma imagem nova.

CREATE TABLE IF NOT EXISTS catalogo_produtos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    -- Livre: a categoria é o que a administradora digitar, nunca uma lista
    -- fixa no código (GET /api/admin/catalogo/categorias só sugere as já
    -- usadas, para reaproveitar nomes em vez de fixá-los).
    categoria TEXT NOT NULL,
    descricao_curta TEXT NOT NULL,
    descricao_completa TEXT,
    preco_centavos INTEGER CHECK (preco_centavos IS NULL OR preco_centavos >= 0),
    unidade_venda TEXT NOT NULL DEFAULT 'unidade',
    quantidade_minima INTEGER NOT NULL DEFAULT 1 CHECK (quantidade_minima >= 1),
    multiplo_compra INTEGER NOT NULL DEFAULT 1 CHECK (multiplo_compra >= 1),
    modalidade_compra TEXT NOT NULL CHECK (modalidade_compra IN ('comprar_site', 'orcamento', 'em_breve')),
    -- Só usado quando modalidade_compra='comprar_site': para onde o botão
    -- de compra leva (pode ser a página/seção que já tem um checkout real,
    -- como a da própria bebida -- isto nunca cria um checkout novo).
    url_compra TEXT,
    disponibilidade TEXT,
    status TEXT NOT NULL DEFAULT 'rascunho' CHECK (status IN ('rascunho', 'publicado', 'em_breve')),
    destaque_home BOOLEAN NOT NULL DEFAULT FALSE,
    ordem_exibicao INTEGER NOT NULL DEFAULT 0,
    -- Só os quatro campos citados no pedido, todos opcionais. Não é um
    -- editor de chave/valor livre -- ver docs/catalogo-produtos.md.
    volume TEXT,
    peso TEXT,
    composicao TEXT,
    cuidados TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (modalidade_compra <> 'comprar_site' OR url_compra IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS catalogo_produtos_slug_unico ON catalogo_produtos(slug);
CREATE INDEX IF NOT EXISTS catalogo_produtos_status_idx ON catalogo_produtos(status, ordem_exibicao);
CREATE INDEX IF NOT EXISTS catalogo_produtos_categoria_idx ON catalogo_produtos(categoria);

CREATE TABLE IF NOT EXISTS catalogo_produto_midias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    produto_id UUID NOT NULL REFERENCES catalogo_produtos(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('imagem', 'video')),
    blob_id UUID REFERENCES mi_artefatos_blobs(id),
    url_externa TEXT,
    alt_text TEXT NOT NULL DEFAULT '',
    capa BOOLEAN NOT NULL DEFAULT FALSE,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((blob_id IS NULL) <> (url_externa IS NULL))
);

CREATE INDEX IF NOT EXISTS catalogo_produto_midias_produto_idx ON catalogo_produto_midias(produto_id, ordem);
-- Sem isto, reaplicar a migration duplicaria a mídia semeada a cada vez
-- (o id da linha é gerado, então nunca colidiria sozinho com ON CONFLICT).
CREATE UNIQUE INDEX IF NOT EXISTS catalogo_produto_midias_url_unica
    ON catalogo_produto_midias(produto_id, url_externa) WHERE url_externa IS NOT NULL;

-- Produto inaugural: o Maranhão Cordial. Usa a fotografia real já
-- publicada (img/hero/tres-cordiais.webp) e o preço/checkout que já
-- existem em compreaqui.html -- nada aqui inventa dado novo. ON CONFLICT
-- garante que reaplicar esta migration nunca duplique nem reviva um
-- produto que a administradora despublicou.
INSERT INTO catalogo_produtos (
    slug, nome, categoria, descricao_curta, descricao_completa,
    preco_centavos, unidade_venda, quantidade_minima, multiplo_compra,
    modalidade_compra, url_compra, disponibilidade, status,
    destaque_home, ordem_exibicao, volume
) VALUES (
    'maranhao-cordial',
    'Maranhão Cordial',
    'Bebidas',
    'Concentrado líquido botânico sem álcool para preparar drinks.',
    'Guaraná & Gengibre, Bacuri & Gengibre e Cajá & Gengibre. Cada caixa contém unidades de um único sabor à sua escolha. 0,0% álcool.',
    5990,
    'unidade',
    12,
    12,
    'comprar_site',
    '/compreaqui.html#checkoutCard',
    'Disponível',
    'publicado',
    TRUE,
    0,
    '200 mL'
)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO catalogo_produto_midias (produto_id, tipo, url_externa, alt_text, capa, ordem)
SELECT id, 'imagem', '/img/hero/tres-cordiais.webp',
       'As três garrafas Maranhão Cordial lado a lado — Guaraná & Gengibre, Bacuri & Gengibre e Cajá & Gengibre.',
       TRUE, 0
FROM catalogo_produtos WHERE slug = 'maranhao-cordial'
ON CONFLICT (produto_id, url_externa) WHERE url_externa IS NOT NULL DO NOTHING;

-- Esta migration é somente um arquivo versionado: não foi executada
-- contra nenhum banco (nem produção, nem homologação) nesta etapa.
