/* Canais -- painel somente leitura. Só consome GET /api/admin/canais/status
   (canais_status.py); nenhuma ação, nenhum envio, nenhum dado inventado. */
(() => {
  'use strict';
  const panel = document.getElementById('canais-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/canais/status';
  const $ = id => document.getElementById('canais-' + id);
  let busy = false;

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const ESTADO_ROTULO = { conectado: 'Conectado', pendente: 'Pendente', bloqueado: 'Bloqueado' };
  const simNao = v => (v ? 'Sim' : 'Não');

  async function call() {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar os Canais.');
    const response = await fetch(api, { cache: 'no-store', headers: { 'X-Admin-Key': window.adminKeyAtual } });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar os Canais.');
    return body.canais;
  }

  function render(canais) {
    const container = $('conteudo');
    container.replaceChildren();
    const wrap = el('div', undefined, 'mi-tabela-wrap');
    const tabela = el('table', undefined, 'mi-tabela');
    const thead = el('thead');
    const trh = el('tr');
    for (const c of ['Canal', 'Estado', 'Última sincronização', 'Leitura', 'Escrita', 'Aprovação exigida', 'Último erro', 'Próximo passo externo']) trh.append(el('th', c));
    thead.append(trh);
    tabela.append(thead);
    const tbody = el('tbody');
    for (const canal of canais) {
      const tr = el('tr', undefined, 'canais-linha-' + canal.estado);
      tr.append(
        el('td', canal.canal),
        el('td', ESTADO_ROTULO[canal.estado] || canal.estado, 'canais-badge canais-badge-' + canal.estado),
        el('td', canal.ultima_sincronizacao || 'nunca sincronizado'),
        el('td', simNao(canal.leitura_disponivel)),
        el('td', simNao(canal.escrita_disponivel)),
        el('td', simNao(canal.aprovacao_exigida)),
        el('td', canal.ultimo_erro || '—'),
        el('td', canal.proximo_passo || '—'),
      );
      tbody.append(tr);
    }
    tabela.append(tbody);
    wrap.append(tabela);
    container.append(wrap);
    $('conteudo').hidden = false;
  }

  async function load() {
    if (busy) return;
    busy = true;
    $('atualizar').disabled = true;
    $('status').textContent = 'Consultando os Canais…';
    try {
      const canais = await call();
      render(canais);
      $('status').textContent = 'Leitura atualizada. Nenhuma ação foi executada.';
    } catch (e) {
      $('status').textContent = e.message;
    } finally {
      busy = false;
      $('atualizar').disabled = false;
    }
  }

  $('atualizar').addEventListener('click', load);
  const tab = document.querySelector('[data-tab="canais"]');
  if (tab) tab.addEventListener('click', () => { if (window.adminKeyAtual) load(); });
})();
