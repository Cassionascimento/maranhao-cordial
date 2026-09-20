/* Página pública de um QR rastreável (/q/<codigo>).
 *
 * A lógica que decide o que é enviado fica em funções puras (exportadas para
 * teste em Node); o resto só desenha e envia. Nada vindo do servidor é
 * inserido como HTML: tudo entra por textContent.
 *
 * Privacidade: não lê nem envia IP, user-agent ou identificador de aparelho.
 * A única "identidade" é uma chave aleatória por envio, guardada na sessão
 * do navegador, que serve para o servidor não contar o mesmo envio duas vezes.
 */
(function (raiz) {
  'use strict';

  var ROTULOS = {
    perfil: { consumidor: 'Consumidor', bartender: 'Bartender', bar_restaurante: 'Bar ou restaurante',
      distribuidor: 'Distribuidor', imprensa_influenciador: 'Imprensa ou influenciador', outro: 'Outro' },
    aplicacao: { agua_com_gas: 'Com água com gás', mocktail: 'Em mocktail', drink_alcoolico: 'Em drink com álcool',
      puro_com_gelo: 'Puro, com gelo', cozinha: 'Na cozinha', outra: 'Outra' },
    atributo: { guarana: 'Guaraná', docura: 'Doçura', acidez: 'Acidez', gengibre: 'Gengibre', textura: 'Textura' },
    nivel: { baixo: 'Baixo', ideal: 'Ideal', alto: 'Alto' },
    nivel_forca: { baixo: 'Fraco', ideal: 'Ideal', alto: 'Forte' },
    intencao: { certamente: 'Com certeza', provavelmente: 'Provavelmente', talvez: 'Talvez', nao: 'Não' },
    faixa_preco: { ate_39: 'Até R$ 39', '40_49': 'R$ 40 a R$ 49', '50_58': 'R$ 50 a R$ 58',
      '59_69': 'R$ 59 a R$ 69', '70_ou_mais': 'R$ 70 ou mais' },
    forma_uso: { com_agua_com_gas: 'Com água com gás', drinks_sem_alcool: 'Drinks sem álcool',
      drinks_com_alcool: 'Drinks com álcool', cozinha: 'Cozinha', presente: 'Para presentear', outra: 'Outra' },
    interesse: { comprar: 'Comprar', servir: 'Servir no meu negócio', amostra: 'Receber amostra',
      proposta: 'Receber proposta', revenda: 'Revender', distribuicao: 'Distribuir', parceria: 'Parceria' }
  };
  // Força (fraco/forte) descreve melhor guaraná e gengibre; doçura e acidez
  // seguem baixo/ideal/alto.
  var ATRIBUTOS_DE_FORCA = { guarana: 1, gengibre: 1, textura: 0 };

  function rotuloNivel(atributo, nivel) {
    return (ATRIBUTOS_DE_FORCA[atributo] ? ROTULOS.nivel_forca : ROTULOS.nivel)[nivel] || nivel;
  }

  function novaChave() {
    var c = raiz.crypto;
    if (c && typeof c.randomUUID === 'function') return c.randomUUID();
    var b = new Uint8Array(16);
    if (c && c.getRandomValues) c.getRandomValues(b); else for (var i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    var h = Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
    return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
  }

  /* Uma chave por (código, propósito) durante a sessão. Sem storage
   * disponível, cai numa chave em memória — o envio continua funcionando. */
  function chaveDaSessao(storage, memoria, codigo, proposito) {
    var nome = 'qr:' + codigo + ':' + proposito;
    try {
      var atual = storage && storage.getItem(nome);
      if (atual) return atual;
      var nova = novaChave();
      if (storage) storage.setItem(nome, nova);
      return nova;
    } catch (e) {
      if (!memoria[nome]) memoria[nome] = novaChave();
      return memoria[nome];
    }
  }

  function codigoDaUrl(caminho) {
    var m = /^\/q\/([^\/?#]+)\/?$/.exec(caminho || '');
    return m ? decodeURIComponent(m[1]).trim().toLowerCase() : null;
  }

  function soDigitos(v) { return String(v || '').replace(/\D+/g, ''); }

  /* O servidor é quem manda; aqui só se evita o round-trip óbvio. */
  function validarAvaliacao(e, atributos) {
    if (!e.perfil) return 'perfil';
    if (!e.aplicacao) return 'aplicacao';
    if (typeof e.nota !== 'number') return 'nota';
    for (var i = 0; i < atributos.length; i++) if (!e.sensorial || !e.sensorial[atributos[i]]) return atributos[i];
    if (!e.intencao_compra) return 'intencao_compra';
    if (!e.faixa_preco) return 'faixa_preco';
    if (!e.formas_uso || !e.formas_uso.length) return 'formas_uso';
    return null;
  }

  function montarAvaliacao(e, chave, isca) {
    var corpo = {
      chave: chave, perfil: e.perfil, aplicacao: e.aplicacao, nota: e.nota,
      sensorial: e.sensorial, intencao_compra: e.intencao_compra, faixa_preco: e.faixa_preco,
      formas_uso: e.formas_uso, website: isca || ''
    };
    var comentario = (e.comentario || '').trim();
    if (comentario) corpo.comentario = comentario;
    return corpo;
  }

  function validarContato(e) {
    if (!(e.nome || '').trim()) return 'nome';
    var tel = soDigitos(e.whatsapp), mail = (e.email || '').trim();
    if (!tel && !mail) return 'contato';
    if (tel && (tel.length < 10 || tel.length > 13)) return 'whatsapp';
    if (mail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail)) return 'email';
    if (!e.interesse) return 'interesse';
    if (e.consentimento_contato !== true) return 'consentimento_contato';
    return null;
  }

  function montarContato(e, chave, avaliacaoChave, isca) {
    var c = {
      chave: chave, nome: e.nome.trim(), whatsapp: (e.whatsapp || '').trim(), email: (e.email || '').trim(),
      empresa: (e.empresa || '').trim(), cidade: (e.cidade || '').trim(), uf: e.uf || '',
      interesse: e.interesse, perfil: e.perfil || '',
      // Dois consentimentos, dois campos: nunca um implica o outro.
      consentimento_contato: e.consentimento_contato === true,
      consentimento_marketing: e.consentimento_marketing === true,
      website: isca || ''
    };
    if (avaliacaoChave) c.avaliacao_chave = avaliacaoChave;
    return c;
  }

  var MENSAGENS = {
    perfil: 'Escolha o seu perfil.', aplicacao: 'Diga onde você provou.', nota: 'Dê uma nota de 0 a 10.',
    intencao_compra: 'Diga se compraria.', faixa_preco: 'Escolha uma faixa de preço.',
    formas_uso: 'Escolha ao menos uma forma de uso.', nome: 'Informe seu nome.',
    contato: 'Informe WhatsApp ou e-mail.', whatsapp: 'Confira o WhatsApp, com DDD.', email: 'Confira o e-mail.',
    interesse: 'Escolha o seu interesse.', consentimento_contato: 'Para enviarmos o contato, marque a autorização.',
    uf: 'Confira o estado.'
  };
  function mensagemDoCampo(campo) {
    if (ROTULOS.atributo[campo]) return 'Avalie ' + ROTULOS.atributo[campo].toLowerCase() + '.';
    return MENSAGENS[campo] || 'Confira os dados e tente de novo.';
  }

  var api = {
    ROTULOS: ROTULOS, rotuloNivel: rotuloNivel, novaChave: novaChave, chaveDaSessao: chaveDaSessao,
    codigoDaUrl: codigoDaUrl, validarAvaliacao: validarAvaliacao, montarAvaliacao: montarAvaliacao,
    validarContato: validarContato, montarContato: montarContato, mensagemDoCampo: mensagemDoCampo
  };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  raiz.QRPagina = api;

  /* ----------------------------------------------------------------- DOM */

  var doc = raiz.document;
  var memoria = {};
  var storage = null;
  try { storage = raiz.sessionStorage; } catch (e) { storage = null; }

  function el(tag, attrs, filhos) {
    var n = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'texto') n.textContent = attrs[k]; else if (k === 'classe') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (filhos || []).forEach(function (f) { if (f) n.appendChild(f); });
    return n;
  }

  function post(url, corpo) {
    return raiz.fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
      credentials: 'omit', referrerPolicy: 'no-referrer', keepalive: true })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, dados: j }; }); });
  }

  function grupo(nome, titulo, valores, rotulos, opts) {
    opts = opts || {};
    var tipo = opts.multiplo ? 'checkbox' : 'radio';
    var caixa = el('div', { classe: 'qr-opcoes' });
    valores.forEach(function (v) {
      var input = el('input', { type: tipo, name: nome, value: v });
      caixa.appendChild(el('label', { classe: 'qr-opcao' }, [input, el('span', { texto: rotulos[v] || v })]));
    });
    var f = el('fieldset', {}, [el('legend', { texto: titulo }), caixa]);
    return f;
  }

  function lerGrupo(form, nome, multiplo) {
    var marcados = Array.prototype.slice.call(form.querySelectorAll('input[name="' + nome + '"]:checked'));
    return multiplo ? marcados.map(function (i) { return i.value; }) : (marcados[0] ? marcados[0].value : '');
  }

  function iniciar() {
    var principal = doc.getElementById('raiz');
    var codigo = codigoDaUrl(raiz.location.pathname);
    function mostrar(nos) {
      principal.textContent = '';
      principal.appendChild(el('p', { classe: 'qr-marca', texto: 'Maranhão Cordial' }));
      nos.forEach(function (n) { principal.appendChild(n); });
    }
    function invalido() {
      mostrar([el('h1', { texto: 'Este código não está disponível.' }),
        el('p', { classe: 'qr-lead', texto: 'Confira o QR ou digite o endereço de novo.' }),
        el('a', { classe: 'qr-secundario', href: '/', texto: 'Ir para o site', style: 'text-align:center;line-height:46px;text-decoration:none' })]);
    }
    if (!codigo) return invalido();

    raiz.fetch('/api/qr/' + encodeURIComponent(codigo), { credentials: 'omit', referrerPolicy: 'no-referrer' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (config) { if (!config || !config.success) return invalido(); montar(config); })
      .catch(function () {
        mostrar([el('h1', { texto: 'Sem conexão.' }), el('p', { classe: 'qr-lead', texto: 'Tente novamente em instantes.' })]);
      });

    function montar(config) {
      var qr = config.qr, opc = config.opcoes, consent = config.consentimento;
      var base = '/api/qr/' + encodeURIComponent(codigo);
      // Um scan por sessão de navegação: recarregar a página não infla o funil.
      post(base + '/scan', { chave: chaveDaSessao(storage, memoria, codigo, 'scan') }).catch(function () {});
      if (qr.destino_tipo === 'redirecionar' && qr.destino_url) {
        // Pequena espera para o registro do scan sair antes de deixar a página.
        raiz.setTimeout(function () { raiz.location.replace(qr.destino_url); }, 250);
        return mostrar([el('h1', { texto: 'Abrindo…' })]);
      }
      if (qr.tem_avaliacao) return telaAvaliacao();
      if (qr.finalidade === 'comercial') return telaContato(null, 'Fale com a Maranhão.', 'Conte o que você precisa e retornamos.');
      return telaDivulgacao();

      function telaDivulgacao() {
        mostrar([el('h1', { texto: qr.chamada }),
          el('p', { classe: 'qr-lead', texto: 'Uma bebida de guaraná e gengibre, do Maranhão.' }),
          el('div', { classe: 'qr-passo' }, [el('ul', { classe: 'qr-links' }, [
            el('li', {}, [el('a', { href: '/', texto: 'Conhecer o site' })])])]),
          botao('Quero falar com a Maranhão', function () { telaContato(null, 'Fale com a Maranhão.', 'Deixe seu contato e retornamos.'); }, 'qr-secundario')]);
      }

      function botao(texto, aoClicar, classe, tipo) {
        var b = el('button', { type: tipo || 'button', classe: classe || 'qr-botao', texto: texto });
        if (aoClicar) b.addEventListener('click', aoClicar);
        return b;
      }

      function isca() { return el('div', { classe: 'qr-isca', 'aria-hidden': 'true' }, [el('input', { type: 'text', name: 'website', tabindex: '-1', autocomplete: 'off' })]); }

      function telaAvaliacao() {
        var iniciou = false;
        var form = el('form', { classe: 'qr-passo', novalidate: 'novalidate' });
        var rot = ROTULOS;
        form.appendChild(grupo('perfil', 'Quem é você?', opc.perfis, rot.perfil));
        form.appendChild(grupo('aplicacao', 'Como você provou?', opc.aplicacoes, rot.aplicacao));

        var nota = el('fieldset', {}, [el('legend', { texto: 'Nota de 0 a 10' })]);
        var grade = el('div', { classe: 'qr-nota' });
        for (var n = 0; n <= 10; n++) {
          grade.appendChild(el('label', { classe: 'qr-opcao' }, [el('input', { type: 'radio', name: 'nota', value: String(n) }), el('span', { texto: String(n) })]));
        }
        nota.appendChild(grade);
        nota.appendChild(el('div', { classe: 'qr-nota-eixos' }, [el('span', { texto: 'Não gostei' }), el('span', { texto: 'Adorei' })]));
        form.appendChild(nota);

        var sens = el('fieldset', {}, [el('legend', {}, [doc.createTextNode('Como você sentiu?')])]);
        var bloco = el('div', { classe: 'qr-sensorial' });
        opc.atributos.forEach(function (a) {
          var opcoes = el('div', { classe: 'qr-opcoes' });
          opc.niveis.forEach(function (nv) {
            opcoes.appendChild(el('label', { classe: 'qr-opcao' }, [el('input', { type: 'radio', name: 'sens_' + a, value: nv }), el('span', { texto: rotuloNivel(a, nv) })]));
          });
          bloco.appendChild(el('div', { classe: 'qr-linha' }, [el('span', { texto: rot.atributo[a] || a }), opcoes]));
        });
        sens.appendChild(bloco);
        form.appendChild(sens);

        form.appendChild(grupo('intencao_compra', 'Você compraria?', opc.intencoes, rot.intencao));
        var preco = grupo('faixa_preco', 'Quanto aceitaria pagar por 200 mL?', opc.faixas_preco, rot.faixa_preco);
        form.appendChild(preco);
        form.appendChild(grupo('formas_uso', 'Como usaria?', opc.formas_uso, rot.forma_uso, { multiplo: true }));
        form.appendChild(el('div', { classe: 'qr-campo' }, [
          el('label', { classe: 'qr-rotulo', 'for': 'comentario' }, [doc.createTextNode('Quer contar mais? '), el('span', { classe: 'qr-dica', texto: 'Opcional' })]),
          el('textarea', { id: 'comentario', name: 'comentario', maxlength: '500' })]));
        form.appendChild(isca());
        var erro = el('p', { classe: 'qr-erro', role: 'alert' });
        var enviar = botao('Enviar avaliação', null, 'qr-botao', 'submit');
        form.appendChild(enviar); form.appendChild(erro);

        function primeiraInteracao() {
          if (iniciou) return; iniciou = true;
          post(base + '/inicio', { chave: chaveDaSessao(storage, memoria, codigo, 'avaliacao') }).catch(function () {});
        }
        form.addEventListener('change', primeiraInteracao);
        form.addEventListener('input', primeiraInteracao);

        form.addEventListener('submit', function (ev) {
          ev.preventDefault();
          var sensorial = {};
          opc.atributos.forEach(function (a) { sensorial[a] = lerGrupo(form, 'sens_' + a); });
          var notaValor = lerGrupo(form, 'nota');
          var estado = {
            perfil: lerGrupo(form, 'perfil'), aplicacao: lerGrupo(form, 'aplicacao'),
            nota: notaValor === '' ? null : Number(notaValor), sensorial: sensorial,
            intencao_compra: lerGrupo(form, 'intencao_compra'), faixa_preco: lerGrupo(form, 'faixa_preco'),
            formas_uso: lerGrupo(form, 'formas_uso', true), comentario: form.elements.comentario.value
          };
          var falta = validarAvaliacao(estado, opc.atributos);
          if (falta) { erro.textContent = mensagemDoCampo(falta); return; }
          erro.textContent = ''; enviar.disabled = true;
          var chave = chaveDaSessao(storage, memoria, codigo, 'avaliacao');
          post(base + '/avaliacao', montarAvaliacao(estado, chave, form.elements.website.value))
            .then(function (r) {
              if (r.ok) return agradecer(estado, chave);
              enviar.disabled = false;
              erro.textContent = r.dados && r.dados.campo ? mensagemDoCampo(r.dados.campo) : 'Não foi possível enviar agora. Tente de novo.';
            }).catch(function () { enviar.disabled = false; erro.textContent = 'Sem conexão. Tente de novo.'; });
        });

        mostrar([el('h1', { texto: qr.chamada }),
          el('p', { classe: 'qr-lead', texto: 'Leva cerca de um minuto. Você não precisa se identificar.' }), form]);
      }

      function agradecer(avaliacao, chave) {
        mostrar([el('h1', { texto: 'Obrigado pela avaliação.' }),
          el('p', { classe: 'qr-lead', texto: 'Ela já foi registrada. Se quiser, deixe um contato para falarmos com você.' }),
          botao('Deixar meu contato', function () { telaContato(chave, 'Deixe seu contato.', 'Usamos só para responder ao seu interesse.', avaliacao.perfil); }),
          botao('Agora não', function () {
            mostrar([el('h1', { texto: 'Até a próxima.' }), el('p', { classe: 'qr-lead', texto: 'Sua avaliação continua anônima.' })]);
          }, 'qr-secundario')]);
      }

      function telaContato(avaliacaoChave, titulo, texto, perfil) {
        var form = el('form', { classe: 'qr-passo', novalidate: 'novalidate' });
        function campo(id, rotulo, tipo, extra) {
          var a = { id: id, name: id, type: tipo || 'text' };
          Object.keys(extra || {}).forEach(function (k) { a[k] = extra[k]; });
          return el('div', { classe: 'qr-campo' }, [el('label', { classe: 'qr-rotulo', 'for': id, texto: rotulo }), el('input', a)]);
        }
        form.appendChild(campo('nome', 'Nome', 'text', { autocomplete: 'name' }));
        form.appendChild(campo('whatsapp', 'WhatsApp', 'tel', { autocomplete: 'tel', inputmode: 'tel', placeholder: '(98) 90000-0000' }));
        form.appendChild(campo('email', 'E-mail', 'email', { autocomplete: 'email', inputmode: 'email' }));
        form.appendChild(el('p', { classe: 'qr-dica', texto: 'Informe WhatsApp ou e-mail.' }));
        form.appendChild(campo('empresa', 'Empresa (opcional)', 'text', { autocomplete: 'organization' }));
        var uf = el('select', { id: 'uf', name: 'uf', autocomplete: 'address-level1' }, [el('option', { value: '', texto: 'UF' })]);
        opc.ufs.forEach(function (u) { uf.appendChild(el('option', { value: u, texto: u })); });
        form.appendChild(el('div', { classe: 'qr-dupla qr-campo' }, [
          el('div', {}, [el('label', { classe: 'qr-rotulo', 'for': 'cidade', texto: 'Cidade' }), el('input', { id: 'cidade', name: 'cidade', type: 'text', autocomplete: 'address-level2' })]),
          el('div', {}, [el('label', { classe: 'qr-rotulo', 'for': 'uf', texto: 'Estado' }), uf])]));
        form.appendChild(grupo('interesse', 'Qual é o seu interesse?', opc.interesses, ROTULOS.interesse));
        if (!avaliacaoChave) form.appendChild(grupo('perfil', 'Quem é você?', opc.perfis, ROTULOS.perfil));
        // Dois consentimentos, separados, sempre desmarcados.
        function consentimento(nome, texto) {
          return el('label', { classe: 'qr-consent' }, [el('input', { type: 'checkbox', name: nome }), el('span', { texto: texto })]);
        }
        form.appendChild(consentimento('consentimento_contato', consent.contato));
        form.appendChild(consentimento('consentimento_marketing', consent.marketing));
        form.appendChild(isca());
        var erro = el('p', { classe: 'qr-erro', role: 'alert' });
        var enviar = botao('Enviar contato', null, 'qr-botao', 'submit');
        form.appendChild(enviar); form.appendChild(erro);

        form.addEventListener('submit', function (ev) {
          ev.preventDefault();
          var v = function (n) { return form.elements[n] ? form.elements[n].value : ''; };
          var estado = {
            nome: v('nome'), whatsapp: v('whatsapp'), email: v('email'), empresa: v('empresa'), cidade: v('cidade'), uf: v('uf'),
            interesse: lerGrupo(form, 'interesse'), perfil: perfil || lerGrupo(form, 'perfil'),
            consentimento_contato: form.elements.consentimento_contato.checked,
            consentimento_marketing: form.elements.consentimento_marketing.checked
          };
          var falta = validarContato(estado);
          if (falta) { erro.textContent = mensagemDoCampo(falta); return; }
          erro.textContent = ''; enviar.disabled = true;
          var chave = chaveDaSessao(storage, memoria, codigo, 'contato');
          post(base + '/contato', montarContato(estado, chave, avaliacaoChave, form.elements.website.value))
            .then(function (r) {
              if (r.ok) return mostrar([el('h1', { texto: 'Recebemos seu contato.' }), el('p', { classe: 'qr-lead', texto: 'Obrigado. Retornaremos em breve.' })]);
              enviar.disabled = false;
              erro.textContent = r.dados && r.dados.campo ? mensagemDoCampo(r.dados.campo) : 'Não foi possível enviar agora. Tente de novo.';
            }).catch(function () { enviar.disabled = false; erro.textContent = 'Sem conexão. Tente de novo.'; });
        });
        mostrar([el('h1', { texto: titulo }), el('p', { classe: 'qr-lead', texto: texto }), form]);
      }
    }
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})(typeof window !== 'undefined' ? window : globalThis);
