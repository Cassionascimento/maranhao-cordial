/* Hero cinematográfico da página inicial: "MARANHÃO" como máscara de vídeo,
 * ampliada pelo scroll até virar o vídeo em tela cheia, seguida da legenda e
 * da chegada do produto (garrafas/sabores já existentes).
 *
 * Um vídeo só (o mesmo de sempre), nunca recarregado: o scroll escala o
 * ELEMENTO que contém a máscara (transform: scale), não o vídeo -- o
 * arquivo continua tocando uma vez só, decodificado uma vez só.
 *
 * Por que um <canvas> no meio: aplicar mask-image direto num <video> não
 * recorta o quadro decodificado de forma confiável (testado nesta
 * implementação -- a máscara "pega" na caixa do elemento, mas o quadro em
 * si continua aparecendo inteiro, sem o recorte). O vídeo real fica
 * invisível só alimentando quadros; quem recebe a máscara é o canvas, que
 * desenha o quadro atual a cada requestVideoFrameCallback (ou
 * requestAnimationFrame, onde aquele não existir) -- sem redesenhar quando
 * o quadro não mudou.
 *
 * Sem GSAP/ScrollTrigger (bloqueado, offline, falha de rede) ou com
 * prefers-reduced-motion, cai para o hero estático de sempre (.mc-cine-
 * fallback, já no HTML) e garante que o resto do conteúdo não fique
 * escondido esperando uma animação que não vai rodar.
 */
