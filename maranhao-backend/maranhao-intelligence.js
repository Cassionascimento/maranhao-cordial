/* Maranhão Intelligence Command Center — leitura e decisão humana, sem execução autônoma. */
(() => {
  'use strict';
  const panel = document.getElementById('mi-painel');
  if (!panel) return;
  const BASE = 'https://maranhao-cordial-api.onrender.com';
  const $ = id => document.getElementById(id);
  let loaded = false;

  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => Number(v || 0).toLocaleString('pt-BR');
  const value = (obj, keys, fallback = 0) => { for (const k of keys) if (obj && obj[k] != null) return obj[k]; return fallback; };
  const arr = v => Array.isArray(v) ? v : [];
  const label = v => ({NOT_ENOUGH_DATA:'Dados insuficientes',UNKNOWN:'Desconhecido',REAL:'Real',DERIVED:'Derivado',INFERRED:'Inferido',SYNTHETIC_TEST:'Teste sintético'}[v] || v || '—');

  async function get(path) {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin para consultar a Maranhão Intelligence.');
    const r = await fetch(BASE + path, {cache:'no-store', headers:{'X-Admin-Key':window.adminKeyAtual,'Content-Type':'application/json'}});
    let b = {}; try { b = await r.json(); } catch (_) {}
    if (!r.ok || b.success === false) throw new Error(b.error || `Consulta indisponível (${r.status}).`);
    return b;
  }

  // P5X stays inside the existing Command Center. Every write is a user click.
  let creativeAnalysis = null;
  const artifactPath = id => '/api/admin/mi/artefatos/' + encodeURIComponent(id);
  async function write(path, body, form=false) {
    if (!window.adminKeyAtual) throw new Error('Entre no Admin.');
    const headers={'X-Admin-Key':window.adminKeyAtual};
    if(!form) headers['Content-Type']='application/json';
    const r=await fetch(BASE+path,{method:'POST',headers,body:form?body:JSON.stringify(body)});
    const b=await r.json();
    if(!r.ok || b.success===false) throw new Error(b.error||b.motivo||`Falha (${r.status})`);
    return b;
  }
  function creativeShell() {
    return `<section class="mic-card mic-card--wide"><span class="mic-kicker">EXECUTIVE & CREATIVE</span>
      <h3>Do Conselho à criação.</h3><p class="mic-note">Geração sob solicitação. Aprovação não publica. Providers podem ter custo; erros e ausência de dados permanecem explícitos.</p>
      <p id="mic-creative-status" role="status">Nenhuma geração solicitada · not_requested</p>
      <div class="mic-search"><input id="mic-creative-actor" placeholder="Responsável pela decisão" aria-label="Responsável pela decisão"><button data-creative-action="refresh">Atualizar acervo</button></div>
      <div class="mic-grid mic-grid--2"><section class="mic-sub"><h4>Conselho Executivo</h4>
        <textarea id="mic-creative-demand" aria-label="Demanda do Conselho" placeholder="Qual decisão precisa de evidência?"></textarea>
        <button data-creative-action="analyze">Solicitar parecer</button><button data-creative-action="record">Registrar para decisão humana</button>
        <div id="mic-creative-analysis"></div><div id="mic-creative-meetings"></div></section>
      <section class="mic-sub"><h4>Pirret · direção criativa</h4><p id="mic-creative-provider">Provider ainda não consultado.</p>
        <textarea id="mic-creative-brief" aria-label="Brief criativo" placeholder="Objetivo e direção criativa"></textarea>
        <input id="mic-creative-sku" placeholder="SKU para conceito de rótulo" aria-label="SKU">
        <button data-creative-action="label">Gerar rótulo</button><button data-creative-action="campaign">Gerar conceito de campanha</button>
        <details><summary>Brand Context e memória visual</summary><div id="mic-creative-brand"></div></details>
      </section></div>
      <button data-creative-action="chart">Gráfico dos segmentos registrados</button>
      <div id="mic-creative-artifacts" class="mic-grid mic-grid--3"></div><div id="mic-creative-detail"></div>
    </section>`;
  }
  async function loadCreative() {
    const reads=[['/api/admin/mi/artefatos','mic-creative-artifacts',b=>{
      $('mic-creative-artifacts').innerHTML=arr(b.artefatos).map(a=>`<article class="mic-sub"><span>${esc(a.artifact_type)}</span><h4>Versão ${esc(a.version)} · ${esc(a.status)}</h4><small>${esc(a.metadata?.production_status||a.metadata?.confidence||'Proveniência não informada')}</small>
      <div>${['open','download','detail','approve','reject',...(['image/png','image/jpeg','image/webp'].includes(a.mime_type)?['refine','social']:[])].map(action=>`<button data-creative-action="${action}" data-artifact="${esc(a.id)}">${({open:'Abrir',download:'Baixar',detail:'Versões / metadata',approve:'Aprovar',reject:'Rejeitar',refine:'Nova versão',social:'Feed / story / mockup'})[action]}</button>`).join('')}</div></article>`).join('')||empty('Nenhum artefato registrado.');
    }],['/api/admin/mi/conselho','mic-creative-meetings',b=>{
      $('mic-creative-meetings').innerHTML=[...arr(b.conselho?.reunioes_recentes),...arr(b.conselho?.relatorios_recentes)].map(r=>`<div class="mic-row"><b>${esc(r.titulo||r.tipo)}</b><button data-creative-action="ata" data-record="${esc(r.id)}">Secretário</button><button data-creative-action="deck" data-record="${esc(r.id)}">Gerar PPTX</button></div>`).join('')||empty('Nenhuma reunião registrada.');
    }],['/api/admin/mi/brand-context','mic-creative-brand',b=>{$('mic-creative-brand').textContent=b.configurado?JSON.stringify(b.campos):'Brand Context não configurado.';}],
    ['/api/admin/mi/visual-memory','mic-creative-brand',b=>{const p=document.createElement('p');p.textContent=`Referências aprovadas: ${arr(b.referencias).length}`;$('mic-creative-brand').appendChild(p);}],
    ['/api/admin/mi/pirret/provider-status','mic-creative-provider',b=>{$('mic-creative-provider').textContent=b.provider==='MockImageProvider'?'MOCK/TEST ONLY — sem geração real':b.disponivel?'Provider configurado · disponibilidade externa não homologada':'IMAGE PROVIDER — NOT CONFIGURED';}]];
    for(const [path,target,render] of reads){try{render(await get(path));}catch(e){$(target).textContent=e.message;}}
  }
  async function creativeClick(e) {
    const button=e.target.closest('[data-creative-action]'); if(!button)return;
    const action=button.dataset.creativeAction, id=button.dataset.artifact, record=button.dataset.record;
    const status=$('mic-creative-status'); button.disabled=true; status.textContent='Processando solicitação…';
    try {
      let result;
      const actor=$('mic-creative-actor').value.trim();
      if(['approve','reject','record'].includes(action)&&!actor)throw new Error('Informe o responsável pela decisão.');
      if(action==='refresh') await loadCreative();
      else if(action==='analyze') {const f=new FormData();f.append('demanda',$('mic-creative-demand').value);f.append('modo','automatico');result=await write('/api/admin/mi/conselho/analisar',f,true);creativeAnalysis=result.resultado;$('mic-creative-analysis').textContent=creativeAnalysis.sintese||JSON.stringify(creativeAnalysis);}
      else if(action==='record'){if(!creativeAnalysis)throw new Error('Solicite um parecer primeiro.');result=await write('/api/admin/mi/conselho/enviar-diretor',{resultado:creativeAnalysis});await loadCreative();}
      else if(action==='ata'){result=await get('/api/admin/mi/conselho/'+encodeURIComponent(record)+'/ata');$('mic-creative-detail').textContent=JSON.stringify(result,null,2);}
      else if(action==='deck'){result=await write('/api/admin/mi/conselho/'+encodeURIComponent(record)+'/apresentacao',{});await loadCreative();}
      else if(action==='label'||action==='campaign') {const pedido=$('mic-creative-brief').value.trim();if(!pedido)throw new Error('Informe o brief.');result=await write(action==='label'?'/api/admin/mi/label-studio/conceitos':'/api/admin/mi/pirret/conceitos',{pedido,sku:$('mic-creative-sku').value.trim(),quantidade:1,artifact_type:'SOCIAL_CREATIVE'});await loadCreative();}
      else if(action==='approve'||action==='reject'){result=await write(artifactPath(id)+(action==='approve'?'/aprovar':'/rejeitar'),{ator:actor});await loadCreative();}
      else if(action==='detail'){result=await get(artifactPath(id)+'/linhagem');const audit=await get(artifactPath(id)+'/auditoria');$('mic-creative-detail').textContent=JSON.stringify({...result,...audit},null,2);}
      else if(action==='refine'){const instrucao=$('mic-creative-brief').value.trim();if(!instrucao)throw new Error('Informe no brief a alteração desejada.');result=await write('/api/admin/mi/pirret/refinar/'+encodeURIComponent(id),{instrucao});await loadCreative();}
      else if(action==='social'){result=await write('/api/admin/mi/social-studio/campanha/'+encodeURIComponent(id),{formatos:['feed','story','mockup'],briefing:$('mic-creative-brief').value});await loadCreative();}
      else if(action==='chart'){
        const overview=await get('/api/admin/mi/overview?amostra_limite=50'), segments=overview.segmentos_distribuicao;
        const entries=segments&&!Array.isArray(segments)?Object.entries(segments):[];
        if(!entries.length||entries.some(([,v])=>typeof v!=='number'||!Number.isFinite(v))){status.textContent='AGUARDANDO DADOS / NOT_ENOUGH_DATA';return;}
        result=await write('/api/admin/mi/graficos',{spec:{chart_type:'bar',title:'Segmentos registrados',x:entries.map(([k])=>k),series:[{name:'Relações',values:entries.map(([,v])=>v)}],units:'relações',source:'MI overview · segmentos_distribuicao',freshness:new Date().toISOString(),confidence:'DERIVED'}});await loadCreative();
      } else if(action==='download'||action==='open'){
        if(!window.adminKeyAtual)throw new Error('Entre no Admin.');
        const r=await fetch(BASE+artifactPath(id)+'/download',{headers:{'X-Admin-Key':window.adminKeyAtual}});if(!r.ok)throw new Error('Download indisponível.');
        const blob=await r.blob(), url=URL.createObjectURL(blob);
        // Only passive image types are previewed; arbitrary HTML/SVG is downloaded.
        if(action==='open'&&['image/png','image/jpeg','image/webp'].includes(blob.type)){const img=document.createElement('img');img.src=url;img.alt='Artefato registrado';img.style.maxWidth='100%';$('mic-creative-detail').replaceChildren(img);}
        else {const link=document.createElement('a');link.href=url;link.download='artefato-'+id+(blob.type.includes('presentationml')?'.pptx':blob.type.includes('svg')?'.svg':'');link.click();}
        setTimeout(()=>URL.revokeObjectURL(url),60000);
      }
      status.textContent='Solicitação concluída. Nenhuma publicação externa realizada.';
    } catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  }

  function shell() {
    panel.innerHTML = `
      <header class="mic-hero">
        <div><p class="mi-eyebrow">MARANHÃO INTELLIGENCE · COMMAND CENTER</p><h2>Inteligência que vira decisão.</h2><p class="mi-subtitle">Relacionamentos, sinais, oportunidades e resultados em uma única superfície. Evidência antes de ação.</p></div>
        <div class="mic-hero-actions"><span class="mic-live"><i></i> Human-in-the-loop</span><button id="mic-refresh" type="button">Atualizar</button></div>
      </header>
      <p id="mic-status" class="mic-status" role="status" aria-live="polite">Pronto para consultar.</p>
      <nav class="mic-nav" aria-label="Áreas da Intelligence">
        <button class="active" data-mic-view="overview">Overview</button><button data-mic-view="decisions">Decisões</button><button data-mic-view="relationship">Relationship 360</button><button data-mic-view="legacy">Produto & território</button><button data-mic-view="creative">Executivo & Criativo</button>
      </nav>
      <div id="mic-overview" class="mic-view active">
        <div id="mic-kpis" class="mic-kpis"></div>
        <div class="mic-grid mic-grid--2"><section class="mic-card"><div class="mic-card-head"><div><span>01 · INTELLIGENCE</span><h3>Oportunidades detectadas</h3></div><b id="mic-op-count">0</b></div><div id="mic-opportunities"></div></section>
        <section class="mic-card"><div class="mic-card-head"><div><span>02 · GOVERNANÇA</span><h3>Fila de decisão</h3></div><b id="mic-queue-count">0</b></div><div id="mic-queue-preview"></div><button class="mic-link" data-open-view="decisions">Abrir fila completa →</button></section></div>
        <div class="mic-grid mic-grid--3"><section class="mic-card"><span class="mic-kicker">SEGMENTOS</span><h3>Distribuição atual</h3><div id="mic-segments"></div></section><section class="mic-card"><span class="mic-kicker">LEARNING READINESS</span><h3>Base para aprendizado</h3><div id="mic-learning"></div></section><section class="mic-card"><span class="mic-kicker">DATA QUALITY</span><h3>Confiança da leitura</h3><div id="mic-quality"></div></section></div>
      </div>
      <div id="mic-decisions" class="mic-view"><section class="mic-card mic-card--wide"><div class="mic-card-head"><div><span>HUMAN DECISION</span><h3>Recomendações aguardando decisão</h3></div></div><p class="mic-note">Esta tela explica e organiza recomendações. Aprovações e execução continuam nos controles existentes; nada é enviado automaticamente.</p><div id="mic-queue"></div></section></div>
      <div id="mic-relationship" class="mic-view"><section class="mic-card mic-card--wide"><span class="mic-kicker">CUSTOMER / PARTNER 360</span><h3>Investigar relacionamento</h3><div class="mic-search"><input id="mic-rel-id" placeholder="ID do lead ou estabelecimento" autocomplete="off"><button id="mic-rel-load" type="button">Abrir 360</button></div><div id="mic-rel-result"></div></section></div>
      <div id="mic-creative" class="mic-view">${creativeShell()}</div>
      <div id="mic-legacy" class="mic-view"><section class="mic-card mic-card--wide"><span class="mic-kicker">OPERAÇÃO FÍSICA</span><h3>Produto → Unidade → Mercado → Território</h3><div id="mic-legacy-body"><p class="mic-note">Carregando rastreabilidade operacional…</p></div></section></div>`;

    panel.querySelectorAll('[data-mic-view]').forEach(b => b.addEventListener('click', () => openView(b.dataset.micView)));
    panel.querySelectorAll('[data-open-view]').forEach(b => b.addEventListener('click', () => openView(b.dataset.openView)));
    $('mic-creative').addEventListener('click',creativeClick);
    $('mic-refresh').addEventListener('click', loadAll);
    $('mic-rel-load').addEventListener('click', loadRelationship);
    $('mic-rel-id').addEventListener('keydown', e => { if (e.key === 'Enter') loadRelationship(); });
  }

  function openView(name) {
    if(name==='creative')loadCreative();
    panel.querySelectorAll('[data-mic-view]').forEach(b => b.classList.toggle('active', b.dataset.micView === name));
    panel.querySelectorAll('.mic-view').forEach(v => v.classList.toggle('active', v.id === 'mic-' + name));
  }

  function kpi(title, n, meta, tone='') { return `<article class="mic-kpi ${tone}"><span>${esc(title)}</span><strong>${esc(num(n))}</strong><small>${esc(meta)}</small></article>`; }
  function empty(text) { return `<div class="mic-empty"><b>Sem atividade para mostrar</b><span>${esc(text)}</span></div>`; }

  function renderOverview(o, q) {
    const rel = o.relacionamentos_conhecidos || {};
    const fila = o.fila_decisao || {};
    const learning = o.learning_status || {};
    // oportunidades_detectadas (contrato P5) é um mapa {tipo: contagem} --
    // mesma forma de segmentos_distribuicao, nunca uma lista de objetos.
    const ops = o.oportunidades_detectadas || o.opportunities || {};
    const seg = o.segmentos_distribuicao || o.segments_distribution || {};
    const known = value(rel,['total_pessoas','total','conhecidos'], value(o,['relacionamentos_total'],0));
    const sufficient = value(rel,['dados_suficientes','suficientes'],0);
    const pending = value(fila,['pendentes','aguardando'], q.length);
    const outcomes = value(o,['outcomes_registrados'], value(learning,['outcomes_registrados','outcomes'],0));
    const opEntries = Array.isArray(ops) ? ops.map((x,i)=>[x.tipo||x.type||`#${i+1}`, 1]) : Object.entries(ops || {});
    const opTotal = opEntries.reduce((acc,[,v])=>acc+(Number(v)||0),0);
    $('mic-kpis').innerHTML = kpi('Relacionamentos',known,'pessoas e organizações conhecidas') + kpi('Dados suficientes',sufficient,'aptos a uma leitura mais completa') + kpi('Oportunidades',opTotal,'sinais convertidos em oportunidade','accent') + kpi('Aguardando decisão',pending,'nenhuma ação automática','attention') + kpi('Outcomes',outcomes,'resultados registrados');

    $('mic-op-count').textContent = num(opTotal);
    $('mic-opportunities').innerHTML = opEntries.length ? `<div class="mic-bars">${opEntries.slice(0,8).map(([tipo,total])=>`<div><span>${esc(label(tipo))}</span><b>${esc(num(total))}</b></div>`).join('')}</div>` : empty('As oportunidades aparecerão conforme sinais reais forem registrados.');

    $('mic-queue-count').textContent = num(q.length);
    $('mic-queue-preview').innerHTML = q.length ? q.slice(0,4).map(queueRow).join('') : empty('Nenhuma recomendação está aguardando decisão humana.');
    const entries = Array.isArray(seg) ? seg.map(x=>[x.segmento||x.name,x.total||x.count]) : Object.entries(seg || {});
    $('mic-segments').innerHTML = entries.length ? `<div class="mic-bars">${entries.slice(0,8).map(([n,v])=>`<div><span>${esc(label(n))}</span><b>${esc(num(v))}</b></div>`).join('')}</div>` : empty('A distribuição surgirá com relacionamentos classificáveis.');

    const ready = !!value(learning,['ready'],false); const lines = value(learning,['total_linhas_dataset','linhas_dataset','dataset_rows'],0);
    $('mic-learning').innerHTML = `<div class="mic-readiness ${ready?'ready':''}"><strong>${ready?'READY':'NOT ENOUGH DATA'}</strong><span>${esc(num(lines))} linhas reais de aprendizado</span><p>${esc(learning.motivo || learning.reason || (ready?'Base mínima disponível.':'O sistema aguarda decisões e outcomes reais antes de aprender.'))}</p></div>`;
    const insufficient = value(rel,['dados_insuficientes','insuficientes'],Math.max(known-sufficient,0));
    $('mic-quality').innerHTML = `<div class="mic-quality"><strong>${known ? Math.round((sufficient/known)*100) : 0}%</strong><span>cobertura suficiente</span><p>${esc(num(insufficient))} relacionamentos ainda precisam de mais evidência.</p></div>`;
  }

  function queueRow(x) { return `<div class="mic-row mic-row--decision"><div><b>${esc(x.recommendation || x.recomendacao || 'Recomendação')}</b><span>${esc(x.reason || x.motivo || 'Sem justificativa adicional.')}</span><small>${esc(x.relationship_id || x.lead_id || x.estabelecimento_id || '')}</small></div><em>${esc(label(x.confidence || x.confianca || x.priority || x.prioridade))}</em></div>`; }
  function renderQueue(q) { $('mic-queue').innerHTML = q.length ? q.map(queueRow).join('') : empty('Quando a Intelligence gerar recomendações persistidas, elas aparecerão aqui.'); }

  function renderTerritorio(territory) {
    // `territory` (contrato P5, ?incluir_territorio=1) é 'not_requested'
    // (não pedido), 'NOT_ENOUGH_DATA' (pedido, sem correspondência real) ou
    // uma lista real de oportunidades territoriais -- nunca inventamos
    // cobertura quando cidade/UF não bateram com nada calculado.
    if (territory === 'not_requested') return empty('Território não foi solicitado nesta consulta.');
    if (!Array.isArray(territory) || !territory.length) return empty('Dados insuficientes para território.');
    return territory.map(t => `<div class="mic-row"><div><b>${esc(t.type || 'Território')}</b><span>${esc(t.territory || '')} · ${esc((arr(t.evidence)[0]) || '')}</span></div><em>${esc(label(t.priority))}</em></div>`).join('');
  }

  async function loadRelationship() {
    const id = $('mic-rel-id').value.trim(); if (!id) { $('mic-rel-result').innerHTML = empty('Informe um ID para abrir o Relationship 360.'); return; }
    $('mic-rel-result').innerHTML = '<p class="mic-note">Montando visão 360…</p>';
    try {
      const d = await get(`/api/admin/mi/relacionamento/${encodeURIComponent(id)}/contrato?incluir_territorio=1&incluir_forecast=1`);
      // Contrato canônico P5: identity.pessoa (não identity.nome direto);
      // score/score_version/confidence são campos PLANOS no topo, nunca um
      // sub-objeto `score.score_geral`.
      const identity = d.identity || {}; const pessoa = identity.pessoa || {};
      const org = d.organization || {}; const provenance = d.provenance || {}; const explain = d.explainability || {};
      const segments = arr(d.segments); const opps = arr(d.opportunities); const nbas = arr(d.next_best_actions);
      const scoreDisplay = typeof d.score === 'number' ? d.score : label(d.score);
      $('mic-rel-result').innerHTML = `<div class="mic-rel-head"><div><span>IDENTIDADE</span><h4>${esc(pessoa.nome || pessoa.empresa || org.nome || org.name || id)}</h4><p>${esc(org.nome || org.name || pessoa.empresa || 'Organização não confirmada')}</p></div><div class="mic-score"><span>Relationship score</span><strong>${esc(scoreDisplay)}</strong><small>${esc(d.score_version || '')}</small></div></div>
      <div class="mic-grid mic-grid--3"><div class="mic-mini"><span>Segmentos</span><p>${segments.length?segments.map(x=>esc(label(x.segmento||x.nome||x))).join(' · '):'Dados insuficientes'}</p></div><div class="mic-mini"><span>Oportunidades</span><strong>${opps.length}</strong></div><div class="mic-mini"><span>Next best actions</span><strong>${nbas.length}</strong></div></div>
      <div class="mic-grid mic-grid--2"><section class="mic-sub"><h4>Por que o sistema pensa isso?</h4><p>${esc(explain.motivo_principal || d.recommendations?.[0]?.reason || 'A explicação aparecerá quando houver recomendação sustentada por evidências.')}</p>${arr(explain.evidencias || explain.evidence).map(e=>`<span class="mic-evidence">${esc(typeof e==='string'?e:JSON.stringify(e))}</span>`).join('')}</section><section class="mic-sub"><h4>Proveniência</h4><div class="mic-provenance">${Object.entries(provenance).slice(0,10).map(([k,v])=>`<span><b>${esc(k)}</b>${esc(label(typeof v==='object'?(v.status||v.tipo||'DERIVED'):v))}</span>`).join('') || '<span>Sem metadados de proveniência.</span>'}</div></section></div>
      <section class="mic-sub"><h4>Oportunidades e próximas ações</h4>${opps.length?opps.map(x=>`<div class="mic-row"><div><b>${esc(x.type||x.tipo||'Oportunidade')}</b><span>${esc((arr(x.evidence||x.evidencias)[0])||x.recommended_action||'')}</span></div></div>`).join(''):empty('Nenhuma oportunidade detectada para este relacionamento.')}</section>
      <section class="mic-sub"><h4>Território</h4>${renderTerritorio(d.territory)}</section>`;
    } catch(e) { $('mic-rel-result').innerHTML = `<div class="mic-error">${esc(e.message)}</div>`; }
  }

  async function loadLegacy() {
    try { const p = await get('/api/admin/mi/painel'); const r=p.resumo||{}; $('mic-legacy-body').innerHTML = `<div class="mic-kpis">${kpi('Unidades',r.unidades,'unidades rastreáveis')}${kpi('Eventos',r.eventos,'eventos físicos/digitais')}${kpi('Scans QR',r.scans_qr,'leituras registradas')}${kpi('Estabelecimentos',r.estabelecimentos,'pontos vinculados')}${kpi('Territórios ativos',r.territorios_ativos,'cobertura observada')}</div><p class="mic-note">Esta camada mantém a rastreabilidade operacional existente. A inteligência territorial detalhada continua disponível na seção Território.</p>`; } catch(e) { $('mic-legacy-body').innerHTML = `<div class="mic-error">${esc(e.message)}</div>`; }
  }

  async function loadAll() {
    const btn=$('mic-refresh'); btn.disabled=true; $('mic-status').textContent='Sincronizando visão executiva…';
    try {
      const [o,qb] = await Promise.all([get('/api/admin/mi/overview?amostra_limite=50'),get('/api/admin/mi/fila-decisao')]);
      const q = arr(qb.pendentes || qb.items || qb.fila || qb.recomendacoes || qb.data || (Array.isArray(qb)?qb:[]));
      renderOverview(o,q); renderQueue(q); loadLegacy(); loaded=true;
      $('mic-status').textContent=`Atualizado às ${new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}. Leitura baseada nos dados existentes.`;
    } catch(e) { $('mic-status').textContent=e.message; }
    finally { btn.disabled=false; }
  }

  shell();
  document.querySelector('[data-tab="maranhao-intelligence"]')?.addEventListener('click',()=>{ if(!loaded && window.adminKeyAtual) loadAll(); });
  window.addEventListener('admin-autorizado',()=>{ if(panel.classList.contains('active')) loadAll(); });
})();
