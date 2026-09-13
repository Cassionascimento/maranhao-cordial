/* Player discreto do álbum GINGA — Five Moments, embutido na homepage.
   Áudio local (mesmos arquivos do projeto, sem serviço externo novo),
   um <audio> só, troca de src por faixa. Nenhum estado é enviado a
   nenhum backend -- puramente client-side.

   Autoplay: navegadores bloqueiam áudio com som antes de um gesto real
   do usuário. Este player nunca tenta contornar isso -- fica pronto
   (primeira faixa carregada, pausada) e só começa a tocar sozinho no
   primeiro gesto genuíno em qualquer lugar da página (clique/toque/tecla
   fora dos próprios controles, que já têm sua intenção explícita). */
(() => {
  'use strict';
  const player = document.getElementById('mc-player');
  if (!player) return;

  const TRACKS = [
    { titulo: 'Black Ginga', src: 'audio/five-moments/01-black-ginga.mp3' },
    { titulo: 'Rhythm of That Look', src: 'audio/five-moments/02-rhythm-of-that-look.wav' },
    { titulo: 'Quimbara Cumba', src: 'audio/five-moments/03-quimbara-cumba.mp3' },
    { titulo: 'Maranhão en el Alma', src: 'audio/five-moments/04-maranhao-en-el-alma.mp3' },
    { titulo: 'Maranhão Cordial', src: 'audio/five-moments/05-maranhao-cordial.mp3' },
  ];
  const PASSO_VOLUME = 0.1;

  const audio = document.getElementById('mc-audio');
  const btnPlayPause = document.getElementById('mc-playpause');
  const btnPrev = document.getElementById('mc-prev');
  const btnNext = document.getElementById('mc-next');
  const btnVolDown = document.getElementById('mc-vol-down');
  const btnVolUp = document.getElementById('mc-vol-up');
  const rotuloFaixa = document.getElementById('mc-track');
  if (!audio || !btnPlayPause || !btnPrev || !btnNext || !btnVolDown || !btnVolUp || !rotuloFaixa) return;

  let indiceAtual = 0;
  let jaIniciouPeloGesto = false;

  function carregarFaixa(indice, { autoplay } = {}) {
    indiceAtual = ((indice % TRACKS.length) + TRACKS.length) % TRACKS.length;
    const faixa = TRACKS[indiceAtual];
    audio.src = faixa.src;
    rotuloFaixa.textContent = faixa.titulo;
    if (autoplay) {
      audio.play().catch(() => { /* gesto insuficiente -- fica pronto, sem forçar */ });
    }
  }

  function atualizarBotaoPlayPause() {
    const tocando = !audio.paused && !audio.ended;
    btnPlayPause.textContent = tocando ? '⏸' : '▶';
    btnPlayPause.setAttribute('aria-label', tocando ? 'Pausar' : 'Tocar');
    btnPlayPause.setAttribute('aria-pressed', String(tocando));
  }

  function alternarPlayPause() {
    if (!audio.src) carregarFaixa(0);
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }

  btnPlayPause.addEventListener('click', alternarPlayPause);
  btnPrev.addEventListener('click', () => carregarFaixa(indiceAtual - 1, { autoplay: true }));
  btnNext.addEventListener('click', () => carregarFaixa(indiceAtual + 1, { autoplay: true }));
  btnVolDown.addEventListener('click', () => { audio.volume = Math.max(0, audio.volume - PASSO_VOLUME); });
  btnVolUp.addEventListener('click', () => { audio.volume = Math.min(1, audio.volume + PASSO_VOLUME); });

  audio.addEventListener('play', atualizarBotaoPlayPause);
  audio.addEventListener('pause', atualizarBotaoPlayPause);
  // Ao terminar uma faixa, toca a próxima automaticamente; depois da
  // última, volta à primeira (mesmo comportamento de carregarFaixa, que
  // já é circular).
  audio.addEventListener('ended', () => carregarFaixa(indiceAtual + 1, { autoplay: true }));

  audio.volume = 0.7;
  carregarFaixa(0);
  atualizarBotaoPlayPause();

  // Primeiro gesto genuíno em qualquer lugar da página (fora do próprio
  // player, que já trata seu clique como intenção explícita) inicia a
  // experiência musical -- nunca antes disso, nunca via truque de autoplay.
  document.addEventListener('click', (evento) => {
    if (jaIniciouPeloGesto || (audio.currentTime > 0 && !audio.paused)) return;
    if (evento.target.closest('#mc-player')) return;
    jaIniciouPeloGesto = true;
    audio.play().catch(() => {});
  }, { capture: true });
})();
