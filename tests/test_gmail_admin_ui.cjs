const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/gmail-admin.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

function setup({chave='chave-teste', janelaAceita=true, readyState='complete'}={}) {
  const status={textContent:''};
  const botao={textContent:'Conectar Gmail institucional'};
  const registry={gmailP0Status: status};
  const listeners={};
  const document={
    readyState,
    getElementById:id=>registry[id] || null,
    querySelector:sel=> sel==='[onclick="conectarGmailP0()"]' ? botao : null,
    addEventListener:(evt,fn)=>{ listeners[evt]=fn; },
  };
  const window={
    adminKeyAtual: chave,
    open:(...args)=>{ window._openArgs=args; return janelaAceita ? {} : null; },
  };
  const sandbox={window,document};
  vm.runInNewContext(code,sandbox);
  return {status,botao,listeners,window,conectarGmailP0:sandbox.conectarGmailP0};
}

test('função extraída fica disponível globalmente (ponte para o onclick legado)',()=>{
  const t=setup();
  assert.equal(typeof t.window.conectarGmailP0,'function');
});

test('sem chave administrativa, não abre janela e avisa',()=>{
  const t=setup({chave:''});
  t.window.conectarGmailP0();
  assert.equal(t.status.textContent,'Entre na Central com a chave administrativa.');
  assert.equal(t.window._openArgs,undefined);
});

test('janela bloqueada pelo navegador avisa sem lançar erro',()=>{
  const t=setup({janelaAceita:false});
  t.window.conectarGmailP0();
  assert.equal(t.status.textContent,'O navegador bloqueou a nova aba. Permita pop-ups para abrir o Gmail.');
});

test('abre o Gmail institucional diretamente, sem popup de autorização nem postMessage',()=>{
  const t=setup();
  t.window.conectarGmailP0();
  assert.deepEqual(t.window._openArgs,[
    'https://mail.google.com/mail/u/0/','_blank','noopener,noreferrer',
  ]);
  assert.equal(t.status.textContent,'Gmail institucional aberto em nova aba.');
});

test('nenhum handshake de postMessage é usado (fluxo antigo de popup foi removido)',()=>{
  assert.ok(!/postMessage/.test(code));
  assert.ok(!/addEventListener\(\s*['"]message['"]/.test(code));
  assert.ok(!/setTimeout/.test(code));
});

test('OAuth de reconexão permanece disponível no backend (comentário/documentação preservados)',()=>{
  assert.match(code,/OAuth permanece disponível no backend/);
});

test('ao carregar (DOM já pronto), o texto do botão é atualizado para refletir a abertura direta',()=>{
  const t=setup({readyState:'complete'});
  assert.equal(t.botao.textContent,'Abrir Gmail institucional');
  assert.equal(t.listeners.DOMContentLoaded,undefined);
});

test('ao carregar (DOM ainda carregando), espera DOMContentLoaded antes de atualizar o botão',()=>{
  const t=setup({readyState:'loading'});
  assert.equal(t.botao.textContent,'Conectar Gmail institucional');
  assert.equal(typeof t.listeners.DOMContentLoaded,'function');
  t.listeners.DOMContentLoaded();
  assert.equal(t.botao.textContent,'Abrir Gmail institucional');
});

test('ausência do elemento de status não derruba a função (abre a aba mesmo assim)',()=>{
  const t=setup();
  const document={readyState:'complete',getElementById:()=>null,querySelector:()=>null,addEventListener:()=>{}};
  const sandbox={window:t.window,document};
  vm.runInNewContext(code,sandbox);
  assert.doesNotThrow(()=>sandbox.window.conectarGmailP0());
  assert.ok(t.window._openArgs);
});

test('chamada legada via onclick inline continua presente no admin.html',()=>{
  assert.match(html,/<button type="button" onclick="conectarGmailP0\(\)">Conectar Gmail institucional<\/button>/);
});

test('script extraído é carregado e a implementação antiga não fica duplicada no admin.html',()=>{
  assert.match(html,/<script src="\/gmail-admin\.js" defer><\/script>/);
  assert.ok(!html.includes('function conectarGmailP0'),'implementação antiga ainda presente inline em admin.html');
});
