const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
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

test('css protege contra overflow de token tecnico longo (causa real do bug de sobreposicao/corte)',()=>{
  assert.match(css,/overflow-wrap:\s*anywhere/);
  assert.match(css,/#conselho-painel\s*\{[^}]*overflow-x:\s*hidden/);
  assert.match(css,/\.conselho-parecer-card[^}]*min-width:\s*0/s);
});

test('compatibilidade: Conselho, Maranhão Intelligence e Modo Diretor permanecem no Admin',()=>{
  assert.ok(html.includes('id="conselho-painel"'));
  assert.ok(html.includes('id="mi-painel"'));
  assert.ok(html.includes('id="modo-diretor"'));
  assert.match(html,/<script src="\/conselho-agentes\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="\/conselho-agentes\.css">/);
  assert.match(html,/data-tab="conselho-de-agentes"/);
});

// ---------------------------------------------------------------------
// Apresentação executiva das Atas (leitura histórica) -- harness de DOM
// completo, porque aqui o que importa é o COMPORTAMENTO de renderização,
// não só a presença de strings no código-fonte.
// ---------------------------------------------------------------------

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
    // posicoes.leonard fica como STRING pura de propósito -- é o formato de
    // um registro antigo (anterior à mudança em _consolidar), o painel
    // precisa continuar lendo isso sem quebrar nem inventar campo nenhum.
    {id: 'r1', tipo: 'conclave', demanda: 'Piloto Bacuri', contexto: 'Novo SKU', participantes: ['leonard', 'marie'],
     dados_apresentados: {vendas: 10}, posicoes: {leonard: 'a favor'}, conflitos: null, conclusao: 'Seguir com piloto restrito.',
     recomendacoes: [{responsavel: 'leonard', descricao: 'iniciar piloto', confianca: 'media'}], vetos: null, pendencias: null,
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

// Registro no formato NOVO (posicoes estruturado, o que mi_conselho_executor
// grava depois da mudança em _consolidar), com dois agentes reais e uma
// recomendação só de um deles -- para testar Evidências/Riscos/Recomendação
// por agente e a Síntese independente.
const REGISTRO_ESTRUTURADO = {
  id: 'r2', tipo: 'reuniao', versao: 1, criado_em: '2026-02-02T10:00:00+00:00',
  demanda: 'Quero saber se fiz uma boa ideia em colocar parte das músicas no Instagram novamente.',
  contexto: 'pergunta direta do Diretor',
  participantes: ['iris', 'leonard'],
  posicoes: {
    iris: {
      conclusao: 'Ainda não há evidência suficiente para afirmar que voltar a publicar músicas melhorará o desempenho do Instagram.',
      confianca: 'media',
      dados_utilizados: 'Há conteúdos para Instagram já previstos no calendário. Instagram aparece entre os canais associados a segmentos relevantes.',
      riscos: 'nenhum risco imediato',
    },
    leonard: { conclusao: 'Vendas concorda com o teste, mas a base de leads do Instagram ainda é pequena.', confianca: 'media', dados_utilizados: '', riscos: 'risco de canibalizar orçamento de outro canal' },
  },
  conflitos: null,
  recomendacoes: [{responsavel: 'iris', descricao: 'Testar uma publicação musical e comparar com conteúdos recentes.', confianca: 'media'}],
  vetos: null, pendencias: null, precisa_diretor: false,
  conclusao: 'Iris: Ainda não há evidência suficiente...; Leonard: Vendas concorda com o teste...',
};

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},
    className:'',open:undefined,
    classList:{_c:new Set(),add(c){this._c.add(c);},toggle(c,v){v?this._c.add(c):this._c.delete(c);},contains(c){return this._c.has(c);}},
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return null;},
    querySelector(){return null;}, querySelectorAll(){return [];},
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
  const sandbox={document,window,fetch:fetchMock,console,JSON,FormData:class{append(){}}};
  vm.runInNewContext(code, sandbox);
  return {document,window,elementos,calls,eventos,painel};
}

function achar(no_, regex, achados=[]) {
  if (typeof no_.textContent === 'string' && regex.test(no_.textContent)) achados.push(no_);
  for (const filho of (no_.children || [])) achar(filho, regex, achados);
  return achados;
}

function acharPorClasse(no_, classe) {
  const classes = String(no_.className || '').split(/\s+/);
  if (classes.includes(classe)) return no_;
  for (const filho of (no_.children || [])) {
    const achado = acharPorClasse(filho, classe);
    if (achado) return achado;
  }
  return null;
}

test('carrega e mostra conteudo quando autorizado e a API responde bem',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.equal(t.calls.length,1);
  assert.ok(t.calls[0].includes('/api/admin/mi/conselho'));
  assert.equal(t.elementos['conselho-conteudo'].hidden,false);
});

test('sem mensagens explica estado vazio (uma linha so, sem details)',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, mensagens_recentes:[]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const container=t.elementos['conselho-mensagens'];
  assert.match(container.children[0].textContent,/Nenhuma mensagem/);
  assert.notEqual(container.children[0].tag,'details');
});

