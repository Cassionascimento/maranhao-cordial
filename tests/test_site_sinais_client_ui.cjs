const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/site-sinais.js','utf8');

function localStorageFalso() {
  const dados = {};
  return {
    getItem: k => (k in dados ? dados[k] : null),
    setItem: (k,v) => { dados[k]=String(v); },
    removeItem: k => { delete dados[k]; },
  };
}

function no(tag='div') {
  return {tag, dataset:{}, listeners:{},
    addEventListener(k,fn){ this.listeners[k]=fn; },
    closest(sel){
      // suficiente para os testes: o próprio nó "é" o alvo se tiver QUALQUER
      // um dos atributos data-* do seletor composto (separado por vírgula).
      const chaves = sel.split(',').map(parte => {
        const m = parte.trim().match(/\[data-([a-z-]+)\]/);
        return m ? m[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase()) : null;
      }).filter(Boolean);
      return chaves.some(chave => this.dataset[chave] !== undefined) ? this : null;
    },
  };
}

function setup({aceito=false, statusInicial=null}={}) {
  const localStorage = localStorageFalso();
  const chamadas = [];
  const listenersDocumento = {};
  const document = {
    addEventListener: (k,fn) => { listenersDocumento[k]=fn; },
  };
  const listenersJanela = {};
  const window = {
    addEventListener: (k,fn) => { listenersJanela[k]=fn; },
    MCConsentimento: { aceito: () => aceito },
  };
  const fetchMock = (url, opts) => { chamadas.push({url, opts, corpo: JSON.parse(opts.body)}); return Promise.resolve({}).then(()=>({})); };
  const cryptoFake = { randomUUID: () => '11111111-1111-1111-1111-111111111111' };
  const sandbox = { document, window, localStorage, fetch: fetchMock, crypto: cryptoFake, console, Date };
  vm.runInNewContext(code, sandbox);
  return { document, window, localStorage, chamadas, listenersDocumento, listenersJanela };
}

test('consentiu -> sinal permitido (fetch acontece)',()=>{
  // aceito=true já dispara 'pagina_visitada' automaticamente ao carregar;
  // a chamada explícita abaixo é a que o teste verifica, por isso pega a última.
  const t=setup({aceito:true});
  t.window.MCSinaisSite.produtoVisitado('guarana');
  const ultima = t.chamadas[t.chamadas.length-1];
  assert.ok(ultima.url.includes('/api/site/sinal'));
  assert.equal(ultima.corpo.tipo,'produto_visitado');
  assert.equal(ultima.corpo.produto,'guarana');
  assert.equal(ultima.corpo.consentimento,true);
});

test('recusou -> nenhum sinal',()=>{
  const t=setup({aceito:false});
  t.window.MCSinaisSite.produtoVisitado('guarana');
  t.window.MCSinaisSite.ctaClicado('compreaqui');
  t.window.MCSinaisSite.intencaoContato();
  assert.equal(t.chamadas.length,0);
});

test('sem decisao (MCConsentimento ausente) -> nenhum sinal',()=>{
  const localStorage = localStorageFalso();
  const chamadas = [];
  const document = { addEventListener(){} };
  const window = { addEventListener(){} }; // sem MCConsentimento
  const fetchMock = (...args) => { chamadas.push(args); return Promise.resolve({}); };
  vm.runInNewContext(code, { document, window, localStorage, fetch: fetchMock, crypto:{randomUUID:()=>'x'}, console, Date });
  window.MCSinaisSite.paginaVisitada();
  assert.equal(chamadas.length,0);
});

test('revogar consentimento apaga o token anonimo imediatamente',()=>{
  const t=setup({aceito:true});
  t.window.MCSinaisSite.produtoVisitado('acai');
  assert.ok(t.localStorage.getItem('mc_visitante_anonimo'));
  t.listenersJanela['mc-consentimento-mudou']({detail:{aceito:false}});
  assert.equal(t.localStorage.getItem('mc_visitante_anonimo'),null);
});

