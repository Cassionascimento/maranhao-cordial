const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/conselho-agentes.js','utf8');
const css=fs.readFileSync('maranhao-backend/conselho-agentes.css','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

test('mantem leitura existente do Conselho',()=>{
  assert.match(code,/\/api\/admin\/mi\/conselho/);
  assert.match(code,/renderAgentes/);
  assert.match(code,/renderMensagens/);
  assert.match(code,/renderReunioes/);
  assert.match(code,/renderAtas/);
  assert.match(code,/renderRelatorios/);
  assert.match(code,/renderConflitos/);
  assert.match(code,/renderVetos/);
  assert.match(code,/renderAguardandoDiretor/);
});

test('Perguntar ao Conselho oferece os tres modos',()=>{
  assert.match(code,/Perguntar ao Conselho/);
  assert.match(code,/Seleção automática/);
  assert.match(code,/Escolher especialistas/);
  assert.match(code,/Conclave completo/);
  assert.match(code,/name = 'modo'/);
});

test('lista os oito especialistas para escolha manual',()=>{
  for(const nome of ['Pirret','Standard','Zilda','Leonard','Marie','Rua','Dicio','Iris']) assert.match(code,new RegExp(nome));
});

test('aceita documento sem prometer persistencia do upload',()=>{
  assert.match(code,/\.pdf,\.docx,\.txt,\.md,\.csv,\.json/);
  assert.match(code,/até 8 MB/);
  assert.match(code,/não é salvo como upload/);
});

test('analise e envio ao Diretor sao duas acoes separadas',()=>{
  assert.match(code,/api \+ '\/analisar'/);
  assert.match(code,/api \+ '\/enviar-diretor'/);
  assert.match(code,/Enviar para decisão do Diretor/);
  assert.match(code,/Só este clique registra a análise/);
});

test('rotas de escrita continuam protegidas pela chave Admin',()=>{
  assert.match(code,/X-Admin-Key/);
  assert.match(code,/method: 'POST'/);
  assert.match(code,/window\.adminKeyAtual/);
});

test('resultado mostra pareceres sintese risco e veto',()=>{
  assert.match(code,/Pareceres do Conselho/);
  assert.match(code,/Síntese/);
  assert.match(code,/Riscos:/);
  assert.match(code,/Divergências:/);
  assert.match(code,/VETO:/);
});

test('interface deixa explicito que analise nao executa acao externa',()=>{
  assert.match(code,/Nenhuma ação externa é executada/);
  assert.match(code,/Nada foi executado externamente/);
});

test('estilos da nova consulta existem e continuam responsivos',()=>{
  assert.match(css,/\.conselho-consulta/);
  assert.match(css,/\.conselho-pareceres-grid/);
  assert.match(css,/@media \(max-width:720px\)/);
});

test('compatibilidade: Conselho, Maranhão Intelligence e Modo Diretor permanecem no Admin',()=>{
  assert.ok(html.includes('id="conselho-painel"'));
  assert.ok(html.includes('id="mi-painel"'));
  assert.ok(html.includes('id="modo-diretor"'));
  assert.match(html,/<script src="\/conselho-agentes\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="\/conselho-agentes\.css">/);
  assert.match(html,/data-tab="conselho-de-agentes"/);
});
