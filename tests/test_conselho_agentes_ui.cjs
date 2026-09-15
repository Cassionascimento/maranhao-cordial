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

test('radio/checkbox do modo e dos especialistas nao herdam o input{width:100%} global (causa real medida em producao: radio ~192px, checkbox ~64px, texto espremido em 2 linhas)',()=>{
  assert.match(css,/\.conselho-modo-card input,\s*\n?\s*\.conselho-check input\s*\{[^}]*width:\s*auto/);
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

// Registro no formato mais novo ainda: já com dados_apresentados.
// sintese_estruturada/classificacao_divergencia/recomendacoes_ja_em_andamento
// (correção de UX/divergência) -- usado para testar o painel executivo
// compacto, sem afetar os testes acima (que continuam usando registros
// sem esses campos).
const REGISTRO_COM_SINTESE = {
  ...REGISTRO_ESTRUTURADO,
  id: 'r3',
  precisa_diretor: true,
  dados_apresentados: {
    sinal_id: 's1', tipo_evento: 'custo_ingrediente',
    recomendacoes_ja_em_andamento: [{responsavel: 'rua', descricao: 'acionar fornecedor alternativo'}],
    classificacao_divergencia: [
      {agente: 'leonard', natureza: 'divergencia_real', texto: 'discorda do prazo proposto por Rua'},
    ],
    sintese_estruturada: {
      o_que_sabemos: [{agente: 'Iris', dados_utilizados: 'Há 3 leituras de preço confirmadas pelo fornecedor.'}],
      o_que_nao_sabemos: ['MOQ do fornecedor X não confirmado', 'lead time não confirmado'],
      convergencias: ['Iris', 'Leonard'],
      divergencias: {Leonard: 'discorda do prazo proposto por Rua'},
      riscos: {Standard: 'variação de câmbio pode elevar custo'},
      bloqueios: {veto: null, numeros_sem_evidencia: ['50'], agentes_com_falha: null},
      decisao_possivel_agora: false,
      proxima_acao: 'Confirmar MOQ e lead time com o fornecedor antes de negociar preço.',
      responsavel: 'Iris',
      evidencia_necessaria: ['MOQ do fornecedor X não confirmado', 'lead time não confirmado'],
      precisa_diretor: true,
      motivos_diretor: [{agente: 'Standard', motivo: 'número(s) sem proveniência: 50'}],
    },
  },
};

// className e classList sincronizados nos dois sentidos -- mesma
// semântica do DOM real (setar className atualiza classList e
// vice-versa), necessário porque o código de produção mistura os dois
// (el() define className na criação; toggles de progressive disclosure
// usam classList.toggle depois).
function no(tag='div') {
  const obj = {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},
    open:undefined,type:undefined,_atributos:{},_classNameInterna:'',
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return null;},
    querySelector(){return null;}, querySelectorAll(){return [];},
    setAttribute(k,v){this._atributos[k]=String(v);},
    getAttribute(k){return Object.prototype.hasOwnProperty.call(this._atributos,k)?this._atributos[k]:null;},
    removeAttribute(k){delete this._atributos[k];},
  };
  const sincronizar = () => { obj._classNameInterna = [...obj.classList._c].join(' '); };
  obj.classList = {
    _c: new Set(),
    add(c){this._c.add(c); sincronizar();},
    remove(c){this._c.delete(c); sincronizar();},
    toggle(c,v){ (v===undefined ? !this._c.has(c) : v) ? this._c.add(c) : this._c.delete(c); sincronizar(); },
    contains(c){return this._c.has(c);},
  };
  Object.defineProperty(obj, 'className', {
    get(){ return obj._classNameInterna; },
    set(v){ obj._classNameInterna = v || ''; obj.classList._c = new Set((v || '').split(/\s+/).filter(Boolean)); },
  });
  return obj;
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
  assert.match(t.elementos['conselho-conflitos'].children[0].textContent,/Nenhuma divergência relevante/);
  assert.match(t.elementos['conselho-vetos'].children[0].textContent,/Nenhum veto/);
});

