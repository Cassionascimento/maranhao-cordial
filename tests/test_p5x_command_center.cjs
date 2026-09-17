const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('maranhao-backend/maranhao-intelligence.js','utf8');
function harness(reply={}){
 const nodes=new Map(),calls=[];
 const el=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',appendChild(){}});return nodes.get(id);};
 const ctx={document:{getElementById:el,createElement:()=>({})},window:{adminKeyAtual:'test-only'},FormData,URL,console,setTimeout:()=>{},fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>reply};}};
 vm.createContext(ctx);vm.runInContext(source.replace('  shell();','  globalThis.testing={creativeClick,creativeShell,write}; return;\n  shell();'),ctx);
 return {ctx,el,calls,click:async(action,id='id')=>ctx.testing.creativeClick({target:{closest:()=>({dataset:{creativeAction:action,artifact:id},disabled:false})}})};
}
test('P5X não faz chamada ao carregar e usa o Command Center existente',()=>{const h=harness();assert.equal(h.calls.length,0);assert.match(h.ctx.testing.creativeShell(),/EXECUTIVE & CREATIVE/);assert.match(source,/id="mic-creative" class="mic-view"/);});
test('gráfico sem fonte disponível explicita lacuna e não grava',async()=>{const h=harness({segmentos_distribuicao:{}});await h.click('chart');assert.equal(h.calls.length,1);assert.match(h.el('mic-creative-status').textContent,/NOT_ENOUGH_DATA/);});
test('aprovar exige responsável e não envia',async()=>{const h=harness({success:true});await h.click('approve');assert.equal(h.calls.length,0);h.el('mic-creative-actor').value='Diretor teste';await h.click('approve');const writes=h.calls.filter(c=>c.opts.method==='POST');assert.equal(writes.length,1);assert.match(writes[0].url,/artefatos\/id\/aprovar$/);});
test('nova versão usa endpoint existente e mantém falhas explícitas',async()=>{const h=harness({success:false,error:'Provider indisponível'});h.el('mic-creative-brief').value='Nova composição';await h.click('refine');assert.match(h.calls[0].url,/pirret\/refinar\/id$/);assert.equal(h.el('mic-creative-status').textContent,'Provider indisponível');});
test('sem autenticação não dispara geração',async()=>{const h=harness();h.ctx.window.adminKeyAtual='';h.el('mic-creative-brief').value='Teste';await h.click('campaign');assert.equal(h.calls.length,0);});
