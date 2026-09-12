const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const code=fs.readFileSync('maranhao-backend/app-shell.js','utf8');

function setup(textoInicial=''){
  const classes=new Set();
  const abaGovernanca={classList:{
    toggle(cls,v){ if(v) classes.add(cls); else classes.delete(cls); },
    contains(cls){ return classes.has(cls); },
  }};
  const statusEl={textContent:textoInicial};
  let callback=null;
  class MutationObserverMock{ constructor(cb){ callback=cb; } observe(){} }
  const document={
    querySelector:sel=>sel.includes('governanca') ? abaGovernanca : null,
    getElementById:id=>id==='status-acoes-comerciais' ? statusEl : null,
  };
  vm.runInNewContext(code,{document,MutationObserver:MutationObserverMock});
  return {
    temAlerta:()=>abaGovernanca.classList.contains('app-shell-alerta'),
    dispara(novoTexto){ statusEl.textContent=novoTexto; callback(); },
  };
}

test('sem pendências, nenhum destaque aparece',()=>{
  const t=setup('Nenhuma ação aguardando aprovação.');
  assert.equal(t.temAlerta(),false);
});

test('com pendências, destaque discreto aparece na aba Governança',()=>{
  const t=setup('3 ações para sua decisão.');
  assert.equal(t.temAlerta(),true);
});

test('destaque some quando as pendências chegam a zero',()=>{
  const t=setup('2 ações para sua decisão.');
  assert.equal(t.temAlerta(),true);
  t.dispara('Nenhuma ação aguardando aprovação.');
  assert.equal(t.temAlerta(),false);
});

test('sem os elementos esperados na página, o script não faz nada (nunca lança erro)',()=>{
  const document={querySelector:()=>null,getElementById:()=>null};
  assert.doesNotThrow(()=>vm.runInNewContext(code,{document,MutationObserver:class{observe(){}}}));
});
