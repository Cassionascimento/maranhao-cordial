const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/conselho-testes.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

test('painel referencia a rota de execucao da bateria',()=>{
  assert.match(code,/\/api\/admin\/mi\/conselho\/testes\/executar/);
  assert.match(code,/incluir_ao_vivo/);
});

test('admin.html registra a aba, o painel e o script do testing center',()=>{
  assert.ok(html.includes('data-tab="conselho-testes"'));
  assert.ok(html.includes('id="conselho-testes-painel"'));
  assert.ok(html.includes('src="/conselho-testes.js"'));
});

function no(tag='div') {
  const obj = {tag,children:[],listeners:{},textContent:'',hidden:true,
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    setAttribute(){},getAttribute(){return null;},removeAttribute(){},
    _classNameInterna:'',
  };
  obj.classList = {_c:new Set(), add(c){this._c.add(c);}, remove(c){this._c.delete(c);}, contains(c){return this._c.has(c);}};
  Object.defineProperty(obj,'className',{get(){return obj._classNameInterna;},set(v){obj._classNameInterna=v||'';}});
  return obj;
}

const RESULTADO_MISTO = {
  success:true, total:3, aprovados:2, falharam:1,
  resultados:[
    {id:'schema', grupo:'unitario', descricao:'schema ok', passou:true, motivo:'ok'},
    {id:'ao_vivo_rua_isolado', grupo:'ao_vivo', descricao:'rua isolado', passou:true, motivo:'confiança=media'},
    {id:'ao_vivo_conjunto', grupo:'ao_vivo', descricao:'conjunto', passou:false, motivo:'RespostaLLMInvalida: resposta_llm_incompleta:max_output_tokens'},
  ],
};

function setup({resultado=RESULTADO_MISTO, ok=true, semChave=false, confirma=true}={}) {
  const elementos={};
  const painel=no('div'); painel.id='conselho-testes-painel';
  const document={
    createElement:no,
    getElementById:id=>{ if (id==='conselho-testes-painel') return painel; return elementos[id] ||= no(); },
  };
  const window={adminKeyAtual: semChave ? '' : 'chave-teste', confirm:()=>confirma};
  const calls=[];
  const fetchMock=async (url,opts) => {
    calls.push({url, body: opts && opts.body ? JSON.parse(opts.body) : null});
    return {ok, json: async () => (ok ? resultado : {success:false, error:'Não foi possível rodar a bateria de testes.'})};
  };
  const sandbox={document,window,fetch:fetchMock,console,JSON,Object};
  vm.runInNewContext(code, sandbox);
  return {document,window,elementos,calls,painel};
}

test('rodar (sem ao vivo) chama a API com incluir_ao_vivo=false',async()=>{
  const t=setup();
  await t.elementos['conselho-testes-rodar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.equal(t.calls[0].body.incluir_ao_vivo,false);
  assert.equal(t.elementos['conselho-testes-conteudo'].hidden,false);
});

test('rodar ao vivo pede confirmacao antes de custar tokens reais',async()=>{
  const t=setup({confirma:false});
  await t.elementos['conselho-testes-rodar-ao-vivo'].listeners.click();
  assert.equal(t.calls.length,0);
});

test('confirmando, roda ao vivo com incluir_ao_vivo=true',async()=>{
  const t=setup({confirma:true});
  await t.elementos['conselho-testes-rodar-ao-vivo'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.equal(t.calls[0].body.incluir_ao_vivo,true);
});

test('resultado mostra aprovados/falharam e nao esconde falha',async()=>{
  const t=setup();
  await t.elementos['conselho-testes-rodar'].listeners.click();
  assert.equal(t.elementos['conselho-testes-status'].textContent,'2/3 casos aprovados.');
});

test('sem chave admin nao chama a API',async()=>{
  const t=setup({semChave:true});
  await t.elementos['conselho-testes-rodar'].listeners.click();
  assert.equal(t.calls.length,0);
});