test('apos revogar, nenhuma nova chamada acontece mesmo que o codigo tente enviar',()=>{
  const t=setup({aceito:true});
  t.window.MCSinaisSite.paginaVisitada();
  const antes = t.chamadas.length;
  t.window.MCConsentimento.aceito = () => false; // revogado
  t.listenersJanela['mc-consentimento-mudou']({detail:{aceito:false}});
  t.window.MCSinaisSite.ctaClicado('profissional');
  assert.equal(t.chamadas.length, antes); // nenhuma chamada nova
});

test('reaceitar apos revogar volta a permitir e reenvia pagina_visitada',()=>{
  const t=setup({aceito:false});
  t.window.MCSinaisSite.produtoVisitado('bacuri');
  assert.equal(t.chamadas.length,0);
  t.window.MCConsentimento.aceito = () => true;
  t.listenersJanela['mc-consentimento-mudou']({detail:{aceito:true}});
  assert.equal(t.chamadas.length,1);
  assert.equal(t.chamadas[0].corpo.tipo,'pagina_visitada');
});

test('primeira visita nao gera sinal de retorno; segunda chamada de paginaVisitada gera',()=>{
  // aceito=false no carregamento -- nenhum autodisparo; controlamos as duas
  // chamadas de paginaVisitada() manualmente para isolar a primeira/segunda.
  const t=setup({aceito:false});
  t.window.MCConsentimento.aceito = () => true;
  t.window.MCSinaisSite.paginaVisitada();
  assert.equal(t.chamadas.length,1); // só pagina_visitada, sem token prévio
  assert.equal(t.chamadas[0].corpo.tipo,'pagina_visitada');
  t.window.MCSinaisSite.paginaVisitada();
  const tipos = t.chamadas.map(c=>c.corpo.tipo);
  assert.ok(tipos.includes('retorno_visitante'));
});

test('nunca envia nome, email, telefone ou texto livre',()=>{
  const t=setup({aceito:true});
  t.window.MCSinaisSite.produtoVisitado('guarana');
  t.window.MCSinaisSite.ctaClicado('compreaqui');
  for (const chamada of t.chamadas) {
    const chaves = Object.keys(chamada.corpo);
    for (const chave of chaves) {
      assert.ok(['tipo','consentimento','produto','cta','visitante_anonimo'].includes(chave), chave);
    }
  }
});

test('delegado data-mc-cta dispara ctaClicado ao clicar',()=>{
  const t=setup({aceito:true});
  const antes = t.chamadas.length; // ignora o pagina_visitada automático do load
  const elemento = no('a');
  elemento.dataset.mcCta = 'experience';
  t.listenersDocumento.click({target: elemento});
  const ultima = t.chamadas[t.chamadas.length-1];
  assert.equal(t.chamadas.length, antes+1);
  assert.equal(ultima.corpo.tipo,'cta_clicado');
  assert.equal(ultima.corpo.cta,'experience');
});

test('delegado data-mc-produto dispara produtoVisitado ao clicar',()=>{
  const t=setup({aceito:true});
  const antes = t.chamadas.length;
  const elemento = no('a');
  elemento.dataset.mcProduto = 'guarana';
  t.listenersDocumento.click({target: elemento});
  const ultima = t.chamadas[t.chamadas.length-1];
  assert.equal(t.chamadas.length, antes+1);
  assert.equal(ultima.corpo.tipo,'produto_visitado');
  assert.equal(ultima.corpo.produto,'guarana');
});

test('clique fora de qualquer elemento marcado nao dispara nada alem do load automatico',()=>{
  const t=setup({aceito:true});
  const antes = t.chamadas.length; // só o pagina_visitada automático do load
  const elemento = no('div');
  t.listenersDocumento.click({target: elemento});
  assert.equal(t.chamadas.length, antes);
});

test('index.html liga consentimento.js/site-sinais.js e marca os 3 CTAs reais',()=>{
  const html = fs.readFileSync('maranhao-backend/index.html','utf8');
  assert.match(html,/<link rel="stylesheet" href="consentimento\.css">/);
  assert.match(html,/<script src="consentimento\.js" defer><\/script>/);
  assert.match(html,/<script src="site-sinais\.js" defer><\/script>/);
  assert.match(html,/data-mc-cta="experience"/);
  assert.match(html,/data-mc-cta="compreaqui"/);
  assert.match(html,/data-mc-produto="guarana"/);
  assert.match(html,/data-mc-cta="profissional"/);
});
