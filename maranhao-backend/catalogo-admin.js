/* Painel "Catálogo" do ADM: cadastrar, editar, publicar/despublicar e
 * gerenciar mídia de produtos sem programar. Vive no seu próprio
 * data-panel="catalogo" (não é sub-vista de outro painel).
 */
(function (raiz) {
  'use strict';

  var MODALIDADES = { comprar_site: 'Compra pelo site', orcamento: 'Solicitação de orçamento', em_breve: 'Em breve' };
  var STATUS = { rascunho: 'Rascunho', publicado: 'Publicado', em_breve: 'Em breve' };

  function centavosParaReais(c) { return c == null ? '' : (c / 100).toFixed(2).replace('.', ','); }
  function reaisParaCentavos(v) {
    v = (v || '').trim();
    if (!v) return null;
    var normalizado = v.replace(/\./g, '').replace(',', '.');
    var numero = Number(normalizado);
    if (!isFinite(numero) || numero < 0) return undefined; // undefined = inválido
    return Math.round(numero * 100);
  }
  function slugSugerido(nome) {
    return (nome || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
  }

  var api = { centavosParaReais: centavosParaReais, reaisParaCentavos: reaisParaCentavos, slugSugerido: slugSugerido };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var painel = doc.getElementById('catalogo-painel');
  if (!painel) return;
  var BASE = 'https://maranhao-cordial-api.onrender.com';
  var carregado = false;
  var editandoId = null;

  function chamar(caminho, opcoes) {
    if (!raiz.adminKeyAtual) return Promise.reject(new Error('Entre no Admin para gerenciar o catálogo.'));
    opcoes = opcoes || {};
    var cab = { 'X-Admin-Key': raiz.adminKeyAtual };
    if (opcoes.corpo) cab['Content-Type'] = 'application/json';
    return raiz.fetch(BASE + caminho, {
      method: opcoes.metodo || 'GET', cache: 'no-store', headers: cab,
      body: opcoes.corpo ? JSON.stringify(opcoes.corpo) : opcoes.formData,
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.campo ? 'Confira o campo: ' + j.campo : (j.error || 'Falha ' + r.status)); e.dados = j; throw e; }
        return j;
      });
    });
  }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function montarShell() {
    painel.innerHTML =
      '<div class="cat-topo"><div><h2>Catálogo de produtos</h2>' +
      '<p>Cadastre, edite, publique e despublique produtos. Ao publicar, o item aparece automaticamente no catálogo e, se marcado como destaque, na página inicial — sem precisar mexer em código.</p></div>' +
      '<button type="button" class="cat-btn cat-btn--primario" id="cat-novo">Novo produto</button></div>' +
      '<p id="cat-status" class="cat-status" role="status" aria-live="polite"></p>' +
      '<div id="cat-tabela"></div>' +
      '<form id="cat-form" class="cat-form" novalidate></form>';
    $('cat-novo').addEventListener('click', function () { abrirFormulario(null); });
    montarFormulario();
  }

  function $(id) { return doc.getElementById(id); }

  function status(t) { $('cat-status').textContent = t || ''; }

  function carregar() {
    status('Consultando…');
    Promise.all([chamar('/api/admin/catalogo/produtos'), chamar('/api/admin/catalogo/categorias')])
      .then(function (r) {
        desenharTabela(r[0].produtos);
        var lista = $('cat-categorias-lista');
        if (lista) lista.innerHTML = r[1].categorias.map(function (c) { return '<option value="' + esc(c) + '">'; }).join('');
        carregado = true;
        status('Atualizado às ' + new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) + '.');
      })
      .catch(function (e) { status(e.message); });
  }

  function capaDe(produto) {
    return (produto.midias || []).find(function (m) { return m.capa; }) || (produto.midias || [])[0];
  }

  function desenharTabela(produtos) {
    if (!produtos.length) { $('cat-tabela').innerHTML = '<p class="mic-note">Nenhum produto cadastrado ainda.</p>'; return; }
    var linhas = produtos.map(function (p) {
      var capa = capaDe(p);
      var thumb = capa ? '<img class="cat-thumb" src="' + esc(capa.url) + '" alt="">' : '<div class="cat-thumb"></div>';
      var preco = p.preco_centavos == null ? '—' : 'R$ ' + centavosParaReais(p.preco_centavos);
      return '<tr data-id="' + esc(p.id) + '">' +
        '<td>' + thumb + '</td>' +
        '<td><b>' + esc(p.nome) + '</b><small>/produto/' + esc(p.slug) + '</small></td>' +
        '<td>' + esc(p.categoria) + '</td>' +
        '<td><span class="cat-badge ' + esc(p.status) + '">' + esc(STATUS[p.status] || p.status) + '</span></td>' +
        '<td>' + esc(MODALIDADES[p.modalidade_compra] || p.modalidade_compra) + '</td>' +
        '<td>' + preco + '</td>' +
        '<td>' + (p.destaque_home ? 'Sim' : 'Não') + '</td>' +
        '<td>' +
          '<button type="button" class="cat-btn" data-acao="editar">Editar</button>' +
          publicarBotoes(p) +
          '<button type="button" class="cat-btn" data-acao="midias">Mídias (' + (p.midias || []).length + ')</button>' +
        '</td></tr>' +
        '<tr class="cat-midias-linha" data-midias-de="' + esc(p.id) + '"><td colspan="8">' +
          '<div class="cat-midias" id="cat-midias-' + esc(p.id) + '"></div>' +
          formularioUpload(p.id) +
        '</td></tr>';
    }).join('');
    $('cat-tabela').innerHTML = '<div class="table-wrap"><table><thead><tr>' +
      '<th></th><th>Produto</th><th>Categoria</th><th>Status</th><th>Modalidade</th><th>Preço</th><th>Destaque</th><th>Ações</th>' +
      '</tr></thead><tbody>' + linhas + '</tbody></table></div>';

    produtosPorId = {};
    produtos.forEach(function (p) { produtosPorId[p.id] = p; });
    ligarAcoesTabela();
  }

  function publicarBotoes(p) {
    var b = '';
    if (p.status !== 'publicado') b += '<button type="button" class="cat-btn" data-acao="publicar">Publicar</button>';
    if (p.status !== 'rascunho') b += '<button type="button" class="cat-btn" data-acao="rascunho">Despublicar</button>';
    if (p.status !== 'em_breve') b += '<button type="button" class="cat-btn" data-acao="em_breve">Marcar "Em breve"</button>';
    return b;
  }

  function formularioUpload(id) {
    return '<form class="cat-upload" data-upload-de="' + esc(id) + '">' +
      '<label>Arquivo <input type="file" name="arquivo" accept="image/png,image/jpeg,image/webp,video/mp4" required></label>' +
      '<label>Tipo <select name="tipo"><option value="imagem">Imagem</option><option value="video">Vídeo</option></select></label>' +
      '<label>Texto alternativo <input type="text" name="alt_text" maxlength="240"></label>' +
      '<label class="cat-check"><input type="checkbox" name="capa"> Usar como capa</label>' +
      '<button type="submit" class="cat-btn">Enviar mídia</button>' +
      '<p class="cat-status" data-upload-status></p></form>';
  }

  var produtosPorId = {};

  function ligarAcoesTabela() {
    $('cat-tabela').querySelectorAll('button[data-acao]').forEach(function (b) {
      b.addEventListener('click', function () {
        var linha = b.closest('tr');
        var id = linha.dataset.id;
        var acao = b.dataset.acao;
        if (acao === 'editar') return abrirFormulario(produtosPorId[id]);
        if (acao === 'midias') return alternarMidias(id);
        var novoStatus = acao === 'publicar' ? 'publicado' : acao === 'rascunho' ? 'rascunho' : 'em_breve';
        chamar('/api/admin/catalogo/produtos/' + id, { metodo: 'PATCH', corpo: { status: novoStatus } })
          .then(function () { status('Status atualizado.'); carregar(); })
          .catch(function (e) { status(e.message); });
      });
    });
    $('cat-tabela').querySelectorAll('form[data-upload-de]').forEach(function (form) {
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var id = form.dataset.uploadDe;
        var arquivoInput = form.querySelector('input[type=file]');
        var statusEl = form.querySelector('[data-upload-status]');
        if (!arquivoInput.files[0]) { statusEl.textContent = 'Escolha um arquivo.'; return; }
        var fd = new raiz.FormData(form);
        statusEl.textContent = 'Enviando…';
        chamar('/api/admin/catalogo/produtos/' + id + '/midias', { metodo: 'POST', formData: fd })
          .then(function () { statusEl.textContent = 'Mídia enviada.'; form.reset(); recarregarLinha(id); })
          .catch(function (e) { statusEl.textContent = e.message; });
      });
    });
  }

  function recarregarLinha(id) {
    chamar('/api/admin/catalogo/produtos').then(function (r) {
      produtosPorId = {}; r.produtos.forEach(function (p) { produtosPorId[p.id] = p; });
      desenharMidias(id);
    }).catch(function () {});
  }

  function alternarMidias(id) {
    var caixa = $('cat-midias-' + id);
    var aberto = caixa.classList.toggle('aberto');
    if (aberto) desenharMidias(id);
  }

  function desenharMidias(id) {
    var produto = produtosPorId[id];
    var caixa = $('cat-midias-' + id);
    if (!caixa || !produto) return;
    caixa.innerHTML = (produto.midias || []).map(function (m) {
      var tag = m.tipo === 'video' ? '<video src="' + esc(m.url) + '" muted></video>' : '<img src="' + esc(m.url) + '" alt="">';
      return '<div class="cat-midia-item">' + tag + '<button type="button" data-remover-midia="' + esc(m.id) + '" data-produto="' + esc(id) + '">remover</button></div>';
    }).join('');
    caixa.querySelectorAll('[data-remover-midia]').forEach(function (b) {
      b.addEventListener('click', function () {
        chamar('/api/admin/catalogo/produtos/' + b.dataset.produto + '/midias/' + b.dataset.removerMidia, { metodo: 'DELETE' })
          .then(function () { status('Mídia removida.'); carregar(); })
          .catch(function (e) { status(e.message); });
      });
    });
  }

  function montarFormulario() {
    $('cat-form').innerHTML =
      '<h3 id="cat-form-titulo">Novo produto</h3>' +
      '<label>Nome <input name="nome" required minlength="2" maxlength="160"></label>' +
      '<label>Endereço da página (gerado do nome; só é definido na criação) <input name="slug" pattern="[a-z][a-z0-9-]{2,78}[a-z0-9]" placeholder="gerado automaticamente"></label>' +
      '<label>Categoria <input name="categoria" list="cat-categorias-lista" required maxlength="60"><datalist id="cat-categorias-lista"></datalist></label>' +
      '<label>Descrição curta <input name="descricao_curta" required minlength="3" maxlength="240"></label>' +
      '<label>Descrição completa <textarea name="descricao_completa" maxlength="4000"></textarea></label>' +
      '<div class="cat-linha2"><label>Preço em R$ (deixe vazio se não houver) <input name="preco_reais" placeholder="0,00"></label>' +
      '<label>Unidade de venda <input name="unidade_venda" placeholder="unidade"></label></div>' +
      '<div class="cat-linha2"><label>Quantidade mínima <input name="quantidade_minima" type="number" min="1" value="1"></label>' +
      '<label>Múltiplo de compra <input name="multiplo_compra" type="number" min="1" value="1"></label></div>' +
      '<label>Modalidade de compra <select name="modalidade_compra">' +
        '<option value="em_breve">Em breve (sem pagamento)</option>' +
        '<option value="orcamento">Solicitação de orçamento</option>' +
        '<option value="comprar_site">Compra pelo site (exige um link que já funciona)</option>' +
      '</select></label>' +
      '<label id="cat-campo-url" style="display:none">URL de compra já funcional (ex.: /compreaqui.html#checkoutCard) <input name="url_compra"></label>' +
      '<label>Disponibilidade <input name="disponibilidade" maxlength="120" placeholder="Disponível, Sob encomenda…"></label>' +
      '<div class="cat-linha2"><label>Volume <input name="volume" maxlength="120"></label><label>Peso <input name="peso" maxlength="120"></label></div>' +
      '<div class="cat-linha2"><label>Composição <input name="composicao" maxlength="400"></label><label>Cuidados <input name="cuidados" maxlength="400"></label></div>' +
      '<div class="cat-linha2"><label class="cat-check"><input type="checkbox" name="destaque_home"> Destacar na página inicial</label>' +
      '<label>Ordem de exibição <input name="ordem_exibicao" type="number" value="0"></label></div>' +
      '<label>Status <select name="status"><option value="rascunho">Rascunho</option><option value="publicado">Publicado</option><option value="em_breve">Em breve</option></select></label>' +
      '<div><button type="submit" class="cat-btn cat-btn--primario">Salvar</button> ' +
      '<button type="button" class="cat-btn" id="cat-cancelar">Cancelar</button></div>' +
      '<p id="cat-form-status" class="cat-status" role="status"></p>';

    var form = $('cat-form');
    var modalidade = form.elements.modalidade_compra;
    var campoUrl = $('cat-campo-url');
    modalidade.addEventListener('change', function () {
      campoUrl.style.display = modalidade.value === 'comprar_site' ? 'grid' : 'none';
    });
    form.elements.nome.addEventListener('input', function () {
      if (!editandoId) form.elements.slug.value = slugSugerido(form.elements.nome.value);
    });
    $('cat-cancelar').addEventListener('click', function () { fecharFormulario(); });
    form.addEventListener('submit', salvar);
  }

  function abrirFormulario(produto) {
    var form = $('cat-form');
    form.reset();
    editandoId = produto ? produto.id : null;
    $('cat-form-titulo').textContent = produto ? 'Editar produto' : 'Novo produto';
    form.elements.slug.disabled = !!produto;
    if (produto) {
      form.elements.nome.value = produto.nome;
      form.elements.slug.value = produto.slug;
      form.elements.categoria.value = produto.categoria;
      form.elements.descricao_curta.value = produto.descricao_curta;
      form.elements.descricao_completa.value = produto.descricao_completa || '';
      form.elements.preco_reais.value = centavosParaReais(produto.preco_centavos);
      form.elements.unidade_venda.value = produto.unidade_venda;
      form.elements.quantidade_minima.value = produto.quantidade_minima;
      form.elements.multiplo_compra.value = produto.multiplo_compra;
      form.elements.modalidade_compra.value = produto.modalidade_compra;
      form.elements.url_compra.value = produto.url_compra || '';
      form.elements.disponibilidade.value = produto.disponibilidade || '';
      form.elements.volume.value = produto.volume || '';
      form.elements.peso.value = produto.peso || '';
      form.elements.composicao.value = produto.composicao || '';
      form.elements.cuidados.value = produto.cuidados || '';
      form.elements.destaque_home.checked = !!produto.destaque_home;
      form.elements.ordem_exibicao.value = produto.ordem_exibicao;
      form.elements.status.value = produto.status;
    }
    $('cat-campo-url').style.display = form.elements.modalidade_compra.value === 'comprar_site' ? 'grid' : 'none';
    form.classList.add('aberto');
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function fecharFormulario() {
    $('cat-form').classList.remove('aberto');
    editandoId = null;
  }

  function salvar(ev) {
    ev.preventDefault();
    var form = ev.target;
    var st = $('cat-form-status');
    var precoCentavos = reaisParaCentavos(form.elements.preco_reais.value);
    if (precoCentavos === undefined) { st.textContent = 'Confira o preço.'; return; }
    var corpo = {
      nome: form.elements.nome.value, categoria: form.elements.categoria.value,
      descricao_curta: form.elements.descricao_curta.value, descricao_completa: form.elements.descricao_completa.value || null,
      preco_centavos: precoCentavos, unidade_venda: form.elements.unidade_venda.value || undefined,
      quantidade_minima: Number(form.elements.quantidade_minima.value) || 1,
      multiplo_compra: Number(form.elements.multiplo_compra.value) || 1,
      modalidade_compra: form.elements.modalidade_compra.value,
      url_compra: form.elements.url_compra.value || null,
      disponibilidade: form.elements.disponibilidade.value || null,
      volume: form.elements.volume.value || null, peso: form.elements.peso.value || null,
      composicao: form.elements.composicao.value || null, cuidados: form.elements.cuidados.value || null,
      destaque_home: form.elements.destaque_home.checked, ordem_exibicao: Number(form.elements.ordem_exibicao.value) || 0,
      status: form.elements.status.value,
    };
    Object.keys(corpo).forEach(function (k) { if (corpo[k] === undefined) delete corpo[k]; });
    st.textContent = 'Salvando…';
    if (editandoId) {
      // Na edição, id/slug/criado_em nunca entram no corpo (o servidor recusaria).
      chamar('/api/admin/catalogo/produtos/' + editandoId, { metodo: 'PATCH', corpo: corpo })
        .then(function () { st.textContent = 'Salvo.'; fecharFormulario(); carregar(); })
        .catch(function (e) { st.textContent = e.message; });
    } else {
      if (form.elements.slug.value) corpo.slug = form.elements.slug.value;
      chamar('/api/admin/catalogo/produtos', { metodo: 'POST', corpo: corpo })
        .then(function () { st.textContent = 'Criado.'; fecharFormulario(); carregar(); })
        .catch(function (e) { st.textContent = e.message; });
    }
  }

  montarShell();
  doc.querySelector('[data-tab="catalogo"]')?.addEventListener('click', function () { if (!carregado && raiz.adminKeyAtual) carregar(); });
  raiz.addEventListener('admin-autorizado', function () { if (painel.classList.contains('active')) carregar(); });
})(typeof window !== 'undefined' ? window : globalThis);
