/* ============================================================
   INÍCIO — a primeira tela do ADM.

   Responde a três perguntas, nesta ordem:
     1. O que está acontecendo?
     2. O que precisa de mim?
     3. Qual foi o resultado?

   Só leitura. Quatro GETs em endpoints que já existiam
   (/api/admin/mi/diretor, /api/admin/acoes-comerciais,
   /api/admin/crm/leads, /api/admin/pedidos). Nenhuma escrita,
   nenhum endpoint novo, nenhuma execução disparada.

   Regras de honestidade aplicadas no cálculo, não no texto:
   - receita confirmada conta SOMENTE pedidos com status 'pago';
   - oportunidades e propostas nunca entram em receita;
   - fonte indisponível vira "sem dados" com o motivo, jamais
     zero;
   - uma sugestão nunca é apresentada como ação concluída.
   ============================================================ */

(() => {
    'use strict';

    const ESTAGIOS_FORA = new Set(['cliente', 'perdido']);

    /* Mesmos rótulos já usados no Modo Diretor: a pessoa nunca lê o nome
       técnico da ação. */
    const ROTULOS_ACAO = {
        pesquisar: 'Procurou novos contatos',
        classificar: 'Classificou prospectos',
        analisar: 'Analisou o funil',
        planejar: 'Planejou as próximas ações',
        sugerir_conteudo: 'Sugeriu conteúdo',
        enviar_followup: 'Preparou um follow-up',
        avaliar_reengajamento: 'Avaliou reengajamento',
        revisar_bloqueio: 'Revisou um bloqueio',
        decidir_proposta: 'Preparou uma proposta para decisão',
        priorizar_atendimento: 'Priorizou um atendimento',
        informar_diretor: 'Registrou uma mudança de público',
    };

    /* --------------------------------------------------------
       CÁLCULO (puro — testável sem DOM)
       -------------------------------------------------------- */

    function contarLeadsAtivos(crm) {
        if (!crm || !crm.ok || !Array.isArray(crm.corpo.leads)) return null;
        return crm.corpo.leads.filter(lead =>
            !ESTAGIOS_FORA.has(lead.estagio) && !lead.arquivado && !lead.cadastro_teste
        ).length;
    }

    function separarAcoes(acoes) {
        if (!acoes || !acoes.ok || !Array.isArray(acoes.corpo.acoes)) return null;
        const lista = acoes.corpo.acoes;
        const por = status => lista.filter(a => a.status === status).length;
        return {
            total: lista.length,
            aguardando: por('aguardando_aprovacao'),
            aprovadas: por('aprovada') + por('executando'),
            enviadas: por('enviada'),
            semConfirmacao: por('bloqueada') + por('incerta'),
        };
    }

    /* Receita confirmada = pedidos pagos. Nunca proposta, nunca
       oportunidade, nunca projeção. */
    function receitaConfirmada(pedidos) {
        if (!pedidos || !pedidos.ok || !Array.isArray(pedidos.corpo.pedidos)) return null;
        const pagos = pedidos.corpo.pedidos.filter(p => p.status === 'pago');
        return {
            quantidade: pagos.length,
            centavos: pagos.reduce((soma, p) => soma + (Number(p.valor_centavos) || 0), 0),
            registrados: pedidos.corpo.pedidos.length,
        };
    }

    function leituraDiretor(diretor) {
        if (!diretor || !diretor.ok || !diretor.corpo.leitura) return null;
        return diretor.corpo.leitura;
    }

    function contarPrecisaDeVoce(estado) {
        const acoes = separarAcoes(estado.acoes);
        const leitura = leituraDiretor(estado.diretor);
        if (acoes === null && leitura === null) return null;
        const aguardando = acoes ? acoes.aguardando : 0;
        const conselho = leitura && leitura.conselho
            ? (leitura.conselho.aguardando_diretor || []).length + (leitura.conselho.vetos || []).length
            : 0;
        return aguardando + conselho;
    }

    function montarIndicadores(estado) {
        const acoes = separarAcoes(estado.acoes);
        const leitura = leituraDiretor(estado.diretor);
        const receita = receitaConfirmada(estado.pedidos);
        const leads = contarLeadsAtivos(estado.crm);
        const precisa = contarPrecisaDeVoce(estado);

        const oportunidades = leitura && leitura.comercial
            ? (leitura.comercial.oportunidades || []).length
            : null;

        return [
            {
                chave: 'precisa',
                rotulo: 'Precisa de você',
                valor: precisa,
                formato: 'numero',
                contexto: precisa === null
                    ? 'Fila de decisões indisponível agora.'
                    : 'Decisões abertas neste momento.',
            },
            {
                chave: 'contatos',
                rotulo: 'Contatos ativos',
                valor: leads,
                formato: 'numero',
                contexto: leads === null
                    ? 'Cadastro de relacionamento indisponível agora.'
                    : 'Em relacionamento hoje, sem contar clientes fechados nem perdidos.',
            },
            {
                chave: 'oportunidades',
                rotulo: 'Oportunidades',
                valor: oportunidades,
                formato: 'numero',
                contexto: oportunidades === null
                    ? 'Acompanhamento comercial indisponível agora.'
                    : 'Em aberto no acompanhamento. Não são receita nem proposta aceita.',
            },
            {
                chave: 'receita',
                rotulo: 'Receita confirmada',
                valor: receita === null ? null : receita.centavos,
                formato: 'dinheiro',
                contexto: receita === null
                    ? 'Registro de pedidos indisponível agora.'
                    : `${receita.quantidade} de ${receita.registrados} pedidos com pagamento confirmado. Propostas e oportunidades não entram aqui.`,
            },
        ].map(i => Object.assign(i, { acoesResumo: acoes }));
    }

    /* Prioridades: no máximo três, ordenadas por urgência e
       impacto. Pendência técnica só entra quando impede uma tarefa
       — caso contrário fica na área de Operação. */
    function montarPrioridades(estado) {
        const acoes = separarAcoes(estado.acoes);
        const leitura = leituraDiretor(estado.diretor);
        const candidatos = [];

        if (acoes && acoes.aguardando > 0) {
            candidatos.push({
                peso: 0,
                urgencia: 'alta',
                titulo: acoes.aguardando === 1
                    ? '1 ação aguardando sua aprovação'
                    : `${acoes.aguardando} ações aguardando sua aprovação`,
                descricao: 'Revise o que será feito e para quem antes de decidir. Aprovar registra a decisão; nada é enviado por este botão.',
                botao: 'Revisar',
                painel: 'governanca',
            });
        }

        if (leitura && leitura.conselho) {
            const vetos = (leitura.conselho.vetos || []).length;
            const aguardando = (leitura.conselho.aguardando_diretor || []).length;
            if (vetos > 0) {
                candidatos.push({
                    peso: 1,
                    urgencia: 'alta',
                    titulo: vetos === 1 ? 'O Conselho registrou 1 veto' : `O Conselho registrou ${vetos} vetos`,
                    descricao: 'Um especialista se opôs a uma recomendação. A decisão final é sua.',
                    botao: 'Ver Conselho',
                    painel: 'conselho-de-agentes',
                });
            }
            if (aguardando > 0) {
                candidatos.push({
                    peso: 2,
                    urgencia: 'alta',
                    titulo: aguardando === 1
                        ? '1 análise do Conselho aguarda você'
                        : `${aguardando} análises do Conselho aguardam você`,
                    descricao: 'Conclusões que só avançam com uma decisão humana.',
                    botao: 'Ver Conselho',
                    painel: 'conselho-de-agentes',
                });
            }
        }

        if (leitura && leitura.comercial) {
            const importantes = (leitura.comercial.oportunidades || [])
                .filter(o => o.prioridade === 'urgente' || o.prioridade === 'alta');
            if (importantes.length) {
                candidatos.push({
                    peso: 3,
                    urgencia: 'media',
                    titulo: importantes.length === 1
                        ? '1 oportunidade importante parada'
                        : `${importantes.length} oportunidades importantes paradas`,
                    descricao: 'Estão marcadas como prioridade alta e não tiveram movimento.',
                    botao: 'Abrir contatos',
                    painel: 'crm',
                });
            }
            const followups = (leitura.comercial.followups || []).length;
            if (followups > 0) {
                candidatos.push({
                    peso: 4,
                    urgencia: 'media',
                    titulo: followups === 1 ? '1 retorno combinado venceu' : `${followups} retornos combinados venceram`,
                    descricao: 'Contatos que ficaram de ser retomados e passaram do prazo.',
                    botao: 'Abrir contatos',
                    painel: 'crm',
                });
            }
        }

        /* Pendência técnica com efeito prático: há ação aprovada que
           não conseguiu concluir. Aqui ela impede uma tarefa, então
           merece estar entre as prioridades. */
        if (acoes && acoes.semConfirmacao > 0) {
            candidatos.push({
                peso: 5,
                urgencia: 'alta',
                titulo: acoes.semConfirmacao === 1
                    ? '1 ação aprovada não se confirmou'
                    : `${acoes.semConfirmacao} ações aprovadas não se confirmaram`,
                descricao: 'A execução não teve confirmação. Revise antes de tentar de novo — não há reenvio automático.',
                botao: 'Revisar',
                painel: 'governanca',
            });
        }

        candidatos.sort((a, b) => a.peso - b.peso);
        return candidatos.slice(0, 3);
    }

    function montarSituacao(estado) {
        const leitura = leituraDiretor(estado.diretor);
        const precisa = contarPrecisaDeVoce(estado);
        const falhas = ['diretor', 'acoes', 'crm', 'pedidos'].filter(k => estado[k] && !estado[k].ok);

        if (falhas.length === 4) {
            return {
                texto: 'Não foi possível ler o estado do negócio agora.',
                nota: 'Nenhuma das fontes respondeu. Tente atualizar em instantes; nada foi alterado.',
                grave: true,
            };
        }

        let texto;
        if (precisa === null) {
            texto = 'A leitura do dia está parcial.';
        } else if (precisa === 0) {
            texto = leitura && leitura.ia_trabalhando
                ? 'Nada espera por você agora. A rotina seguiu sem precisar de decisão.'
                : 'Nada espera por você agora.';
        } else if (precisa === 1) {
            texto = 'Há 1 decisão esperando por você.';
        } else {
            texto = `Há ${precisa} decisões esperando por você.`;
        }

        const nota = falhas.length
            ? `Parte das informações não carregou agora (${falhas.length} de 4 fontes). O que aparece abaixo é o que foi lido.`
            : 'Leitura direta dos registros da empresa. Nenhuma ação foi executada ao abrir esta tela.';

        return { texto, nota, grave: false };
    }

    function montarAcaoPrincipal(estado) {
        const acoes = separarAcoes(estado.acoes);
        if (acoes && acoes.aguardando > 0) {
            return {
                rotulo: acoes.aguardando === 1 ? 'Revisar 1 aprovação' : `Revisar ${acoes.aguardando} aprovações`,
                painel: 'governanca',
            };
        }
        const prioridades = montarPrioridades(estado);
        if (prioridades.length) {
            return { rotulo: prioridades[0].botao, painel: prioridades[0].painel };
        }
        return { rotulo: 'Ver a leitura do dia', painel: 'ia-empresarial' };
    }

    /* Cadeia: informação → decisão → ação → resultado. Cada etapa
       mostra o estado REAL. "Sugerido" nunca aparece como
       "executado"; sem resultado medido, a etapa fica explicitamente
       vazia em vez de exibir um número inventado. */
    function montarCadeia(estado) {
        const acoes = separarAcoes(estado.acoes);
        const leitura = leituraDiretor(estado.diretor);
        const oportunidades = leitura && leitura.comercial ? (leitura.comercial.oportunidades || []) : [];
        const proxima = leitura ? leitura.proxima_acao_ia : null;
        const resultados = leitura && leitura.conselho ? (leitura.conselho.resultados_recentes || []) : [];

        const etapas = [];

        etapas.push({
            titulo: 'Oportunidade identificada',
            estado: oportunidades.length ? 'sugerido' : null,
            selo: oportunidades.length ? 'Observado' : null,
            texto: oportunidades.length
                ? `${oportunidades.length} ${oportunidades.length === 1 ? 'oportunidade aberta foi identificada' : 'oportunidades abertas foram identificadas'} a partir dos registros existentes.`
                : 'Nenhuma oportunidade aberta identificada até agora.',
        });

        etapas.push({
            titulo: 'Ação sugerida',
            estado: (acoes && acoes.total > 0) || proxima ? 'sugerido' : null,
            selo: (acoes && acoes.total > 0) || proxima ? 'Sugerido' : null,
            texto: acoes && acoes.total > 0
                ? `${acoes.total} ${acoes.total === 1 ? 'ação foi proposta' : 'ações foram propostas'} para decisão humana.`
                : (proxima ? 'Há uma próxima ação planejada, ainda não proposta para aprovação.' : 'Nenhuma ação proposta até agora.'),
        });

        let estadoExecucao = null;
        let seloExecucao = null;
        let textoExecucao = 'Nenhuma ação chegou à execução.';
        if (acoes && acoes.enviadas > 0) {
            estadoExecucao = 'executado';
            seloExecucao = 'Executado';
            textoExecucao = `${acoes.enviadas} ${acoes.enviadas === 1 ? 'ação aprovada foi executada' : 'ações aprovadas foram executadas'}.`;
        } else if (acoes && acoes.aprovadas > 0) {
            estadoExecucao = 'aguardando';
            seloExecucao = 'Aprovado — execução em curso';
            textoExecucao = `${acoes.aprovadas} ${acoes.aprovadas === 1 ? 'ação aprovada aguarda' : 'ações aprovadas aguardam'} execução.`;
        } else if (acoes && acoes.aguardando > 0) {
            estadoExecucao = 'aguardando';
            seloExecucao = 'Aguardando aprovação';
            textoExecucao = `${acoes.aguardando} ${acoes.aguardando === 1 ? 'ação aguarda' : 'ações aguardam'} sua aprovação antes de qualquer execução.`;
        }
        etapas.push({ titulo: 'Aprovado e executado', estado: estadoExecucao, selo: seloExecucao, texto: textoExecucao });

        let estadoResultado = null;
        let seloResultado = null;
        let textoResultado = 'Ainda não há resultado confirmado para mostrar.';
        if (acoes && acoes.semConfirmacao > 0) {
            estadoResultado = 'falhou';
            seloResultado = 'Sem confirmação';
            textoResultado = `${acoes.semConfirmacao} ${acoes.semConfirmacao === 1 ? 'execução não teve confirmação' : 'execuções não tiveram confirmação'}. Nada foi reenviado automaticamente.`;
        } else if (resultados.length) {
            estadoResultado = 'confirmado';
            seloResultado = 'Resultado confirmado';
            textoResultado = `${resultados.length} ${resultados.length === 1 ? 'resultado registrado' : 'resultados registrados'} após a execução.`;
        }
        etapas.push({ titulo: 'Resposta ou resultado', estado: estadoResultado, selo: seloResultado, texto: textoResultado });

        return etapas;
    }

    function montarRecente(estado) {
        const leitura = leituraDiretor(estado.diretor);
        if (!leitura) return null;
        const concluido = (leitura.hoje && leitura.hoje.concluido) || [];
        return {
            total: concluido.length,
            itens: concluido.slice(0, 3).map(item => ({
                texto: ROTULOS_ACAO[item.proxima_acao] || item.proxima_acao || item.tipo_decisao || 'Atividade concluída',
                motivo: item.motivo || item.inferencia || null,
            })),
            trabalhando: !!leitura.ia_trabalhando,
        };
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            contarLeadsAtivos, separarAcoes, receitaConfirmada, contarPrecisaDeVoce,
            montarIndicadores, montarPrioridades, montarSituacao, montarAcaoPrincipal,
            montarCadeia, montarRecente,
        };
    }

    if (typeof document === 'undefined') return;
    const raiz = document.getElementById('adm-inicio-raiz');
    if (!raiz) return;

    /* --------------------------------------------------------
       DESENHO
       -------------------------------------------------------- */

    const API = 'https://maranhao-cordial-api.onrender.com';
    const criar = (tag, texto, classe) => {
        const no = document.createElement(tag);
        if (texto !== undefined && texto !== null) no.textContent = texto;
        if (classe) no.className = classe;
        return no;
    };
    const numero = v => Number(v).toLocaleString('pt-BR');
    const dinheiro = centavos => (Number(centavos) / 100).toLocaleString('pt-BR', {
        style: 'currency', currency: 'BRL', maximumFractionDigits: 0,
    });

    let carregando = false;
    let jaCarregou = false;
    let ultimaAcao = null;

    function aplicarAcaoNoCabecalho() {
        const botao = document.querySelector('.adm-acao-principal');
        const noInicio = document.querySelector('.tab-panel[data-panel="adm-inicio"].active');
        if (!botao || !noInicio || !ultimaAcao) return;
        botao.hidden = false;
        botao.textContent = ultimaAcao.rotulo;
        botao.onclick = () => window.admIrPara && window.admIrPara(ultimaAcao.painel);
    }

    async function buscar(caminho) {
        try {
            const resposta = await fetch(API + caminho, {
                cache: 'no-store',
                headers: { 'X-Admin-Key': window.adminKeyAtual, 'Content-Type': 'application/json' },
            });
            const corpo = await resposta.json().catch(() => ({}));
            return { ok: resposta.ok && corpo.success !== false, corpo };
        } catch (erro) {
            return { ok: false, corpo: {} };
        }
    }

    function desenharEsqueleto() {
        raiz.replaceChildren();
        const faixa = criar('div', undefined, 'adm-indicadores');
        for (let i = 0; i < 4; i += 1) faixa.append(criar('div', undefined, 'adm-esqueleto'));
        raiz.append(criar('p', 'Lendo o estado do negócio…', 'adm-situacao-nota'), faixa);
    }

    function desenharIndicadores(indicadores) {
        const faixa = criar('div', undefined, 'adm-indicadores');
        for (const indicador of indicadores) {
            const caixa = criar('article', undefined, 'adm-indicador');
            caixa.append(criar('span', indicador.rotulo, 'adm-indicador-rotulo'));
            const valor = criar('strong', undefined, 'adm-indicador-valor');
            if (indicador.valor === null || indicador.valor === undefined) {
                valor.textContent = 'sem dados';
                valor.classList.add('adm-sem-dado');
            } else {
                valor.textContent = indicador.formato === 'dinheiro'
                    ? dinheiro(indicador.valor)
                    : numero(indicador.valor);
            }
            caixa.append(valor, criar('small', indicador.contexto, 'adm-indicador-contexto'));
            faixa.append(caixa);
        }
        return faixa;
    }

    function desenharPrioridades(prioridades) {
        const bloco = criar('section', undefined, 'adm-bloco');
        const titulo = criar('div', undefined, 'adm-bloco-titulo');
        titulo.append(criar('h2', 'O que precisa de você'));
        const verTudo = criar('button', 'Ver todas as decisões →');
        verTudo.type = 'button';
        verTudo.addEventListener('click', () => window.admIrPara && window.admIrPara('governanca'));
        titulo.append(verTudo);
        bloco.append(titulo);

        if (!prioridades.length) {
            bloco.append(criar('p', 'Nada exige sua decisão agora. O que estiver em andamento continua sendo registrado.', 'adm-vazio'));
            return bloco;
        }

        for (const item of prioridades) {
            const linha = criar('article', undefined, 'adm-prioridade');
            linha.dataset.urgencia = item.urgencia;
            linha.append(criar('span', '', 'adm-prioridade-marca'));
            const corpo = criar('div', undefined, 'adm-prioridade-corpo');
            corpo.append(criar('strong', item.titulo, 'adm-prioridade-titulo'), criar('p', item.descricao, 'adm-prioridade-desc'));
            linha.append(corpo);
            const botao = criar('button', item.botao, 'adm-prio-botao');
            botao.type = 'button';
            botao.addEventListener('click', () => window.admIrPara && window.admIrPara(item.painel));
            linha.append(botao);
            bloco.append(linha);
        }
        return bloco;
    }

    function desenharCadeia(etapas) {
        const bloco = criar('section', undefined, 'adm-bloco');
        const titulo = criar('div', undefined, 'adm-bloco-titulo');
        titulo.append(criar('h2', 'Do sinal ao resultado'));
        bloco.append(titulo);

        const grade = criar('div', undefined, 'adm-cadeia');
        for (const etapa of etapas) {
            const caixa = criar('div', undefined, 'adm-cadeia-etapa');
            caixa.append(criar('strong', etapa.titulo, 'adm-prioridade-titulo'));
            if (etapa.selo) {
                const selo = criar('span', etapa.selo, 'adm-selo');
                selo.dataset.estado = etapa.estado;
                caixa.append(selo);
            }
            const texto = criar('p', etapa.texto, 'adm-cadeia-texto');
            if (!etapa.selo) texto.classList.add('adm-cadeia-vazio');
            caixa.append(texto);
            grade.append(caixa);
        }
        bloco.append(grade);
        return bloco;
    }

    function desenharRecente(recente) {
        const bloco = criar('section', undefined, 'adm-bloco adm-recente');
        if (!recente) {
            bloco.append(criar('p', 'O resumo do trabalho recente não carregou agora.', 'adm-situacao-nota'));
            return bloco;
        }
        const resumo = recente.total === 0
            ? (recente.trabalhando ? 'A tecnologia está em atividade; nada foi concluído ainda hoje.' : 'Nenhuma atividade concluída registrada hoje.')
            : `${numero(recente.total)} ${recente.total === 1 ? 'atividade concluída' : 'atividades concluídas'} recentemente.`;
        bloco.append(criar('p', resumo, 'adm-situacao-nota'));
        if (recente.itens.length) {
            const lista = criar('ul');
            for (const item of recente.itens) {
                const li = criar('li');
                li.append(criar('strong', item.texto));
                if (item.motivo) li.append(criar('span', item.motivo));
                lista.append(li);
            }
            bloco.append(lista);
        }
        return bloco;
    }

    function desenhar(estado) {
        const situacao = montarSituacao(estado);
        raiz.replaceChildren();

        if (situacao.grave) {
            /* Sem leitura nenhuma, a ação principal anterior fica obsoleta:
               melhor não oferecer nada do que oferecer algo que talvez já
               não exista. */
            const botaoObsoleto = document.querySelector('.adm-acao-principal');
            if (botaoObsoleto) botaoObsoleto.hidden = true;

            const aviso = criar('div', undefined, 'adm-falha');
            aviso.append(criar('strong', situacao.texto), criar('p', situacao.nota));
            const tentar = criar('button', 'Tentar de novo', 'adm-prio-botao');
            tentar.type = 'button';
            tentar.addEventListener('click', () => carregar(true));
            aviso.append(tentar);
            raiz.append(aviso);
            return;
        }

        raiz.append(
            criar('p', situacao.texto, 'adm-situacao'),
            criar('p', situacao.nota, 'adm-situacao-nota'),
            desenharIndicadores(montarIndicadores(estado)),
            desenharPrioridades(montarPrioridades(estado)),
            desenharCadeia(montarCadeia(estado)),
            desenharRecente(montarRecente(estado))
        );

        /* A ação principal da tela vive no cabeçalho do shell: uma
           por contexto, sempre a mais provável agora. Guardada para ser
           reposta quando a pessoa voltar ao Início sem recarregar — o
           cabeçalho é reconstruído a cada troca de vista. */
        ultimaAcao = montarAcaoPrincipal(estado);
        aplicarAcaoNoCabecalho();
    }

    async function carregar(forcar) {
        if (carregando) return;
        if (!window.adminKeyAtual) return;
        if (jaCarregou && !forcar) return;
        carregando = true;
        desenharEsqueleto();
        try {
            const [diretor, acoes, crm, pedidos] = await Promise.all([
                buscar('/api/admin/mi/diretor'),
                buscar('/api/admin/acoes-comerciais'),
                buscar('/api/admin/crm/leads'),
                buscar('/api/admin/pedidos'),
            ]);
            desenhar({ diretor, acoes, crm, pedidos });
            jaCarregou = true;
        } finally {
            carregando = false;
        }
    }

    window.addEventListener('adm-vista', evento => {
        if (!evento.detail || evento.detail.painel !== 'adm-inicio') return;
        carregar(false);
        // Voltar ao Início sem recarregar não pode deixar o cabeçalho sem
        // ação: repõe a última calculada.
        aplicarAcaoNoCabecalho();
    });
    window.addEventListener('admin-autorizado', () => carregar(true));
    window.admRecarregarInicio = () => carregar(true);
})();
