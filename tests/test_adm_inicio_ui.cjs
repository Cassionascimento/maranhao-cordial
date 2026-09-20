/* Início: a primeira tela precisa responder o que está acontecendo, o que
   precisa da pessoa e qual foi o resultado — sem inventar nenhum número. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const inicio = require('../maranhao-backend/adm-inicio.js');
const fonte = fs.readFileSync('maranhao-backend/adm-inicio.js', 'utf8');

const ok = corpo => ({ ok: true, corpo });
const falha = () => ({ ok: false, corpo: {} });

function estadoCompleto(extra = {}) {
    return Object.assign({
        crm: ok({
            leads: [
                { estagio: 'novo' },
                { estagio: 'negociacao' },
                { estagio: 'cliente' },
                { estagio: 'perdido' },
                { estagio: 'novo', arquivado: true },
                { estagio: 'novo', cadastro_teste: true },
            ],
        }),
        acoes: ok({
            acoes: [
                { status: 'aguardando_aprovacao' },
                { status: 'aguardando_aprovacao' },
                { status: 'aprovada' },
                { status: 'enviada' },
                { status: 'bloqueada' },
            ],
        }),
        pedidos: ok({
            pedidos: [
                { status: 'pago', valor_centavos: 12000 },
                { status: 'pago', valor_centavos: 8000 },
                { status: 'aguardando_pagamento', valor_centavos: 99000 },
            ],
        }),
        diretor: ok({
            leitura: {
                ia_trabalhando: true,
                hoje: { concluido: [{ proxima_acao: 'pesquisar' }], planejado: [], precisa_de_mim: [] },
                comercial: {
                    oportunidades: [{ prioridade: 'alta' }, { prioridade: 'baixa' }],
                    followups: [{}],
                },
                conselho: { aguardando_diretor: [{}], vetos: [], resultados_recentes: [{}] },
                proxima_acao_ia: { o_que: 'pesquisar' },
            },
        }),
    }, extra);
}

const porChave = (indicadores, chave) => indicadores.find(i => i.chave === chave);

/* ---------------- HONESTIDADE DOS NÚMEROS ---------------- */

test('receita confirmada conta só pedidos pagos', () => {
    const receita = inicio.receitaConfirmada(estadoCompleto().pedidos);
    assert.equal(receita.centavos, 20000);
    assert.equal(receita.quantidade, 2);
    assert.equal(receita.registrados, 3);
});

test('proposta e oportunidade nunca entram na receita', () => {
    const indicadores = inicio.montarIndicadores(estadoCompleto());
    assert.equal(porChave(indicadores, 'receita').valor, 20000);
    assert.match(porChave(indicadores, 'oportunidades').contexto, /não são receita/i);
    assert.match(porChave(indicadores, 'receita').contexto, /pagamento confirmado/i);
});

test('fonte fora do ar vira "sem dados", nunca zero', () => {
    const indicadores = inicio.montarIndicadores(estadoCompleto({ pedidos: falha(), crm: falha() }));
    assert.equal(porChave(indicadores, 'receita').valor, null);
    assert.equal(porChave(indicadores, 'contatos').valor, null);
    assert.match(porChave(indicadores, 'receita').contexto, /indispon/i);
});

test('lista vazia confirmada é zero de verdade', () => {
    const vazio = inicio.montarIndicadores(estadoCompleto({
        pedidos: ok({ pedidos: [] }), crm: ok({ leads: [] }),
    }));
    assert.equal(porChave(vazio, 'receita').valor, 0);
    assert.equal(porChave(vazio, 'contatos').valor, 0);
});

test('contatos ativos excluem cliente, perdido, arquivado e cadastro de teste', () => {
    assert.equal(inicio.contarLeadsAtivos(estadoCompleto().crm), 2);
});

test('todo indicador traz contexto explicando o que o número é', () => {
    for (const indicador of inicio.montarIndicadores(estadoCompleto())) {
        assert.ok(indicador.contexto && indicador.contexto.length > 10, indicador.chave);
        assert.ok(indicador.rotulo);
    }
});

test('são no máximo quatro indicadores', () => {
    assert.ok(inicio.montarIndicadores(estadoCompleto()).length <= 4);
});

/* ---------------- PRIORIDADES ---------------- */

