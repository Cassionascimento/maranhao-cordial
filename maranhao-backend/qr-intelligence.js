/* Maranhão Intelligence · QR & Avaliações.
 *
 * Acrescenta uma sub-vista ao Command Center existente (não cria painel,
 * não reconstrói nada). Só lê /api/admin/qr/painel e administra os códigos.
 *
 * Regras de exibição:
 *  - sem dado, o valor é "—", nunca 0%;
 *  - todo percentual vem com o tamanho da amostra (n) e, abaixo do mínimo,
 *    com o aviso de que ainda não permite conclusão;
 *  - nenhum dado pessoal chega aqui (o painel só devolve agregados e
 *    comentários sem identificação).
 */
(function (raiz) {
  'use strict';

  var ROTULO_FINALIDADE = { avaliacao_feira: 'Avaliação na feira', avaliacao_produto: 'Avaliação do produto',
    comercial: 'Comercial', divulgacao: 'Divulgação' };
  var ROTULO_INTERESSE = { comprar: 'Comprar', servir: 'Servir', amostra: 'Amostra', proposta: 'Proposta',
    revenda: 'Revenda', distribuicao: 'Distribuição', parceria: 'Parceria' };
  var ROTULO_ATRIBUTO = { guarana: 'Guaraná', docura: 'Doçura', acidez: 'Acidez', gengibre: 'Gengibre', textura: 'Textura' };
  var ROTULO_INTENCAO = { certamente: 'Com certeza', provavelmente: 'Provavelmente', talvez: 'Talvez', nao: 'Não' };
  var ROTULO_FAIXA = { ate_39: 'Até R$ 39', '40_49': 'R$ 40–49', '50_58': 'R$ 50–58', '59_69': 'R$ 59–69', '70_ou_mais': 'R$ 70+' };
  var ROTULO_PERFIL = { consumidor: 'Consumidor', bartender: 'Bartender', bar_restaurante: 'Bar ou restaurante',
    distribuidor: 'Distribuidor', imprensa_influenciador: 'Imprensa/influenciador', outro: 'Outro' };
  var ROTULO_ESTADO = { ativo: 'Ativo', pausado: 'Pausado', revogado: 'Revogado' };

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function pct(v) { return v == null ? '—' : String(v).replace('.', ',') + '%'; }
  function dec(v) { return v == null ? '—' : Number(v).toFixed(1).replace('.', ','); }
  function inteiro(v) { return Number(v || 0).toLocaleString('pt-BR'); }

  /* "62,5% (n=8, amostra pequena)" — ou "—" quando não há dado. */
  function comAmostra(valor, n, pequena, formatar) {
    if (valor == null) return '—';
    return (formatar || pct)(valor) + ' <small>n=' + inteiro(n) + (pequena ? ' · amostra pequena' : '') + '</small>';
  }

  function textoAmostra(a, minima) {
    if (!a || !a.n) return 'Ainda sem avaliações neste período.';
    if (a.amostra_pequena) {
      return inteiro(a.n) + ' avaliação(ões): abaixo de ' + inteiro(minima) + ', ainda não permite conclusão. Leia como registro, não como tendência.';
    }
    return inteiro(a.n) + ' avaliações no período.';
  }

  function slugValido(s) { return /^[a-z][a-z0-9_]{2,63}$/.test(s || ''); }

  function corpoCriacao(f) {
    var c = { nome: (f.nome || '').trim(), chamada: (f.chamada || '').trim(), finalidade: f.finalidade,
      origem: (f.origem || '').trim(), campanha: (f.campanha || '').trim() || undefined,
      posicao: (f.posicao || '').trim() || undefined, sku: (f.sku || '').trim() || undefined };
    Object.keys(c).forEach(function (k) { if (c[k] === undefined || c[k] === '') delete c[k]; });
    return c;
  }

  var api = { esc: esc, pct: pct, dec: dec, comAmostra: comAmostra, textoAmostra: textoAmostra, corpoCriacao: corpoCriacao,
    slugValido: slugValido, ROTULO_FINALIDADE: ROTULO_FINALIDADE };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  /* ------------------------------------------------------------------ DOM */
  var doc = raiz.document;
  var painel = doc.getElementById('mi-painel');
  var nav = painel && painel.querySelector('.mic-nav');
  if (!painel || !nav) return;
  var BASE = 'https://maranhao-cordial-api.onrender.com';
  var carregado = false;
  var $ = function (id) { return doc.getElementById(id); };

  function chamar(caminho, opcoes) {
    if (!raiz.adminKeyAtual) return Promise.reject(new Error('Entre no Admin para consultar os QR Codes.'));
    opcoes = opcoes || {};
    var cab = { 'X-Admin-Key': raiz.adminKeyAtual };
    if (opcoes.corpo) cab['Content-Type'] = 'application/json';
    return raiz.fetch(BASE + caminho, { method: opcoes.metodo || 'GET', cache: 'no-store', headers: cab,
      body: opcoes.corpo ? JSON.stringify(opcoes.corpo) : undefined }).then(function (r) {
      if (opcoes.blob && r.ok) return r.blob();
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.campo ? 'Confira o campo: ' + j.campo : (j.error || 'Falha ' + r.status)); e.dados = j; throw e; }
        return j;
      });
    });
  }

  function montar() {
    var gancho = doc.createElement('span');
    gancho.innerHTML = '<button type="button" data-mic-view="qr">QR &amp; Avaliações</button>';
    var botao = gancho.firstChild;
    nav.appendChild(botao);
    var vista = doc.createElement('div');
    vista.id = 'mic-qr'; vista.className = 'mic-view';
    vista.innerHTML =
      '<section class="mic-card mic-card--wide"><div class="mic-card-head"><div><span>QR CODES RASTREÁVEIS</span><h3>Do QR à avaliação e ao contato</h3></div>' +
      '<label class="qri-periodo">Período <select id="qri-dias"><option value="">Tudo</option><option value="7">7 dias</option><option value="30" selected>30 dias</option><option value="90">90 dias</option></select></label><button id="qri-atualizar" type="button" class="qri-btn">Atualizar</button></div>' +
      '<p class="mic-note">Só dados reais. Sem dado aparece “—”. Percentuais mostram o tamanho da amostra e avisam quando ela é pequena. Avaliações anônimas não viram lead.</p>' +
      '<p id="qri-status" class="mic-status" role="status" aria-live="polite"></p><div id="qri-corpo"></div></section>' +
      '<section class="mic-card mic-card--wide"><span class="mic-kicker">CÓDIGOS</span><h3>QR Codes e destinos</h3><div id="qri-codigos"></div>' +
      '<details class="qri-novo"><summary>Criar novo QR</summary><form id="qri-form" novalidate></form></details></section>';
    painel.appendChild(vista);
    botao.addEventListener('click', function () {
      painel.querySelectorAll('[data-mic-view]').forEach(function (b) { b.classList.toggle('active', b === botao); });
      painel.querySelectorAll('.mic-view').forEach(function (v) { v.classList.toggle('active', v === vista); });
      carregar();
    });
    $('qri-dias').addEventListener('change', carregar);
    $('qri-atualizar').addEventListener('click', carregar);
    formulario();
  }

  function kpi(titulo, valor, meta) {
    return '<article class="mic-kpi"><span>' + esc(titulo) + '</span><strong>' + valor + '</strong><small>' + meta + '</small></article>';
  }

  function tabela(cabecalho, linhas) {
    if (!linhas.length) return '';
    return '<div class="qri-rolagem"><table class="qri-tabela"><thead><tr>' + cabecalho.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + linhas.map(function (l) { return '<tr>' + l.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
  }

  function desenharPainel(p) {
    var a = p.avaliacoes, minima = p.amostra_minima;
    var totalScans = 0, scansDeAvaliacao = 0, totalIniciadas = 0, totalContatos = 0, totalOportunidades = 0;
    p.por_qr.forEach(function (l) { totalScans += l.scans; if (/^avaliacao_/.test(l.finalidade)) scansDeAvaliacao += l.scans; totalIniciadas += l.iniciadas; totalContatos += l.contatos; totalOportunidades += l.oportunidades; });
    // Conversão só sobre leituras de QRs que pedem avaliação: comercial e divulgação não têm avaliação a concluir.
    var conv = scansDeAvaliacao ? Math.round(1000 * a.n / scansDeAvaliacao) / 10 : null;
    var html = '<div class="mic-kpis">' +
      kpi('Leituras do QR', inteiro(totalScans), 'Por sessão de navegação') +
      kpi('Avaliações iniciadas', inteiro(totalIniciadas), 'Quem começou a responder') +
      kpi('Avaliações concluídas', inteiro(a.n), conv == null ? 'Sem leituras para comparar' : pct(conv) + ' das leituras de QRs de avaliação') +
      kpi('Nota média (0–10)', a.nota_media == null ? '—' : dec(a.nota_media), 'n=' + inteiro(a.n)) +
      kpi('Compraria (com certeza/provavelmente)', pct(a.pct_intencao_positiva), a.n ? 'n=' + inteiro(a.n) : 'Sem dado') +
      kpi('Aceita R$ ' + p.preco_referencia + ' por 200 mL', pct(a.pct_aceita_59), a.n ? 'n=' + inteiro(a.n) : 'Sem dado') +
      kpi('Contatos deixados', inteiro(p.contatos.total), 'Com consentimento de contato') +
      kpi('Oportunidades', inteiro(totalOportunidades), 'Interesse além de consumo') + '</div>' +
      '<p class="mic-note ' + (a.amostra_pequena ? 'qri-aviso' : '') + '">' + esc(textoAmostra(a, minima)) + '</p>';

    html += '<h4 class="qri-h">Por QR</h4>' + tabela(['QR', 'Finalidade', 'Leituras', 'Iniciadas', 'Concluídas', 'Conversão', 'Contatos', 'Leads', 'Oportunidades'],
      p.por_qr.map(function (l) {
        return [esc(l.nome), esc(ROTULO_FINALIDADE[l.finalidade] || l.finalidade), inteiro(l.scans), inteiro(l.iniciadas), inteiro(l.concluidas),
          pct(l.conversao_avaliacao), inteiro(l.contatos), inteiro(l.leads), inteiro(l.oportunidades)];
      }));

    if (a.n) {
      html += '<h4 class="qri-h">Percepção sensorial</h4>' + tabela(['Atributo', 'Baixo/fraco', 'Ideal', 'Alto/forte', 'n'],
        Object.keys(a.sensorial).map(function (k) {
          var s = a.sensorial[k];
          return [esc(ROTULO_ATRIBUTO[k] || k), pct(s.pct.baixo), pct(s.pct.ideal), pct(s.pct.alto), inteiro(s.n) + (s.amostra_pequena ? ' · pequena' : '')];
        }));
      html += '<h4 class="qri-h">Intenção de compra e preço (200 mL)</h4>' + tabela(['Resposta', 'Respostas'],
        Object.keys(a.intencao).filter(function (k) { return k in ROTULO_INTENCAO; }).map(function (k) { return [esc(ROTULO_INTENCAO[k]), inteiro(a.intencao[k])]; }).concat(
          Object.keys(a.faixa_preco).filter(function (k) { return k in ROTULO_FAIXA; }).map(function (k) { return [esc('Aceita pagar até ' + ROTULO_FAIXA[k]), inteiro(a.faixa_preco[k])]; })));
      var f = p.comparacao.feira, o = p.comparacao.outras_origens;
      html += '<h4 class="qri-h">Feira × outras origens</h4><p class="mic-note">' + esc(p.comparacao.descricao_outras_origens) +
        ' Não há base externa importada: “outras origens” são só as avaliações por QR de embalagem, material e digital.</p>' +
        tabela(['Grupo', 'Nota média', 'Compraria', 'Aceita R$ ' + p.preco_referencia, 'n'], [
          ['Feira', dec(f.nota_media), pct(f.pct_intencao_positiva), pct(f.pct_aceita_59), inteiro(f.n) + (f.amostra_pequena ? ' · pequena' : '')],
          ['Outras origens', dec(o.nota_media), pct(o.pct_intencao_positiva), pct(o.pct_aceita_59), inteiro(o.n) + (o.amostra_pequena ? ' · pequena' : '')]]);
      html += '<h4 class="qri-h">Por perfil</h4>' + tabela(['Perfil', 'Nota média', 'Compraria', 'Aceita R$ ' + p.preco_referencia, 'n'],
        p.por_perfil.map(function (l) {
          return [esc(ROTULO_PERFIL[l.perfil] || l.perfil), dec(l.nota_media), pct(l.pct_intencao_positiva), pct(l.pct_aceita_59), inteiro(l.n) + (l.amostra_pequena ? ' · pequena' : '')];
        }));
    }
    var origens = p.por_origem || [];
    if (origens.length) {
      html += '<h4 class="qri-h">Por origem e canal</h4>' + tabela(['Origem', 'Canal', 'Leituras', 'Concluídas', 'Contatos', 'Leads'],
        origens.map(function (l) { return [esc(l.origem), esc(l.canal), inteiro(l.scans), inteiro(l.concluidas), inteiro(l.contatos), inteiro(l.leads)]; }));
    }
    var interesses = Object.keys(p.contatos.por_interesse);
    if (interesses.length) {
      html += '<h4 class="qri-h">Interesse dos contatos</h4>' + tabela(['Interesse', 'Contatos', 'Leads'],
        interesses.map(function (k) { return [esc(ROTULO_INTERESSE[k] || k), inteiro(p.contatos.por_interesse[k].contatos), inteiro(p.contatos.por_interesse[k].leads)]; }));
      if (p.contatos.identidade_pendente) {
        html += '<p class="mic-note qri-aviso">' + inteiro(p.contatos.identidade_pendente) + ' contato(s) com telefone/e-mail já ligado a mais de um cadastro: aguardam decisão humana em Duplicados.</p>';
      }
    }
    if (p.comentarios_recentes.length) {
      html += '<h4 class="qri-h">Comentários recentes (sem identificação)</h4><ul class="qri-comentarios">' + p.comentarios_recentes.map(function (c) {
        return '<li><b>' + esc(c.nota) + '/10</b> · ' + esc(ROTULO_PERFIL[c.perfil] || c.perfil) + '<br>' + esc(c.comentario) + '</li>';
      }).join('') + '</ul>';
    }
    $('qri-corpo').innerHTML = html;
  }

  function desenharCodigos(lista) {
    $('qri-codigos').innerHTML = tabela(['Nome', 'Estado', 'Link', 'Arquivos', 'Ações'], lista.map(function (q) {
      var acoes = q.estado === 'revogado' ? '—' :
        '<button type="button" class="qri-btn" data-qri-acao="destino" data-id="' + esc(q.id) + '">Destino</button> ' +
        '<button type="button" class="qri-btn" data-qri-acao="' + (q.estado === 'ativo' ? 'pausar' : 'ativar') + '" data-id="' + esc(q.id) + '">' + (q.estado === 'ativo' ? 'Pausar' : 'Ativar') + '</button>';
      var arquivos = ['svg', 'png', 'pdf'].map(function (f) {
        return '<button type="button" class="qri-btn" data-qri-acao="baixar" data-formato="' + f + '" data-id="' + esc(q.id) + '" data-slug="' + esc(q.slug) + '">' + f.toUpperCase() + '</button>';
      }).join(' ');
      return [esc(q.nome) + '<small>' + esc(ROTULO_FINALIDADE[q.finalidade] || q.finalidade) + ' · ' + esc(q.destino_tipo === 'redirecionar' ? 'redireciona' : 'página própria') + '</small>',
        esc(ROTULO_ESTADO[q.estado] || q.estado),
        '<button type="button" class="qri-btn" data-qri-acao="copiar" data-url="' + esc(q.url) + '">Copiar link</button>', arquivos, acoes];
    }));
  }

  function status(t) { $('qri-status').textContent = t || ''; }

  function carregar() {
    var dias = $('qri-dias').value;
    status('Consultando…');
    Promise.all([chamar('/api/admin/qr/painel' + (dias ? '?dias=' + encodeURIComponent(dias) : '')), chamar('/api/admin/qr/codigos')])
      .then(function (r) { desenharPainel(r[0]); desenharCodigos(r[1].codigos); carregado = true; status('Atualizado às ' + new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) + '.'); })
      .catch(function (e) { status(e.message); });
  }

  function formulario() {
    $('qri-form').innerHTML =
      '<p class="mic-note">O código público é gerado ao salvar, opaco e imutável. Depois de impresso, só o destino e o estado mudam.</p>' +
      '<label>Nome<input name="nome" required minlength="3"></label>' +
      '<label>Frase impressa<input name="chamada" required minlength="3" maxlength="80"></label>' +
      '<label>Finalidade<select name="finalidade">' + Object.keys(ROTULO_FINALIDADE).map(function (k) { return '<option value="' + k + '">' + esc(ROTULO_FINALIDADE[k]) + '</option>'; }).join('') + '</select></label>' +
      '<label>Origem<input name="origem" required placeholder="feira, embalagem, material_comercial, digital…"></label>' +
      '<label>Campanha ou evento<input name="campanha"></label><label>Posição (estande, embalagem, slide…)<input name="posicao"></label>' +
      '<label>SKU (opcional, precisa existir)<input name="sku"></label>' +
      '<button type="submit" class="qri-btn qri-btn--primario">Criar QR</button><p id="qri-form-status" class="mic-status" role="status"></p>';
    $('qri-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var dados = {}; new raiz.FormData(ev.target).forEach(function (v, k) { dados[k] = v; });
      var st = $('qri-form-status'); st.textContent = 'Criando…';
      chamar('/api/admin/qr/codigos', { metodo: 'POST', corpo: corpoCriacao(dados) }).then(function (r) {
        st.textContent = 'Criado: ' + r.qr.url; ev.target.reset(); carregar();
      }).catch(function (e) { st.textContent = e.message; });
    });
  }

  painel.addEventListener('click', function (ev) {
    var b = ev.target.closest && ev.target.closest('[data-qri-acao]');
    if (!b) return;
    var acao = b.dataset.qriAcao, id = b.dataset.id;
    if (acao === 'copiar') {
      var url = b.dataset.url;
      (raiz.navigator.clipboard ? raiz.navigator.clipboard.writeText(url) : Promise.reject()).then(function () { status('Link copiado.'); }, function () { status(url); });
    } else if (acao === 'baixar') {
      chamar('/api/admin/qr/codigos/' + encodeURIComponent(id) + '/arquivo?formato=' + b.dataset.formato, { blob: true }).then(function (blob) {
        var a = doc.createElement('a'); a.href = raiz.URL.createObjectURL(blob); a.download = 'qr_' + b.dataset.slug + '.' + b.dataset.formato;
        doc.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { raiz.URL.revokeObjectURL(a.href); }, 4000);
      }).catch(function (e) { status(e.message); });
    } else if (acao === 'pausar' || acao === 'ativar') {
      chamar('/api/admin/qr/codigos/' + encodeURIComponent(id), { metodo: 'PATCH', corpo: { estado: acao === 'pausar' ? 'pausado' : 'ativo' } })
        .then(carregar).catch(function (e) { status(e.message); });
    } else if (acao === 'destino') {
      var novo = raiz.prompt('Novo destino (URL https://…). Deixe vazio para voltar à página do QR.');
      if (novo === null) return;
      var corpo = novo.trim() ? { destino_tipo: 'redirecionar', destino_url: novo.trim() } : { destino_tipo: 'pagina' };
      chamar('/api/admin/qr/codigos/' + encodeURIComponent(id), { metodo: 'PATCH', corpo: corpo }).then(function () { status('Destino atualizado. O código impresso não mudou.'); carregar(); })
        .catch(function (e) { status(e.message); });
    }
  });

  montar();
  raiz.addEventListener('admin-autorizado', function () { if ($('mic-qr').classList.contains('active')) carregar(); });
})(typeof window !== 'undefined' ? window : globalThis);
