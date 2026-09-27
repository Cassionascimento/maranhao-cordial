/* Página genérica de produto (/produto/<slug>). Um único arquivo serve
 * qualquer produto cadastrado -- o conteúdo vem inteiro de
 * /api/catalogo/produtos/<slug>. Sem checkout próprio: "comprar_site"
 * só existe quando o produto já aponta para uma compra funcional
 * (url_compra); "orcamento" reaproveita a solicitação de orçamento que
 * já existe; "em_breve" nunca oferece pagamento.
 */
(function (raiz) {
  'use strict';

  function slugDaUrl(caminho) {
    var m = /^\/produto\/([^\/?#]+)\/?$/.exec(caminho || '');
    return m ? decodeURIComponent(m[1]).trim().toLowerCase() : null;
  }

  function linkOrcamento(slug) {
    return '/cadastro-profissional?origem=' + encodeURIComponent('orcamento_' + slug);
  }

  function rotuloCTA(produto) {
    if (produto.modalidade_compra === 'em_breve') return null;
    if (produto.modalidade_compra === 'comprar_site') return 'Comprar';
    return 'Solicitar orçamento';
  }

  function hrefCTA(produto) {
    if (produto.modalidade_compra === 'comprar_site') return produto.url_compra;
    if (produto.modalidade_compra === 'orcamento') return linkOrcamento(produto.slug);
    return null;
  }

  var api = { slugDaUrl: slugDaUrl, linkOrcamento: linkOrcamento, rotuloCTA: rotuloCTA, hrefCTA: hrefCTA };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var raizEl = doc.getElementById('raiz');
  if (!raizEl) return;

  function el(tag, attrs, filhos) {
    var n = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'texto') n.textContent = attrs[k]; else if (k === 'classe') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (filhos || []).forEach(function (f) { if (f) n.appendChild(f); });
    return n;
  }

  function formatarPreco(centavos) {
    if (centavos == null) return null;
    return (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  }

  function mostrar(nos) { raizEl.textContent = ''; nos.forEach(function (n) { raizEl.appendChild(n); }); }

  function naoEncontrado() {
    doc.title = 'Produto não encontrado — Maranhão Cordial';
    mostrar([el('div', { classe: 'pr-erro' }, [
      el('h1', { texto: 'Este produto não está disponível.' }),
      el('p', { texto: 'Ele pode ter sido despublicado ou o endereço está incorreto.' })])]);
  }

  var slug = slugDaUrl(raiz.location.pathname);
  if (!slug) { naoEncontrado(); return; }

  raiz.fetch('/api/catalogo/produtos/' + encodeURIComponent(slug), { credentials: 'omit' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (dados) {
      if (!dados || !dados.success) return naoEncontrado();
      montar(dados.produto);
    })
    .catch(naoEncontrado);

  function montar(produto) {
    doc.title = produto.nome + ' — Maranhão Cordial';

    var capa = (produto.midias || []).find(function (m) { return m.capa; }) || (produto.midias || [])[0];
    var midiaNo;
    if (capa && capa.tipo === 'video') {
      midiaNo = el('video', { src: capa.url, muted: 'muted', loop: 'loop', playsinline: 'playsinline', autoplay: 'autoplay', 'aria-label': produto.nome });
    } else if (capa) {
      midiaNo = el('img', { src: capa.url, alt: capa.alt_text || produto.nome, loading: 'eager' });
    }

    var ficha = [];
    [['Volume', produto.volume], ['Peso', produto.peso], ['Composição', produto.composicao], ['Cuidados', produto.cuidados],
     ['Unidade de venda', produto.unidade_venda]].forEach(function (par) {
      if (par[1]) ficha.push(el('li', {}, [el('b', { texto: par[0] + ': ' }), doc.createTextNode(par[1])]));
    });

    var corpo = [
      el('div', { classe: 'pr-corpo' }, [
        el('div', { classe: 'pr-midia' }, [midiaNo]),
        el('div', {}, [
          el('p', { classe: 'pr-eyebrow', texto: produto.categoria }),
          el('h1', { texto: produto.nome }),
          produto.disponibilidade ? el('span', { classe: 'pr-disponibilidade', texto: produto.disponibilidade }) : null,
          (function () { var p = formatarPreco(produto.preco_centavos); return p ? el('p', { classe: 'pr-preco', texto: 'A partir de ' + p }) : null; })(),
          el('p', { classe: 'pr-curta', texto: produto.descricao_curta }),
          produto.descricao_completa ? el('p', { classe: 'pr-completa', texto: produto.descricao_completa }) : null,
          ficha.length ? el('ul', { classe: 'pr-ficha' }, ficha) : null,
          botaoOuAviso(produto),
        ]),
      ]),
    ];
    mostrar(corpo);
  }

  function botaoOuAviso(produto) {
    var rotulo = rotuloCTA(produto);
    if (!rotulo) return el('p', { classe: 'pr-embreve', texto: 'Em breve, sem possibilidade de pagamento no momento.' });
    var href = hrefCTA(produto);
    if (!href) return el('p', { classe: 'pr-embreve', texto: 'Consulte disponibilidade em breve.' });
    return el('a', { classe: 'pr-cta', href: href, texto: rotulo });
  }
})(typeof window !== 'undefined' ? window : globalThis);