test('no máximo três prioridades, a mais urgente primeiro', () => {
    const prioridades = inicio.montarPrioridades(estadoCompleto());
    assert.ok(prioridades.length <= 3);
    assert.match(prioridades[0].titulo, /aguardando sua aprovação/);
    assert.equal(prioridades[0].urgencia, 'alta');
});

test('veto do Conselho aparece acima de oportunidade parada', () => {
    const estado = estadoCompleto();
    estado.acoes = ok({ acoes: [] });
    estado.diretor.corpo.leitura.conselho.vetos = [{}];
    const titulos = inicio.montarPrioridades(estado).map(p => p.titulo);
    assert.match(titulos[0], /veto/i);
});

test('sem nada pendente, nenhuma prioridade é inventada', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [] }) });
    estado.diretor.corpo.leitura.comercial = { oportunidades: [], followups: [] };
    estado.diretor.corpo.leitura.conselho = { aguardando_diretor: [], vetos: [], resultados_recentes: [] };
    assert.deepEqual(inicio.montarPrioridades(estado), []);
});

test('cada prioridade leva a uma tela concreta', () => {
    for (const prioridade of inicio.montarPrioridades(estadoCompleto())) {
        assert.ok(prioridade.painel);
        assert.ok(prioridade.botao);
        assert.ok(prioridade.descricao.length > 10);
    }
});

test('pendência técnica só vira prioridade quando impede uma tarefa', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [{ status: 'bloqueada' }] }) });
    estado.diretor.corpo.leitura.comercial = { oportunidades: [], followups: [] };
    estado.diretor.corpo.leitura.conselho = { aguardando_diretor: [], vetos: [], resultados_recentes: [] };
    const prioridades = inicio.montarPrioridades(estado);
    assert.equal(prioridades.length, 1);
    assert.match(prioridades[0].titulo, /não se confirmou/);
    assert.match(prioridades[0].descricao, /não há reenvio automático/i);
});

/* ---------------- SITUAÇÃO E AÇÃO PRINCIPAL ---------------- */

test('a frase de situação diz quantas decisões esperam a pessoa', () => {
    const situacao = inicio.montarSituacao(estadoCompleto());
    assert.match(situacao.texto, /3 decis/);
    assert.equal(situacao.grave, false);
});

test('sem nada pendente a frase não inventa urgência', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [] }) });
    estado.diretor.corpo.leitura.conselho = { aguardando_diretor: [], vetos: [], resultados_recentes: [] };
    assert.match(inicio.montarSituacao(estado).texto, /Nada espera por você/);
});

test('todas as fontes fora do ar viram um aviso explícito, não uma tela vazia', () => {
    const situacao = inicio.montarSituacao({
        crm: falha(), acoes: falha(), pedidos: falha(), diretor: falha(),
    });
    assert.equal(situacao.grave, true);
    assert.match(situacao.nota, /nada foi alterado/i);
});

test('falha parcial é declarada em vez de silenciada', () => {
    const situacao = inicio.montarSituacao(estadoCompleto({ pedidos: falha() }));
    assert.match(situacao.nota, /não carregou/i);
});

test('a ação principal é a aprovação quando há fila', () => {
    const acao = inicio.montarAcaoPrincipal(estadoCompleto());
    assert.match(acao.rotulo, /Revisar 2 aprova/);
    assert.equal(acao.painel, 'governanca');
});

test('sem fila, a ação principal ainda existe e é uma só', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [] }) });
    estado.diretor.corpo.leitura.comercial = { oportunidades: [], followups: [] };
    estado.diretor.corpo.leitura.conselho = { aguardando_diretor: [], vetos: [], resultados_recentes: [] };
    const acao = inicio.montarAcaoPrincipal(estado);
    assert.equal(acao.painel, 'ia-empresarial');
    assert.ok(acao.rotulo);
});

/* ---------------- CADEIA: SUGERIDO ≠ EXECUTADO ---------------- */

test('a cadeia tem quatro etapas, do sinal ao resultado', () => {
    const etapas = inicio.montarCadeia(estadoCompleto());
    assert.equal(etapas.length, 4);
    assert.deepEqual(etapas.map(e => e.titulo), [
        'Oportunidade identificada', 'Ação sugerida', 'Aprovado e executado', 'Resposta ou resultado',
    ]);
});

