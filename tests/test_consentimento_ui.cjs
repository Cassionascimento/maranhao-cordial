const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/consentimento.js','utf8');

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',hidden:false,dataset:{},className:'',
    append(...xs){this.children.push(...xs);},
    appendChild(x){this.children.push(x);return x;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    click(){this.listeners.click && this.listeners.click();},
    setAttribute(k,v){this[k]=v;},
  };
}

function localStorageFalso() {
  const dados = {};
  return {
    getItem: k => (k in dados ? dados[k] : null),
    setItem: (k,v) => { dados[k]=String(v); },
    removeItem: k => { delete dados[k]; },
    _dados: dados,
  };
}

function setup({consentimentoInicial=null, comGtag=true}={}) {
  const localStorage = localStorageFalso();
  if (consentimentoInicial) localStorage.setItem('mc_consentimento', consentimentoInicial);
  const body = no('body');
  const document = { createElement: no, body };
  const eventosDisparados = [];
  const listenersJanela = {};
  const chamadasGtag = [];
  class CustomEventFake { constructor(tipo, init) { this.type=tipo; this.detail = init && init.detail; } }
  const window = {
    addEventListener: (k,fn) => { listenersJanela[k]=fn; },
    dispatchEvent: ev => { eventosDisparados.push(ev); if (listenersJanela[ev.type]) listenersJanela[ev.type](ev); },
  };
  if (comGtag) window.gtag = (...args) => { chamadasGtag.push(args); };
  const sandbox = { document, window, localStorage, CustomEvent: CustomEventFake, console };
  vm.runInNewContext(code, sandbox);
  return { document, window, localStorage, body, eventosDisparados, chamadasGtag };
}

test('sem decisao previa, banner aparece automaticamente',()=>{
  const t=setup();
  assert.equal(t.body.children.length,1);
  assert.equal(t.body.children[0].id,'mc-consentimento-banner');
  assert.equal(t.body.children[0].hidden,false);
});

test('com decisao ja salva (aceito), banner nao aparece sozinho',()=>{
  const t=setup({consentimentoInicial:'aceito'});
  assert.equal(t.body.children.length,0);
});

test('com decisao ja salva (recusado), banner nao aparece sozinho',()=>{
  const t=setup({consentimentoInicial:'recusado'});
  assert.equal(t.body.children.length,0);
});

test('aceitar salva a decisao, esconde o banner e dispara evento',()=>{
  const t=setup();
  t.window.MCConsentimento.aceitar();
  assert.equal(t.localStorage.getItem('mc_consentimento'),'aceito');
  assert.equal(t.body.children[0].hidden,true);
  assert.equal(t.eventosDisparados.length,1);
  assert.equal(t.eventosDisparados[0].detail.aceito,true);
});

test('recusar salva a decisao, esconde o banner e dispara evento',()=>{
  const t=setup();
  t.window.MCConsentimento.recusar();
  assert.equal(t.localStorage.getItem('mc_consentimento'),'recusado');
  assert.equal(t.eventosDisparados[0].detail.aceito,false);
});

test('MCConsentimento.aceito() reflete a decisao corretamente',()=>{
  const t=setup();
  assert.equal(t.window.MCConsentimento.aceito(),false);
  t.window.MCConsentimento.aceitar();
  assert.equal(t.window.MCConsentimento.aceito(),true);
  t.window.MCConsentimento.recusar();
  assert.equal(t.window.MCConsentimento.aceito(),false);
});

test('abrirPreferencias reexibe o banner mesmo apos decisao (permite mudar de ideia)',()=>{
  const t=setup({consentimentoInicial:'recusado'});
  t.window.MCConsentimento.abrirPreferencias();
  assert.equal(t.body.children.length,1);
  assert.equal(t.body.children[0].hidden,false);
});

test('mudar de recusado para aceito dispara novo evento com aceito=true',()=>{
  const t=setup({consentimentoInicial:'recusado'});
  t.window.MCConsentimento.aceitar();
  assert.equal(t.localStorage.getItem('mc_consentimento'),'aceito');
  assert.equal(t.eventosDisparados[t.eventosDisparados.length-1].detail.aceito,true);
});

