const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('maranhao-backend/mc-player.js', 'utf8');

function botao() {
  return { textContent: '', listeners: {}, dataset: {}, className: '',
    setAttribute(nome, valor) { this[nome === 'aria-label' ? '_ariaLabel' : '_ariaPressed'] = valor; },
    addEventListener(evento, fn) { this.listeners[evento] = fn; } };
}

function elFaixa() {
  return { textContent: '' };
}

function audioFake() {
  return {
    src: '', volume: 1, paused: true, ended: false, currentTime: 0, duration: NaN,
    _listeners: {},
    play() { this.paused = false; this._disparar('play'); return Promise.resolve(); },
    pause() { this.paused = true; this._disparar('pause'); },
    addEventListener(evento, fn) { (this._listeners[evento] ||= []).push(fn); },
    _disparar(evento) { for (const fn of (this._listeners[evento] || [])) fn(); },
  };
}

function progressoFake() {
  return { value: '0', _listeners: {},
    setAttribute() {}, matches() { return false; },
    addEventListener(evento, fn) { (this._listeners[evento] ||= []).push(fn); } };
}

/* Mock mínimo de localStorage: mesma API, guardada em memória -- é o que
   permite ao teste rodar sem depender de um navegador de verdade. */
function localStorageFake() {
  const dados = {};
  return {
    getItem: chave => (chave in dados ? dados[chave] : null),
    setItem: (chave, valor) => { dados[chave] = String(valor); },
    removeItem: chave => { delete dados[chave]; },
  };
}

function setup(estadoSalvoInicial) {
  const painel = { closest() { return null; } };
  const elementos = {
    'mc-player': painel,
    'mc-audio': audioFake(),
    'mc-playpause': botao(),
    'mc-prev': botao(),
    'mc-next': botao(),
    'mc-vol-down': botao(),
    'mc-vol-up': botao(),
    'mc-track': elFaixa(),
    'mc-progress': progressoFake(),
  };
  const listenersDocumento = {};
  const document = {
    getElementById: id => elementos[id],
    addEventListener(evento, fn, opts) { listenersDocumento[evento] = {fn, opts}; },
  };
  const localStorage = localStorageFake();
  if (estadoSalvoInicial) localStorage.setItem('mc-player-estado-v1', JSON.stringify(estadoSalvoInicial));
  const listenersWindow = {};
  // window === o mesmo objeto global do sandbox (como num navegador real:
  // window.setInterval, window.addEventListener etc. são os mesmos que os
  // globais soltos) -- setInterval/clearInterval reaproveitam os do Node,
  // só para o código não quebrar; os testes não dependem de o timer disparar.
  const window = {
    localStorage,
    // Sem timer real: o teste não roda 4s de relógio. O código só precisa
    // de uma função que aceite a chamada -- id nunca é usado para limpar.
    setInterval() { return 0; }, clearInterval() {},
    addEventListener(evento, fn) { (listenersWindow[evento] ||= []).push(fn); },
  };
  vm.runInNewContext(code, {document, window});
  return {elementos, listenersDocumento, listenersWindow, localStorage};
}

test('player carrega a primeira faixa (Black Ginga) pronta, pausada, sem autoplay',()=>{
  const {elementos} = setup();
  assert.equal(elementos['mc-track'].textContent, 'Black Ginga');
  assert.equal(elementos['mc-audio'].src, 'audio/five-moments/01-black-ginga.mp3');
  assert.equal(elementos['mc-audio'].paused, true);
});

