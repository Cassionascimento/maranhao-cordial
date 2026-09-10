const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/inteligencia-territorial.js','utf8');
function setup(key='test') {
 const calls=[],elements={},events={};let fail=false,formValues=[];
 function node(tag='div'){return {tag,children:[],listeners:{},textContent:'',value:'cidade',classList:{contains:()=>false},
  append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},addEventListener(k,fn){this.listeners[k]=fn},scrollIntoView(){},reset(){formValues=[]}};}
 const document={createElement:node,getElementById:id=>elements[id] ||=node(),querySelector:()=>elements.tab ||=node()};
 const window={adminKeyAtual:key,addEventListener:(e,fn)=>events[e]=fn};
 const bucket={id:'one',territorio:'<img onerror=alert(1)>',fatos:{relacoes:2},indicadores:{taxa_resposta:null,base_taxa_resposta:0,densidade_relativa_base_localizada:1},circulacao:{},metricas:{},sinais:[],evidencias:[{nome:'<script>bad</script>',fonte:'CRM',id:'one'}]};
 const decision={classificacao:'sinal inicial',territorio:bucket.territorio,territorio_id:'one',por_que:['2 relações'],dados_faltantes:['respostas']};
 const report={success:true,cobertura:{relacoes_unicas:2,relacoes_sem_cidade_uf:0,interacoes_sem_vinculo:0,registros_excluidos:0,fontes_limitadas:[]},limites:[],presenca_digital:{snapshot_existente:null},niveis:{cidade:[bucket],uf:[bucket]},decisoes:Object.fromEntries(['midia','prospeccao','producao_distribuicao','eventos'].map(k=>[k,decision]))};
 vm.runInNewContext(code,{document,window,Intl,crypto:require('node:crypto').webcrypto,FormData:class{[Symbol.iterator](){return formValues[Symbol.iterator]()}},fetch:async(url,options)=>{
   calls.push({url,options});if(fail && url.endsWith('/registros'))throw new Error('connection lost');
   return {ok:true,json:async()=>report};
 }});
 return {calls,elements,events,setFail:v=>fail=v,setForm:v=>formValues=v};
}
test('abrir Admin não inicia leitura, IA ou transporte; sem chave nenhuma chamada',async()=>{
 const t=setup('');t.events['admin-autorizado']();await t.elements['territorio-atualizar'].listeners.click();assert.equal(t.calls.length,0);
});
test('leitura é GET explícito e conteúdos são texto, com aprofundamento',async()=>{
 const t=setup();assert.equal(t.calls.length,0);await t.elements['territorio-atualizar'].listeners.click();
 assert.equal(t.calls.length,1);assert.equal(t.calls[0].options.method,undefined);
 const card=t.elements['territorio-cards'].children[0];assert.ok(card.children.some(c=>c.textContent==='<img onerror=alert(1)>'));
 card.children.find(c=>c.tag==='button').listeners.click();
 assert.equal(t.elements['territorio-detalhe'].hidden,false);
 assert.ok(!code.includes('innerHTML'));
});
test('IA somente por ação explícita e endpoint analítico',async()=>{
 const t=setup();await t.elements['territorio-interpretar'].listeners.click();
 const posts=t.calls.filter(c=>c.options.method==='POST');assert.equal(posts.length,1);assert.ok(posts[0].url.endsWith('/interpretar'));
});
test('retry de fato mantém chave e desconhecidos; nenhuma execução',async()=>{
 const t=setup();t.setForm([['tipo_registro','circulacao'],['origem','visita'],['responsavel','Direção'],['cidade',''],['quantidade',''],['metrica_conversoes','0']]);
 t.setFail(true);await t.elements['territorio-form'].listeners.submit({preventDefault(){}});
 t.setFail(false);await t.elements['territorio-form'].listeners.submit({preventDefault(){}});
 const posts=t.calls.filter(c=>c.options.method==='POST');assert.equal(posts.length,2);
 const a=JSON.parse(posts[0].options.body),b=JSON.parse(posts[1].options.body);
 assert.equal(a.chave,b.chave);assert.equal(a.cidade,null);assert.equal(a.quantidade,null);assert.equal(a.metricas.conversoes,0);
 assert.ok(t.calls.every(c=>c.url.startsWith('https://maranhao-cordial-api.onrender.com/api/admin/inteligencia-territorial')));
});
