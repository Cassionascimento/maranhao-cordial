/* Captura de sinais do site (ETAPA 5.4B) -- ativa o backend
   POST /api/site/sinal já existente (site_sinais.py, ETAPA 5.4). Nenhum
   endpoint novo, nenhum motor novo: só o cliente que faltava.

   Regra absoluta: nunca envia nada sem window.MCConsentimento.aceito()
   ser true no momento exato do envio -- não há cache de "já verifiquei
   antes". Se o consentimento for revogado, o token anônimo local é
   apagado na hora (ouve 'mc-consentimento-mudou'), então mesmo uma
   chamada tardia não teria mais o que enviar como identificador.

   Nunca captura nome, e-mail, telefone ou qualquer texto livre digitado
   pelo visitante -- só os tipos/produtos/CTAs fixos que o backend aceita
   (site_sinais.TIPOS_SINAL/PRODUTOS). Degustação e B2B continuam sendo
   capturados do jeito que já eram (formulário -> main.py -> mi_sinais),
   com o consentimento específico do próprio formulário -- não passam por
   aqui e não dependem deste banner. */
(() => {
  'use strict';
  const CHAVE_TOKEN = 'mc_visitante_anonimo';
  const API = window.MC_API_BASE || 'https://maranhao-cordial-api.onrender.com';

  function temTokenSalvo() {
    try { return !!localStorage.getItem(CHAVE_TOKEN); } catch { return false; }
  }

  function tokenAnonimo() {
    try {
      let token = localStorage.getItem(CHAVE_TOKEN);
      if (token) return token;
      token = (crypto.randomUUID ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2)))
        .replace(/[^a-z0-9-]/g, '').slice(0, 64);
      localStorage.setItem(CHAVE_TOKEN, token);
      return token;
    } catch {
      return null;
    }
  }

  function apagarToken() {
    try { localStorage.removeItem(CHAVE_TOKEN); } catch { /* nada a apagar */ }
  }

  function enviar(tipo, extra) {
    if (!window.MCConsentimento || !window.MCConsentimento.aceito()) return;
    const corpo = Object.assign({ tipo, consentimento: true }, extra || {});
    const anonimo = tokenAnonimo();
    if (anonimo) corpo.visitante_anonimo = anonimo;
    try {
      fetch(API + '/api/site/sinal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
        keepalive: true,
      }).catch(() => {});
    } catch { /* navegador sem fetch: silenciosamente não captura */ }
  }

  const MCSinaisSite = {
    paginaVisitada() {
      const retorno = temTokenSalvo();
      enviar('pagina_visitada');
      if (retorno) enviar('retorno_visitante');
    },
    produtoVisitado(produto) { enviar('produto_visitado', { produto }); },
    ctaClicado(cta) { enviar('cta_clicado', { cta }); },
    intencaoContato() { enviar('intencao_contato'); },
  };

  window.MCSinaisSite = MCSinaisSite;

  window.addEventListener('mc-consentimento-mudou', (evento) => {
    if (evento.detail && evento.detail.aceito) {
      MCSinaisSite.paginaVisitada();
    } else {
      apagarToken();
    }
  });

  if (window.MCConsentimento && window.MCConsentimento.aceito()) {
    MCSinaisSite.paginaVisitada();
  }

  // Delegado e genérico: qualquer página só precisa marcar o elemento com
  // data-mc-cta="<codigo>" (e opcionalmente data-mc-produto="guarana|acai|
  // bacuri") -- nenhuma página precisa de JS próprio para ativar a captura.
  document.addEventListener('click', (evento) => {
    const alvo = evento.target.closest('[data-mc-cta], [data-mc-produto]');
    if (!alvo) return;
    if (alvo.dataset.mcCta) MCSinaisSite.ctaClicado(alvo.dataset.mcCta);
    if (alvo.dataset.mcProduto) MCSinaisSite.produtoVisitado(alvo.dataset.mcProduto);
  });
})();