test('as 5 faixas do album estao na ordem certa, arquivos locais (sem servico externo)',()=>{
  const {elementos} = setup();
  const audio = elementos['mc-audio'];
  const esperadas = [
    'audio/five-moments/01-black-ginga.mp3',
    'audio/five-moments/02-rhythm-of-that-look.wav',
    'audio/five-moments/03-quimbara-cumba.mp3',
    'audio/five-moments/04-maranhao-en-el-alma.mp3',
    'audio/five-moments/05-maranhao-cordial.mp3',
  ];
  const titulos = [];
  const srcs = [];
  for (let i = 0; i < 5; i++) {
    elementos['mc-next'].listeners.click();
    srcs.push(audio.src);
    titulos.push(elementos['mc-track'].textContent);
  }
  // volta ao início (5 next a partir da faixa 1 -> passa por 2,3,4,5,1)
  assert.deepEqual(srcs, [...esperadas.slice(1), esperadas[0]]);
  assert.deepEqual(titulos, ['Rhythm of That Look', 'Quimbara Cumba', 'Maranhão en el Alma', 'Maranhão Cordial', 'Black Ginga']);
  for (const url of [...srcs]) assert.ok(!/^https?:\/\//.test(url), 'nenhum arquivo deve vir de servico externo');
});

test('play/pause alterna estado, label e aria-pressed',()=>{
  const {elementos} = setup();
  const btn = elementos['mc-playpause'];
  assert.equal(btn.textContent, '▶');
  btn.listeners.click();
  assert.equal(elementos['mc-audio'].paused, false);
  assert.equal(btn.textContent, '⏸');
  assert.equal(btn._ariaLabel, 'Pausar');
  assert.equal(btn._ariaPressed, 'true');
  btn.listeners.click();
  assert.equal(elementos['mc-audio'].paused, true);
  assert.equal(btn.textContent, '▶');
  assert.equal(btn._ariaLabel, 'Tocar');
  assert.equal(btn._ariaPressed, 'false');
});

test('proxima e anterior trocam de faixa e continuam tocando automaticamente',()=>{
  const {elementos} = setup();
  elementos['mc-next'].listeners.click();
  assert.equal(elementos['mc-track'].textContent, 'Rhythm of That Look');
  assert.equal(elementos['mc-audio'].paused, false); // continua automaticamente
  elementos['mc-prev'].listeners.click();
  assert.equal(elementos['mc-track'].textContent, 'Black Ginga');
  assert.equal(elementos['mc-audio'].paused, false);
});

test('anterior na primeira faixa volta para a ultima (circular)',()=>{
  const {elementos} = setup();
  elementos['mc-prev'].listeners.click();
  assert.equal(elementos['mc-track'].textContent, 'Maranhão Cordial');
});

test('ao terminar uma faixa, toca a proxima automaticamente',()=>{
  const {elementos} = setup();
  const audio = elementos['mc-audio'];
  audio._disparar('ended');
  assert.equal(elementos['mc-track'].textContent, 'Rhythm of That Look');
  assert.equal(audio.paused, false);
});

test('depois da ultima faixa, terminar retorna a primeira',()=>{
  const {elementos} = setup();
  const audio = elementos['mc-audio'];
  for (let i = 0; i < 4; i++) audio._disparar('ended'); // 1->2->3->4->5
  assert.equal(elementos['mc-track'].textContent, 'Maranhão Cordial');
  audio._disparar('ended'); // 5->1
  assert.equal(elementos['mc-track'].textContent, 'Black Ginga');
});

test('volume +/- ajusta e satura em 0 e 1, nunca sai do intervalo',()=>{
  const {elementos} = setup();
  const audio = elementos['mc-audio'];
  audio.volume = 0.95;
  elementos['mc-vol-up'].listeners.click();
  assert.equal(Math.round(audio.volume * 100) / 100, 1);
  for (let i = 0; i < 20; i++) elementos['mc-vol-down'].listeners.click();
  assert.equal(audio.volume, 0);
});

test('primeiro gesto em qualquer lugar da pagina (fora do player) inicia a musica uma unica vez',()=>{
  const {elementos, listenersDocumento} = setup();
  const audio = elementos['mc-audio'];
  assert.equal(audio.paused, true);
  const {fn, opts} = listenersDocumento.click;
  assert.equal(opts.capture, true);
  fn({target: {closest: () => null}}); // gesto fora do player
  assert.equal(audio.paused, false);
  audio.pause();
  fn({target: {closest: () => null}}); // segundo gesto nao deve forcar play de novo
  assert.equal(audio.paused, true);
});

test('gesto dentro do proprio player nao dispara o auto-inicio generico (evita duplo toggle)',()=>{
  const {elementos, listenersDocumento} = setup();
  const audio = elementos['mc-audio'];
  const {fn} = listenersDocumento.click;
  fn({target: {closest: sel => sel === '#mc-player' ? {} : null}});
  assert.equal(audio.paused, true); // o listener generico nao mexeu -- so o botao proprio tocaria
});

test('nenhuma chamada de rede / iframe / servico externo no player',()=>{
  assert.ok(!/fetch\(|XMLHttpRequest|iframe|youtube|spotify/i.test(code));
});

test('com estado salvo de outra pagina, retoma faixa e volume salvos', () => {
  const { elementos } = setup({ indice: 2, tempo: 37, volume: 0.3, tocando: false });
  assert.equal(elementos['mc-track'].textContent, 'Quimbara Cumba');
  assert.equal(elementos['mc-audio'].volume, 0.3);
});

test('se a pessoa tinha pausado antes de navegar, a proxima pagina nao volta a tocar sozinha', () => {
  const { elementos, listenersDocumento } = setup({ indice: 0, tempo: 5, volume: 0.7, tocando: false });
  const { fn } = listenersDocumento.click;
  fn({ target: { closest: () => null } });
  assert.equal(elementos['mc-audio'].paused, true);
});

test('se estava tocando ao navegar, o primeiro gesto na pagina seguinte retoma', () => {
  const { elementos, listenersDocumento } = setup({ indice: 0, tempo: 5, volume: 0.7, tocando: true });
  const { fn } = listenersDocumento.click;
  fn({ target: { closest: () => null } });
  assert.equal(elementos['mc-audio'].paused, false);
});

test('sem estado salvo (primeira visita), o primeiro gesto continua comecando a musica -- comportamento de sempre', () => {
  const { elementos, listenersDocumento } = setup();
  const { fn } = listenersDocumento.click;
  fn({ target: { closest: () => null } });
  assert.equal(elementos['mc-audio'].paused, false);
});

test('estado salvo corrompido nao quebra o player -- cai no comportamento padrao', () => {
  const painel = { closest() { return null; } };
  const elementos = {
    'mc-player': painel, 'mc-audio': audioFake(), 'mc-playpause': botao(), 'mc-prev': botao(),
    'mc-next': botao(), 'mc-vol-down': botao(), 'mc-vol-up': botao(), 'mc-track': elFaixa(),
    'mc-progress': progressoFake(),
  };
  const document = { getElementById: id => elementos[id], addEventListener() {} };
  const window = {
    localStorage: { getItem: () => 'isto nao e json{{{', setItem() {}, removeItem() {} },
    setInterval() { return 0; }, clearInterval() {}, addEventListener() {},
  };
  assert.doesNotThrow(() => vm.runInNewContext(code, { document, window }));
  assert.equal(elementos['mc-track'].textContent, 'Black Ginga');
});
