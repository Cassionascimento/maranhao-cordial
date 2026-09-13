/* Consentimento mínimo de privacidade (ETAPA 5.4B; GA4 alinhado na 5.4C).
   Auditoria: o site não tinha nenhum banner de cookies/consentimento --
   só checkboxes de formulário (degustação/B2B), que autorizam contato
   comercial, não navegação/analytics. Este continua sendo o único banner
   do site; a 5.4C não cria um segundo -- só faz o GA4 (Google Consent
   Mode) escutar a MESMA decisão.

   Guarda a decisão em localStorage (só neste navegador, nunca enviada a
   nenhum servidor). window.MCConsentimento é a única fonte de verdade;
   site-sinais.js e o Consent Mode do GA4 (abaixo) consultam/escutam esta
   mesma decisão -- nenhum dos dois guarda seu próprio estado. */
(() => {
  'use strict';
  const CHAVE = 'mc_consentimento';

  function status() {
    try { return localStorage.getItem(CHAVE); } catch { return null; }
  }
  function aceito() { return status() === 'aceito'; }

  // Google Consent Mode: cada página já declara 'analytics_storage':'denied'
  // por padrão, antes do gtag.js carregar (ver index.html/raizes.html/
  // entrega.html/deposito.html) -- aqui só ATUALIZAMOS esse estado para a
  // decisão real, sem criar nenhum mecanismo de consentimento novo.
  function sincronizarConsentModeGA4(estaAceito) {
    if (typeof window.gtag !== 'function') return;
    window.gtag('consent', 'update', { analytics_storage: estaAceito ? 'granted' : 'denied' });
  }

  function definir(valor) {
    try { localStorage.setItem(CHAVE, valor); } catch { /* navegação sem storage: decisão não persiste, mas nada é capturado nesta sessão */ }
    esconderBanner();
    sincronizarConsentModeGA4(valor === 'aceito');
    window.dispatchEvent(new CustomEvent('mc-consentimento-mudou', { detail: { aceito: valor === 'aceito' } }));
  }
  const aceitar = () => definir('aceito');
  const recusar = () => definir('recusado');

  let bannerEl = null;

  function criarBanner() {
    const div = document.createElement('div');
    div.id = 'mc-consentimento-banner';
    div.setAttribute('role', 'dialog');
    div.setAttribute('aria-label', 'Preferências de privacidade');

    const texto = document.createElement('p');
    texto.textContent = 'Usamos dados de navegação (páginas e produtos vistos, cliques) para entender o interesse do público e orientar a Maranhão Intelligence. Não exigimos nome, e-mail ou telefone para isso, e você pode mudar de ideia quando quiser. ';
    const link = document.createElement('a');
    link.href = 'politica-de-privacidade.html';
    link.textContent = 'Saiba mais';
    texto.append(link);

    const botoes = document.createElement('div');
    botoes.className = 'mc-consentimento-botoes';
    const btnRecusar = document.createElement('button');
    btnRecusar.type = 'button';
    btnRecusar.textContent = 'Recusar';
    btnRecusar.addEventListener('click', recusar);
    const btnAceitar = document.createElement('button');
    btnAceitar.type = 'button';
    btnAceitar.className = 'mc-consentimento-aceitar';
    btnAceitar.textContent = 'Aceitar';
    btnAceitar.addEventListener('click', aceitar);
    botoes.append(btnRecusar, btnAceitar);

    div.append(texto, botoes);
    document.body.appendChild(div);
    return div;
  }

  function mostrarBanner() {
    if (!bannerEl) bannerEl = criarBanner();
    bannerEl.hidden = false;
  }
  function esconderBanner() {
    if (bannerEl) bannerEl.hidden = true;
  }

  window.MCConsentimento = {
    status, aceito, aceitar, recusar,
    abrirPreferencias: mostrarBanner,
  };

  const decisaoAtual = status();
  if (decisaoAtual === null) {
    mostrarBanner();
  } else {
    // O default de cada página é sempre 'denied' até esta chamada -- uma
    // decisão de visita anterior precisa ser reaplicada a cada carregamento.
    sincronizarConsentModeGA4(decisaoAtual === 'aceito');
  }
})();
