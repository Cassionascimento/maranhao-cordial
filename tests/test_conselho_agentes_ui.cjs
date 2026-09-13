const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/conselho-agentes.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

const CONSELHO_OK = {
  agentes: [
    {codigo: 'leonard', nome: 'Leonard', area: 'Vendas', status: 'trabalhando', ultima_atividade: {tipo_evento: 'mensagem_enviada', criado_em: '2026-02-01T09:00:00+00:00'}},
    {codigo: 'marie', nome: 'Marie', area: 'Produto', status: 'sem_demanda', ultima_atividade: null},
  ],
  trabalhando: 1, sem_demanda: 1,
  mensagens_recentes: [
    {id: 'm1', de_agente: 'leonard', para_agente: 'rua', demanda_referencia: 'piloto-bacuri', texto: 'Capacidade confirmada?', criado_em: '2026-02-01T09:00:00+00:00'},
  ],
  reunioes_recentes: [
    {id: 'r1', tipo: 'conclave', demanda: 'Piloto Bacuri', contexto: 'Novo SKU', participantes: ['leonard', 'marie'],
     dados_apresentados: {vendas: 10}, posicoes: {leonard: 'a favor'}, conflitos: null, conclusao: 'Seguir com piloto restrito.',
     recomendacoes: [{responsavel: 'leonard', descricao: 'iniciar piloto'}], vetos: null, pendencias: null,
     precisa_diretor: true, versao: 1, criado_em: '2026-02-01T10:00:00+00:00'},
  ],
  relatorios_recentes: [
    {id: 'rel1', tipo: 'relatorio', demanda: 'Margem Bacuri', participantes: ['standard'], conclusao: 'Margem dentro do esperado.',
     precisa_diretor: false, criado_em: '2026-02-01T08:00:00+00:00'},
  ],
  conflitos: [], vetos: [], aguardando_diretor: [
    {id: 'r1', tipo: 'conclave', demanda: 'Piloto Bacuri', conclusao: 'Seguir com piloto restrito.', criado_em: '2026-02-01T10:00:00+00:00'},
  ],
};

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},
    className:'',
    classList:{_c:new Set(),add(c){this._c.add(c);},toggle(c,v){v?this._c.add(c):this._c.delete(c);},contains(c){return this._c.has(c);}},
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return null;},
  };
}

function setup({respostaConselho=CONSELHO_OK, ok=true, semChave=false, semPainel=false}={}) {
  const elementos={};
  const painel=no('div');
  painel.id='conselho-painel';
  const document={
    createElement:no,
    getElementById:id=>{
      if (id==='conselho-painel') return semPainel ? null : painel;
      return elementos[id] ||= no();
    },
    querySelector:sel=>{
      if (sel.includes('[data-tab="conselho-de-agentes"]')) return elementos.tabConselho ||= no('button');
      return null;
    },
  };
  const eventos={};
  const window={adminKeyAtual: semChave ? '' : 'chave-teste', addEventListener:(k,fn)=>{eventos[k]=fn;}};
  const calls=[];
  const fetchMock=async (url) => {
    calls.push(url);
    return {ok, json: async () => (ok ? {success:true, conselho: respostaConselho} : {success:false, error:'Conselho indisponível.'})};
  };
  const sandbox={document,window,fetch:fetchMock,console,JSON};
  vm.runInNewContext(code,sandbox);
  return {document,window,elementos,calls,eventos,painel};
}

test('sem chave administrativa, nenhuma chamada é feita',()=>{
  const t=setup({semChave:true});
  t.document.querySelector('[data-tab="conselho-de-agentes"]').listeners.click();
  assert.equal(t.calls.length,0);
});

test('carrega e mostra conteudo quando autorizado e a API responde bem',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.ok(t.calls[0].includes('/api/admin/mi/conselho'));
  assert.equal(t.elementos['conselho-conteudo'].hidden,false);
});

test('api indisponivel mostra estado explicado, nunca dado ficticio',async()=>{
  const t=setup({ok:false});
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.equal(t.document.getElementById('conselho-conteudo').hidden,true);
  assert.match(t.elementos['conselho-status'].textContent,/indisponível/);
});

