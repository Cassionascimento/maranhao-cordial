/* Painel de Canais: mostra o diagnóstico real, nunca inventa "conectado",
   e não oferece botão que não tem rota. Contrato rico (canais_diagnostico.py)
   e contrato antigo precisam renderizar. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

const code=fs.readFileSync('maranhao-backend/canais-status.js','utf8');

function no(tag='div') {
  const n = {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},
    className:'',title:'',atributos:{},
    append(...xs){this.children.push(...xs);},
    replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    setAttribute(k,v){this.atributos[k]=v;},
    get childElementCount(){return this.children.length;}};
  return n;
}

/* Contrato rico: é o que o servidor passa a devolver com ?remoto=1. */
const CANAIS = [
  {canal:'WhatsApp',grupo:'mensageria',estado:'aguardando_aprovacao_externa',conta:'+55 98 90000-0000',
   tipo_conta:'CLOUD_API',leitura_disponivel:true,escrita_disponivel:false,aprovacao_exigida:true,
   webhook_ativo:true,token_expira_em:null,permissoes_concedidas:['whatsapp_business_messaging'],
   permissoes_ausentes:['whatsapp_business_management'],ultima_sincronizacao:null,
   ultima_tentativa:'2026-09-19T12:00:00Z',ultimo_erro:null,codigo_erro:null,exige_reconexao:false,
   exige_acao_admin:false,aguardando_plataforma:true,verificacao_remota:true,
   proximo_passo:'Aguardando aprovação da Meta para: whatsapp_business_management.',motivo_nao_priorizado:null},
  {canal:'TikTok Shop',grupo:'comercial',estado:'nao_configurado',conta:null,tipo_conta:null,
   leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,webhook_ativo:null,
   token_expira_em:null,permissoes_concedidas:null,permissoes_ausentes:null,ultima_sincronizacao:null,
   ultima_tentativa:'2026-09-19T12:00:00Z',ultimo_erro:null,codigo_erro:null,exige_reconexao:false,
   exige_acao_admin:true,aguardando_plataforma:false,verificacao_remota:false,
   proximo_passo:'Criar o app em partner.tiktokshop.com (Partner Center).',motivo_nao_priorizado:null},
  {canal:'LinkedIn',grupo:'social',estado:'conectado_parcial',conta:'Cássio',tipo_conta:'Perfil pessoal',
   leitura_disponivel:true,escrita_disponivel:false,aprovacao_exigida:true,webhook_ativo:null,
   token_expira_em:null,permissoes_concedidas:null,permissoes_ausentes:['w_organization_social'],
   ultima_sincronizacao:null,ultima_tentativa:'2026-09-19T12:00:00Z',ultimo_erro:null,codigo_erro:null,
   exige_reconexao:false,exige_acao_admin:true,aguardando_plataforma:false,verificacao_remota:true,
   proximo_passo:'Criar/confirmar a Página "Maranhão Cordial".',motivo_nao_priorizado:null},
  {canal:'Instagram',grupo:'social',estado:'conectado',conta:'@maranhaocordial',tipo_conta:'Conta profissional',
   leitura_disponivel:true,escrita_disponivel:true,aprovacao_exigida:true,webhook_ativo:null,
   token_expira_em:'2026-11-01T00:00:00Z',permissoes_concedidas:['instagram_basic','instagram_manage_messages'],
   permissoes_ausentes:[],ultima_sincronizacao:null,ultima_tentativa:'2026-09-19T12:00:00Z',
   ultimo_erro:null,codigo_erro:null,exige_reconexao:false,exige_acao_admin:false,
   aguardando_plataforma:false,verificacao_remota:true,proximo_passo:null,motivo_nao_priorizado:null},
  {canal:'Gmail',grupo:'mensageria',estado:'conectado',conta:null,tipo_conta:'Caixa institucional (OAuth)',
   leitura_disponivel:true,escrita_disponivel:true,aprovacao_exigida:true,webhook_ativo:null,
   token_expira_em:null,permissoes_concedidas:['gmail.readonly'],permissoes_ausentes:null,
   ultima_sincronizacao:'2026-09-19T08:00:00Z',ultima_tentativa:'2026-09-19T12:00:00Z',ultimo_erro:null,
   codigo_erro:null,exige_reconexao:false,exige_acao_admin:false,aguardando_plataforma:false,
   verificacao_remota:false,proximo_passo:null,motivo_nao_priorizado:null},
  {canal:'Pinterest',grupo:'social',estado:'nao_priorizado',conta:null,tipo_conta:null,
   leitura_disponivel:false,escrita_disponivel:false,aprovacao_exigida:true,webhook_ativo:null,
   token_expira_em:null,permissoes_concedidas:null,permissoes_ausentes:null,ultima_sincronizacao:null,
   ultima_tentativa:null,ultimo_erro:null,codigo_erro:null,exige_reconexao:false,exige_acao_admin:false,
   aguardando_plataforma:false,verificacao_remota:false,proximo_passo:'Reavaliar quando houver catálogo.',
   motivo_nao_priorizado:'Sem uso comercial imediato.'},
  {canal:'X',grupo:'social',estado:'token_expirado',conta:null,tipo_conta:null,leitura_disponivel:false,
   escrita_disponivel:false,aprovacao_exigida:true,webhook_ativo:null,token_expira_em:null,
   permissoes_concedidas:null,permissoes_ausentes:null,ultima_sincronizacao:null,ultima_tentativa:null,
   ultimo_erro:'token_recusado',codigo_erro:'http_401',exige_reconexao:true,exige_acao_admin:true,
   aguardando_plataforma:false,verificacao_remota:true,proximo_passo:'Reautorizar.',motivo_nao_priorizado:null},
];

