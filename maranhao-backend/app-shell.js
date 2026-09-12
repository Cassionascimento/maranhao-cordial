/* Estrutura/navegação/apresentação global do shell administrativo.
   Nenhuma lógica de negócio, nenhuma chamada de rede, nenhum toque em
   login/gating aqui — só observa o que já existe na página para dar um
   sinal visual discreto. */
(() => {
  'use strict';
  const abaGovernanca = document.querySelector('.admin-tab[data-tab="governanca"]');
  const statusAcoes = document.getElementById('status-acoes-comerciais');
  if (!abaGovernanca || !statusAcoes) return;

  function avaliarPendencias() {
    const texto = statusAcoes.textContent || '';
    const match = texto.match(/^(\d+)\s+ações?/);
    const pendentes = match ? Number(match[1]) : 0;
    abaGovernanca.classList.toggle('app-shell-alerta', pendentes > 0);
  }

  new MutationObserver(avaliarPendencias).observe(statusAcoes, {
    childList: true,
    characterData: true,
    subtree: true,
  });
  avaliarPendencias();
})();

/* Sidebar desktop (ETAPA 4.7). Gerada a partir de #adminTabs -- única fonte
   de verdade, nada duplicado em HTML. Cada item só encaminha o clique para
   o .admin-tab real (mesmo padrão já usado por data-exec-tab/data-vg-tab);
   nenhuma lógica de troca de painel é reimplementada aqui. A fileira de
   abas legada não é removida, só fica oculta via CSS (>=1024px) enquanto a
   sidebar está ativa -- reversível, sem duplicar navegação funcional. */
(() => {
  'use strict';
  const nav = document.getElementById('adminTabs');
  if (!nav) return;
  const grupos = [...nav.querySelectorAll('.app-shell-grupo')];
  if (!grupos.length) return;

  const sidebar = document.createElement('nav');
  sidebar.className = 'app-sidebar';
  sidebar.setAttribute('aria-label', 'Navegação principal');

  const marca = document.createElement('div');
  marca.className = 'app-sidebar-marca';
  marca.textContent = 'Maranhão Cordial';
  sidebar.append(marca);

  const botoesPorTab = new Map();

  for (const grupo of grupos) {
    const tituloTexto = grupo.querySelector('.app-shell-grupo-titulo')?.textContent || '';
    const bloco = document.createElement('div');
    bloco.className = 'app-sidebar-grupo';
    const tituloEl = document.createElement('p');
    tituloEl.className = 'app-sidebar-grupo-titulo';
    tituloEl.textContent = tituloTexto;
    bloco.append(tituloEl);

    for (const tab of grupo.querySelectorAll('.admin-tab')) {
      const destino = tab.dataset.tab;
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'app-sidebar-item' + (tab.classList.contains('active') ? ' active' : '');
      item.textContent = tab.textContent;
      item.dataset.tab = destino;
      item.addEventListener('click', () => tab.click());
      botoesPorTab.set(destino, item);
      bloco.append(item);
    }
    sidebar.append(bloco);
  }

  document.body.insertBefore(sidebar, document.body.firstChild);
  document.body.classList.add('app-shell-sidebar-ativa');

  function sincronizarAtivo() {
    for (const [destino, item] of botoesPorTab) {
      const original = nav.querySelector(`.admin-tab[data-tab="${destino}"]`);
      item.classList.toggle('active', !!original && original.classList.contains('active'));
    }
  }

  new MutationObserver(sincronizarAtivo).observe(nav, {
    attributes: true,
    attributeFilter: ['class'],
    subtree: true,
  });
})();
