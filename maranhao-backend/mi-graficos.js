/* Visualizações leves do Maranhão Intelligence -- só leitura, reaproveita
   os endpoints já existentes (/api/admin/mi/painel, /api/admin/mi/diretor,
   /api/admin/canais/status). Nenhum dado é inventado: sem números reais
   suficientes, cada gráfico mostra um estado vazio explícito. */
(() => {
  'use strict';
  const painel = document.getElementById('mi-painel');
  const raiz = document.getElementById('mig-raiz');
  if (!painel || !raiz) return;

  const NS = 'http://www.w3.org/2000/svg';
  const svgEl = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const vazio = (container, texto) => container.append(el('p', texto, 'mi-vazio'));

  function cartao(titulo) {
    const card = el('div', undefined, 'mig-card');
    card.append(el('h4', titulo));
    return card;
  }

  function barras(container, titulo, dados) {
    const card = cartao(titulo);
    container.append(card);
    const validos = (dados || []).filter(d => d.valor > 0).slice(0, 8);
    if (!validos.length) return vazio(card, 'Sem dados suficientes ainda.');
    const max = Math.max(...validos.map(d => d.valor));
    const largura = 100, alturaLinha = 22, altura = validos.length * alturaLinha;
    const svg = svgEl('svg', { viewBox: `0 0 ${largura} ${altura}`, role: 'img', 'aria-label': titulo });
    validos.forEach((d, i) => {
      const y = i * alturaLinha;
      const larguraBarra = Math.max(2, (d.valor / max) * (largura - 42));
      const truncado = d.rotulo.length > 16;
      // Rótulo truncado ainda podia colidir visualmente com o valor à direita
      // (SVG não faz auto-fit de texto) -- textLength força o desenho a caber
      // no espaço reservado, sem sobrepor o número.
      const atributosRotulo = { x: 0, y: y + 9, class: 'mig-bar-label' };
      if (truncado) { atributosRotulo.textLength = largura - 26; atributosRotulo.lengthAdjust = 'spacingAndGlyphs'; }
      const rotulo = svgEl('text', atributosRotulo);
      rotulo.textContent = truncado ? d.rotulo.slice(0, 15) + '…' : d.rotulo;
      svg.append(rotulo);
      svg.append(svgEl('rect', { x: 0, y: y + 12, width: larguraBarra, height: 6, rx: 2, fill: '#d4af37' }));
      const txt = svgEl('text', { x: largura, y: y + 9, class: 'mig-bar-valor', 'text-anchor': 'end' });
      txt.textContent = d.valor;
      svg.append(txt);
    });
    card.append(svg);
  }

  function donut(container, titulo, dados) {
    const card = cartao(titulo);
    container.append(card);
    const cores = ['#d4af37', '#8fbf8a', '#c98a8a', '#7aa6c9', '#b088c9'];
    const validos = (dados || []).filter(d => d.valor > 0);
    const total = validos.reduce((s, d) => s + d.valor, 0);
    if (!total) return vazio(card, 'Sem dados suficientes ainda.');
    const svg = svgEl('svg', { viewBox: '0 0 42 42', role: 'img', 'aria-label': titulo });
    const raio = 15.9155, circ = 2 * Math.PI * raio;
    let acumulado = 0;
    validos.forEach((d, i) => {
      const fracao = d.valor / total;
      const comprimento = fracao * circ;
      svg.append(svgEl('circle', {
        cx: 21, cy: 21, r: raio, fill: 'transparent', stroke: cores[i % cores.length],
        'stroke-width': 6, 'stroke-dasharray': `${comprimento} ${circ - comprimento}`,
        'stroke-dashoffset': -acumulado, transform: 'rotate(-90 21 21)',
      }));
      acumulado += comprimento;
    });
    card.append(svg);
    const legenda = el('div', undefined, 'mig-canais-lista');
    validos.forEach((d, i) => {
      const linha = el('span');
      const ponto = el('span', '● ');
      ponto.style.color = cores[i % cores.length];
      const texto = el('span', `${d.rotulo}: ${d.valor}`);
      linha.append(ponto, texto);
      legenda.append(linha);
    });
    card.append(legenda);
  }

  function linhaTemporal(container, titulo, pontos) {
    const card = cartao(titulo);
    container.append(card);
    const validos = pontos || [];
    if (validos.length < 2) return vazio(card, 'Sem histórico suficiente ainda.');
    const max = Math.max(1, ...validos.map(p => p.valor));
    const largura = 100, altura = 34;
    const passo = largura / (validos.length - 1);
    const coords = validos.map((p, i) => `${i * passo},${altura - (p.valor / max) * altura}`);
    const svg = svgEl('svg', { viewBox: `0 0 ${largura} ${altura}`, role: 'img', 'aria-label': titulo });
    svg.append(svgEl('polygon', { points: `0,${altura} ${coords.join(' ')} ${largura},${altura}`, class: 'mig-linha-area' }));
    svg.append(svgEl('polyline', { points: coords.join(' '), class: 'mig-linha' }));
    card.append(svg);
    const legenda = el('p', `${validos[0].rotulo} → ${validos[validos.length - 1].rotulo}`, 'mi-vazio');
    card.append(legenda);
  }

  function funil(container, titulo, etapas) {
    const card = cartao(titulo);
    container.append(card);
    const validos = (etapas || []).filter(e => e.valor >= 0);
    if (!validos.some(e => e.valor > 0)) return vazio(card, 'Sem dados suficientes ainda.');
    const max = Math.max(...validos.map(e => e.valor), 1);
    for (const etapa of validos) {
      const linha = el('div');
      linha.style.margin = '0 0 8px';
      const rotulo = el('div', `${etapa.rotulo}: ${etapa.valor}`, 'mig-bar-label');
      rotulo.style.marginBottom = '3px';
      const barraFundo = el('div');
      barraFundo.style.cssText = 'background:#1b261e;border:1px solid #344139;border-radius:4px;height:10px;overflow:hidden;';
      const barra = el('div');
      const pct = Math.max(4, Math.round((etapa.valor / max) * 100));
      barra.style.cssText = `background:#d4af37;height:100%;width:${pct}%;`;
      barraFundo.append(barra);
      linha.append(rotulo, barraFundo);
      card.append(linha);
    }
  }

  function listaCanais(container, canais) {
    const card = cartao('Status dos canais');
    container.append(card);
    if (!canais || !canais.length) return vazio(card, 'Sem canais configurados ainda.');
    const lista = el('div', undefined, 'mig-canais-lista');
    for (const c of canais) {
      const linha = el('span', c.canal + ' ');
      const badge = el('span', c.estado, 'mig-badge mig-badge-' + c.estado);
      linha.append(badge);
      lista.append(linha);
    }
    card.append(lista);
  }

  async function buscar(url) {
    const response = await fetch(url, { cache: 'no-store', headers: { 'X-Admin-Key': window.adminKeyAtual || '' } });
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao consultar.');
    return body;
  }

  async function carregar() {
    raiz.replaceChildren();
    if (!window.adminKeyAtual) return;
    const grid = el('div', undefined, 'mig-grid');
    raiz.append(grid);
    // Cada fonte é buscada e tratada de forma independente -- a falha de
    // uma (ex.: mi/painel indisponível) não pode apagar os demais gráficos
    // já prontos para exibir; cada card mostra seu próprio estado vazio.
    const [painelBody, diretorBody, canaisBody] = await Promise.all([
      buscar('https://maranhao-cordial-api.onrender.com/api/admin/mi/painel').catch(() => null),
      buscar('https://maranhao-cordial-api.onrender.com/api/admin/mi/diretor').catch(() => null),
      buscar('https://maranhao-cordial-api.onrender.com/api/admin/canais/status').catch(() => null),
    ]);

    barras(grid, 'Eventos por SKU', (painelBody?.produto?.por_sku || []).map(p => ({ rotulo: p.produto_nome || p.sku, valor: p.total })));
    donut(grid, 'Unidades por estado', Object.entries(painelBody?.secundario?.unidades_por_estado || {}).map(([rotulo, valor]) => ({ rotulo, valor })));
    linhaTemporal(grid, 'Atividade recente (ordem cronológica)', (painelBody?.atividade_recente || []).slice().reverse().map((a, i) => ({ rotulo: (a.tipo_evento || '') + ' #' + (i + 1), valor: i + 1 })));

    // /api/admin/mi/diretor devolve {success, leitura:{comercial,conselho}} --
    // a leitura fica embrulhada em `leitura`, nunca solta na raiz do corpo.
    const leituraDiretor = diretorBody?.leitura;
    funil(grid, 'Funil comercial (30 dias)', leituraDiretor ? [
      { rotulo: 'Prospectos encontrados', valor: leituraDiretor.comercial?.prospectos_encontrados || 0 },
      { rotulo: 'Prospectos qualificados', valor: leituraDiretor.comercial?.prospectos_qualificados || 0 },
      { rotulo: 'Oportunidades', valor: (leituraDiretor.comercial?.oportunidades || []).length },
    ] : []);
    barras(grid, 'Conselho de Agentes', leituraDiretor ? [
      { rotulo: 'Trabalhando', valor: leituraDiretor.conselho?.trabalhando || 0 },
      { rotulo: 'Sem demanda', valor: leituraDiretor.conselho?.sem_demanda || 0 },
      { rotulo: 'Conflitos', valor: (leituraDiretor.conselho?.conflitos || []).length },
      { rotulo: 'Vetos', valor: (leituraDiretor.conselho?.vetos || []).length },
      { rotulo: 'Aguardando Diretor', valor: (leituraDiretor.conselho?.aguardando_diretor || []).length },
    ] : []);
    const contagemPorEstado = {};
    for (const c of (canaisBody?.canais || [])) contagemPorEstado[c.estado] = (contagemPorEstado[c.estado] || 0) + 1;
    donut(grid, 'Canais por status', [
      { rotulo: 'Conectado', valor: contagemPorEstado.conectado || 0 },
      { rotulo: 'Pendente', valor: contagemPorEstado.pendente || 0 },
      { rotulo: 'Bloqueado', valor: contagemPorEstado.bloqueado || 0 },
    ]);
    listaCanais(grid, canaisBody?.canais);
  }

  const btnMi = document.getElementById('mi-atualizar');
  if (btnMi) btnMi.addEventListener('click', carregar);
  window.addEventListener('admin-autorizado', () => { if (painel.classList.contains('active')) carregar(); });
  const tab = document.querySelector('[data-tab="maranhao-intelligence"]');
  if (tab) tab.addEventListener('click', () => { if (window.adminKeyAtual) carregar(); });
})();
