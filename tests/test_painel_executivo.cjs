const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {model}=require('../maranhao-backend/painel-executivo.js');
test('ausência não vira zero',()=>{const m=model({});assert.equal(m.contatos,null);assert.equal(m.pedidos,null);assert.ok(m.stages.every(s=>s.count===null));});
test('consulta vazia confirmada é zero',()=>{assert.equal(model({crm:[],pedidos:[]}).contatos,0);});
test('funil só conta estágios explícitos e preserva desconhecidos',()=>{const m=model({crm:[{estagio:'cliente'},{estagio:'negociacao'},{},{estagio:'inexistente'}]});assert.equal(m.clientes,1);assert.equal(m.negociacoes,1);assert.equal(m.desconhecidos,2);assert.equal(m.contatos,4);assert.equal(m.pedidos,null);});
test('pedido sem pagamento não cria receita ou conversão',()=>{const m=model({pedidos:[{status:'aguardando_pagamento',valor_centavos:9000}]});assert.equal(m.pedidos,1);assert.equal(m.receita,undefined);assert.equal(m.conversao,undefined);});
test('painel não chama rede e renderiza dados como texto',()=>{const source=fs.readFileSync('maranhao-backend/painel-executivo.js','utf8');assert.ok(!source.includes('fetch('));assert.ok(!source.includes('innerHTML'));assert.ok(!source.includes('/enviar'));});
