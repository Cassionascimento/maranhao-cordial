/* Canais -- painel omnichannel. Só leitura + as ações que têm rota real no
   backend (connect/testar/reconectar/desconectar dos conectores OAuth).

   O que mudou em relação à versão anterior: o painel deixou de descrever
   presença de variável de ambiente e passou a mostrar o diagnóstico remoto
   (/api/admin/canais/status?remoto=1 e /api/admin/canais/diagnostico).
   Regras que o desenho respeita:

   - nenhum botão decorativo: quando a operação não existe para o canal, o
     botão fica desabilitado com o motivo no title e em texto;
   - "nenhum próximo passo" só aparece quando o canal está realmente
     conectado e sem permissão faltando;
   - estado desconhecido é "—", nunca um otimismo;
   - a resposta antiga (sem os campos ricos) continua renderizando, para o
     painel não quebrar se o servidor ainda não tiver o diagnóstico. */
(() => {
  'use strict';
  const panel = document.getElementById('canais-painel');
  if (!panel) return;
  const base = 'https://maranhao-cordial-api.onrender.com';
  const $ = id => document.getElementById('canais-' + id);
  let busy = false;
  let ultimos = [];
  let filtro = 'todos';

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };

  /* Rótulo de cada estado. Um estado sem rótulo aqui aparece como veio --
     preferível a inventar uma tradução otimista. */
  const ESTADO_ROTULO = {
    conectado: 'Conectado',
    conectado_parcial: 'Conectado em parte',
    aguardando_autorizacao: 'Aguardando autorização',
    aguardando_aprovacao_externa: 'Aguardando aprovação da plataforma',
    token_expirado: 'Token expirado',
    bloqueado: 'Bloqueado',
    erro: 'Erro',
    nao_configurado: 'Não configurado',
    nao_priorizado: 'Não priorizado',
    pendente: 'Pendente',
  };
  const ESTADO_GRUPO = {
    conectado: 'ok', conectado_parcial: 'atencao', aguardando_autorizacao: 'atencao',
    aguardando_aprovacao_externa: 'atencao', token_expirado: 'falha', bloqueado: 'falha',
    erro: 'falha', nao_configurado: 'neutro', nao_priorizado: 'neutro', pendente: 'atencao',
  };

  const quando = (iso) => {
    if (!iso) return null;
    const data = new Date(iso);
    return Number.isNaN(data.getTime()) ? String(iso)
      : data.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  const simNao = v => (v === true ? 'Sim' : v === false ? 'Não' : '—');
  const capacidade = (disponivel, exigeAprovacao) => {
    if (disponivel !== true) return 'Não disponível';
    return exigeAprovacao ? 'Ativa (exige aprovação)' : 'Ativa';
  };

  /* Só canais com rotas OAuth registradas no backend ganham botões de
     conexão -- ver registrar_rotas_* nos conectores. */
  const ROTA_PREFIXO = { LinkedIn: 'linkedin', Pinterest: 'pinterest', X: 'x' };

  async function chamar(caminho, opcoes) {
    const resposta = await fetch(base + caminho, {
      cache: 'no-store',
      headers: { 'X-Admin-Key': window.adminKeyAtual || '' },
      ...opcoes,
    });
    const corpo = await resposta.json().catch(() => ({}));
    if (!resposta.ok || corpo.success === false) throw new Error(corpo.error || 'Falha na operação.');
    return corpo;
  }

  async function call() {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar os Canais.');
    const corpo = await chamar('/api/admin/canais/status?remoto=1');
    return corpo.canais || [];
  }

  function linha(rotulo, valor) {
    const item = el('div', undefined, 'canais-card-linha');
    item.append(el('span', rotulo, 'canais-card-rotulo'),
                el('span', valor == null || valor === '' ? '—' : String(valor), 'canais-card-valor'));
    return item;
  }

  function botao(rotulo, aoClicar, motivoDesabilitado) {
    const b = el('button', rotulo, 'btn');
    b.type = 'button';
    if (motivoDesabilitado) {
      b.disabled = true;
      b.title = motivoDesabilitado;
      b.setAttribute('aria-label', rotulo + ' — indisponível: ' + motivoDesabilitado);
      return b;
    }
    b.addEventListener('click', aoClicar);
    return b;
  }

  function selo(texto, classe) {
    return el('span', texto, 'canais-badge ' + classe);
  }

  function card(canal) {
    const estado = canal.estado || 'nao_configurado';
    const grupo = ESTADO_GRUPO[estado] || 'neutro';
    const box = el('article', undefined, 'canais-card canais-card-' + grupo);
    box.dataset.canal = canal.canal;
    box.dataset.estado = estado;

    const cabecalho = el('div', undefined, 'canais-card-cabecalho');
    cabecalho.append(el('h4', canal.canal),
                     selo(ESTADO_ROTULO[estado] || estado, 'canais-badge-' + grupo));
    box.append(cabecalho);

    const avisos = el('div', undefined, 'canais-card-avisos');
    if (canal.exige_acao_admin) avisos.append(selo('Exige ação do administrador', 'canais-badge-atencao'));
    if (canal.aguardando_plataforma) avisos.append(selo('Aguardando aprovação da plataforma', 'canais-badge-atencao'));
    if (canal.exige_reconexao) avisos.append(selo('Precisa reconectar', 'canais-badge-falha'));
    if (avisos.childElementCount) box.append(avisos);

    box.append(
      linha('Conta conectada', canal.conta),
      linha('Tipo de conta', canal.tipo_conta),
      linha('Leitura', capacidade(canal.leitura_disponivel, false)),
      linha('Escrita', capacidade(canal.escrita_disponivel, canal.aprovacao_exigida)),
      linha('Webhook', simNao(canal.webhook_ativo)),
      linha('Token expira em', quando(canal.token_expira_em)),
      linha('Última sincronização', quando(canal.ultima_sincronizacao) || 'Nunca sincronizado'),
      linha('Última verificação', quando(canal.ultima_tentativa)),
      linha('Último erro', canal.ultimo_erro || 'Nenhum'),
      linha('Código técnico', canal.codigo_erro),
    );

    if (Array.isArray(canal.permissoes_ausentes) && canal.permissoes_ausentes.length) {
      box.append(linha('Permissões que faltam', canal.permissoes_ausentes.join(', ')));
    } else if (Array.isArray(canal.permissoes_concedidas) && canal.permissoes_concedidas.length) {
      box.append(linha('Permissões concedidas', canal.permissoes_concedidas.join(', ')));
    }
    if (canal.motivo_nao_priorizado) box.append(linha('Por que não é prioridade', canal.motivo_nao_priorizado));

    /* Regra dura: só declara ausência de pendência quando não há nada
       faltando de fato. */
    const nadaPendente = estado === 'conectado'
      && !(canal.permissoes_ausentes || []).length
      && canal.exige_acao_admin !== true
      && canal.aguardando_plataforma !== true;
    box.append(el('p', canal.proximo_passo || (nadaPendente
      ? 'Nenhum próximo passo pendente.'
      : 'Próximo passo não determinado nesta leitura. Use Diagnosticar.'), 'canais-card-proximo'));

    const mensagem = el('p', '', 'canais-card-mensagem');
    const acoes = el('div', undefined, 'canais-card-acoes');

    acoes.append(botao('Diagnosticar', async () => {
      mensagem.textContent = 'Consultando a plataforma…';
      try {
        const corpo = await chamar('/api/admin/canais/diagnostico?canal=' + encodeURIComponent(canal.canal));
        // O histórico vem ao lado do canal na resposta; o cartão desenha os
        // dois juntos.
        const atualizado = Object.assign({}, corpo.canal, { historico: corpo.historico || [] });
        ultimos = ultimos.map(c => (c.canal === atualizado.canal ? atualizado : c));
        render(ultimos);
        mensagem.textContent = 'Verificado agora.';
      } catch (e) {
        mensagem.textContent = e.message;
      }
    }));

    const prefixo = ROTA_PREFIXO[canal.canal];
    const semRota = 'Este canal não tem fluxo OAuth próprio no sistema; a conexão é feita no portal da plataforma.';
    acoes.append(
      botao('Conectar', async () => {
        mensagem.textContent = 'Abrindo autorização…';
        const r = await chamar(`/api/admin/${prefixo}/connect`);
        if (r.url) window.open(r.url, '_blank', 'noopener');
        mensagem.textContent = 'Autorização aberta em nova aba.';
      }, prefixo ? null : semRota),
      botao('Testar', async () => {
        mensagem.textContent = 'Testando…';
        const r = await chamar(`/api/admin/${prefixo}/testar`);
        mensagem.textContent = r.conexao === 'ok' ? 'Conexão OK.' : 'Teste concluído.';
      }, prefixo ? null : semRota),
      botao('Reconectar', async () => {
        await chamar(`/api/admin/${prefixo}/reconectar`, { method: 'POST' });
        mensagem.textContent = 'Reconectado localmente.';
        carregar();
      }, prefixo ? null : semRota),
      botao('Desconectar', async () => {
        await chamar(`/api/admin/${prefixo}/desconectar`, { method: 'POST' });
        mensagem.textContent = 'Desconectado localmente.';
        carregar();
      }, prefixo ? null : semRota),
    );
    box.append(acoes, mensagem);

    if (Array.isArray(canal.historico) && canal.historico.length) {
      const detalhe = el('details');
      detalhe.append(el('summary', 'Histórico de mudanças e falhas'));
      for (const evento of canal.historico) {
        detalhe.append(el('p', `${quando(evento.verificado_em) || '—'} · ${ESTADO_ROTULO[evento.estado] || evento.estado}`
          + (evento.codigo_erro ? ` · ${evento.codigo_erro}` : '')));
      }
      box.append(detalhe);
    }
    return box;
  }

  function barraDeFiltros(canais) {
    const barra = el('div', undefined, 'canais-filtros');
    const contagem = canais.reduce((acc, c) => {
      const g = ESTADO_GRUPO[c.estado] || 'neutro';
      acc[g] = (acc[g] || 0) + 1;
      return acc;
    }, {});
    const opcoes = [['todos', 'Todos', canais.length], ['falha', 'Com falha', contagem.falha || 0],
                    ['atencao', 'Exigem atenção', contagem.atencao || 0], ['ok', 'Conectados', contagem.ok || 0],
                    ['neutro', 'Sem prioridade', contagem.neutro || 0]];
    for (const [chave, rotulo, total] of opcoes) {
      const b = el('button', `${rotulo} (${total})`, 'canais-filtro');
      b.type = 'button';
      b.dataset.filtro = chave;
      b.setAttribute('aria-pressed', String(filtro === chave));
      b.addEventListener('click', () => { filtro = chave; render(ultimos); });
      barra.append(b);
    }
    return barra;
  }

  function render(canais) {
    ultimos = canais;
    const container = $('conteudo');
    container.replaceChildren();
    container.append(barraDeFiltros(canais));
    const visiveis = canais.filter(c => filtro === 'todos' || (ESTADO_GRUPO[c.estado] || 'neutro') === filtro);
    const grid = el('div', undefined, 'canais-grid');
    if (!visiveis.length) {
      grid.append(el('p', 'Nenhum canal neste filtro.', 'canais-card-proximo'));
    }
    for (const canal of visiveis) grid.append(card(canal));
    container.append(grid);
    container.hidden = false;
  }

  async function carregar() {
    if (busy) return;
    busy = true;
    $('atualizar').disabled = true;
    $('status').textContent = 'Consultando cada plataforma…';
    try {
      const canais = await call();
      render(canais);
      const pendentes = canais.filter(c => c.exige_acao_admin || c.aguardando_plataforma).length;
      $('status').textContent = pendentes
        ? `Leitura atualizada. ${pendentes} canal(is) exigem uma ação. Nenhuma ação automática foi executada.`
        : 'Leitura atualizada. Nenhuma ação automática foi executada.';
    } catch (e) {
      $('status').textContent = e.message;
    } finally {
      busy = false;
      $('atualizar').disabled = false;
    }
  }

  const load = carregar;
  $('atualizar').addEventListener('click', carregar);
  const tab = document.querySelector('[data-tab="canais"]');
  if (tab) tab.addEventListener('click', () => { if (window.adminKeyAtual) carregar(); });
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ESTADO_ROTULO, ESTADO_GRUPO, capacidade, simNao };
  }
})();
