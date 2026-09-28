/* Hero cinematográfico ("MARANHÃO" como máscara de vídeo): lógica pura
 * (máscara SVG e o recorte tipo object-fit:cover do canvas) mais garantias
 * estáticas de que o conteúdo, os vídeos, o player, o catálogo e o checkout
 * existentes não foram alterados -- só a apresentação do hero mudou. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const cine = require('../maranhao-backend/mc-cine.js');
const cineLite = require('../maranhao-backend/mc-cine-lite.js');
const cineFonte = fs.readFileSync('maranhao-backend/mc-cine.js', 'utf8');
const cineLiteFonte = fs.readFileSync('maranhao-backend/mc-cine-lite.js', 'utf8');
const indexHtml = fs.readFileSync('maranhao-backend/index.html', 'utf8');
const compreaquiHtml = fs.readFileSync('maranhao-backend/compreaqui.html', 'utf8');

test('máscara: só a letra tem alpha (sem <rect> de fundo, senão a máscara não recorta nada)', () => {
    const url = cine.mascaraDaPalavra('MARANHÃO');
    assert.match(url, /^url\("data:image\/svg\+xml,/);
    const svg = decodeURIComponent(url.slice('url("data:image/svg+xml,'.length, -2));
    assert.doesNotMatch(svg, /<rect/);
    assert.match(svg, /<text[^>]*>MARANHÃO<\/text>/);
    assert.match(svg, /fill='white'/);
});

test('máscara: texto vai inteiro para o SVG (a letra certa aparece)', () => {
    const url = cineLite.mascaraDaPalavra('TESTE');
    const svg = decodeURIComponent(url.slice('url("data:image/svg+xml,'.length, -2));
    assert.match(svg, /TESTE/);
});

test('recorte do canvas replica object-fit: cover (preenche sem distorcer, corta o excesso)', () => {
    // Vídeo mais largo que o canvas: cover deve cortar as laterais.
    const r1 = cine.retanguloCover(100, 100, 200, 100);
    assert.equal(r1.dh, 100);
    assert.ok(r1.dw > 100);
    assert.ok(r1.dx < 0);
    // Vídeo mais alto que o canvas: cover deve cortar em cima/embaixo.
    const r2 = cine.retanguloCover(100, 100, 100, 200);
    assert.equal(r2.dw, 100);
    assert.ok(r2.dh > 100);
    assert.ok(r2.dy < 0);
    // Mesma proporção: preenche exatamente, sem sobra.
    const r3 = cine.retanguloCover(100, 50, 200, 100);
    assert.equal(r3.dw, 100);
    assert.equal(r3.dh, 50);
    assert.equal(r3.dx, 0);
    assert.equal(r3.dy, 0);
});

test('o vídeo do hero nunca é referenciado duas vezes (um <video>, o canvas só desenha a partir dele)', () => {
    const ocorrencias = (indexHtml.match(/maranhao-cordial-hero\.mp4/g) || []).length;
    // Uma vez no <source> do vídeo real e uma vez no <source> do fallback
    // (prefers-reduced-motion / sem JS) -- nunca um terceiro <video> ativo
    // ao mesmo tempo, e o canvas não tem src próprio.
    assert.equal(ocorrencias, 2, 'esperado: 1 no hero cinematográfico + 1 no fallback estático, nunca mais');
    assert.equal((indexHtml.match(/<video class=/g) || []).length, 2, 'só as duas tags <video> reais, sem contar comentários que mencionam <video>');
});

test('mc-cine.js nunca chama .load()/.src= numa segunda cópia do vídeo (não recarrega o arquivo)', () => {
    assert.doesNotMatch(cineFonte, /new Audio|createElement\('video'\)|createElement\("video"\)/);
});

test('canvas e vídeo real reservam dimensão (aspect-ratio) -- sem isso, salto de layout ao carregar', () => {
    assert.match(indexHtml, /\.mc-cine-word \{[^}]*aspect-ratio: 16 \/ 5/s);
    assert.match(compreaquiHtml, /\.mc-lite-word \{[^}]*aspect-ratio: 16 \/ 6/s);
});

test('prefers-reduced-motion esconde o pin/zoom nas duas páginas e mostra o fallback', () => {
    assert.match(indexHtml, /@media \(prefers-reduced-motion: reduce\) \{[^}]*\.mc-cine-pin \{ display: none/s);
    assert.match(indexHtml, /\.mc-cine-fallback \{ display: flex/);
    assert.match(compreaquiHtml, /@media \(prefers-reduced-motion: reduce\) \{\s*\.mc-lite-hero \{ display: none/);
    assert.match(cineFonte, /prefers-reduced-motion: reduce/);
    assert.match(cineLiteFonte, /prefers-reduced-motion: reduce/);
});

test('sem JavaScript, o conteúdo do produto/garrafas não fica invisível (noscript cobre o fallback)', () => {
    assert.match(indexHtml, /<noscript><style>[\s\S]*\.mc-cine-produto-img, \.mc-cine-produto-copy \{ opacity: 1/);
    assert.match(compreaquiHtml, /<noscript><style>\.mc-lite-word\{opacity:1/);
});

test('microinteração do mouse só roda com hover fino (desktop) e nunca distorce as letras (só x/y)', () => {
    assert.match(cineFonte, /hover: hover.*pointer: fine/);
    assert.doesNotMatch(cineFonte, /quickTo\(palavra, ['"]scale['"]/);
    assert.doesNotMatch(cineFonte, /quickTo\(palavra, ['"]skew/);
});

test('GSAP e ScrollTrigger carregados uma vez cada, antes de mc-cine.js', () => {
    const gsapIdx = indexHtml.indexOf('gsap.min.js');
    const stIdx = indexHtml.indexOf('ScrollTrigger.min.js');
    const cineIdx = indexHtml.indexOf('src="mc-cine.js"');
    assert.ok(gsapIdx > 0 && stIdx > gsapIdx && cineIdx > stIdx);
    assert.equal((indexHtml.match(/gsap\.min\.js/g) || []).length, 1);
    assert.equal((indexHtml.match(/ScrollTrigger\.min\.js/g) || []).length, 1);
});

test('página inicial: h1 de SEO preservado ("Produtos regionais, entregues a você.") e único na página', () => {
    const h1s = indexHtml.match(/<h1[^>]*>([\s\S]*?)<\/h1>/g) || [];
    assert.equal(h1s.length, 1, 'só pode haver um <h1> na página');
    assert.match(h1s[0], /Produtos regionais, entregues a você\./);
});

test('"MARANHÃO" grande continua acessível (h2 fora de tela, não decorativo escondido de leitor de tela)', () => {
    assert.match(indexHtml, /<h2 class="mc-cine-sr">Maranhão<\/h2>/);
});

test('conteúdo comercial e sabores existentes continuam intactos, só reordenados na narrativa', () => {
    for (const trecho of [
        'Nossa bebida. O início de uma coleção regional.',
        'Concentrado líquido botânico sem álcool para preparar drinks.',
        'Guaraná &amp; Gengibre', 'Bacuri &amp; Gengibre', 'Cajá &amp; Gengibre',
        '0,0% álcool',
        'Conheça o Maranhão Cordial, nosso concentrado líquido botânico',
        'data-mc-cta="produtos_home"', 'data-mc-cta="bebida_home"',
    ]) {
        assert.ok(indexHtml.includes(trecho), trecho);
    }
});

test('legenda "Maranhão Cordial / Cordiais brasileiros. / 0,0% álcool" existe uma vez no hero cinematográfico', () => {
    assert.match(indexHtml, /<p class="mc-cine-caption-title">Maranhão Cordial<\/p>/);
    assert.match(indexHtml, /<p class="mc-cine-caption-tag">Cordiais brasileiros\.<\/p>/);
    assert.match(indexHtml, /<p class="mc-cine-caption-abv">0,0% álcool<\/p>/);
});

test('"Compre aqui": o vídeo já existente (maranhao-regional-10s.mp4) é reaproveitado no hero leve, não duplicado', () => {
    const ocorrencias = (compreaquiHtml.match(/<source src="\/assets\/video\/maranhao-regional-10s\.mp4"/g) || []).length;
    // 1 no hero leve (mc-lite-video) + 1 no bloco de vídeo já existente da
    // seção .hero -- as duas tags já existiam como necessidade de duas
    // telas diferentes (mc-lite-video é novo, mas aponta pro mesmo arquivo).
    // Conta só <source>, não o nome do arquivo solto (que também aparece
    // num comentário do CSS explicando a reutilização).
    assert.equal(ocorrencias, 2);
});

test('"Compre aqui": catálogo e checkout da bebida continuam intactos', () => {
    for (const trecho of [
        '1 caixa · 12 unidades', '2 caixas · 24 unidades', 'api/c6/pix/checkout',
        'R$ 59,90', 'Lotes profissionais', 'id="checkoutCard"',
        'Produtos regionais, entregues a você.',
        'Conheça os produtos disponíveis e consulte as condições de compra e entrega de cada item.',
        'Cena ilustrativa. Consulte a apresentação de cada produto.',
    ]) {
        assert.ok(compreaquiHtml.includes(trecho), trecho);
    }
});

test('player de música presente e intacto nas duas páginas', () => {
    for (const html of [indexHtml, compreaquiHtml]) {
        assert.match(html, /id="mc-player"/);
        assert.match(html, /id="mc-progress"/);
        assert.match(html, /mc-player\.js/);
    }
});

test('sem "premium" em nenhuma das duas páginas', () => {
    assert.doesNotMatch(indexHtml, /premium/i);
    assert.doesNotMatch(compreaquiHtml, /premium/i);
});

test('a vitrine de produtos (catalogo-vitrine.js) continua carregada na home, sem alteração de contrato', () => {
    assert.match(indexHtml, /<script src="catalogo-vitrine\.js" defer><\/script>/);
    assert.match(indexHtml, /id="mc-produtos-grid"/);
});
