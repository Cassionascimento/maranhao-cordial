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
      const alerta = el('div', undefined, 'conselho-alerta');
      alerta.append(el('p', 'Alguns especialistas não responderam. A falha não é tratada como concordância.'));
      const lista = el('ul', undefined, 'conselho-erros-lista');
      resultado.erros.forEach(e => {
        const nome = NOMES[e.agente]?.[0] || e.agente;
        const texto = nome + ' — ' + (e.erro || 'falha desconhecida') + (e.detalhe ? ' (' + e.detalhe + ')' : '');
        lista.append(el('li', texto));
      });
      alerta.append(lista);
      container.append(alerta);
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

  // ---- Painel executivo compacto por ata (correção de UX) ----
  // Objetivo: em ~5 segundos o Diretor entende status/risco/bloqueio/
  // decisão/necessidade de Diretor, sem abrir nada. Detalhe completo
  // (pareceres inteiros, síntese de sempre, auditoria) nunca é removido --
  // só passa a viver dentro de "Visão completa" (details), reaproveitando
  // exatamente as mesmas funções (parecerExecutivoCard/sinteseDoConselho/
  // jsonBloco) já existentes acima.
  function chip(rotulo, valor, tom, detalhe) {
    const c = el('div', undefined, 'conselho-chip' + (tom ? ' conselho-chip--' + tom : ''));
    c.append(el('span', rotulo, 'conselho-chip-rotulo'));
    c.append(el('strong', String(valor), 'conselho-chip-valor'));
    if (detalhe) c.append(el('span', detalhe, 'conselho-chip-detalhe'));
    return c;
  }

  // Nunca confiar só na cor -- todo tag carrega um símbolo + texto.
  const SIMBOLO_TAG = {
    fato: '✓', 'evidencia-ausente': '⚠', divergencia: '⇄', convergencia: '✓',
    bloqueio: '⚠', decisao: '●', acao: '→', 'em-andamento': '●', concluido: '✓',
  };

  function bloqueiosDaSintese(sintese) {
    if (!sintese || !sintese.bloqueios) return [];
    const b = sintese.bloqueios;
    return [
      ...(b.veto ? Object.keys(b.veto) : []),
      ...(b.numeros_sem_evidencia || []),
      ...(b.agentes_com_falha || []),
    ];
  }

  // "Precisa do Diretor" sempre com motivo explícito (correção de
  // escalonamento) -- nunca um texto genérico tipo "necessidade
  // sinalizada". SIM usa sintese.motivos_diretor (mi_conselho_executor);
  // NÃO usa a primeira lacuna pendente como "o que ainda falta", nunca
  // inventando um motivo que os dados não sustentam.
  function motivoDiretorTexto(registro, sintese) {
    if (registro.precisa_diretor) {
      const motivos = (sintese && sintese.motivos_diretor) || [];
      if (!motivos.length) return 'Motivo não especificado pelo agente.';
      return motivos.map(m => (m.agente ? m.agente + ': ' : '') + m.motivo).join(' · ');
    }
    const lacunas = (sintese && sintese.o_que_nao_sabemos) || [];
    if (lacunas.length) {
      return 'Aguardando: ' + lacunas[0] + (lacunas.length > 1 ? ' (+' + (lacunas.length - 1) + ')' : '.');
    }
    return sintese ? 'Nenhuma pendência sinalizada.' : 'NÃO CONFIRMADO';
  }

  // Resumo executivo: STATUS/RISCO/PRAZO/BLOQUEADORES/DADOS AUSENTES/
  // DIRETOR -- nunca inventa valor para preencher um campo sem evidência
  // (usa "NÃO CONFIRMADO" em vez de um placeholder otimista).
  function resumoExecutivoStrip(registro) {
    const sintese = (registro.dados_apresentados || {}).sintese_estruturada;
    const temVeto = Object.keys(registro.vetos || {}).length > 0;
    const bloqueios = bloqueiosDaSintese(sintese);
    const dadosAusentes = (sintese && sintese.o_que_nao_sabemos) || [];

    let status = 'Em análise', statusTom = 'neutro';
    if (temVeto) { status = 'Bloqueada por veto'; statusTom = 'critico'; }
    else if (registro.precisa_diretor) { status = 'Aguardando Diretor'; statusTom = 'atencao'; }
    else if (sintese && sintese.decisao_possivel_agora) { status = 'Decisão possível agora'; statusTom = 'ok'; }

    let risco = 'NÃO CONFIRMADO', riscoTom = 'neutro';
    if (temVeto) { risco = 'Alto'; riscoTom = 'critico'; }
    else if (bloqueios.length) { risco = 'Atenção'; riscoTom = 'atencao'; }
    else if (sintese) { risco = 'Nenhum sinalizado'; riscoTom = 'ok'; }

    const dadosAusentesValor = dadosAusentes.length
      ? dadosAusentes.length + ' · ' + dadosAusentes.slice(0, 2).join(' · ') + (dadosAusentes.length > 2 ? '…' : '')
      : (sintese ? 'Nenhum' : 'NÃO CONFIRMADO');

    const strip = el('div', undefined, 'conselho-resumo-executivo');
    strip.append(chip('Status', status, statusTom));
    strip.append(chip('Risco', risco, riscoTom));
    strip.append(chip('Prazo', 'NÃO CONFIRMADO', 'neutro'));
    strip.append(chip('Bloqueadores', bloqueios.length, bloqueios.length ? 'atencao' : 'ok'));
    strip.append(chip('Dados ausentes', dadosAusentesValor, dadosAusentes.length ? 'atencao' : 'ok'));
    strip.append(chip('Diretor', registro.precisa_diretor ? 'Sim' : 'Não',
                       registro.precisa_diretor ? 'atencao' : 'ok', motivoDiretorTexto(registro, sintese)));
    return strip;
  }

  // Cabeçalho da demanda: nunca abre o texto inteiro por padrão -- clamp
  // visual (CSS) + botão que remove o clamp, sem duplicar o texto.
  function demandaBloco(registro) {
    const wrap = el('div', undefined, 'conselho-demanda');
    wrap.append(el('span', 'DEMANDA', 'conselho-demanda-rotulo'));
    const texto = registro.demanda || '—';
    const paragrafo = el('p', texto, 'conselho-demanda-texto conselho-clamp-3');
    wrap.append(paragrafo);

    const botao = el('button', 'Ver demanda completa', 'conselho-link-botao');
    botao.type = 'button';
    botao.setAttribute('aria-expanded', 'false');
    botao.addEventListener('click', () => {
      const aberto = !paragrafo.classList.contains('conselho-clamp-3');
      paragrafo.classList.toggle('conselho-clamp-3', aberto);
      botao.textContent = aberto ? 'Ver demanda completa' : 'Ver menos';
      botao.setAttribute('aria-expanded', String(!aberto));
    });
    wrap.append(botao);
    return wrap;
  }

  // Decisão do Conselho: um card curto -- nunca repete os pareceres
  // individuais, só o que já foi consolidado.
  function decisaoAgoraBloco(registro, sintese) {
    const bloco = el('div', undefined, 'conselho-decisao-agora');
    bloco.append(el('span', 'DECISÃO AGORA', 'conselho-decisao-rotulo'));

    let texto;
    if (Object.keys(registro.vetos || {}).length) {
      texto = 'Bloqueada por veto jurídico — aguardando revisão humana antes de qualquer ação.';
    } else if (sintese) {
      texto = sintese.decisao_possivel_agora
        ? (sintese.proxima_acao || 'Recomendação registrada, sem detalhe adicional.')
        : 'Ainda não há decisão segura com a evidência atual (ver Dados ausentes acima).';
    } else {
      texto = registro.conclusao || 'Nenhuma decisão registrada ainda.';
    }
    bloco.append(el('p', texto, 'conselho-decisao-texto'));

    const acoes = registro.recomendacoes || [];
    if (acoes.length) {
      bloco.append(el('span', 'PRÓXIMAS AÇÕES', 'conselho-decisao-rotulo'));
      const item = a => el('li', nomeDe(a.responsavel) + ' — ' + a.descricao);
      const lista = el('ul', undefined, 'conselho-decisao-lista');
      for (const a of acoes.slice(0, 3)) lista.append(item(a));
      bloco.append(lista);
      if (acoes.length > 3) {
        const verTodas = el('details', undefined, 'conselho-secao-recolhivel');
        verTodas.append(el('summary', 'Ver todas (' + acoes.length + ')'));
        const listaCompleta = el('ul', undefined, 'conselho-decisao-lista');
        for (const a of acoes) listaCompleta.append(item(a));
        verTodas.append(listaCompleta);
        bloco.append(verTodas);
      }
    }

    const jaEmAndamento = (registro.dados_apresentados || {}).recomendacoes_ja_em_andamento;
    if (jaEmAndamento && jaEmAndamento.length) {
      const linha = el('p', undefined, 'conselho-decisao-em-andamento');
      linha.append(el('span', SIMBOLO_TAG['em-andamento'] + ' EM ANDAMENTO', 'conselho-tag conselho-tag--em-andamento'));
      linha.append(el('span', ' ' + jaEmAndamento.map(a => nomeDe(a.responsavel) + ': ' + a.descricao).join(' · ')));
      bloco.append(linha);
    }

    return bloco;
  }

  // Convergência condensada: uma linha só, nunca repetida por agente --
  // "próxima ação" já É o ponto em que os convergentes concordam (mesmo
  // cálculo que gerou a recomendação consolidada).
  function convergenciaCondensada(sintese) {
    if (!sintese || !sintese.convergencias || sintese.convergencias.length < 2) return null;
    const bloco = el('div', undefined, 'conselho-convergencia');
    bloco.append(el('span', SIMBOLO_TAG.convergencia + ' CONVERGÊNCIA', 'conselho-tag conselho-tag--convergencia'));
    bloco.append(el('strong', sintese.convergencias.join(' · '), 'conselho-convergencia-agentes'));
    bloco.append(el('p', sintese.proxima_acao || 'Sem ação consolidada registrada ainda.', 'conselho-convergencia-texto'));
    return bloco;
  }

  // Síntese estruturada: as 11 seções produzidas por
  // mi_conselho_executor._consolidar quando o registro já vem no formato
  // novo. Registros antigos (sem dados_apresentados.sintese_estruturada)
  // continuam mostrando só a Síntese do Conselho de sempre -- nenhum dado
  // é inventado para preencher esta seção.
  function listaOuVazio(itens, vazioTexto) {
    if (!itens || !itens.length) return el('p', vazioTexto, 'conselho-parecer-vazio');
    const lista = el('ul', undefined, 'conselho-parecer-lista');
    for (const item of itens) lista.append(el('li', typeof item === 'string' ? item : JSON.stringify(item)));
    return lista;
  }

  function sinteseEstruturadaBloco(registro) {
    const sintese = (registro.dados_apresentados || {}).sintese_estruturada;
    if (!sintese) return null;
    const bloco = el('div', undefined, 'conselho-sintese-estruturada');
    bloco.append(el('strong', 'Leitura estruturada do Conselho', 'conselho-sintese-titulo'));

    const secao = (rotulo, tag, conteudoEl) => {
      const cab = el('div', undefined, 'conselho-sintese-secao-cab');
      cab.append(el('span', rotulo, 'conselho-sintese-rotulo'));
      if (tag) {
        const simbolo = SIMBOLO_TAG[tag.tom] ? SIMBOLO_TAG[tag.tom] + ' ' : '';
        cab.append(el('span', simbolo + tag.texto, 'conselho-tag conselho-tag--' + tag.tom));
      }
      bloco.append(cab);
      bloco.append(conteudoEl);
    };
    const TAG_FATO = {texto: 'FATO', tom: 'fato'};
    const TAG_SEM_EVIDENCIA = {texto: 'SEM EVIDÊNCIA', tom: 'evidencia-ausente'};
    const TAG_DIVERGENCIA = {texto: 'DIVERGÊNCIA', tom: 'divergencia'};
    const TAG_BLOQUEIO = {texto: 'BLOQUEIO', tom: 'bloqueio'};
    const TAG_DECISAO = {texto: 'DECISÃO', tom: 'decisao'};
    const TAG_ACAO = {texto: 'AÇÃO', tom: 'acao'};

    secao('O que sabemos', TAG_FATO, listaOuVazio(
      (sintese.o_que_sabemos || []).map(f => (f.agente ? f.agente + ': ' : '') + f.dados_utilizados),
      'Nenhum dado apresentado ainda.',
    ));
    secao('O que não sabemos', TAG_SEM_EVIDENCIA, listaOuVazio(sintese.o_que_nao_sabemos, 'Nenhuma lacuna sinalizada.'));
    secao('Convergências', null, listaOuVazio(sintese.convergencias, 'Nenhuma convergência explícita.'));
    secao('Divergências', TAG_DIVERGENCIA, listaOuVazio(
      Object.entries(sintese.divergencias || {}).map(([agente, texto]) => agente + ': ' + texto),
      'Nenhuma divergência real registrada (dado ausente/risco/hipótese não contam).',
    ));
    secao('Riscos', null, listaOuVazio(
      Object.entries(sintese.riscos || {}).map(([agente, texto]) => agente + ': ' + texto),
      'Nenhum risco material sinalizado.',
    ));
    secao('Bloqueios', TAG_BLOQUEIO, listaOuVazio(bloqueiosDaSintese(sintese), 'Nenhum bloqueio.'));
    secao('Decisão possível agora', TAG_DECISAO, el('p', sintese.decisao_possivel_agora ? 'Sim' : 'Não', 'conselho-sintese-texto'));
    secao('Próxima ação', TAG_ACAO, el('p', sintese.proxima_acao || 'Nenhuma ação recomendada ainda.', 'conselho-sintese-texto'));
    secao('Responsável', null, el('p', sintese.responsavel || '—', 'conselho-sintese-texto'));
    secao('Evidência necessária', TAG_SEM_EVIDENCIA, listaOuVazio(sintese.evidencia_necessaria, 'Nenhuma.'));
    secao('Precisa do Diretor', null, el('p',
      (sintese.precisa_diretor ? 'Sim' : 'Não') + ' — ' + motivoDiretorTexto({precisa_diretor: sintese.precisa_diretor, vetos: {}}, sintese),
      'conselho-sintese-texto'));

    return bloco;
  }

  // Card de agente compacto: 2-3 linhas + chips; detalhe completo só em
  // "Ver análise" (reaproveita parecerExecutivoCard sem alterar seu
  // conteúdo -- nunca remove informação, só adia a exibição).
  function agenteCompactoCard(registro, codigo, classificacaoPorAgente) {
    const posicao = posicaoDoAgente(registro, codigo);
    const card = el('div', undefined, 'conselho-agente-compacto');

    const cab = el('div', undefined, 'conselho-agente-compacto-cab');
    cab.append(el('strong', nomeDe(codigo) + ' · ' + areaDe(codigo).toUpperCase()));
    if (posicao && posicao.confianca) {
      cab.append(el('span', 'Confiança: ' + posicao.confianca, 'conselho-badge conselho-badge-' + posicao.confianca));
    }
    card.append(cab);

    const tags = el('div', undefined, 'conselho-agente-compacto-tags');
    let temTag = false;
    if (posicao && posicao.riscos && !trivial(posicao.riscos, RISCO_TRIVIAL)) {
      tags.append(el('span', SIMBOLO_TAG.bloqueio + ' RISCO', 'conselho-tag conselho-tag--bloqueio'));
      temTag = true;
    }
    if (classificacaoPorAgente[codigo] === 'divergencia_real') {
      tags.append(el('span', SIMBOLO_TAG.divergencia + ' DIVERGÊNCIA', 'conselho-tag conselho-tag--divergencia'));
      temTag = true;
    }
    if ((registro.recomendacoes || []).some(r => r.responsavel === codigo)) {
      tags.append(el('span', SIMBOLO_TAG.acao + ' AÇÃO SUGERIDA', 'conselho-tag conselho-tag--acao'));
      temTag = true;
    }
    if (registro.vetos && registro.vetos[codigo]) {
      tags.append(el('span', '⚠ VETO', 'conselho-tag conselho-tag--bloqueio'));
      temTag = true;
    }
    if (temTag) card.append(tags);

    const excerto = posicao && (posicao.conclusao || '').trim() ? posicao.conclusao : 'Não há dados suficientes para concluir.';
    card.append(el('p', excerto, 'conselho-agente-compacto-texto conselho-clamp-3'));

    const detalhes = el('details', undefined, 'conselho-agente-detalhes');
    detalhes.append(el('summary', 'Ver análise'));
    detalhes.append(parecerExecutivoCard(registro, codigo));
    card.append(detalhes);

    return card;
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
      const sintese = (r.dados_apresentados || {}).sintese_estruturada;
      const classificacaoPorAgente = {};
      for (const c of (r.dados_apresentados || {}).classificacao_divergencia || []) classificacaoPorAgente[c.agente] = c.natureza;
      const participantes = r.participantes || [];

      const card = el('div', undefined, 'conselho-ata-card');
      const cabecalho = el('div', undefined, 'conselho-ata-cabecalho');
      cabecalho.append(el('strong', (r.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — v' + r.versao), el('span', dataHora(r.criado_em)));
      card.append(cabecalho);

      // Painel executivo (visível por padrão): demanda resumida + resumo
      // em chips + decisão + convergência condensada + agentes compactos.
      card.append(demandaBloco(r));
      card.append(resumoExecutivoStrip(r));
      card.append(decisaoAgoraBloco(r, sintese));

      const convergencia = convergenciaCondensada(sintese);
      if (convergencia) card.append(convergencia);

      if (participantes.length) {
        const grid = el('div', undefined, 'conselho-agentes-compactos');
        for (const codigo of participantes) grid.append(agenteCompactoCard(r, codigo, classificacaoPorAgente));
        card.append(grid);
      }

      // Visão completa: tudo que já existia antes desta correção continua
      // aqui, inteiro -- só passou a vir recolhido por padrão.
      const visaoCompleta = el('details', undefined, 'conselho-visao-completa');
      visaoCompleta.append(el('summary', 'Visão completa (agentes, evidências, divergências, auditoria)'));

      const sinteseNova = sinteseEstruturadaBloco(r);
      if (sinteseNova) visaoCompleta.append(sinteseNova);
      visaoCompleta.append(sinteseDoConselho(r));

      if (participantes.length) {
        const pareceresWrap = el('div', undefined, 'conselho-pareceres-grid');
        for (const codigo of participantes) pareceresWrap.append(parecerExecutivoCard(r, codigo));
        visaoCompleta.append(pareceresWrap);
      }

      const auditoria = el('details', undefined, 'conselho-auditoria');
      auditoria.append(el('summary', 'Dados técnicos (auditoria)'));
      auditoria.append(el('p', 'Demanda completa: ' + (r.demanda || '—')));
      auditoria.append(el('p', 'Contexto: ' + (r.contexto || '—')));
      auditoria.append(el('p', 'Conclusão consolidada (registro bruto): ' + (r.conclusao || '—')));
      auditoria.append(el('p', 'Precisa do Diretor: ' + (r.precisa_diretor ? 'Sim' : 'Não')));
      for (const [rotulo, valor] of [['Participantes', r.participantes], ['Dados apresentados', r.dados_apresentados], ['Posições', r.posicoes], ['Conflitos', r.conflitos], ['Recomendações', r.recomendacoes], ['Vetos', r.vetos], ['Pendências', r.pendencias]]) {
        const b = jsonBloco(rotulo, valor); if (b) auditoria.append(b);
      }
      visaoCompleta.append(auditoria);

      card.append(visaoCompleta);
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
