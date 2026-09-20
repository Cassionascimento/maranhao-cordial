/* Canais -- painel somente leitura + ações reais já existentes no backend
   (connect/testar/desconectar/reconectar). Só consome GET /api/admin/canais/status
   (canais_status.py) para leitura; nenhum dado inventado, nenhum botão sem
   rota correspondente no conector do canal. */
(() => {
  'use strict';
  const panel = document.getElementById('canais-painel');
  if (!panel) return;
  const base = 'https://maranhao-cordial-api.onrender.com';
  const api = base + '/api/admin/canais/status';
  const $ = id => document.getElementById('canais-' + id);
  let busy = false;

  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const ESTADO_ROTULO = { conectado: 'Conectado', pendente: 'Pendente', bloqueado: 'Bloqueado' };
  // Data legível em vez do carimbo técnico; valor inesperado volta cru, sem
  // inventar uma data.
  const quando = (iso) => {
    if (!iso) return 'Nunca sincronizado';
    const data = new Date(iso);
    return Number.isNaN(data.getTime())
      ? String(iso)
      : data.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  const LEITURA_ROTULO = (canal) => (canal.leitura_disponivel ? 'Ativa' : (canal.estado === 'bloqueado' ? 'Não disponível' : 'Pendente'));
  const ESCRITA_ROTULO = (canal) => (canal.escrita_disponivel ? (canal.aprovacao_exigida ? 'Ativa (exige aprovação)' : 'Ativa') : 'Não disponível');
  // Só canais com rotas reais de OAuth registradas (ver registrar_rotas_*
  // nos respectivos conectores) ganham botões -- nenhum botão sem backend.
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
    const response = await fetch(api, { cache: 'no-store', headers: { 'X-Admin-Key': window.adminKeyAtual } });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar os Canais.');
    return body.canais;
  }

  function linha(rotulo, valor) {
    const item = el('div', undefined, 'canais-card-linha');
    item.append(el('span', rotulo, 'canais-card-rotulo'), el('span', valor, 'canais-card-valor'));
    return item;
  }

  function cardAcao(rotulo, acao, mensagemEl) {
    const botao = el('button', rotulo, 'btn');
    botao.type = 'button';
    botao.addEventListener('click', async () => {
      botao.disabled = true;
      mensagemEl.textContent = 'Executando ' + rotulo.toLowerCase() + '…';
      try {
        const resultado = await acao();
        mensagemEl.textContent = resultado || 'Concluído.';
        load();
      } catch (e) {
        mensagemEl.textContent = e.message;
      } finally {
        botao.disabled = false;
      }
    });
    return botao;
  }

  function card(canal) {
    const box = el('article', undefined, 'canais-card canais-card-' + canal.estado);
    const cabecalho = el('div', undefined, 'canais-card-cabecalho');
    cabecalho.append(el('h4', canal.canal), el('span', ESTADO_ROTULO[canal.estado] || canal.estado, 'canais-badge canais-badge-' + canal.estado));
    box.append(cabecalho);

    box.append(
      linha('Leitura', LEITURA_ROTULO(canal)),
      linha('Escrita', ESCRITA_ROTULO(canal)),
      linha('Última sincronização', quando(canal.ultima_sincronizacao)),
      linha('Último erro', canal.ultimo_erro || 'Nenhum'),
    );
    box.append(el('p', canal.proximo_passo || 'Nenhum próximo passo pendente.', 'canais-card-proximo'));

    const prefixo = ROTA_PREFIXO[canal.canal];
    if (prefixo) {
      const mensagem = el('p', '', 'canais-card-mensagem');
      const acoes = el('div', undefined, 'canais-card-acoes');
      acoes.append(
        cardAcao('Conectar', async () => {
          const r = await chamar(`/api/admin/${prefixo}/connect`);
          if (r.url) window.open(r.url, '_blank', 'noopener');
          return 'Autorização aberta em nova aba.';
        }, mensagem),
        cardAcao('Testar', async () => {
          const r = await chamar(`/api/admin/${prefixo}/testar`);
          return r.conexao === 'ok' ? 'Conexão OK.' : 'Teste concluído.';
        }, mensagem),
        cardAcao('Reconectar', async () => {
          await chamar(`/api/admin/${prefixo}/reconectar`, { method: 'POST' });
          return 'Reconectado localmente.';
        }, mensagem),
        cardAcao('Desconectar', async () => {
          await chamar(`/api/admin/${prefixo}/desconectar`, { method: 'POST' });
          return 'Desconectado localmente.';
        }, mensagem),
      );
      box.append(acoes, mensagem);
    }
    return box;
  }

  function render(canais) {
    const container = $('conteudo');
    container.replaceChildren();
    const grid = el('div', undefined, 'canais-grid');
    for (const canal of canais) grid.append(card(canal));
    container.append(grid);
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
      $('status').textContent = 'Leitura atualizada. Nenhuma ação automática foi executada.';
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