/* Contrato antigo -- o painel não pode quebrar se o servidor ainda não
   tiver o diagnóstico remoto. */
const CANAIS_ANTIGOS = [
  {canal:'Instagram',estado:'pendente',ultima_sincronizacao:null,leitura_disponivel:false,
   escrita_disponivel:false,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:'Definir INSTAGRAM_ACCESS_TOKEN.'},
  {canal:'LinkedIn',estado:'conectado',ultima_sincronizacao:null,leitura_disponivel:true,
   escrita_disponivel:true,aprovacao_exigida:true,ultimo_erro:null,proximo_passo:null},
];

function setup({semChave=false, ok=true, canais=CANAIS}={}) {
  const elementos = {};
  const painel = no('div'); painel.id = 'canais-painel';
  const document = {
    createElement: no,
    getElementById: id => (id === 'canais-painel' ? painel : (elementos[id] ||= no())),
    querySelector: sel => (sel.includes('[data-tab="canais"]') ? (elementos.tab ||= no('button')) : null),
  };
  const window = { adminKeyAtual: semChave ? '' : 'x', open: () => {} };
  const calls = [];
  const fetchMock = async (url, opcoes) => {
    calls.push({ url, method: (opcoes && opcoes.method) || 'GET' });
    if (url.includes('/api/admin/canais/status')) {
      return { ok, json: async () => (ok ? {success:true, canais} : {success:false, error:'indisponivel'}) };
    }
    if (url.includes('/api/admin/canais/diagnostico')) {
      return { ok:true, json: async () => ({success:true, canal: Object.assign({}, canais[0], {estado:'conectado', escrita_disponivel:true, proximo_passo:null, aguardando_plataforma:false, permissoes_ausentes:[]}), historico:[{estado:'erro',codigo_erro:'http_401',verificado_em:'2026-09-18T10:00:00Z'}]}) };
    }
    if (url.includes('/connect')) return { ok:true, json: async () => ({success:true, url:'https://exemplo/auth'}) };
    if (url.includes('/testar')) return { ok:true, json: async () => ({success:true, conexao:'ok'}) };
    return { ok:true, json: async () => ({success:true}) };
  };
  vm.runInNewContext(code, {document, window, fetch: fetchMock, console});
  return {elementos, calls, document};
}

