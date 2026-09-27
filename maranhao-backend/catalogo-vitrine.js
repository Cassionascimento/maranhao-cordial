/* Vitrine pública "Produtos da Maranhão" (página inicial). Busca
 * /api/catalogo/produtos (só produtos publicados/em breve — rascunho nunca
 * chega aqui, isso é decidido pelo servidor) e desenha os cartões. O
 * layout funciona igual com um produto só ou com vários.
 *
 * Lógica pura (o que decide o link e o rótulo de cada cartão) fica em
 * funções exportadas, testáveis sem DOM.
 */
(function (raiz) {
  'use strict';

  function formatarPreco(centavos) {
    if (centavos == null) return null;
    return (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  }

  /* Para onde o cartão leva: só a modalidade "comprar_site" pula direto
   * para uma compra já funcional (a da própria bebida, por exemplo).
   * Orçamento e "em breve" sempre passam pela página do produto, que
   * explica o item antes de qualquer contato. */
  function linkDoProduto(produto) {
    if (produto.modalidade_compra === 'comprar_site' && produto.url_compra) return produto.url_compra;
    return '/produto/' + encodeURIComponent(produto.slug);
  }

  function rotuloDoProduto(produto) {
    if (produto.status === 'em_breve' || produto.modalidade_compra === 'em_breve') return 'Em breve';
    if (produto.modalidade_compra === 'comprar_site') return 'Ver produto';
    return 'Solicitar orçamento';
  }

  function capaDoProduto(produto) {
    var capa = (produto.midias || []).find(function (m) { return m.tipo === 'imagem' && m.capa; }) ||
      (produto.midias || []).find(function (m) { return m.tipo === 'imagem'; });
    return capa || null;
  }

  var api = { formatarPreco: formatarPreco, linkDoProduto: linkDoProduto, rotuloDoProduto: rotuloDoProduto, capaDoProduto: capaDoProduto };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var grade = doc.getElementById('mc-produtos-grid');
  if (!grade) return;

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function el(tag, attrs, filhos) {
    var n = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'texto') n.textContent = attrs[k]; else if (k === 'classe') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (filhos || []).forEach(function (f) { if (f) n.appendChild(f); });
    return n;
  }

  function cartao(produto) {
    var emBreve = produto.status === 'em_breve' || produto.modalidade_compra === 'em_breve';
    var capa = capaDoProduto(produto);
    var filhos = [];
    if (capa) filhos.push(el('img', { src: capa.url, alt: capa.alt_text || produto.nome, loading: 'lazy' }));
    filhos.push(el('h3', { texto: produto.nome }));
    filhos.push(el('p', { texto: produto.descricao_curta }));
    var preco = formatarPreco(produto.preco_centavos);
    if (preco) filhos.push(el('p', { classe: 'mc-produto-preco', texto: 'A partir de ' + preco }));
    filhos.push(el('span', { classe: 'mc-produto-badge', texto: rotuloDoProduto(produto) }));
    // "Em breve" continua levando à página do produto (informativa); é
    // produto.html/produto-pagina.js quem garante que ela nunca oferece
    // pagamento para esse status.
    return el('a', { classe: 'mc-produto-card' + (emBreve ? ' em-breve' : ''), href: linkDoProduto(produto) }, filhos);
  }

  raiz.fetch('/api/catalogo/produtos', { credentials: 'omit' })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('falha')); })
    .then(function (dados) {
      var produtos = (dados && dados.produtos) || [];
      grade.textContent = '';
      if (!produtos.length) {
        grade.appendChild(el('p', { classe: 'mc-produtos-vazio', texto: 'Em breve, novos produtos por aqui.' }));
        return;
      }
      produtos.forEach(function (p) { grade.appendChild(cartao(p)); });
    })
    .catch(function () {
      grade.textContent = '';
      grade.appendChild(el('p', { classe: 'mc-produtos-erro', texto: 'Não foi possível carregar os produtos agora.' }));
    });
})(typeof window !== 'undefined' ? window : globalThis);
