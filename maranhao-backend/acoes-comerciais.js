/* Somente leitura e decisão; aprovar nunca chama transporte. */
(() => {
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/acoes-comerciais';
  const status = document.getElementById('status-acoes-comerciais');
  const lista = document.getElementById('lista-acoes-comerciais');
  function elemento(tag, texto) {
    const e = document.createElement(tag); e.textContent = texto; return e;
  }
  async function chamada(url, options = {}) {
    if (!window.adminKeyAtual) throw new Error('Entre no painel para consultar ações.');
    const r = await fetch(url, {...options, cache: 'no-store', headers: {
      'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json'
    }});
    if (!r.ok) throw new Error('Não foi possível confirmar a operação. Atualize antes de tentar novamente.');
    return r.json();
  }
  async function carregar() {
    status.textContent = 'Carregando ações…'; lista.replaceChildren();
    try {
      const dados = await chamada(api);
      const pendentes = dados.acoes.filter(a => a.status === 'aguardando_aprovacao');
      status.textContent = pendentes.length ? `${pendentes.length} ações para sua decisão.` : 'Nenhuma ação aguardando aprovação.';
      for (const a of pendentes) {
        const d = a.dados, card = elemento('article', ''); card.className = 'card';
        card.append(elemento('h3', d.empresa), elemento('p', `${d.contato || d.destinatario} | ${d.canal}`),
          elemento('p', d.motivo));
        const mensagem = elemento('p', d.mensagem); mensagem.style.whiteSpace = 'pre-wrap'; card.append(mensagem);
        const botoes = [];
        for (const [rotulo, decisao] of [['Aprovar', 'aprovar'], ['Rejeitar', 'rejeitar']]) {
          const b = elemento('button', rotulo); b.type = 'button'; botoes.push(b);
          b.addEventListener('click', async () => {
            botoes.forEach(x => {x.disabled = true;});
            try {
              await chamada(`${api}/${a.id}/decisao`, {method: 'POST', body: JSON.stringify({decisao, digest: a.digest})});
              await carregar();
            } catch (e) { status.textContent = e.message; }
          }); card.append(b);
        }
        const detalhe = elemento('details', ''); detalhe.append(elemento('summary', 'Ver detalhes'));
        const origens = {prospecto_fase56: 'Parceiro técnico — Fase 5.6', prospecto_fase57: 'Prospecção — Fase 5.7'};
        detalhe.append(elemento('p', `Origem: ${origens[a.origem_tipo] || a.origem_tipo || 'Não informada'} | ${a.origem_id || 'Não informado'}`));
        const pre = elemento('pre', JSON.stringify(a, null, 2)); pre.style.whiteSpace = 'pre-wrap'; pre.style.overflowWrap = 'anywhere';
        detalhe.append(pre); card.append(detalhe); lista.append(card);
      }
    } catch(e) {status.textContent = e.message;}
  }
  document.getElementById('atualizar-acoes-comerciais').addEventListener('click', carregar);
  window.addEventListener('admin-autorizado', carregar);
})();
