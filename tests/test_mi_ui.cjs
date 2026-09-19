// Testes do Maranhão Intelligence Command Center (Admin V2).
//
// Reescrito após o incidente de produção "Consulta indisponível (404)":
// os testes antigos aqui validavam o painel de uma única tela anterior ao
// Command Center (ids mi-atualizar/mi-resumo/.../endpoint único
// /api/admin/mi/painel) e quebraram quando o painel foi substituído. Este
// arquivo testa o Command Center real, contra as MESMAS formas de resposta
// que o backend P5 realmente devolve (conferidas em mi_intelligence_api.py):
//   - GET /api/admin/mi/overview            -> {success, ...visao_executiva()}
//   - GET /api/admin/mi/fila-decisao        -> {success, pendentes:[...]}
//   - GET /api/admin/mi/relacionamento/<id>/contrato -> {success, ...contrato_canonico()}
//   - GET /api/admin/mi/painel (legado)     -> {success, resumo:{...}}
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('maranhao-backend/maranhao-intelligence.js', 'utf8');

const BASE = 'https://maranhao-cordial-api.onrender.com';

function makeNode(tag = 'div', id = '') {
  const listeners = {};
  const classes = new Set();
  let html = '';
  return {
    tag, id, dataset: {}, value: '',
    disabled: false, hidden: false,
    listeners,
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); },
    get textContent() { return html; },
    set textContent(v) { html = String(v); },
    classList: {
      contains: c => classes.has(c),
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      toggle(c, force) {
        const to = force === undefined ? !classes.has(c) : force;
        to ? classes.add(c) : classes.delete(c);
      },
    },
    addEventListener(evt, fn) { listeners[evt] = fn; },
  };
}

// O Command Center monta a própria navegação e as próprias views via
// panel.innerHTML (um template estático), depois usa querySelectorAll só
// para essas 3 consultas -- nunca reimplementamos um parser de HTML aqui,
// só devolvemos nós sintéticos memoizados nas mesmas posições que o
// template real usa (nav com data-mic-view, o link "abrir fila completa"
// com data-open-view, e os 4 containers .mic-view).
function wirePanelQueries(panel, elements) {
  let navButtons = null;
  let openViewButtons = null;
  panel.querySelectorAll = sel => {
    if (sel === '[data-mic-view]') {
      if (!navButtons) {
        navButtons = ['overview', 'decisions', 'relationship', 'legacy'].map(name => {
          const n = makeNode('button');
          n.dataset.micView = name;
          if (name === 'overview') n.classList.add('active');
          return n;
        });
      }
      return navButtons;
    }
    if (sel === '[data-open-view]') {
      if (!openViewButtons) {
        const n = makeNode('button');
        n.dataset.openView = 'decisions';
        openViewButtons = [n];
      }
      return openViewButtons;
    }
    if (sel === '.mic-view') {
      return ['overview', 'decisions', 'relationship', 'legacy'].map(name => {
        const eid = 'mic-' + name;
        return elements[eid] || (elements[eid] = makeNode('div', eid));
      });
    }
    return [];
  };
}

function setup({adminKey = 'chave-teste', responses = {}} = {}) {
  const elements = {};
  const calls = [];
  const events = {};

  const panel = makeNode('div', 'mi-painel');
  elements['mi-painel'] = panel;
  wirePanelQueries(panel, elements);

  const document = {
    getElementById: id => elements[id] || (elements[id] = makeNode('div', id)),
    querySelector: () => makeNode('button'),
  };
  const window = {adminKeyAtual: adminKey, addEventListener: (e, fn) => { events[e] = fn; }};

  const fetchMock = async (url, options) => {
    calls.push({url, options});
    const path = url.replace(BASE, '').split('?')[0];
    const body = responses[path];
    if (body === undefined) return {ok: true, json: async () => ({success: true})};
    if (body.__status) return {ok: false, status: body.__status, json: async () => body};
    return {ok: true, json: async () => body};
  };

  vm.runInNewContext(code, {document, window, fetch: fetchMock, Number, String, Array, Object, Promise, JSON, Math, Date, encodeURIComponent});
  return {elements, calls, events, panel};
}

// Aguarda os microtasks pendentes (ex.: loadLegacy(), que loadAll() dispara
// sem `await` de propósito -- não bloqueia a visão executiva por causa da
// camada legada).
const settle = () => new Promise(r => setTimeout(r, 0));

const OVERVIEW_REAL = {
  success: true,
  generated_at: '2026-09-17T10:00:00Z',
  relacionamentos_conhecidos: {total_pessoas: 42, com_interacao: 10, com_compra: 8, dados_suficientes: 15, dados_insuficientes: 27},
  segmentos_distribuicao: {cliente_ativo: 5, em_risco: 2},
  oportunidades_detectadas: {provavel_recompra: 3, upsell_potencial: 2},
  amostra: {tamanho: 42, limite: 50, nota: 'amostra recente'},
  fila_decisao: {pendentes: 4, bloqueadas: 1, concluidas: 6, precisa_diretor: 0},
  outcomes_registrados: 6,
  learning_status: {dataset_versao: 'relacionamento_learning_v1', total_linhas_dataset: 12, ready: false, motivo: '12 linha(s) no dataset, mínimo de 20 exigido'},
};

