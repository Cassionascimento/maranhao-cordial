/* Hero cinematográfico ("MARANHÃO" como porta de entrada para o vídeo):
 * lógica pura (máscara SVG medida em tempo real, largura segura que nunca
 * corta a palavra, recorte tipo object-fit:cover do canvas) mais garantias
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

function svgDaMascara(url) {
    return decodeURIComponent(url.slice('url("data:image/svg+xml,'.length, -2));
}

test('máscara: só a letra tem alpha (sem <rect> de fundo, senão a máscara não recorta nada)', () => {
    const { url } = cine.mascaraDaPalavra('MARANHÃO', 1400, { tamanhoFonte: 300 });
    assert.match(url, /^url\("data:image\/svg\+xml,/);
    const svg = svgDaMascara(url);
    assert.doesNotMatch(svg, /<rect/);
    assert.match(svg, /<text[^>]*>MARANHÃO<\/text>/);
    assert.match(svg, /fill='white'/);
});

test('máscara: texto vai inteiro para o SVG (a letra certa aparece)', () => {
    const url = cineLite.mascaraDaPalavra('TESTE', 500, { tamanhoFonte: 280 });
    assert.match(svgDaMascara(url), /TESTE/);
});

test('a máscara NUNCA corta a palavra internamente: o viewBox sempre acomoda a largura medida do texto', () => {
    // É exatamente o bug relatado (M inicial e Ã/O final cortados): um
    // viewBox mais estreito que o texto medido cortava a palavra na
    // origem, antes mesmo de qualquer mask-size entrar em jogo.
    for (const larguraTexto of [200, 900, 1400, 2200, 3000]) {
        const { url, proporcao } = cine.mascaraDaPalavra('MARANHÃO', larguraTexto, { tamanhoFonte: 300, margem: 84 });
        const svg = svgDaMascara(url);
        const viewBox = svg.match(/viewBox='0 0 (\d+) (\d+)'/).slice(1, 3).map(Number);
        assert.ok(viewBox[0] >= larguraTexto + 84 * 2 - 1, `viewBox ${viewBox[0]} deveria acomodar texto de ${larguraTexto} + margens`);
        assert.equal(Math.round(proporcao * 1000), Math.round((viewBox[0] / viewBox[1]) * 1000));
    }
});

test('largura segura do mask: nunca ultrapassa a viewport, nem por largura nem por altura', () => {
    const proporcao = 3.37; // aproximado de "MARANHÃO" em Georgia 700, largura:altura
    // Desktop largo: a largura da tela é o limite.
    const desktop = cine.larguraSeguraDoMask(proporcao, 1920, 1080, 40, 40);
    assert.ok(desktop <= 1920 - 80);
    assert.ok(desktop * (1 / proporcao) <= 1080 - 80 + 1);
    // Celular: alto e estreito -- a largura da tela deve seguir sendo o
    // limite para uma palavra larga e baixa como esta (3.37:1).
    const mobile = cine.larguraSeguraDoMask(proporcao, 375, 812, 22, 30);
    assert.ok(mobile <= 375 - 44);
    // Viewport artificialmente baixa (ex.: paisagem no celular): a altura
    // vira o limite, e o resultado precisa respeitar isso.
    const baixinha = cine.larguraSeguraDoMask(proporcao, 1200, 200, 20, 20);
    assert.ok(baixinha <= (200 - 40) * proporcao + 1);
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
    // Mesma proporção: preenche exatamente, sem sobra (nunca esticado).
    const r3 = cine.retanguloCover(100, 50, 200, 100);
    assert.equal(r3.dw, 100);
    assert.equal(r3.dh, 50);
    assert.equal(r3.dx, 0);
    assert.equal(r3.dy, 0);
});

test('o vídeo do hero nunca é referenciado duas vezes (um <video>, o canvas só desenha a partir dele)', () => {
    const ocorrencias = (indexHtml.match(/maranhao-cordial-hero\.mp4/g) || []).length;
    assert.equal(ocorrencias, 2, 'esperado: 1 no hero cinematográfico + 1 no fallback estático, nunca mais');
    assert.equal((indexHtml.match(/<video class=/g) || []).length, 2, 'só as duas tags <video> reais, sem contar comentários que mencionam <video>');
});

test('mc-cine.js nunca chama .load()/.src= numa segunda cópia do vídeo (não recarrega o arquivo)', () => {
    assert.doesNotMatch(cineFonte, /new Audio|createElement\('video'\)|createElement\("video"\)/);
});

test('o canvas cobre a tela desde o primeiro frame -- nunca é redimensionado por transform:scale', () => {
    assert.match(indexHtml, /\.mc-cine-canvas \{[^}]*position: absolute/s);
    assert.doesNotMatch(cineFonte, /gsap\.(to|fromTo|set)\(\s*canvas,\s*\{[^}]*scale/s);
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

test('microinteração do mouse só roda com hover fino (desktop), no canvas, e nunca distorce (só x/y)', () => {
    assert.match(cineFonte, /hover: hover.*pointer: fine/);
    assert.match(cineFonte, /quickTo\(canvas, ['"]x['"]/);
    assert.doesNotMatch(cineFonte, /quickTo\(canvas, ['"]scale['"]/);
    assert.doesNotMatch(cineFonte, /quickTo\(canvas, ['"]skew/);
});

test('GSAP e ScrollTrigger carregados uma vez cada, antes de mc-cine.js', () => {
    const gsapIdx = indexHtml.indexOf('gsap.min.js');
    const stIdx = indexHtml.indexOf('ScrollTrigger.min.js');
    const cineIdx = indexHtml.indexOf('src="mc-cine.js"');
    assert.ok(gsapIdx > 0 && stIdx > gsapIdx && cineIdx > stIdx);
    assert.equal((indexHtml.match(/gsap\.min\.js/g) || []).length, 1);
    assert.equal((indexHtml.match(/ScrollTrigger\.min\.js/g) || []).length, 1);
});

test('a fase de máscara é curta e o vídeo em tela cheia tem tempo de sobra antes do produto', () => {
    // Extrai a duração total pinada (end: '+=N%') e os dois trechos que
    // fazem a máscara crescer -- juntos, não podem passar de ~45% do
    // percurso: o resto é vídeo já em tela cheia (o pedido explícito de
    // "tempo suficiente para o vídeo ser apreciado").
    const fimPin = Number(cineFonte.match(/end: '\+=(\d+)%'/)[1]);
    assert.ok(fimPin <= 180, 'o percurso pinado precisa ser curto (pouca tela preta/estreita)');
    const duracoes = [...cineFonte.matchAll(/duration: (0\.\d+), ease: '(?:power1\.out|power3\.in)'/g)].map(m => Number(m[1]));
    assert.equal(duracoes.length, 2);
    const fimDaExpansao = duracoes.reduce((a, b) => a + b, 0);
    assert.ok(fimDaExpansao <= 0.45, `máscara deveria terminar de expandir cedo, terminou em ${fimDaExpansao}`);
});

test('a legenda fica no terço inferior -- nunca cobre o centro do quadro do vídeo', () => {
    assert.match(indexHtml, /\.mc-cine-caption \{[^}]*justify-content: flex-end/s);
    assert.doesNotMatch(indexHtml, /\.mc-cine-caption \{[^}]*justify-content: center/s);
});

test('página inicial: h1 de SEO preservado ("Produtos regionais, entregues a você.") e único na página', () => {
    const h1s = indexHtml.match(/<h1[^>]*>([\s\S]*?)<\/h1>/g) || [];
    assert.equal(h1s.length, 1, 'só pode haver um <h1> na página');
    assert.match(h1s[0], /Produtos regionais, entregues a você\./);
});

test('"MARANHÃO" grande continua acessível (h2 fora de tela, não decorativo escondido de leitor de tela)', () => {
    assert.match(indexHtml, /<h2 class="mc-cine-sr">Maranhão<\/h2>/);
});

test('imagem das garrafas nunca deforma: height:auto explícito, sem width/height fixos conflitantes', () => {
    assert.match(indexHtml, /\.mc-cine-produto-img \{[^}]*height: auto/s);
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
    assert.equal(ocorrencias, 2);
});

test('"Compre aqui": efeito leve, curto (sem pin nem scroll-scrub) -- não repete a experiência da home', () => {
    assert.doesNotMatch(cineLiteFonte, /ScrollTrigger|scrollTrigger|pin: true/);
    assert.doesNotMatch(cineLiteFonte, /\bgsap\.(to|from|fromTo|timeline|quickTo)\(/);
    assert.doesNotMatch(compreaquiHtml, /ScrollTrigger\.min\.js|gsap\.min\.js/);
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
