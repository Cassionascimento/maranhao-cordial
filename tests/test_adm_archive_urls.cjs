const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('maranhao-backend/admin.html','utf8');
for(const name of ['restaurarMensagemIA','arquivarMensagemIA','arquivarProfissionalWorkflow','restaurarProfissionalWorkflow']){
 test(name+' usa API real do projeto e preserva autenticação e método',async()=>{
  const start=src.indexOf('async function '+name+'('), end=src.indexOf('\n}',start);
  // Captura a declaração até o fechamento pelo balanceamento de chaves.
  let pos=src.indexOf('{',start),level=1,finish=pos+1;
  for(;level && finish<src.length;finish++){if(src[finish]==='{')level++;if(src[finish]==='}')level--;}
  const calls=[];const ctx={window:{adminKeyAtual:'test-only'},document:{getElementById:()=>({value:'teste'})},confirm:()=>true,alert:()=>{},encodeURIComponent,carregarCentralDecisoes:async()=>{},carregarProfissionaisWorkflow:async()=>{},fetch:async(url,opts)=>{calls.push({url,opts});return{ok:true,json:async()=>({})}}};
  vm.createContext(ctx);vm.runInContext(src.slice(start,finish),ctx);
  await ctx[name](name.includes('Mensagem')?{dataset:{interacaoId:'id-1'}}:'id-1');
  assert.equal(calls.length,1);assert.ok(calls[0].url.startsWith('https://maranhao-cordial-api.onrender.com/api/admin/'));assert.ok(calls[0].url.endsWith('/id-1/arquivamento'));assert.equal(calls[0].opts.method,'PATCH');assert.equal(calls[0].opts.headers['X-Admin-Key'],'test-only');
 });
}
