/* Página pública do QR: lógica pura + garantias estáticas de privacidade. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const pg = require('../maranhao-backend/qr-pagina.js');
const fonte = fs.readFileSync('maranhao-backend/qr-pagina.js', 'utf8');
const html = fs.readFileSync('maranhao-backend/qr.html', 'utf8');
const ATRIBUTOS = ['guarana', 'docura', 'acidez', 'gengibre', 'textura'];

const avaliacaoCompleta = (extra = {}) => Object.assign({
    perfil: 'consumidor', aplicacao: 'mocktail', nota: 0,
    sensorial: { guarana: 'ideal', docura: 'alto', acidez: 'baixo', gengibre: 'ideal', textura: 'ideal' },
    intencao_compra: 'talvez', faixa_preco: '59_69', formas_uso: ['cozinha'], comentario: '  ',
}, extra);

test('código vem da URL, em minúscula, e só de /q/<codigo>', () => {
    assert.equal(pg.codigoDaUrl('/q/P8QP3AV4G5'), 'p8qp3av4g5');
    assert.equal(pg.codigoDaUrl('/q/p8qp3av4g5/'), 'p8qp3av4g5');
    for (const ruim of ['/', '/q/', '/q/a/b', '/outra/abc', '', null]) assert.equal(pg.codigoDaUrl(ruim), null, String(ruim));
});

test('nota 0 é uma nota válida (não é "vazio")', () => {
    assert.equal(pg.validarAvaliacao(avaliacaoCompleta({ nota: 0 }), ATRIBUTOS), null);
    assert.equal(pg.validarAvaliacao(avaliacaoCompleta({ nota: null }), ATRIBUTOS), 'nota');
});

test('avaliação aponta o primeiro campo que falta', () => {
    assert.equal(pg.validarAvaliacao(avaliacaoCompleta({ perfil: '' }), ATRIBUTOS), 'perfil');
    assert.equal(pg.validarAvaliacao(avaliacaoCompleta({ formas_uso: [] }), ATRIBUTOS), 'formas_uso');
    const sem = avaliacaoCompleta(); sem.sensorial.acidez = '';
    assert.equal(pg.validarAvaliacao(sem, ATRIBUTOS), 'acidez');
    assert.match(pg.mensagemDoCampo('acidez'), /acidez/i);
});

test('corpo da avaliação: sem comentário em branco, com isca, sem "aceita_59" e sem dado pessoal', () => {
    const corpo = pg.montarAvaliacao(avaliacaoCompleta(), 'k-1', '');
    assert.equal('comentario' in corpo, false);
    assert.equal(corpo.website, '');
    assert.equal('aceita_59' in corpo, false, 'o derivado é do servidor');
    assert.deepEqual(Object.keys(corpo).sort(),
        ['aplicacao', 'chave', 'formas_uso', 'faixa_preco', 'intencao_compra', 'nota', 'perfil', 'sensorial', 'website'].sort());
    assert.equal(pg.montarAvaliacao(avaliacaoCompleta({ comentario: ' Bom ' }), 'k', '').comentario, 'Bom');
});

const contatoOk = (extra = {}) => Object.assign({
    nome: 'Marina', whatsapp: '(98) 99000-0000', email: '', interesse: 'amostra', consentimento_contato: true,
}, extra);

test('contato: nome, um meio de contato, interesse e consentimento de contato', () => {
    assert.equal(pg.validarContato(contatoOk()), null);
    assert.equal(pg.validarContato(contatoOk({ nome: ' ' })), 'nome');
    assert.equal(pg.validarContato(contatoOk({ whatsapp: '', email: '' })), 'contato');
    assert.equal(pg.validarContato(contatoOk({ whatsapp: '123' })), 'whatsapp');
    assert.equal(pg.validarContato(contatoOk({ whatsapp: '', email: 'sem-arroba' })), 'email');
    assert.equal(pg.validarContato(contatoOk({ whatsapp: '', email: 'a@b.co' })), null);
    assert.equal(pg.validarContato(contatoOk({ interesse: '' })), 'interesse');
});

test('consentimento de contato é obrigatório e o de marketing não o substitui', () => {
    assert.equal(pg.validarContato(contatoOk({ consentimento_contato: false, consentimento_marketing: true })), 'consentimento_contato');
    assert.equal(pg.validarContato(contatoOk({ consentimento_contato: 'true' })), 'consentimento_contato');
    const c = pg.montarContato(contatoOk({ consentimento_marketing: undefined }), 'k', 'av', '');
    assert.equal(c.consentimento_contato, true);
    assert.equal(c.consentimento_marketing, false, 'marketing só vale se marcado');
    assert.equal(c.avaliacao_chave, 'av');
    assert.equal('avaliacao_chave' in pg.montarContato(contatoOk(), 'k', null, ''), false);
});

test('chave da sessão é estável por propósito e sobrevive a storage quebrado', () => {
    const dados = {};
    const storage = { getItem: k => dados[k] || null, setItem: (k, v) => { dados[k] = v; } };
    const a = pg.chaveDaSessao(storage, {}, 'cod', 'scan');
    assert.equal(pg.chaveDaSessao(storage, {}, 'cod', 'scan'), a);
    assert.notEqual(pg.chaveDaSessao(storage, {}, 'cod', 'avaliacao'), a);
    assert.notEqual(pg.chaveDaSessao(storage, {}, 'outro', 'scan'), a);
    const quebrado = { getItem() { throw new Error('bloqueado'); }, setItem() { throw new Error('bloqueado'); } };
    const memoria = {};
    const b = pg.chaveDaSessao(quebrado, memoria, 'cod', 'scan');
    assert.equal(pg.chaveDaSessao(quebrado, memoria, 'cod', 'scan'), b);
    assert.match(b, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test('rótulos: nada de promessa nem adjetivo de autopromoção na tela', () => {
    const textos = JSON.stringify(pg.ROTULOS) + fonte + html;
    for (const proibido of [/premium/i, /alto padr/i, /exclusiv/i, /luxo/i, /incr[ií]vel/i, /melhor do/i]) {
        assert.doesNotMatch(textos, proibido);
    }
});

test('privacidade e segurança na página', () => {
    assert.doesNotMatch(fonte, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/);
    assert.doesNotMatch(fonte, /userAgent|navigator\.|geolocation|localStorage|document\.cookie/);
    assert.match(fonte, /credentials: 'omit'/);
    assert.match(fonte, /referrerPolicy: 'no-referrer'/);
    assert.match(html, /name="robots" content="noindex, nofollow"/);
    // Consentimentos nascem desmarcados: nenhum "checked" no código dos campos.
    assert.doesNotMatch(fonte, /checked\s*[:=]\s*true|setAttribute\('checked'/);
});

test('cadastro: o perfil escolhido tem name="perfil" e chega ao envio', () => {
    const cadastro = fs.readFileSync('maranhao-backend/cadastro.html', 'utf8');
    const m = /<input\s+type="hidden"\s+id="perfilSelecionado"\s+name="perfil"\s*>/.exec(cadastro);
    assert.ok(m, 'input hidden perfilSelecionado precisa de name="perfil"');
    assert.match(cadastro, /Object\.fromEntries\(\s*new FormData\(form\)\.entries\(\)\s*\)/);
});
