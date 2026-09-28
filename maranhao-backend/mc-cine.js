/* Hero cinematográfico da página inicial: "MARANHÃO" como porta de entrada
 * para o vídeo (o mesmo de sempre, nunca recarregado), que rapidamente
 * ocupa a tela inteira -- SEM nunca esticar nem cortar letra nenhuma.
 *
 * Como o vídeo é desenhado: um <canvas> cobre a tela inteira desde o
 * primeiro frame (nunca é redimensionado por CSS transform -- por isso
 * nunca perde nitidez nem proporção) e desenha o quadro atual do <video>
 * (invisível, só alimentando frames) sempre com recorte tipo "cover",
 * calculado à mão (retanguloCover) -- o vídeo NUNCA é deformado.
 *
 * Como a "letra" funciona: a máscara aplicada ao canvas é só o tamanho
 * (mask-size, em px) de um SVG isolado cuja LARGURA é medida em tempo real
 * (measureText, com a mesma fonte/peso) -- garante que "MARANHÃO" nunca
 * seja cortado nas pontas (M inicial, Ã/O final), em nenhuma largura de
 * tela. O ponto de partida já é grande o bastante para ter presença visual
 * imediata (sem tela preta arrastada); um scroll pequeno faz a máscara
 * crescer e, rapidamente, desaparecer -- o vídeo passa a ocupar a tela
 * inteira, com tempo de sobra antes da legenda e da transição para o
 * produto.
 *
 * Sem GSAP/ScrollTrigger (bloqueado, offline, falha de rede) ou com
 * prefers-reduced-motion, cai para o hero estático de sempre (.mc-cine-
 * fallback, já no HTML) e garante que o resto do conteúdo não fique
 * escondido esperando uma animação que não vai rodar.
 */
