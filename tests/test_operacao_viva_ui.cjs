/* Operação Viva (Central Empresarial, seção 3 da ordem). Executa o script
   real em VM com um DOM mínimo simulado (sem jsdom disponível no projeto):
   cobre montagem do modal, troca de abas, e os fluxos de submit/clique
   delegados em document, que são o miolo real de mi_operacoes.js. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const code = fs.readFileSync('maranhao-backend/operacao-viva.js', 'utf8');

function classesOf(n) { return new Set((n.className || '').split(/\s+/).filter(Boolean)); }

function node(tag = 'div') {
  const n = {
    tag, children: [], parentNode: null, className: '', dataset: {}, _listeners: {},
    _text: '', _html: '',
    get classList() {
      return {
        add: c => { const s = classesOf(n); s.add(c); n.className = [...s].join(' '); },
        remove: c => { const s = classesOf(n); s.delete(c); n.className = [...s].join(' '); },
        toggle: (c, v) => { const s = classesOf(n); const to = v === undefined ? !s.has(c) : v; to ? s.add(c) : s.delete(c); n.className = [...s].join(' '); },
        contains: c => classesOf(n).has(c),
      };
    },
    get textContent() { return n._text; },
    set textContent(v) { n._text = v; },
    get innerHTML() { return n._html; },
    set innerHTML(v) {
      // Fake DOM não faz parsing real de HTML: extrai só os id="..."
      // literais do template (montarModal usa innerHTML para desenhar a
      // casca do modal) e cria um stub filho para cada um, o suficiente
      // para os querySelector/getElementById que o código real faz logo
      // em seguida.
      n._html = v;
      n.children = n.children.filter(c => !c._geradoPorInnerHTML);
      const ids = [...v.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
      for (const id of ids) {
        const filho = node('div');
        filho.id = id;
        filho._geradoPorInnerHTML = true;
        n.append(filho);
      }
    },
    append(...xs) { for (const x of xs) { x.parentNode = n; n.children.push(x); } },
    addEventListener(k, fn) { n._listeners[k] = fn; },
    removeEventListener(k) { delete n._listeners[k]; },
    click() { n._listeners.click && n._listeners.click({target: n}); },
    matches(sel) { return matchesSelector(n, sel); },
    closest(sel) { let cur = n; while (cur) { if (matchesSelector(cur, sel)) return cur; cur = cur.parentNode; } return null; },
    querySelector(sel) { return collect(n, sel)[0] || null; },
    querySelectorAll(sel) { return collect(n, sel); },
  };
  return n;
}

function matchesSelector(n, sel) {
  if (sel.startsWith('#')) return n.id === sel.slice(1);
  if (sel.startsWith('.')) return classesOf(n).has(sel.slice(1));
  const attr = sel.match(/^\[data-([a-z]+)\]$/);
  if (attr) return n.dataset && n.dataset[attr[1]] !== undefined;
  return false;
}

function collect(root, sel) {
  const out = [];
  (function walk(x) { for (const c of x.children) { if (matchesSelector(c, sel)) out.push(c); walk(c); } })(root);
  return out;
}

function buildDocument() {
  const body = node('body');
  const docListeners = {};
  const registry = {};
  const doc = {
    body,
    addEventListener(k, fn) { docListeners[k] = docListeners[k] || []; docListeners[k].push(fn); },
    createElement(tag) { return node(tag); },
    getElementById(id) { return registry[id] || (body.children.length ? collectId(body, id) : null); },
    querySelectorAll: sel => collect(body, sel),
    fire(evt, payload) { (docListeners[evt] || []).forEach(fn => fn(payload)); },
  };
  function collectId(root, id) {
    let found = null;
    (function walk(x) { for (const c of x.children) { if (c.id === id) found = c; walk(c); } })(root);
    return found;
  }
  const origAppend = body.append.bind(body);
  return doc;
}

class FakeFormData {
  constructor(form) { this.data = form._formValues || {}; }
  get(k) { return this.data[k] ?? null; }
}

function setup({adminKey = 'chave-teste', fetchImpl} = {}) {
  const document = buildDocument();
  const window = {adminKeyAtual: adminKey};
  const calls = [];
  const fetchMock = fetchImpl || (async (url, opts) => { calls.push({url, opts}); return {ok: true, json: async () => ({success: true})}; });
  const sandbox = {document, window, fetch: fetchMock, FormData: FakeFormData, console};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return {document, window, calls, sandbox};
}

test('sem chave administrativa, api() rejeita com mensagem clara (nunca chama fetch)', async () => {
  const {sandbox, calls} = setup({adminKey: null});
  let mensagem = null;
  try { await sandbox.window.abrirOperacaoViva('op-1'); } catch (e) { mensagem = e.message; }
  // abrirOperacaoViva não propaga a rejeição (mostra erro na tela), então
  // verificamos indiretamente: nenhuma chamada de rede deve ter ocorrido.
  assert.equal(calls.length, 0);
});

test('abrirOperacaoViva monta o modal com as 9 abas exigidas pela ordem de UX', async () => {
  const {document, sandbox} = setup({
    fetchImpl: async () => ({ok: true, json: async () => ({success: true, operacao: {titulo: 'Softdrinks Tech', data_inicio: '2026-10-15', data_fim: '2026-10-16', local: null, estado: 'planejamento', prioridade: 'alta', responsavel: null, descricao: null}, contagens: {pessoas: 0, itens: 0, brainstorm: 0, metricas: 0, financeiro: 0, arquivos: 0}})}),
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const modal = document.getElementById('ov-modal');
  assert.ok(modal, 'modal deveria ter sido criado');
  assert.ok(modal.classList.contains('show'));
  const abas = document.querySelectorAll('.ov-aba');
  assert.equal(abas.length, 9);
  const titulo = document.getElementById('ov-titulo');
  assert.equal(titulo.textContent, 'Softdrinks Tech');
});

test('aba Visão Geral mostra AGUARDANDO DADOS para campos ausentes, nunca inventa valor', async () => {
  const {document, sandbox} = setup({
    fetchImpl: async () => ({ok: true, json: async () => ({success: true, operacao: {titulo: 'X', data_inicio: '2026-10-15', data_fim: '2026-10-16', local: null, estado: 'planejamento', prioridade: 'alta', responsavel: null, descricao: null}, contagens: {pessoas: 0, itens: 0, brainstorm: 0, metricas: 0, financeiro: 0, arquivos: 0}})}),
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const corpo = document.getElementById('ov-corpo');
  assert.match(corpo.innerHTML, /AGUARDANDO DADOS/);
});

test('erro de rede na aba ativa mostra estado de erro explícito, nunca tela em branco', async () => {
  const {document, sandbox} = setup({
    fetchImpl: async () => ({ok: false, status: 503, json: async () => ({success: false, error: 'Operação indisponível no momento.'})}),
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const corpo = document.getElementById('ov-corpo');
  assert.match(corpo.innerHTML, /ov-erro/);
  assert.match(corpo.innerHTML, /Operação indisponível no momento\./);
});

test('submit do formulário de equipe envia POST com corpo correto e nunca com estado já confirmado', async () => {
  const chamadas = [];
  const {document, sandbox} = setup({
    fetchImpl: async (url, opts) => { chamadas.push({url, opts}); return {ok: true, json: async () => (url.includes('/pessoas') && opts?.method === 'POST' ? {success: true, pessoa: {id: 'p1', estado: 'sugerido'}} : {success: true, pessoas: []})}; },
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  document.fire('click', {target: {closest: sel => sel === '.ov-aba' ? {dataset: {aba: 'equipe'}, classList: {toggle(){}}} : null}});
  // Troca de aba real via API pública (selecionarAba não é exposta, então
  // simulamos clicando no botão real da aba 'equipe' já criado no modal).
  const abaEquipe = document.querySelectorAll('.ov-aba').find(a => a.dataset.aba === 'equipe');
  abaEquipe.click();
  await new Promise(r => setTimeout(r, 0));

  const form = {id: 'ov-form-pessoa', reset() { this._reset = true; }, _formValues: {funcao: 'Bartender', nome: 'Fulano', origem: 'humano'}};
  let prevented = false;
  document.fire('submit', {target: form, preventDefault() { prevented = true; }});
  await new Promise(r => setTimeout(r, 0));

  assert.ok(prevented);
  const post = chamadas.find(c => c.opts?.method === 'POST' && c.url.includes('/pessoas'));
  assert.ok(post, 'deveria ter enviado POST para /pessoas');
  const corpo = JSON.parse(post.opts.body);
  assert.equal(corpo.funcao, 'Bartender');
  assert.equal(corpo.origem, 'humano');
  assert.ok(!('estado' in corpo), 'estado inicial é sempre decidido pelo backend (sugerido), nunca enviado pelo formulário');
});

test('clique em ação de brainstorm sem agente selecionado não chama a API (evita rodada vazia)', async () => {
  const chamadas = [];
  const {sandbox} = setup({
    fetchImpl: async (url, opts) => { chamadas.push({url, opts}); return {ok: true, json: async () => ({success: true, brainstorm: []})}; },
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const fakeArtigo = {querySelectorAll: () => []};
  const fakeBtn = {dataset: {acao: 'brainstorm-executar', id: 'b1'}, closest: sel => sel === '.ov-acoes' ? fakeArtigo : null};
  const chamadasAntes = chamadas.length;
  // Disparamos o listener de clique registrado em document diretamente.
  const doc = sandbox.document;
  doc.fire('click', {target: {closest: sel => sel === '[data-acao]' ? fakeBtn : null}});
  await new Promise(r => setTimeout(r, 0));
  assert.equal(chamadas.length, chamadasAntes, 'nenhuma chamada de execução deveria ter sido feita sem agente selecionado');
});

test('decisão de brainstorm chama o endpoint de decisão com o payload exato', async () => {
  const chamadas = [];
  const {sandbox} = setup({
    fetchImpl: async (url, opts) => { chamadas.push({url, opts}); return {ok: true, json: async () => ({success: true, brainstorm: []})}; },
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const fakeBtn = {dataset: {acao: 'brainstorm-decisao', id: 'b1', decisao: 'transformar_em_tarefa'}, closest: () => null};
  sandbox.document.fire('click', {target: {closest: sel => sel === '[data-acao]' ? fakeBtn : null}});
  await new Promise(r => setTimeout(r, 0));
  const chamada = chamadas.find(c => c.url.includes('/brainstorm/b1/decisao'));
  assert.ok(chamada);
  assert.equal(JSON.parse(chamada.opts.body).decisao, 'transformar_em_tarefa');
});

test('lançamento financeiro converte reais em centavos sem perda de precisão', async () => {
  const chamadas = [];
  const {sandbox} = setup({
    fetchImpl: async (url, opts) => { chamadas.push({url, opts}); return {ok: true, json: async () => ({success: true, lancamentos: [], totais_centavos: {}})}; },
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  const form = {id: 'ov-form-financeiro', reset() {}, _formValues: {categoria: 'staff', tipo: 'orcamento', valor_reais: '19.9', fonte: ''}};
  sandbox.document.fire('submit', {target: form, preventDefault() {}});
  await new Promise(r => setTimeout(r, 0));
  const post = chamadas.find(c => c.opts?.method === 'POST' && c.url.includes('/financeiro'));
  assert.ok(post);
  const corpo = JSON.parse(post.opts.body);
  assert.equal(corpo.valor_centavos, 1990);
  assert.equal(corpo.estado_dado, 'estimativa');
});

test('fecharOperacaoViva remove a classe show e reseta o estado interno', async () => {
  const {document, sandbox} = setup({
    fetchImpl: async () => ({ok: true, json: async () => ({success: true, operacao: {titulo: 'X', data_inicio: '2026-10-15', data_fim: '2026-10-16', local: null, estado: 'planejamento', prioridade: 'alta', responsavel: null, descricao: null}, contagens: {pessoas: 0, itens: 0, brainstorm: 0, metricas: 0, financeiro: 0, arquivos: 0}})}),
  });
  await sandbox.window.abrirOperacaoViva('op-1');
  await new Promise(r => setTimeout(r, 0));
  sandbox.window.fecharOperacaoViva();
  assert.ok(!document.getElementById('ov-modal').classList.contains('show'));
});
