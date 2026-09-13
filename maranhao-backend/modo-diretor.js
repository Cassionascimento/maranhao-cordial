/* Modo Diretor (ETAPA 5.3): HOME executiva do Admin.
   Só consome /api/admin/mi/diretor -- nenhuma lógica de negócio aqui, tudo
   já vem calculado por mi_diretor.py. Este arquivo só busca e desenha.
   Mesmo padrão de visao-geral.js: guarda de adminKeyAtual, sem gravação,
   sem endpoint novo, estado vazio sempre explicado (nunca dado fictício). */
(() => {
  'use strict';
  const raiz = document.getElementById('modo-diretor');
  if (!raiz) return;
  const api = 'https://maranhao-cordial-api.onrender.com';
  const $ = id => document.getElementById('md-' + id);
  let carregado = false, busy = false;

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const vazio = texto => el('p', texto, 'vg-vazio');
  const fmt = v => (v == null ? '—' : Number(v).toLocaleString('pt-BR'));

  const ROTULOS_NATUREZA = {
    fato: 'Fato', interesse_observado: 'Interesse observado', inferencia: 'Inferência',
    recomendacao: 'Recomendação', acao: 'Ação', resultado: 'Resultado',
  };
  function selo(natureza) {
    if (!natureza) return null;
    const span = el('span', ROTULOS_NATUREZA[natureza] || natureza, 'md-natureza md-natureza-' + natureza);
    return span;
  }

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

  function renderStatus(leitura) {
    const container = $('status');
    container.replaceChildren();
    const precisa = leitura.chamar_diretor && leitura.chamar_diretor.necessario;
    const trabalhando = leitura.ia_trabalhando;
    const estado = precisa ? 'precisa' : trabalhando ? 'trabalhando' : 'aguardando';
    const texto = precisa ? 'Precisa de você' : trabalhando ? 'IA trabalhando' : 'IA aguardando';
    container.className = 'md-status md-status-' + estado;
    container.append(el('span', undefined, 'md-status-ponto'), el('strong', texto));
  }

  function renderHoje(hoje) {
    const container = $('hoje');
    container.replaceChildren();
    for (const [label, valor] of [
      ['Planejado', (hoje.planejado || []).length],
      ['Concluído', (hoje.concluido || []).length],
      ['Aguardando', (hoje.aguardando || []).length],
      ['Oportunidades', (hoje.oportunidades || []).length],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      container.append(stat);
    }
  }

  const ROTULOS_ACAO = {
    pesquisar: 'Pesquisar novos contatos', enviar_followup: 'Enviar follow-up', avaliar_reengajamento: 'Avaliar reengajamento',
    revisar_bloqueio: 'Revisar bloqueio', decidir_proposta: 'Decidir proposta', priorizar_atendimento: 'Priorizar atendimento',
    informar_diretor: 'Informar sobre mudança de público', sugerir_conteudo: 'Sugerir conteúdo',
  };
  function formatarQuando(iso) {
    if (!iso) return null;
    const data = new Date(iso);
    if (Number.isNaN(data.getTime())) return iso;
    return data.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }

  function renderProximaAcao(proxima) {
    const container = $('proxima');
    container.replaceChildren();
    if (!proxima) {
      container.append(vazio('Nenhuma próxima ação planejada ainda.'));
      return;
    }
    const p = el('p', undefined, 'md-proxima');
    p.append(el('strong', ROTULOS_ACAO[proxima.o_que] || proxima.o_que || 'Ação não identificada'));
    const quando = formatarQuando(proxima.quando);
    if (quando) p.append(document.createTextNode(' — ' + quando));
    if (proxima.motivo) p.append(el('span', proxima.motivo, 'md-motivo'));
    container.append(p);
  }

  function renderPrecisaDeVoce(chamar) {
    const container = $('precisa');
    container.replaceChildren();
    if (!chamar || !chamar.necessario) {
      container.append(el('p', 'Nada. A rotina está sob controle da IA.', 'md-precisa-nada'));
      return;
    }
    const lista = el('ul', undefined, 'md-precisa-lista');
    for (const motivo of chamar.motivos || []) lista.append(el('li', motivo));
    container.append(lista);
  }

  function renderTop10(top10) {
    const container = $('top10');
    container.replaceChildren();
    if (!top10 || !top10.length) {
      container.append(vazio('Nenhum assunto de interesse identificado ainda — aguardando sinais de CRM, interações e prospecção.'));
      return;
    }
    const lista = el('ol', undefined, 'md-top10');
    const simbolos = { subindo: '↑', caindo: '↓', estavel: '→', novo: '↑' };
    for (const item of top10) {
      const li = el('li');
      li.append(el('span', String(item.posicao), 'md-posicao'), el('span', item.tema, 'md-tema'));
      const badge = selo(item.natureza);
      if (badge) li.append(badge);
      const simbolo = simbolos[item.tendencia] || '→';
      li.append(el('span', simbolo, 'md-tendencia md-tendencia-' + (item.tendencia || 'estavel')));
      lista.append(li);
    }
    container.append(lista);
  }

  function renderConteudoHoje(conteudos) {
    const container = $('conteudo');
    container.replaceChildren();
    if (!conteudos || !conteudos.length) {
      container.append(vazio('Nenhum conteúdo sugerido ainda (é preciso ao menos um assunto de interesse identificado).'));
      return;
    }
    const grade = el('div', undefined, 'md-conteudo-grid');
    const rotulosSlot = { manha: 'Manhã', tarde: 'Tarde', noite: 'Noite' };
    const rotulosObjetivo = {
      descoberta_cultura: 'Descoberta e cultura', produto_uso_educacao: 'Produto, uso e educação',
      desejo_conversao_comunidade: 'Desejo e conversão',
    };
    const rotulosFormato = { reels: 'Reels', carrossel: 'Carrossel', stories: 'Stories' };
    for (const item of conteudos) {
      const detalhe = item.detalhe_conteudo || {};
      const card = el('div', undefined, 'md-conteudo-card');
      card.append(el('span', rotulosSlot[detalhe.slot] || detalhe.slot || '—', 'md-conteudo-slot'));
      card.append(el('strong', detalhe.tema || item.motivo || '—', 'md-conteudo-tema'));
      const meta = [rotulosFormato[detalhe.formato] || detalhe.formato, rotulosObjetivo[detalhe.objetivo] || detalhe.objetivo]
        .filter(Boolean).join(' · ');
      card.append(el('span', meta, 'md-conteudo-meta'));
      if (detalhe.cta) card.append(el('span', detalhe.cta, 'md-conteudo-cta'));
      grade.append(card);
    }
    container.append(grade);
  }

  function renderComercial(comercial) {
    const container = $('comercial');
    container.replaceChildren();
    for (const [label, valor] of [
      ['Prospectos encontrados', comercial.prospectos_encontrados],
      ['Qualificados', comercial.prospectos_qualificados],
      ['Follow-ups', (comercial.followups || []).length],
      ['Oportunidades', (comercial.oportunidades || []).length],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      container.append(stat);
    }
  }

  const ROTULOS_PRODUTO = { guarana: 'Guaraná', acai: 'Açaí', bacuri: 'Bacuri' };
  function renderSite(site) {
    const container = $('site');
    container.replaceChildren();
    site = site || {};
    for (const [label, valor] of [
      ['Visitas', site.visitas], ['Interesses', site.interesses],
      ['CTAs clicados', site.ctas], ['Conversões', site.conversoes],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      container.append(stat);
    }
    const destaque = $('site-destaque');
    const partes = [];
    if (site.produto_em_alta) partes.push('Produto em alta: ' + (ROTULOS_PRODUTO[site.produto_em_alta] || site.produto_em_alta) + '.');
    if (site.origem_em_alta) partes.push('Origem em alta: ' + site.origem_em_alta + '.');
    if (site.mudanca_relevante) partes.push('Mudança relevante detectada no interesse do site.');
    destaque.textContent = partes.join(' ') || 'Sem destaque de produto/origem ainda.';
  }

  const NOMES_EVENTO_CONSELHO = {
    mensagem_enviada: 'troca de mensagem', reuniao_registrada: 'reunião', conclave_registrado: 'conclave',
    relatorio_registrado: 'relatório',
  };
  function renderConselho(conselho) {
    const container = $('conselho');
    container.replaceChildren();
    conselho = conselho || {};
    const agentes = conselho.agentes || [];

    const stats = el('div', undefined, 'md-conselho-stats');
    for (const [label, valor] of [
      ['Agentes disponíveis', agentes.length],
      ['Trabalhando', conselho.trabalhando],
      ['Sem demanda', conselho.sem_demanda],
    ]) {
      const stat = el('div', undefined, 'mi-stat');
      stat.append(el('strong', fmt(valor)), el('span', label));
      stats.append(stat);
    }
    container.append(stats);

    const agora = el('div', undefined, 'md-conselho-bloco');
    agora.append(el('h4', 'Agora'));
    const emAtividade = agentes.filter(a => a.status === 'trabalhando');
    if (!emAtividade.length) {
      agora.append(vazio('Nenhum agente com demanda no momento.'));
    } else {
      const lista = el('ul', undefined, 'md-conselho-lista');
      for (const a of emAtividade) {
        const evento = a.ultima_atividade && (NOMES_EVENTO_CONSELHO[a.ultima_atividade.tipo_evento] || a.ultima_atividade.tipo_evento);
        lista.append(el('li', `${a.nome} (${a.area})` + (evento ? ` — ${evento}` : '')));
      }
      agora.append(lista);
    }
    container.append(agora);

    const reuniao = el('div', undefined, 'md-conselho-bloco');
    reuniao.append(el('h4', 'Reunião mais recente'));
    const ultima = conselho.reuniao_mais_recente;
    if (!ultima) {
      reuniao.append(vazio('Nenhuma reunião ou conclave registrado ainda.'));
    } else {
      const p = el('p');
      p.append(el('strong', ultima.tipo === 'conclave' ? 'Conclave' : 'Reunião'));
      if (ultima.demanda) p.append(document.createTextNode(' — ' + ultima.demanda));
      reuniao.append(p);
      if (ultima.conclusao) reuniao.append(el('p', 'Conclusão: ' + ultima.conclusao, 'md-conselho-conclusao'));
    }
    container.append(reuniao);

    const pendente = el('div', undefined, 'md-conselho-bloco');
    pendente.append(el('h4', 'Precisa de você'));
    const totalPendente = (conselho.conflitos || []).length + (conselho.vetos || []).length + (conselho.aguardando_diretor || []).length;
    if (!totalPendente) {
      pendente.append(el('p', 'Nada. Conselho sem pendências.', 'md-precisa-nada'));
    } else {
      pendente.append(el('p', totalPendente + (totalPendente === 1 ? ' item pendente do Conselho' : ' itens pendentes do Conselho')));
    }
    container.append(pendente);
  }

  function renderCalendario(calendario) {
    const container = $('calendario');
    container.replaceChildren();
    calendario = calendario || {};
    const faixa = el('div', undefined, 'md-calendario-strip');
    for (const [label, valor] of [
      ['Hoje', calendario.hoje], ['Próximas', calendario.proximas],
      ['Concluídas', calendario.concluidas], ['Bloqueadas', calendario.bloqueadas],
    ]) {
      const bloco = el('div');
      bloco.append(el('strong', fmt(valor)), el('span', label));
      faixa.append(bloco);
    }
    container.append(faixa);
  }

  function renderIndisponivel(mensagem) {
    $('conteudo-geral').hidden = true;
    $('indisponivel').hidden = false;
    $('indisponivel').textContent = mensagem;
  }

  function controles(valor) {
    busy = valor;
    $('atualizar').disabled = valor;
  }

  async function carregarTudo() {
    if (busy) return;
    if (!window.adminKeyAtual) {
      $('status-texto').textContent = 'Entre no Admin para consultar o Modo Diretor.';
      return;
    }
    controles(true);
    $('status-texto').textContent = 'Consultando o estado atual…';
    try {
      const resposta = await chamar('/api/admin/mi/diretor');
      if (!resposta.ok) {
        renderIndisponivel(
          'Maranhão Intelligence ainda não está disponível neste ambiente — ' +
          'as tabelas de sinais e fila (migrations 013–015) ainda não foram aplicadas.'
        );
        $('status-texto').textContent = '';
        return;
      }
      const leitura = resposta.body.leitura || {};
      renderStatus(leitura);
      renderHoje(leitura.hoje || {});
      renderProximaAcao(leitura.proxima_acao_ia);
      renderPrecisaDeVoce(leitura.chamar_diretor);
      renderTop10((leitura.publico || {}).top10);
      renderConteudoHoje((leitura.publico || {}).conteudos_sugeridos_hoje);
      renderComercial(leitura.comercial || {});
      renderSite(leitura.site);
      renderConselho(leitura.conselho);
      renderCalendario(leitura.calendario);
      $('conteudo-geral').hidden = false;
      $('indisponivel').hidden = true;
      $('status-texto').textContent = 'Leitura atualizada. Nenhuma ação foi executada.';
      carregado = true;
    } catch (erro) {
      $('status-texto').textContent = 'Não foi possível consultar o Modo Diretor agora.';
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
