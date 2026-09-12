const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/gmail-admin.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

function setup({chave='chave-teste', janelaAceita=true}={}) {
  const status={textContent:''};
  const listeners={};
  const janela={postMessage(){ janela._mensagens.push([...arguments]); }, _mensagens:[]};
  const timers=[];
  const window={
    adminKeyAtual: chave,
    open:(...args)=>{ window._openArgs=args; return janelaAceita ? janela : null; },
    addEventListener:(evt,fn)=>{ listeners[evt]=fn; },
    removeEventListener:(evt,fn)=>{ if(listeners[evt]===fn) delete listeners[evt]; },
  };
  const document={getElementById:id=>id==='gmailP0Status' ? status : null};
  const sandbox={window,document,
    setTimeout:(fn,ms)=>{ const t={fn,ms,cancelado:false}; timers.push(t); return t; },
    clearTimeout:(t)=>{ if(t) t.cancelado=true; }};
  vm.runInNewContext(code,sandbox);
  return {status,listeners,janela,timers,window,conectarGmailP0:sandbox.conectarGmailP0};
}

test('função extraída fica disponível globalmente (ponte para o onclick legado)',()=>{
  const t=setup();
  assert.equal(typeof t.window.conectarGmailP0,'function');
});

test('sem chave administrativa, não abre janela e avisa (tratamento de erro equivalente)',()=>{
  const t=setup({chave:''});
  t.window.conectarGmailP0();
  assert.equal(t.status.textContent,'Entre na Central com a chave administrativa.');
  assert.equal(t.window._openArgs,undefined);
});

test('janela bloqueada pelo navegador avisa sem lançar erro',()=>{
  const t=setup({janelaAceita:false});
  t.window.conectarGmailP0();
  assert.equal(t.status.textContent,'Permita a abertura da janela para conectar o Gmail.');
});

test('endpoint e método (abrir janela, não fetch) permanecem inalterados',()=>{
  const t=setup();
  t.window.conectarGmailP0();
  assert.deepEqual(t.window._openArgs,[
    'https://maranhao-cordial-api.onrender.com/api/gmail/painel','_blank','width=640,height=760',
  ]);
});

test('renderização equivalente: status de sucesso e mensagem correta enviada à janela',()=>{
  const t=setup({chave:'abc123'});
  t.window.conectarGmailP0();
  assert.equal(t.status.textContent,'Conclua a autorização na janela do Gmail.');
  t.listeners.message({origin:'https://maranhao-cordial-api.onrender.com',source:t.janela,data:{tipo:'gmail-p0-pronto'}});
  const [mensagem,destino]=t.janela._mensagens[0];
  assert.equal(mensagem.tipo,'gmail-p0-autorizar');
  assert.equal(mensagem.chave,'abc123');
  assert.equal(destino,'https://maranhao-cordial-api.onrender.com');
  assert.equal(t.listeners.message,undefined); // listener removido após concluir
  assert.equal(t.timers[0].cancelado,true); // timeout cancelado após concluir
});

test('mensagem de origem/fonte/tipo diferentes é ignorada',()=>{
  const t=setup();
  t.window.conectarGmailP0();
  t.listeners.message({origin:'https://outro.example',source:t.janela,data:{tipo:'gmail-p0-pronto'}});
  assert.equal(t.janela._mensagens.length,0);
  assert.ok(t.listeners.message); // continua esperando a mensagem certa
});

test('sem resposta a tempo, timeout avisa e remove o listener',()=>{
  const t=setup();
  t.window.conectarGmailP0();
  t.timers[0].fn();
  assert.equal(t.status.textContent,'Conexão não iniciada. Feche a janela e tente novamente.');
  assert.equal(t.listeners.message,undefined);
});

test('ausência do elemento de status preserva o comportamento original (mesma falha, nada novo)',()=>{
  // O código original nunca teve proteção contra #gmailP0Status ausente; a extração
  // não pode introduzir nem remover essa proteção -- só preservar o que já existia.
  const t=setup();
  const document={getElementById:()=>null};
  const sandbox={window:t.window,document,setTimeout:()=>{},clearTimeout:()=>{}};
  vm.runInNewContext(code,sandbox);
  assert.throws(()=>sandbox.window.conectarGmailP0(),err=>err.name==='TypeError');
  // A falha acontece antes de qualquer listener/timer ser registrado.
  assert.equal(t.listeners.message,undefined);
});

test('chamada legada via onclick inline continua presente no admin.html',()=>{
  assert.match(html,/<button type="button" onclick="conectarGmailP0\(\)">Conectar Gmail institucional<\/button>/);
});

test('script extraído é carregado e a implementação antiga não fica duplicada no admin.html',()=>{
  assert.match(html,/<script src="\/gmail-admin\.js" defer><\/script>/);
  assert.ok(!html.includes('function conectarGmailP0'),'implementação antiga ainda presente inline em admin.html');
});