test('divergencia mostra agente -> posicao e sintese, nunca JSON cru',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, conflitos:[
    {registro_id:'r1', tipo:'reuniao', conflitos:{iris:'dado insuficiente', leonard:'vendas discorda'}},
  ]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-conflitos']);
  assert.match(texto,/Iris/);
  assert.match(texto,/dado insuficiente/);
  assert.match(texto,/Leonard/);
  assert.match(texto,/Síntese/);
  assert.doesNotMatch(texto,/"agente_a"/);
});

test('topo executivo mostra demandas analisadas, recomendacoes abertas e precisam do diretor',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-topo-executivo']);
  assert.match(texto,/Demandas analisadas/);
  assert.match(texto,/Recomendações abertas/);
  assert.match(texto,/Precisam do Diretor/);
});

test('relatorio aparece como card compacto, nao tabela nem JSON cru',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const container=t.elementos['conselho-relatorios'];
  const card=container.children[0].children[1];
  assert.equal(card.tag,'div');
  const texto=JSON.stringify(container);
  assert.match(texto,/Margem dentro do esperado/);
  assert.doesNotMatch(texto,/"tag":"table"/);
});

test('card do agente mostra contagem de demandas participadas',async()=>{
  const t=setup();
  await t.elementos['conselho-atualizar'].listeners.click();
  const texto=JSON.stringify(t.elementos['conselho-agentes']);
  assert.match(texto,/Demandas participadas: \d/);
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

// ---------------------------------------------------------------------
// Correção de UX (painel executivo compacto) e correção de classificação
// de divergência -- ambas sobre o mesmo harness de DOM acima.
// ---------------------------------------------------------------------

function acharTodosPorClasse(no_, classe, achados=[]) {
  const classes = String(no_.className || '').split(/\s+/);
  if (classes.includes(classe)) achados.push(no_);
  for (const filho of (no_.children || [])) acharTodosPorClasse(filho, classe, achados);
  return achados;
}

test('resumo executivo, decisao, agentes compactos e visao completa aparecem nesta ordem',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const card=acharPorClasse(t.elementos['conselho-atas'],'conselho-ata-card');
  const idxResumo=card.children.findIndex(c=>c.className==='conselho-resumo-executivo');
  const idxDecisao=card.children.findIndex(c=>c.className==='conselho-decisao-agora');
  const idxAgentesCompactos=card.children.findIndex(c=>c.className==='conselho-agentes-compactos');
  const idxVisaoCompleta=card.children.findIndex(c=>c.className==='conselho-visao-completa');
  assert.ok(idxResumo>=0 && idxDecisao>=0 && idxAgentesCompactos>=0 && idxVisaoCompleta>=0);
  assert.ok(idxResumo<idxDecisao && idxDecisao<idxAgentesCompactos && idxAgentesCompactos<idxVisaoCompleta);
});

test('resumo executivo mostra status, risco, dados ausentes e diretor com motivo real',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const resumo=acharPorClasse(t.elementos['conselho-atas'],'conselho-resumo-executivo');
  const texto=JSON.stringify(resumo);
  assert.match(texto,/Status/);
  assert.match(texto,/Aguardando Diretor/);
  assert.match(texto,/Dados ausentes/);
  assert.match(texto,/MOQ do fornecedor X não confirmado/);
  assert.match(texto,/Standard: número\(s\) sem proveniência: 50/); // motivo real, nunca generico
  assert.doesNotMatch(texto,/necessidade sinalizada/);
});

test('demanda aparece truncada por padrao e o botao expande sem duplicar o texto',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const demanda=acharPorClasse(t.elementos['conselho-atas'],'conselho-demanda');
  const paragrafo=demanda.children.find(c=>c.tag==='p');
  const botao=demanda.children.find(c=>c.tag==='button');
  assert.ok(paragrafo.classList.contains('conselho-clamp-3'));
  assert.equal(botao.getAttribute('aria-expanded'),'false');
  assert.equal(paragrafo.textContent, REGISTRO_COM_SINTESE.demanda);
  botao.listeners.click();
  assert.ok(!paragrafo.classList.contains('conselho-clamp-3'));
  assert.equal(botao.getAttribute('aria-expanded'),'true');
});

