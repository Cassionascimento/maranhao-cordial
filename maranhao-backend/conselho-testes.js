/* Testing Center -- bateria repetível dos 8 agentes. Casos unitários (schema,
   proveniência, fato x estimativa, ação já em andamento, divergência real,
   motivo do Diretor, guardrail de veto) rodam grátis e instantâneos; casos
   "ao vivo" (Rua/Iris/Marie isolados + execução conjunta) só rodam quando o
   Diretor pede explicitamente, porque consomem tokens reais. Nenhum caso
   executa ação externa (WhatsApp/Gmail/Pix) -- o próprio Conselho é modo
   observador por natureza. */
(() => {
  'use strict';
  const panel = document.getElementById('conselho-testes-painel');
  if (!panel) return;
  const api = 'https://maranhao-cordial-api.onrender.com/api/admin/mi/conselho/testes/executar';
  const $ = id => document.getElementById('conselho-testes-' + id);
  const authHeaders = extra => Object.assign({ 'X-Admin-Key': window.adminKeyAtual || '' }, extra || {});
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };

  async function rodar(incluirAoVivo) {
    if (!window.adminKeyAtual) { $('status').textContent = 'Entre no Admin para rodar os testes.'; return; }
    $('status').textContent = incluirAoVivo ? 'Rodando bateria completa (chamadas reais em andamento)...' : 'Rodando bateria unitária...';
    $('conteudo').hidden = true;
    try {
      const resp = await fetch(api, {
        method: 'POST', cache: 'no-store',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ incluir_ao_vivo: incluirAoVivo }),
      });
      const body = await resp.json();
      if (!resp.ok || !body.success) throw new Error(body.error || 'Falha ao rodar a bateria de testes.');
      renderizar(body);
      $('status').textContent = body.aprovados + '/' + body.total + ' casos aprovados.';
    } catch (erro) {
      $('status').textContent = erro.message || 'Não foi possível rodar a bateria de testes.';
    }
  }

  function renderizar(body) {
    const raiz = $('conteudo');
    raiz.replaceChildren();
    raiz.hidden = false;

    const resumo = el('p', body.aprovados + ' de ' + body.total + ' casos aprovados (' + body.falharam + ' falharam).', 'mi-resumo-testes');
    raiz.append(resumo);

    ['unitario', 'ao_vivo'].forEach(grupo => {
      const casos = body.resultados.filter(r => r.grupo === grupo);
      if (!casos.length) return;
      const titulo = el('h4', grupo === 'unitario' ? 'Casos unitários (sem custo)' : 'Casos ao vivo (chamada real à OpenAI)');
      raiz.append(titulo);
      const lista = el('ul', undefined, 'conselho-testes-lista');
      casos.forEach(r => {
        const item = el('li', undefined, r.passou ? 'conselho-teste-ok' : 'conselho-teste-falhou');
        item.append(el('strong', r.passou ? 'APROVADO' : 'FALHOU'));
        item.append(el('span', ' — ' + r.descricao));
        if (r.motivo) item.append(el('div', r.motivo, 'conselho-teste-motivo'));
        lista.append(item);
      });
      raiz.append(lista);
    });
  }

  $('rodar').addEventListener('click', () => rodar(false));
  $('rodar-ao-vivo').addEventListener('click', () => {
    if (window.confirm('Os casos ao vivo chamam a OpenAI de verdade (Rua, Iris, Marie isolados + execução conjunta) e consomem tokens reais. Continuar?')) {
      rodar(true);
    }
  });
})();