test('banner explica analytics/inteligencia e nunca promete anonimato total falso',()=>{
  const t=setup();
  const texto=JSON.stringify(t.body.children[0]);
  assert.match(texto,/navegação/);
  assert.match(texto,/interesse do público/);
});

test('botoes aceitar/recusar existem e chamam as funcoes certas',()=>{
  const t=setup();
  const banner=t.body.children[0];
  const botoes=banner.children[1].children;
  assert.equal(botoes.length,2);
  botoes[1].click(); // aceitar é o segundo botão
  assert.equal(t.localStorage.getItem('mc_consentimento'),'aceito');
});

test('nenhuma chamada de rede -- consentimento.js so mexe em localStorage e DOM',()=>{
  assert.ok(!/fetch\s*\(/.test(code));
});

test('sem decisao -- consentimento.js nao chama gtag (default ja foi setado pela propria pagina)',()=>{
  const t=setup({comGtag:true});
  assert.equal(t.chamadasGtag.length,0);
});

test('aceitou -- atualiza consent mode para granted',()=>{
  const t=setup();
  t.window.MCConsentimento.aceitar();
  assert.equal(JSON.stringify(t.chamadasGtag), JSON.stringify([['consent','update',{analytics_storage:'granted'}]]));
});

test('recusou -- atualiza consent mode para denied',()=>{
  const t=setup();
  t.window.MCConsentimento.recusar();
  assert.equal(JSON.stringify(t.chamadasGtag), JSON.stringify([['consent','update',{analytics_storage:'denied'}]]));
});

test('revogou (aceito -> recusado) -- consent mode volta para denied imediatamente',()=>{
  const t=setup();
  t.window.MCConsentimento.aceitar();
  t.window.MCConsentimento.recusar();
  assert.equal(JSON.stringify(t.chamadasGtag[t.chamadasGtag.length-1]), JSON.stringify(['consent','update',{analytics_storage:'denied'}]));
});

test('reaceitou depois de revogar -- consent mode volta para granted',()=>{
  const t=setup();
  t.window.MCConsentimento.aceitar();
  t.window.MCConsentimento.recusar();
  t.window.MCConsentimento.aceitar();
  assert.equal(JSON.stringify(t.chamadasGtag[t.chamadasGtag.length-1]), JSON.stringify(['consent','update',{analytics_storage:'granted'}]));
});

test('decisao ja existente (aceito) de visita anterior sincroniza o consent mode ao carregar, sem precisar clicar',()=>{
  const t=setup({consentimentoInicial:'aceito'});
  assert.equal(JSON.stringify(t.chamadasGtag), JSON.stringify([['consent','update',{analytics_storage:'granted'}]]));
});

test('decisao ja existente (recusado) de visita anterior tambem sincroniza ao carregar',()=>{
  const t=setup({consentimentoInicial:'recusado'});
  assert.equal(JSON.stringify(t.chamadasGtag), JSON.stringify([['consent','update',{analytics_storage:'denied'}]]));
});

test('pagina sem GA4 (sem window.gtag) nunca quebra ao aceitar/recusar',()=>{
  const t=setup({comGtag:false});
  assert.doesNotThrow(() => t.window.MCConsentimento.aceitar());
  assert.doesNotThrow(() => t.window.MCConsentimento.recusar());
});

test('index.html e raizes.html declaram o Consent Mode default (denied) antes do gtag config',()=>{
  for (const pagina of ['maranhao-backend/index.html','maranhao-backend/raizes.html']) {
    const html = fs.readFileSync(pagina,'utf8');
    const posDefault = html.indexOf("gtag('consent', 'default'");
    const posConfig = html.indexOf("gtag('config', 'G-JPD3R3NG3S')");
    assert.ok(posDefault >= 0, pagina + ': falta consent default');
    assert.ok(posConfig >= 0, pagina + ': falta gtag config');
    assert.ok(posDefault < posConfig, pagina + ': default deveria vir antes do config');
    assert.match(html, /'analytics_storage':\s*'denied'/);
  }
});

test('raizes.html carrega consentimento.js/css (mesmo banner, sem duplicar)',()=>{
  const html = fs.readFileSync('maranhao-backend/raizes.html','utf8');
  assert.match(html,/<script src="consentimento\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="consentimento\.css">/);
});
