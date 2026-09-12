/* Monitor somente leitura. Não chama IA, aprovação ou transporte. */
(() => {
  const status=document.getElementById('whatsapp-omni-status');
  if(!status)return;
  const $=name=>document.getElementById('whatsapp-omni-'+name);
  const el=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
  async function load(){
    if(!window.adminKeyAtual)return;
    $('atualizar').disabled=true;
    try {
      const response=await fetch('https://maranhao-cordial-api.onrender.com/api/admin/omnichannel/whatsapp',{
        cache:'no-store',headers:{'X-Admin-Key':window.adminKeyAtual}});
      const data=await response.json();
      if(!response.ok || !data.success)throw new Error(data.error || 'Não foi possível consultar o WhatsApp.');
      status.textContent=`${data.conector.prontidao?.estado || data.conector.estado} · envio bloqueado. Aprovar uma resposta não envia mensagem.`;
      $('resumo').replaceChildren(el('p',Object.entries(data.processamentos).map(([k,v])=>`${k}: ${v}`).join(' · ') || 'Nenhuma entrada interna registrada.'));
      $('meta').replaceChildren(el('p',data.conector.verificacao_remota));
      for(const item of data.conector.dependencias_meta)$('meta').append(el('p',item));
      $('meta').append(el('p','Configuração ausente: '+(data.conector.faltantes.join(', ') || 'nenhum campo obrigatório ausente; validade externa ainda não confirmada')));
      $('entradas').replaceChildren();
      for(const row of data.entradas){
        const box=el('article','');box.style.margin='16px 0';
        box.append(el('strong',row.estado),el('p',row.texto || 'Evento de status da Meta'),
          el('p',`Classificação: ${row.classificacao || 'pendente'} · Contato CRM: ${row.lead_id || 'pendente'} · Resposta: ${row.resposta_status || 'ainda não proposta'}`),
          el('p',`Tentativas: ${row.tentativas} · Último erro: ${row.erro_tipo || 'nenhum'}`));
        if(row.resposta_sugerida)box.append(el('p','Sugestão para revisão: '+row.resposta_sugerida));
        const trace=el('details','');trace.append(el('summary','Rastreabilidade'));
        trace.append(el('p',`Entrada: ${row.chave} · Interação: ${row.interacao_id || 'pendente'} · Resposta: ${row.resposta_id || 'pendente'}`));
        for(const audit of [...data.auditoria,...(data.auditoria_respostas || [])].filter(a=>a.chave===row.chave))trace.append(el('p',`${audit.criado_em} · ${audit.etapa}`));
        box.append(trace);$('entradas').append(box);
      }
    }catch(error){status.textContent=error.message+' Envio continua bloqueado.';}
    finally{$('atualizar').disabled=false;}
  }
  $('atualizar').addEventListener('click',load);
  window.addEventListener('admin-autorizado',load);
})();
