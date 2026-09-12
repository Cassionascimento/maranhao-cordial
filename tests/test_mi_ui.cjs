const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/maranhao-intelligence.js','utf8');

function setup(key='test') {
  const calls=[],elements={};
  const events={};
  function node(){return {tag:'div',children:[],listeners:{},textContent:'',disabled:false,hidden:false,
    classList:{contains:()=>true},
    append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},
    addEventListener(k,fn){this.listeners[k]=fn}};}
  const document={createElement:node,getElementById:id=>elements[id] ||= node(),querySelector:()=>elements.tab ||= node()};
  const window={adminKeyAtual:key,addEventListener:(e,fn)=>events[e]=fn};
  const painel={success:true,
    resumo:{unidades:10,eventos:20,scans_qr:12,estabelecimentos:3,territorios_ativos:2},
    secundario:{skus:2,lotes:3,unidades_por_estado:{emitida:4,ativa:5,revogada:1}},
    atividade_recente:[{tipo_evento:'scan',canal:'qr',sku:'<img onerror=alert(1)>',criado_em:'2026-01-01T10:00:00Z',cidade:'Salvador',uf:'BA'}],
    produto:{por_sku:[{sku:'MC-100ML',produto_nome:'Concentrado',total:10}],por_lote:[{lote:'L001',total:6},{lote:'não associado',total:4}]},
    estabelecimentos_distribuicao:[{nome:'Bar do Zé',cidade:'Salvador',uf:'BA',total:8}],
    territorio:[{cidade:'Salvador',uf:'BA',total:8}]};
  vm.runInNewContext(code,{document,window,Number,
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>painel};}});
  return {calls,elements,events,painel};
}

test('sem chave admin, nenhuma chamada é feita', async()=>{
  const t=setup('');
  t.events['admin-autorizado']();
  await t.elements['mi-atualizar'].listeners.click();
  assert.equal(t.calls.length,0);
});

test('atualizar faz um GET simples e preenche o resumo sem innerHTML', async()=>{
  const t=setup();
  await t.elements['mi-atualizar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.equal(t.calls[0].options.method,undefined); // GET implícito, nunca POST/escrita
  assert.equal(t.calls[0].url,'https://maranhao-cordial-api.onrender.com/api/admin/mi/painel');
  assert.ok(!code.includes('innerHTML'));
  const resumo=t.elements['mi-resumo'];
  assert.equal(resumo.children.length,5); // 5 indicadores primários, não uma parede de cards
  assert.equal(t.elements['mi-conteudo'].hidden,false);
});

test('conteúdo malicioso vira texto, nunca é interpretado como HTML', async()=>{
  const t=setup();
  await t.elements['mi-atualizar'].listeners.click();
  const linhas=t.elements['mi-atividade'].children;
  const contemValor=linhas.some(n=>JSON.stringify(n).includes('<img onerror=alert(1)>'));
  assert.ok(contemValor);
  assert.ok(!code.includes('.innerHTML'));
});

test('nenhuma chamada de escrita é feita neste painel', async()=>{
  const t=setup();
  await t.elements['mi-atualizar'].listeners.click();
  assert.ok(t.calls.every(c=>!c.options.method || c.options.method==='GET'));
});
