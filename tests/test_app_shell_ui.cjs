const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

test('os seis domínios da nova arquitetura existem como metadados de navegação',()=>{
  for(const grupo of ['visao-geral','comercial','maranhao-intelligence','territorio','operacao','governanca']){
    assert.ok(html.includes(`data-grupo="${grupo}"`),`grupo ausente: ${grupo}`);
    assert.ok(html.includes(`data-app-grupo="${grupo}"`),`cabeçalho de grupo ausente: ${grupo}`);
  }
});

test('Governança existe como aba e como painel navegável',()=>{
  assert.match(html,/<button class="admin-tab"[^>]*data-tab="governanca"/);
  assert.match(html,/<section class="tab-panel"[^>]*data-panel="governanca"/);
});

test('Ações aguardando aprovação foi movida para dentro do painel de Governança, preservando os ids',()=>{
  const inicio=html.indexOf('data-panel="governanca"');
  assert.ok(inicio>-1,'painel de governança não encontrado');
  const bloco=html.slice(inicio,inicio+4000);
  for(const id of ['titulo-acoes-comerciais','atualizar-acoes-comerciais','status-acoes-comerciais','lista-acoes-comerciais']){
    assert.ok(bloco.includes(`id="${id}"`),`id ausente dentro de Governança: ${id}`);
  }
});

test('o card de aprovações não está mais solto fora de qualquer painel',()=>{
  const antesDoPrimeiroPainel=html.slice(html.indexOf('id="adminContent"'),html.indexOf('data-panel='));
  assert.ok(!antesDoPrimeiroPainel.includes('id="lista-acoes-comerciais"'));
});

test('nenhuma aba legada foi removida',()=>{
  for(const tab of ['visao-geral','ia-empresarial','crm','b2b','presenca-digital','empresa','inteligencia-territorial','maranhao-intelligence']){
    assert.ok(html.includes(`data-tab="${tab}"`),`aba legada removida: ${tab}`);
  }
});

test('nenhum painel legado foi removido',()=>{
  for(const painel of ['visao-geral','crm','b2b','presenca-digital','empresa','ia-empresarial','inteligencia-territorial','maranhao-intelligence']){
    assert.ok(html.includes(`data-panel="${painel}"`),`painel legado removido: ${painel}`);
  }
});

test('login/gating permanece intacto',()=>{
  assert.ok(html.includes('id="loginPanel"'));
  assert.ok(html.includes('id="adminContent"'));
  assert.ok(html.includes('id="entrarAdmin"'));
  assert.ok(html.includes('id="adminKey"'));
  assert.ok(html.includes('id="adminTabs"'));
});

test('Conectar Gmail continua presente, preservado (ainda não movido)',()=>{
  assert.ok(html.includes('conectarGmailP0()'));
  assert.ok(html.includes('id="gmailP0Status"'));
  assert.ok(html.includes('data-app-futuro-grupo="operacao"'));
});

test('app-shell é carregado sem bloquear o parser',()=>{
  assert.match(html,/<link rel="stylesheet" href="\/app-shell\.css">/);
  assert.match(html,/<script src="\/app-shell\.js" defer><\/script>/);
});
