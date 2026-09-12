const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/visao-geral.js','utf8');
const html=fs.readFileSync('maranhao-backend/admin.html','utf8');

const RESPOSTAS_OK = {
  '/api/admin/crm/leads': {success:true, leads:[
    {estagio:'negociacao'}, {estagio:'cliente'}, {estagio:'perdido'},
    {estagio:'qualificacao', arquivado:true}, {estagio:'novo'},
  ]},
  '/api/admin/acoes-comerciais': {success:true, acoes:[
    {status:'aguardando_aprovacao'}, {status:'aguardando_aprovacao'}, {status:'enviada'},
  ]},
  '/api/admin/omnichannel/whatsapp': {success:true, estado:'aguardando_meta', envio_liberado:false},
  '/api/c6/status': {success:true, ready:false, credentials_configured:true},
  '/api/admin/mi/painel': {success:true, resumo:{unidades:10,eventos:20,scans_qr:5,estabelecimentos:2,territorios_ativos:1},
    atividade_recente:[{tipo_evento:'scan',criado_em:new Date().toISOString()},{tipo_evento:'venda',criado_em:'2020-01-01T00:00:00Z'}]},
  '/api/admin/ia-empresarial/hoje': {success:true, resumo:{total_atencao:1,total_novos_prospectos:2,total_proximas_acoes:3}, precisa_atencao:['Revisar prospecto X']},
};

function no(tag='div') {
  return {tag,children:[],listeners:{},textContent:'',disabled:false,hidden:true,dataset:{},
    className:'',
    classList:{_c:new Set(),add(c){this._c.add(c);},toggle(c,v){v?this._c.add(c):this._c.delete(c);},contains(c){return this._c.has(c);}},
    append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
    addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return null;},
    set dataset_vgTab(v){this.dataset.vgTab=v;},
  };
}

function setup({respostas=RESPOSTAS_OK, falharChave=[], semChave=false, semAdminContent=false}={}) {
  const elementos={};
  const tabButtons={'maranhao-intelligence':no('button'),'ia-empresarial':no('button')};
  for (const k in tabButtons) tabButtons[k].click=()=>{tabButtons[k]._clicado=true;};
  const raiz=no('div');
  raiz.id='visao-geral-executiva';
  const eventos={};
  const document={
    createElement:no,
    getElementById:id=>{
      if (id==='visao-geral-executiva') return semAdminContent ? null : raiz;
      return elementos[id] ||= no();
    },
    querySelector:sel=>{
      const m=sel.match(/data-tab="([^"]+)"/);
      if (sel.includes('[data-tab="visao-geral"]')) return elementos.tabVisaoGeral ||= no('button');
      if (m && tabButtons[m[1]]) return tabButtons[m[1]];
      if (sel.includes('data-panel="visao-geral"')) return elementos.painelAtivo ||= (() => { const p=no(); p.classList.add('active'); return p; })();
      return null;
    },
  };
  const eventosDisparados=[];
  const window={adminKeyAtual: semChave ? '' : 'chave-teste', addEventListener:(k,fn)=>{eventos[k]=fn;}, dispatchEvent(ev){ eventosDisparados.push(ev); }};
  const calls=[];
  const fetchMock=async (url) => {
    calls.push(url);
    const caminho=Object.keys(respostas).find(c=>url.includes(c));
    if (!caminho || falharChave.includes(caminho)) return {ok:false, json: async () => ({success:false})};
    return {ok:true, json: async () => respostas[caminho]};
  };
  const sandbox={document,window,fetch:fetchMock,CustomEvent:function(tipo,init){ this.type=tipo; this.detail=init && init.detail; },console};
  vm.runInNewContext(code,sandbox);
  return {document,window,elementos,tabButtons,calls,eventos};
}

