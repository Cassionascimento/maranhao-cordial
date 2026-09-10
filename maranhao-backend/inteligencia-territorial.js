/* Leitura e registro de observações. Nenhum endpoint de execução ou transporte. */
(() => {
  'use strict';
  const panel = document.getElementById('territorio-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/inteligencia-territorial';
  const $ = id => document.getElementById('territorio-' + id);
  let report = null, busy = false, pendingRecord = null;
  const titles = {midia:'Mídia → onde investir agora?', prospeccao:'Prospecção → onde concentrar busca?',
    producao_distribuicao:'Produção/Distribuição → onde investigar estrutura?', eventos:'Eventos → quais territórios priorizar?'};
  const labels = {relacoes:'Relações únicas',contatados:'Relações abordadas',respostas_com_abordagem:'Relações com resposta após abordagem',
    interesses_confirmados:'Interesses confirmados',classificacoes_interesse:'Classificações de interesse pela IA',relacoes_com_conversao:'Relações com conversão',
    relacoes_com_amostra_registrada:'Relações com amostra registrada',relacoes_com_eventos:'Relações com vínculo a eventos',presencas_digitais:'Relações com perfil/site',
    circulacoes_registradas:'Circulações realizadas registradas',registros_operacionais:'Registros operacionais',relacoes_verificadas:'Relações verificadas'};
  function el(tag,text,cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e; }
  function list(items) { const ul=el('ul'); for(const s of items)ul.append(el('li',s)); return ul; }
  const pct = v => v==null ? 'desconhecida' : new Intl.NumberFormat('pt-BR',{style:'percent',maximumFractionDigits:1}).format(v);
  async function call(path='',options={}) {
    if(!window.adminKeyAtual)throw new Error('Entre no Admin para consultar os dados.');
    const response=await fetch(api+path,{...options,cache:'no-store',headers:{'X-Admin-Key':window.adminKeyAtual,'Content-Type':'application/json'}});
    const body=await response.json();
    if(!response.ok || !body.success)throw new Error(body.error || 'Não foi possível confirmar a operação.');
    return body;
  }
  function controls(value) {
    busy=value;
    for(const id of ['atualizar','interpretar','salvar'])$(id).disabled=value;
  }
  function detail(bucket) {
    const box=$('detalhe');box.replaceChildren();
    box.append(el('h3',bucket.territorio),el('h4','FATOS • registros do sistema'));
    const facts=el('dl',undefined,'territorio-fatos');
    for(const [key,label] of Object.entries(labels)) {facts.append(el('dt',label),el('dd',String(bucket.fatos[key]??0)));}
    box.append(facts,el('p','Zero significa nenhum registro observado na base consultada; não comprova inexistência no território.','territorio-nota'));
    if(Object.keys(bucket.circulacao).length)box.append(el('p','Circulação realizada: '+Object.entries(bucket.circulacao).map(([k,v])=>`${v} ${k}`).join(' · ')));
    if(Object.keys(bucket.metricas).length)box.append(el('p','Métricas operacionais registradas: '+Object.entries(bucket.metricas).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ')));
    box.append(el('h4','SINAIS • padrões observados'),el('p',`Taxa de resposta: ${pct(bucket.indicadores.taxa_resposta)} (${bucket.fatos.respostas_com_abordagem??0}/${bucket.indicadores.base_taxa_resposta} relações abordadas).`),
      el('p',`Concentração na base localizada: ${pct(bucket.indicadores.densidade_relativa_base_localizada)}. Não representa participação de mercado.`),list(bucket.sinais));
    const evidence=el('details');evidence.append(el('summary',`Evidências utilizadas (${bucket.evidencias.length})`));
    const rows=el('ul');
    for(const e of bucket.evidencias)rows.append(el('li',`${e.nome} — ${e.fonte}; referência ${e.id}${e.localizacao_registrada ? '; local informado: '+Object.values(e.localizacao_registrada).join(' / ') : ''}${e.data ? '; data: '+e.data : ''}${e.verificada ? '; verificação registrada' : '; validação não comprovada'}`));
    evidence.append(rows);box.append(evidence);box.hidden=false;
  }
  function territories() {
    const rows=$('lista');rows.replaceChildren();
    for(const b of report.niveis[$('nivel').value]) {
      const button=el('button',undefined,'territorio-linha');button.type='button';
      button.append(el('strong',b.territorio),el('span',`${b.fatos.relacoes??0} relações · resposta ${pct(b.indicadores.taxa_resposta)} (${b.fatos.respostas_com_abordagem??0}/${b.indicadores.base_taxa_resposta})`));
      button.addEventListener('click',()=>detail(b));rows.append(button);
    }
  }
  function render() {
    const c=report.cobertura;
    $('cobertura').textContent=`${c.relacoes_unicas} relações únicas · ${c.relacoes_sem_cidade_uf} sem cidade/UF completas · ${c.interacoes_sem_vinculo} interações sem vínculo · ${c.registros_excluidos} registros excluídos por teste, arquivo ou invalidação.`;
    $('limites').replaceChildren(list([report.periodo,...report.limites,...(c.fontes_limitadas.length ? ['Base parcial; fontes limitadas: '+c.fontes_limitadas.join(', ')] : [])]));
    const digital=report.presenca_digital.snapshot_existente;
    $('digital').textContent=digital ? `Presença digital: snapshot global de ${digital.data}, ${digital.janela}. Localização da audiência desconhecida; tráfego global não foi distribuído entre territórios.` : 'Presença digital: não há snapshot com métricas territoriais disponível.';
    const ia=report.interpretacao_ia;
    $('ia-status').textContent=ia ? 'RECOMENDAÇÃO • interpretação da IA sobre este conjunto de dados, para decisão da direção.' : 'SINAIS • ranking calculado a partir dos registros. A interpretação da IA ainda não foi solicitada para estes dados.';
    $('cards').replaceChildren();
    for(const [key,title] of Object.entries(titles)) {
      const d=ia ? ia.decisoes[key] : report.decisoes[key];
      const card=el('article',undefined,'territorio-card');
      card.append(el('h3',title),el('p',d.classificacao,'territorio-nivel'),el('h4',d.territorio || 'Sem prioridade sustentada pelos dados'));
      if(key==='midia' && d.classificacao!=='evidência suficiente')card.append(el('p','Ainda não há base para recomendar investimento agora.'));
      card.append(list(d.por_que));
      if(d.motivos_ia)card.append(el('p','Ênfase da IA: '+d.motivos_ia.join('; ')));
      const gaps=el('details');gaps.append(el('summary','Dados necessários para avançar'),list(d.dados_faltantes));card.append(gaps);
      if(d.territorio_id) {
        const btn=el('button','Ver fatos e evidências');btn.type='button';
        btn.addEventListener('click',()=>{detail(report.niveis.cidade.find(b=>b.id===d.territorio_id));$('detalhe').scrollIntoView({behavior:'smooth',block:'start'});});card.append(btn);
      }
      $('cards').append(card);
    }
    territories();$('conteudo').hidden=false;
  }
  async function load() {
    if(busy)return;controls(true);$('status').textContent='Consultando os registros existentes…';
    try {report=await call();render();$('status').textContent='Leitura atualizada. Nenhuma ação externa executada.';}
    catch(e){$('status').textContent=e.message;}
    finally{controls(false);}
  }
  $('atualizar').addEventListener('click',load);
  $('nivel').addEventListener('change',()=>{if(report){$('detalhe').hidden=true;territories();}});
  $('interpretar').addEventListener('click',async()=>{
    if(busy)return;controls(true);$('status').textContent='Interpretando os agregados com IA…';
    try {const result=await call('/interpretar',{method:'POST',body:'{}'});
      report=await call();render();$('status').textContent=result.cache ? 'Interpretação existente reutilizada para estes dados.' : 'Interpretação registrada. Nenhuma ação externa executada.';}
    catch(e){$('status').textContent=e.message;}finally{controls(false);}
  });
  const form=$('form');
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    const record={metricas:{}};
    for(const [k,v] of new FormData(form)) {
      const value=String(v).trim();
      if(k.startsWith('metrica_')){if(value!=='')record.metricas[k.slice(8)]=Number(value);}
      else record[k]=value==='' ? null : k==='quantidade' ? Number(value) : value;
    }
    const content=JSON.stringify(record);
    // Em erro/retry, mantém a mesma chave apenas para o mesmo conteúdo.
    if(!pendingRecord || pendingRecord.content!==content)pendingRecord={content,chave:crypto.randomUUID()};
    controls(true);$('status').textContent='Registrando o fato observado…';
    try {
      await call('/registros',{method:'POST',body:JSON.stringify({...record,chave:pendingRecord.chave})});
      pendingRecord=null;form.reset();report=await call();render();
      $('status').textContent='Fato registrado. Isso não movimenta estoque nem dispara contatos.';
    } catch(e){$('status').textContent=e.message;}finally{controls(false);}
  });
  document.querySelector('[data-tab="inteligencia-territorial"]').addEventListener('click',()=>{if(!report && window.adminKeyAtual)load();});
  window.addEventListener('admin-autorizado',()=>{if(panel.classList.contains('active'))load();});
})();