test('resumo mostra as 6 estatisticas pedidas, na ordem certa',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const rotulos=t.elementos['conselho-resumo'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Agentes disponíveis','Trabalhando','Sem demanda','Conflitos','Vetos','Aguardando Diretor']);
});

test('cada agente vira um card com status, atividade, demanda, mensagem e relatorio',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const cards=t.elementos['conselho-agentes'].children;
  assert.equal(cards.length,2);
  const leonard=JSON.stringify(cards[0]);
  assert.match(leonard,/Leonard/);
  assert.match(leonard,/Vendas/);
  assert.match(leonard,/Trabalhando/);
  assert.match(leonard,/Capacidade confirmada/);
  const marie=JSON.stringify(cards[1]);
  assert.match(marie,/Sem demanda/);
  assert.match(marie,/nenhuma registrada/);
});

test('mensagens do conselho aparecem em tabela',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-mensagens']);
  assert.match(texto,/leonard/);
  assert.match(texto,/Capacidade confirmada/);
});

test('sem mensagens explica estado vazio',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, mensagens_recentes:[]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.match(t.elementos['conselho-mensagens'].children[0].textContent,/Nenhuma mensagem/);
});

test('reunioes aparecem em tabela com tipo e precisa diretor',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-reunioes']);
  assert.match(texto,/Conclave/);
  assert.match(texto,/Piloto Bacuri/);
});

test('atas mostram o registro completo (demanda, contexto, conclusao e blocos estruturados)',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/Piloto Bacuri/);
  assert.match(texto,/Seguir com piloto restrito/);
  assert.match(texto,/Recomendações/);
  assert.match(texto,/iniciar piloto/);
});

test('ata nao mostra bloco json para campos vazios (nao inventa estrutura)',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.doesNotMatch(texto,/"Vetos"/);
  assert.doesNotMatch(texto,/"Conflitos"/);
});

test('relatorios aparecem em tabela',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-relatorios']);
  assert.match(texto,/Margem Bacuri/);
  assert.match(texto,/Margem dentro do esperado/);
});

test('sem relatorios explica que so gera relatorio quando ha atividade real',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, relatorios_recentes:[]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.match(t.elementos['conselho-relatorios'].children[0].textContent,/atividade real/);
});

test('conflitos e vetos vazios mostram estado explicado',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.match(t.elementos['conselho-conflitos'].children[0].textContent,/Nenhum conflito/);
  assert.match(t.elementos['conselho-vetos'].children[0].textContent,/Nenhum veto/);
});

test('veto registrado nunca fica silenciosamente ignorado -- aparece em Vetos',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, vetos:[{registro_id:'r1', tipo:'conclave', vetos:{dicio:'risco regulatório'}}]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-vetos']);
  assert.match(texto,/risco regulatório/);
});

test('aguardando diretor aparece em tabela',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-diretor']);
  assert.match(texto,/Piloto Bacuri/);
});

test('nenhuma chamada de rede fora do endpoint de leitura do conselho',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  for (const url of t.calls) assert.ok(url.includes('/api/admin/mi/conselho'));
});

test('nenhuma escrita: so GET, sem method/body nas chamadas',()=>{
  assert.ok(!/method\s*:\s*['"](POST|PUT|DELETE)/i.test(code));
});

test('carrega automaticamente quando a aba ja esta ativa no evento admin-autorizado',async()=>{
  const t=setup();
  t.painel.classList.add('active');
  await t.eventos['admin-autorizado']();
  assert.equal(t.calls.length,1);
});

test('compatibilidade: conselho de agentes nao remove maranhao-intelligence nem modo-diretor',()=>{
  assert.ok(html.includes('id="conselho-painel"'));
  assert.ok(html.includes('id="mi-painel"'));
  assert.ok(html.includes('id="modo-diretor"'));
  assert.match(html,/<script src="\/conselho-agentes\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="\/conselho-agentes\.css">/);
  assert.match(html,/data-tab="conselho-de-agentes"/);
});
