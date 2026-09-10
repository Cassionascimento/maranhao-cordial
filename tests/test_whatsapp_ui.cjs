const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const admin=fs.readFileSync('maranhao-backend/admin.html','utf8');
const decision=admin.slice(admin.indexOf('async function decidirMensagemIA('),admin.indexOf('iaListaDecisoes.addEventListener(',admin.indexOf('async function decidirMensagemIA(')));
function setupDecision(canal){
 const calls=[],status={textContent:''},buttons=[{}],card={dataset:{id:'uuid',canal},querySelector:s=>s.includes('resposta')?{value:'Texto revisado'}:status,querySelectorAll:()=>buttons};
 const context={adminKeyAtual:'sintetica',encodeURIComponent,setTimeout:()=>{},carregarCentralDecisoes:()=>{},fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({success:true})};}};
 vm.createContext(context);vm.runInContext(decision,context);return {calls,status,card,run:acao=>context.decidirMensagemIA(card,acao)};
}
test('aprovar WhatsApp registra somente decisão, sem chamar envio',async()=>{
 const t=setupDecision('whatsapp');await t.run('aprovar');assert.equal(t.calls.length,1);assert.equal(t.calls[0].options.method,'PATCH');assert.match(t.status.textContent,/Envio bloqueado/);
 assert.equal(JSON.parse(t.calls[0].options.body).resposta,'Texto revisado');
});
test('rejeitar WhatsApp não chama transporte',async()=>{const t=setupDecision('whatsapp');await t.run('rejeitar');assert.equal(t.calls.length,1);assert.equal(JSON.parse(t.calls[0].options.body).acao,'rejeitar');});
test('canais existentes preservam o fluxo anterior (HTTP simulado)',async()=>{const t=setupDecision('instagram');await t.run('aprovar');assert.equal(t.calls.length,2);assert.ok(t.calls[1].url.endsWith('/enviar'));});
const script=fs.readFileSync('maranhao-backend/whatsapp-omnichannel.js','utf8');
function setupPanel(key='sintetica'){
 const calls=[],elements={},events={};function node(){return {children:[],listeners:{},style:{},textContent:'',append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},addEventListener(k,fn){this.listeners[k]=fn}};}
 const document={getElementById:k=>elements[k] ||=node(),createElement:node};
 const body={success:true,conector:{estado:'aguardando_meta',verificacao_remota:'não verificado',dependencias_meta:['Número online'],faltantes:[]},processamentos:{concluido:1},entradas:[{chave:'key',estado:'concluido',texto:'<img onerror=alert(1)>',tentativas:1,resposta_status:'aguardando_aprovacao'}],auditoria:[]};
 vm.runInNewContext(script,{document,window:{adminKeyAtual:key,addEventListener:(k,fn)=>events[k]=fn},fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>body};}});
 return {calls,elements,events};
}
test('painel sem login não consulta',async()=>{const t=setupPanel('');await t.events['admin-autorizado']();assert.equal(t.calls.length,0);});
test('status é somente leitura e mostra conteúdo como texto',async()=>{
 const t=setupPanel();await t.events['admin-autorizado']();assert.equal(t.calls.length,1);assert.equal(t.calls[0].options.method,undefined);
 assert.match(t.elements['whatsapp-omni-status'].textContent,/aguardando_meta/);
 const entry=t.elements['whatsapp-omni-entradas'].children[0];assert.ok(entry.children.some(c=>c.textContent==='<img onerror=alert(1)>'));
 assert.ok(!script.includes('innerHTML'));
});