const grade = t => t.elementos['canais-conteudo'].children[1];
const cartao = (t, nome) => grade(t).children.find(c => c.dataset && c.dataset.canal === nome);
const texto = alvo => JSON.stringify(alvo);

test('sem chave admin, nenhuma chamada',()=>{
  const t = setup({semChave:true});
  t.elementos.tab.listeners.click();
  assert.equal(t.calls.length, 0);
});

test('carrega os canais em cards, somente leitura automática',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.equal(t.calls.length, 1);
  assert.equal(t.calls[0].method, 'GET');
  assert.ok(t.calls[0].url.includes('remoto=1'), 'o painel precisa pedir o diagnóstico remoto');
  for (const nome of ['WhatsApp','TikTok Shop','LinkedIn','Instagram','Gmail','Pinterest','X']) {
    assert.ok(cartao(t, nome), 'faltou o cartão de ' + nome);
  }
  assert.equal(t.elementos['canais-conteudo'].hidden, false);
});

test('cada card mostra conta, leitura, escrita, webhook, token, erro e próximo passo',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const conteudo = texto(t.elementos['canais-conteudo']);
  for (const rotulo of ['Conta conectada','Leitura','Escrita','Webhook','Token expira em',
                        'Última sincronização','Última verificação','Último erro','Código técnico']) {
    assert.match(conteudo, new RegExp(rotulo), 'faltou a linha ' + rotulo);
  }
  assert.match(conteudo, /Aguardando aprovação da Meta/);
});

test('TikTok Shop é um canal próprio, separado do social',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const shop = cartao(t, 'TikTok Shop');
  assert.ok(shop);
  assert.match(texto(shop), /partner\.tiktokshop\.com/);
});

test('"nenhum próximo passo pendente" só aparece quando não falta nada',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  // WhatsApp tem permissão faltando -> nunca pode declarar ausência de pendência
  assert.ok(!texto(cartao(t,'WhatsApp')).includes('Nenhum próximo passo pendente'));
  // LinkedIn exige ação do admin -> idem
  assert.ok(!texto(cartao(t,'LinkedIn')).includes('Nenhum próximo passo pendente'));
  // Instagram conectado e sem pendência -> pode
  assert.match(texto(cartao(t,'Instagram')), /Nenhum próximo passo pendente/);
});

test('estados têm rótulo próprio; "pendente" genérico não substitui o motivo',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.match(texto(cartao(t,'WhatsApp')), /Aguardando aprovação da plataforma/);
  assert.match(texto(cartao(t,'LinkedIn')), /Conectado em parte/);
  assert.match(texto(cartao(t,'X')), /Token expirado/);
  assert.match(texto(cartao(t,'Pinterest')), /Não priorizado/);
  assert.match(texto(cartao(t,'Pinterest')), /Sem uso comercial imediato/);
});

test('avisos de ação do administrador e de espera pela plataforma aparecem',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.match(texto(cartao(t,'TikTok Shop')), /Exige ação do administrador/);
  assert.match(texto(cartao(t,'WhatsApp')), /Aguardando aprovação da plataforma/);
  assert.match(texto(cartao(t,'X')), /Precisa reconectar/);
});

test('botões sem rota real ficam desabilitados com motivo, nunca decorativos',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const acoesDe = nome => cartao(t,nome).children.find(c => c.className === 'canais-card-acoes');
  const semRota = acoesDe('WhatsApp').children.filter(b => b.textContent !== 'Diagnosticar');
  assert.equal(semRota.length, 4);
  for (const b of semRota) {
    assert.equal(b.disabled, true);
    assert.ok(b.title.length > 10, 'botão desabilitado precisa explicar o motivo');
    assert.equal(b.listeners.click, undefined, 'botão desabilitado não pode ter ação');
  }
  const comRota = acoesDe('LinkedIn').children.filter(b => b.textContent !== 'Diagnosticar');
  assert.ok(comRota.every(b => b.disabled === false));
});

