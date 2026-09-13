const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/modo-diretor.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

const LEITURA_OK = {
  ia_trabalhando: true,
  chamar_diretor: {necessario: false, motivos: []},
  hoje: {planejado: [{}], concluido: [{}, {}], aguardando: [{}], bloqueado: [], oportunidades: [{prioridade:'alta'}]},
  proxima_acao_ia: {o_que: 'pesquisar', quando: '2026-02-01T09:00:00+00:00', motivo: 'faltam contatos'},
  publico: {
    top10: [
      {posicao: 1, tema: 'degustacao', natureza: 'interesse_observado', tendencia: 'subindo'},
      {posicao: 2, tema: 'guarana', natureza: 'fato', tendencia: 'caindo'},
    ],
    conteudos_sugeridos_hoje: [
      {detalhe_conteudo: {slot: 'manha', tema: 'cultura', formato: 'reels', objetivo: 'descoberta_cultura', cta: 'Descubra mais.'}},
    ],
  },
  comercial: {prospectos_encontrados: 10, prospectos_qualificados: 4, followups: [{}], oportunidades: [{}]},
  calendario: {hoje: 3, proximas: 5, concluidas: 2, bloqueadas: 0},
  site: {visitas: 120, interesses: 30, ctas: 8, conversoes: 5, produto_em_alta: 'guarana',
         origem_em_alta: 'instagram_bio', mudanca_relevante: false},
  conselho: {
    agentes: [
      {codigo: 'leonard', nome: 'Leonard', area: 'Vendas', status: 'trabalhando', ultima_atividade: {tipo_evento: 'mensagem_enviada', criado_em: '2026-02-01T09:00:00+00:00'}},
      {codigo: 'marie', nome: 'Marie', area: 'Produto', status: 'sem_demanda', ultima_atividade: null},
    ],
    trabalhando: 1, sem_demanda: 1,
    mensagens_recentes: [], reunioes_recentes: [], relatorios_recentes: [],
    reuniao_mais_recente: {tipo: 'conclave', demanda: 'Piloto Bacuri', conclusao: 'Seguir com piloto restrito.'},
    conflitos: [], vetos: [], aguardando_diretor: [],
  },
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

function setup({respostaLeitura=LEITURA_OK, ok=true, semChave=false, semRaiz=false}={}) {
  const elementos={};
  const tabButtons={'conselho-de-agentes':no('button')};
  for (const k in tabButtons) tabButtons[k].click=()=>{tabButtons[k]._clicado=true;};
  const raiz=no('div');
  raiz.id='modo-diretor';
  const document={
    createElement:no,
    createTextNode:text=>({tag:'#text',textContent:text}),
    getElementById:id=>{
      if (id==='modo-diretor') return semRaiz ? null : raiz;
      return elementos[id] ||= no();
    },
    querySelector:sel=>{
      const m=sel.match(/data-tab="([^"]+)"/);
      if (sel.includes('[data-tab="visao-geral"]')) return elementos.tabVisaoGeral ||= no('button');
      if (sel.includes('data-panel="visao-geral"')) return elementos.painelAtivo ||= (() => { const p=no(); p.classList.add('active'); return p; })();
      if (m && tabButtons[m[1]]) return tabButtons[m[1]];
      return null;
    },
  };
  const eventos={};
  const window={adminKeyAtual: semChave ? '' : 'chave-teste', addEventListener:(k,fn)=>{eventos[k]=fn;}};
  const calls=[];
  const fetchMock=async (url) => {
    calls.push(url);
    return {ok, json: async () => (ok ? {success:true, leitura: respostaLeitura} : {success:false})};
  };
  const sandbox={document,window,fetch:fetchMock,console};
  vm.runInNewContext(code,sandbox);
  return {document,window,elementos,calls,eventos,tabButtons,raiz};
}

test('sem chave administrativa, nenhuma chamada é feita',()=>{
  const t=setup({semChave:true});
  t.document.querySelector('[data-tab="visao-geral"]').listeners.click();
  assert.equal(t.calls.length,0);
});

test('carrega e mostra conteúdo quando autorizado e a API responde bem',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.ok(t.calls[0].includes('/api/admin/mi/diretor'));
  assert.equal(t.elementos['md-conteudo-geral'].hidden,false);
  assert.equal(t.elementos['md-indisponivel'].hidden,true);
});

