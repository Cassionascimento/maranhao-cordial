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
  {canal:'Instagram',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:'Definir INSTAGRAM_ACCESS_TOKEN.'},
  {canal:'WhatsApp',estado:'bloqueado',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:'configuracao_incompleta',proximo_passo:'Concluir validação Meta.'},
  {canal:'LinkedIn',estado:'conectado',ultima_sincronizacao:null,leitura_disponivel:true,escrita_disponivel:true,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:null},
  {canal:'Pinterest',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:'Criar app no Pinterest Developers.'},
  {canal:'X',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:'Criar app no X Developer Portal.'},
  {canal:'Gmail',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:'Definir GMAIL_REFRESH_TOKEN.'},
];

function setup({semChave=false, ok=true}={}) {
  const elementos = {};
  const painel = no('div'); painel.id = 'canais-painel';
  const document = {
    createElement: no,
    getElementById: id => (id === 'canais-painel' ? painel : (elementos[id] ||= no())),
    querySelector: sel => (sel.includes('[data-tab="canais"]') ? (elementos.tab ||= no('button')) : null),
  };
  const window = { adminKeyAtual: semChave ? '' : 'x', open: () => {} };
  const calls = [];
  const fetchMock = async (url, opcoes) => {
    calls.push({ url, method: (opcoes && opcoes.method) || 'GET' });
    if (url.endsWith('/api/admin/canais/status')) {
      return { ok, json: async () => (ok ? {success:true, canais: CANAIS_OK} : {success:false, error:'indisponivel'}) };
    }
    // rotas de ação dos conectores (connect/testar/desconectar/reconectar)
    if (url.includes('/connect')) return { ok:true, json: async () => ({success:true, url:'https://exemplo/auth'}) };
    if (url.includes('/testar')) return { ok:true, json: async () => ({success:true, conexao:'ok'}) };
    return { ok:true, json: async () => ({success:true}) };
  };
  vm.runInNewContext(code, {document, window, fetch: fetchMock, console});
  return {elementos, calls, document};
}

test('sem chave admin, nenhuma chamada',()=>{
  const t = setup({semChave:true});
  t.elementos.tab.listeners.click();
  assert.equal(t.calls.length, 0);
});

test('carrega os 6 canais em cards, somente leitura automatica',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.equal(t.calls.length, 1);
  assert.ok(t.calls[0].url.includes('/api/admin/canais/status'));
  assert.equal(t.calls[0].method, 'GET');
  const texto = JSON.stringify(t.elementos['canais-conteudo']);
  for (const nome of ['Instagram','WhatsApp','LinkedIn','Pinterest','X','Gmail']) assert.match(texto, new RegExp(nome));
  assert.equal(t.elementos['canais-conteudo'].hidden, false);
});

test('cada card mostra leitura, escrita, ultima sincronizacao, ultimo erro e proximo passo',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const texto = JSON.stringify(t.elementos['canais-conteudo']);
  assert.match(texto, /Leitura/);
  assert.match(texto, /Escrita/);
  assert.match(texto, /Última sincronização/);
  assert.match(texto, /Último erro/);
  assert.match(texto, /Criar app no Pinterest Developers/);
});

test('botoes de acao so aparecem para canais com rota real (LinkedIn/Pinterest/X)',async()=>{
  const t = setup();
  await t.elementos['canais-conteudo'] // garante existencia antes do load
  await t.elementos['canais-atualizar'].listeners.click();
  const grid = t.elementos['canais-conteudo'].children[0];
  const comBotao = grid.children.filter(card => card.children.some(c => c.tag === 'div' && c.className === 'canais-card-acoes'));
  assert.equal(comBotao.length, 3);
});

test('conectar abre nova aba e nao chama escrita automatica no load',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const grid = t.elementos['canais-conteudo'].children[0];
  const linkedinCard = grid.children.find(c => JSON.stringify(c).includes('LinkedIn'));
  const acoes = linkedinCard.children.find(c => c.className === 'canais-card-acoes');
  const conectar = acoes.children.find(b => b.textContent === 'Conectar');
  await conectar.listeners.click();
  assert.ok(t.calls.some(c => c.url.includes('/api/admin/linkedin/connect') && c.method === 'GET'));
});

test('reconectar e desconectar usam POST nas rotas reais do conector',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const grid = t.elementos['canais-conteudo'].children[0];
  const xCard = grid.children.find(c => JSON.stringify(c).includes('"X"') || c.children.some(h => h.children && h.children.some(hh => hh.textContent === 'X')));
  const acoes = xCard.children.find(c => c.className === 'canais-card-acoes');
  const desconectar = acoes.children.find(b => b.textContent === 'Desconectar');
  await desconectar.listeners.click();
  assert.ok(t.calls.some(c => c.url.includes('/api/admin/x/desconectar') && c.method === 'POST'));
});

test('falha na API mostra estado explicado, nao trava',async()=>{
  const t = setup({ok:false});
  await t.elementos['canais-atualizar'].listeners.click();
  assert.equal(t.document.getElementById('canais-conteudo').hidden, true);
  assert.match(t.elementos['canais-status'].textContent, /indisponivel|Não foi possível/);
});

test('nenhuma escrita automatica: leitura periodica so faz GET',()=>{
  assert.match(code,/async function call\(\)/);
  assert.ok(!/method\s*:\s*['"]POST['"][^}]*\}\s*\);?\s*\n\s*const body/.test(code));
});

test('admin.html liga a aba Canais e os arquivos novos',()=>{
  assert.match(html,/data-tab="canais"/);
  assert.match(html,/id="canais-painel"/);
  assert.match(html,/<link rel="stylesheet" href="\/canais-status\.css">/);
  assert.match(html,/<script src="\/canais-status\.js" defer><\/script>/);
});