test('todo canal pode ser diagnosticado individualmente',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  for (const nome of ['WhatsApp','TikTok Shop','Gmail','Instagram']) {
    const acoes = cartao(t,nome).children.find(c => c.className === 'canais-card-acoes');
    const diag = acoes.children.find(b => b.textContent === 'Diagnosticar');
    assert.ok(diag && diag.disabled === false, nome);
  }
});

test('diagnóstico individual atualiza só aquele cartão e traz histórico',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const acoes = cartao(t,'WhatsApp').children.find(c => c.className === 'canais-card-acoes');
  await acoes.children.find(b => b.textContent === 'Diagnosticar').listeners.click();
  const chamada = t.calls.find(c => c.url.includes('/canais/diagnostico'));
  assert.ok(chamada && chamada.method === 'GET');
  assert.ok(chamada.url.includes('canal=WhatsApp'));
  assert.match(texto(cartao(t,'WhatsApp')), /Histórico de mudanças e falhas/);
  assert.match(texto(cartao(t,'LinkedIn')), /Conectado em parte/, 'os outros cartões não podem mudar');
});

test('filtro por status existe e reduz a lista',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const barra = t.elementos['canais-conteudo'].children[0];
  const filtros = barra.children.map(b => b.dataset.filtro);
  assert.deepEqual(filtros, ['todos','falha','atencao','ok','neutro']);
  await barra.children.find(b => b.dataset.filtro === 'ok').listeners.click();
  const nomes = grade(t).children.map(c => c.dataset.canal);
  assert.deepEqual(nomes.sort(), ['Gmail','Instagram']);
});

test('conectar abre nova aba; o load não chama nenhuma escrita',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.ok(t.calls.every(c => c.method === 'GET'));
  const acoes = cartao(t,'LinkedIn').children.find(c => c.className === 'canais-card-acoes');
  await acoes.children.find(b => b.textContent === 'Conectar').listeners.click();
  assert.ok(t.calls.some(c => c.url.includes('/api/admin/linkedin/connect')));
});

test('reconectar e desconectar usam POST nas rotas reais do conector',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  const acoes = cartao(t,'X').children.find(c => c.className === 'canais-card-acoes');
  await acoes.children.find(b => b.textContent === 'Reconectar').listeners.click();
  await acoes.children.find(b => b.textContent === 'Desconectar').listeners.click();
  const escritas = t.calls.filter(c => c.method === 'POST');
  assert.equal(escritas.length, 2);
  assert.ok(escritas.every(c => c.url.includes('/api/admin/x/')));
});

test('falha na API mostra estado explicado, não trava',async()=>{
  const t = setup({ok:false});
  await t.elementos['canais-atualizar'].listeners.click();
  assert.match(t.elementos['canais-status'].textContent, /indisponivel|Falha/);
  assert.equal(t.elementos['canais-atualizar'].disabled, false);
});

test('o resumo diz quantos canais exigem ação',async()=>{
  const t = setup();
  await t.elementos['canais-atualizar'].listeners.click();
  assert.match(t.elementos['canais-status'].textContent, /exigem uma ação/);
  assert.match(t.elementos['canais-status'].textContent, /Nenhuma ação automática/);
});

test('contrato antigo continua renderizando, sem inventar campo',async()=>{
  const t = setup({canais: CANAIS_ANTIGOS});
  await t.elementos['canais-atualizar'].listeners.click();
  assert.ok(cartao(t,'Instagram'));
  assert.ok(cartao(t,'LinkedIn'));
  const instagram = texto(cartao(t,'Instagram'));
  assert.match(instagram, /Definir INSTAGRAM_ACCESS_TOKEN/);
  assert.match(instagram, /—/, 'campo ausente vira travessão, não valor otimista');
});

test('o painel nunca faz chamada de escrita sozinho',()=>{
  assert.ok(!/method:\s*['"]POST['"][^}]*\)\s*;?\s*\n\s*\}\s*\)\s*\(\)/.test(code));
  const automaticas = code.slice(code.indexOf('async function carregar'), code.length);
  assert.ok(!automaticas.includes("method: 'POST'"));
});
