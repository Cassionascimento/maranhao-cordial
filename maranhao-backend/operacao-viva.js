/* Operação Viva — workspace da Central Empresarial sobre /api/admin/mi/operacoes.
   Reaproveita window.adminKeyAtual (mesma autenticação de toda a Central).
   Cada aba carrega sob demanda e sempre mostra um dos estados exigidos pela
   ordem de UX: CARREGANDO / SUCESSO / VAZIO / BLOQUEADO / ERRO. */
(() => {
'use strict';
const BASE = 'https://maranhao-cordial-api.onrender.com';
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const centavos = v => 'R$ ' + ((Number(v) || 0) / 100).toLocaleString('pt-BR', {minimumFractionDigits: 2});
const dataBr = v => { if (!v) return 'AGUARDANDO DADOS'; const d = new Date(v + 'T00:00:00'); return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString('pt-BR'); };
const AGENTES = ['pirret','standard','zilda','leonard','marie','rua','dicio','iris'];

function api(caminho, opcoes) {
  if (!window.adminKeyAtual) return Promise.reject(new Error('Entre na Central com a chave administrativa.'));
  return fetch(BASE + caminho, {
    cache: 'no-store', ...opcoes,
    headers: {'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json', ...(opcoes && opcoes.headers)},
  }).then(async r => {
    const corpo = await r.json().catch(() => null);
    if (!r.ok || !corpo || corpo.success === false) {
      throw new Error((corpo && (corpo.error || corpo.motivo)) || `Falha na operação (HTTP ${r.status}).`);
    }
    return corpo;
  });
}

const TABS = [
  {id: 'visao-geral', label: 'Visão Geral'}, {id: 'equipe', label: 'Equipe'},
  {id: 'plano', label: 'Plano'}, {id: 'brainstorm', label: 'Brainstorm'},
  {id: 'visual', label: 'Visual'}, {id: 'indicadores', label: 'Indicadores'},
  {id: 'financeiro', label: 'Financeiro'}, {id: 'arquivos', label: 'Arquivos'},
  {id: 'historico', label: 'Histórico'},
];

let estado = {operacaoId: null, abaAtiva: 'visao-geral', carregado: {}};

function montarModal() {
  if (document.getElementById('ov-modal')) return;
  const modal = document.createElement('div');
  modal.id = 'ov-modal';
  modal.className = 'ov-modal';
  modal.innerHTML = `<div class="ov-caixa" role="dialog" aria-modal="true">
    <header class="ov-cabecalho">
      <div><p class="app-shell-eyebrow">OPERAÇÃO VIVA</p><h2 id="ov-titulo">Carregando…</h2></div>
      <button type="button" id="ov-fechar" aria-label="Fechar">×</button>
    </header>
    <nav id="ov-abas" class="ov-abas"></nav>
    <div id="ov-corpo" class="ov-corpo"><p class="ov-estado">Carregando…</p></div>
  </div>`;
  document.body.append(modal);
  modal.querySelector('#ov-fechar').addEventListener('click', fecharOperacaoViva);
  modal.addEventListener('click', e => { if (e.target === modal) fecharOperacaoViva(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.classList.contains('show')) fecharOperacaoViva(); });
  for (const tab of TABS) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'ov-aba'; btn.dataset.aba = tab.id; btn.textContent = tab.label;
    btn.addEventListener('click', () => selecionarAba(tab.id));
    modal.querySelector('#ov-abas').append(btn);
  }
}

function fecharOperacaoViva() {
  document.getElementById('ov-modal')?.classList.remove('show');
  estado = {operacaoId: null, abaAtiva: 'visao-geral', carregado: {}};
}

async function abrirOperacaoViva(operacaoId) {
  montarModal();
  estado = {operacaoId, abaAtiva: 'visao-geral', carregado: {}};
  document.getElementById('ov-modal').classList.add('show');
  document.getElementById('ov-titulo').textContent = 'Carregando…';
  selecionarAba('visao-geral');
}

function selecionarAba(abaId) {
  estado.abaAtiva = abaId;
  document.querySelectorAll('.ov-aba').forEach(b => b.classList.toggle('active', b.dataset.aba === abaId));
  renderizarAba(abaId, {forcar: false});
}

function corpo() { return document.getElementById('ov-corpo'); }
function carregando() { corpo().innerHTML = '<p class="ov-estado ov-carregando">Carregando…</p>'; }
function vazio(msg) { corpo().innerHTML = `<p class="ov-estado ov-vazio">${esc(msg)}</p>`; }
function erro(msg) { corpo().innerHTML = `<p class="ov-estado ov-erro">${esc(msg)}</p>`; }

async function renderizarAba(abaId, {forcar}) {
  if (!forcar && estado.carregado[abaId]) { corpo().innerHTML = estado.carregado[abaId]; return; }
  carregando();
  try {
    const html = await RENDERERS[abaId]();
    estado.carregado[abaId] = html;
    corpo().innerHTML = html;
  } catch (e) {
    erro(e.message || 'Não foi possível carregar esta seção.');
  }
}

function invalidar(abaId) { delete estado.carregado[abaId]; if (estado.abaAtiva === abaId) renderizarAba(abaId, {forcar: true}); }

const RENDERERS = {
  'visao-geral': async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}`);
    const o = r.operacao, c = r.contagens;
    document.getElementById('ov-titulo').textContent = o.titulo;
    return `<div class="ov-visao-geral">
      <p><b>Período:</b> ${dataBr(o.data_inicio)} a ${dataBr(o.data_fim)}</p>
      <p><b>Local:</b> ${esc(o.local || 'AGUARDANDO DADOS')}</p>
      <p><b>Estado:</b> ${esc(o.estado)} &middot; <b>Prioridade:</b> ${esc(o.prioridade)}</p>
      <p><b>Responsável:</b> ${esc(o.responsavel || 'AGUARDANDO DADOS')}</p>
      <p>${esc(o.descricao || 'Sem descrição.')}</p>
      <div class="ov-resumo-grid">
        <div><strong>${c.pessoas}</strong><span>Equipe</span></div>
        <div><strong>${c.itens}</strong><span>Itens do plano</span></div>
        <div><strong>${c.brainstorm}</strong><span>Brainstorms</span></div>
        <div><strong>${c.metricas}</strong><span>Indicadores</span></div>
        <div><strong>${c.financeiro}</strong><span>Lançamentos</span></div>
        <div><strong>${c.arquivos}</strong><span>Arquivos</span></div>
      </div></div>`;
  },
  equipe: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/pessoas`);
    const lista = r.pessoas.length ? r.pessoas.map(p => `<article class="ov-item">
        <div class="ov-item-topo"><b>${esc(p.funcao)}</b><span class="ov-badge ov-badge-${esc(p.estado)}">${esc(p.estado)}</span></div>
        <p>${esc(p.nome || 'AGUARDANDO DADOS')} ${p.origem === 'agente' ? '· sugerido pela IA' : ''}</p>
        <div class="ov-acoes">
          ${['sugerido','convidado','confirmado','cancelado'].map(s => `<button type="button" data-acao="pessoa-estado" data-id="${p.id}" data-estado="${s}" ${s === p.estado ? 'disabled' : ''}>${s}</button>`).join('')}
        </div></article>`).join('') : '<p class="ov-vazio">Nenhuma pessoa na equipe ainda.</p>';
    return `<form id="ov-form-pessoa" class="ov-form">
      <input name="funcao" placeholder="Função (ex.: Bartender)" required>
      <input name="nome" placeholder="Nome (opcional)">
      <select name="origem"><option value="humano">Sugestão humana</option><option value="agente">Sugestão da IA</option></select>
      <button type="submit">Adicionar</button></form><div id="ov-status-equipe" class="ov-status"></div>${lista}`;
  },
  plano: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/itens`);
    const lista = r.itens.length ? r.itens.map(i => `<article class="ov-item">
        <div class="ov-item-topo"><b>${esc(i.titulo)}</b><span class="ov-badge ov-badge-${esc(i.status)}">${esc(i.status)}</span></div>
        <p>${esc(i.descricao || '')} ${i.data_prevista ? '· ' + dataBr(i.data_prevista) : ''} ${i.responsavel ? '· ' + esc(i.responsavel) : ''}</p>
        <div class="ov-acoes">
          ${['pendente','em_andamento','concluido','bloqueado','cancelado'].map(s => `<button type="button" data-acao="item-status" data-id="${i.id}" data-estado="${s}" ${s === i.status ? 'disabled' : ''}>${s}</button>`).join('')}
        </div></article>`).join('') : '<p class="ov-vazio">Nenhum item no plano operacional ainda.</p>';
    return `<form id="ov-form-item" class="ov-form">
      <input name="titulo" placeholder="Título da tarefa/marco" required>
      <input name="data_prevista" type="date">
      <input name="responsavel" placeholder="Responsável (opcional)">
      <button type="submit">Adicionar</button></form><div id="ov-status-plano" class="ov-status"></div>${lista}`;
  },
  brainstorm: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/brainstorm`);
    const lista = r.brainstorm.length ? r.brainstorm.map(b => {
      const resp = b.resposta;
      const bloco = resp ? `<div class="ov-resposta">
          <p><b>Ideias:</b> ${esc((resp.ideias || []).join('; ') || 'AGUARDANDO DADOS')}</p>
          <p><b>Riscos:</b> ${esc((resp.riscos || []).join('; ') || 'AGUARDANDO DADOS')}</p>
          <p><b>Recomendação:</b> ${esc(resp.recomendacao || 'AGUARDANDO DADOS')}</p>
          ${b.status === 'respondido' ? `<div class="ov-acoes">
            <button type="button" data-acao="brainstorm-decisao" data-id="${b.id}" data-decisao="aceitar_como_proposta">Aceitar como proposta</button>
            <button type="button" data-acao="brainstorm-decisao" data-id="${b.id}" data-decisao="transformar_em_tarefa">Transformar em tarefa</button>
            <button type="button" data-acao="brainstorm-decisao" data-id="${b.id}" data-decisao="pedir_nova_rodada">Pedir nova rodada</button>
            <button type="button" data-acao="brainstorm-decisao" data-id="${b.id}" data-decisao="descartar">Descartar</button>
          </div>` : ''}
        </div>` : `<div class="ov-acoes">
          ${AGENTES.map(a => `<label class="ov-check"><input type="checkbox" value="${a}"> ${a}</label>`).join('')}
          <button type="button" data-acao="brainstorm-executar" data-id="${b.id}">Perguntar ao Conselho</button>
        </div>`;
      return `<article class="ov-item"><div class="ov-item-topo"><b>${esc(b.pergunta)}</b><span class="ov-badge ov-badge-${esc(b.status)}">${esc(b.status)}</span></div>${bloco}</article>`;
    }).join('') : '<p class="ov-vazio">Nenhuma pergunta enviada ao Conselho ainda.</p>';
    return `<form id="ov-form-brainstorm" class="ov-form">
      <textarea name="pergunta" placeholder="Pergunta para o Conselho sobre esta operação" required></textarea>
      <button type="submit">Registrar pergunta</button></form><div id="ov-status-brainstorm" class="ov-status"></div>${lista}`;
  },
  visual: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/arquivos`);
    const visuais = r.arquivos.filter(a => a.categoria === 'visual');
    const lista = visuais.length ? visuais.map(a => `<article class="ov-item">
        <div class="ov-item-topo"><b>${esc(a.artifact_type)}</b><span class="ov-badge ov-badge-${esc(a.artefato_status)}">${esc(a.artefato_status)}</span></div>
        <p>Versão ${esc(a.version)} · ${esc(a.mime_type)}</p></article>`).join('') : '<p class="ov-vazio">Nenhum visual vinculado ainda. Gere no Pirret/Label Studio/Social Studio e vincule pelo ID do artefato.</p>';
    return `<form id="ov-form-visual" class="ov-form">
      <input name="artefato_id" placeholder="ID do artefato já gerado (Pirret/Label/Social Studio)" required>
      <button type="submit">Vincular como visual</button></form><div id="ov-status-visual" class="ov-status"></div>${lista}`;
  },
  indicadores: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/metricas`);
    const lista = r.metricas.length ? r.metricas.map(m => `<article class="ov-item">
        <div class="ov-item-topo"><b>${esc(m.nome)}</b><span class="ov-badge ov-badge-${esc(m.estado_dado)}">${esc(m.estado_dado)}</span></div>
        <p>${m.valor !== null ? esc(m.valor) + ' ' + esc(m.unidade || '') : 'AGUARDANDO DADOS'} ${m.periodo ? '· ' + esc(m.periodo) : ''}</p>
        <p>${esc(m.explicacao || '')}</p></article>`).join('') : '<p class="ov-vazio">Nenhum indicador definido ainda.</p>';
    return `<form id="ov-form-metrica" class="ov-form">
      <input name="nome" placeholder="Nome do indicador (ex.: CAC)" required>
      <input name="valor" type="number" step="0.01" placeholder="Valor (deixe vazio = aguardando dados)">
      <input name="unidade" placeholder="Unidade">
      <input name="fonte" placeholder="Fonte do dado">
      <button type="submit">Salvar indicador</button></form><div id="ov-status-indicadores" class="ov-status"></div>${lista}`;
  },
  financeiro: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/financeiro`);
    const totais = r.totais_centavos;
    const resumo = `<div class="ov-resumo-grid">${Object.entries(totais).map(([k, v]) => `<div><strong>${centavos(v)}</strong><span>${esc(k)}</span></div>`).join('')}</div>`;
    const lista = r.lancamentos.length ? r.lancamentos.map(l => `<article class="ov-item">
        <div class="ov-item-topo"><b>${esc(l.categoria)}</b><span class="ov-badge ov-badge-${esc(l.estado_dado)}">${esc(l.tipo)}</span></div>
        <p>${centavos(l.valor_centavos)} · ${esc(l.estado_dado)} ${l.fonte ? '· fonte: ' + esc(l.fonte) : ''}</p></article>`).join('') : '<p class="ov-vazio">Nenhum lançamento financeiro ainda.</p>';
    return `${resumo}<form id="ov-form-financeiro" class="ov-form">
      <input name="categoria" placeholder="Categoria (ex.: staff)" required>
      <select name="tipo"><option value="orcamento">Orçamento</option><option value="realizado">Realizado</option><option value="comprometido">Comprometido</option><option value="receita_atribuida">Receita atribuída</option><option value="taxa">Taxa</option><option value="tributo">Tributo</option></select>
      <input name="valor_reais" type="number" step="0.01" placeholder="Valor em R$" required>
      <input name="fonte" placeholder="Fonte (obrigatória se confirmado)">
      <button type="submit">Lançar</button></form><div id="ov-status-financeiro" class="ov-status"></div>${lista}`;
  },
  arquivos: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/arquivos`);
    const docs = r.arquivos.filter(a => a.categoria !== 'visual');
    return docs.length ? docs.map(a => `<article class="ov-item"><div class="ov-item-topo"><b>${esc(a.categoria)}</b><span class="ov-badge">${esc(a.artefato_status)}</span></div><p>${esc(a.mime_type)} · versão ${esc(a.version)}</p></article>`).join('') : '<p class="ov-vazio">Nenhum documento vinculado ainda.</p>';
  },
  historico: async () => {
    const r = await api(`/api/admin/mi/operacoes/${estado.operacaoId}/historico`);
    return r.auditoria.length ? `<table class="ov-tabela"><thead><tr><th>Quando</th><th>Entidade</th><th>Ação</th><th>Campo</th><th>De</th><th>Para</th><th>Autor</th></tr></thead><tbody>${
      r.auditoria.map(a => `<tr><td>${esc(a.criado_em)}</td><td>${esc(a.entidade)}</td><td>${esc(a.acao)}</td><td>${esc(a.campo || '')}</td><td>${esc(a.valor_anterior || '')}</td><td>${esc(a.valor_novo || '')}</td><td>${esc(a.ator_nome)}</td></tr>`).join('')
    }</tbody></table>` : '<p class="ov-vazio">Nenhuma alteração registrada ainda.</p>';
  },
};

