/* Experiência do ADM: a reorganização não pode fazer nenhuma função
   desaparecer, e a navegação precisa continuar delegando aos controles que
   já existem (nada de lógica de painel reimplementada). */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const { MAPA, ATALHOS, construirIndice, filtrar, paineisDoMapa, vistasDoMapa, semAcento } =
    require('../maranhao-backend/adm-experiencia.js');

const html = fs.readFileSync('maranhao-backend/admin.html', 'utf8');
const fonte = fs.readFileSync('maranhao-backend/adm-experiencia.js', 'utf8');

/* Os módulos que constroem DOM em tempo de execução. Olhar só o admin.html
   deixa de fora painéis e controles que só existem depois que o navegador
   roda — foi assim que o Calendário (criado por app-shell.js) ficou fora do
   primeiro inventário. */
const MODULOS = [
    'app-shell.js', 'maranhao-intelligence.js', 'qr-intelligence.js', 'conselho-agentes.js',
    'calendario-empresarial.js', 'operacao-viva.js', 'mi-graficos.js',
    'canais-status.js', 'modo-diretor.js', 'visao-geral.js',
].map(n => fs.readFileSync('maranhao-backend/' + n, 'utf8'));
const TUDO = [html, ...MODULOS].join('\n');

/* Painéis estáticos (admin.html) + painéis injetados em tempo de execução
   (ex.: painel.dataset.panel='calendario' em app-shell.js). */
function painéisDoHtml() {
    const estaticos = [...html.matchAll(/data-panel="([a-z0-9-]+)"/g)].map(m => m[1]);
    const injetados = MODULOS.flatMap(src => [
        ...src.matchAll(/dataset\.panel\s*=\s*'([a-z0-9-]+)'/g),
        ...src.matchAll(/data-panel="([a-z0-9-]+)"/g),
    ].map(m => m[1]));
    return [...estaticos, ...injetados];
}

/* ---------------- INVENTÁRIO: nada pode sumir ---------------- */

test('todo painel existente no admin.html tem caminho de acesso na navegação', () => {
    const noMapa = new Set(paineisDoMapa(MAPA));
    const orfaos = [...new Set(painéisDoHtml())].filter(p => !noMapa.has(p));
    assert.deepEqual(orfaos, [], 'painéis sem caminho de acesso: ' + orfaos.join(', '));
});

test('toda vista da navegação aponta para um painel que existe de fato', () => {
    const noHtml = new Set(painéisDoHtml());
    const inventados = paineisDoMapa(MAPA).filter(p => !noHtml.has(p));
    assert.deepEqual(inventados, [], 'vistas sem painel: ' + inventados.join(', '));
});

test('as seções que estavam soltas ganham painel hospedeiro, nenhuma é removida', () => {
    for (const seletor of ['#fabricasWorkflowSection', '#profissionaisWorkflowSection',
        '#fase57Comando', '#fase55Governanca', '#whatsapp-omni-painel']) {
        assert.ok(fonte.includes(seletor), 'realocação ausente para ' + seletor);
        assert.ok(html.includes(seletor.slice(1)), 'seção removida do HTML: ' + seletor);
    }
    assert.ok(!fonte.includes('.remove()'),
        'nenhum nó existente pode ser removido do DOM: módulos registram '
        + 'carregamento preguiçoso em [data-tab] e some junto com o nó');
});

test('as abas legadas continuam no HTML — elas seguem sendo a fonte dos handlers', () => {
    for (const aba of ['visao-geral', 'ia-empresarial', 'crm', 'b2b', 'presenca-digital',
        'maranhao-intelligence', 'conselho-de-agentes', 'canais',
        'inteligencia-territorial', 'empresa', 'governanca']) {
        assert.ok(html.includes(`data-tab="${aba}"`), 'aba legada removida: ' + aba);
    }
});

/* ---------------- ESTRUTURA: no máximo 5 áreas ---------------- */

test('a navegação tem no máximo cinco áreas principais', () => {
    assert.ok(MAPA.length <= 5, `${MAPA.length} áreas`);
});

