// Executa os scripts reais em VM com DOM/janelas/fetch simulados; nenhuma rede.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const scripts = file => [...fs.readFileSync(path.join(root, file), 'utf8').matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(x => x[1]);
// conectarGmailP0 foi extraído de admin.html para gmail-admin.js (ETAPA 4.5); lido direto do arquivo, não mais de um <script> inline.
const admin = fs.readFileSync(path.join(root, 'maranhao-backend/gmail-admin.js'), 'utf8');
const bridge = scripts('maranhao-backend/gmail-oauth.html')[0];
const api = 'https://maranhao-cordial-api.onrender.com';
const origemPainel = 'https://maranhaocordial.com.br';

function painel(chave = 'chave-sintetica', popupBloqueado = false) {
    const listeners = {};
    const mensagens = [];
    const status = {textContent: ''};
    const popup = {postMessage: (...a) => mensagens.push(a)};
    const window = {
        adminKeyAtual: chave,
        open: (...a) => {window.abertura = a; return popupBloqueado ? null : popup;},
        addEventListener: (tipo, fn) => {listeners[tipo] = fn;},
        removeEventListener: tipo => {delete listeners[tipo];}
    };
    const ctx = vm.createContext({window, document: {getElementById: () => status, querySelector: () => null}, setTimeout: () => 1, clearTimeout: () => {}});
    vm.runInContext(admin, ctx);
    ctx.conectarGmailP0();
    return {window, popup, listeners, mensagens, status};
}

function janela({opener = true, url = 'https://accounts.google.com/o/oauth2/auth?state=sintetico', sucesso = true} = {}) {
    const listeners = {};
    const chamadas = [];
    const status = {textContent: ''};
    const painel = {postMessage: () => {}};
    const window = {
        opener: opener ? painel : null,
        location: {origin: api, replace: u => {window.destino = u;}},
        addEventListener: (tipo, fn) => {listeners[tipo] = fn;}
    };
    const ctx = vm.createContext({window, URL, document: {getElementById: () => status}, fetch: async (...a) => {
        chamadas.push(a);
        return {ok: sucesso, json: async () => ({success: sucesso, authorization_url: url, error: sucesso ? undefined : 'Não autorizado.'})};
    }});
    vm.runInContext(bridge, ctx);
    return {window, painel, listeners, chamadas, status};
}

test('sintaxe de todos os scripts inline do painel e da janela OAuth', () => {
    for (const file of ['maranhao-backend/admin.html', 'maranhao-backend/gmail-oauth.html']) {
        for (const s of scripts(file)) new vm.Script(s, {filename: file});
    }
    new vm.Script(admin, {filename: 'maranhao-backend/gmail-admin.js'});
});

test('painel não inicia OAuth sem autenticação ou com popup bloqueado', () => {
    const a = painel('');
    assert.equal(a.window.abertura, undefined);
    assert.match(a.status.textContent, /chave administrativa/);
    const b = painel('sintetico', true);
    assert.match(b.status.textContent, /Permita/);
    assert.equal(b.listeners.message, undefined);
});

test('painel abre o Gmail institucional direto, sem handshake de postMessage nem chave exposta na URL', () => {
    // O botão da Central deixou de abrir um popup de autorização com troca
    // de postMessage (conectarGmailP0 hoje só abre a caixa institucional);
    // a reconexão OAuth propriamente dita continua isolada na bridge
    // gmail-oauth.html, coberta pelos testes de janela() abaixo.
    const p = painel();
    assert.equal(p.listeners.message, undefined);
    assert.equal(p.mensagens.length, 0);
    assert.equal(p.window.abertura[0], 'https://mail.google.com/mail/u/0/');
    assert.ok(!p.window.abertura[0].includes('chave-sintetica'));
});

test('janela ignora mensagens de origem ou remetente não autorizado', async () => {
    const p = janela();
    const data = {tipo: 'gmail-p0-autorizar', chave: 'sintetica'};
    await p.listeners.message({origin: 'https://malicioso.example', source: p.painel, data});
    await p.listeners.message({origin: origemPainel, source: {}, data});
    assert.equal(p.chamadas.length, 0);
});

test('janela usa POST autenticado com sessão first-party e vai ao Google uma vez', async () => {
    const p = janela();
    const evento = {origin: origemPainel, source: p.painel, data: {tipo: 'gmail-p0-autorizar', chave: 'sintetica'}};
    await p.listeners.message(evento);
    await p.listeners.message(evento);
    assert.equal(p.chamadas.length, 1);
    assert.equal(p.chamadas[0][0], '/api/gmail/conectar');
    assert.equal(p.chamadas[0][1].method, 'POST');
    assert.equal(p.chamadas[0][1].credentials, 'same-origin');
    assert.equal(p.chamadas[0][1].headers['X-Admin-Key'], 'sintetica');
    assert.equal(new URL(p.window.destino).origin, 'https://accounts.google.com');
    assert.equal(p.window.opener, null);
    assert.ok(!p.window.destino.includes('sintetica'));
});

test('janela não navega com falha HTTP, destino estranho ou abertura direta', async () => {
    for (const config of [{sucesso: false}, {url: 'https://malicioso.example/'}]) {
        const p = janela(config);
        await p.listeners.message({origin: origemPainel, source: p.painel, data: {tipo: 'gmail-p0-autorizar', chave: 'sintetica'}});
        assert.equal(p.window.destino, undefined);
        assert.ok(p.status.textContent);
    }
    const p = janela({opener: false});
    assert.equal(p.listeners.message, undefined);
    assert.match(p.status.textContent, /painel administrativo/);
});