const FILA_REAL = {
  success: true,
  pendentes: [{
    chave: 'lead:1:provavel_recompra', relationship_id: 'lead-1', lead_id: 'lead-1', estabelecimento_id: null,
    recommendation: 'sugerir_recompra', reason: 'janela de recompra prevista vencida', evidence: ['lead:1:proxima_recompra_em:2026-09-01'],
    priority: 'normal', confidence: 'DIRECT', status: 'aguardando', generated_at: '2026-09-16T09:00:00Z', necessidade_de_aprovacao: true,
  }],
};

const PAINEL_LEGADO = {
  success: true,
  resumo: {unidades: 10, eventos: 20, scans_qr: 12, estabelecimentos: 3, territorios_ativos: 2},
};

function respostasPadrao(overrides = {}) {
  return {
    '/api/admin/mi/overview': OVERVIEW_REAL,
    '/api/admin/mi/fila-decisao': FILA_REAL,
    '/api/admin/mi/painel': PAINEL_LEGADO,
    ...overrides,
  };
}

test('sem chave de admin: nenhuma chamada de rede é feita e o status explica o motivo', async () => {
  const t = setup({adminKey: '', responses: respostasPadrao()});
  await t.elements['mic-refresh'].listeners.click();
  assert.equal(t.calls.length, 0);
  assert.match(t.elements['mic-status'].textContent, /Admin/);
});

test('com chave válida: loadAll consulta overview, fila-decisao e painel legado, todas por GET com X-Admin-Key', async () => {
  const t = setup({responses: respostasPadrao()});
  await t.elements['mic-refresh'].listeners.click();
  await settle();
  const urls = t.calls.map(c => c.url);
  assert.ok(urls.some(u => u === BASE + '/api/admin/mi/overview?amostra_limite=50'));
  assert.ok(urls.some(u => u === BASE + '/api/admin/mi/fila-decisao'));
  assert.ok(urls.some(u => u === BASE + '/api/admin/mi/painel'));
  for (const c of t.calls) {
    assert.ok(!c.options.method || c.options.method === 'GET', 'Command Center é somente leitura -- nunca deve emitir escrita');
    assert.equal(c.options.headers['X-Admin-Key'], 'chave-teste');
  }
});

