/* Painel "Catálogo" do ADM: conversão de preço e geração de slug (lógica
 * pura), mais garantias estáticas de que o formulário cobre o que o
 * pedido descreveu e não expõe nada indevido. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const adm = require('../maranhao-backend/catalogo-admin.js');
const fonte = fs.readFileSync('maranhao-backend/catalogo-admin.js', 'utf8');

test('centavos <-> reais, nos dois sentidos', () => {
    assert.equal(adm.centavosParaReais(5990), '59,90');
    assert.equal(adm.centavosParaReais(null), '');
    assert.equal(adm.reaisParaCentavos('59,90'), 5990);
    assert.equal(adm.reaisParaCentavos('1.234,50'), 123450);
    assert.equal(adm.reaisParaCentavos(''), null);
    assert.equal(adm.reaisParaCentavos('  '), null);
});

test('preço inválido não é silenciosamente aceito como zero', () => {
    assert.equal(adm.reaisParaCentavos('abc'), undefined);
    assert.equal(adm.reaisParaCentavos('-5'), undefined);
});

test('slug sugerido a partir do nome: minúsculo, sem acento, hífens', () => {
    assert.equal(adm.slugSugerido('Vela de Alecrim e Cajá'), 'vela-de-alecrim-e-caja');
    assert.equal(adm.slugSugerido('  Sabonete!!  '), 'sabonete');
});

test('o formulário cobre os campos pedidos: nome, categoria, descrições, preço, unidade, quantidade mínima e múltiplo, modalidade, status, destaque, ordem e a ficha técnica', () => {
    for (const campo of ['nome', 'categoria', 'descricao_curta', 'descricao_completa', 'preco_reais',
        'unidade_venda', 'quantidade_minima', 'multiplo_compra', 'modalidade_compra', 'disponibilidade',
        'status', 'destaque_home', 'ordem_exibicao', 'volume', 'peso', 'composicao', 'cuidados']) {
        assert.match(fonte, new RegExp('name="' + campo + '"'), campo);
    }
});

test('upload de mídia pede arquivo, tipo, texto alternativo e capa — sem exigir nada da bebida em outra categoria', () => {
    assert.match(fonte, /name="arquivo"/);
    assert.match(fonte, /name="alt_text"/);
    assert.match(fonte, /name="capa"/);
    assert.doesNotMatch(fonte, /volume.*required|peso.*required|composicao.*required/is);
});

test('id/criado_em nunca são enviados, e slug só é definido na criação (nunca no PATCH de edição)', () => {
    assert.doesNotMatch(fonte, /corpo\.(id|criado_em)\s*=/);
    const criacao = fonte.slice(fonte.indexOf('} else {', fonte.indexOf('function salvar')));
    assert.match(criacao, /corpo\.slug\s*=/, 'slug é definido no ramo de criação');
    const edicao = fonte.slice(fonte.indexOf('if (editandoId)'), fonte.indexOf('} else {'));
    assert.doesNotMatch(edicao, /corpo\.slug\s*=/, 'slug não pode ser definido no ramo de edição');
});

test('sem inserção de HTML cru vindo de dado do produto (nome/descrição passam por esc)', () => {
    assert.match(fonte, /function esc\(/);
    assert.match(fonte, /esc\(p\.nome\)/);
});

test('painel exige autenticação do ADM antes de qualquer chamada', () => {
    assert.match(fonte, /adminKeyAtual/);
    assert.match(fonte, /X-Admin-Key/);
});
