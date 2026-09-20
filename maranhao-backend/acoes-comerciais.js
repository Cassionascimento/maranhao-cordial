/* Somente leitura e decisão; aprovar nunca chama transporte. */
(() => {
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/acoes-comerciais';
  const status = document.getElementById('status-acoes-comerciais');
  const lista = document.getElementById('lista-acoes-comerciais');
  function elemento(tag, texto) {
    const e = document.createElement(tag); e.textContent = texto; return e;
  }
  function linhaRotulada(rotulo, valor) {
    const p = elemento('p', ''); p.className = 'acao-linha';
    const marca = elemento('span', rotulo); marca.className = 'acao-rotulo';
    p.append(marca, elemento('span', valor == null ? '—' : String(valor)));
    return p;
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
        const d = a.dados, card = elemento('article', ''); card.className = 'card acao-aprovacao';
        // Revisão compacta: para quem, por quê, o que será feito e qual é o
        // efeito de aprovar. A decisão enviada continua a mesma (decisão +
        // digest) -- nenhum campo novo, nenhum contrato alterado.
        card.append(
          elemento('h3', d.empresa),
          linhaRotulada('Para quem', `${d.contato || d.destinatario} · ${d.canal}`),
          linhaRotulada('Por quê', d.motivo)
        );
        const rotuloMensagem = elemento('p', 'O que será feito');
        rotuloMensagem.className = 'acao-rotulo-bloco';
        const mensagem = elemento('p', d.mensagem);
        mensagem.style.whiteSpace = 'pre-wrap'; mensagem.className = 'acao-mensagem';
        card.append(rotuloMensagem, mensagem);
        card.append(linhaRotulada('Efeito de aprovar',
          'registra a decisão. O envio é um passo separado e auditado — nada sai por este botão.'));
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
        const origens = {prospecto_fase56: 'Parceiro técnico', prospecto_fase57: 'Prospecção de contatos'};
        detalhe.append(elemento('p', `Origem: ${origens[a.origem_tipo] || a.origem_tipo || 'Não informada'} | ${a.origem_id || 'Não informado'}`));
        const pre = elemento('pre', JSON.stringify(a, null, 2)); pre.style.whiteSpace = 'pre-wrap'; pre.style.overflowWrap = 'anywhere';
        detalhe.append(pre); card.append(detalhe); lista.append(card);
      }
    } catch(e) {status.textContent = e.message;}
  }
  document.getElementById('atualizar-acoes-comerciais').addEventListener('click', carregar);
  window.addEventListener('admin-autorizado', carregar);
})();