test('cada área tem rótulo de negócio e ao menos uma vista', () => {
    for (const area of MAPA) {
        assert.ok(area.rotulo && area.rotulo.length <= 16, 'rótulo longo: ' + area.rotulo);
        assert.ok(area.vistas.length >= 1);
        assert.ok(area.icone, 'ícone ausente em ' + area.id);
    }
});

test('toda vista tem título e uma frase curta de contexto', () => {
    for (const vista of MAPA.flatMap(a => a.vistas)) {
        assert.ok(vista.titulo, 'título ausente: ' + vista.painel);
        assert.ok(vista.descricao, 'descrição ausente: ' + vista.painel);
        assert.ok(vista.descricao.length <= 180, 'descrição longa: ' + vista.painel);
    }
});

test('há no máximo uma ação principal por vista', () => {
    for (const vista of MAPA.flatMap(a => a.vistas)) {
        if (!vista.acao) continue;
        const destinos = [vista.acao.clicar, vista.acao.focar].filter(Boolean);
        assert.equal(destinos.length, 1, 'mais de um destino em ' + vista.painel);
        assert.ok(vista.acao.rotulo);
    }
});

test('toda ação principal aponta para um controle que existe de fato', () => {
    for (const vista of MAPA.flatMap(a => a.vistas)) {
        if (!vista.acao) continue;
        const seletor = vista.acao.clicar || vista.acao.focar;
        const porId = seletor.match(/^#([A-Za-z0-9_-]+)/);
        const porAtributo = seletor.match(/\[([a-z-]+)="([^"]+)"\]/);
        if (porId) {
            const nome = porId[1];
            assert.ok(
                TUDO.includes(`id="${nome}"`) || TUDO.includes(`id = '${nome}'`)
                || TUDO.includes(`.id='${nome}'`) || TUDO.includes(`.id = '${nome}'`),
                'controle inexistente: ' + seletor,
            );
        } else if (porAtributo) {
            assert.ok(TUDO.includes(`${porAtributo[1]}="${porAtributo[2]}"`),
                'controle inexistente: ' + seletor);
        } else {
            assert.fail('seletor inesperado: ' + seletor);
        }
    }
});

test('toda sub-vista interna aponta para um controle que existe', () => {
    for (const vista of MAPA.flatMap(a => a.vistas)) {
        if (!vista.aoAbrir) continue;
        const m = vista.aoAbrir.match(/\[([a-z-]+)="([^"]+)"\]/);
        assert.ok(m, 'seletor inesperado: ' + vista.aoAbrir);
        assert.ok(TUDO.includes(`${m[1]}="${m[2]}"`), 'sub-vista inexistente: ' + vista.aoAbrir);
    }
});

test('o Início é a primeira área e a primeira vista', () => {
    assert.equal(MAPA[0].id, 'inicio');
    assert.equal(MAPA[0].vistas[0].painel, 'adm-inicio');
});

test('cada vista tem id único — duas podem dividir o mesmo painel', () => {
    const ids = vistasDoMapa(MAPA);
    assert.equal(new Set(ids).size, ids.length, 'id de vista repetido');
    const mi = MAPA.flatMap(a => a.vistas).filter(v => v.painel === 'maranhao-intelligence');
    assert.equal(mi.length, 3, 'Intelligence, Materiais e QR & Avaliações dividem o painel');
    assert.ok(mi.every(v => v.aoAbrir), 'vistas que dividem painel precisam abrir sub-vista própria');
});

test('as quatro capacidades auditadas têm entrada visível na navegação', () => {
    const porId = Object.fromEntries(MAPA.flatMap(a => a.vistas).map(v => [v.id, v]));
    // Agentes e calendário: vista própria.
    assert.ok(porId.conselho, 'sem entrada para os agentes');
    assert.ok(porId.agenda, 'sem entrada para o calendário');
    assert.equal(porId.agenda.painel, 'calendario');
    // PowerPoint e imagens: a vista Materiais abre o estúdio que os gera.
    assert.ok(porId.materiais, 'sem entrada para a criação de materiais');
    assert.equal(porId.materiais.aoAbrir, '[data-mic-view="creative"]');
    // Os oito nomes reais aparecem na descrição da vista dos agentes.
    for (const nome of ['Pirret', 'Standard', 'Zilda', 'Leonard', 'Marie', 'Rua', 'Dicio', 'Iris']) {
        assert.ok(porId.conselho.descricao.includes(nome), 'agente ausente: ' + nome);
    }
});

/* ---------------- BUSCA GLOBAL ---------------- */

const indice = construirIndice(MAPA, ATALHOS);

test('a busca cobre todas as vistas e os atalhos', () => {
    const vistas = indice.filter(i => i.tipo === 'vista');
    assert.equal(vistas.length, vistasDoMapa(MAPA).length);
    assert.equal(indice.filter(i => i.tipo === 'acao').length, ATALHOS.length);
});

test('a busca ignora acento e maiúscula', () => {
    const achados = filtrar(indice, 'APROVAÇOES').map(i => i.rotulo);
    assert.ok(achados.includes('Aprovações'), achados.join('|'));
    assert.deepEqual(filtrar(indice, 'aprovacoes').map(i => i.rotulo), achados);
});

test('quem começa com o termo vem antes de quem só o contém', () => {
    const achados = filtrar(indice, 'contatos');
    assert.equal(achados[0].rotulo, 'Contatos');
});

test('termo sem correspondência devolve lista vazia, nunca um palpite', () => {
    assert.deepEqual(filtrar(indice, 'zzzzzz'), []);
});

test('busca vazia mostra um começo curto, não o índice inteiro', () => {
    assert.ok(filtrar(indice, '').length <= 10);
});

test('cada resultado diz de que área veio', () => {
    for (const item of filtrar(indice, 'a')) assert.ok(item.contexto);
});

test('semAcento não quebra com valor ausente', () => {
    assert.equal(semAcento(null), '');
    assert.equal(semAcento(undefined), '');
});

/* ---------------- SEGURANÇA E NÃO-REGRESSÃO ---------------- */

test('o shell não faz nenhuma chamada de rede', () => {
    assert.ok(!fonte.includes('fetch('), 'o shell não pode falar com a API');
    assert.ok(!fonte.includes('XMLHttpRequest'));
});

test('o shell nunca escreve HTML cru (sem innerHTML)', () => {
    assert.ok(!fonte.includes('innerHTML'));
});

test('a troca de painel é delegada aos controles existentes', () => {
    assert.ok(fonte.includes('[data-tab="${painelId}"]'), 'deve clicar o controle legado');
    assert.ok(fonte.includes('.empresa-link[data-destino='), 'deve usar o atalho legado');
});

test('sair só limpa a sessão do navegador — não toca em credencial nem em fila', () => {
    const trecho = fonte.slice(fonte.indexOf('function sair()'), fonte.indexOf('botaoSair.addEventListener'));
    assert.ok(trecho.includes('sessionStorage.removeItem'));
    assert.ok(!trecho.includes('fetch'));
    assert.ok(!trecho.includes('localStorage.clear'));
});

test('a busca global só abre depois da autenticação', () => {
    assert.ok(fonte.includes("corpo.classList.contains('adm-dentro')"),
        'o atalho de teclado precisa checar que a pessoa entrou');
});

test('o armazenamento de sessão é sempre protegido por try/catch', () => {
    const usos = [...fonte.matchAll(/sessionStorage\.(getItem|setItem|removeItem)/g)];
    assert.ok(usos.length >= 3);
    for (const uso of usos) {
        const antes = fonte.slice(Math.max(0, uso.index - 260), uso.index);
        assert.ok(antes.includes('try {'), 'acesso a sessionStorage sem try/catch');
    }
});

test('nenhuma função fica escondida só em gesto, hover ou ícone sem rótulo', () => {
    for (const area of MAPA) {
        assert.ok(/\p{L}/u.test(area.rotulo), 'área sem rótulo textual: ' + area.id);
    }
    assert.ok(fonte.includes("criar('span', area.rotulo)"), 'a sidebar precisa mostrar o rótulo');
    assert.ok(fonte.includes("criar('span', area.rotulo)"), 'a barra mobile também');
    assert.ok(fonte.includes("setAttribute('aria-label'"), 'controles só com ícone precisam de nome acessível');
});

test('o contexto de leitura é preservado ao voltar de um detalhe', () => {
    assert.ok(fonte.includes('estado.rolagem[estado.vista] = window.scrollY'));
    assert.ok(fonte.includes('window.scrollTo('));
});

test('a experiência principal não expõe linguagem de desenvolvimento', () => {
    // Texto visível: o que está entre tags e o conteúdo de atributos de
    // rótulo. Comentários HTML e nomes de arquivo ficam de fora.
    const visivel = html
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/<script[\s\S]*?<\/script>/g, ' ')
        .replace(/<style[\s\S]*?<\/style>/g, ' ')
        .replace(/<[^>]+>/g, ' ');
    for (const termo of [/Fase\s*5/i, /Fase\s*4/i, /\bETAPA\s*\d/i, /migration/i, /mi_conselho/i, /SELECT /i]) {
        assert.ok(!termo.test(visivel), 'linguagem técnica visível: ' + termo);
    }
    for (const arquivo of ['adm-experiencia.js', 'adm-inicio.js', 'adm-apresentacao.js']) {
        const codigo = fs.readFileSync('maranhao-backend/' + arquivo, 'utf8')
            .replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ');
        // Só frases: seletores CSS, caminhos e chaves de estado ficam fora.
        const textos = [...codigo.matchAll(/'([^']{8,})'/g)].map(m => m[1])
            .filter(t => !/^[#.\[/]/.test(t) && /\s/.test(t));
        for (const texto of textos) {
            assert.ok(!/Fase\s*5|ETAPA\s*\d|tabela|SELECT |migration/i.test(texto),
                `${arquivo}: linguagem técnica em "${texto}"`);
        }
    }
});

test('cada tela é carregada uma única vez ao navegar', () => {
    // Clicar o primeiro [data-tab] faz o item da sidebar legada encaminhar
    // para a aba, que dispara os carregamentos. Clicar os dois disparia
    // duas consultas por tela.
    const trecho = fonte.slice(fonte.indexOf('function ativar('), fonte.indexOf('function esconderTituloDuplicado'));
    const cliques = [...trecho.matchAll(/\.click\(\)/g)];
    assert.equal(cliques.length, 2, 'um clique por caminho: aba legada ou atalho da Empresa');
    assert.ok(trecho.includes('return;'), 'os caminhos precisam ser exclusivos');
});

test('a ação principal não aparece duas vezes: o botão original só é ocultado', () => {
    const trecho = fonte.slice(fonte.indexOf('function esconderAcaoEspelhada'), fonte.indexOf('function aplicarAcao'));
    assert.ok(trecho.includes("classList.add('adm-acao-espelhada')"));
    assert.ok(!trecho.includes('.remove()'), 'o botão original precisa continuar no DOM');
    assert.ok(trecho.includes('painel.contains(alvo)'),
        'só o botão de dentro do próprio painel pode ser ocultado');
});

test('a busca encontra os recursos pelos termos que a pessoa usa', () => {
    const esperado = {
        agentes: 'Conselho de Agentes',
        conselho: 'Conselho de Agentes',
        especialistas: 'Conselho de Agentes',
        pirret: 'Conselho de Agentes',
        iris: 'Conselho de Agentes',
        agenda: 'Agenda',
        calendário: 'Agenda',
        calendario: 'Agenda',
        powerpoint: 'Materiais do Conselho',
        pptx: 'Materiais do Conselho',
        slides: 'Materiais do Conselho',
        imagens: 'Materiais do Conselho',
        rótulo: 'Materiais do Conselho',
    };
    for (const [termo, alvo] of Object.entries(esperado)) {
        const achados = filtrar(indice, termo).map(i => i.rotulo);
        assert.ok(achados.includes(alvo),
            `buscar "${termo}" não encontrou "${alvo}" (achou: ${achados.join(', ') || 'nada'})`);
    }
});

test('o calendário só existe em tempo de execução — o inventário precisa vê-lo', () => {
    // Guarda contra a regressão real: o primeiro inventário leu apenas o
    // admin.html e por isso não enxergou o painel criado por app-shell.js.
    assert.ok(!html.includes('data-panel="calendario"'),
        'se o calendário passar a ser estático, simplifique este teste');
    assert.ok(painéisDoHtml().includes('calendario'),
        'o inventário precisa ler os painéis injetados em tempo de execução');
});
