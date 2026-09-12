/* Espelho somente leitura: nenhuma publicação ou execução comercial. */
(() => {
  const box = document.getElementById('tiktok-shop-dados');
  if (!box) return;
  const status = document.getElementById('tiktok-shop-status');
  const button = document.getElementById('tiktok-shop-atualizar');
  const node = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  async function load() {
    if (!window.adminKeyAtual) return;
    button.disabled = true;
    try {
      const response = await fetch('https://maranhao-cordial-api.onrender.com/api/admin/tiktok-shop', {
        cache: 'no-store', headers: {'X-Admin-Key': window.adminKeyAtual}
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Consulta indisponível.');
      status.textContent = `${data.estado} · automações comerciais bloqueadas`;
      box.replaceChildren(node('p', 'Últimos 100 registros. Campos ausentes: desconhecidos.'));
      for (const row of data.fatos) {
        const detail = node('details', '');
        detail.append(node('summary', `${row.tipo} · ${row.loja} · ${row.externo_id}`),
          node('pre', JSON.stringify(row.dados, null, 2)),
          node('p', `CRM: ${row.lead_id || 'não associado'} · origem: ${row.origem} · versão: ${row.versao}`));
        for (const h of data.historico.filter(h => h.loja === row.loja && h.tipo === row.tipo && h.externo_id === row.externo_id))
          detail.append(node('p', `Registro ${h.id} · versão ${h.versao} · ${h.registrado_em}`));
        box.append(detail);
      }
      if (!data.fatos.length) box.append(node('p', 'Nenhum dado Shop importado.'));
      for (const gap of data.lacunas) box.append(node('p', gap));
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  }
  button.addEventListener('click', load);
  window.addEventListener('admin-autorizado', load);
})();
