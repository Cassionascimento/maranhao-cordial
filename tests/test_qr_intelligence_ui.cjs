/* Vista "QR & Avaliações" do Maranhão Intelligence: honestidade dos números. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const v = require('../maranhao-backend/qr-intelligence.js');
const fonte = fs.readFileSync('maranhao-backend/qr-intelligence.js', 'utf8');
const admin = fs.readFileSync('maranhao-backend/admin.html', 'utf8');
const mapa = fs.readFileSync('maranhao-backend/adm-experiencia.js', 'utf8');

test('sem dado o valor é "—", nunca 0%', () => {
    assert.equal(v.pct(null), '—');
    assert.equal(v.dec(null), '—');
    assert.equal(v.comAmostra(null, 0, true), '—');
    assert.equal(v.pct(0), '0%', 'zero medido continua sendo zero');
});

test('percentual sempre acompanha n e avisa amostra pequena', () => {
    assert.match(v.comAmostra(62.5, 8, true), /62,5%.*n=8.*amostra pequena/);
    assert.doesNotMatch(v.comAmostra(62.5, 80, false), /pequena/);
});

test('texto de amostra não afirma tendência abaixo do mínimo', () => {
    assert.match(v.textoAmostra({ n: 0 }, 30), /Ainda sem avaliações/);
    assert.match(v.textoAmostra({ n: 4, amostra_pequena: true }, 30), /não permite conclusão/);
    assert.doesNotMatch(v.textoAmostra({ n: 40, amostra_pequena: false }, 30), /não permite/);
});

test('todo texto vindo do servidor passa por esc()', () => {
    assert.equal(v.esc('<img src=x onerror=1>&"\''), '&lt;img src=x onerror=1&gt;&amp;&quot;&#39;');
    // Comentário, nome e perfil são os campos livres: têm de sair escapados.
    assert.match(fonte, /esc\(c\.comentario\)/);
    assert.match(fonte, /esc\(q\.nome\)/);
});

test('criação de QR: só campos preenchidos e nada de código enviado pelo navegador', () => {
    const c = v.corpoCriacao({ nome: ' Feira X ', chamada: 'Provou?', finalidade: 'avaliacao_feira', origem: 'feira', campanha: '', posicao: ' ', sku: '' });
    assert.deepEqual(c, { nome: 'Feira X', chamada: 'Provou?', finalidade: 'avaliacao_feira', origem: 'feira' });
    assert.equal('codigo_publico' in c, false);
    assert.ok(v.slugValido('feira_x_2026'));
    assert.ok(!v.slugValido('Feira X'));
});

test('a vista está no shell: script, estilo, botão e caminho na navegação', () => {
    assert.match(admin, /<script src="\/qr-intelligence\.js" defer><\/script>/);
    assert.match(admin, /href="\/qr-intelligence\.css"/);
    assert.ok(admin.indexOf('/maranhao-intelligence.js') < admin.indexOf('/qr-intelligence.js'), 'depende do shell do Command Center');
    assert.match(mapa, /id: 'qr-avaliacoes'/);
    assert.match(mapa, /aoAbrir: '\[data-mic-view="qr"\]'/);
    assert.match(fonte, /data-mic-view="qr"/);
});

test('sem "premium" e afins na tela', () => {
    assert.doesNotMatch(fonte, /premium|alto padr|exclusiv|luxo/i);
});
