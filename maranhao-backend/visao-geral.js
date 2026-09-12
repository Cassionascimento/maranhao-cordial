/* Visão Geral executiva: "o que está acontecendo na Maranhão agora?".
   Só leitura -- todas as chamadas são GET em endpoints já existentes (CRM,
   ações comerciais, WhatsApp, C6/Pix, Maranhão Intelligence, IA empresarial).
   Nenhuma escrita, nenhum endpoint novo. Falha em uma fonte não derruba as
   outras: cada uma é buscada e tratada de forma independente. */
(() => {
  'use strict';
  const raiz = document.getElementById('visao-geral-executiva');
  if (!raiz) return;
  const api = 'https://maranhao-cordial-api.onrender.com';
  const $ = id => document.getElementById('vg-' + id);
  let carregado = false, busy = false;

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const fmt = v => (v == null ? '—' : Number(v).toLocaleString('pt-BR'));

  async function chamar(caminho) {
    try {
      const resposta = await fetch(api + caminho, {
        cache: 'no-store',
        headers: { 'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json' },
      });
      const corpo = await resposta.json().catch(() => ({}));
      return { ok: resposta.ok && corpo.success !== false, body: corpo };
    } catch {
      return { ok: false, body: {} };
    }
  }

  function leadsAtivos(leads) {
    if (!leads.ok || !Array.isArray(leads.body.leads)) return null;
    return leads.body.leads.filter(l => l.estagio !== 'cliente' && l.estagio !== 'perdido'
      && !l.arquivado && !l.cadastro_teste).length;
  }

  function acoesPendentes(acoes) {
    if (!acoes.ok || !Array.isArray(acoes.body.acoes)) return null;
    return acoes.body.acoes.filter(a => a.status === 'aguardando_aprovacao').length;
  }

  function scansHoje(mi) {
    if (!mi.ok || !Array.isArray(mi.body.atividade_recente)) return null;
    const hoje = new Date().toISOString().slice(0, 10);
    return mi.body.atividade_recente.filter(e => e.tipo_evento === 'scan'
      && String(e.criado_em || '').slice(0, 10) === hoje).length;
  }

  function estadoWhatsapp(whatsapp) {
    if (!whatsapp.ok) return 'indisponivel';
    if (whatsapp.body.envio_liberado) return 'operacional';
    return whatsapp.body.estado === 'aguardando_meta' ? 'atencao' : 'indisponivel';
  }

  function estadoC6(c6) {
    if (!c6.ok) return 'indisponivel';
    if (c6.body.ready) return 'operacional';
    return c6.body.credentials_configured ? 'atencao' : 'indisponivel';
  }

  function pontosDeAtencao({ acoesQtd, whatsappEstado, c6Estado, ia }) {
    const itens = [];
    if (acoesQtd) itens.push(`${acoesQtd} ação${acoesQtd > 1 ? 'ões' : ''} comercial${acoesQtd > 1 ? 'is' : ''} aguardando aprovação.`);
    if (whatsappEstado !== 'operacional') itens.push('WhatsApp não está com envio liberado — verifique a configuração Meta.');
    if (c6Estado !== 'operacional') itens.push('C6/Pix não está pronto para cobranças.');
    if (ia.ok) {
      for (const item of (ia.body.precisa_atencao || []).slice(0, 5)) {
        itens.push(typeof item === 'string' ? item : (item.titulo || item.descricao || JSON.stringify(item)));
      }
    }
    return itens;
  }

  function renderKpis({ leads, acoesQtd, scans, atencaoQtd }) {
    const container = $('kpis');
    container.replaceChildren();
    for (const [label, valor] of [
      ['Leads ativos', leads],
      ['Aprovações pendentes', acoesQtd],
      ['Scans hoje*', scans],
      ['Alertas abertos', atencaoQtd],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      container.append(stat);
    }
  }

  function renderLeitura(ia) {
    const container = $('leitura');
    container.replaceChildren();
    if (!ia.ok) {
      container.append(el('p', 'Leitura executiva indisponível agora.', 'vg-vazio'));
      return;
    }
    const r = ia.body.resumo || {};
    container.append(el('p',
      `${fmt(r.total_atencao)} pontos de atenção · ${fmt(r.total_novos_prospectos)} novos prospectos · ${fmt(r.total_proximas_acoes)} próximas ações.`));
    const botao = el('button', 'Abrir análise completa da IA →');
    botao.type = 'button';
    botao.dataset.vgTab = 'ia-empresarial';
    container.append(botao);
  }

  function renderAtencao(itens) {
    const container = $('atencao');
    container.replaceChildren();
    if (!itens.length) {
      container.append(el('p', 'Nada exige atenção agora.', 'vg-vazio'));
      return;
    }
    const lista = el('ul', undefined, 'vg-atencao-lista');
    for (const item of itens) lista.append(el('li', item));
    container.append(lista);
  }

  function canal(rotulo, estado) {
    const rotulos = {
      operacional: 'Operacional', atencao: 'Atenção',
      indisponivel: 'Indisponível', desconhecido: 'Sem verificação automática',
    };
    const item = el('div', undefined, 'vg-canal vg-canal-' + estado);
    item.append(el('strong', rotulo), el('span', rotulos[estado]));
    return item;
  }

  function renderCanais(whatsappEstado, c6Estado) {
    const container = $('canais');
    container.replaceChildren();
    container.append(canal('Gmail', 'desconhecido'));
    container.append(canal('WhatsApp', whatsappEstado));
    container.append(canal('C6/Pix', c6Estado));
  }

  function renderMi(mi) {
    const container = $('mi');
    container.replaceChildren();
    if (!mi.ok) {
      container.append(el('p', 'Painel Maranhão Intelligence indisponível agora.', 'vg-vazio'));
      return;
    }
    const r = mi.body.resumo || {};
    const faixa = el('div', undefined, 'mi-resumo');
    for (const [label, valor] of [
      ['Unidades', r.unidades], ['Eventos', r.eventos],
      ['Scans QR', r.scans_qr], ['Territórios ativos', r.territorios_ativos],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      faixa.append(stat);
    }
    container.append(faixa);
  }

  function controles(valor) {
    busy = valor;
    $('atualizar').disabled = valor;
  }

  async function carregarTudo() {
    if (busy) return;
    if (!window.adminKeyAtual) {
      $('status').textContent = 'Entre no Admin para consultar os dados.';
      return;
    }
    controles(true);
    $('status').textContent = 'Consultando o estado atual…';
    try {
      const [leads, acoes, whatsapp, c6, mi, ia] = await Promise.all([
        chamar('/api/admin/crm/leads'),
        chamar('/api/admin/acoes-comerciais'),
        chamar('/api/admin/omnichannel/whatsapp'),
        chamar('/api/c6/status'),
        chamar('/api/admin/mi/painel'),
        chamar('/api/admin/ia-empresarial/hoje'),
      ]);

      const whatsappEstado = estadoWhatsapp(whatsapp);
      const c6Estado = estadoC6(c6);
      const acoesQtd = acoesPendentes(acoes);
      const itensAtencao = pontosDeAtencao({ acoesQtd: acoesQtd || 0, whatsappEstado, c6Estado, ia });

      renderKpis({
        leads: leadsAtivos(leads),
        acoesQtd,
        scans: scansHoje(mi),
        atencaoQtd: itensAtencao.length,
      });
      renderLeitura(ia);
      renderAtencao(itensAtencao);
      renderCanais(whatsappEstado, c6Estado);
      renderMi(mi);

      // Mesmo evento que carregarLeadsCRM já dispara: o funil comercial existente
      // (painel-executivo.js) reage sozinho, sem duplicar lógica de cálculo aqui.
      if (leads.ok) {
        window.dispatchEvent(new CustomEvent('executivo-dados', { detail: { fonte: 'crm', dados: leads.body.leads || [] } }));
      }

      $('status').textContent = 'Leitura atualizada. Nenhuma ação foi executada.';
      $('conteudo').hidden = false;
      carregado = true;
    } catch (erro) {
      $('status').textContent = 'Não foi possível consultar o estado atual agora.';
    } finally {
      controles(false);
    }
  }

  $('atualizar').addEventListener('click', carregarTudo);
  raiz.addEventListener('click', evento => {
    const botao = evento.target.closest('[data-vg-tab]');
    if (!botao) return;
    document.querySelector(`.admin-tab[data-tab="${botao.dataset.vgTab}"]`)?.click();
  });
  document.querySelector('[data-tab="visao-geral"]').addEventListener('click', () => {
    if (!carregado && window.adminKeyAtual) carregarTudo();
  });
  window.addEventListener('admin-autorizado', () => {
    const painelAtivo = document.querySelector('.tab-panel[data-panel="visao-geral"]');
    if (painelAtivo && painelAtivo.classList.contains('active')) carregarTudo();
  });
})();
