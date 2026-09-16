/* Relacionamento 360 -- visão única do contato (CRM + identidades por canal
   já resolvidas + interações WhatsApp/Instagram/Gmail, quando existentes) e
   Next Best Action (até 3 sugestões, sempre com motivo/evidência/confiança/
   responsável). Nenhuma fusão de identidade acontece aqui -- só lê o que o
   Contact Central já resolveu. Nenhuma ação é executada -- só recomendação. */
(() => {
  'use strict';
  const panel = document.getElementById('relacionamento-360-painel');
  if (!panel) return;
  const apiBase = 'https://maranhao-cordial-api.onrender.com/api/admin/mi';
  const $ = id => document.getElementById('relacionamento-360-' + id);
  const authHeaders = extra => Object.assign({ 'X-Admin-Key': window.adminKeyAtual || '' }, extra || {});
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const dataHora = iso => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('pt-BR');
  };

  async function buscar() {
    const termo = $('busca').value.trim();
    const raiz = $('resultados');
    raiz.replaceChildren();
    $('detalhe').hidden = true;
    if (!window.adminKeyAtual) { raiz.append(el('p', 'Entre no Admin para buscar.', 'mi-subtitle')); return; }
    if (!termo) { raiz.append(el('p', 'Digite um termo de busca.', 'mi-subtitle')); return; }
    raiz.append(el('p', 'Buscando...', 'mi-subtitle'));
    try {
      const resp = await fetch(apiBase + '/visao-unica/buscar?q=' + encodeURIComponent(termo), { cache: 'no-store', headers: authHeaders() });
      const body = await resp.json();
      if (!resp.ok || !body.success) throw new Error(body.error || 'Falha na busca.');
      renderizarResultados(body.resultados || []);
    } catch (erro) {
      raiz.replaceChildren(el('p', erro.message || 'Falha na busca.', 'mi-subtitle'));
    }
  }

  function renderizarResultados(leads) {
    const raiz = $('resultados');
    raiz.replaceChildren();
    if (!leads.length) { raiz.append(el('p', 'Nenhum contato encontrado.', 'mi-subtitle')); return; }
    const lista = el('ul', undefined, 'relacionamento-360-lista');
    leads.forEach(lead => {
      const item = el('li');
      const botao = el('button', (lead.nome || 'Sem nome') + ' · ' + (lead.empresa || '—') + ' · ' + (lead.estagio || '—'), 'btn-secundario');
      botao.type = 'button';
      botao.addEventListener('click', () => abrirDetalhe(lead.id));
      item.append(botao);
      lista.append(item);
    });
    raiz.append(lista);
  }

  async function abrirDetalhe(leadId) {
    const raiz = $('detalhe');
    raiz.hidden = false;
    raiz.replaceChildren(el('p', 'Carregando...', 'mi-subtitle'));
    try {
      const [visaoResp, nbaResp] = await Promise.all([
        fetch(apiBase + '/visao-unica/' + encodeURIComponent(leadId), { cache: 'no-store', headers: authHeaders() }),
        fetch(apiBase + '/next-best-action/' + encodeURIComponent(leadId), { cache: 'no-store', headers: authHeaders() }),
      ]);
      const visao = await visaoResp.json();
      const nba = await nbaResp.json();
      if (!visaoResp.ok || !visao.success) throw new Error(visao.error || 'Falha ao carregar visão única.');
      renderizarDetalhe(visao, nbaResp.ok && nba.success ? nba.sugestoes : []);
    } catch (erro) {
      raiz.replaceChildren(el('p', erro.message || 'Falha ao carregar detalhe.', 'mi-subtitle'));
    }
  }

  function renderizarDetalhe(visao, sugestoes) {
    const raiz = $('detalhe');
    raiz.replaceChildren();
    const lead = visao.lead;

    const cabecalho = el('div', undefined, 'mi-bloco');
    cabecalho.append(el('h3', lead.nome || 'Sem nome'));
    cabecalho.append(el('p', [lead.empresa, lead.email, lead.telefone, lead.instagram].filter(Boolean).join(' · ') || 'Sem dados de contato', 'mi-subtitle'));
    cabecalho.append(el('p', 'Estágio: ' + (lead.estagio || '—') + ' · Status: ' + (lead.status || '—')));
    raiz.append(cabecalho);

    const blocoIdentidades = el('div', undefined, 'mi-bloco');
    blocoIdentidades.append(el('h4', 'Identidades por canal'));
    const identidades = visao.identidades_por_canal || [];
    if (!identidades.length) {
      blocoIdentidades.append(el('p', 'Nenhuma identidade externa vinculada ainda.', 'mi-subtitle'));
    } else {
      const ul = el('ul');
      identidades.forEach(i => ul.append(el('li',
        i.canal + ': ' + (i.username_publico || i.identificador_externo) +
        (i.confianca != null ? ' (confiança ' + i.confianca + ')' : '') + ' — vínculo: ' + (i.criterio_vinculo || '—'))));
      blocoIdentidades.append(ul);
    }
    raiz.append(blocoIdentidades);

    const blocoInteracoes = el('div', undefined, 'mi-bloco');
    blocoInteracoes.append(el('h4', 'Interações recentes (' + (visao.total_interacoes_na_janela || 0) + ')'));
    const interacoes = visao.interacoes_recentes || [];
    if (!interacoes.length) {
      blocoInteracoes.append(el('p', 'Nenhuma interação registrada.', 'mi-subtitle'));
    } else {
      const ul = el('ul');
      interacoes.slice(0, 10).forEach(i => ul.append(el('li',
        dataHora(i.criado_em) + ' · ' + i.canal + (i.tipo_interacao ? ' (' + i.tipo_interacao + ')' : '') +
        (i.interesse || i.classificacao ? ' · sinal: ' + (i.interesse || i.classificacao) : ''))));
      blocoInteracoes.append(ul);
    }
    raiz.append(blocoInteracoes);

    const blocoNba = el('div', undefined, 'mi-bloco');
    blocoNba.append(el('h4', 'Next Best Action (até 3 sugestões)'));
    if (!sugestoes.length) {
      blocoNba.append(el('p', 'Nenhuma sugestão com evidência suficiente no momento.', 'mi-subtitle'));
    } else {
      sugestoes.forEach(s => {
        const card = el('div', undefined, 'relacionamento-360-sugestao');
        card.append(el('strong', s.tipo.replace(/_/g, ' ')));
        card.append(el('span', ' · confiança ' + s.confianca + ' · responsável: ' + s.responsavel, 'mi-subtitle'));
        card.append(el('p', s.motivo));
        const ul = el('ul');
        (s.evidencia || []).forEach(e => ul.append(el('li', e)));
        card.append(ul);
        if (s.bloqueio) card.append(el('p', 'Bloqueado para envio: ' + s.bloqueio, 'conselho-veto-texto'));
        blocoNba.append(card);
      });
    }
    raiz.append(blocoNba);
  }

  $('buscar-botao').addEventListener('click', buscar);
  $('busca').addEventListener('keydown', ev => { if (ev.key === 'Enter') buscar(); });
})();
