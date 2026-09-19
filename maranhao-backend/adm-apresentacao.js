/* ============================================================
   APRESENTAÇÃO EXECUTIVA — somente leitura, quatro passos.

   Usa os mesmos dados e a mesma identidade do sistema: uma única
   chamada GET a /api/admin/apresentacao, que já devolve o corpo
   agregado e sem dados pessoais (adm_apresentacao.py). Nenhuma
   escrita, nenhum envio, nenhum link público é criado aqui.

   A restrição de acesso é do servidor: /api/admin/* exige chave
   administrativa válida. Esta tela apenas desenha o que a rota
   autorizou — se a chave não existir, não há o que mostrar.

   Tradução: todo texto visível vive em TEXTOS[idioma]. Acrescentar
   um idioma é acrescentar uma chave — nenhuma frase está presa ao
   desenho. Nenhum idioma adicional é escolhido aqui: a preferência
   é confirmada antes de ser disponibilizada.
   ============================================================ */

(() => {
    'use strict';

    const TEXTOS = {
        'pt-BR': {
            selo: 'Apresentação executiva',
            fechar: 'Fechar',
            somenteLeitura: 'Somente leitura',
            passos: ['O negócio', 'A oportunidade', 'O controle', 'O resultado'],
            carregando: 'Preparando a leitura…',
            indisponivel: 'A apresentação não pôde ser montada agora.',
            indisponivelNota: 'Nenhum dado foi alterado. Tente novamente em instantes.',
            semDado: 'sem dados',
            negocio: {
                eyebrow: 'Maranhão Cordial',
                titulo: 'Cordiais brasileiros, com a operação registrada em um só lugar.',
                linha: 'A plataforma registra relacionamento, pedidos, canais e decisões no mesmo lugar. Os números abaixo são leitura direta dos registros — não há dados de demonstração.',
                contatos: 'Contatos em relacionamento',
                contatosNota: 'Estágios abertos, sem clientes fechados nem cadastros de teste.',
                pracas: 'Praças alcançadas',
                pracasNota: 'Cidades distintas com relacionamento registrado.',
                pedidos: 'Pedidos pagos',
                pedidosNota: 'Com pagamento confirmado; de {total} pedidos registrados.',
                receita: 'Receita confirmada',
                receitaNota: 'Somente pedidos pagos. Propostas e oportunidades não entram aqui.',
            },
            oportunidade: {
                eyebrow: 'Do sinal ao trabalho',
                titulo: 'Uma oportunidade real, com trabalho registrado sobre ela.',
                semOportunidade: 'Nenhuma oportunidade aberta está registrada neste momento.',
                semOportunidadeNota: 'A plataforma não cria oportunidades para ter o que mostrar. Quando houver sinal nos registros, ela aparece aqui.',
                prioridade: 'Prioridade atribuída',
                acao: 'Ação sugerida',
                aprovacao: 'Exige aprovação humana',
                abertas: 'Oportunidades abertas',
                prioridades: { urgente: 'Urgente', alta: 'Alta', normal: 'Normal', baixa: 'Baixa', outro: 'Não classificada' },
                acoes: {
                    pesquisar: 'Procurar contatos', classificar: 'Classificar',
                    analisar: 'Analisar', planejar: 'Planejar',
                    sugerir_conteudo: 'Sugerir conteúdo', enviar_followup: 'Enviar retorno',
                    avaliar_reengajamento: 'Avaliar reengajamento', revisar_bloqueio: 'Revisar bloqueio',
                    decidir_proposta: 'Decidir proposta', priorizar_atendimento: 'Priorizar atendimento',
                    informar_diretor: 'Informar a direção', outro: 'Não classificada',
                },
                sim: 'sim', nao: 'não',
                trabalho: 'Trabalho da tecnologia',
                concluidas: 'Atividades concluídas',
                planejadas: 'Planejadas para hoje',
                especialistas: 'Especialistas em atividade',
                divergencias: 'Divergências registradas',
            },
            controle: {
                eyebrow: 'Controle humano',
                titulo: 'Nada sai daqui sem uma decisão de uma pessoa.',
                linha: 'Cada ação proposta pela tecnologia entra numa fila de aprovação. Aprovar registra a decisão; a execução é um passo separado e auditado. Não existe envio automático.',
                propostas: 'Ações propostas',
                aguardando: 'Aguardando aprovação',
                aprovadas: 'Aprovadas',
                rejeitadas: 'Rejeitadas',
                executadas: 'Executadas',
                filaNaoLida: 'A fila de aprovações não pôde ser lida agora.',
                envio: 'Envio automático: desligado.',
            },
            resultado: {
                eyebrow: 'Resultado',
                titulo: 'O que está comprovado — e o que ainda não está.',
                confirmados: 'Resultados confirmados',
                semConfirmacao: 'Execuções sem confirmação',
                etapa: 'Etapa alcançada',
                etapas: {
                    acao_executada: 'Ações aprovadas já foram executadas e auditadas.',
                    acao_aprovada: 'Há ações aprovadas aguardando execução.',
                    acao_aguardando_aprovacao: 'Há ações propostas aguardando decisão humana.',
                    acao_proposta: 'A tecnologia já propõe ações a partir dos registros.',
                    relacionamento_em_andamento: 'O relacionamento comercial está registrado e em andamento.',
                    operacao_preparada: 'A operação está preparada; ainda não há ação comercial proposta.',
                    fila_nao_lida: 'A fila de aprovações não pôde ser lida agora.',
                },
                capacidades: 'Capacidades em operação',
                estados: { conectado: 'Conectado', pendente: 'Pendente', bloqueado: 'Bloqueado' },
                leitura: 'leitura',
                escrita: 'escrita',
            },
            limites: 'Critérios desta leitura',
            traducao: 'Interface preparada para tradução. Um idioma adicional é habilitado depois que a preferência for confirmada.',
        },
    };

    function textos(idioma) {
        return TEXTOS[idioma] || TEXTOS['pt-BR'];
    }

    /* Formatação pura — exportada para teste. */
    function formatarDinheiro(centavos, idioma) {
        if (centavos === null || centavos === undefined) return null;
        return (Number(centavos) / 100).toLocaleString(idioma || 'pt-BR', {
            style: 'currency', currency: 'BRL', maximumFractionDigits: 0,
        });
    }

    /* Nenhum campo de texto livre é aceito: se o servidor mandasse algo
       fora da enumeração (não manda), a interface mostraria o código cru
       em vez de inventar uma frase. */
    function descreverEtapa(codigo, idioma) {
        const t = textos(idioma);
        return t.resultado.etapas[codigo] || codigo || '—';
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { TEXTOS, textos, formatarDinheiro, descreverEtapa };
    }

    if (typeof document === 'undefined') return;

    const API = 'https://maranhao-cordial-api.onrender.com';
    let idioma = 'pt-BR';
    let dados = null;
    let passo = 0;
    let carregando = false;

    const criar = (tag, texto, classe) => {
        const no = document.createElement(tag);
        if (texto !== undefined && texto !== null) no.textContent = texto;
        if (classe) no.className = classe;
        return no;
    };
    const numero = v => (v === null || v === undefined ? null : Number(v).toLocaleString('pt-BR'));

    const painel = criar('div', undefined, 'adm-apresentacao');
    painel.hidden = true;
    painel.setAttribute('role', 'dialog');
    painel.setAttribute('aria-modal', 'true');

    const topo = criar('div', undefined, 'adm-ap-topo');
    const selo = criar('span', '', 'adm-ap-selo');
    const somenteLeitura = criar('span', '', 'adm-topbar-botao');
    somenteLeitura.style.pointerEvents = 'none';
    const passosBox = criar('div', undefined, 'adm-ap-passos');
    const fechar = criar('button', '', 'adm-topbar-botao');
    fechar.type = 'button';
    topo.append(selo, somenteLeitura, passosBox, fechar);

    const palco = criar('div', undefined, 'adm-ap-palco');
    painel.append(topo, palco);
    document.body.append(painel);

    function caixaNumero(rotulo, valor, nota) {
        const caixa = criar('article', undefined, 'adm-ap-num');
        caixa.append(criar('span', rotulo));
        caixa.append(criar('strong', valor === null ? textos(idioma).semDado : valor));
        if (nota) caixa.append(criar('small', nota));
        return caixa;
    }

    function desenharNegocio(t) {
        const s = dados.situacao;
        palco.append(
            criar('p', t.negocio.eyebrow, 'adm-ap-eyebrow'),
            criar('h2', t.negocio.titulo, 'adm-ap-titulo'),
            criar('p', t.negocio.linha, 'adm-ap-linha')
        );
        const grade = criar('div', undefined, 'adm-ap-grade');
        grade.append(
            caixaNumero(t.negocio.contatos, s ? numero(s.contatos_em_relacionamento) : null, t.negocio.contatosNota),
            caixaNumero(t.negocio.pracas, s ? numero(s.pracas_alcancadas) : null, t.negocio.pracasNota),
            caixaNumero(t.negocio.pedidos, s ? numero(s.pedidos_pagos) : null,
                s ? t.negocio.pedidosNota.replace('{total}', numero(s.pedidos_registrados)) : null),
            caixaNumero(t.negocio.receita, s ? formatarDinheiro(s.receita_confirmada_centavos, idioma) : null, t.negocio.receitaNota)
        );
        palco.append(grade);
    }

    function desenharOportunidade(t) {
        const o = dados.oportunidade;
        const trabalho = dados.trabalho_da_tecnologia;
        palco.append(
            criar('p', t.oportunidade.eyebrow, 'adm-ap-eyebrow'),
            criar('h2', t.oportunidade.titulo, 'adm-ap-titulo')
        );
        if (!o) {
            palco.append(
                criar('p', t.oportunidade.semOportunidade, 'adm-ap-linha'),
                criar('p', t.oportunidade.semOportunidadeNota, 'adm-ap-rodape')
            );
        } else {
            const grade = criar('div', undefined, 'adm-ap-grade');
            grade.append(
                caixaNumero(t.oportunidade.abertas, numero(o.total_abertas)),
                caixaNumero(t.oportunidade.prioridade, t.oportunidade.prioridades[o.prioridade] || o.prioridade),
                caixaNumero(t.oportunidade.acao, t.oportunidade.acoes[o.proxima_acao] || o.proxima_acao),
                caixaNumero(t.oportunidade.aprovacao, o.exige_aprovacao ? t.oportunidade.sim : t.oportunidade.nao)
            );
            palco.append(grade);
        }
        if (trabalho) {
            palco.append(criar('p', t.oportunidade.trabalho, 'adm-ap-eyebrow'));
            const grade = criar('div', undefined, 'adm-ap-grade');
            grade.append(
                caixaNumero(t.oportunidade.concluidas, numero(trabalho.concluidas_recentes)),
                caixaNumero(t.oportunidade.planejadas, numero(trabalho.planejadas_hoje)),
                caixaNumero(t.oportunidade.especialistas, numero(trabalho.especialistas_ativos)),
                caixaNumero(t.oportunidade.divergencias, numero(trabalho.divergencias_registradas))
            );
            palco.append(grade);
        }
    }

    function desenharControle(t) {
        const c = dados.controle_humano;
        palco.append(
            criar('p', t.controle.eyebrow, 'adm-ap-eyebrow'),
            criar('h2', t.controle.titulo, 'adm-ap-titulo'),
            criar('p', t.controle.linha, 'adm-ap-linha')
        );
        if (!c) {
            palco.append(criar('p', t.controle.filaNaoLida, 'adm-ap-rodape'));
            return;
        }
        const grade = criar('div', undefined, 'adm-ap-grade');
        grade.append(
            caixaNumero(t.controle.propostas, numero(c.propostas)),
            caixaNumero(t.controle.aguardando, numero(c.aguardando_aprovacao)),
            caixaNumero(t.controle.aprovadas, numero(c.aprovadas)),
            caixaNumero(t.controle.executadas, numero(c.executadas))
        );
        palco.append(grade, criar('p', t.controle.envio, 'adm-ap-rodape'));
    }

    function desenharResultado(t) {
        const r = dados.resultado;
        const capacidades = dados.capacidades || [];
        palco.append(
            criar('p', t.resultado.eyebrow, 'adm-ap-eyebrow'),
            criar('h2', t.resultado.titulo, 'adm-ap-titulo'),
            criar('p', descreverEtapa(r.etapa_alcancada, idioma), 'adm-ap-linha')
        );
        const grade = criar('div', undefined, 'adm-ap-grade');
        grade.append(
            caixaNumero(t.resultado.confirmados, numero(r.confirmados)),
            caixaNumero(t.resultado.semConfirmacao, numero(r.sem_confirmacao))
        );
        for (const capacidade of capacidades.slice(0, 6)) {
            const caixa = criar('article', undefined, 'adm-ap-num');
            caixa.append(criar('span', capacidade.canal));
            caixa.append(criar('strong', t.resultado.estados[capacidade.estado] || capacidade.estado));
            const partes = [];
            if (capacidade.leitura) partes.push(t.resultado.leitura);
            if (capacidade.escrita) partes.push(t.resultado.escrita);
            caixa.append(criar('small', partes.join(' · ') || '—'));
            grade.append(caixa);
        }
        palco.append(grade);
    }

    function desenhar() {
        const t = textos(idioma);
        selo.textContent = t.selo;
        somenteLeitura.textContent = t.somenteLeitura;
        fechar.textContent = t.fechar;

        passosBox.replaceChildren();
        t.passos.forEach((rotulo, indice) => {
            const botao = criar('button', rotulo, 'adm-ap-passo');
            botao.type = 'button';
            botao.setAttribute('aria-current', String(indice === passo));
            botao.addEventListener('click', () => { passo = indice; desenhar(); });
            passosBox.append(botao);
        });

        palco.replaceChildren();
        if (carregando) {
            palco.append(criar('p', t.carregando, 'adm-ap-linha'));
            return;
        }
        if (!dados) {
            palco.append(
                criar('h2', t.indisponivel, 'adm-ap-titulo'),
                criar('p', t.indisponivelNota, 'adm-ap-linha')
            );
            return;
        }

        if (passo === 0) desenharNegocio(t);
        else if (passo === 1) desenharOportunidade(t);
        else if (passo === 2) desenharControle(t);
        else desenharResultado(t);

        const rodape = criar('div', undefined, 'adm-ap-rodape');
        rodape.append(criar('strong', t.limites + ': '));
        rodape.append(document.createTextNode((dados.limites || []).join(' ')));
        rodape.append(criar('p', t.traducao));
        palco.append(rodape);
        palco.classList.remove('adm-entrando');
        void palco.offsetWidth;
        palco.classList.add('adm-entrando');
    }

    async function carregar() {
        carregando = true;
        desenhar();
        try {
            const resposta = await fetch(API + '/api/admin/apresentacao', {
                cache: 'no-store',
                headers: { 'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json' },
            });
            const corpo = await resposta.json().catch(() => ({}));
            dados = (resposta.ok && corpo.success) ? corpo.apresentacao : null;
        } catch (erro) {
            dados = null;
        } finally {
            carregando = false;
            desenhar();
        }
    }

    function abrir() {
        if (!window.adminKeyAtual) return;
        painel.hidden = false;
        passo = 0;
        fechar.focus();
        carregar();
    }

    function fecharPainel() {
        painel.hidden = true;
    }

    fechar.addEventListener('click', fecharPainel);
    document.addEventListener('keydown', evento => {
        if (painel.hidden) return;
        if (evento.key === 'Escape') { fecharPainel(); return; }
        if (evento.key === 'ArrowRight') { passo = Math.min(3, passo + 1); desenhar(); }
        if (evento.key === 'ArrowLeft') { passo = Math.max(0, passo - 1); desenhar(); }
    });
    window.addEventListener('adm-abrir-apresentacao', abrir);
})();
