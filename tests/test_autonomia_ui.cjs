const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('maranhao-backend/autonomia-supervisionada.js','utf8');
function setup(key,response){
 const nodes=[],handlers={},calls=[];
 const node=()=>{const n={textContent:'',append(){},addEventListener(){}};nodes.push(n);return n;};
 const root=node();
 const window={adminKeyAtual:key,addEventListener:(name,fn)=>handlers[name]=fn};
 vm.runInNewContext(source,{window,document:{getElementById:()=>root,createElement:node},fetch:async(...args)=>{calls.push(args);return response;},Date});
 return {nodes,handlers,calls};
}
test('supervisão sem autenticação não consulta',async()=>{const t=setup(null);await t.handlers['admin-autorizado']();assert.equal(t.calls.length,0);});
test('supervisão somente GET e texto com transporte bloqueado',async()=>{const t=setup('sintetica',{ok:true,json:async()=>({success:true,politica:{versao:'v1',habilitada:true},execucao_habilitada:false,pausado:false,registros:[],proximo_briefing:null})});await t.handlers['admin-autorizado']();assert.equal(t.calls.length,1);assert.equal(t.calls[0][1].method,undefined);assert.equal(t.calls[0][1].body,undefined);assert.ok(t.nodes.some(n=>n.textContent.includes('Execução: bloqueada')));assert.ok(!source.includes('innerHTML'));});
test('schema indisponível aparece sem dados',async()=>{const t=setup('sintetica',{ok:false,json:async()=>({success:false})});await t.handlers['admin-autorizado']();assert.ok(t.nodes.some(n=>n.textContent.startsWith('Sem dados — não foi possível')));});