test('uma sugestão nunca é apresentada como executada', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [{ status: 'aguardando_aprovacao' }] }) });
    const etapas = inicio.montarCadeia(estado);
    assert.equal(etapas[1].estado, 'sugerido');
    assert.equal(etapas[2].estado, 'aguardando');
    assert.match(etapas[2].texto, /antes de qualquer execução/);
});

test('execução sem confirmação aparece como falha, nunca como resultado', () => {
    const etapas = inicio.montarCadeia(estadoCompleto());
    assert.equal(etapas[3].estado, 'falhou');
    assert.match(etapas[3].texto, /Nada foi reenviado automaticamente/);
});

test('resultado confirmado só aparece quando existe registro de resultado', () => {
    const estado = estadoCompleto({ acoes: ok({ acoes: [{ status: 'enviada' }] }) });
    const etapas = inicio.montarCadeia(estado);
    assert.equal(etapas[2].estado, 'executado');
    assert.equal(etapas[3].estado, 'confirmado');

    estado.diretor.corpo.leitura.conselho.resultados_recentes = [];
    const semResultado = inicio.montarCadeia(estado);
    assert.equal(semResultado[3].estado, null);
    assert.match(semResultado[3].texto, /Ainda não há resultado confirmado/);
});

test('cada estado da cadeia tem rótulo em texto, não só cor', () => {
    for (const etapa of inicio.montarCadeia(estadoCompleto())) {
        if (etapa.estado) assert.ok(etapa.selo, 'estado sem rótulo: ' + etapa.titulo);
        assert.ok(etapa.texto);
    }
});

test('sem leitura do diretor a cadeia não quebra nem inventa etapas', () => {
    const etapas = inicio.montarCadeia({ diretor: falha(), acoes: falha() });
    assert.equal(etapas.length, 4);
    assert.ok(etapas.every(e => e.estado === null));
});

/* ---------------- TRABALHO RECENTE ---------------- */

test('o resumo do trabalho recente mostra no máximo três itens', () => {
    const estado = estadoCompleto();
    estado.diretor.corpo.leitura.hoje.concluido = [{}, {}, {}, {}, {}];
    const recente = inicio.montarRecente(estado);
    assert.equal(recente.total, 5);
    assert.equal(recente.itens.length, 3);
});

test('sem leitura do diretor o trabalho recente é nulo, não zero', () => {
    assert.equal(inicio.montarRecente({ diretor: falha() }), null);
});

/* ---------------- SEGURANÇA ---------------- */

test('a tela inicial só faz leitura: nenhum POST, PUT ou DELETE', () => {
    assert.ok(!/method:\s*['"](POST|PUT|PATCH|DELETE)/i.test(fonte));
    assert.ok(!fonte.includes('body: JSON.stringify'));
});

test('a tela inicial nunca escreve HTML cru', () => {
    assert.ok(!fonte.includes('innerHTML'));
});

test('sem chave administrativa nada é consultado', () => {
    assert.ok(fonte.includes('if (!window.adminKeyAtual) return;'));
});

test('só consulta endpoints que já existiam', () => {
    const chamados = [...fonte.matchAll(/buscar\('([^']+)'\)/g)].map(m => m[1]);
    assert.deepEqual(chamados.sort(), [
        '/api/admin/acoes-comerciais',
        '/api/admin/crm/leads',
        '/api/admin/mi/diretor',
        '/api/admin/pedidos',
    ]);
});

test('quando nada pôde ser lido, a ação principal anterior é retirada', () => {
    const trecho = fonte.slice(fonte.indexOf('if (situacao.grave)'), fonte.indexOf('raiz.append(aviso)'));
    assert.ok(trecho.includes('botaoObsoleto.hidden = true'),
        'a ação principal obsoleta precisa sair da tela de falha');
    assert.ok(trecho.includes('Tentar de novo'), 'a tela de falha precisa oferecer uma saída');
});

test('voltar ao Início repõe a ação principal sem precisar recarregar', () => {
    assert.ok(fonte.includes('function aplicarAcaoNoCabecalho'));
    const listener = fonte.slice(fonte.indexOf("window.addEventListener('adm-vista'"));
    assert.ok(listener.includes('aplicarAcaoNoCabecalho()'),
        'a volta ao Início precisa repor a ação no cabeçalho');
});
