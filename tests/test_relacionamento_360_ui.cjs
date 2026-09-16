const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/relacionamento-360.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

test('painel referencia as rotas de visao unica e next best action',()=>{
  assert.match(code,/\/visao-unica\/buscar/);
  assert.match(code,/\/visao-unica\//);
  assert.match(code,/\/next-best-action\//);
});

test('admin.html registra a aba, o painel e o script do relacionamento 360',()=>{
  assert.ok(html.includes('data-tab="relacionamento-360"'));
  assert.ok(html.includes('id="relacionamento-360-painel"'));
  assert.ok(html.includes('src="/relacionamento-360.js"'));
});

function no(tag='div') {
  const obj = {tag,children:[],listeners:{},textContent:'',hidden:false,value:'',type:'',
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    setAttribute(){},getAttribute(){return null;},removeAttribute(){},
    _classNameInterna:'',
  };
  obj.classList = {_c:new Set(), add(c){this._c.add(c);}, remove(c){this._c.delete(c);}, contains(c){return this._c.has(c);}};
  Object.defineProperty(obj,'className',{get(){return obj._classNameInterna;},set(v){obj._classNameInterna=v||'';}});
  return obj;
}

const LEADS = [{id:'lead1', nome:'Fulano', empresa:'Bar X', email:'fulano@x.com', estagio:'novo', status:'ativo'}];
const VISAO = {
  success:true,
  lead:{id:'lead1', nome:'Fulano', empresa:'Bar X', email:'fulano@x.com', telefone:null, instagram:null, estagio:'novo', status:'ativo'},
  identidades_por_canal:[{canal:'whatsapp', identificador_externo:'5511999', username_publico:null, confianca:90, criterio_vinculo:'telefone_exato'}],
  interacoes_recentes:[{canal:'whatsapp', tipo_interacao:'mensagem', interesse:'alto', classificacao:null, criado_em:'2026-09-14T10:00:00Z'}],
  total_interacoes_na_janela:1,
};
const NBA = {success:true, lead_id:'lead1', sugestoes:[
  {tipo:'follow_up_interesse_alto', motivo:'Última interação sinalizou interesse alto.', evidencia:['interacoes_omnichannel: ...'],
   confianca:'alta', responsavel:'Leonard', bloqueio:null},
]};

function setup({leads=LEADS, visao=VISAO, nba=NBA, semChave=false}={}) {
  const elementos={};
  const painel=no('div'); painel.id='relacionamento-360-painel';
  const document={
    createElement:no,
    getElementById:id=>{ if (id==='relacionamento-360-painel') return painel; return elementos[id] ||= no(); },
  };
  const window={adminKeyAtual: semChave ? '' : 'chave-teste'};
  const calls=[];
  const fetchMock=async (url) => {
    calls.push(url);
    if (url.includes('/visao-unica/buscar')) return {ok:true, json: async () => ({success:true, resultados:leads})};
    if (url.includes('/next-best-action/')) return {ok:true, json: async () => nba};
    if (url.includes('/visao-unica/')) return {ok:true, json: async () => visao};
    return {ok:false, json: async () => ({success:false, error:'rota desconhecida'})};
  };
  const sandbox={document,window,fetch:fetchMock,console,Promise,encodeURIComponent,JSON,Date,Number,String};
  vm.runInNewContext(code, sandbox);
  return {document,window,elementos,calls,painel};
}

test('busca vazia nao chama a API',async()=>{
  const t=setup();
  t.elementos['relacionamento-360-busca'].value='';
  await t.elementos['relacionamento-360-buscar-botao'].listeners.click();
  assert.equal(t.calls.length,0);
});

test('busca com termo lista resultados clicaveis',async()=>{
  const t=setup();
  t.elementos['relacionamento-360-busca'].value='fulano';
  await t.elementos['relacionamento-360-buscar-botao'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.ok(t.calls[0].includes('q=fulano'));
});

test('clicar em um resultado carrega visao unica e next best action juntas',async()=>{
  const t=setup();
  t.elementos['relacionamento-360-busca'].value='fulano';
  await t.elementos['relacionamento-360-buscar-botao'].listeners.click();
  const lista = t.elementos['relacionamento-360-resultados'].children.find(c=>c.tag==='ul');
  const botao = lista.children[0].children[0];
  await botao.listeners.click();
  assert.equal(t.calls.length,3);
  assert.equal(t.elementos['relacionamento-360-detalhe'].hidden,false);
});

test('sugestao de next best action nunca aparece sem motivo/evidencia/responsavel',async()=>{
  const t=setup();
  t.elementos['relacionamento-360-busca'].value='fulano';
  await t.elementos['relacionamento-360-buscar-botao'].listeners.click();
  const lista = t.elementos['relacionamento-360-resultados'].children.find(c=>c.tag==='ul');
  await lista.children[0].children[0].listeners.click();
  const detalhe = t.elementos['relacionamento-360-detalhe'];
  const blocoNba = detalhe.children[detalhe.children.length-1];
  const card = blocoNba.children.find(c=>c.className && c.className.includes('relacionamento-360-sugestao'));
  assert.ok(card, 'card de sugestao deveria existir');
});

test('sem chave admin nao busca',async()=>{
  const t=setup({semChave:true});
  t.elementos['relacionamento-360-busca'].value='fulano';
  await t.elementos['relacionamento-360-buscar-botao'].listeners.click();
  assert.equal(t.calls.length,0);
});
