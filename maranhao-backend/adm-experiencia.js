/* ============================================================
   EXPERIÊNCIA DO ADM (2026) — estrutura, navegação e busca.

   Princípio: nenhuma regra de negócio vive aqui. Toda troca de
   tela é delegada aos controles que já existem (.admin-tab e
   .empresa-link), exatamente como painel-executivo.js e
   app-shell.js já faziam. Assim, cada painel continua sendo
   carregado pelo mesmo código de antes — nada de rede, nada de
   permissão e nada de estado de negócio foi reimplementado.

   O que este arquivo acrescenta:
   - 5 áreas de navegação com nomes de negócio (antes: 6 grupos
     e painéis sem caminho de acesso);
   - sub-navegação por vista, com revelação progressiva;
   - um cabeçalho por vista: título, uma frase e UMA ação
     principal;
   - busca global (Ctrl/Cmd+K) sobre vistas e ações;
   - preservação de contexto: a posição de rolagem de cada vista
     volta como estava ao retornar de um detalhe;
   - realocação (sem remover) das seções que estavam soltas no
     fim da página e não tinham lugar na navegação.
   ============================================================ */

(() => {
    'use strict';

    /* --------------------------------------------------------
       ARQUITETURA DE INFORMAÇÃO
       `painel` é sempre o data-panel de uma <section class="tab-panel">
       que JÁ existe (ou de um painel hospedeiro declarado no
       admin.html). Nenhuma vista inventa funcionalidade.
       -------------------------------------------------------- */
    const MAPA = [
        {
            id: 'inicio',
            rotulo: 'Início',
            icone: '◈',
            vistas: [
                {
                    painel: 'adm-inicio',
                    rotulo: 'Início',
                    titulo: 'Início',
                    descricao: 'O que está acontecendo, o que precisa de você e qual foi o resultado.',
                },
            ],
        },
        {
            id: 'decisoes',
            rotulo: 'Decisões',
            icone: '✓',
            contador: 'aprovacoes',
            vistas: [
                {
                    painel: 'governanca',
                    rotulo: 'Aprovações',
                    titulo: 'Aprovações',
                    descricao: 'Ações propostas pela tecnologia esperando sua decisão. Aprovar registra a decisão — nenhuma mensagem é enviada por aqui.',
                    acao: { rotulo: 'Atualizar lista', clicar: '#atualizar-acoes-comerciais' },
                },
                {
                    painel: 'conselho-de-agentes',
                    rotulo: 'Conselho',
                    titulo: 'Conselho de Agentes',
                    descricao: 'As análises dos especialistas, as divergências entre eles e o que ficou aguardando você.',
                    acao: { rotulo: 'Atualizar Conselho', clicar: '#conselho-atualizar' },
                },
                {
                    painel: 'acoes',
                    rotulo: 'Ações da empresa',
                    titulo: 'Ações da empresa',
                    descricao: 'Tarefas registradas com responsável, prazo e resultado.',
                    acao: { rotulo: 'Registrar ação', focar: '#acaoTitulo' },
                },
                {
                    painel: 'adm-autonomia',
                    rotulo: 'Autonomia',
                    titulo: 'Autonomia da operação',
                    descricao: 'Quanto a operação depende de você hoje e o que foi filtrado antes de chegar até aqui.',
                    acao: { rotulo: 'Atualizar', clicar: '#fase55Governanca button' },
                },
            ],
        },
        {
            id: 'comercial',
            rotulo: 'Comercial',
            icone: '◎',
            vistas: [
                {
                    painel: 'crm',
                    rotulo: 'Contatos',
                    titulo: 'Contatos',
                    descricao: 'Pessoas e empresas em relacionamento, com estágio, origem e histórico.',
                    acao: { rotulo: 'Cadastrar contato', focar: '#crmNome' },
                },
                {
                    painel: 'b2b',
                    rotulo: 'Oportunidades',
                    titulo: 'Oportunidades',
                    descricao: 'Interesses de bares, restaurantes, hotéis e distribuidores registrados pelo site.',
                },
                {
                    painel: 'pedidos',
                    rotulo: 'Pedidos',
                    titulo: 'Pedidos',
                    descricao: 'Compras registradas, situação de pagamento e de entrega.',
                },
                {
                    painel: 'degustacoes',
                    rotulo: 'Degustações',
                    titulo: 'Degustações',
                    descricao: 'Solicitações de degustação recebidas pelo site.',
                },
                {
                    painel: 'sac',
                    rotulo: 'Atendimento',
                    titulo: 'Atendimento',
                    descricao: 'Conversas recebidas e o que foi respondido.',
                },
                {
                    painel: 'adm-parceiros',
                    rotulo: 'Parceiros',
                    titulo: 'Parceiros',
                    descricao: 'Fábricas e profissionais cadastrados, com o andamento de cada um.',
                },
            ],
        },
        {
            id: 'inteligencia',
            rotulo: 'Inteligência',
            icone: '◇',
            vistas: [
                {
                    painel: 'ia-empresarial',
                    rotulo: 'Leitura do dia',
                    titulo: 'Leitura do dia',
                    descricao: 'O que a tecnologia observou, o que sugeriu e o que está esperando decisão.',
                    acao: { rotulo: 'Perguntar', focar: '#iaEmpresarialPergunta' },
                },
                {
                    painel: 'visao-geral',
                    rotulo: 'Panorama',
                    titulo: 'Panorama',
                    descricao: 'Uma leitura ampla do estado do negócio, reunindo todas as fontes disponíveis.',
                    acao: { rotulo: 'Atualizar dados', clicar: '#vg-atualizar' },
                },
                {
                    painel: 'maranhao-intelligence',
                    rotulo: 'Maranhão Intelligence',
                    titulo: 'Maranhão Intelligence',
                    descricao: 'Produto, unidades, estabelecimentos e território — de onde vêm os sinais.',
                    acao: { rotulo: 'Atualizar dados', clicar: '#mi-atualizar' },
                },
                {
                    painel: 'inteligencia-territorial',
                    rotulo: 'Território',
                    titulo: 'Inteligência Territorial',
                    descricao: 'Onde a marca está presente e o que foi registrado em cada lugar.',
                    acao: { rotulo: 'Atualizar dados', clicar: '#territorio-atualizar' },
                },
                {
                    painel: 'adm-prospeccao',
                    rotulo: 'Prospecção',
                    titulo: 'Prospecção',
                    descricao: 'Defina um objetivo e a busca de contatos entra no ciclo com aprovação humana antes de qualquer envio.',
                    acao: { rotulo: 'Definir objetivo', focar: '#f57objetivo' },
                },
            ],
        },
        {
            id: 'operacao',
            rotulo: 'Operação',
            icone: '⚙',
            vistas: [
                {
                    painel: 'canais',
                    rotulo: 'Canais',
                    titulo: 'Canais',
                    descricao: 'O que está conectado, o que está pendente e qual é o próximo passo de cada canal.',
                    acao: { rotulo: 'Atualizar canais', clicar: '#canais-atualizar' },
                },
                {
                    painel: 'presenca-digital',
                    rotulo: 'Presença digital',
                    titulo: 'Presença digital',
                    descricao: 'Audiência, alcance e origem do tráfego, conforme cada fonte permitir ler.',
                },
                {
                    painel: 'adm-mensagens',
                    rotulo: 'Mensagens',
                    titulo: 'Mensagens',
                    descricao: 'E-mail institucional e WhatsApp: estado da conexão e entradas em revisão.',
                    acao: { rotulo: 'Atualizar WhatsApp', clicar: '#whatsapp-omni-atualizar' },
                },
                {
                    painel: 'documentos',
                    rotulo: 'Documentos',
                    titulo: 'Documentos',
                    descricao: 'Documentos da empresa, versões e nível de acesso.',
                    acao: { rotulo: 'Enviar documento', focar: '#docNome' },
                },
                {
                    painel: 'empresa',
                    rotulo: 'Empresa',
                    titulo: 'Empresa',
                    descricao: 'Atalhos da operação, preservados como estavam.',
                },
            ],
        },
    ];

    /* Ações de acesso rápido: entram na busca global junto das
       vistas. Cada uma aponta para um controle real já existente. */
    const ATALHOS = [
        { rotulo: 'Conectar e-mail institucional', painel: 'adm-mensagens', clicar: '#adm-mensagens button' },
        { rotulo: 'Ver apresentação executiva', apresentacao: true },
        { rotulo: 'Sair da Central', sair: true },
    ];

    /* --------------------------------------------------------
       ÍNDICE DE BUSCA (puro — testável sem DOM)
       -------------------------------------------------------- */

    function semAcento(texto) {
        return String(texto == null ? '' : texto)
            .normalize('NFD')
            .replace(/[̀-ͯ]/g, '')
            .toLowerCase();
    }

    function construirIndice(mapa, atalhos) {
        const itens = [];
        for (const area of mapa) {
            for (const vista of area.vistas) {
                itens.push({
                    tipo: 'vista',
                    rotulo: vista.titulo,
                    contexto: area.rotulo,
                    area: area.id,
                    painel: vista.painel,
                    termos: semAcento(
                        [vista.titulo, vista.rotulo, area.rotulo, vista.descricao].join(' ')
                    ),
                });
            }
        }
        for (const atalho of atalhos || []) {
            itens.push({
                tipo: 'acao',
                rotulo: atalho.rotulo,
                contexto: 'Ação',
                painel: atalho.painel || null,
                clicar: atalho.clicar || null,
                apresentacao: !!atalho.apresentacao,
                sair: !!atalho.sair,
                termos: semAcento(atalho.rotulo),
            });
        }
        return itens;
    }

    /* Ranking simples e previsível: começa com o termo > contém o
       termo. Sem busca difusa — a pessoa precisa reconhecer por que
       um resultado apareceu. */
    function filtrar(indice, termo) {
        const alvo = semAcento(termo).trim();
        if (!alvo) return indice.slice(0, 10);
        const pontuado = [];
        for (const item of indice) {
            const posicao = item.termos.indexOf(alvo);
            if (posicao < 0) continue;
            const comecaRotulo = semAcento(item.rotulo).startsWith(alvo);
            pontuado.push({ item, peso: comecaRotulo ? 0 : (posicao === 0 ? 1 : 2) });
        }
        pontuado.sort((a, b) => a.peso - b.peso);
        return pontuado.map(p => p.item).slice(0, 12);
    }

    /* Inventário: todo data-panel presente na página precisa ter um
       caminho de acesso no mapa. Usado pelos testes para garantir
       que nenhuma função sumiu. */
    function paineisDoMapa(mapa) {
        return mapa.flatMap(area => area.vistas.map(v => v.painel));
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { MAPA, ATALHOS, construirIndice, filtrar, paineisDoMapa, semAcento };
    }

    if (typeof document === 'undefined' || !document.getElementById('adminTabs')) return;

    /* --------------------------------------------------------
       CONSTRUÇÃO DO SHELL
       -------------------------------------------------------- */

    const corpo = document.body;
    const conteudo = document.getElementById('adminContent');
    const shell = document.querySelector('.admin-shell');
    if (!conteudo || !shell) return;

    const criar = (tag, texto, classe) => {
        const no = document.createElement(tag);
        if (texto !== undefined && texto !== null) no.textContent = texto;
        if (classe) no.className = classe;
        return no;
    };

    const estado = {
        area: 'inicio',
        painel: 'adm-inicio',
        rolagem: Object.create(null),
    };

    const indice = construirIndice(MAPA, ATALHOS);
    const vistaPorPainel = new Map();
    const areaPorPainel = new Map();
    for (const area of MAPA) {
        for (const vista of area.vistas) {
            vistaPorPainel.set(vista.painel, vista);
            areaPorPainel.set(vista.painel, area);
        }
    }

    /* A sidebar da etapa anterior sai de cena, mas CONTINUA no DOM.
       Motivo concreto: vários módulos (conselho-agentes.js,
       canais-status.js, mi-graficos.js, visao-geral.js, modo-diretor.js)
       registram o carregamento preguiçoso em
       document.querySelector('[data-tab="..."]') — e esse primeiro
       elemento do documento é justamente um item daquela sidebar, que é
       inserida no começo do <body>. Removê-la levava junto esses
       ouvintes, e telas como o Conselho ficavam eternamente em "Abra esta
       seção para consultar". Esconder via CSS preserva todos eles. */
    corpo.classList.remove('app-shell-sidebar-ativa');

    /* --- Realocação das seções soltas ---------------------------
       Mover um nó preserva seus ouvintes de evento: nenhum handler é
       reatribuído, nenhum comportamento muda. Só deixam de flutuar
       no fim da página sem caminho de navegação. */
    function realocar(seletorOrigem, idDestino) {
        const origem = document.querySelector(seletorOrigem);
        const destino = document.getElementById(idDestino);
        if (!origem || !destino) return;
        destino.append(origem);
        origem.style.margin = '0 0 24px';
        origem.style.maxWidth = 'none';
        origem.style.padding = origem.style.padding || '0';
    }

    realocar('#fabricasWorkflowSection', 'adm-parceiros');
    realocar('#profissionaisWorkflowSection', 'adm-parceiros');
    realocar('#fase57Comando', 'adm-prospeccao');
    realocar('#fase55Governanca', 'adm-autonomia');
    realocar('[data-app-futuro-grupo="operacao"]', 'adm-mensagens');
    realocar('#whatsapp-omni-painel', 'adm-mensagens');

    /* --- Topo --------------------------------------------------- */
    const topo = criar('header', undefined, 'adm-topbar');
    topo.append(criar('span', 'Maranhão Cordial', 'adm-topbar-marca'));

    const buscaBotao = criar('button', undefined, 'adm-busca-abrir');
    buscaBotao.type = 'button';
    buscaBotao.setAttribute('aria-label', 'Buscar telas e ações');
    // Rótulo completo no desktop, curto no celular — nunca só ícone.
    buscaBotao.append(
        criar('span', '⌕', 'adm-busca-icone'),
        criar('span', 'Buscar telas e ações', 'adm-busca-longo'),
        criar('span', 'Buscar', 'adm-busca-curto'),
        criar('span', '⌘K', 'adm-busca-atalho')
    );
    topo.append(buscaBotao);

    const acoesTopo = criar('div', undefined, 'adm-topbar-acoes');
    const botaoApresentar = criar('button', 'Apresentação', 'adm-topbar-botao');
    botaoApresentar.type = 'button';
    const botaoSair = criar('button', 'Sair', 'adm-topbar-botao');
    botaoSair.type = 'button';
    acoesTopo.append(botaoApresentar, botaoSair);
    topo.append(acoesTopo);

    /* --- Navegação principal ------------------------------------ */
    const nav = criar('nav', undefined, 'adm-nav');
    nav.setAttribute('aria-label', 'Áreas da Central');

    const marca = criar('div', undefined, 'adm-nav-marca');
    marca.append(document.createTextNode('Central'), criar('small', 'Maranhão Cordial'));
    nav.append(marca);

    const barraMobile = criar('nav', undefined, 'adm-mobilebar');
    barraMobile.setAttribute('aria-label', 'Áreas da Central');

    const botoesArea = new Map();
    const botoesAreaMobile = new Map();
    const listasVista = new Map();
    const botoesVista = new Map();
    const contadores = new Map();

    for (const area of MAPA) {
        const botao = criar('button', undefined, 'adm-area');
        botao.type = 'button';
        botao.dataset.area = area.id;
        botao.append(criar('span', area.icone, 'adm-area-icone'), criar('span', area.rotulo));
        if (area.contador) {
            const sino = criar('span', '', 'adm-area-sino');
            sino.hidden = true;
            botao.append(sino);
            contadores.set(area.contador, sino);
        }
        botao.addEventListener('click', () => abrirArea(area.id));
        nav.append(botao);
        botoesArea.set(area.id, botao);

        const lista = criar('div', undefined, 'adm-vistas');
        lista.hidden = true;
        lista.dataset.unica = String(area.vistas.length < 2);
        for (const vista of area.vistas) {
            const item = criar('button', vista.rotulo, 'adm-vista');
            item.type = 'button';
            item.dataset.painel = vista.painel;
            item.addEventListener('click', () => irPara(vista.painel));
            lista.append(item);
            botoesVista.set(vista.painel, item);
        }
        nav.append(lista);
        listasVista.set(area.id, lista);

        const mob = criar('button', undefined, 'adm-mob-area');
        mob.type = 'button';
        mob.append(criar('span', area.icone, 'adm-mob-icone'), criar('span', area.rotulo));
        mob.addEventListener('click', () => abrirArea(area.id));
        barraMobile.append(mob);
        botoesAreaMobile.set(area.id, mob);
    }

    /* --- Cabeçalho da vista ------------------------------------- */
    const cabecalho = criar('div', undefined, 'adm-cabecalho');
    const textoCabecalho = criar('div', undefined, 'adm-cabecalho-texto');
    const trilha = criar('p', '', 'adm-trilha');
    const titulo = criar('h1', '');
    const descricao = criar('p', '');
    textoCabecalho.append(trilha, titulo, descricao);
    const acaoPrincipal = criar('button', '', 'adm-acao-principal');
    acaoPrincipal.type = 'button';
    acaoPrincipal.hidden = true;
    cabecalho.append(textoCabecalho, acaoPrincipal);

    /* Fileira de vistas para telas estreitas (a sidebar some). */
    const chipsMobile = criar('div', undefined, 'adm-vistas-mobile');
    const chipsPorPainel = new Map();

    conteudo.prepend(chipsMobile);
    conteudo.prepend(cabecalho);
    shell.prepend(nav);
    corpo.prepend(topo);
    corpo.append(barraMobile);

    /* --------------------------------------------------------
       NAVEGAÇÃO
       -------------------------------------------------------- */

    function painelDe(id) {
        return document.querySelector(`.tab-panel[data-panel="${id}"]`);
    }

    /* Delegação: o controle legado continua sendo quem troca de
       painel e quem dispara os carregamentos. Só quando não existe
       controle legado (painéis hospedeiros novos) a troca é feita
       aqui, com exatamente a mesma regra do código original. */
    function ativar(painelId) {
        /* Sem o seletor de classe de propósito: pega o MESMO elemento que
           os módulos existentes observam (o primeiro [data-tab] do
           documento). Ele encaminha o clique para a aba legada, então
           tudo dispara exatamente uma vez — nada é carregado em dobro. */
        const aba = document.querySelector(`[data-tab="${painelId}"]`);
        if (aba) {
            aba.click();
            return;
        }
        const atalhoEmpresa = document.querySelector(`.empresa-link[data-destino="${painelId}"]`);
        if (atalhoEmpresa) {
            atalhoEmpresa.click();
            return;
        }
        document.querySelectorAll('.tab-panel').forEach(painel => {
            painel.classList.toggle('active', painel.dataset.panel === painelId);
        });
    }

    /* O cabeçalho da vista (título + frase + ação) substitui o cabeçalho
       que cada painel trazia. Esconder é feito uma única vez por painel e
       só no cabeçalho de nível mais alto: títulos de seções internas
       (ex.: os três blocos do Panorama) continuam visíveis, porque eles
       organizam o conteúdo em vez de repetir o nome da tela. */
    function esconderTituloDuplicado(painel, tituloVista) {
        if (!painel || painel.dataset.admTituloTratado) return;
        painel.dataset.admTituloTratado = '1';

        const proprio = [...painel.children].find(no =>
            no.classList && (no.classList.contains('app-shell-cabecalho') || no.classList.contains('mi-topo'))
        );
        if (proprio) {
            proprio.hidden = true;
            return;
        }

        const alvo = semAcento(tituloVista);
        for (const h of painel.querySelectorAll('h2')) {
            if (semAcento(h.textContent).trim() !== alvo) continue;
            h.hidden = true;
            const anterior = h.previousElementSibling;
            if (anterior && /eyebrow/.test(anterior.className || '')) anterior.hidden = true;
            break;
        }
    }

    /* Quando a ação principal da vista é exatamente um botão que já existe
       dentro do painel, o botão de dentro sai de cena: a mesma ação em dois
       lugares é ruído. O elemento continua no DOM e continua sendo ele que
       recebe o clique — o cabeçalho é só o novo lugar dele. */
    function esconderAcaoEspelhada(painel, vista) {
        if (!painel || !vista.acao || !vista.acao.clicar) return;
        if (painel.dataset.admAcaoTratada) return;
        painel.dataset.admAcaoTratada = '1';
        const alvo = document.querySelector(vista.acao.clicar);
        if (alvo && painel.contains(alvo) && alvo.tagName === 'BUTTON') {
            alvo.classList.add('adm-acao-espelhada');
        }
    }

    function aplicarAcao(vista) {
        acaoPrincipal.hidden = !vista.acao;
        if (!vista.acao) return;
        acaoPrincipal.textContent = vista.acao.rotulo;
        acaoPrincipal.onclick = () => {
            const seletor = vista.acao.clicar || vista.acao.focar;
            const alvo = seletor ? document.querySelector(seletor) : null;
            if (!alvo) return;
            if (vista.acao.clicar) {
                alvo.click();
                return;
            }
            alvo.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (typeof alvo.focus === 'function') alvo.focus({ preventScroll: true });
        };
    }

    function sincronizarChips(area) {
        chipsMobile.replaceChildren();
        chipsPorPainel.clear();
        if (area.vistas.length < 2) return;
        for (const vista of area.vistas) {
            const chip = criar('button', vista.rotulo, 'adm-chip');
            chip.type = 'button';
            chip.addEventListener('click', () => irPara(vista.painel));
            chipsMobile.append(chip);
            chipsPorPainel.set(vista.painel, chip);
        }
    }

    function marcarAtual() {
        for (const [id, botao] of botoesArea) {
            botao.setAttribute('aria-current', String(id === estado.area));
        }
        for (const [id, botao] of botoesAreaMobile) {
            botao.setAttribute('aria-current', String(id === estado.area));
        }
        for (const [id, lista] of listasVista) {
            // Uma área com vista única não repete o próprio nome abaixo dele.
            lista.hidden = id !== estado.area || lista.dataset.unica === 'true';
        }
        for (const [painelId, botao] of botoesVista) {
            botao.setAttribute('aria-current', String(painelId === estado.painel));
        }
        for (const [painelId, chip] of chipsPorPainel) {
            chip.setAttribute('aria-current', String(painelId === estado.painel));
        }
    }

    function irPara(painelId, opcoes) {
        const vista = vistaPorPainel.get(painelId);
        if (!vista) return;
        const area = areaPorPainel.get(painelId);

        /* Contexto preservado: a posição de leitura da vista que está
           saindo é guardada para quando a pessoa voltar. */
        if (estado.painel && estado.painel !== painelId) {
            estado.rolagem[estado.painel] = window.scrollY || 0;
        }

        estado.area = area.id;
        estado.painel = painelId;
        ativar(painelId);

        trilha.textContent = area.rotulo;
        titulo.textContent = vista.titulo;
        descricao.textContent = vista.descricao || '';
        aplicarAcao(vista);
        esconderTituloDuplicado(painelDe(painelId), vista.titulo);
        esconderAcaoEspelhada(painelDe(painelId), vista);
        sincronizarChips(area);
        marcarAtual();

        const painel = painelDe(painelId);
        if (painel) {
            painel.classList.remove('adm-entrando');
            void painel.offsetWidth;
            painel.classList.add('adm-entrando');
        }

        try {
            sessionStorage.setItem('adm.painel', painelId);
        } catch (erro) {
            /* Navegação privada ou armazenamento bloqueado: a tela
               funciona igual, só não lembra a última vista. */
        }

        const anterior = estado.rolagem[painelId];
        window.scrollTo({ top: (opcoes && opcoes.manterRolagem) ? window.scrollY : (anterior || 0), behavior: 'auto' });
        window.dispatchEvent(new CustomEvent('adm-vista', { detail: { painel: painelId, area: area.id } }));
    }

    function abrirArea(areaId) {
        const area = MAPA.find(a => a.id === areaId);
        if (!area) return;
        /* Abrir uma área leva à última vista usada nela, não sempre à
           primeira: quem já estava em "Pedidos" volta para "Pedidos". */
        const ultima = estado.rolagem['__area_' + areaId];
        const destino = (ultima && vistaPorPainel.has(ultima)) ? ultima : area.vistas[0].painel;
        irPara(destino);
        estado.rolagem['__area_' + areaId] = destino;
    }

    window.addEventListener('adm-vista', evento => {
        estado.rolagem['__area_' + evento.detail.area] = evento.detail.painel;
    });

    window.admIrPara = irPara;

    /* --------------------------------------------------------
       BUSCA GLOBAL
       -------------------------------------------------------- */

    const paleta = criar('div', undefined, 'adm-paleta');
    paleta.hidden = true;
    paleta.setAttribute('role', 'dialog');
    paleta.setAttribute('aria-modal', 'true');
    paleta.setAttribute('aria-label', 'Buscar telas e ações');
    const caixa = criar('div', undefined, 'adm-paleta-caixa');
    const campo = document.createElement('input');
    campo.type = 'search';
    campo.placeholder = 'Buscar telas e ações…';
    campo.setAttribute('aria-label', 'Buscar telas e ações');
    const listaPaleta = criar('div', undefined, 'adm-paleta-lista');
    caixa.append(campo, listaPaleta);
    paleta.append(caixa);
    corpo.append(paleta);

    let selecionado = 0;
    let resultados = [];

    function executarItem(item) {
        fecharPaleta();
        if (item.apresentacao) {
            window.dispatchEvent(new Event('adm-abrir-apresentacao'));
            return;
        }
        if (item.sair) {
            sair();
            return;
        }
        if (item.painel) irPara(item.painel);
        if (item.clicar) {
            const alvo = document.querySelector(item.clicar);
            if (alvo) alvo.click();
        }
    }

    function desenharResultados() {
        listaPaleta.replaceChildren();
        if (!resultados.length) {
            listaPaleta.append(criar('p', 'Nada encontrado com esse termo.', 'adm-paleta-vazio'));
            return;
        }
        resultados.forEach((item, posicao) => {
            const botao = criar('button', undefined, 'adm-paleta-item');
            botao.type = 'button';
            botao.setAttribute('aria-selected', String(posicao === selecionado));
            botao.append(criar('span', item.rotulo), criar('small', item.contexto));
            botao.addEventListener('click', () => executarItem(item));
            listaPaleta.append(botao);
        });
    }

    function atualizarBusca() {
        resultados = filtrar(indice, campo.value);
        selecionado = 0;
        desenharResultados();
    }

    function abrirPaleta() {
        paleta.hidden = false;
        campo.value = '';
        atualizarBusca();
        campo.focus();
    }

    function fecharPaleta() {
        paleta.hidden = true;
    }

    campo.addEventListener('input', atualizarBusca);
    campo.addEventListener('keydown', evento => {
        if (evento.key === 'ArrowDown' || evento.key === 'ArrowUp') {
            evento.preventDefault();
            if (!resultados.length) return;
            selecionado = (selecionado + (evento.key === 'ArrowDown' ? 1 : -1) + resultados.length) % resultados.length;
            desenharResultados();
            return;
        }
        if (evento.key === 'Enter') {
            evento.preventDefault();
            if (resultados[selecionado]) executarItem(resultados[selecionado]);
            return;
        }
        if (evento.key === 'Escape') fecharPaleta();
    });
    paleta.addEventListener('click', evento => {
        if (evento.target === paleta) fecharPaleta();
    });
    buscaBotao.addEventListener('click', abrirPaleta);
    document.addEventListener('keydown', evento => {
        if ((evento.metaKey || evento.ctrlKey) && evento.key.toLowerCase() === 'k') {
            evento.preventDefault();
            if (corpo.classList.contains('adm-dentro')) abrirPaleta();
        }
    });

    /* --------------------------------------------------------
       ENTRADA / SAÍDA
       -------------------------------------------------------- */

    function sair() {
        /* Só limpa a sessão do navegador. Não toca em credencial, em
           dado do servidor nem em nenhuma fila. */
        window.adminKeyAtual = '';
        try {
            sessionStorage.removeItem('adm.painel');
        } catch (erro) { /* armazenamento indisponível */ }
        window.location.reload();
    }

    botaoSair.addEventListener('click', sair);
    botaoApresentar.addEventListener('click', () => {
        window.dispatchEvent(new Event('adm-abrir-apresentacao'));
    });

    /* Marca de pendência na área Decisões: lê o mesmo texto de status
       que a fila de aprovações já publica — nenhuma consulta extra. */
    const statusAcoes = document.getElementById('status-acoes-comerciais');
    if (statusAcoes && contadores.has('aprovacoes')) {
        const sino = contadores.get('aprovacoes');
        const avaliar = () => {
            const encontrado = (statusAcoes.textContent || '').match(/^(\d+)\s+a[çc]/i);
            const total = encontrado ? Number(encontrado[1]) : 0;
            sino.hidden = total <= 0;
            sino.textContent = total > 0 ? String(total) : '';
        };
        new MutationObserver(avaliar).observe(statusAcoes, {
            childList: true, characterData: true, subtree: true,
        });
        avaliar();
    }

    window.addEventListener('admin-autorizado', () => {
        corpo.classList.remove('adm-fora');
        corpo.classList.add('adm-dentro');
        let inicial = 'adm-inicio';
        try {
            const guardado = sessionStorage.getItem('adm.painel');
            if (guardado && vistaPorPainel.has(guardado)) inicial = guardado;
        } catch (erro) { /* armazenamento indisponível */ }
        irPara(inicial);
    });
})();
