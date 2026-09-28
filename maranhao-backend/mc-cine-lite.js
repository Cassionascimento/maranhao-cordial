/* Versão leve do hero cinematográfico da home (mc-cine.js) para "Compre
 * aqui": a mesma linguagem visual -- "MARANHÃO" como janela para um vídeo
 * já existente -- só que sem pin nem zoom por scroll, apenas uma revelação
 * curta e suave ao entrar na tela. Mesmo vídeo de sempre desta página
 * (maranhao-regional-10s.mp4), nunca carregado uma segunda vez: é o
 * elemento de vídeo que a própria página já tinha, só que também desenhado
 * aqui, mascarado, num <canvas>.
 *
 * O porquê do canvas (não mask-image direto no <video>) é o mesmo do hero
 * da home: nesta implementação, aplicar a máscara direto num <video> não
 * recorta o quadro decodificado -- só a caixa do elemento. Ver mc-cine.js.
 */
(function (raiz) {
  'use strict';

  /* Mesma função do hero da home: `larguraTexto` já vem medida
   * (measureText, mesma fonte/peso), então o viewBox nasce do tamanho real
   * do texto -- nunca corta M inicial nem Ã/O final internamente, antes
   * mesmo do mask-size entrar em jogo. Ver mc-cine.js para o porquê de não
   * ter <rect> de fundo. */
  function mascaraDaPalavra(texto, larguraTexto, opcoes) {
    opcoes = opcoes || {};
    var tamanhoFonte = opcoes.tamanhoFonte || 280;
    var familia = opcoes.familia || 'Georgia, "Times New Roman", serif';
    var margem = opcoes.margem != null ? opcoes.margem : Math.round(tamanhoFonte * 0.28);
    var alturaViewBox = opcoes.alturaViewBox || Math.round(tamanhoFonte * 1.55);
    var larguraViewBox = Math.max(1, Math.ceil(larguraTexto + margem * 2));
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 " + larguraViewBox + " " + alturaViewBox + "'>" +
      "<text x='" + (larguraViewBox / 2) + "' y='" + Math.round(alturaViewBox * 0.72) + "' text-anchor='middle' " +
      "font-family='" + familia + "' font-weight='700' " +
      "font-size='" + tamanhoFonte + "' letter-spacing='2' fill='white'>" + texto + "</text></svg>";
    return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
  }

  function retanguloCover(cw, ch, vw, vh) {
    var escala = Math.max(cw / vw, ch / vh);
    var dw = vw * escala, dh = vh * escala;
    return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw: dw, dh: dh };
  }

  var api = { mascaraDaPalavra: mascaraDaPalavra, retanguloCover: retanguloCover };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var wrap = doc.getElementById('liteWord');
  var video = doc.getElementById('liteVideo');
  var canvas = doc.getElementById('liteCanvas');
  if (!wrap || !video || !canvas) return;

  var reduzido = raiz.matchMedia && raiz.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduzido) return; // CSS já esconde .mc-lite-hero neste caso

  var TEXTO = 'MARANHÃO';
  var FAMILIA = 'Georgia, "Times New Roman", serif';
  var TAMANHO_FONTE = 280;

  function medirLarguraTexto(texto, tamanhoFonte, familia) {
    var medidor = doc.createElement('canvas').getContext('2d');
    medidor.font = "700 " + tamanhoFonte + "px " + familia;
    return medidor.measureText(texto).width + 2 * Math.max(0, texto.length - 1);
  }

  var larguraMedida = medirLarguraTexto(TEXTO, TAMANHO_FONTE, FAMILIA);
  var url = mascaraDaPalavra(TEXTO, larguraMedida, { tamanhoFonte: TAMANHO_FONTE, familia: FAMILIA });
  canvas.style.webkitMaskImage = url;
  canvas.style.maskImage = url;

  var ctx = canvas.getContext('2d', { alpha: false });
  var dpr = Math.min(raiz.devicePixelRatio || 1, 2);
  var pronto = false;

  function redimensionarCanvas() {
    var caixa = canvas.getBoundingClientRect();
    if (!caixa.width || !caixa.height) return;
    canvas.width = Math.round(caixa.width * dpr);
    canvas.height = Math.round(caixa.height * dpr);
  }

  function desenharQuadro() {
    if (!video.videoWidth || !canvas.width) return;
    var r = retanguloCover(canvas.width, canvas.height, video.videoWidth, video.videoHeight);
    ctx.drawImage(video, r.dx, r.dy, r.dw, r.dh);
    if (!pronto) { pronto = true; wrap.classList.add('is-ready'); }
  }

  function loopQuadros() {
    desenharQuadro();
    if (video.requestVideoFrameCallback) {
      video.requestVideoFrameCallback(loopQuadros);
    } else {
      raiz.requestAnimationFrame(loopQuadros);
    }
  }

  function iniciarQuandoPronto() {
    redimensionarCanvas();
    loopQuadros();
  }
  if (video.readyState >= 2) {
    iniciarQuandoPronto();
  } else {
    video.addEventListener('loadeddata', iniciarQuandoPronto, { once: true });
  }

  var redimensionarPendente = null;
  raiz.addEventListener('resize', function () {
    if (redimensionarPendente) raiz.clearTimeout(redimensionarPendente);
    redimensionarPendente = raiz.setTimeout(redimensionarCanvas, 150);
  }, { passive: true });

  // Revelação curta ao entrar na tela -- sem pin, sem scrub, sem GSAP (não é
  // necessário para um fade + leve escala que dispara uma vez só).
  function revelar() {
    wrap.classList.add('is-visible');
  }

  function jaNaTela() {
    var r = wrap.getBoundingClientRect();
    var alturaJanela = raiz.innerHeight || doc.documentElement.clientHeight;
    return r.top < alturaJanela && r.bottom > 0;
  }

  if (jaNaTela()) {
    // A seção normalmente já nasce visível (fica logo no topo da página) --
    // resolve sem esperar o observer, que em alguns motores não dispara
    // para um elemento que já está na tela no instante em que observe()
    // é chamado (comportamento documentado do IntersectionObserver em
    // certas versões de navegador).
    revelar();
  } else if (raiz.IntersectionObserver) {
    var obs = new raiz.IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          revelar();
          obs.unobserve(wrap);
        }
      });
    }, { threshold: 0.2 });
    obs.observe(wrap);
    // Rede de segurança: se por qualquer motivo o observer nunca disparar,
    // o conteúdo não pode ficar invisível para sempre.
    raiz.setTimeout(revelar, 2500);
  } else {
    revelar();
  }
})(typeof window !== 'undefined' ? window : globalThis);
