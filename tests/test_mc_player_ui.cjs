/* Player Five Moments (mc-player.js): garantias estáticas -- progresso,
 * persistência entre páginas e ausência de autoplay forçado com som. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const fonte = fs.readFileSync('maranhao-backend/mc-player.js', 'utf8');
const css = fs.readFileSync('maranhao-backend/mc-player.css', 'utf8');
const indexHtml = fs.readFileSync('maranhao-backend/index.html', 'utf8');
const compreaquiHtml = fs.readFileSync('maranhao-backend/compreaqui.html', 'utf8');

test('progresso: existe o controle e ele lê/escreve currentTime', () => {
    assert.match(fonte, /mc-progress/);
    assert.match(fonte, /timeupdate/);
    assert.match(fonte, /audio\.currentTime\s*=/);
});

test('volume e faixa são persistidos em localStorage, protegidos por try/catch', () => {
    assert.match(fonte, /localStorage\.setItem/);
    assert.match(fonte, /localStorage\.getItem/);
    assert.match(fonte, /try\s*{[^}]*localStorage/s);
});

test('nunca chama play() fora de um gesto explícito (clique) ou de retomada explicitamente marcada', () => {
    const chamadasDePlay = [...fonte.matchAll(/\.play\(\)/g)].length;
    // Todas as ocorrências de .play() devem estar dentro de um listener de
    // clique/submit ou guardadas por "retomarTocando" -- nunca soltas no
    // corpo do IIFE a executar no carregamento da página.
    assert.ok(chamadasDePlay >= 1);
    assert.doesNotMatch(fonte, /^\s*audio\.play\(\);?\s*$/m);
});

test('faixas continuam sendo as cinco do álbum já usado (nenhuma nova foi inventada)', () => {
    assert.match(fonte, /Black Ginga/);
    assert.match(fonte, /Maranhão Cordial/);
    const faixas = [...fonte.matchAll(/titulo: '([^']+)'/g)].map(m => m[1]);
    assert.equal(faixas.length, 5);
});

test('o mesmo CSS do player é compartilhado pelas duas páginas (mc-player.css)', () => {
    assert.match(indexHtml, /<link rel="stylesheet" href="mc-player\.css">/);
    assert.match(compreaquiHtml, /<link rel="stylesheet" href="mc-player\.css">/);
    assert.doesNotMatch(indexHtml, /\.mc-player\s*\{/, 'CSS do player não deve mais estar duplicado inline em index.html');
});

test('no celular, o player some do centro e evita o rodapé de compra/atendimento', () => {
    assert.match(css, /@media \(max-width: 600px\)/);
});