test('com mensagens, a secao vira <details> aberto com contador',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const container=t.elementos['conselho-mensagens'];
  assert.equal(container.children[0].tag,'details');
  assert.equal(container.children[0].open,true);
  assert.match(container.children[0].children[0].textContent,/1 mensagem/);
});

test('ata mostra demanda e continua preservando os dados de auditoria',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/Piloto Bacuri/);
  assert.match(texto,/Dados técnicos \(auditoria\)/);
  assert.match(texto,/Seguir com piloto restrito/);
  assert.match(texto,/Recomendações/);
  assert.match(texto,/iniciar piloto/);
});

test('ata nao mostra bloco json de auditoria para campos vazios',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.doesNotMatch(texto,/"Vetos"/);
  assert.doesNotMatch(texto,/"Conflitos"/);
});

test('ata aceita posicoes em formato antigo (string simples) sem quebrar',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/a favor/);
  assert.match(texto,/Não há dados suficientes para concluir/);
});

test('parecer executivo mostra confianca, conclusao, evidencias em bullets e recomendacao do agente',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_ESTRUTURADO]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/Iris · Dados/);
  assert.match(texto,/Confiança: media/);
  assert.match(texto,/Há conteúdos para Instagram já previstos no calendário/);
  assert.match(texto,/Testar uma publicação musical/);
});

test('riscos triviais nao aparecem no parecer executivo; riscos materiais aparecem',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_ESTRUTURADO]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const pareceres=JSON.stringify(acharPorClasse(t.elementos['conselho-atas'],'conselho-pareceres-grid'));
  assert.doesNotMatch(pareceres,/nenhum risco imediato/);
  assert.match(pareceres,/risco de canibalizar orçamento/);
  const auditoria=JSON.stringify(acharPorClasse(t.elementos['conselho-atas'],'conselho-auditoria'));
  assert.match(auditoria,/nenhum risco imediato/);
});

test('agente sem recomendacao propria mostra "nenhuma acao recomendada"',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_ESTRUTURADO]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/Nenhuma ação recomendada/);
});

test('sintese do conselho aparece com decisao, por que, proximo passo e precisa do diretor',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_ESTRUTURADO]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/Síntese do Conselho/);
  assert.match(texto,/O Conselho recomenda seguir com a orientação de Iris/);
  assert.match(texto,/Precisa do Diretor: Não/);
});

test('sintese nunca repete literalmente o texto de conclusao de um agente, mesmo com um so participante',async()=>{
  const registroUmAgente = {...REGISTRO_ESTRUTURADO, participantes:['iris'],
    posicoes:{iris: REGISTRO_ESTRUTURADO.posicoes.iris}, recomendacoes:[REGISTRO_ESTRUTURADO.recomendacoes[0]]};
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[registroUmAgente]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const sintese=acharPorClasse(t.elementos['conselho-atas'],'conselho-sintese');
  const textoDecisao=sintese.children[1].textContent; // [0]=h4 "Síntese do Conselho", [1]=p da decisão
  assert.notEqual(textoDecisao, REGISTRO_ESTRUTURADO.posicoes.iris.conclusao);
  assert.ok(!textoDecisao.includes(REGISTRO_ESTRUTURADO.posicoes.iris.conclusao));
  assert.match(textoDecisao,/Iris/);
});

test('veto flui para o parecer do agente e para a sintese, nunca fica silencioso',async()=>{
  const registroVetado = {...REGISTRO_ESTRUTURADO, vetos:{iris:'dado insuficiente para publicar como fato'}, precisa_diretor:true};
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[registroVetado]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-atas']);
  assert.match(texto,/VETO: dado insuficiente para publicar como fato/);
  assert.match(texto,/vetou esta demanda/);
});

test('participante sem posicao registrada mostra "nao ha dados suficientes"',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const acha=achar(t.elementos['conselho-atas'],/Não há dados suficientes para concluir/);
  assert.ok(acha.length>=1);
});

test('conflitos e vetos vazios mostram estado explicado',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.match(t.elementos['conselho-conflitos'].children[0].textContent,/Nenhum conflito/);
  assert.match(t.elementos['conselho-vetos'].children[0].textContent,/Nenhum veto/);
});

test('veto registrado (lista) nunca fica silenciosamente ignorado -- aparece em Vetos',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, vetos:[{registro_id:'r1', tipo:'conclave', vetos:{dicio:'risco regulatório'}}]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-vetos']);
  assert.match(texto,/risco regulatório/);
});

test('card do agente mostra a demanda (fato curto), nunca a conclusao consolidada bruta',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, relatorios_recentes:[
    {id:'rel1', tipo:'relatorio', demanda:'Margem Bacuri', participantes:['leonard'],
     conclusao:'Leonard: texto tecnico longo; Iris: outro texto tecnico', precisa_diretor:false, criado_em:'2026-02-01T08:00:00+00:00'},
  ]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const leonard=JSON.stringify(t.elementos['conselho-agentes'].children[0]);
  assert.match(leonard,/Margem Bacuri/);
  assert.doesNotMatch(leonard,/texto tecnico/);
});

test('nenhuma escrita na leitura: GET simples para o Conselho',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  for (const url of t.calls) assert.ok(url.includes('/api/admin/mi/conselho'));
});
