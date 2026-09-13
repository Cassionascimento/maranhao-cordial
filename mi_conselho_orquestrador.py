"""Orquestração do Conclave nesta interface (Claude Code no app desktop).

Por que este arquivo existe: nesta superfície, a ferramenta de agente não
carrega `.claude/agents/*.md` como tipos de subagente invocáveis por nome
(testado -- `Agent(subagent_type="iris")` é recusado) e `/conclave` não é
reconhecido como slash command. O mecanismo real e disponível aqui é
`Agent(subagent_type="general-purpose", prompt=...)`, que roda em contexto
isolado de verdade. Este módulo prepara só o que esse mecanismo precisa:
qual especialista convocar, o prompt dele (o corpo do `.md` já existente,
sem duplicar) e o contexto factual (somente leitura). Quem efetivamente
chama `Agent(...)` continua sendo a sessão do Claude Code, nunca este
módulo -- não existe aqui nenhum cliente da API Anthropic, nenhum loop,
nenhum agendador.

Este módulo NÃO decide fato nem estratégia, NÃO conecta produção e NUNCA
recebe `factory()`/string de conexão/segredo -- só um snapshot de leitura
já pronto (ex.: saída de `mi_diretor.leitura_diretor`/`mi_conselho.
leitura_conselho`), passado pelo chamador como argumento. Sem snapshot, o
contexto entregue aos agentes diz explicitamente "dado indisponível" --
nunca inventa número, sinal ou histórico.
"""
import json
import os
import re

from mi_conselho import AGENTES

_DIR_AGENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.claude', 'agents')
_FRONTMATTER = re.compile(r'^---\n.*?\n---\n', re.S)

_PADRAO_SEGREDO = re.compile(
    r'(postgres(?:ql)?|mysql|redis|mongodb)://\S+|Bearer\s+\S+|sk-[A-Za-z0-9]{10,}',
    re.I,
)
_CHAVE_SENSIVEL = re.compile(
    r'(database_url|db_url|senha|password|passwd|token|api[_-]?key|secret|factory|'
    r'connection|conn_str|credencial|credential)',
    re.I,
)

MARCADOR_SEM_DADO = (
    "[CONTEXTO FACTUAL INDISPONIVEL -- nenhum snapshot de leitura foi fornecido a "
    "este Conclave. Responda com confianca reduzida, declare explicitamente a "
    "ausencia de dado e NUNCA invente numero, sinal ou historico que nao esteja "
    "aqui.]"
)

_INSTRUCAO_GOVERNANCA_SESSAO = (
    "Esta e uma sessao de analise do Conselho de Agentes (Conclave ou reuniao). Nao "
    "e uma etapa de codigo: nao edite arquivos, nao rode comando de escrita, nao "
    "chame nenhuma ferramenta de envio, publicacao, pagamento, deploy ou migration. "
    "Responda apenas com o parecer estruturado definido no seu proprio arquivo de "
    "persona (campos: agente, data/hora, demanda, dados utilizados, conclusao, "
    "confianca, riscos, divergencias, acao sugerida, necessidade de Diretor, decisao "
    "humana posterior). Nunca exponha raciocinio interno passo a passo -- entregue "
    "conclusoes e evidencias resumidas, nunca chain-of-thought."
)


def contem_credencial(texto):
    """Defesa em profundidade: True se `texto` parece conter uma URL de
    conexão ou segredo (não apenas a palavra em prosa)."""
    return bool(_PADRAO_SEGREDO.search(str(texto)))


def _checar_sem_credenciais(obj, caminho='contexto'):
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if _CHAVE_SENSIVEL.search(str(chave)):
                raise ValueError(f'contexto_contem_chave_sensivel:{caminho}.{chave}')
            _checar_sem_credenciais(valor, f'{caminho}.{chave}')
    elif isinstance(obj, (list, tuple)):
        for indice, valor in enumerate(obj):
            _checar_sem_credenciais(valor, f'{caminho}[{indice}]')
    elif isinstance(obj, str) and contem_credencial(obj):
        raise ValueError(f'contexto_contem_valor_sensivel:{caminho}')


def carregar_persona(agente):
    """Lê `.claude/agents/<agente>.md` e devolve o corpo (sem frontmatter)
    -- fonte única da persona, nunca copiada para outro arquivo."""
    if agente not in AGENTES:
        raise ValueError(f'agente_desconhecido:{agente}')
    caminho = os.path.join(_DIR_AGENTES, f'{agente}.md')
    with open(caminho, encoding='utf-8') as arquivo:
        texto = arquivo.read()
    corpo = _FRONTMATTER.sub('', texto, count=1).strip()
    if not corpo:
        raise ValueError(f'persona_vazia:{agente}')
    return corpo