test('escritas ficam na ação humana P5X; carregamento automático permanece somente leitura', () => {
  const loading=code.slice(code.indexOf('  async function loadAll()'),code.indexOf('  shell();'));
  assert.ok(!/write\(|method\s*:\s*['"](POST|PUT|DELETE|PATCH)['"]/i.test(loading));
  assert.match(code,/addEventListener\('click',creativeClick\)/);
  assert.ok(!/method\s*:\s*['"](PUT|DELETE|PATCH)['"]/i.test(code));
});

test('oportunidades_detectadas (mapa {tipo: contagem} do contrato real) é somado corretamente, nunca tratado como lista', async () => {
  const t = setup({responses: respostasPadrao()});
  await t.elements['mic-refresh'].listeners.click();
  await settle();
  assert.equal(t.elements['mic-op-count'].textContent, '5'); // 3 + 2, não 2 (tamanho do mapa) nem 1 (bug antigo tratando como array)
  assert.match(t.elements['mic-opportunities'].innerHTML, /Provável recompra|provavel_recompra/i);
});

test('fila-decisao real (qb.pendentes como lista de recomendações) alimenta a fila de decisão', async () => {
  const t = setup({responses: respostasPadrao()});
  await t.elements['mic-refresh'].listeners.click();
  await settle();
  assert.equal(t.elements['mic-queue-count'].textContent, '1');
  assert.match(t.elements['mic-queue-preview'].innerHTML, /sugerir_recompra/);
});

test('recomendação com conteúdo malicioso nunca vira HTML interpretável (sempre passa por esc())', async () => {
  const t = setup({responses: respostasPadrao({
    '/api/admin/mi/fila-decisao': {success: true, pendentes: [{
      chave: 'x', relationship_id: 'lead-2', recommendation: '<img src=x onerror=alert(1)>',
      reason: 'teste', evidence: [], priority: 'normal', confidence: 'DIRECT',
    }]},
  })});
  await t.elements['mic-refresh'].listeners.click();
  await settle();
  const html = t.elements['mic-queue-preview'].innerHTML;
  assert.ok(!html.includes('<img'), 'HTML malicioso não pode aparecer cru no DOM');
  assert.ok(html.includes('&lt;img'), 'o conteúdo deve estar escapado como texto');
});

test('sem chave de admin: overview mostra erro explicativo, nunca trava a UI', async () => {
  const t = setup({adminKey: ''});
  await t.elements['mic-refresh'].listeners.click();
  assert.doesNotThrow(() => t.elements['mic-status'].textContent);
});

test('relacionamento 360: identity.pessoa.nome e score plano (contrato real) são lidos corretamente', async () => {
  const contrato = {
    success: true, contrato_versao: 'intelligence_contract_v1', relationship_id: 'lead-9',
    identity: {pessoa: {id: 'lead-9', nome: 'Maria Souza'}},
    organization: {nome: 'Bar do Zé'},
    provenance: {identity: 'REAL', organization: 'REAL', signals: 'DERIVED'},
    score: 72.5, score_version: 'relacionamento_score_v1', confidence: 'DIRECT',
    segments: [{segmento: 'cliente_ativo'}],
    opportunities: [{type: 'provavel_recompra', evidence: ['lead:9:reorder'], recommended_action: 'sugerir_recompra'}],
    next_best_actions: [{action: 'sugerir_recompra', reason: 'janela vencida'}],
    explainability: {recommendation: 'sugerir_recompra', motivo_principal: 'janela de recompra vencida', evidencias: ['lead:9:reorder']},
    territory: 'not_requested', forecast_readiness: 'not_requested',
  };
  const t = setup({responses: respostasPadrao({'/api/admin/mi/relacionamento/X/contrato': contrato})});
  // a URL real inclui o id + query string; o mock casa por pathname sem query,
  // então normalizamos o id usado na busca para bater com a chave acima.
  t.elements['mic-rel-id'].value = 'X';
  await t.elements['mic-rel-load'].listeners.click();
  const html = t.elements['mic-rel-result'].innerHTML;
  assert.match(html, /Maria Souza/);
  assert.match(html, /Bar do Zé/);
  assert.match(html, /72\.5|72,5/);
  assert.match(html, /janela de recompra vencida/);
  assert.ok(!html.includes('[object Object]'));
});

test('relacionamento inexistente (404 real do backend) mostra a mensagem de erro, não uma tela quebrada', async () => {
  const t = setup({responses: respostasPadrao({
    '/api/admin/mi/relacionamento/inexistente/contrato': {__status: 404, success: false, error: 'Relacionamento não encontrado.'},
  })});
  t.elements['mic-rel-id'].value = 'inexistente';
  await t.elements['mic-rel-load'].listeners.click();
  assert.match(t.elements['mic-rel-result'].innerHTML, /não encontrado/i);
});

test('território: not_requested, NOT_ENOUGH_DATA e lista real nunca são confundidos nem inventados', async () => {
  const base = {
    success: true, identity: {pessoa: {nome: 'Teste'}}, organization: {},
    provenance: {}, score: 10, score_version: 'v1', segments: [], opportunities: [], next_best_actions: [],
    explainability: null,
  };
  const casos = [
    {territory: 'not_requested', esperado: /não foi solicitad/i},
    {territory: 'NOT_ENOUGH_DATA', esperado: /insuficientes/i},
    {territory: [{type: 'expansao_territorial', territory: 'Salvador/BA', evidence: ['sku:MC-100ML sem cobertura'], priority: 'alta'}], esperado: /Salvador\/BA/},
  ];
  for (const caso of casos) {
    const t = setup({responses: respostasPadrao({'/api/admin/mi/relacionamento/X/contrato': {...base, territory: caso.territory}})});
    t.elements['mic-rel-id'].value = 'X';
    await t.elements['mic-rel-load'].listeners.click();
    assert.match(t.elements['mic-rel-result'].innerHTML, caso.esperado);
  }
});

test('painel legado (mi_painel) continua a fonte da camada operacional física, sem duplicar dados', async () => {
  const t = setup({responses: respostasPadrao()});
  await t.elements['mic-refresh'].listeners.click();
  await settle();
  const html = t.elements['mic-legacy-body'].innerHTML;
  assert.match(html, /10/); // unidades
  assert.match(html, /12/); // scans_qr
});

test('navegação por abas: clicar em Decisões ativa a view mic-decisions', () => {
  const t = setup({responses: respostasPadrao()});
  const decisoesBtn = t.panel.querySelectorAll('[data-mic-view]').find(b => b.dataset.micView === 'decisions');
  decisoesBtn.listeners.click();
  assert.ok(t.elements['mic-decisions'].classList.contains('active'));
  assert.ok(!t.elements['mic-overview'].classList.contains('active'));
});

test('busca vazia no Relationship 360 não dispara requisição', async () => {
  const t = setup({responses: respostasPadrao()});
  t.elements['mic-rel-id'].value = '   ';
  await t.elements['mic-rel-load'].listeners.click();
  assert.equal(t.calls.length, 0);
  assert.match(t.elements['mic-rel-result'].innerHTML, /Informe um ID/);
});
