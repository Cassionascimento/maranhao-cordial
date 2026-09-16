/* Saúde dos Agentes -- observabilidade das chamadas reais do Conselho.
   Nunca mostra prompt, resposta bruta, segredo ou stack trace -- só o que
   mi_conselho_saude.py já expõe (status/duração/erro categorizado/modelo/
   tokens). Falha de agente aparece como falha, nunca como "sem dado". */
(() => {
  'use strict';
  const panel = document.getElementById('saude-agentes-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/mi/conselho/saude';
  const $ = id => document.getElementById('saude-agentes-' + id);
  const authHeaders = extra => Object.assign({ 'X-Admin-Key': window.adminKeyAtual || '' }, extra || {});

  const NOMES = {
    pirret: 'Pirret · Marketing', standard: 'Standard · Financeiro', zilda: 'Zilda · Pessoas',
    leonard: 'Leonard · Vendas', marie: 'Marie · Produto', rua: 'Rua · Operações',
    dicio: 'Dicio · Jurídico', iris: 'Iris · Dados',
  };
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const dataHora = iso => {
    if (!iso) return 'nunca executado';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR');
  };
  const chipStatus = status => {
    const rotulo = { sucesso: 'Sucesso', falha: 'Falha', sem_execucao: 'Sem execução' }[status] || status;
    return el('span', rotulo, 'saude-chip saude-chip-' + status);
  };

  async function carregar() {
    if (!window.adminKeyAtual) { $('status').textContent = 'Entre no Admin para consultar.'; return; }
    $('status').textContent = 'Consultando...';
    $('conteudo').hidden = true;
    const janela = $('janela').value || '24';
    try {
      const resp = await fetch(api + '?janela_horas=' + encodeURIComponent(janela), { cache: 'no-store', headers: authHeaders() });
      const body = await resp.json();
      if (!resp.ok || !body.success) throw new Error(body.error || 'Falha ao consultar saúde dos agentes.');
      renderizar(body.agentes || []);
      $('status').textContent = 'Atualizado agora · janela de ' + janela + 'h.';
    } catch (erro) {
      $('status').textContent = erro.message || 'Não foi possível consultar a saúde dos agentes.';
    }
  }

  function renderizar(agentes) {
    const raiz = $('conteudo');
    raiz.replaceChildren();
    raiz.hidden = false;

    const tabela = el('table', undefined, 'saude-tabela');
    const thead = el('thead');
    const linhaCabecalho = el('tr');
    ['Agente', 'Status', 'Última execução', 'Duração', 'Modelo', 'Tokens saída (últ.)', 'Sucesso na janela', 'Falhas por categoria']
      .forEach(rotulo => linhaCabecalho.append(el('th', rotulo)));
    thead.append(linhaCabecalho);
    tabela.append(thead);

    const tbody = el('tbody');
    agentes.forEach(a => {
      const tr = el('tr', undefined, a.status === 'falha' ? 'saude-linha-falha' : '');
      tr.append(el('td', NOMES[a.agente] || a.agente));
      const tdStatus = el('td'); tdStatus.append(chipStatus(a.status)); tr.append(tdStatus);
      tr.append(el('td', dataHora(a.ultima_execucao)));
      tr.append(el('td', a.duracao_ms != null ? (a.duracao_ms / 1000).toFixed(1) + 's' : '—'));
      tr.append(el('td', a.modelo || '—'));
      tr.append(el('td', a.tokens_saida_total != null ? String(a.tokens_saida_total) : '—'));
      tr.append(el('td', a.total_execucoes ? Math.round((a.taxa_sucesso || 0) * 100) + '% (' + a.total_sucesso + '/' + a.total_execucoes + ')' : '—'));
      const categorias = Object.entries(a.falhas_por_categoria || {});
      const tdFalhas = el('td', categorias.length ? categorias.map(([cat, n]) => cat + ' ×' + n).join(', ') : '—');
      tr.append(tdFalhas);
      if (a.status === 'falha' && a.erro_detalhe) {
        tr.title = a.erro_categoria + ': ' + a.erro_detalhe;
      }
      tbody.append(tr);
    });
    tabela.append(tbody);
    raiz.append(tabela);
    raiz.append(el('p', 'Falha de um agente nunca é concordância -- entra como falha explícita, nunca "sem objeção".', 'mi-subtitle'));
  }

  $('atualizar').addEventListener('click', carregar);
  $('janela').addEventListener('change', carregar);
})();