def formatar_contexto_factual(snapshot):
    """`snapshot` é a saída já pronta de uma leitura somente-leitura
    existente (ex.: `mi_diretor.leitura_diretor(factory)` ou `mi_conselho.
    leitura_conselho(factory)`) -- nunca `factory()`/credencial. Sem
    snapshot, devolve o marcador explícito de dado indisponível."""
    if not snapshot:
        return MARCADOR_SEM_DADO
    _checar_sem_credenciais(snapshot)
    corpo = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    return (
        "[CONTEXTO FACTUAL -- somente leitura, extraido de leitura_diretor/"
        "leitura_conselho ja existentes (mi_diretor.py/mi_conselho.py). Nao contem "
        "credencial nem funcao de escrita. Use isto como a unica fonte de dado real "
        "desta rodada -- qualquer coisa fora daqui e suposicao, e deve ser marcada "
        "como tal.]\n\n" + corpo
    )


_REGRAS_CLASSIFICACAO = (
    (('marketing', 'campanha', 'divulga', 'comunicaç', 'comunicac', 'anúncio', 'anuncio',
      'mídia', 'midia', 'audiência', 'audiencia', 'conteúdo', 'conteudo', 'posicionamento'),
     'pirret', 'demanda menciona marketing/comunicação/campanha/mídia'),
    (('vend', 'pitch', 'funil', 'follow-up', 'followup', 'oportunidade comercial', 'cliente',
      'potencial comercial', 'prospect', 'pedido', 'negociação', 'negociacao', 'proposta'),
     'leonard', 'demanda menciona vendas/oportunidade/cliente/proposta comercial'),
    (('preço', 'preco', 'desconto', 'margem', 'pricing', 'financeiro', 'custo', 'receita', 'payback',
      'precificação', 'precificacao', 'retorno', 'lucro', 'investimento', 'rendimento', 'perda'),
     'standard', 'demanda menciona preço/margem/custo/investimento/rendimento/perda'),
    (('fórmula', 'formula', 'embalagem', 'claim', 'anvisa', 'rótulo', 'rotulo',
      'viabilidade técnica', 'viabilidade tecnica', 'formulação', 'formulacao', 'estabilidade',
      'processo', 'especificação técnica', 'especificacao tecnica', 'sku', 'ingrediente',
      'rotulagem', 'claim técnico', 'claim tecnico', 'desenvolvimento de produto',
      'bancada', 'ph medido', 'brix medido'),
     'marie', 'demanda menciona fórmula/embalagem/viabilidade técnica/bancada/pH/Brix'),
    (('produção', 'producao', 'capacidade', 'estoque', 'entrega', 'logística', 'logistica', 'prazo', 'lote',
      'capacidade de produção', 'capacidade de producao', 'prazo operacional', 'ruptura'),
     'rua', 'demanda menciona produção/capacidade/logística/prazo'),
    (('contrato', 'jurídico', 'juridico', 'lgpd', 'legal', 'compliance', 'concorrência desleal',
      'concorrencia desleal', 'propaganda enganosa', 'risco regulatório', 'risco regulatorio',
      'regulatório', 'regulatorio', 'anvisa', 'rotulagem', 'claim', 'responsabilidade',
      'não conformidade', 'nao conformidade', 'conformidade'),
     'dicio', 'demanda menciona contrato/jurídico/compliance/risco regulatório/conformidade'),
    (('contrata', 'desliga', 'demiss', 'promoção', 'promocao', 'realoca', 'headcount', 'recursos humanos',
      'contratação', 'contratacao', 'desligamento', 'desempenho', 'equipe', 'funcionário', 'funcionario',
      'colaborador', 'cargo', 'remuneração', 'remuneracao', 'treinamento', 'gestão de pessoas', 'gestao de pessoas'),
     'zilda', 'demanda menciona contratação/desligamento/equipe/gestão de pessoas'),
    (('mercado', 'concorrência', 'concorrencia', 'tendência', 'tendencia', 'sinal', 'comportamento do cliente',
      'comportamento', 'dados', 'demanda', 'sinais', 'pesquisa'),
     'iris', 'demanda menciona mercado/dado/sinal/tendência/comportamento'),
)

# 7 (de 8) especialidades distintas já identificadas -- ou pedido explícito
# -- é o que caracteriza "alta multidisciplinaridade" o bastante para
# cobrir o Conselho inteiro; um recorte de 5-6 áreas continua sendo uma
# seleção pontual, não um Conclave completo.
_LIMIAR_CONCLAVE_COMPLETO = 7


