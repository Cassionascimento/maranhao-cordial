/* Supervisão: consulta autenticada, sem botão de execução ou alteração de pausa. */
(() => {
  if (typeof document === 'undefined') return;
  const root=document.getElementById('painel-executivo');
  if (!root) return;
  const box=document.createElement('article');box.className='exec-priority';
  const title=document.createElement('strong');title.textContent='Autonomia supervisionada';
  const detail=document.createElement('p');detail.textContent='Sem dados de supervisão nesta sessão.';
  const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Atualizar supervisão';
  box.append(title,detail,refresh);root.append(box);
  async function carregar(){
    if(!window.adminKeyAtual){detail.textContent='Sem dados — autentique-se para consultar.';return;}
    refresh.disabled=true;
    try{
      const r=await fetch('https://maranhao-cordial-api.onrender.com/api/admin/autonomia-supervisionada',
        {cache:'no-store',headers:{'X-Admin-Key':window.adminKeyAtual}});
      const d=await r.json();if(!r.ok || !d.success)throw new Error('sem dados');
      const registros=Array.isArray(d.registros)?d.registros:null;
      const soma=estado=>registros?registros.filter(r=>r.estado===estado).reduce((s,r)=>s+Number(r.quantidade),0):'sem dados';
      detail.textContent=`Política: ${d.politica?.versao || 'sem dados'}. Execução: ${d.execucao_habilitada===true && d.politica?.habilitada===true && d.pausado===false?'habilitada sob limites':'bloqueada'}. Reservadas: ${soma('reservada')}; aceitas pelo provedor: ${soma('enviada')}; incertas: ${soma('incerta')}. Próximo briefing: ${d.proximo_briefing?new Date(d.proximo_briefing).toLocaleString('pt-BR'):'sem dados'}. WhatsApp: bloqueado pela Meta.`;
    }catch{detail.textContent='Sem dados — não foi possível confirmar a supervisão.';}
    finally{refresh.disabled=false;}
  }
  refresh.addEventListener('click',carregar);window.addEventListener('admin-autorizado',carregar);
})();
