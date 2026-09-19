/* Apresentação executiva: somente leitura, sem dado pessoal, sem número
   inventado e preparada para tradução. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const { TEXTOS, textos, formatarDinheiro, descreverEtapa } =
    require('../maranhao-backend/adm-apresentacao.js');
const fonte = fs.readFileSync('maranhao-backend/adm-apresentacao.js', 'utf8');

/* ---------------- SOMENTE LEITURA ---------------- */

test('faz exatamente uma chamada, e é GET', () => {
    const chamadas = [...fonte.matchAll(/fetch\(/g)];
    assert.equal(chamadas.length, 1);
    assert.ok(!/method:\s*['"](POST|PUT|PATCH|DELETE)/i.test(fonte));
    assert.ok(!fonte.includes('body:'));
});

test('consome só o endpoint agregado da apresentação', () => {
    const caminhos = [...fonte.matchAll(/'(\/api\/[^']+)'/g)].map(m => m[1]);
    assert.deepEqual(caminhos, ['/api/admin/apresentacao']);
});

test('não abre painel sem chave administrativa — a proteção real é do servidor', () => {
    assert.ok(fonte.includes('if (!window.adminKeyAtual) return;'));
    assert.ok(fonte.includes("'X-Admin-Key': window.adminKeyAtual"));
});

test('nenhum link público é criado', () => {
    assert.ok(!fonte.includes('window.open'));
    assert.ok(!fonte.includes('navigator.clipboard'));
    assert.ok(!/share|publicar|public_url/i.test(fonte.replace(/público/g, '')));
});

test('nunca escreve HTML cru', () => {
    assert.ok(!fonte.includes('innerHTML'));
});

/* ---------------- HONESTIDADE ---------------- */

test('valor ausente vira "sem dados", nunca zero', () => {
    assert.equal(formatarDinheiro(null), null);
    assert.equal(formatarDinheiro(undefined), null);
    assert.ok(fonte.includes('textos(idioma).semDado'));
});

test('receita é formatada a partir de centavos', () => {
    const formatado = formatarDinheiro(123400);
    assert.match(formatado, /1\.234/);
});

test('sem oportunidade real, diz isso em vez de inventar uma', () => {
    const t = textos('pt-BR');
    assert.match(t.oportunidade.semOportunidade, /Nenhuma oportunidade/);
    assert.match(t.oportunidade.semOportunidadeNota, /não cria oportunidades/);
});

test('toda etapa possível do resultado tem frase própria — nenhuma promessa', () => {
    const etapas = textos('pt-BR').resultado.etapas;
    for (const codigo of ['acao_executada', 'acao_aprovada', 'acao_aguardando_aprovacao',
        'acao_proposta', 'relacionamento_em_andamento', 'operacao_preparada', 'fila_nao_lida']) {
        assert.ok(etapas[codigo], 'etapa sem texto: ' + codigo);
        assert.ok(!/breve|logo|vai ser|prometemos/i.test(etapas[codigo]), codigo);
    }
});

test('código desconhecido não vira frase inventada', () => {
    assert.equal(descreverEtapa('codigo_que_nao_existe'), 'codigo_que_nao_existe');
});

test('o texto declara que não há envio automático', () => {
    assert.match(textos('pt-BR').controle.envio, /desligado/i);
    assert.match(textos('pt-BR').controle.linha, /decisão de uma pessoa|fila de aprovação/i);
});

test('nenhuma comparação de superioridade sem evidência', () => {
    const tudo = JSON.stringify(TEXTOS).toLowerCase();
    for (const termo of ['china', 'chinesa', 'melhor do mundo', 'superior', 'líder de mercado',
        'roi', 'economia de tempo', 'aumento de', '% de conversão']) {
        assert.ok(!tudo.includes(termo), 'afirmação sem evidência: ' + termo);
    }
});

test('nenhum número aparece fixo nos textos da apresentação', () => {
    const tudo = JSON.stringify(TEXTOS);
    const numeros = tudo.match(/\d[\d.,]*/g) || [];
    assert.deepEqual(numeros, [], 'número fixo no texto: ' + numeros.join(', '));
});

/* ---------------- ESTRUTURA DE 60 SEGUNDOS ---------------- */

test('são exatamente quatro passos, na ordem pedida', () => {
    assert.deepEqual(textos('pt-BR').passos,
        ['O negócio', 'A oportunidade', 'O controle', 'O resultado']);
});

test('cada passo tem título e uma linha de contexto', () => {
    const t = textos('pt-BR');
    for (const bloco of ['negocio', 'oportunidade', 'controle', 'resultado']) {
        assert.ok(t[bloco].eyebrow, bloco);
        assert.ok(t[bloco].titulo, bloco);
    }
});

test('os limites da leitura acompanham a apresentação', () => {
    assert.ok(textos('pt-BR').limites);
    assert.ok(fonte.includes('dados.limites'));
});

/* ---------------- TRADUÇÃO ---------------- */

test('todo texto visível vive no dicionário de idioma', () => {
    // Nenhuma frase longa em português solta no código de desenho.
    const soltos = [...fonte.matchAll(/criar\('(?:h2|p|span|strong|small)',\s*'([^']{12,})'/g)];
    assert.deepEqual(soltos.map(m => m[1]), [], 'texto fora do dicionário');
});

test('acrescentar um idioma é acrescentar uma chave', () => {
    assert.ok(TEXTOS['pt-BR']);
    assert.equal(Object.keys(TEXTOS).length, 1,
        'nenhum idioma adicional é escolhido sem a preferência confirmada');
    assert.equal(textos('zh-Hans'), TEXTOS['pt-BR'], 'idioma desconhecido volta ao padrão');
});

test('a interface diz que a tradução depende de confirmação da preferência', () => {
    assert.match(textos('pt-BR').traducao, /preferência for confirmada/);
});

test('nenhuma variante de mandarim foi escolhida por conta própria', () => {
    assert.ok(!/zh-Hans|zh-Hant|简体|繁體/.test(fonte.replace("textos('zh-Hans')", '')));
});

test('código interno de ação e prioridade vira rótulo legível', () => {
    const o = textos('pt-BR').oportunidade;
    assert.equal(o.acoes.enviar_followup, 'Enviar retorno');
    assert.equal(o.prioridades.alta, 'Alta');
    // Toda enumeração que o servidor pode devolver tem tradução, inclusive
    // o valor de escape "outro".
    for (const codigo of ['pesquisar', 'classificar', 'analisar', 'planejar', 'sugerir_conteudo',
        'enviar_followup', 'avaliar_reengajamento', 'revisar_bloqueio', 'decidir_proposta',
        'priorizar_atendimento', 'informar_diretor', 'outro']) {
        assert.ok(o.acoes[codigo], 'ação sem rótulo: ' + codigo);
    }
    for (const codigo of ['urgente', 'alta', 'normal', 'baixa', 'outro']) {
        assert.ok(o.prioridades[codigo], 'prioridade sem rótulo: ' + codigo);
    }
});