test('api indisponível (503/erro) mostra estado explicado, nunca dado fictício',async()=>{
  const t=setup({ok:false});
  await t.elementos['md-atualizar'].listeners.click();
  assert.equal(t.elementos['md-conteudo-geral'].hidden,true);
  assert.equal(t.elementos['md-indisponivel'].hidden,false);
  assert.match(t.elementos['md-indisponivel'].textContent,/migrations 013.*015/);
});

test('status reflete precisa_de_voce antes de ia_trabalhando',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, chamar_diretor:{necessario:true,motivos:['bloqueio relevante']}}});
  await t.elementos['md-atualizar'].listeners.click();
  const status=t.elementos['md-status'];
  assert.equal(status.className,'md-status md-status-precisa');
  assert.equal(status.children[1].textContent,'Precisa de você');
});

test('sem pendencias e ia trabalhando mostra IA trabalhando',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const status=t.elementos['md-status'];
  assert.equal(status.className,'md-status md-status-trabalhando');
});

test('hoje mostra os 4 números pedidos, na ordem certa',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const rotulos=t.elementos['md-hoje'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Planejado','Concluído','Aguardando','Oportunidades']);
  const valores=t.elementos['md-hoje'].children.map(c=>c.children[0].textContent);
  assert.deepEqual(valores,['1','2','1','1']);
});

test('proxima acao mostra o que, quando e motivo',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['md-proxima']);
  assert.match(texto,/Pesquisar/i);
  assert.match(texto,/faltam contatos/);
  assert.match(texto,/01\/02/);
});

test('sem proxima acao mostra estado vazio explicado',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, proxima_acao_ia:null}});
  await t.elementos['md-atualizar'].listeners.click();
  assert.equal(t.elementos['md-proxima'].children[0].className,'vg-vazio');
});

test('precisa de voce mostra NADA quando nao necessario',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  assert.equal(t.elementos['md-precisa'].children[0].className,'md-precisa-nada');
});

test('precisa de voce lista os motivos quando necessario',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, chamar_diretor:{necessario:true,motivos:['decisão necessária','bloqueio relevante']}}});
  await t.elementos['md-atualizar'].listeners.click();
  const lista=t.elementos['md-precisa'].children[0];
  assert.equal(lista.children.length,2);
});

test('top10 mostra posicao, tema, selo de natureza e tendencia',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const lista=t.elementos['md-top10'].children[0];
  assert.equal(lista.children.length,2);
  const primeiro=lista.children[0];
  const classes=primeiro.children.map(c=>c.className);
  assert.ok(classes.includes('md-posicao'));
  assert.ok(classes.includes('md-tema'));
  assert.ok(classes.some(c=>c.startsWith('md-natureza')));
  assert.ok(classes.some(c=>c.startsWith('md-tendencia')));
});

test('top10 vazio explica que ainda nao ha sinais suficientes',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, publico:{top10:[],conteudos_sugeridos_hoje:[]}}});
  await t.elementos['md-atualizar'].listeners.click();
  assert.match(t.elementos['md-top10'].children[0].textContent,/aguardando sinais/);
});

test('conteudo de hoje mostra os campos pedidos por card',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const grade=t.elementos['md-conteudo'].children[0];
  const card=grade.children[0];
  const texto=JSON.stringify(card);
  assert.match(texto,/Manhã/);
  assert.match(texto,/cultura/);
  assert.match(texto,/Reels/);
  assert.match(texto,/Descoberta e cultura/);
  assert.match(texto,/Descubra mais/);
});

test('comercial mostra os 4 numeros pedidos',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const rotulos=t.elementos['md-comercial'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Prospectos encontrados','Qualificados','Follow-ups','Oportunidades']);
});

test('site agora mostra visitas/interesses/ctas/conversoes na ordem certa',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const rotulos=t.elementos['md-site'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Visitas','Interesses','CTAs clicados','Conversões']);
  const valores=t.elementos['md-site'].children.map(c=>c.children[0].textContent);
  assert.deepEqual(valores,['120','30','8','5']);
});

test('site agora destaca produto e origem em alta',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const texto=t.elementos['md-site-destaque'].textContent;
  assert.match(texto,/Guaraná/);
  assert.match(texto,/instagram_bio/);
});

