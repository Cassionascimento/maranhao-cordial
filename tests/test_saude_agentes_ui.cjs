const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/saude-agentes.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

test('painel de saude referencia a rota certa e nunca renderiza output_text/resposta bruta',()=>{
  assert.match(code,/\/api\/admin\/mi\/conselho\/saude/);
  assert.doesNotMatch(code,/output_text/);
});

test('admin.html registra a aba, o painel e o script de saude dos agentes',()=>{
  assert.ok(html.includes('data-tab="saude-agentes"'));
  assert.ok(html.includes('id="saude-agentes-painel"'));
  assert.ok(html.includes('src="/saude-agentes.js"'));
  assert.ok(html.includes('href="/mi-observabilidade.css"'));
});

function no(tag='div') {
  const obj = {tag,children:[],listeners:{},textContent:'',hidden:true,value:'24',title:'',
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    setAttribute(){},getAttribute(){return null;},removeAttribute(){},
    _classNameInterna:'',
  };
  obj.classList = {_c:new Set(), add(c){this._c.add(c);}, remove(c){this._c.delete(c);}, contains(c){return this._c.has(c);}};
  Object.defineProperty(obj,'className',{get(){return obj._classNameInterna;},set(v){obj._classNameInterna=v||'';}});
  return obj;
}

const AGENTES_OK = [
  {agente:'rua', status:'falha', ultima_execucao:'2026-09-15T10:00:00Z', duracao_ms:31000, modelo:'gpt-5-mini',
   erro_categoria:'RespostaLLMInvalida', erro_detalhe:'resposta_llm_incompleta:max_output_tokens',
   total_execucoes:3, total_sucesso:1, total_falha:2, taxa_sucesso:0.333, falhas_por_categoria:{RespostaLLMInvalida:2},
   tokens_saida_total:900},
  {agente:'iris', status:'sucesso', ultima_execucao:'2026-09-15T11:00:00Z', duracao_ms:2200, modelo:'gpt-5-mini',
   erro_categoria:null, erro_detalhe:null, total_execucoes:4, total_sucesso:4, total_falha:0, taxa_sucesso:1,
   falhas_por_categoria:{}, tokens_saida_total:1400},
];

function setup({agentes=AGENTES_OK, ok=true, semChave=false}={}) {
  const elementos={};
  const painel=no('div'); painel.id='saude-agentes-painel';
  const document={
    createElement:no,
    getElementById:id=>{ if (id==='saude-agentes-painel') return painel; return elementos[id] ||= no(); },
  };
  const window={adminKeyAtual: semChave ? '' : 'chave-teste'};
  const calls=[];
  const fetchMock=async (url) => {
    calls.push(url);
    return {ok, json: async () => (ok ? {success:true, janela_horas:24, agentes} : {success:false, error:'Painel de saúde indisponível.'})};
  };
  const sandbox={document,window,fetch:fetchMock,console,Object,Number,Math,Date,String,JSON};
  vm.runInNewContext(code, sandbox);
  return {document,window,elementos,calls,painel};
}

test('atualizar consulta a rota com a janela selecionada',async()=>{
  const t=setup();
  t.elementos['saude-agentes-janela'].value='168';
  await t.elementos['saude-agentes-atualizar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.ok(t.calls[0].includes('janela_horas=168'));
  assert.equal(t.elementos['saude-agentes-conteudo'].hidden,false);
});

test('agente com falha aparece como falha explicita, nunca escondido',async()=>{
  const t=setup();
  await t.elementos['saude-agentes-atualizar'].listeners.click();
  const tabela = t.elementos['saude-agentes-conteudo'].children.find(c=>c.tag==='table');
  const linhaRua = tabela.children.find(c=>c.tag==='tbody').children[0];
  assert.equal(linhaRua.className.includes('saude-linha-falha'), true);
});

test('sem chave admin nao chama a API',async()=>{
  const t=setup({semChave:true});
  await t.elementos['saude-agentes-atualizar'].listeners.click();
  assert.equal(t.calls.length,0);
});

test('falha da API mostra mensagem sem quebrar',async()=>{
  const t=setup({ok:false});
  await t.elementos['saude-agentes-atualizar'].listeners.click();
  assert.equal(t.elementos['saude-agentes-status'].textContent,'Painel de saúde indisponível.');
});