def classificar_especialistas(demanda, conclave_completo=False):
    """Decide quais dos 8 agentes são pertinentes à demanda -- nunca
    convoca os 8 por padrão. Regra determinística por palavra-chave;
    quando `conclave_completo=True` (pedido explícito do Diretor/usuário)
    ou quando 7+ especialidades distintas já foram identificadas (alta
    multidisciplinaridade), cobre os 8 com o motivo registrado."""
    if not isinstance(demanda, str) or not demanda.strip():
        raise ValueError('demanda_obrigatoria')
    texto = demanda.lower()

    selecionados = set()
    motivos = {}

    def marcar(agente, motivo):
        selecionados.add(agente)
        motivos.setdefault(agente, []).append(motivo)

    for palavras, agente, motivo in _REGRAS_CLASSIFICACAO:
        if any(p in texto for p in palavras):
            marcar(agente, motivo)

    # Produto/fórmula com risco regulatório puxa Dicio; com impacto de
    # produção puxa Rua -- exatamente o exemplo dado na especificação.
    if 'marie' in selecionados and any(p in texto for p in ('regulat', 'anvisa', 'risco jurídico', 'risco juridico')):
        marcar('dicio', 'produto/fórmula com possível risco regulatório -- Dicio valida ao lado de Marie')
    if 'marie' in selecionados and any(p in texto for p in ('produção', 'producao', 'capacidade', 'escala')):
        marcar('rua', 'produto/fórmula com impacto de produção -- Rua valida capacidade ao lado de Marie')

    # Questão de pessoal com desligamento/contratação puxa Dicio (risco trabalhista).
    if 'zilda' in selecionados and any(p in texto for p in ('desliga', 'demiss', 'contrata')):
        marcar('dicio', 'contratação/desligamento -- Dicio valida risco trabalhista ao lado de Zilda')

    # Iris entra como base factual sempre que mais de um especialista de
    # conteúdo for convocado (ela não escolhe estratégia, mas os outros
    # precisam de dado para não trabalhar no vácuo).
    especialistas_de_conteudo = selecionados - {'iris'}
    if len(especialistas_de_conteudo) > 1 and 'iris' not in selecionados:
        marcar('iris', 'mais de um especialista convocado -- Iris entra com a base factual antes das análises')

    completo = bool(conclave_completo) or len(selecionados) >= _LIMIAR_CONCLAVE_COMPLETO
    if completo:
        motivo_completo = (
            'convocação explícita de Conclave completo' if conclave_completo
            else f'demanda envolve {len(selecionados)} ou mais especialidades relevantes'
        )
        for agente in AGENTES:
            motivos.setdefault(agente, []).append(motivo_completo)
        selecionados = set(AGENTES.keys())

    if not selecionados:
        raise ValueError('nenhum_especialista_identificado')

    excluidos = {
        agente: 'nenhuma palavra-chave da demanda corresponde à especialidade deste agente'
        for agente in AGENTES if agente not in selecionados
    }

    return {
        'selecionados': sorted(selecionados),
        'motivos': {agente: motivos[agente] for agente in sorted(selecionados)},
        'excluidos': excluidos,
        'conclave_completo': completo,
    }


def ordenar_execucao(selecionados):
    """Iris, quando convocada, sempre roda primeiro -- ela fornece a base
    factual que os demais especialistas usam como contexto adicional."""
    especialistas = sorted(agente for agente in selecionados if agente != 'iris')
    return (['iris'] + especialistas) if 'iris' in selecionados else especialistas


def montar_prompt(agente, demanda, contexto_factual_texto, posicao_conflitante=None, ciclo=1):
    """Monta o prompt final para `Agent(subagent_type="general-purpose",
    prompt=...)`: persona (arquivo original, sem cópia) + demanda +
    contexto factual + (na segunda rodada) a posição divergente do outro
    lado, para réplica com evidência -- nunca concessão automática."""
    if not isinstance(demanda, str) or not demanda.strip():
        raise ValueError('demanda_obrigatoria')
    persona = carregar_persona(agente)
    contexto = contexto_factual_texto or MARCADOR_SEM_DADO

    partes = [
        persona,
        '---',
        f'Ciclo do Conclave: {ciclo}',
        f'Demanda a analisar: {demanda.strip()}',
        contexto,
    ]
    if posicao_conflitante:
        outro = posicao_conflitante.get('agente', 'outro agente')
        texto_outro = posicao_conflitante.get('texto', '')
        partes.append(
            f"Posicao divergente de {outro}, com a evidencia dele: {texto_outro}\n\n"
            "Responda com sua propria evidencia -- nao concorde por educacao. Se "
            "mantiver a divergencia, diga explicitamente por que, com base na sua "
            "especialidade."
        )
    partes.append(_INSTRUCAO_GOVERNANCA_SESSAO)

    prompt = '\n\n'.join(partes)
    if contem_credencial(prompt):
        raise ValueError('prompt_contem_credencial')
    return prompt
