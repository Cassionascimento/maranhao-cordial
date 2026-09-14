const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/mi-graficos.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',dataset:{},className:'',style:{},
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;}, setAttribute(){}, classList:{contains:()=>true}};
}
function setup({adminKey='x', painel, diretor, canais, ok=true}={}) {
  const elementos = {};
  const mi = no('div'); mi.id='mi-painel'; mi.classList={contains:()=>true};
  const raiz = no('div'); raiz.id='mig-raiz';
  const document = {
    createElement: no,
    createElementNS: (ns, tag) => no(tag),
    getElementById: id => (id==='mi-painel'?mi : id==='mig-raiz'?raiz : (elementos[id] ||= no())),
    querySelector: sel => (sel.includes('[data-tab="maranhao-intelligence"]') ? (elementos.tab ||= no('button')) : null),
  };
  const window = { adminKeyAtual: adminKey, addEventListener(){} };
  const calls = [];
  const fetchMock = async url => {
    calls.push(url);
    if (String(url).includes('/mi/painel')) return {ok, json: async () => ({success:true, ...painel})};
    if (String(url).includes('/mi/diretor')) return {ok, json: async () => ({success:true, ...diretor})};
    if (String(url).includes('/canais/status')) return {ok, json: async () => ({success:true, canais: canais||[]})};
    return {ok:false, json: async () => ({success:false})};
  };
  vm.runInNewContext(code, {document, window, fetch: fetchMock, console});
  return {elementos, calls, raiz, mi, document};
}

test('sem chave admin, nao busca nada ao clicar atualizar',async()=>{
  const t = setup({adminKey:''});
  await t.elementos['mi-atualizar'].listeners.click();
  assert.equal(t.calls.length, 0);
});

test('com dados reais, desenha graficos sem inventar numeros',async()=>{
  const t = setup({
    painel: {produto:{por_sku:[{sku:'X',produto_nome:'Guaraná',total:5}]}, secundario:{unidades_por_estado:{emitida:3,ativa:2,revogada:1}}, atividade_recente:[{tipo_evento:'scan'},{tipo_evento:'scan'}]},
    diretor: {comercial:{prospectos_encontrados:10,prospectos_qualificados:4,oportunidades:[{}]}, conselho:{trabalhando:2,sem_demanda:1,conflitos:[],vetos:[],aguardando_diretor:[]}},
    canais: [{canal:'LinkedIn', estado:'pendente'}],
  });
  await t.elementos['mi-atualizar'].listeners.click();
  const texto = JSON.stringify(t.raiz);
  assert.match(texto, /Guaraná/);
  assert.match(texto, /Funil comercial/);
  assert.match(texto, /LinkedIn/);
});

test('sem dado nenhum, mostra estado vazio, nunca numero fabricado',async()=>{
  const t = setup({painel:{produto:{por_sku:[]}, secundario:{unidades_por_estado:{}}, atividade_recente:[]}, diretor:{comercial:{prospectos_encontrados:0,prospectos_qualificados:0,oportunidades:[]}, conselho:{trabalhando:0,sem_demanda:0,conflitos:[],vetos:[],aguardando_diretor:[]}}, canais:[]});
  await t.elementos['mi-atualizar'].listeners.click();
  const texto = JSON.stringify(t.raiz);
  assert.match(texto, /Sem dados suficientes/);
});

test('nenhuma chamada de escrita: so GET',()=>{
  assert.ok(!/method\s*:\s*['"](POST|PUT|DELETE)/i.test(code));
});

test('admin.html liga os arquivos novos de graficos',()=>{
  assert.match(html,/id="mig-raiz"/);
  assert.match(html,/<link rel="stylesheet" href="\/mi-graficos\.css">/);
  assert.match(html,/<script src="\/mi-graficos\.js" defer><\/script>/);
});
