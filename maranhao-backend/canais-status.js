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
  let retorno = null;

  /* Desfechos que o callback devolve em ?oauth=. Tradução fica aqui, não no
     servidor: a rota só carrega o código curto, sem texto para o usuário. */
  const RETORNO_TEXTO = {
    ok: 'Autorização concluída. O diagnóstico abaixo foi refeito agora.',
    cancelado: 'Autorização cancelada na plataforma. Nada mudou aqui.',
    estado_invalido: 'O pedido de autorização expirou ou não confere com este navegador. Use Conectar de novo.',
    repetido: 'Esta autorização já tinha sido concluída. Nada foi refeito.',
    erro: 'A plataforma recusou a autorização.',
    indisponivel: 'Não foi possível concluir a autorização agora. Tente novamente.',
  };

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

  /* Mapa de capacidades REAIS por canal. A versão anterior listava só
     LinkedIn/Pinterest/X e desabilitava todo o resto -- inclusive canais
     que já tinham rota OAuth funcional (TikTok Social em /api/tiktok/login,
     Gmail em /api/gmail/conectar). Era essa a causa dos botões cinzentos.

     `modo` diz como abrir: 'url' = o backend devolve {url} em JSON;
     'redirect' = a própria rota redireciona o navegador. */
  const CANAIS_OAUTH = {
    Instagram: {
      conectar: { caminho: '/api/admin/instagram/connect', modo: 'url' },
      desconectar: '/api/admin/instagram/desconectar',
      reautoriza: true,
    },
    'TikTok Social': {
      conectar: { caminho: '/api/tiktok/login', modo: 'redirect' },
      reautoriza: true,
    },
    Gmail: {
      conectar: { caminho: '/api/gmail/conectar', modo: 'redirect' },
      reautoriza: true,
    },
    LinkedIn: {
      conectar: { caminho: '/api/admin/linkedin/connect', modo: 'url' },
      testar: '/api/admin/linkedin/testar',
      reconectar: '/api/admin/linkedin/reconectar',
      desconectar: '/api/admin/linkedin/desconectar',
    },
    Pinterest: {
      conectar: { caminho: '/api/admin/pinterest/connect', modo: 'url' },
      testar: '/api/admin/pinterest/testar',
      reconectar: '/api/admin/pinterest/reconectar',
      desconectar: '/api/admin/pinterest/desconectar',
    },
    X: {
      conectar: { caminho: '/api/admin/x/connect', modo: 'url' },
      testar: '/api/admin/x/testar',
      reconectar: '/api/admin/x/reconectar',
      desconectar: '/api/admin/x/desconectar',
    },
    /* Sem app aprovado no Partner Center não existe rota para abrir. O
       botão continua acionável e explica o que falta, em vez de ficar
       cinzento sem dizer nada. */
    'TikTok Shop': {
      instrucao: 'Criar o app em partner.tiktokshop.com (Partner Center) e autorizar a loja '
        + 'no Seller Center. Exige conta de parceiro aprovada — é uma validação empresarial, '
        + 'não uma configuração do sistema.',
    },
    WhatsApp: {
      instrucao: 'O WhatsApp é autorizado no Meta Business (WABA, número e assinatura do '
        + 'webhook). Leitura e webhook já estão ativos; não há reconexão a fazer por aqui.',
    },
  };

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
    if (retorno && retorno.canal === canal.canal) {
      mensagem.textContent = (RETORNO_TEXTO[retorno.desfecho] || RETORNO_TEXTO.erro)
        + (retorno.motivo ? ' (' + retorno.motivo + ')' : '');
      mensagem.className = 'canais-card-mensagem canais-card-mensagem--'
        + (retorno.desfecho === 'ok' ? 'ok' : retorno.desfecho === 'cancelado' ? 'neutro' : 'falha');
      box.dataset.retorno = retorno.desfecho;
    }

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

    const oauth = CANAIS_OAUTH[canal.canal] || {};
    const semRota = 'Este canal não tem fluxo de autorização próprio no sistema. '
      + 'Use Diagnosticar para ver o estado real.';

    async function abrirAutorizacao(rotulo) {
      mensagem.textContent = 'Abrindo a autorização…';
      if (oauth.instrucao) {
        mensagem.textContent = oauth.instrucao;
        return;
      }
      const destino = oauth.conectar;
      if (destino.modo === 'redirect') {
        // A própria rota redireciona; abrir em nova aba preserva o ADM.
        window.open(base + destino.caminho, '_blank', 'noopener');
        mensagem.textContent = rotulo + ': autorização aberta em nova aba. '
          + 'Ao concluir, volte aqui e use Diagnosticar.';
        return;
      }
      const corpo = await chamar(destino.caminho);
      if (!corpo.url) throw new Error('O servidor não devolveu a URL de autorização.');
      window.open(corpo.url, '_blank', 'noopener');
      mensagem.textContent = rotulo + ': autorização aberta em nova aba. '
        + 'Ao concluir, você volta para este cartão automaticamente.';
    }

    const podeAutorizar = !!(oauth.conectar || oauth.instrucao);
    acoes.append(
      botao('Conectar', () => abrirAutorizacao('Conectar'), podeAutorizar ? null : semRota),
      botao('Testar', async () => {
        mensagem.textContent = 'Testando…';
        const r = await chamar(oauth.testar);
        mensagem.textContent = r.conexao === 'ok' ? 'Conexão OK.' : 'Teste concluído.';
      }, oauth.testar ? null : 'Este canal não expõe teste isolado. Use Diagnosticar.'),
      botao('Reconectar', async () => {
        if (oauth.reconectar) {
          await chamar(oauth.reconectar, { method: 'POST' });
          mensagem.textContent = 'Reconectado localmente.';
          carregar();
          return;
        }
        // Sem rota local de reconexão, reconectar É refazer o OAuth --
        // é o que resolve token expirado, revogado ou permissão removida.
        await abrirAutorizacao('Reconectar');
      }, (oauth.reconectar || oauth.reautoriza) ? null
         : (oauth.instrucao || 'Este canal não tem reconexão própria no sistema.')),
      botao('Desconectar', async () => {
        const r = await chamar(oauth.desconectar, { method: 'POST' });
        mensagem.textContent = r.aviso || 'Desconectado.';
        carregar();
      }, oauth.desconectar ? null : 'Este canal não guarda credencial no sistema; '
         + 'a desconexão é feita no portal da plataforma.'),
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

  /* Volta do callback: o servidor redireciona para /admin.html?canal=..&oauth=..
     Aqui a tela abre Canais, mostra o desfecho no cartão certo e refaz o
     diagnóstico daquele canal -- é o que prova se a autorização pegou. */
  function lerRetornoDeAutorizacao() {
    try {
      const busca = (window.location && window.location.search) || '';
      if (!busca) return null;
      const params = new URLSearchParams(busca);
      const canal = params.get('canal');
      const desfecho = params.get('oauth');
      if (!canal || !desfecho) return null;
      // Limpa a URL para um recarregar não repetir o aviso.
      if (window.history && window.history.replaceState) {
        window.history.replaceState({}, '', (window.location.pathname || '/admin.html'));
      }
      return { canal, desfecho, motivo: params.get('motivo') };
    } catch (e) {
      return null;
    }
  }

  async function tratarRetorno() {
    retorno = lerRetornoDeAutorizacao();
    if (!retorno) return;
    if (typeof window.admIrPara === 'function') window.admIrPara('canais');
    await carregar();
    if (retorno.desfecho !== 'ok') return;
    // Só o diagnóstico autenticado decide se ficou conectado de verdade.
    try {
      const corpo = await chamar('/api/admin/canais/diagnostico?canal=' + encodeURIComponent(retorno.canal));
      const atualizado = Object.assign({}, corpo.canal, { historico: corpo.historico || [] });
      ultimos = ultimos.map(c => (c.canal === atualizado.canal ? atualizado : c));
      render(ultimos);
    } catch (e) {
      $('status').textContent = e.message;
    }
  }

  const load = carregar;
  $('atualizar').addEventListener('click', carregar);
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('admin-autorizado', tratarRetorno);
  }
  const tab = document.querySelector('[data-tab="canais"]');
  if (tab) tab.addEventListener('click', () => { if (window.adminKeyAtual) carregar(); });
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ESTADO_ROTULO, ESTADO_GRUPO, CANAIS_OAUTH, RETORNO_TEXTO, capacidade, simNao };
  }
})();
