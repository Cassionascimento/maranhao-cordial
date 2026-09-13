/* Conselho de Agentes -- painel somente leitura, detalhado, dentro de
   Maranhão Intelligence. Só consome GET /api/admin/mi/conselho (mi_conselho.
   leitura_conselho); nenhuma escrita, nenhuma invocação de agente, nenhum
   /conclave é disparado por esta tela. Mesmo padrão de maranhao-
   intelligence.js: busca, guarda em memória, desenha. */
(() => {
  'use strict';
  const panel = document.getElementById('conselho-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/mi/conselho';
  const $ = id => document.getElementById('conselho-' + id);
  let conselho = null, busy = false;

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

  async function call() {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar o Conselho.');
    const response = await fetch(api, {
      cache: 'no-store',
      headers: { 'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json' },
    });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar o Conselho.');
    return body.conselho;
  }

  function controls(value) {
    busy = value;
    $('atualizar').disabled = value;
  }

  function tabela(container, colunas, linhas, vazioTexto) {
    container.replaceChildren();
    if (!linhas.length) {
      container.append(el('p', vazioTexto, 'mi-vazio'));
      return;
    }
    const wrap = el('div', undefined, 'mi-tabela-wrap');
    const tabelaEl = el('table', undefined, 'mi-tabela');
    const thead = el('thead');
    const trh = el('tr');
    for (const c of colunas) trh.append(el('th', c));
    thead.append(trh);
    tabelaEl.append(thead);
    const tbody = el('tbody');
    for (const linha of linhas) {
      const tr = el('tr');
      for (const valor of linha) tr.append(el('td', valor));
      tbody.append(tr);
    }
    tabelaEl.append(tbody);
    wrap.append(tabelaEl);
    container.append(wrap);
  }

  function jsonBloco(rotulo, valor) {
    if (valor == null || (Array.isArray(valor) && !valor.length) || (typeof valor === 'object' && !Array.isArray(valor) && !Object.keys(valor).length)) {
      return null;
    }
    const bloco = el('div', undefined, 'conselho-json-bloco');
    bloco.append(el('span', rotulo, 'conselho-json-rotulo'));
    bloco.append(el('pre', JSON.stringify(valor, null, 2), 'conselho-json-pre'));
    return bloco;
  }

  const NOMES_EVENTO = {
    mensagem_enviada: 'Troca de mensagem', reuniao_registrada: 'Reunião registrada',
    conclave_registrado: 'Conclave registrado', relatorio_registrado: 'Relatório registrado',
  };

  function participaDe(registro, codigo) {
    return Array.isArray(registro.participantes) && registro.participantes.includes(codigo);
  }

  function renderAgentes() {
    const container = $('agentes');
    container.replaceChildren();
    const mensagens = conselho.mensagens_recentes || [];
    const relatorios = conselho.relatorios_recentes || [];
    const reunioes = conselho.reunioes_recentes || [];
    for (const agente of conselho.agentes || []) {
      const card = el('div', undefined, 'conselho-agente-card conselho-agente-' + agente.status);
      card.append(el('strong', agente.nome, 'conselho-agente-nome'));
      card.append(el('span', agente.area, 'conselho-agente-area'));
      card.append(el('span', agente.status === 'trabalhando' ? 'Trabalhando' : 'Sem demanda', 'conselho-agente-status'));

      const atividade = agente.ultima_atividade;
      card.append(el('p', 'Última atividade: ' + (atividade
        ? (NOMES_EVENTO[atividade.tipo_evento] || atividade.tipo_evento) + ' em ' + dataHora(atividade.criado_em)
        : 'nenhuma registrada')));

      const demandaAtual = agente.status === 'trabalhando' && [...reunioes, ...relatorios]
        .filter(r => participaDe(r, agente.codigo))
        .sort((a, b) => new Date(b.criado_em) - new Date(a.criado_em))[0];
      card.append(el('p', 'Demanda atual: ' + (demandaAtual ? (demandaAtual.demanda || '—') : 'nenhuma')));

      const ultimaMensagem = mensagens.find(m => m.de_agente === agente.codigo);
      card.append(el('p', 'Última mensagem: ' + (ultimaMensagem ? ('"' + ultimaMensagem.texto + '"') : 'nenhuma')));

      const ultimoRelatorio = relatorios.find(r => participaDe(r, agente.codigo));
      card.append(el('p', 'Último relatório: ' + (ultimoRelatorio ? (ultimoRelatorio.conclusao || ultimoRelatorio.demanda || '—') : 'nenhum')));

      card.append(el('p', 'Próxima atividade: nenhuma agendada (agentes só atuam por demanda real)', 'conselho-agente-nota'));
      container.append(card);
    }
  }

  function renderMensagens() {
    tabela(
      $('mensagens'),
      ['Quando', 'De', 'Para', 'Demanda', 'Mensagem'],
      (conselho.mensagens_recentes || []).map(m => [
        dataHora(m.criado_em), m.de_agente, m.para_agente || 'todos', m.demanda_referencia || '—', m.texto,
      ]),
      'Nenhuma mensagem registrada entre agentes ainda.'
    );
  }

  function renderReunioes() {
    tabela(
      $('reunioes'),
      ['Quando', 'Tipo', 'Demanda', 'Participantes', 'Precisa Diretor'],
      (conselho.reunioes_recentes || []).map(r => [
        dataHora(r.criado_em), r.tipo === 'conclave' ? 'Conclave' : 'Reunião', r.demanda || '—',
        (r.participantes || []).join(', ') || '—', r.precisa_diretor ? 'Sim' : 'Não',
      ]),
      'Nenhuma reunião ou conclave registrado ainda.'
    );
  }

  function renderAtas() {
    const container = $('atas');
    container.replaceChildren();
    const registros = conselho.reunioes_recentes || [];
    if (!registros.length) {
      container.append(el('p', 'Nenhuma ata registrada ainda.', 'mi-vazio'));
      return;
    }
    for (const r of registros) {
      const card = el('div', undefined, 'conselho-ata-card');
      const cabecalho = el('div', undefined, 'conselho-ata-cabecalho');
      cabecalho.append(el('strong', (r.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — v' + r.versao));
      cabecalho.append(el('span', dataHora(r.criado_em)));
      card.append(cabecalho);
      card.append(el('p', 'Demanda: ' + (r.demanda || '—')));
      card.append(el('p', 'Contexto: ' + (r.contexto || '—')));
      card.append(el('p', 'Conclusão: ' + (r.conclusao || '—')));
      card.append(el('p', 'Precisa do Diretor: ' + (r.precisa_diretor ? 'Sim' : 'Não')));
      for (const [rotulo, valor] of [
        ['Participantes', r.participantes], ['Dados apresentados', r.dados_apresentados],
        ['Posições', r.posicoes], ['Conflitos', r.conflitos], ['Recomendações', r.recomendacoes],
        ['Vetos', r.vetos], ['Pendências', r.pendencias],
      ]) {
        const bloco = jsonBloco(rotulo, valor);
        if (bloco) card.append(bloco);
      }
      container.append(card);
    }
  }

  function renderRelatorios() {
    tabela(
      $('relatorios'),
      ['Quando', 'Demanda', 'Participantes', 'Conclusão', 'Precisa Diretor'],
      (conselho.relatorios_recentes || []).map(r => [
        dataHora(r.criado_em), r.demanda || '—', (r.participantes || []).join(', ') || '—',
        r.conclusao || '—', r.precisa_diretor ? 'Sim' : 'Não',
      ]),
      'Nenhum relatório registrado ainda (só é gerado quando há atividade real).'
    );
  }

  function renderConflitos() {
    const container = $('conflitos');
    container.replaceChildren();
    const lista = conselho.conflitos || [];
    if (!lista.length) {
      container.append(el('p', 'Nenhum conflito identificado até o momento.', 'mi-vazio'));
      return;
    }
    for (const item of lista) {
      const bloco = el('div', undefined, 'conselho-json-card');
      bloco.append(el('strong', (item.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — registro ' + item.registro_id));
      bloco.append(el('pre', JSON.stringify(item.conflitos, null, 2), 'conselho-json-pre'));
      container.append(bloco);
    }
  }

  function renderVetos() {
    const container = $('vetos');
    container.replaceChildren();
    const lista = conselho.vetos || [];
    if (!lista.length) {
      container.append(el('p', 'Nenhum veto registrado.', 'mi-vazio'));
      return;
    }
    for (const item of lista) {
      const bloco = el('div', undefined, 'conselho-json-card conselho-json-card--veto');
      bloco.append(el('strong', (item.tipo === 'conclave' ? 'Conclave' : 'Reunião') + ' — registro ' + item.registro_id));
      bloco.append(el('pre', JSON.stringify(item.vetos, null, 2), 'conselho-json-pre'));
      container.append(bloco);
    }
  }

  function renderAguardandoDiretor() {
    tabela(
      $('diretor'),
      ['Quando', 'Tipo', 'Demanda', 'Conclusão'],
      (conselho.aguardando_diretor || []).map(r => [
        dataHora(r.criado_em), { reuniao: 'Reunião', conclave: 'Conclave', relatorio: 'Relatório' }[r.tipo] || r.tipo,
        r.demanda || '—', r.conclusao || '—',
      ]),
      'Nenhum item aguardando decisão do Diretor.'
    );
  }

  function render() {
    const resumo = $('resumo');
    resumo.replaceChildren();
    for (const [label, valor] of [
      ['Agentes disponíveis', (conselho.agentes || []).length],
      ['Trabalhando', conselho.trabalhando],
      ['Sem demanda', conselho.sem_demanda],
      ['Conflitos', (conselho.conflitos || []).length],
      ['Vetos', (conselho.vetos || []).length],
      ['Aguardando Diretor', (conselho.aguardando_diretor || []).length],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      resumo.append(stat);
    }

    renderAgentes();
    renderMensagens();
    renderReunioes();
    renderAtas();
    renderRelatorios();
    renderConflitos();
    renderVetos();
    renderAguardandoDiretor();

    $('conteudo').hidden = false;
  }

  async function load() {
    if (busy) return;
    controls(true);
    $('status').textContent = 'Consultando o Conselho…';
    try {
      conselho = await call();
      render();
      $('status').textContent = 'Leitura atualizada. Painel somente leitura; nenhuma ação foi executada.';
    } catch (e) {
      $('status').textContent = e.message;
    } finally {
      controls(false);
    }
  }

  $('atualizar').addEventListener('click', load);
  document.querySelector('[data-tab="conselho-de-agentes"]').addEventListener('click', () => {
    if (!conselho && window.adminKeyAtual) load();
  });
  window.addEventListener('admin-autorizado', () => {
    if (panel.classList.contains('active')) load();
  });
})();