(function (raiz) {
  'use strict';

  /* SVG isolado (não lê fontes do documento): usa uma pilha serifada do
   * sistema para nascer correta em qualquer navegador, sem depender do
   * Cormorant Garamond terminar de carregar primeiro.
   *
   * Sem <rect> de fundo, de propósito: mask-image usa o CANAL ALPHA por
   * padrão para uma imagem comum (mask-mode: match-source). Um retângulo
   * opaco atrás do texto teria alpha=1 em toda a área -- a "máscara"
   * mostraria o quadrado inteiro, sem recorte nenhum. Só a letra tem
   * alpha > 0; o resto do SVG fica transparente. */
  function mascaraDaPalavra(texto) {
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1600 500'>" +
      "<text x='800' y='372' text-anchor='middle' " +
      "font-family='Georgia, \"Times New Roman\", serif' font-weight='700' " +
      "font-size='300' letter-spacing='2' fill='white'>" + texto + "</text></svg>";
    return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
  }

  /* object-fit: cover, calculado à mão -- é o que o <canvas> usa para
   * desenhar o quadro do vídeo (drawImage não tem essa opção nativa). */
  function retanguloCover(cw, ch, vw, vh) {
    var escala = Math.max(cw / vw, ch / vh);
    var dw = vw * escala, dh = vh * escala;
    return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw: dw, dh: dh };
  }

  var api = { mascaraDaPalavra: mascaraDaPalavra, retanguloCover: retanguloCover };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var secao = doc.getElementById('maranhao-cordial');
  var pin = doc.getElementById('cinePin');
  var palavra = doc.getElementById('cineWord');
  var video = doc.getElementById('cineVideo');
  var canvas = doc.getElementById('cineCanvas');
  var legenda = doc.getElementById('cineCaption');
  var produtoImg = doc.getElementById('cineProdutoImg');
  var produtoCopy = doc.getElementById('cineProdutoCopy');
  if (!secao || !pin || !palavra || !video || !canvas) return;

  function mostrarProdutoSemAnimacao() {
    [produtoImg, produtoCopy].forEach(function (el) {
      if (!el) return;
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
  }

  var reduzido = raiz.matchMedia && raiz.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduzido) {
    // O CSS já troca para .mc-cine-fallback; só falta garantir que o
    // restante da narrativa (garrafas/sabores) não dependa do scroll-reveal.
    mostrarProdutoSemAnimacao();
    return;
  }

  canvas.style.webkitMaskImage = mascaraDaPalavra('MARANHÃO');
  canvas.style.maskImage = mascaraDaPalavra('MARANHÃO');

  // ---------------------------------------------------------- canvas <- vídeo
  var ctx = canvas.getContext('2d', { alpha: false });
  var dpr = Math.min(raiz.devicePixelRatio || 1, 2);
  var pronto = false;

  function redimensionarCanvas() {
    var caixa = canvas.getBoundingClientRect();
    if (!caixa.width || !caixa.height) return;
    canvas.width = Math.round(caixa.width * dpr);
    canvas.height = Math.round(caixa.height * dpr);
  }

  /* Emula object-fit: cover manualmente -- o canvas não tem essa opção
   * nativa para drawImage, então a mesma matemática é feita à mão. */
  function desenharQuadro() {
    if (!video.videoWidth || !canvas.width) return;
    var r = retanguloCover(canvas.width, canvas.height, video.videoWidth, video.videoHeight);
    ctx.drawImage(video, r.dx, r.dy, r.dw, r.dh);
    if (!pronto) { pronto = true; palavra.classList.add('is-ready'); }
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

  // ----------------------------------------------------------------- scroll
  if (!raiz.gsap || !raiz.ScrollTrigger) {
    // A palavra fica estática (com o vídeo visível dentro dela, sem zoom) e
    // o produto aparece direto -- degradação funcional, nunca conteúdo preso.
    mostrarProdutoSemAnimacao();
    return;
  }

  var gsap = raiz.gsap;
  gsap.registerPlugin(raiz.ScrollTrigger);

  var tlHero = gsap.timeline({
    scrollTrigger: {
      trigger: pin,
      start: 'top top',
      end: '+=220%',
      scrub: 0.6,
      pin: true,
      anticipatePin: 1,
    },
  });

  tlHero
    .fromTo(palavra, { scale: 1 }, { scale: 22, ease: 'power1.in', duration: 1 }, 0)
    .to(legenda, { opacity: 1, duration: 0.16, ease: 'none' }, 0.72)
    .to(legenda, { opacity: 1, duration: 0.12 }, 0.88)
    .to([palavra, legenda], { opacity: 0, duration: 0.1, ease: 'none' }, 0.97);

  if (produtoImg && produtoCopy) {
    gsap.timeline({
      scrollTrigger: { trigger: produtoImg, start: 'top 82%', end: 'top 38%', scrub: 0.5 },
    })
      .fromTo(produtoImg, { opacity: 0, y: 28, scale: 0.96 },
        { opacity: 1, y: 0, scale: 1, ease: 'power2.out', duration: 1 }, 0)
      .fromTo(produtoCopy, { opacity: 0, y: 20, scale: 0.98 },
        { opacity: 1, y: 0, scale: 1, ease: 'power2.out', duration: 1 }, 0.15);
  }

  /* Microinteração desktop: a palavra segue o mouse por poucos pixels antes
   * do scroll começar. Nada disso roda em toque/mobile (sem hover fino) nem
   * distorce as letras -- só translada o retângulo que já existe. */
  var suportaHoverFino = raiz.matchMedia && raiz.matchMedia('(hover: hover) and (pointer: fine)').matches;
  if (suportaHoverFino) {
    var LIMITE_PX = 6;
    var moverX = gsap.quickTo(palavra, 'x', { duration: 0.7, ease: 'power3.out' });
    var moverY = gsap.quickTo(palavra, 'y', { duration: 0.7, ease: 'power3.out' });
    doc.addEventListener('mousemove', function (evento) {
      var cx = raiz.innerWidth / 2;
      var cy = raiz.innerHeight / 2;
      moverX(((evento.clientX - cx) / cx) * LIMITE_PX);
      moverY(((evento.clientY - cy) / cy) * LIMITE_PX);
    }, { passive: true });
  }
})(typeof window !== 'undefined' ? window : globalThis);
