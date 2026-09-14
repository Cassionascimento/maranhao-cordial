const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/canais-status.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},className:'',
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;}};
}

const CANAIS_OK = [
  {canal:'Instagram',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null},
  {canal:'WhatsApp',estado:'bloqueado',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:'configuracao_incompleta'},
  {canal:'LinkedIn',estado:'conectado',ultima_sincronizacao:null,leitura_disponivel:true,escrita_disponivel:true,aprovacao_exigida:true,ultimo_erro:null},
  {canal:'Pinterest',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null},
  {canal:'X',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null},
  {canal:'Gmail',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null},
];

function setup({semChave=false, ok=true}={}) {
  const elementos = {};
  const painel = no('div'); painel.id = 'canais-painel';
  const document = {
    createElement: no,
    getElementById: id => (id === 'canais-painel' ? painel : (elementos[id] ||= no())),
    querySelector: sel => (sel.includes('[data-tab="canais"]') ? (elementos.tab ||= no('button')) : null),
  };
  const window = { adminKeyAtual: semChave ? '' : 'x' };
  const calls = [];
  const fetchMock = async url => { calls.push(url); return { ok, json: async () => (ok ? {success:true, canais: CANAIS_OK} : {success:false, error:'indisponivel'}) }; };
  vm.runInNewContext(code, {document, window, fetch: fetchMock, console});
  return {elementos, calls, document};
}

test('sem chave admin, nenhuma chamada',()=>{
  const t = setup({semChave:true});
  t.elementos.tab.listeners.click();
  assert.equal(t.calls.length, 0);
});

test('carrega os 6 canais numa tabela, somente leitura',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.equal(t.calls.length, 1);
  assert.ok(t.calls[0].includes('/api/admin/canais/status'));
  const texto = JSON.stringify(t.elementos['canais-conteudo']);
  for (const nome of ['Instagram','WhatsApp','LinkedIn','Pinterest','X','Gmail']) assert.match(texto, new RegExp(nome));
  assert.equal(t.elementos['canais-conteudo'].hidden, false);
});

test('falha na API mostra estado explicado, nao trava',async()=>{
  const t = setup({ok:false});
  await t.elementos['canais-atualizar'].listeners.click();
  assert.equal(t.document.getElementById('canais-conteudo').hidden, true);
  assert.match(t.elementos['canais-status'].textContent, /indisponivel|Não foi possível/);
});

test('nenhuma chamada de escrita: so GET, sem method/body',()=>{
  assert.ok(!/method\s*:\s*['"](POST|PUT|DELETE)/i.test(code));
});

test('admin.html liga a aba Canais e os arquivos novos',()=>{
  assert.match(html,/data-tab="canais"/);
  assert.match(html,/id="canais-painel"/);
  assert.match(html,/<link rel="stylesheet" href="\/canais-status\.css">/);
  assert.match(html,/<script src="\/canais-status\.js" defer><\/script>/);
});
