/* Calendário Empresarial (seção 2 da ordem Central Empresarial). Cobre
   especificamente a integração nova: cards de Operação Viva distintos e
   clicáveis, abrindo o workspace via window.abrirOperacaoViva -- sem
   duplicar nenhum calendário/fonte de verdade. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const code = fs.readFileSync('maranhao-backend/calendario-empresarial.js', 'utf8');

function node(tag = 'div') {
  const n = {
    tag, children: [], className: '', dataset: {}, _listeners: {}, _text: '', _html: '',
    get classList() {
      return {contains: c => (n.className || '').split(/\s+/).includes(c)};
    },
    get textContent() { return n._text; }, set textContent(v) { n._text = v; },
    get innerHTML() { return n._html; }, set innerHTML(v) { n._html = v; },
    append(...xs) { n.children.push(...xs); },
    addEventListener(k, fn) { n._listeners[k] = fn; },
    closest(sel) {
      const cls = sel.replace(/^\./, '');
      if ((n.className || '').split(/\s+/).includes(cls)) return n;
      return null;
    },
  };
  return n;
}

function buildDocument(root) {
  const listeners = {};
  const registry = {'calendario-empresarial': root.raiz, 'ce-status': root.status, 'ce-corpo': root.corpo};
  return {
    getElementById: id => registry[id] || null,
    addEventListener(k, fn) { listeners[k] = listeners[k] || []; listeners[k].push(fn); },
    fire(evt, payload) { (listeners[evt] || []).forEach(fn => fn(payload)); },
  };
}

function setup(respostaFetch) {
  const raiz = node('div'); raiz.id = 'calendario-empresarial';
  const status = node('p'); status.id = 'ce-status';
  const corpo = node('div'); corpo.id = 'ce-corpo';
  const document = buildDocument({raiz, status, corpo});
  const window = {adminKeyAtual: 'chave-teste'};
  const fetchMock = async () => ({ok: true, json: async () => respostaFetch});
  const sandbox = {document, window, fetch: fetchMock, console};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return {document, window, sandbox, corpo};
}

const RESUMO_VAZIO = {total_hoje: 0, total_proximas: 0, total_aguardando: 0, total_precisa_diretor: 0};

test('card de operação viva é visualmente distinto (classe ce-evento--operacao) e traz dados reais', async () => {
  const operacao = {
    tipo_decisao: 'operacao_viva', operacao_id: 'op-42', titulo: 'Softdrinks Tech',
    prioridade: 'alta', local: 'AGUARDANDO DADOS', responsavel: 'diretor',
    data_inicio: '2026-10-15', data_fim: '2026-10-16', estado_operacao: 'confirmada',
  };
  const {sandbox, corpo} = setup({success: true, resumo: RESUMO_VAZIO, colunas: {hoje: [], proximas: [operacao], aguardando: [], concluidas: [], bloqueadas: [], precisa_diretor: []}, inteligencia_de_publico: {}});
  await sandbox.window.carregarCalendarioEmpresarial();
  assert.match(corpo.innerHTML, /ce-evento--operacao/);
  assert.match(corpo.innerHTML, /data-operacao-id="op-42"/);
  assert.match(corpo.innerHTML, /Softdrinks Tech/);
});

test('atividade que não é operação viva usa o card padrão, sem data-operacao-id', async () => {
  const atividade = {tipo_decisao: 'followup_devido', prioridade: 'normal', inferencia: 'follow-up vencido', executar_em: null};
  const {sandbox, corpo} = setup({success: true, resumo: RESUMO_VAZIO, colunas: {hoje: [atividade], proximas: [], aguardando: [], concluidas: [], bloqueadas: [], precisa_diretor: []}, inteligencia_de_publico: {}});
  await sandbox.window.carregarCalendarioEmpresarial();
  assert.doesNotMatch(corpo.innerHTML, /ce-evento--operacao/);
  assert.doesNotMatch(corpo.innerHTML, /data-operacao-id/);
});

test('clique num card de operação chama window.abrirOperacaoViva com o id correto', async () => {
  const {document, window} = setup({success: true, resumo: RESUMO_VAZIO, colunas: {hoje: [], proximas: [], aguardando: [], concluidas: [], bloqueadas: [], precisa_diretor: []}, inteligencia_de_publico: {}});
  let recebido = null;
  window.abrirOperacaoViva = id => { recebido = id; };
  const fakeCard = {className: 'ce-evento ce-evento--operacao', dataset: {operacaoId: 'op-7'}, closest(sel) { return sel === '.ce-evento--operacao' ? this : null; }};
  document.fire('click', {target: {closest: sel => sel === '.ce-evento--operacao' ? fakeCard : null, id: undefined}});
  assert.equal(recebido, 'op-7');
});
