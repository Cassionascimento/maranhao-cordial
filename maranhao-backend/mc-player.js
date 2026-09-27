/* Player discreto do álbum GINGA — Five Moments, compartilhado pela
   página inicial e por "Compre aqui". Áudio local (mesmos arquivos do
   projeto, sem serviço externo novo), um <audio> só, troca de src por
   faixa. Nenhum estado é enviado a nenhum backend -- puramente
   client-side.

   Autoplay: navegadores bloqueiam áudio com som antes de um gesto real
   do usuário. Este player nunca tenta contornar isso -- fica pronto
   (faixa carregada, pausada) e só começa a tocar sozinho no primeiro
   gesto genuíno em qualquer lugar da página (clique/toque/tecla fora
   dos próprios controles, que já têm sua intenção explícita).

   Persistência entre páginas: como a navegação entre index.html e
   compreaqui.html recarrega o documento por completo (sem SPA aqui),
   não existe um único <audio> contínuo tocando sem interrupção -- isso
   exigiria reestruturar o site inteiro em uma aplicação de página única,
   o que não foi pedido. O que É possível e É feito: faixa, posição e
   volume são salvos em localStorage a cada poucos segundos e ao sair da
   página, e a página seguinte retoma dali no primeiro gesto do
   visitante. Se o áudio estava tocando ao navegar, a retomada é
   automática nesse mesmo primeiro gesto; nunca antes disso. */
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
  const CHAVE_ESTADO = 'mc-player-estado-v1';

  const audio = document.getElementById('mc-audio');
  const btnPlayPause = document.getElementById('mc-playpause');
  const btnPrev = document.getElementById('mc-prev');
  const btnNext = document.getElementById('mc-next');
  const btnVolDown = document.getElementById('mc-vol-down');
  const btnVolUp = document.getElementById('mc-vol-up');
  const rotuloFaixa = document.getElementById('mc-track');
  const progresso = document.getElementById('mc-progress');
  if (!audio || !btnPlayPause || !btnPrev || !btnNext || !btnVolDown || !btnVolUp || !rotuloFaixa) return;

  function lerEstadoSalvo() {
    try {
      const bruto = window.localStorage.getItem(CHAVE_ESTADO);
      if (!bruto) return null;
      const estado = JSON.parse(bruto);
      if (!estado || typeof estado !== 'object') return null;
      return estado;
    } catch (e) {
      return null; // storage bloqueado/indisponível -- player continua funcionando do zero
    }
  }

  function salvarEstado(extra) {
    try {
      window.localStorage.setItem(CHAVE_ESTADO, JSON.stringify(Object.assign({
        indice: indiceAtual,
        tempo: audio.currentTime || 0,
        volume: audio.volume,
        tocando: !audio.paused && !audio.ended,
      }, extra)));
    } catch (e) { /* sem storage disponível: só não persiste entre páginas */ }
  }

  const estadoSalvo = lerEstadoSalvo();
  let indiceAtual = 0;
  let jaIniciouPeloGesto = false;
  // Sem estado salvo (primeira visita), o comportamento é o de sempre: o
  // primeiro gesto na página começa a tocar. Com estado salvo, só retoma
  // se a pessoa estava mesmo ouvindo quando saiu -- se ela pausou antes
  // de navegar, a próxima página respeita isso e não volta a tocar sozinha.
  let retomarTocando = true;
  let tempoParaRetomar = 0;

  function formatarTempo(segundos) {
    if (!isFinite(segundos) || segundos < 0) return '0:00';
    const m = Math.floor(segundos / 60);
    const s = Math.floor(segundos % 60);
    return m + ':' + String(s).padStart(2, '0');
  }

  function carregarFaixa(indice, { autoplay, tempoInicial } = {}) {
    indiceAtual = ((indice % TRACKS.length) + TRACKS.length) % TRACKS.length;
    const faixa = TRACKS[indiceAtual];
    audio.src = faixa.src;
    rotuloFaixa.textContent = faixa.titulo;
    if (progresso) { progresso.value = '0'; progresso.setAttribute('aria-valuetext', '0:00'); }
    if (tempoInicial) {
      const retomar = () => { audio.currentTime = tempoInicial; audio.removeEventListener('loadedmetadata', retomar); };
      audio.addEventListener('loadedmetadata', retomar);
    }
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
  btnVolDown.addEventListener('click', () => { audio.volume = Math.max(0, Math.round((audio.volume - PASSO_VOLUME) * 10) / 10); });
  btnVolUp.addEventListener('click', () => { audio.volume = Math.min(1, Math.round((audio.volume + PASSO_VOLUME) * 10) / 10); });

  audio.addEventListener('play', atualizarBotaoPlayPause);
  audio.addEventListener('pause', atualizarBotaoPlayPause);
  audio.addEventListener('volumechange', () => salvarEstado());
  // Ao terminar uma faixa, toca a próxima automaticamente; depois da
  // última, volta à primeira (mesmo comportamento de carregarFaixa, que
  // já é circular).
  audio.addEventListener('ended', () => carregarFaixa(indiceAtual + 1, { autoplay: true }));

  if (progresso) {
    audio.addEventListener('timeupdate', () => {
      if (!audio.duration || progresso.matches(':active')) return;
      progresso.value = String(Math.floor((audio.currentTime / audio.duration) * 1000));
      progresso.setAttribute('aria-valuetext', formatarTempo(audio.currentTime) + ' de ' + formatarTempo(audio.duration));
    });
    progresso.addEventListener('input', () => {
      if (!audio.duration) return;
      audio.currentTime = (Number(progresso.value) / 1000) * audio.duration;
    });
  }

  // Salva periodicamente (não só a cada timeupdate, que dispara demais) e
  // ao sair da página -- é o que permite a próxima página retomar do
  // mesmo ponto.
  window.setInterval(() => salvarEstado(), 4000);
  window.addEventListener('pagehide', () => salvarEstado());
  window.addEventListener('beforeunload', () => salvarEstado());

  if (estadoSalvo && Number.isInteger(estadoSalvo.indice) && estadoSalvo.indice >= 0 && estadoSalvo.indice < TRACKS.length) {
    audio.volume = typeof estadoSalvo.volume === 'number' ? Math.min(1, Math.max(0, estadoSalvo.volume)) : 0.7;
    retomarTocando = !!estadoSalvo.tocando;
    tempoParaRetomar = typeof estadoSalvo.tempo === 'number' ? estadoSalvo.tempo : 0;
    carregarFaixa(estadoSalvo.indice, { tempoInicial: tempoParaRetomar });
  } else {
    audio.volume = 0.7;
    carregarFaixa(0);
  }
  atualizarBotaoPlayPause();

  // Primeiro gesto genuíno em qualquer lugar da página (fora do próprio
  // player, que já trata seu clique como intenção explícita) inicia a
  // experiência musical -- nunca antes disso, nunca via truque de autoplay.
  // Se a pessoa veio de outra página do site com a música tocando, este
  // mesmo gesto é o que retoma a reprodução de onde parou.
  document.addEventListener('click', (evento) => {
    if (jaIniciouPeloGesto || (audio.currentTime > 0 && !audio.paused)) return;
    if (evento.target.closest('#mc-player')) return;
    jaIniciouPeloGesto = true;
    if (retomarTocando) audio.play().catch(() => {});
  }, { capture: true });
})();
