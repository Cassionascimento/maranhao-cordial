/* Conselho de Agentes -- leitura + consulta interativa no Admin.
   A análise só gera pareceres. Enviar ao Diretor exige um segundo clique explícito.

   Apresentação executiva da leitura histórica (Atas): os campos brutos de
   auditoria (posicoes, dados_apresentados, conflitos, recomendacoes, vetos,
   pendencias, conclusao consolidada) continuam vindo inteiros da API e
   ficam dentro de "Dados técnicos (auditoria)" em cada ata -- nada é
   descartado, só reorganizado: primeiro Conclusão/Evidências/Riscos/
   Recomendação por agente e uma Síntese do Conselho, nunca um dump técnico. */
(() => {
  'use strict';
  const panel = document.getElementById('conselho-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/mi/conselho';
  const $ = id => document.getElementById('conselho-' + id);
  let conselho = null, busy = false, ultimoResultado = null;

  const NOMES = {
    pirret: ['Pirret', 'Marketing'], standard: ['Standard', 'Financeiro'],
    zilda: ['Zilda', 'Pessoas'], leonard: ['Leonard', 'Vendas'],
    marie: ['Marie', 'Produto'], rua: ['Rua', 'Operações'],
    dicio: ['Dicio', 'Jurídico'], iris: ['Iris', 'Dados'],
  };
  const nomeDe = codigo => (NOMES[codigo] && NOMES[codigo][0]) || codigo;
  const areaDe = codigo => (NOMES[codigo] && NOMES[codigo][1]) || '—';

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const fmt = v => (v == null ? '—' : Number(v).toLocaleString('pt-BR'));
  const dataHora = iso => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR');
  };
  const authHeaders = extra => Object.assign({ 'X-Admin-Key': window.adminKeyAtual || '' }, extra || {});

  async function call() {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar o Conselho.');
    const response = await fetch(api, { cache: 'no-store', headers: authHeaders({ 'Content-Type': 'application/json' }) });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar o Conselho.');
    return body.conselho;
  }

  function controls(value) {
    busy = value;
    $('atualizar').disabled = value;
    const analisar = document.getElementById('conselho-analisar');
    if (analisar) analisar.disabled = value;
  }

  function criarConsulta() {
    if (document.getElementById('conselho-consulta')) return;
    const box = el('section', undefined, 'mi-bloco conselho-consulta');
    box.id = 'conselho-consulta';
    const h = el('div', undefined, 'conselho-consulta-head');
    h.append(el('div', undefined, 'conselho-consulta-title'));
    h.firstChild.append(el('span', 'Conselho executivo', 'mi-eyebrow'), el('h3', 'Perguntar ao Conselho'));
    h.append(el('p', 'Os agentes analisam e recomendam. Nenhuma ação externa é executada.', 'conselho-consulta-seguranca'));
    box.append(h);

    const form = document.createElement('form');
    form.id = 'conselho-form';
    const labelPergunta = el('label', 'Pergunta ou demanda', 'conselho-label');
    const area = document.createElement('textarea');
    area.id = 'conselho-demanda'; area.name = 'demanda'; area.rows = 5;
    area.placeholder = 'Ex.: Devemos priorizar produção, feira ou prospecção nas próximas quatro semanas?';
    labelPergunta.append(area); form.append(labelPergunta);

    const modos = el('div', undefined, 'conselho-modos');
    [
      ['automatico', 'Seleção automática', 'O sistema chama só as áreas pertinentes.'],
      ['especialistas', 'Escolher especialistas', 'Você define exatamente quem participa.'],
      ['conclave', 'Conclave completo', 'Convoca os oito agentes. Usa mais tokens.'],
    ].forEach(([valor, titulo, ajuda], i) => {
      const lab = el('label', undefined, 'conselho-modo-card');
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'modo'; radio.value = valor; radio.checked = i === 0;
      const texto = el('span'); texto.append(el('strong', titulo), el('small', ajuda));
      lab.append(radio, texto); modos.append(lab);
    });
    form.append(modos);

    const escolhas = el('div', undefined, 'conselho-especialistas');
    escolhas.id = 'conselho-especialistas';
    Object.entries(NOMES).forEach(([codigo, info]) => {
      const lab = el('label', undefined, 'conselho-check');
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = codigo; check.name = 'agentes';
      lab.append(check, el('span', info[0] + ' · ' + info[1])); escolhas.append(lab);
    });
    form.append(escolhas);

    const arquivoWrap = el('label', 'Anexar documento (opcional)', 'conselho-label');
    const arquivo = document.createElement('input');
    arquivo.id = 'conselho-documento'; arquivo.type = 'file'; arquivo.name = 'documento';
    arquivo.accept = '.pdf,.docx,.txt,.md,.csv,.json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/csv,application/json';
    arquivoWrap.append(arquivo, el('small', 'PDF, DOCX, TXT, MD, CSV ou JSON · até 8 MB. O arquivo é lido para esta análise e não é salvo como upload.', 'conselho-ajuda'));
    form.append(arquivoWrap);

    const acoes = el('div', undefined, 'conselho-consulta-acoes');
    const analisar = el('button', 'Analisar', 'btn btn-primary'); analisar.type = 'submit'; analisar.id = 'conselho-analisar';
    const estado = el('span', 'Pronto para uma nova análise.', 'conselho-consulta-status'); estado.id = 'conselho-consulta-status';
    acoes.append(analisar, estado); form.append(acoes);
    box.append(form);

    const resultado = el('div', undefined, 'conselho-resultado'); resultado.id = 'conselho-resultado'; resultado.hidden = true; box.append(resultado);
    const alvo = $('resumo') || panel.firstElementChild;
    if (alvo && alvo.parentNode) alvo.parentNode.insertBefore(box, alvo);
    else panel.prepend(box);

    const atualizarEscolhas = () => {
      const modo = form.querySelector('input[name="modo"]:checked').value;
      escolhas.hidden = modo !== 'especialistas';
    };
    form.querySelectorAll('input[name="modo"]').forEach(r => r.addEventListener('change', atualizarEscolhas));
    atualizarEscolhas();
    form.addEventListener('submit', analisarConselho);
  }

  async function analisarConselho(event) {
    event.preventDefault();
    if (busy) return;
    if (!window.adminKeyAtual) { document.getElementById('conselho-consulta-status').textContent = 'Entre no Admin antes de analisar.'; return; }
    const form = document.getElementById('conselho-form');
    const demanda = document.getElementById('conselho-demanda').value.trim();
    if (!demanda) { document.getElementById('conselho-consulta-status').textContent = 'Digite a pergunta ou demanda.'; return; }
    const modo = form.querySelector('input[name="modo"]:checked').value;
    const fd = new FormData(); fd.append('demanda', demanda); fd.append('modo', modo);
    const agentes = [...form.querySelectorAll('input[name="agentes"]:checked')].map(i => i.value);
    fd.append('agentes', JSON.stringify(agentes));
    const arquivo = document.getElementById('conselho-documento').files[0]; if (arquivo) fd.append('documento', arquivo);

    controls(true); ultimoResultado = null;
    document.getElementById('conselho-consulta-status').textContent = modo === 'conclave' ? 'Convocando o Conclave completo…' : 'Consultando especialistas…';
    try {
      const response = await fetch(api + '/analisar', { method: 'POST', headers: authHeaders(), body: fd });
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível concluir a análise.');
      ultimoResultado = body.resultado;
      renderResultado(body.resultado);
      document.getElementById('conselho-consulta-status').textContent = 'Análise concluída. Nada foi executado externamente.';
    } catch (e) {
      document.getElementById('conselho-consulta-status').textContent = e.message;
    } finally { controls(false); }
  }

  function renderResultado(resultado) {
    const container = document.getElementById('conselho-resultado'); container.replaceChildren(); container.hidden = false;
    const topo = el('div', undefined, 'conselho-resultado-topo');
    topo.append(el('h4', 'Pareceres do Conselho'));
    const meta = [];
    meta.push(resultado.modo === 'conclave' ? 'Conclave completo' : resultado.modo === 'especialistas' ? 'Especialistas escolhidos' : 'Seleção automática');
    meta.push((resultado.selecionados || []).map(a => NOMES[a]?.[0] || a).join(', '));
    if (resultado.documento) meta.push('Documento: ' + resultado.documento.nome + (resultado.documento.truncado ? ' (texto limitado)' : ''));
    topo.append(el('p', meta.filter(Boolean).join(' · '), 'conselho-resultado-meta')); container.append(topo);

    const grid = el('div', undefined, 'conselho-pareceres-grid');
    (resultado.pareceres || []).forEach(p => {
      const card = el('article', undefined, 'conselho-parecer-card' + (p.veto ? ' conselho-parecer-veto' : ''));
      const nome = NOMES[p.agente] || [p.agente, ''];
      card.append(el('strong', nome[0] + ' · ' + nome[1], 'conselho-parecer-nome'));
      card.append(el('span', 'Confiança: ' + (p.confianca || '—'), 'conselho-parecer-confianca'));
      card.append(el('p', p.conclusao || 'Sem conclusão.', 'conselho-parecer-conclusao'));
      if (p.riscos) card.append(el('p', 'Riscos: ' + p.riscos));
      if (p.divergencias) card.append(el('p', 'Divergências: ' + p.divergencias));
      if (p.acao_sugerida) card.append(el('p', 'Ação sugerida: ' + p.acao_sugerida, 'conselho-parecer-acao'));
      if (p.veto) card.append(el('p', 'VETO: ' + (p.veto_motivo || 'revisão jurídica necessária'), 'conselho-veto-texto'));
      grid.append(card);
    });
    container.append(grid);

    if ((resultado.erros || []).length) {
      container.append(el('p', 'Alguns especialistas não responderam: ' + resultado.erros.map(e => NOMES[e.agente]?.[0] || e.agente).join(', ') + '. A falha não é tratada como concordância.', 'conselho-alerta'));
    }
    const sintese = el('div', undefined, 'conselho-sintese');
    sintese.append(el('h4', 'Síntese'));
    sintese.append(el('p', resultado.sintese?.resumo || 'Sem síntese disponível.'));
    if (resultado.sintese?.ha_veto) sintese.append(el('p', 'Existe veto jurídico nesta análise.', 'conselho-veto-texto'));
    container.append(sintese);

    const acoes = el('div', undefined, 'conselho-diretor-acoes');
    const botao = el('button', 'Enviar para decisão do Diretor', 'btn btn-primary'); botao.type = 'button'; botao.id = 'conselho-enviar-diretor';
    botao.addEventListener('click', enviarDiretor);
    acoes.append(botao, el('span', 'Só este clique registra a análise como aguardando sua decisão.', 'conselho-ajuda'));
    container.append(acoes);
  }

  async function enviarDiretor() {
    if (!ultimoResultado || busy) return;
    const botao = document.getElementById('conselho-enviar-diretor'); botao.disabled = true;
    document.getElementById('conselho-consulta-status').textContent = 'Enviando para o Modo Diretor…';
    try {
      const response = await fetch(api + '/enviar-diretor', {
        method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ resultado: ultimoResultado }),
      });
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível enviar ao Diretor.');
      botao.textContent = 'Enviado ao Diretor';
      document.getElementById('conselho-consulta-status').textContent = 'Registrado no Modo Diretor. Aguardando decisão humana.';
      await load();
    } catch (e) {
      botao.disabled = false; document.getElementById('conselho-consulta-status').textContent = e.message;
    }
  }

  // ---- Seções recolhíveis: vazio continua uma linha só (já compacto);
  // com conteúdo, abre por padrão dentro de <details> para o Diretor poder
  // recolher depois -- nunca um bloco grande fixo ocupando a tela. ----
  function tabela(container, colunas, linhas, vazioTexto, rotuloPlural) {
    container.replaceChildren();
    if (!linhas.length) { container.append(el('p', vazioTexto, 'mi-vazio')); return; }
    const detalhes = el('details', undefined, 'conselho-secao-recolhivel');
    detalhes.open = true;
    detalhes.append(el('summary', linhas.length + ' ' + (rotuloPlural || 'registro(s)')));
    const wrap = el('div', undefined, 'mi-tabela-wrap'); const tabelaEl = el('table', undefined, 'mi-tabela');
    const thead = el('thead'); const trh = el('tr'); for (const c of colunas) trh.append(el('th', c)); thead.append(trh); tabelaEl.append(thead);
    const tbody = el('tbody'); for (const linha of linhas) { const tr = el('tr'); for (const valor of linha) tr.append(el('td', valor)); tbody.append(tr); }
    tabelaEl.append(tbody); wrap.append(tabelaEl); detalhes.append(wrap); container.append(detalhes);
  }

  function listaRecolhivel(container, itens, vazioTexto, rotuloPlural, montarItem) {
    container.replaceChildren();
    if (!itens.length) { container.append(el('p', vazioTexto, 'mi-vazio')); return; }
    const detalhes = el('details', undefined, 'conselho-secao-recolhivel');
    detalhes.open = true;
    detalhes.append(el('summary', itens.length + ' ' + rotuloPlural));
    for (const item of itens) detalhes.append(montarItem(item));
    container.append(detalhes);
  }

  function jsonBloco(rotulo, valor) {
    if (valor == null || (Array.isArray(valor) && !valor.length) || (typeof valor === 'object' && !Array.isArray(valor) && !Object.keys(valor).length)) return null;
    const bloco = el('div', undefined, 'conselho-json-bloco'); bloco.append(el('span', rotulo, 'conselho-json-rotulo')); bloco.append(el('pre', JSON.stringify(valor, null, 2), 'conselho-json-pre')); return bloco;
  }

  const NOMES_EVENTO = { mensagem_enviada: 'Troca de mensagem', reuniao_registrada: 'Reunião registrada', conclave_registrado: 'Conclave registrado', relatorio_registrado: 'Relatório registrado' };
  const participaDe = (registro, codigo) => Array.isArray(registro.participantes) && registro.participantes.includes(codigo);

  function renderAgentes() {
    const container = $('agentes'); container.replaceChildren();
    const mensagens = conselho.mensagens_recentes || [], relatorios = conselho.relatorios_recentes || [], reunioes = conselho.reunioes_recentes || [];
    for (const agente of conselho.agentes || []) {
      const card = el('div', undefined, 'conselho-agente-card conselho-agente-' + agente.status);
      card.append(el('strong', agente.nome, 'conselho-agente-nome'), el('span', agente.area, 'conselho-agente-area'), el('span', agente.status === 'trabalhando' ? 'Trabalhando' : 'Sem demanda', 'conselho-agente-status'));
      const atividade = agente.ultima_atividade;
      card.append(el('p', 'Última atividade: ' + (atividade ? (NOMES_EVENTO[atividade.tipo_evento] || atividade.tipo_evento) + ' em ' + dataHora(atividade.criado_em) : 'nenhuma registrada')));
      const participacoes = [...reunioes, ...relatorios].filter(r => participaDe(r, agente.codigo)).sort((a,b)=>new Date(b.criado_em)-new Date(a.criado_em));
      card.append(el('p', 'Demandas participadas: ' + participacoes.length, 'conselho-agente-contagem'));
      const demandaAtual = agente.status === 'trabalhando' && participacoes[0];
      card.append(el('p', 'Demanda atual: ' + (demandaAtual ? (demandaAtual.demanda || '—') : 'nenhuma')));
      const ultimaMensagem = mensagens.find(m => m.de_agente === agente.codigo); card.append(el('p', 'Última mensagem: ' + (ultimaMensagem ? ('"'+ultimaMensagem.texto+'"') : 'nenhuma')));
      // Mostra a demanda (fato curto), nunca a conclusao consolidada bruta
      // (que concatena "Nome: texto; Nome2: texto2" -- dump técnico).
      const ultimoRelatorio = relatorios.find(r => participaDe(r, agente.codigo)); card.append(el('p', 'Último relatório: ' + (ultimoRelatorio ? (ultimoRelatorio.demanda || '—') : 'nenhum')));
      card.append(el('p', 'Próxima atividade: nenhuma agendada (agentes só atuam por demanda real)', 'conselho-agente-nota')); container.append(card);
    }
  }

  function renderMensagens() { tabela($('mensagens'), ['Quando','De','Para','Demanda','Mensagem'], (conselho.mensagens_recentes||[]).map(m=>[dataHora(m.criado_em),m.de_agente,m.para_agente||'todos',m.demanda_referencia||'—',m.texto]), 'Nenhuma mensagem registrada entre agentes ainda.', 'mensagem(ns)'); }
  function renderReunioes() { tabela($('reunioes'), ['Quando','Tipo','Demanda','Participantes','Precisa Diretor'], (conselho.reunioes_recentes||[]).map(r=>[dataHora(r.criado_em),r.tipo==='conclave'?'Conclave':'Reunião',r.demanda||'—',(r.participantes||[]).join(', ')||'—',r.precisa_diretor?'Sim':'Não']), 'Nenhuma reunião ou conclave registrado ainda.', 'reunião(ões)/conclave(s)'); }

  // ---- Apresentação executiva por parecer histórico (Atas) ----
  // `posicoes[agente]` normalmente é o objeto estruturado que
  // mi_conselho_executor._consolidar grava (conclusao/confianca/
  // dados_utilizados/riscos); um registro antigo pode trazer só uma string
  // (conclusão pura) -- os dois formatos são aceitos, nunca inventamos os
  // campos que faltarem.
  function posicaoDoAgente(registro, codigo) {
    const bruta = (registro.posicoes || {})[codigo];
    if (bruta == null) return null;
    if (typeof bruta === 'string') return { conclusao: bruta, confianca: null, dados_utilizados: '', riscos: '' };
    return bruta;
  }

  const RISCO_TRIVIAL = new Set(['', 'nenhum', 'nenhum risco', 'nenhum risco imediato', 'sem risco', 'não há risco', 'nao ha risco', 'n/a']);
  const trivial = (texto, conjunto) => conjunto.has((texto || '').trim().toLowerCase());

  function bulletsDeEvidencia(texto, limite) {
    if (!texto || !texto.trim()) return null;
    const partes = texto.split(/(?<=[.;])\s+/).map(s => s.trim()).filter(Boolean);
    return partes.length ? partes.slice(0, limite || 4) : null;
  }

  function parecerExecutivoCard(registro, codigo) {
    const posicao = posicaoDoAgente(registro, codigo);
    const card = el('div', undefined, 'conselho-parecer-card');

    const cabecalho = el('div', undefined, 'conselho-parecer-cabecalho');
    cabecalho.append(el('strong', nomeDe(codigo) + ' · ' + areaDe(codigo), 'conselho-parecer-nome'));
    if (posicao && posicao.confianca) {
      cabecalho.append(el('span', 'Confiança: ' + posicao.confianca, 'conselho-badge conselho-badge-' + posicao.confianca));
    }
    card.append(cabecalho);

    if (!posicao || !(posicao.conclusao || '').trim()) {
      card.append(el('p', 'Não há dados suficientes para concluir.', 'conselho-parecer-vazio'));
      return card;
    }

    card.append(el('h4', 'Conclusão', 'conselho-parecer-rotulo'));
    card.append(el('p', posicao.conclusao, 'conselho-parecer-conclusao'));

    card.append(el('h4', 'Evidências', 'conselho-parecer-rotulo'));
    const evidencias = bulletsDeEvidencia(posicao.dados_utilizados, 4);
    if (evidencias) {
      const lista = el('ul', undefined, 'conselho-parecer-lista');
      for (const item of evidencias) lista.append(el('li', item));
      card.append(lista);
    } else {
      card.append(el('p', 'Não há dados suficientes para concluir.', 'conselho-parecer-vazio'));
    }

    if (posicao.riscos && !trivial(posicao.riscos, RISCO_TRIVIAL)) {
      card.append(el('h4', 'Riscos / incertezas', 'conselho-parecer-rotulo'));
      card.append(el('p', posicao.riscos));
    }

    const recomendacao = (registro.recomendacoes || []).find(r => r.responsavel === codigo);
    card.append(el('h4', 'Recomendação', 'conselho-parecer-rotulo'));
    card.append(el('p', recomendacao ? recomendacao.descricao : 'Nenhuma ação recomendada.', 'conselho-parecer-acao'));

    if (registro.vetos && registro.vetos[codigo]) {
      card.classList.add('conselho-parecer-veto');
      card.append(el('p', 'VETO: ' + registro.vetos[codigo], 'conselho-veto-texto'));
    }

    return card;
  }

  // ---- Síntese do Conselho para um registro histórico ----
  // Nunca repete a prosa de um parecer: monta a leitura a partir de fatos
  // estruturados (quem recomendou o quê, se há veto, se há pendência) --
  // mesmo com um único agente convocado, o texto aqui é outro, derivado só
  // de recomendações/veto/pendências, nunca da conclusão do agente.
  function sinteseDoConselho(registro) {
    const bloco = el('div', undefined, 'conselho-sintese');
    bloco.append(el('h4', 'Síntese do Conselho'));

    const participantes = registro.participantes || [];
    const recomendacoes = registro.recomendacoes || [];
    const vetos = registro.vetos || {};
    const agentesComVeto = Object.keys(vetos);

    let decisao;
    if (agentesComVeto.length) {
      decisao = agentesComVeto.map(nomeDe).join(' e ') + ' vetou esta demanda -- ação bloqueada até decisão do Diretor.';
    } else if (recomendacoes.length) {
      const responsaveis = [...new Set(recomendacoes.map(r => nomeDe(r.responsavel)))];
      decisao = 'O Conselho recomenda seguir com a orientação de ' + responsaveis.join(' e ') + '.';
    } else {
      decisao = 'O Conselho não chegou a uma recomendação de ação para esta demanda.';
    }
    bloco.append(el('p', decisao));

    const evidencias = [];
    for (const codigo of participantes) {
      const posicao = posicaoDoAgente(registro, codigo);
      const partes = posicao && bulletsDeEvidencia(posicao.dados_utilizados, 3 - evidencias.length);
      if (partes) evidencias.push(...partes);
      if (evidencias.length >= 3) break;
    }
    if (evidencias.length) {
      const lista = el('ul', undefined, 'conselho-parecer-lista');
      for (const item of evidencias.slice(0, 3)) lista.append(el('li', item));
      bloco.append(lista);
    }

    bloco.append(el('p', recomendacoes.length ? recomendacoes[0].descricao : 'Nenhuma ação recomendada.'));

    const pendencias = registro.pendencias || {};
    let motivo = '';
    if (agentesComVeto.length) motivo = 'veto registrado';
    else if (pendencias.agentes_com_falha) motivo = 'falha de especialista(s) convocado(s)';
    else if (pendencias.especialistas_acima_do_limite) motivo = 'demanda excedeu o limite de especialistas automáticos';
    else if (registro.precisa_diretor) motivo = 'necessidade sinalizada por especialista convocado';
    bloco.append(el('p', 'Precisa do Diretor: ' + (registro.precisa_diretor ? 'Sim' : 'Não') + (motivo ? ' — ' + motivo + '.' : '.')));

    return bloco;
  }

  function renderAtas() {
    const registros = conselho.reunioes_recentes || [];
    listaRecolhivel($('atas'), registros, 'Nenhuma ata registrada ainda.', 'ata(s)', r => {
      const card = el('div', undefined, 'conselho-ata-card');
      const cabecalho = el('div', undefined, 'conselho-ata-cabecalho');
      cabecalho.append(el('strong', (r.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — v' + r.versao), el('span', dataHora(r.criado_em)));
      card.append(cabecalho, el('p', 'Demanda: ' + (r.demanda || '—')));

      const participantes = r.participantes || [];
      if (participantes.length) {
        const pareceresWrap = el('div', undefined, 'conselho-pareceres-grid');
        for (const codigo of participantes) pareceresWrap.append(parecerExecutivoCard(r, codigo));
        card.append(pareceresWrap);
      }

      card.append(sinteseDoConselho(r));

      const auditoria = el('details', undefined, 'conselho-auditoria');
      auditoria.append(el('summary', 'Dados técnicos (auditoria)'));
      auditoria.append(el('p', 'Contexto: ' + (r.contexto || '—')));
      auditoria.append(el('p', 'Conclusão consolidada (registro bruto): ' + (r.conclusao || '—')));
      auditoria.append(el('p', 'Precisa do Diretor: ' + (r.precisa_diretor ? 'Sim' : 'Não')));
      for (const [rotulo, valor] of [['Participantes', r.participantes], ['Dados apresentados', r.dados_apresentados], ['Posições', r.posicoes], ['Conflitos', r.conflitos], ['Recomendações', r.recomendacoes], ['Vetos', r.vetos], ['Pendências', r.pendencias]]) {
        const b = jsonBloco(rotulo, valor); if (b) auditoria.append(b);
      }
      card.append(auditoria);

      return card;
    });
  }

  function relatorioCard(r) {
    const card = el('div', undefined, 'conselho-ata-card');
    const cabecalho = el('div', undefined, 'conselho-ata-cabecalho');
    cabecalho.append(el('strong', 'Relatório'), el('span', dataHora(r.criado_em)));
    card.append(cabecalho, el('p', 'Demanda: ' + (r.demanda || '—')));
    card.append(el('p', 'Participantes: ' + ((r.participantes || []).map(nomeDe).join(', ') || '—')));
    card.append(el('p', r.conclusao || 'Sem conclusão.', 'conselho-parecer-conclusao'));
    const recomendacao = (r.recomendacoes || [])[0];
    if (recomendacao) card.append(el('p', 'Recomendação: ' + recomendacao.descricao, 'conselho-parecer-acao'));
    card.append(el('p', 'Precisa do Diretor: ' + (r.precisa_diretor ? 'Sim' : 'Não'), 'conselho-agente-nota'));
    return card;
  }
  function renderRelatorios(){listaRecolhivel($('relatorios'), conselho.relatorios_recentes||[], 'Nenhum relatório registrado ainda (só é gerado quando há atividade real).', 'relatório(s)', relatorioCard);}

  // `conflitos[i].conflitos` é {agente_codigo: texto_da_divergencia} (ver
  // mi_conselho_executor._consolidar) -- cada entrada já é "agente ->
  // posição"; a síntese aqui é derivada só de quem diverge, nunca repete a
  // prosa do agente.
  function divergenciaCard(item) {
    const card = el('div', undefined, 'conselho-json-card conselho-divergencia-card');
    card.append(el('strong', (item.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — registro ' + item.registro_id));
    const posicoes = item.conflitos || {};
    const codigos = Object.keys(posicoes);
    for (const codigo of codigos) {
      const linha = el('p');
      linha.append(el('strong', nomeDe(codigo) + ' → '), el('span', posicoes[codigo]));
      card.append(linha);
    }
    if (codigos.length) {
      card.append(el('p', 'Síntese: ' + codigos.map(nomeDe).join(' e ') + ' divergem nesta demanda -- decisão cabe ao Diretor.', 'conselho-divergencia-sintese'));
    }
    return card;
  }
  function renderConflitos(){listaRecolhivel($('conflitos'), conselho.conflitos||[], 'Nenhuma divergência relevante.', 'divergência(s)', divergenciaCard);}
  function renderVetos(){listaRecolhivel($('vetos'), conselho.vetos||[], 'Nenhum veto registrado.', 'veto(s)', item => { const b=el('div',undefined,'conselho-json-card conselho-json-card--veto'); b.append(el('strong',(item.tipo==='conclave'?'Conclave':'Reunião')+' — registro '+item.registro_id),el('pre',JSON.stringify(item.vetos,null,2),'conselho-json-pre')); return b; });}
  function renderAguardandoDiretor(){tabela($('diretor'),['Quando','Tipo','Demanda','Conclusão'],(conselho.aguardando_diretor||[]).map(r=>[dataHora(r.criado_em),{reuniao:'Reunião',conclave:'Conclave',relatorio:'Relatório'}[r.tipo]||r.tipo,r.demanda||'—',r.conclusao||'—']),'Nenhum item aguardando decisão do Diretor.','item(ns)');}

  // Três cards executivos no topo -- leitura rápida antes de entrar no
  // detalhe técnico do Resumo abaixo. Derivados só de arrays já retornados
  // pelo endpoint (nenhuma chamada nova, nenhum número inventado).
  function renderTopoExecutivo() {
    const container = $('topo-executivo'); if (!container) return; container.replaceChildren();
    const reunioes = conselho.reunioes_recentes || [], relatorios = conselho.relatorios_recentes || [];
    const demandasAnalisadas = reunioes.length + relatorios.length;
    const recomendacoesAbertas = [...reunioes, ...relatorios].reduce((soma, r) => soma + (r.recomendacoes || []).length, 0);
    const precisamDiretor = (conselho.aguardando_diretor || []).length;
    for (const [label, valor] of [
      ['Demandas analisadas', demandasAnalisadas],
      ['Recomendações abertas', recomendacoesAbertas],
      ['Precisam do Diretor', precisamDiretor],
    ]) {
      const card = el('div', undefined, 'conselho-topo-card');
      card.append(el('strong', fmt(valor)), el('span', label));
      container.append(card);
    }
  }

  function render(){renderTopoExecutivo();const resumo=$('resumo');resumo.replaceChildren();for(const [label,valor] of [['Agentes disponíveis',(conselho.agentes||[]).length],['Trabalhando',conselho.trabalhando],['Sem demanda',conselho.sem_demanda],['Conflitos',(conselho.conflitos||[]).length],['Vetos',(conselho.vetos||[]).length],['Aguardando Diretor',(conselho.aguardando_diretor||[]).length]]){const stat=el('div',undefined,'mi-stat');stat.append(el('strong',fmt(valor)),el('span',label));resumo.append(stat);}renderAgentes();renderMensagens();renderReunioes();renderAtas();renderRelatorios();renderConflitos();renderVetos();renderAguardandoDiretor();$('conteudo').hidden=false;}

  async function load(){if(busy)return;controls(true);$('status').textContent='Consultando o Conselho…';try{conselho=await call();render();$('status').textContent='Leitura atualizada. Nenhuma ação foi executada.';}catch(e){$('status').textContent=e.message;$('conteudo').hidden=false;}finally{controls(false);}}

  criarConsulta();
  $('atualizar').addEventListener('click',load);
  const tab=document.querySelector('[data-tab="conselho-de-agentes"]'); if(tab)tab.addEventListener('click',()=>{if(!conselho&&window.adminKeyAtual)load();});
  window.addEventListener('admin-autorizado',()=>{if(panel.classList.contains('active'))load();});
})();