test('agente compacto fica fechado por padrao mas guarda o parecer completo dentro de "Ver analise"',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const compactos=acharTodosPorClasse(t.elementos['conselho-atas'],'conselho-agente-compacto');
  assert.equal(compactos.length,2);
  const detalhes=acharPorClasse(compactos[0],'conselho-agente-detalhes');
  assert.notEqual(detalhes.open,true);
  assert.match(JSON.stringify(detalhes),/Há conteúdos para Instagram já previstos no calendário/);
});

test('agente com divergencia real mostra tag DIVERGENCIA no card compacto',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const compactos=acharTodosPorClasse(t.elementos['conselho-atas'],'conselho-agente-compacto');
  const leonardCompacto = compactos.find(c => JSON.stringify(c).includes('Leonard'));
  assert.match(JSON.stringify(leonardCompacto),/DIVERGÊNCIA/);
});

test('acao ja em andamento aparece com tag EM ANDAMENTO na decisao, nunca duplicada como nova',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const decisao=acharPorClasse(t.elementos['conselho-atas'],'conselho-decisao-agora');
  const texto=JSON.stringify(decisao);
  assert.match(texto,/EM ANDAMENTO/);
  assert.match(texto,/acionar fornecedor alternativo/);
});

test('convergencia condensada aparece uma vez so quando 2 ou mais agentes convergem',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const convergencias=acharTodosPorClasse(t.elementos['conselho-atas'],'conselho-convergencia');
  assert.equal(convergencias.length,1);
  assert.match(convergencias[0].children[1].textContent,/Iris/);
  assert.match(convergencias[0].children[1].textContent,/Leonard/);
});

test('sintese estruturada tem as 11 secoes com tag SEM EVIDENCIA (correcao de nomenclatura)',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const bloco=acharPorClasse(t.elementos['conselho-atas'],'conselho-sintese-estruturada');
  assert.ok(bloco);
  const texto=JSON.stringify(bloco);
  for (const rotulo of ['O que sabemos','O que não sabemos','Convergências','Divergências','Riscos',
                         'Bloqueios','Decisão possível agora','Próxima ação','Responsável',
                         'Evidência necessária','Precisa do Diretor']) {
    assert.match(texto,new RegExp(rotulo.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
  }
  assert.match(texto,/SEM EVIDÊNCIA/);
  assert.doesNotMatch(texto,/EVIDÊNCIA AUSENTE/);
});

test('registro antigo sem sintese_estruturada nao mostra o bloco novo, so a sintese de sempre',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_ESTRUTURADO]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  assert.equal(acharPorClasse(t.elementos['conselho-atas'],'conselho-sintese-estruturada'),null);
  assert.ok(acharPorClasse(t.elementos['conselho-atas'],'conselho-sintese'));
});

test('visao completa preserva demanda completa, pareceres e auditoria -- nunca perde informacao',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const visao=acharPorClasse(t.elementos['conselho-atas'],'conselho-visao-completa');
  assert.ok(visao);
  assert.notEqual(visao.open,true);
  const texto=JSON.stringify(visao);
  assert.match(texto,new RegExp(REGISTRO_COM_SINTESE.demanda.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
  assert.match(texto,/Dados técnicos \(auditoria\)/);
  assert.match(texto,/Testar uma publicação musical/);
  assert.match(texto,/conselho-pareceres-grid/);
});

test('todo tag/chip de natureza usa simbolo + texto, nunca so cor (acessibilidade)',async()=>{
  const t=setup({respostaConselho:{...CONSELHO_OK, reunioes_recentes:[REGISTRO_COM_SINTESE]}});
  await t.elementos['conselho-atualizar'].listeners.click();
  const tags=acharTodosPorClasse(t.elementos['conselho-atas'],'conselho-tag');
  assert.ok(tags.length>0);
  for (const tag of tags) assert.match(tag.textContent,/^[^A-Za-zÀ-ú]/);
});

test('css define line-clamp para nao explodir a altura inicial dos cards',()=>{
  assert.match(css,/-webkit-line-clamp:\s*3/);
});