test('carrega exatamente os 4 KPIs esperados, na ordem certa',async()=>{
  const t=setup();
  await t.elementos['vg-atualizar'].listeners.click();
  const rotulos=t.elementos['vg-kpis'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Leads ativos','Aprovações pendentes','Scans hoje*','Alertas abertos']);
});

test('conta leads ativos excluindo cliente/perdido/arquivado, e aprovações pendentes corretamente',async()=>{
  const t=setup();
  await t.elementos['vg-atualizar'].listeners.click();
  const valores=t.elementos['vg-kpis'].children.map(c=>c.children[0].textContent);
  assert.equal(valores[0],'2'); // negociacao + novo (cliente/perdido/arquivado excluídos)
  assert.equal(valores[1],'2'); // 2 aguardando_aprovacao
});

test('estado vazio elegante quando nada exige atenção',async()=>{
  const t=setup({respostas:{...RESPOSTAS_OK,
    '/api/admin/acoes-comerciais':{success:true,acoes:[]},
    '/api/admin/omnichannel/whatsapp':{success:true,estado:'conectado',envio_liberado:true},
    '/api/c6/status':{success:true,ready:true},
    '/api/admin/ia-empresarial/hoje':{success:true,resumo:{},precisa_atencao:[]},
  }});
  await t.elementos['vg-atualizar'].listeners.click();
  const atencao=t.elementos['vg-atencao'];
  assert.equal(atencao.children.length,1);
  assert.equal(atencao.children[0].textContent,'Nada exige atenção agora.');
  assert.equal(atencao.children[0].className,'vg-vazio');
});

test('falha de um endpoint não derruba a tela: as outras seções continuam renderizando',async()=>{
  const t=setup({falharChave:['/api/admin/mi/painel']});
  await t.elementos['vg-atualizar'].listeners.click();
  assert.match(t.elementos['vg-mi'].children[0].textContent,/indisponível/);
  // KPIs de outras fontes continuam presentes
  const rotulos=t.elementos['vg-kpis'].children.map(c=>c.children[1].textContent);
  assert.deepEqual(rotulos,['Leads ativos','Aprovações pendentes','Scans hoje*','Alertas abertos']);
  assert.equal(t.elementos['vg-status'].textContent,'Leitura atualizada. Nenhuma ação foi executada.');
});

test('nenhuma chamada é de escrita (todas as buscas são GET, sem method/body)',async()=>{
  const t=setup();
  await t.elementos['vg-atualizar'].listeners.click();
  assert.equal(t.calls.length,6);
  for (const url of t.calls) assert.ok(!/method|POST|PUT|DELETE/i.test(url));
});

test('nenhum dado sensível/interno aparece no texto renderizado (só contagens e rótulos)',async()=>{
  const t=setup();
  await t.elementos['vg-atualizar'].listeners.click();
  const textoTudo=JSON.stringify([t.elementos['vg-kpis'],t.elementos['vg-mi'],t.elementos['vg-canais'],t.elementos['vg-atencao']]);
  for (const suspeito of ['@','uuid','-id','senha','token']) assert.ok(!textoTudo.toLowerCase().includes(suspeito));
});

test('sem chave administrativa, nenhuma chamada é feita ao abrir a aba ou após admin-autorizado',()=>{
  const t=setup({semChave:true});
  t.document.querySelector('[data-tab="visao-geral"]').listeners.click();
  t.eventos['admin-autorizado']();
  assert.equal(t.calls.length,0);
});

test('carrega automaticamente quando a aba já está ativa no evento admin-autorizado',async()=>{
  const t=setup();
  await t.eventos['admin-autorizado']();
  assert.equal(t.calls.length,6);
});

test('botão de atalho para Maranhão Intelligence aciona a aba correspondente, sem duplicar a seção',async()=>{
  const t=setup();
  const raiz=t.document.getElementById('visao-geral-executiva');
  const alvo={dataset:{vgTab:'maranhao-intelligence'},closest:()=>alvo};
  raiz.listeners.click({target:alvo});
  assert.ok(t.tabButtons['maranhao-intelligence']._clicado);
  // A seção MI aqui só mostra o resumo compacto (4 estatísticas), nunca as tabelas completas.
  await t.elementos['vg-atualizar'].listeners.click();
  const faixaMi=t.elementos['vg-mi'].children[0];
  assert.equal(faixaMi.children.length,4);
});

test('compatibilidade: skeleton novo não remove o painel-executivo existente nem os ids legados',()=>{
  assert.ok(html.includes('id="painel-executivo"'));
  assert.ok(html.includes('id="exec-kpis"'));
  assert.ok(html.includes('id="exec-funil"'));
  assert.ok(html.includes('id="visao-geral-executiva"'));
  assert.match(html,/<script src="\/visao-geral\.js" defer><\/script>/);
  assert.match(html,/<link rel="stylesheet" href="\/visao-geral\.css">/);
});
