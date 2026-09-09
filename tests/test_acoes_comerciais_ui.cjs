const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('maranhao-backend/acoes-comerciais.js','utf8');
function setup(key='teste', origemTipo='prospecto_fase57') {
 const calls=[], elements={}, events={};
 function node(tag='div') {return {tag, children:[],style:{},listeners:{},textContent:'',
   append(...xs){this.children.push(...xs)},replaceChildren(){this.children=[]},
   addEventListener(k,fn){this.listeners[k]=fn}}}
 const document={createElement:node,getElementById:id=>elements[id] ||= node()};
 const window={adminKeyAtual:key,addEventListener:(e,fn)=>events[e]=fn};
 const data={id:'uuid',digest:'hash',origem_tipo:origemTipo,origem_id:'origem-uuid',status:'aguardando_aprovacao',dados:{empresa:'<img onerror=alert(1)>',destinatario:'teste@empresa.com',canal:'email',motivo:'Fonte pública',mensagem:'Proposta'}};
 vm.runInNewContext(code,{document,window,fetch:async(url,options)=>{
   calls.push({url,options}); return {ok:true,json:async()=>({acoes:[data],success:true})};
 }});
 return {calls,elements,events};
}
test('sem login não consulta nem envia',async()=>{
 const t=setup('');await t.events['admin-autorizado']();assert.equal(t.calls.length,0);
});
test('aprovação envia apenas decisão com digest; conteúdo usa texto seguro',async()=>{
 const t=setup();await t.events['admin-autorizado']();
 const card=t.elements['lista-acoes-comerciais'].children[0];
 assert.equal(card.children[0].textContent,'<img onerror=alert(1)>');
 const approve=card.children.find(n=>n.tag==='button'&&n.textContent==='Aprovar');
 await approve.listeners.click();
 const posts=t.calls.filter(c=>c.options.method==='POST');
 assert.equal(posts.length,1);assert.ok(posts[0].url.endsWith('/decisao'));
 assert.deepEqual(JSON.parse(posts[0].options.body),{decisao:'aprovar',digest:'hash'});
 assert.ok(!t.calls.some(c=>c.url.endsWith('/executar')));
});
test('rejeição nunca chama executor',async()=>{
 const t=setup();await t.events['admin-autorizado']();
 const card=t.elements['lista-acoes-comerciais'].children[0];
 await card.children.find(n=>n.textContent==='Rejeitar').listeners.click();
 assert.equal(JSON.parse(t.calls.find(c=>c.options.method==='POST').options.body).decisao,'rejeitar');
 assert.ok(!t.calls.some(c=>c.url.includes('/executar')));
});
test('detalhes preservam tipo e ID das duas origens sem link inventado',async()=>{
 for (const [tipo, rotulo] of [['prospecto_fase56','Parceiro técnico — Fase 5.6'],['prospecto_fase57','Prospecção — Fase 5.7']]) {
  const t=setup('teste',tipo);await t.events['admin-autorizado']();
  const card=t.elements['lista-acoes-comerciais'].children[0];
  const detalhes=card.children.find(n=>n.tag==='details');
  assert.ok(detalhes.children.some(n=>n.textContent===`Origem: ${rotulo} | origem-uuid`));
  assert.ok(!detalhes.children.some(n=>n.tag==='a'));
 }
});