document.addEventListener('submit', async e => {
  const form = e.target;
  if (form.id === 'ov-form-pessoa') {
    e.preventDefault();
    const d = new FormData(form);
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/pessoas`, {method: 'POST', body: JSON.stringify({funcao: d.get('funcao'), nome: d.get('nome'), origem: d.get('origem')})}); form.reset(); invalidar('equipe'); }
    catch (err) { document.getElementById('ov-status-equipe').textContent = err.message; }
  } else if (form.id === 'ov-form-item') {
    e.preventDefault();
    const d = new FormData(form);
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/itens`, {method: 'POST', body: JSON.stringify({titulo: d.get('titulo'), data_prevista: d.get('data_prevista') || null, responsavel: d.get('responsavel')})}); form.reset(); invalidar('plano'); }
    catch (err) { document.getElementById('ov-status-plano').textContent = err.message; }
  } else if (form.id === 'ov-form-brainstorm') {
    e.preventDefault();
    const d = new FormData(form);
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/brainstorm`, {method: 'POST', body: JSON.stringify({pergunta: d.get('pergunta')})}); form.reset(); invalidar('brainstorm'); }
    catch (err) { document.getElementById('ov-status-brainstorm').textContent = err.message; }
  } else if (form.id === 'ov-form-visual') {
    e.preventDefault();
    const d = new FormData(form);
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/arquivos`, {method: 'POST', body: JSON.stringify({artefato_id: d.get('artefato_id'), categoria: 'visual'})}); form.reset(); invalidar('visual'); }
    catch (err) { document.getElementById('ov-status-visual').textContent = err.message; }
  } else if (form.id === 'ov-form-metrica') {
    e.preventDefault();
    const d = new FormData(form);
    const valor = d.get('valor');
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/metricas`, {method: 'POST', body: JSON.stringify({nome: d.get('nome'), valor: valor ? Number(valor) : null, unidade: d.get('unidade'), fonte: d.get('fonte'), estado_dado: valor && d.get('fonte') ? 'confirmado' : 'aguardando_dados'})}); form.reset(); invalidar('indicadores'); }
    catch (err) { document.getElementById('ov-status-indicadores').textContent = err.message; }
  } else if (form.id === 'ov-form-financeiro') {
    e.preventDefault();
    const d = new FormData(form);
    const fonte = d.get('fonte');
    try { await api(`/api/admin/mi/operacoes/${estado.operacaoId}/financeiro`, {method: 'POST', body: JSON.stringify({categoria: d.get('categoria'), tipo: d.get('tipo'), valor_centavos: Math.round(Number(d.get('valor_reais')) * 100), fonte, estado_dado: fonte ? 'confirmado' : 'estimativa'})}); form.reset(); invalidar('financeiro'); }
    catch (err) { document.getElementById('ov-status-financeiro').textContent = err.message; }
  }
});

document.addEventListener('click', async e => {
  const btn = e.target?.closest?.('[data-acao]');
  if (!btn) return;
  const acao = btn.dataset.acao;
  try {
    if (acao === 'pessoa-estado') { await api(`/api/admin/mi/operacoes/pessoas/${btn.dataset.id}/estado`, {method: 'PATCH', body: JSON.stringify({estado: btn.dataset.estado})}); invalidar('equipe'); }
    else if (acao === 'item-status') { await api(`/api/admin/mi/operacoes/itens/${btn.dataset.id}`, {method: 'PATCH', body: JSON.stringify({campos: {status: btn.dataset.estado}})}); invalidar('plano'); }
    else if (acao === 'brainstorm-executar') {
      const artigo = btn.closest('.ov-acoes');
      const agentes = [...artigo.querySelectorAll('input[type=checkbox]:checked')].map(i => i.value);
      if (!agentes.length) { erro('Selecione ao menos um agente do Conselho.'); return; }
      await api(`/api/admin/mi/operacoes/brainstorm/${btn.dataset.id}/executar`, {method: 'POST', body: JSON.stringify({agentes})});
      invalidar('brainstorm');
    } else if (acao === 'brainstorm-decisao') { await api(`/api/admin/mi/operacoes/brainstorm/${btn.dataset.id}/decisao`, {method: 'POST', body: JSON.stringify({decisao: btn.dataset.decisao})}); invalidar('brainstorm'); }
  } catch (err) { erro(err.message); }
});

window.abrirOperacaoViva = abrirOperacaoViva;
window.fecharOperacaoViva = fecharOperacaoViva;
})();
