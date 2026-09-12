const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/app-shell.js','utf8');
const css=fs.readFileSync('maranhao-backend/app-shell.css','utf8');

function classesOf(n) { return new Set((n.className || '').split(/\s+/).filter(Boolean)); }
function setClasses(n, set) { n.className = [...set].join(' '); }

function node({tag='div', classes=[], dataset={}, text=''}={}) {
  const n = {
    tag, textContent: text, children: [], parentNode: null, dataset: {...dataset},
    className: classes.join(' '), _listeners: {},
    get classList() {
      return {
        add: c => { const s = classesOf(n); s.add(c); setClasses(n, s); },
        remove: c => { const s = classesOf(n); s.delete(c); setClasses(n, s); },
        toggle: (c, v) => { const s = classesOf(n); const to = v === undefined ? !s.has(c) : v; to ? s.add(c) : s.delete(c); setClasses(n, s); },
        contains: c => classesOf(n).has(c),
      };
    },
    append(...xs) { for (const x of xs) { x.parentNode = n; n.children.push(x); } },
    insertBefore(x) { x.parentNode = n; n.children.unshift(x); },
    querySelectorAll(sel) { return collect(n, sel); },
    querySelector(sel) { return collect(n, sel)[0] || null; },
    addEventListener(k, fn) { n._listeners[k] = fn; },
    click() { n._listeners.click && n._listeners.click(); },
    setAttribute(k, v) { n[k] = v; },
  };
  return n;
}

function matchesSelector(n, sel) {
  const m = sel.match(/^\.([a-zA-Z0-9_-]+)(?:\[data-([a-zA-Z-]+)="([^"]+)"\])?$/);
  if (!m) return false;
  const [, cls, dataKey, dataVal] = m;
  if (!classesOf(n).has(cls)) return false;
  if (dataKey) {
    const key = dataKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    if ((n.dataset || {})[key] !== dataVal) return false;
  }
  return true;
}

function collect(root, sel) {
  const out = [];
  (function walk(x) {
    for (const c of x.children) {
      if (matchesSelector(c, sel)) out.push(c);
      walk(c);
    }
  })(root);
  return out;
}

function tabButton(destino, texto, ativo=false) {
  return node({tag:'button', classes: ativo ? ['admin-tab','active'] : ['admin-tab'], dataset: {tab: destino}, text: texto});
}

function grupo(titulo, tabs) {
  const g = node({classes: ['app-shell-grupo']});
  g.append(node({classes: ['app-shell-grupo-titulo'], text: titulo}));
  for (const t of tabs) g.append(t);
  return g;
}

function montarNav() {
  const nav = node({tag: 'nav', dataset: {}});
  nav.id = 'adminTabs';
  const inicio = tabButton('visao-geral', 'Início');
  const ia = tabButton('ia-empresarial', 'IA', true);
  nav.append(grupo('Visão Geral', [inicio, ia]));
  nav.append(grupo('Comercial', [tabButton('crm', 'Contatos')]));
  nav.append(grupo('Maranhão Intelligence', [tabButton('maranhao-intelligence', 'Maranhão Intelligence')]));
  nav.append(grupo('Território', [tabButton('inteligencia-territorial', 'Inteligência Territorial')]));
  nav.append(grupo('Operação', [tabButton('empresa', 'Empresa')]));
  nav.append(grupo('Governança', [tabButton('governanca', 'Aprovações')]));
  return {nav, inicio, ia};
}

function setup() {
  const {nav, inicio, ia} = montarNav();
  const body = node({tag: 'body'});
  body.append(nav);
  const registry = {adminTabs: nav};
  const document = {
    body,
    getElementById: id => registry[id] || null,
    querySelector: sel => body.querySelector(sel),
    createElement: tag => node({tag}),
  };
  vm.runInNewContext(code, {document, MutationObserver: class { constructor(cb){ this.cb=cb; } observe(){} }});
  const sidebar = body.children.find(c => c.classList.contains('app-sidebar'));
  return {nav, inicio, ia, body, sidebar};
}

test('sidebar renderiza os 6 grupos esperados',()=>{
  const {sidebar} = setup();
  const grupos = sidebar.children.filter(c => c.classList.contains('app-sidebar-grupo'));
  assert.equal(grupos.length, 6);
  const titulos = grupos.map(g => g.children[0].textContent);
  assert.deepEqual(titulos, ['Visão Geral','Comercial','Maranhão Intelligence','Território','Operação','Governança']);
});

test('item ativo da sidebar acompanha a aba realmente ativa (IA, por padrão)',()=>{
  const {sidebar} = setup();
  const itens = sidebar.querySelectorAll('.app-sidebar-item');
  const ativo = itens.find(i => i.classList.contains('active'));
  assert.equal(ativo.dataset.tab, 'ia-empresarial');
});

test('clique no item da sidebar aciona o .admin-tab legado correspondente (compatibilidade)',()=>{
  const {sidebar, inicio} = setup();
  let clicouNoOriginal = false;
  inicio.addEventListener('click', () => { clicouNoOriginal = true; });
  const itemInicio = sidebar.querySelectorAll('.app-sidebar-item').find(i => i.dataset.tab === 'visao-geral');
  itemInicio.click();
  assert.ok(clicouNoOriginal, 'o clique deveria ter disparado o handler legado do .admin-tab, não uma lógica nova');
});

test('handlers legados continuam a única fonte de verdade: sidebar não reimplementa troca de painel',()=>{
  assert.ok(!code.includes('tab-panel'), 'app-shell.js não deveria manipular .tab-panel diretamente -- isso é do handler legado');
});

test('nenhuma chamada de rede é adicionada pela sidebar',()=>{
  assert.ok(!/fetch\s*\(/.test(code));
});

test('login/gating não é referenciado pelo novo código da sidebar',()=>{
  assert.ok(!code.includes('loginPanel'));
  assert.ok(!code.includes('adminContent'));
  assert.ok(!code.includes('adminKeyAtual'));
});

test('sem duplicação funcional: a fileira legada é ocultada via CSS quando a sidebar está ativa, nunca removida',()=>{
  const {body} = setup();
  assert.ok(body.classList.contains('app-shell-sidebar-ativa'));
  assert.match(css, /body\.app-shell-sidebar-ativa \.app-shell-nav\s*\{\s*display:\s*none;/);
});

test('sidebar some fora do breakpoint desktop largo (mobile fica para a 4.8)',()=>{
  assert.match(css, /\.app-sidebar\s*\{\s*display:\s*none;\s*\}/);
  assert.match(css, /@media \(min-width: 1024px\)/);
});

test('z-index da sidebar é moderado e documentado, não um valor arbitrário alto',()=>{
  const m = css.match(/\.app-sidebar\s*\{[^}]*z-index:\s*(\d+)/s);
  assert.ok(m);
  assert.ok(Number(m[1]) < 100);
});
