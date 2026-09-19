const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('maranhao-backend/maranhao-intelligence.js','utf8');
function harness(reply={}){
 const nodes=new Map(),calls=[];
 const el=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',appendChild(){}});return nodes.get(id);};
 const ctx={document:{getElementById:el,createElement:()=>({})},window:{adminKeyAtual:'test-only'},FormData,URL,console,setTimeout:()=>{},fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>reply};}};
 vm.createContext(ctx);vm.runInContext(source.replace('  shell();','  globalThis.testing={creativeClick,creativeShell,write,loadCreative}; return;\n  shell();'),ctx);
 return {ctx,el,calls,click:async(action,id='id')=>ctx.testing.creativeClick({target:{closest:()=>({dataset:{creativeAction:action,artifact:id},disabled:false})}})};
}
test('P5X não faz chamada ao carregar e usa o Command Center existente',()=>{const h=harness();assert.equal(h.calls.length,0);assert.match(h.ctx.testing.creativeShell(),/EXECUTIVE & CREATIVE/);assert.match(source,/id="mic-creative" class="mic-view"/);});
test('gráfico sem fonte disponível explicita lacuna e não grava',async()=>{const h=harness({segmentos_distribuicao:{}});await h.click('chart');assert.equal(h.calls.length,1);assert.match(h.el('mic-creative-status').textContent,/NOT_ENOUGH_DATA/);});
test('aprovar exige responsável e não envia',async()=>{const h=harness({success:true});await h.click('approve');assert.equal(h.calls.length,0);h.el('mic-creative-actor').value='Diretor teste';await h.click('approve');const writes=h.calls.filter(c=>c.opts.method==='POST');assert.equal(writes.length,1);assert.match(writes[0].url,/artefatos\/id\/aprovar$/);});
test('nova versão usa endpoint existente e mantém falhas explícitas',async()=>{const h=harness({success:false,error:'Provider indisponível'});h.el('mic-creative-brief').value='Nova composição';await h.click('refine');assert.match(h.calls[0].url,/pirret\/refinar\/id$/);assert.equal(h.el('mic-creative-status').textContent,'Provider indisponível');});
test('sem autenticação não dispara geração',async()=>{const h=harness();h.ctx.window.adminKeyAtual='';h.el('mic-creative-brief').value='Teste';await h.click('campaign');assert.equal(h.calls.length,0);});

test('SVG factual não oferece geração paga de nova imagem ou campanha',async()=>{const h=harness({success:true,artefatos:[{id:'chart',artifact_type:'CHART',version:1,status:'gerado',mime_type:'image/svg+xml',metadata:{confidence:'DERIVED'}}]});await h.ctx.testing.loadCreative();assert.ok(!h.el('mic-creative-artifacts').innerHTML.includes('data-creative-action="refine"'));assert.ok(!h.el('mic-creative-artifacts').innerHTML.includes('data-creative-action="social"'));});
test('provider mock nunca aparece como provider real configurado',async()=>{const h=harness({success:true,provider:'MockImageProvider',disponivel:true});await h.ctx.testing.loadCreative();assert.match(h.el('mic-creative-provider').textContent,/MOCK\/TEST ONLY/);});
