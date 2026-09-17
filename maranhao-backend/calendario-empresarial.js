/* Calendário Empresarial — camada visual sobre /api/admin/mi/calendario.
   Três visões (seção 2 da ordem Central Empresarial): Lista (baldes
   hoje/próximas/aguardando/precisa de você, como já existia), Semana e
   Mês (grade com as atividades que têm data real). Mesma fonte de
   dados única -- nenhuma visão busca de um endpoint diferente. */
(()=>{'use strict';
const BASE='https://maranhao-cordial-api.onrender.com';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label=v=>String(v||'Ação').replaceAll('_',' ');
const data=v=>{if(!v)return 'Sem horário definido';const d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'});};
const MESES=['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
const DIAS_SEMANA=['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];

let ultimoDado=null, modoAtual='lista', referencia=new Date();

async function carregar(){const root=document.getElementById('calendario-empresarial');if(!root||!window.adminKeyAtual)return;const status=document.getElementById('ce-status');status.textContent='Atualizando agenda…';try{const r=await fetch(BASE+'/api/admin/mi/calendario',{cache:'no-store',headers:{'X-Admin-Key':window.adminKeyAtual}});const b=await r.json();if(!r.ok||b.success===false)throw new Error(b.error||`Calendário indisponível (${r.status}).`);ultimoDado=b;renderTudo();status.textContent='Agenda atualizada agora.';}catch(e){status.textContent=e.message;}}

function cardOperacao(a){return `<article class="ce-evento ce-evento--operacao" data-operacao-id="${esc(a.operacao_id)}" tabindex="0" role="button"><div class="ce-evento-topo"><b>${esc(a.titulo)}</b><span>${esc(a.prioridade)}</span></div><p>${esc(a.local||'AGUARDANDO DADOS')} · ${esc(a.responsavel||'AGUARDANDO DADOS')}</p><small>${esc(a.data_inicio)} a ${esc(a.data_fim)} · ${esc(a.estado_operacao)}</small></article>`;}
function cardPadrao(a){return `<article class="ce-evento"><div class="ce-evento-topo"><b>${esc(label(a.tipo_decisao||a.proxima_acao||a.titulo))}</b><span>${esc(a.prioridade||a.estado||'')}</span></div><p>${esc(a.inferencia||a.descricao||a.proxima_acao||'Ação empresarial registrada.')}</p><small>${esc(data(a.executar_em))}</small></article>`;}
function cards(itens){if(!Array.isArray(itens)||!itens.length)return '<p class="ce-vazio">Nenhuma ação.</p>';return itens.map(a=>a.tipo_decisao==='operacao_viva'?cardOperacao(a):cardPadrao(a)).join('');}

function todasAsAtividades(b){const c=b.colunas||{};return [].concat(c.hoje||[],c.proximas||[],c.aguardando||[],c.precisa_diretor||[],c.concluidas||[],c.bloqueadas||[]);}
function dataChave(d){return d.toISOString().slice(0,10);}
function diasDaAtividade(a){
  // Operação viva ocupa todo o intervalo [data_inicio, data_fim]; demais
  // atividades ocupam só o dia de executar_em (ou hoje, se ausente).
  if(a.tipo_decisao==='operacao_viva'){const out=[];let d=new Date(a.data_inicio+'T00:00:00');const fim=new Date(a.data_fim+'T00:00:00');while(d<=fim){out.push(dataChave(d));d.setDate(d.getDate()+1);}return out;}
  const dt=a.executar_em?new Date(a.executar_em):new Date();
  return Number.isNaN(dt.getTime())?[]:[dataChave(dt)];
}
function agruparPorDia(b){const mapa={};for(const a of todasAsAtividades(b))for(const chave of diasDaAtividade(a)){(mapa[chave]=mapa[chave]||[]).push(a);}return mapa;}

function chipAtividade(a){const cls=a.tipo_decisao==='operacao_viva'?'ce-chip ce-chip--operacao':'ce-chip';const attr=a.tipo_decisao==='operacao_viva'?` data-operacao-id="${esc(a.operacao_id)}" role="button" tabindex="0"`:'';return `<span class="${cls}"${attr}>${esc(a.titulo||label(a.tipo_decisao))}</span>`;}

function renderMes(b){
  const mapa=agruparPorDia(b);
  const ano=referencia.getFullYear(),mes=referencia.getMonth();
  const primeiroDia=new Date(ano,mes,1);
  const offset=(primeiroDia.getDay()+6)%7; // semana começa na segunda
  const diasNoMes=new Date(ano,mes+1,0).getDate();
  const hoje=dataChave(new Date());
  let celulas='';
  for(let i=0;i<offset;i++)celulas+='<div class="ce-dia ce-dia--fora"></div>';
  for(let dia=1;dia<=diasNoMes;dia++){
    const chave=dataChave(new Date(ano,mes,dia));
    const atividades=mapa[chave]||[];
    celulas+=`<div class="ce-dia${chave===hoje?' ce-dia--hoje':''}"><span class="ce-dia-numero">${dia}</span>${atividades.slice(0,4).map(chipAtividade).join('')}${atividades.length>4?`<span class="ce-chip-mais">+${atividades.length-4}</span>`:''}</div>`;
  }
  return `<div class="ce-mes-nav"><button type="button" data-nav="mes-anterior">←</button><h4>${MESES[mes]} ${ano}</h4><button type="button" data-nav="mes-seguinte">→</button></div><div class="ce-mes-grade"><div class="ce-mes-cabecalho">${DIAS_SEMANA.map(d=>`<span>${d}</span>`).join('')}</div><div class="ce-mes-dias">${celulas}</div></div>`;
}

function inicioDaSemana(d){const n=new Date(d);const dia=(n.getDay()+6)%7;n.setDate(n.getDate()-dia);n.setHours(0,0,0,0);return n;}

function renderSemana(b){
  const mapa=agruparPorDia(b);
  const inicio=inicioDaSemana(referencia);
  const hoje=dataChave(new Date());
  let colunas='';
  for(let i=0;i<7;i++){
    const d=new Date(inicio);d.setDate(inicio.getDate()+i);
    const chave=dataChave(d);
    const atividades=mapa[chave]||[];
    colunas+=`<section class="ce-semana-dia${chave===hoje?' ce-dia--hoje':''}"><h4>${DIAS_SEMANA[i]} ${d.getDate()}</h4>${atividades.length?atividades.map(chipAtividade).join(''):'<p class="ce-vazio">Sem ações.</p>'}</section>`;
  }
  const fim=new Date(inicio);fim.setDate(inicio.getDate()+6);
  return `<div class="ce-mes-nav"><button type="button" data-nav="semana-anterior">←</button><h4>${inicio.toLocaleDateString('pt-BR')} a ${fim.toLocaleDateString('pt-BR')}</h4><button type="button" data-nav="semana-seguinte">→</button></div><div class="ce-semana-grade">${colunas}</div>`;
}

function renderLista(b){const c=b.colunas||{},r=b.resumo||{};return `<div class="ce-resumo"><div><strong>${r.total_hoje||0}</strong><span>Hoje</span></div><div><strong>${r.total_proximas||0}</strong><span>Próximas</span></div><div><strong>${r.total_aguardando||0}</strong><span>Aguardando</span></div><div><strong>${r.total_precisa_diretor||0}</strong><span>Precisa de você</span></div></div><div class="ce-colunas"><section><h4>Hoje</h4>${cards(c.hoje)}</section><section><h4>Próximas</h4>${cards(c.proximas)}</section><section><h4>Aguardando</h4>${cards(c.aguardando)}</section><section><h4>Precisa de você</h4>${cards(c.precisa_diretor)}</section></div><details class="ce-concluidas"><summary>Concluídas e bloqueadas</summary><div class="ce-colunas ce-colunas--2"><section><h4>Concluídas</h4>${cards(c.concluidas)}</section><section><h4>Bloqueadas</h4>${cards(c.bloqueadas)}</section></div></details>`;}

function renderTudo(){
  const root=document.getElementById('ce-corpo');
  if(!root)return;
  if(!ultimoDado){root.innerHTML='<p class="ce-vazio">Carregando…</p>';return;}
  const abas=`<div class="ce-modos">${['lista','semana','mes'].map(m=>`<button type="button" class="ce-modo${modoAtual===m?' active':''}" data-modo="${m}">${m==='lista'?'Lista':m==='semana'?'Semana':'Mês'}</button>`).join('')}</div>`;
  const corpo=modoAtual==='mes'?renderMes(ultimoDado):modoAtual==='semana'?renderSemana(ultimoDado):renderLista(ultimoDado);
  root.innerHTML=abas+corpo;
}

document.addEventListener('click',e=>{
  if(e.target?.id==='ce-atualizar')carregar();
  const tab=e.target?.closest?.('[data-tab="calendario"]');if(tab)setTimeout(carregar,0);
  const evOp=e.target?.closest?.('.ce-evento--operacao')||e.target?.closest?.('.ce-chip--operacao');
  if(evOp)window.abrirOperacaoViva?.(evOp.dataset.operacaoId);
  const modoBtn=e.target?.closest?.('[data-modo]');
  if(modoBtn){modoAtual=modoBtn.dataset.modo;renderTudo();}
  const nav=e.target?.closest?.('[data-nav]');
  if(nav){
    const passo=nav.dataset.nav.includes('anterior')?-1:1;
    if(nav.dataset.nav.startsWith('mes'))referencia=new Date(referencia.getFullYear(),referencia.getMonth()+passo,1);
    else referencia=new Date(referencia.getFullYear(),referencia.getMonth(),referencia.getDate()+passo*7);
    renderTudo();
  }
});
document.addEventListener('keydown',e=>{if(e.key!=='Enter'&&e.key!==' ')return;const evOp=e.target?.closest?.('.ce-evento--operacao')||e.target?.closest?.('.ce-chip--operacao');if(evOp){e.preventDefault();window.abrirOperacaoViva?.(evOp.dataset.operacaoId);}});
window.carregarCalendarioEmpresarial=carregar;
})();
