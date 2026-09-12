/* Painel somente leitura do Maranhão Intelligence. Nenhuma ação de escrita aqui. */
(() => {
  'use strict';
  const panel = document.getElementById('mi-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/mi/painel';
  const $ = id => document.getElementById('mi-' + id);
  let painel = null, busy = false;

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
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar os dados.');
    const response = await fetch(api, {
      cache: 'no-store',
      headers: { 'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json' },
    });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar o painel.');
    return body;
  }

  function controls(value) {
    busy = value;
    $('atualizar').disabled = value;
  }

  function tabela(container, colunas, linhas, vazio) {
    container.replaceChildren();
    if (!linhas.length) {
      container.append(el('p', vazio, 'mi-vazio'));
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

  function local(cidade, uf) {
    return [cidade, uf].filter(Boolean).join(' / ') || 'Sem estabelecimento vinculado';
  }

  function render() {
    const r = painel.resumo;
    const resumo = $('resumo');
    resumo.replaceChildren();
    for (const [label, valor] of [
      ['Unidades', r.unidades],
      ['Eventos', r.eventos],
      ['Scans QR', r.scans_qr],
      ['Estabelecimentos', r.estabelecimentos],
      ['Territórios ativos', r.territorios_ativos],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      resumo.append(stat);
    }

    tabela(
      $('atividade'),
      ['Quando', 'Tipo', 'Canal', 'SKU', 'Território'],
      painel.atividade_recente.map(e => [
        dataHora(e.criado_em), e.tipo_evento, e.canal, e.sku || '—', local(e.cidade, e.uf),
      ]),
      'Nenhum evento registrado ainda.'
    );

    const produto = $('produto');
    produto.replaceChildren();
    const secundario = painel.secundario;
    const linhaSecundaria = el('div', undefined, 'mi-secundario-lista');
    linhaSecundaria.append(
      (() => { const s = el('span'); s.append('SKUs cadastrados: ', el('strong', fmt(secundario.skus))); return s; })(),
      (() => { const s = el('span'); s.append('Lotes cadastrados: ', el('strong', fmt(secundario.lotes))); return s; })(),
      (() => { const s = el('span'); s.append('Unidades emitidas: ', el('strong', fmt(secundario.unidades_por_estado.emitida))); return s; })(),
      (() => { const s = el('span'); s.append('Unidades ativas: ', el('strong', fmt(secundario.unidades_por_estado.ativa))); return s; })(),
      (() => { const s = el('span'); s.append('Unidades revogadas: ', el('strong', fmt(secundario.unidades_por_estado.revogada))); return s; })(),
    );
    produto.append(linhaSecundaria);
    const porSku = el('div');
    porSku.append(el('h4', 'Distribuição por SKU'));
    produto.append(porSku);
    tabela(
      porSku,
      ['SKU', 'Produto', 'Eventos'],
      painel.produto.por_sku.map(s => [s.sku, s.produto_nome || '—', fmt(s.total)]),
      'Nenhum evento com SKU registrado ainda.'
    );
    const porLote = el('div');
    porLote.append(el('h4', 'Distribuição por lote'));
    produto.append(porLote);
    tabela(
      porLote,
      ['Lote', 'Eventos'],
      painel.produto.por_lote.map(l => [l.lote, fmt(l.total)]),
      'Nenhum evento associado a lote ainda.'
    );

    tabela(
      $('estabelecimentos'),
      ['Estabelecimento', 'Território', 'Eventos'],
      painel.estabelecimentos_distribuicao.map(e => [e.nome, local(e.cidade, e.uf), fmt(e.total)]),
      'Nenhum evento vinculado a estabelecimento ainda.'
    );

    tabela(
      $('territorio'),
      ['Território', 'Eventos'],
      painel.territorio.map(t => [local(t.cidade, t.uf), fmt(t.total)]),
      'Nenhum território com eventos ainda.'
    );

    $('conteudo').hidden = false;
  }

  async function load() {
    if (busy) return;
    controls(true);
    $('status').textContent = 'Consultando o painel…';
    try {
      painel = await call();
      render();
      $('status').textContent = 'Leitura atualizada. Painel somente leitura; nenhuma ação foi executada.';
    } catch (e) {
      $('status').textContent = e.message;
    } finally {
      controls(false);
    }
  }

  $('atualizar').addEventListener('click', load);
  document.querySelector('[data-tab="maranhao-intelligence"]').addEventListener('click', () => {
    if (!painel && window.adminKeyAtual) load();
  });
  window.addEventListener('admin-autorizado', () => {
    if (panel.classList.contains('active')) load();
  });
})();
