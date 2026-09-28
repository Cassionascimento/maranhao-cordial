/* Versão leve do hero cinematográfico da home (mc-cine.js) para "Compre
 * aqui": a mesma linguagem visual -- "MARANHÃO" como janela para um vídeo
 * já existente -- só que sem pin nem zoom por scroll, apenas uma revelação
 * suave ao entrar na tela. Mesmo vídeo de sempre desta página
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

  /* Mesma função do hero da home (mc-cine.js), com um viewBox mais baixo
   * (a versão leve é uma faixa 16:6, não um retângulo cheio de tela) --
   * ver mc-cine.js para o porquê de não ter <rect> de fundo. */
  function mascaraDaPalavra(texto) {
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1600 600'>" +
      "<text x='800' y='430' text-anchor='middle' " +
      "font-family='Georgia, \"Times New Roman\", serif' font-weight='700' " +
      "font-size='280' letter-spacing='2' fill='white'>" + texto + "</text></svg>";
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

  canvas.style.webkitMaskImage = mascaraDaPalavra('MARANHÃO');
  canvas.style.maskImage = mascaraDaPalavra('MARANHÃO');

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

  // Revelação suave ao entrar na tela -- sem pin, sem scrub, sem GSAP (não é
  // necessário para um fade + leve escala que dispara uma vez só).
  if (raiz.IntersectionObserver) {
    var obs = new raiz.IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          wrap.classList.add('is-visible');
          obs.unobserve(wrap);
        }
      });
    }, { threshold: 0.2 });
    obs.observe(wrap);
  } else {
    wrap.classList.add('is-visible');
  }
})(typeof window !== 'undefined' ? window : globalThis);
