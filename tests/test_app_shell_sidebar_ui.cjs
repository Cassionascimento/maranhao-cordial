const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/app-shell.js','utf8');
const css=fs.readFileSync('maranhao-backend/app-shell.css','utf8');

function classesOf(n) { return new Set((n.className || '').split(/\s+/).filter(Boolean)); }
function setClasses(n, set) { n.className = [...set].join(' '); }

function node({tag='div', classes=[], dataset={}, text=''}={}) {
  const n = {
    tag, textContent: text, children: [], parentNode: null, dataset: {...dataset},
    className: classes.join(' '), _listeners: {}, innerHTML: '',
    get classList() {
      return {
        add: c => { const s = classesOf(n); s.add(c); setClasses(n, s); },
        remove: c => { const s = classesOf(n); s.delete(c); setClasses(n, s); },
        toggle: (c, v) => { const s = classesOf(n); const to = v === undefined ? !s.has(c) : v; to ? s.add(c) : s.delete(c); setClasses(n, s); },
        contains: c => classesOf(n).has(c),
      };
    },
    get lastElementChild() { return n.children.length ? n.children[n.children.length - 1] : null; },
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
  // Cobre '.classe', '.classe[data-x="v"]' e o atributo puro '[data-x="v"]'
  // (usado por app-shell.js para localizar o grupo "Operação" do calendário).
  const comClasse = sel.match(/^\.([a-zA-Z0-9_-]+)(?:\[data-([a-zA-Z-]+)="([^"]+)"\])?$/);
  const soAtributo = sel.match(/^\[data-([a-zA-Z-]+)="([^"]+)"\]$/);
  if (comClasse) {
    const [, cls, dataKey, dataVal] = comClasse;
    if (!classesOf(n).has(cls)) return false;
    if (dataKey) {
      const key = dataKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      if ((n.dataset || {})[key] !== dataVal) return false;
    }
    return true;
  }
  if (soAtributo) {
    const [, dataKey, dataVal] = soAtributo;
    const key = dataKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    return (n.dataset || {})[key] === dataVal;
  }
  return false;
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

function tabButton(destino, texto, ativo=false, grupo=null) {
  const dataset = {tab: destino};
  if (grupo) dataset.grupo = grupo;
  return node({tag:'button', classes: ativo ? ['admin-tab','active'] : ['admin-tab'], dataset, text: texto});
}

function grupo(titulo, tabs, dataGrupo=null) {
  const g = node({classes: ['app-shell-grupo'], dataset: dataGrupo ? {appGrupo: dataGrupo} : {}});
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
  // "Operação" precisa existir com data-app-grupo="operacao" -- é onde
  // app-shell.js insere a nova aba "Calendário" dinamicamente.
  nav.append(grupo('Operação', [tabButton('empresa', 'Empresa', false, 'operacao')], 'operacao'));
  nav.append(grupo('Governança', [tabButton('governanca', 'Aprovações')]));
  return {nav, inicio, ia};
}

function setup({autenticado=false}={}) {
  const {nav, inicio, ia} = montarNav();
  const body = node({tag: 'body'});
  const head = node({tag: 'head'});
  const content = node({tag: 'section', classes: ['admin-content']});
  content.id = 'adminContent';
  if (autenticado) content.classList.add('show');
  body.append(nav);
  body.append(content);
  const registry = {adminTabs: nav, adminContent: content};
  const document = {
    body,
    head,
    getElementById: id => registry[id] || null,
    querySelector: sel => body.querySelector(sel) || (matchesSelector(content, sel) ? content : null),
    createElement: tag => node({tag}),
  };
  vm.runInNewContext(code, {document, window: {}, MutationObserver: class { constructor(cb){ this.cb=cb; } observe(){} }});
  const sidebar = body.children.find(c => c.classList.contains('app-sidebar'));
  return {nav, inicio, ia, body, content, sidebar};
}

test('sidebar renderiza os grupos existentes, incluindo a aba Calendário injetada em Operação',()=>{
  const {sidebar, nav} = setup();
  const grupos = sidebar.children.filter(c => c.classList.contains('app-sidebar-grupo'));
  assert.equal(grupos.length, 6);
  const titulos = grupos.map(g => g.children[0].textContent);
  assert.deepEqual(titulos, ['Visão Geral','Comercial','Maranhão Intelligence','Território','Operação','Governança']);
  // app-shell.js injeta a aba Calendário dentro do grupo "Operação" (real).
  assert.ok(nav.querySelector('[data-tab="calendario"]'), 'aba Calendário deveria ter sido criada em nav');
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

test('nenhuma chamada de rede é adicionada pela sidebar',()=>{
  assert.ok(!/fetch\s*\(/.test(code));
});

test('gating de login É intencional: o shell só monta a sidebar quando #adminTabs e #adminContent existem',()=>{
  // app-shell.js exige AMBOS (nav e content) antes de construir a
  // sidebar -- é essa checagem que impede navegação operacional de
  // aparecer numa página que ainda não montou a Central autenticada.
  assert.match(code, /getElementById\('adminTabs'\).*getElementById\('adminContent'\)/);
  assert.match(code, /if\(!nav\|\|!content\)return/);
});

test('sidebar-ativa (item 1.A da ordem de UX): só fica ativa depois do login, nunca antes',()=>{
  const antes = setup({autenticado: false});
  assert.ok(!antes.body.classList.contains('app-shell-sidebar-ativa'),
    'antes da autenticação (#adminContent sem .show) a sidebar não pode estar ativa');
  const depois = setup({autenticado: true});
  assert.ok(depois.body.classList.contains('app-shell-sidebar-ativa'),
    'depois da autenticação (#adminContent com .show) a sidebar deve ficar ativa');
});

test('CSS: a fileira legada só some quando a sidebar está de fato ativa (nunca incondicionalmente)',()=>{
  // Regressão real encontrada nesta ordem: a regra antiga escondia/mostrava
  // a sidebar de forma incondicional dentro do @media, ignorando a classe
  // app-shell-sidebar-ativa -- por isso a navegação aparecia antes do login
  // em telas largas. As três regras abaixo precisam estar condicionadas a
  // body.app-shell-sidebar-ativa, nunca soltas dentro do @media.
  assert.match(css, /body\.app-shell-sidebar-ativa \.app-shell-nav\s*\{\s*display:\s*none\s*(?:;|\})/);
  assert.match(css, /body\.app-shell-sidebar-ativa \.app-sidebar\s*\{\s*display:\s*block/);
  assert.doesNotMatch(css.replace(/body\.app-shell-sidebar-ativa\s*\.app-sidebar/g, ''), /(?<!\.app-shell-sidebar-ativa\s)\.app-sidebar\s*\{\s*display:\s*block/);
});

test('sidebar some fora do breakpoint desktop largo (mobile fica para a 4.8)',()=>{
  assert.match(css, /\.app-sidebar\s*\{\s*display:\s*none\s*;?\s*\}/);
  assert.match(css, /@media\s*\(min-width:\s*1024px\)/);
});

test('z-index da sidebar é moderado e documentado, não um valor arbitrário alto',()=>{
  const m = css.match(/\.app-sidebar\s*\{[^}]*z-index:\s*(\d+)/s);
  assert.ok(m);
  assert.ok(Number(m[1]) < 100);
});