(function (raiz) {
  'use strict';

  /* SVG isolado (não lê fontes do documento). `larguraTexto` já vem medida
   * (measureText, na mesma fonte/peso) -- o viewBox nasce exatamente do
   * tamanho real do texto mais uma margem, então a própria máscara nunca
   * corta a palavra internamente (o bug original: um viewBox fixo mais
   * estreito que o texto cortava M inicial e Ã/O final na origem, antes
   * mesmo de qualquer escala entrar em jogo).
   *
   * Sem <rect> de fundo, de propósito: mask-image usa o CANAL ALPHA por
   * padrão para uma imagem comum (mask-mode: match-source). Um retângulo
   * opaco atrás do texto teria alpha=1 em toda a área -- a "máscara"
   * mostraria o retângulo inteiro, sem recorte nenhum. Só a letra tem
   * alpha > 0; o resto do SVG fica transparente. */
  function mascaraDaPalavra(texto, larguraTexto, opcoes) {
    opcoes = opcoes || {};
    var tamanhoFonte = opcoes.tamanhoFonte || 300;
    var familia = opcoes.familia || 'Georgia, "Times New Roman", serif';
    var margem = opcoes.margem != null ? opcoes.margem : Math.round(tamanhoFonte * 0.28);
    var alturaViewBox = opcoes.alturaViewBox || Math.round(tamanhoFonte * 1.55);
    var larguraViewBox = Math.max(1, Math.ceil(larguraTexto + margem * 2));
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 " + larguraViewBox + " " + alturaViewBox + "'>" +
      "<text x='" + (larguraViewBox / 2) + "' y='" + Math.round(alturaViewBox * 0.72) + "' text-anchor='middle' " +
      "font-family='" + familia + "' font-weight='700' " +
      "font-size='" + tamanhoFonte + "' letter-spacing='2' fill='white'>" + texto + "</text></svg>";
    return {
      url: 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")',
      proporcao: larguraViewBox / alturaViewBox,
    };
  }

  /* object-fit: cover, calculado à mão -- é o que o <canvas> usa para
   * desenhar o quadro do vídeo (drawImage não tem essa opção nativa).
   * Escala SEMPRE uniforme (mesmo fator nos dois eixos) -- o vídeo nunca
   * é esticado. */
  function retanguloCover(cw, ch, vw, vh) {
    var escala = Math.max(cw / vw, ch / vh);
    var dw = vw * escala, dh = vh * escala;
    return { dx: (cw - dw) / 2, dy: (ch - dh) / 2, dw: dw, dh: dh };
  }

  /* Maior largura (em px de tela) que a máscara pode ter sem que a palavra
   * ultrapasse a viewport -- testa os dois eixos (largura E altura
   * disponíveis), porque numa tela estreita e alta (celular) é a altura
   * que primeiro limita uma palavra larga e baixa como esta. */
  function larguraSeguraDoMask(proporcao, viewportW, viewportH, margemLateral, margemVertical, maximo) {
    var porLargura = Math.max(0, viewportW - margemLateral * 2);
    var porAltura = Math.max(0, viewportH - margemVertical * 2) * proporcao;
    var largura = Math.min(porLargura, porAltura);
    if (maximo) largura = Math.min(largura, maximo);
    return Math.max(60, largura);
  }

  var api = { mascaraDaPalavra: mascaraDaPalavra, retanguloCover: retanguloCover, larguraSeguraDoMask: larguraSeguraDoMask };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  var doc = raiz.document;
  var pin = doc.getElementById('cinePin');
  var video = doc.getElementById('cineVideo');
  var canvas = doc.getElementById('cineCanvas');
  var legenda = doc.getElementById('cineCaption');
  var produtoImg = doc.getElementById('cineProdutoImg');
  var produtoCopy = doc.getElementById('cineProdutoCopy');
  if (!pin || !video || !canvas) return;

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

  var TEXTO = 'MARANHÃO';
  var FAMILIA = 'Georgia, "Times New Roman", serif';
  var TAMANHO_FONTE = 300;

  function medirLarguraTexto(texto, tamanhoFonte, familia) {
    var medidor = doc.createElement('canvas').getContext('2d');
    medidor.font = "700 " + tamanhoFonte + "px " + familia;
    var largura = medidor.measureText(texto).width;
    return largura + 2 * Math.max(0, texto.length - 1); // letter-spacing: 2, por caractere
  }

  var larguraTextoMedida = medirLarguraTexto(TEXTO, TAMANHO_FONTE, FAMILIA);
  var mascara = mascaraDaPalavra(TEXTO, larguraTextoMedida, { tamanhoFonte: TAMANHO_FONTE, familia: FAMILIA });

  function margensSeguras() {
    var estreito = raiz.innerWidth <= 720;
    return { lateral: estreito ? 22 : 44, vertical: estreito ? 30 : 40 };
  }

  // "Monumental, mas cabe perfeitamente": 96% do maior tamanho seguro --
  // não 100%, para sobrar uma folga mínima de arredondamento.
  function larguraMonumental() {
    var m = margensSeguras();
    return larguraSeguraDoMask(mascara.proporcao, raiz.innerWidth, raiz.innerHeight, m.lateral, m.vertical) * 0.96;
  }

  // O teto exato (sem a folga de 4% do "monumental" de repouso): usado só
  // como alvo da FASE 2, que precisa crescer um pouco mas sem NUNCA sair da
  // área segura -- nenhuma letra pode ultrapassar a viewport nessa fase.
  function larguraSeguraMaxima() {
    var m = margensSeguras();
    return larguraSeguraDoMask(mascara.proporcao, raiz.innerWidth, raiz.innerHeight, m.lateral, m.vertical);
  }

  function larguraFullscreen() {
    return Math.max(raiz.innerWidth, raiz.innerHeight) * 2;
  }

  var mascaraAtiva = true;
  function aplicarLarguraMask(px) {
    var limite = larguraFullscreen() * 0.9;
    var deveTerMascara = px < limite;
    if (deveTerMascara !== mascaraAtiva) {
      mascaraAtiva = deveTerMascara;
      var valor = deveTerMascara ? mascara.url : 'none';
      canvas.style.webkitMaskImage = valor;
      canvas.style.maskImage = valor;
    }
    if (deveTerMascara) {
      var tamanho = Math.round(px) + 'px auto';
      canvas.style.webkitMaskSize = tamanho;
      canvas.style.maskSize = tamanho;
    }
  }

  canvas.style.webkitMaskImage = mascara.url;
  canvas.style.maskImage = mascara.url;
  aplicarLarguraMask(larguraMonumental());

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

  function desenharQuadro() {
    if (!video.videoWidth || !canvas.width) return;
    var r = retanguloCover(canvas.width, canvas.height, video.videoWidth, video.videoHeight);
    ctx.drawImage(video, r.dx, r.dy, r.dw, r.dh);
    if (!pronto) { pronto = true; canvas.classList.add('is-ready'); }
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

  var estadoAnimacao = { largura: larguraMonumental() };
  var redimensionarPendente = null;
  raiz.addEventListener('resize', function () {
    if (redimensionarPendente) raiz.clearTimeout(redimensionarPendente);
    redimensionarPendente = raiz.setTimeout(function () {
      redimensionarCanvas();
      // Se o scroll ainda não começou, a largura "monumental" precisa
      // acompanhar o novo tamanho de tela (rotação de celular, por ex.).
      if (!raiz.ScrollTrigger || !raiz.ScrollTrigger.getAll().length || raiz.scrollY < 4) {
        estadoAnimacao.largura = larguraMonumental();
        aplicarLarguraMask(estadoAnimacao.largura);
      }
    }, 150);
  }, { passive: true });

  // ----------------------------------------------------------------- scroll
  if (!raiz.gsap || !raiz.ScrollTrigger) {
    // A palavra fica estática, grande e inteira, com o vídeo visível dentro
    // dela (sem zoom), e o produto aparece direto -- degradação funcional,
    // nunca conteúdo preso.
    mostrarProdutoSemAnimacao();
    return;
  }

  var gsap = raiz.gsap;
  gsap.registerPlugin(raiz.ScrollTrigger);

  function atualizarMask() {
    aplicarLarguraMask(estadoAnimacao.largura);
  }

  var tlHero = gsap.timeline({
    scrollTrigger: {
      trigger: pin,
      start: 'top top',
      end: '+=160%',
      scrub: 0.6,
      pin: true,
      anticipatePin: 1,
    },
  });

  tlHero
    // FASE 1 (0): MARANHÃO grande e inteiro, vídeo já visível dentro dela.
    // FASE 2 (0 -> 0.12): pequeno scroll, o vídeo ganha presença -- cresce
    // só até o teto seguro (larguraSeguraMaxima), nunca além: nenhuma letra
    // pode sair da viewport enquanto a palavra ainda está legível.
    .to(estadoAnimacao, { largura: larguraSeguraMaxima, duration: 0.12, ease: 'power1.out', onUpdate: atualizarMask }, 0)
    // FASE 3 (0.12 -> 0.30): a máscara se expande rápido e "some" -- a
    // sensação de atravessar a palavra. É uma passagem rápida e curta (não
    // um estado de repouso): ao ultrapassar o limite (dentro de
    // aplicarLarguraMask), o vídeo passa a ocupar a viewport inteira,
    // sempre com a proporção original (o canvas nunca é esticado).
    .to(estadoAnimacao, { largura: function () { return larguraFullscreen(); }, duration: 0.18, ease: 'power3.in', onUpdate: atualizarMask }, 0.12)
    // FASE 4: vídeo em tela cheia, com tempo de sobra (0.42 -> 0.90) antes
    // da legenda -- que fica discreta e no terço inferior, sem cobrir o
    // centro do quadro. O canvas fica de fora desta tween: assim que o GSAP
    // toca `opacity` de um elemento ele passa a controlar essa propriedade
    // via estilo inline dali em diante (mesmo antes da tween "começar" no
    // scrub) -- e isso sobrescreveria para sempre a transição por CSS
    // `.mc-cine-canvas.is-ready { opacity: 1 }` que revela o primeiro
    // quadro, deixando a tela preta pra sempre. O vídeo simplesmente rola
    // junto com o pin ao final -- não precisa desaparecer sozinho.
    .to(legenda, { opacity: 1, duration: 0.1, ease: 'none' }, 0.58)
    .to(legenda, { opacity: 0, duration: 0.1, ease: 'none' }, 0.9);

  if (produtoImg && produtoCopy) {
    // FASE 5: só agora território dá lugar ao produto.
    gsap.timeline({
      scrollTrigger: { trigger: produtoImg, start: 'top 82%', end: 'top 38%', scrub: 0.5 },
    })
      .fromTo(produtoImg, { opacity: 0, y: 28, scale: 0.96 },
        { opacity: 1, y: 0, scale: 1, ease: 'power2.out', duration: 1 }, 0)
      .fromTo(produtoCopy, { opacity: 0, y: 20, scale: 0.98 },
        { opacity: 1, y: 0, scale: 1, ease: 'power2.out', duration: 1 }, 0.15);
  }

  /* Microinteração desktop: o quadro (canvas) segue o mouse por poucos
   * pixels antes do scroll começar -- por isso o canvas nasce um pouco
   * maior que a tela (ver CSS), pra sobrar margem sem revelar borda. Nada
   * disso roda em toque/mobile (sem hover fino) nem distorce o vídeo -- só
   * translada o elemento, nunca escala nem inclina. */
  var suportaHoverFino = raiz.matchMedia && raiz.matchMedia('(hover: hover) and (pointer: fine)').matches;
  if (suportaHoverFino) {
    var LIMITE_PX = 6;
    var moverX = gsap.quickTo(canvas, 'x', { duration: 0.7, ease: 'power3.out' });
    var moverY = gsap.quickTo(canvas, 'y', { duration: 0.7, ease: 'power3.out' });
    doc.addEventListener('mousemove', function (evento) {
      var cx = raiz.innerWidth / 2;
      var cy = raiz.innerHeight / 2;
      moverX(((evento.clientX - cx) / cx) * LIMITE_PX);
      moverY(((evento.clientY - cy) / cy) * LIMITE_PX);
    }, { passive: true });
  }
})(typeof window !== 'undefined' ? window : globalThis);
