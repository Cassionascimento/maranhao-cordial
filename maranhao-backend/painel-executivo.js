/* Projection only: no API calls, no commercial commands, no invented zeros. */
(() => {
  const stages = ['novo','qualificacao','degustacao','proposta','negociacao','cliente','perdido'];
  function model(state) {
    const crm = Array.isArray(state.crm) ? state.crm : null;
    const orders = Array.isArray(state.pedidos) ? state.pedidos : null;
    return {
      contatos: crm?.length ?? null,
      negociacoes: crm ? crm.filter(r => r.estagio === 'negociacao').length : null,
      clientes: crm ? crm.filter(r => r.estagio === 'cliente').length : null,
      pedidos: orders?.length ?? null,
      stages: stages.map(stage => ({stage, count: crm ? crm.filter(r => r.estagio === stage).length : null})),
      desconhecidos: crm ? crm.filter(r => !stages.includes(r.estagio)).length : null
    };
  }
  if (typeof module !== 'undefined') module.exports = {model};
  if (typeof document === 'undefined' || !document.getElementById('painel-executivo')) return;
  const state = {}, times = {};
  const $ = id => document.getElementById('exec-' + id);
  const el = (tag, text, cls) => {const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
  const fmt = value => value == null ? 'sem dados' : value.toLocaleString('pt-BR');
  function render() {
    const m=model(state);
    $('kpis').replaceChildren();
    for(const [label,key,note] of [['Contatos','contatos','Na consulta CRM recebida'],['Em negociação','negociacoes','Estágio registrado no CRM'],['Clientes','clientes','Classificados no CRM; não comprova receita'],['Pedidos','pedidos','Na consulta recebida; não comprova pagamento']]) {
      const card=el('article','','exec-kpi');card.append(el('span',label),el('strong',fmt(m[key])),el('small',note));$('kpis').append(card);
    }
    $('funil').replaceChildren();
    const labels={novo:'Novos',qualificacao:'Qualificação',degustacao:'Degustação',proposta:'Proposta',negociacao:'Negociação',cliente:'Clientes',perdido:'Perdidos'};
    for(const row of m.stages){const line=el('div','','exec-stage'),track=el('div','','exec-track'),fill=el('div','','exec-fill');fill.style.width=`${m.contatos ? row.count/m.contatos*100 : 0}%`;track.append(fill);line.append(el('span',labels[row.stage]),track,el('span',fmt(row.count)));$('funil').append(line);}
    $('funil').append(el('p',`Estágio não informado ou não reconhecido: ${fmt(m.desconhecidos)}.`, 'exec-muted'));
    $('atencao').replaceChildren();
    const priorities = m.contatos == null ? [['Carregar contexto comercial','Abra Contatos para consultar o CRM existente.','crm']] :
      [[m.negociacoes ? `${m.negociacoes} contatos em negociação` : 'Consultar oportunidades','Revisar os registros antes de decidir o próximo contato.','crm']];
    priorities.push(['Revisar aprovações','Consulte a fila existente. Quantidade e urgência não verificadas neste painel.','aprovacoes']);
    for(const [title,description,target] of priorities){const item=el('article','','exec-priority');const button=el('button','Abrir →');button.type='button';button.dataset.execTab=target;item.append(el('strong',title),el('p',description),button);$('atencao').append(item);}
    $('leitura').textContent=m.contatos == null ? 'Sem dados comerciais consultados nesta sessão. Carregue Contatos para obter uma leitura baseada no CRM.' :
      `A consulta reúne ${m.contatos} contatos, com ${m.negociacoes} em negociação e ${m.clientes} classificados como clientes. Receita, conversão por período e eficiência de investimento: sem dados neste painel. Esta leitura descreve a consulta, não o histórico completo.`;
    $('saude').replaceChildren();
    for(const [source,label] of [['crm','CRM'],['pedidos','Pedidos'],['externos','Canais externos']]){const item=el('article','');item.append(el('strong',label),el('small',times[source] ? `Dados recebidos às ${times[source]}. Disponibilidade atual não monitorada.` : 'Sem dados de saúde nesta sessão.'));$('saude').append(item);}
  }
  window.addEventListener('executivo-dados',event=>{const {fonte,dados}=event.detail || {};if(!['crm','pedidos'].includes(fonte))return;state[fonte]=dados;times[fonte]=Array.isArray(dados)?new Date().toLocaleTimeString('pt-BR'):null;render();});
  document.getElementById('painel-executivo').addEventListener('click',event=>{const button=event.target.closest('[data-exec-tab]');if(!button)return;const target=button.dataset.execTab;if(target==='aprovacoes'){document.getElementById('titulo-acoes-comerciais')?.scrollIntoView({behavior:'smooth'});return;}document.querySelector(`.admin-tab[data-tab="${target}"]`)?.click();});
  render();
})();