test('sem produto/origem em alta explica que ainda nao ha destaque',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, site:{visitas:0,interesses:0,ctas:0,conversoes:0,produto_em_alta:null,origem_em_alta:null,mudanca_relevante:false}}});
  await t.elementos['md-atualizar'].listeners.click();
  assert.match(t.elementos['md-site-destaque'].textContent,/Sem destaque/);
});

test('calendario mostra hoje/proximas/concluidas/bloqueadas sem recalcular',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const faixa=t.elementos['md-calendario'].children[0];
  const valores=faixa.children.map(c=>c.children[0].textContent);
  assert.deepEqual(valores,['3','5','2','0']);
});

test('conselho mostra agentes disponiveis/trabalhando/sem demanda',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const stats=t.elementos['md-conselho'].children[0];
  const rotulos=stats.children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Agentes disponíveis','Trabalhando','Sem demanda']);
  const valores=stats.children.map(c=>c.children[0].textContent);
  assert.deepEqual(valores,['2','1','1']);
});

test('conselho lista apenas os agentes com demanda em Agora',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const agora=t.elementos['md-conselho'].children[1];
  const lista=agora.children[1];
  assert.equal(lista.children.length,1);
  assert.match(lista.children[0].textContent,/Leonard/);
});

test('conselho sem nenhum agente trabalhando explica estado vazio',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, conselho:{...LEITURA_OK.conselho, agentes:LEITURA_OK.conselho.agentes.map(a=>({...a,status:'sem_demanda',ultima_atividade:null})), trabalhando:0, sem_demanda:2}}});
  await t.elementos['md-atualizar'].listeners.click();
  const agora=t.elementos['md-conselho'].children[1];
  assert.equal(agora.children[1].className,'vg-vazio');
});

test('conselho mostra a reuniao mais recente (conclave) com demanda e conclusao',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['md-conselho'].children[2]);
  assert.match(texto,/Piloto Bacuri/);
  assert.match(texto,/Seguir com piloto restrito/);
});

test('conselho sem reuniao registrada explica estado vazio',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, conselho:{...LEITURA_OK.conselho, reuniao_mais_recente:null}}});
  await t.elementos['md-atualizar'].listeners.click();
  const bloco=t.elementos['md-conselho'].children[2];
  assert.equal(bloco.children[1].className,'vg-vazio');
});

test('conselho sem conflitos/vetos/pendencias mostra nada pendente',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const pendente=t.elementos['md-conselho'].children[3];
  assert.equal(pendente.children[1].className,'md-precisa-nada');
});

test('conselho com veto soma conflitos+vetos+aguardando diretor em precisa de voce',async()=>{
  const t=setup({respostaLeitura:{...LEITURA_OK, conselho:{...LEITURA_OK.conselho, vetos:[{registro_id:'1'}], aguardando_diretor:[{}]}}});
  await t.elementos['md-atualizar'].listeners.click();
  const pendente=t.elementos['md-conselho'].children[3];
  assert.match(pendente.children[1].textContent,/2 itens pendentes/);
});

test('botao "ver conselho completo" aciona a aba conselho-de-agentes sem reimplementar navegacao',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  const alvo={dataset:{vgTab:'conselho-de-agentes'},closest:()=>alvo};
  t.raiz.listeners.click({target:alvo});
  assert.ok(t.tabButtons['conselho-de-agentes']._clicado);
});

test('nenhuma chamada de rede fora do endpoint de leitura do diretor',async()=>{
  const t=setup();
  await t.elementos['md-atualizar'].listeners.click();
  for (const url of t.calls) assert.ok(url.includes('/api/admin/mi/diretor'));
});

test('nenhuma escrita: so GET, sem method/body nas chamadas',()=>{
  assert.ok(!/method\s*:\s*['"](POST|PUT|DELETE)/i.test(code));
});

test('carrega automaticamente quando a aba ja esta ativa no evento admin-autorizado',async()=>{
  const t=setup();
  await t.eventos['admin-autorizado']();
  assert.equal(t.calls.length,1);
});

test('compatibilidade: modo diretor nao remove visao-geral-executiva nem painel-executivo',()=>{
  assert.ok(html.includes('id="modo-diretor"'));
  assert.ok(html.includes('id="visao-geral-executiva"'));
  assert.ok(html.includes('id="painel-executivo"'));
  assert.match(html,/<script src="\/modo-diretor\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="\/modo-diretor\.css">/);
});
