/* Vitrine pública "Produtos da Maranhão" (catalogo-vitrine.js) e a página
 * genérica de produto (produto-pagina.js): lógica pura de link/rótulo,
 * sem checkout inventado. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const v = require('../maranhao-backend/catalogo-vitrine.js');
const vitrineFonte = fs.readFileSync('maranhao-backend/catalogo-vitrine.js', 'utf8');

const pr = require('../maranhao-backend/produto-pagina.js');
const produtoFonte = fs.readFileSync('maranhao-backend/produto-pagina.js', 'utf8');
const produtoHtml = fs.readFileSync('maranhao-backend/produto.html', 'utf8');

const indexHtml = fs.readFileSync('maranhao-backend/index.html', 'utf8');
const compreaquiHtml = fs.readFileSync('maranhao-backend/compreaqui.html', 'utf8');

function produto(extra = {}) {
    return Object.assign({
        slug: 'maranhao-cordial', nome: 'Maranhão Cordial', status: 'publicado',
        modalidade_compra: 'comprar_site', url_compra: '/compreaqui.html#checkoutCard',
        preco_centavos: 5990, unidade_venda: 'unidade', quantidade_minima: 12, midias: [],
    }, extra);
}

test('preço formatado em reais, sem preço vira null (não "R$ NaN")', () => {
    assert.equal(v.formatarPreco(5990), 'R$ 59,90');
    assert.equal(v.formatarPreco(null), null);
});

test('preço por unidade deixa clara a compra mínima -- nunca sugere compra unitária', () => {
    // É exatamente o caso real do Maranhão Cordial: R$ 59,90 é o valor por
    // unidade, mas a compra começa numa caixa de 12 -- o texto precisa dizer
    // isso, senão "R$ 59,90" por si só sugere que dá para comprar 1 unidade.
    assert.equal(v.textoPreco(produto()), 'R$\u00A059,90 / unidade · compra mínima de 12 unidades');
    assert.doesNotMatch(v.textoPreco(produto()), /^A partir de/);
});

test('sem compra mínima (1 unidade), o texto não inventa uma condição', () => {
    assert.equal(v.textoPreco(produto({ quantidade_minima: 1 })), 'R$\u00A059,90 / unidade');
});

test('sem preço cadastrado, não mostra preço nenhum', () => {
    assert.equal(v.textoPreco(produto({ preco_centavos: null })), null);
});

test('comprar_site com url_compra vai direto para a compra que já funciona', () => {
    assert.equal(v.linkDoProduto(produto()), '/compreaqui.html#checkoutCard');
});

test('orçamento e em_breve sempre passam pela página do produto, nunca por um checkout inventado', () => {
    assert.equal(v.linkDoProduto(produto({ modalidade_compra: 'orcamento', url_compra: null })), '/produto/maranhao-cordial');
    assert.equal(v.linkDoProduto(produto({ status: 'em_breve', modalidade_compra: 'em_breve', url_compra: null })), '/produto/maranhao-cordial');
});

test('comprar_site sem url_compra (dado inconsistente) não inventa link: cai na página do produto', () => {
    assert.equal(v.linkDoProduto(produto({ url_compra: null })), '/produto/maranhao-cordial');
});

test('rótulo do cartão reflete a modalidade e nunca promete pagamento em "em breve"', () => {
    assert.equal(v.rotuloDoProduto(produto()), 'Ver produto');
    assert.equal(v.rotuloDoProduto(produto({ modalidade_compra: 'orcamento' })), 'Solicitar orçamento');
    assert.equal(v.rotuloDoProduto(produto({ status: 'em_breve', modalidade_compra: 'em_breve' })), 'Em breve');
});

test('capa: usa a mídia marcada como capa; sem marcação, a primeira imagem', () => {
    const midias = [{ tipo: 'imagem', url: '/a.jpg', capa: false }, { tipo: 'video', url: '/v.mp4', capa: true }, { tipo: 'imagem', url: '/b.jpg', capa: true }];
    assert.equal(v.capaDoProduto(produto({ midias })).url, '/b.jpg');
    assert.equal(v.capaDoProduto(produto({ midias: [{ tipo: 'imagem', url: '/c.jpg', capa: false }] })).url, '/c.jpg');
    assert.equal(v.capaDoProduto(produto({ midias: [] })), null);
});

test('vitrine: nada de innerHTML com dado do servidor, cartões via DOM', () => {
    assert.doesNotMatch(vitrineFonte, /innerHTML|insertAdjacentHTML|document\.write/);
    assert.match(vitrineFonte, /credentials: 'omit'/);
});

test('slug da URL de /produto/<slug>', () => {
    assert.equal(pr.slugDaUrl('/produto/vela-de-cheiro'), 'vela-de-cheiro');
    assert.equal(pr.slugDaUrl('/produto/'), null);
    assert.equal(pr.slugDaUrl('/outra/coisa'), null);
});

test('orçamento reaproveita a solicitação profissional existente, com o produto na origem', () => {
    assert.equal(pr.linkOrcamento('vela-de-cheiro'), '/cadastro-profissional?origem=orcamento_vela-de-cheiro');
});

test('produto-pagina.js aplica a mesma regra de preço por unidade + compra mínima', () => {
    assert.equal(pr.textoPreco(produto()), 'R$ 59,90 / unidade · compra mínima de 12 unidades');
    assert.equal(pr.textoPreco(produto({ quantidade_minima: 1 })), 'R$ 59,90 / unidade');
});

test('CTA da página do produto por modalidade — em_breve nunca tem botão', () => {
    assert.equal(pr.rotuloCTA(produto()), 'Comprar');
    assert.equal(pr.hrefCTA(produto()), '/compreaqui.html#checkoutCard');
    assert.equal(pr.rotuloCTA(produto({ modalidade_compra: 'orcamento' })), 'Solicitar orçamento');
    assert.equal(pr.hrefCTA(produto({ modalidade_compra: 'orcamento' })), '/cadastro-profissional?origem=orcamento_maranhao-cordial');
    assert.equal(pr.rotuloCTA(produto({ modalidade_compra: 'em_breve' })), null);
    assert.equal(pr.hrefCTA(produto({ modalidade_compra: 'em_breve' })), null);
});

test('produto-pagina.js não simula nenhum checkout nem faz POST de pagamento', () => {
    assert.doesNotMatch(produtoFonte, /fetch\([^)]*method:\s*['"]POST['"]/);
    assert.doesNotMatch(produtoFonte, /\bpix\b/i);
    assert.match(produtoFonte, /sem possibilidade de pagamento/, '"em breve" precisa dizer explicitamente que não há pagamento');
    assert.doesNotMatch(produtoFonte, /innerHTML|insertAdjacentHTML|document\.write/);
});

test('produto.html é indexável (não é um recurso interno como a página de QR)', () => {
    assert.match(produtoHtml, /name="robots" content="index, follow"/);
});

test('a página inicial e "Compre aqui" carregam a vitrine/o player e não têm "premium"', () => {
    assert.match(indexHtml, /<script src="catalogo-vitrine\.js" defer><\/script>/);
    assert.match(indexHtml, /<link rel="stylesheet" href="mc-player\.css">/);
    assert.match(compreaquiHtml, /<link rel="stylesheet" href="mc-player\.css">/);
    assert.match(compreaquiHtml, /id="mc-player"/);
    for (const html of [indexHtml, compreaquiHtml]) {
        assert.doesNotMatch(html, /premium/i);
    }
});

test('página inicial: mensagem principal, botões e a seção da bebida preservada', () => {
    assert.match(indexHtml, /Produtos regionais, entregues a você\./);
    assert.match(indexHtml, /Conheça os produtos<\/a>/);
    assert.match(indexHtml, /Conheça o Maranhão Cordial<\/a>/);
    assert.match(indexHtml, /Nossa bebida\. O início de uma coleção regional\./);
    // O vídeo das três garrafas continua no lugar, sem ser trocado.
    assert.match(indexHtml, /maranhao-cordial-hero\.mp4/);
    assert.match(indexHtml, /id="mc-produtos-grid"/);
});

test('"Compre aqui": intro do catálogo, vídeo novo no lugar da imagem, legenda e sem cortar o quadro', () => {
    assert.match(compreaquiHtml, /Produtos regionais, entregues a você\./);
    assert.match(compreaquiHtml, /Conheça os produtos disponíveis e consulte as condições de compra e entrega de cada item\./);
    assert.match(compreaquiHtml, /maranhao-regional-10s\.mp4/);
    assert.doesNotMatch(compreaquiHtml, /maranhaotrio\.png/, 'a imagem das três garrafas foi substituída pelo vídeo');
    assert.match(compreaquiHtml, /Cena ilustrativa\. Consulte a apresentação de cada produto\./);
    assert.match(compreaquiHtml, /object-fit: contain/);
    assert.match(compreaquiHtml, /aspect-ratio: 1 \/ 1/);
    assert.match(compreaquiHtml, /muted/);
    assert.match(compreaquiHtml, /loop/);
    assert.match(compreaquiHtml, /playsinline/);
    assert.match(compreaquiHtml, /prefers-reduced-motion/);
    assert.match(compreaquiHtml, /heroRegionalVideoToggle/);
});

test('as regras comerciais da bebida continuam intactas em "Compre aqui"', () => {
    assert.match(compreaquiHtml, /1 caixa · 12 unidades/);
    assert.match(compreaquiHtml, /2 caixas · 24 unidades/);
    assert.match(compreaquiHtml, /api\/c6\/pix\/checkout/);
    assert.match(compreaquiHtml, /R\$ 59,90/);
});
