"""Execução real dos especialistas do Conselho -- reaproveita o cliente
OpenAI (Responses API) já em uso em produção neste projeto (fase57_
prospeccao_universal.py, territorio_api.py, whatsapp_omnichannel.py,
main.py) -- nenhuma dependência nova, nenhum cliente Anthropic adicionado
nesta etapa.

Cada chamada é isolada de verdade: nunca passa `previous_response_id`
(sem histórico entre agentes nem entre ciclos), nunca recebe `tools`
(o modelo não tem nenhuma ferramenta -- não pode ler banco, não pode
mexer em arquivo, não pode enviar nada), `store=False` (não fica retido
do lado da OpenAI além do necessário para responder), com timeout e
`max_output_tokens` fixos, e saída sempre em JSON estruturado (`text.
format.json_schema`, mesmo mecanismo já usado em main.py) -- nunca texto
livre, nunca raciocínio exposto (só lemos `output_text`; nenhum parâmetro
de resumo de raciocínio é solicitado).

MODO OBSERVADOR (`CONSELHO_MODO_OBSERVADOR`): este módulo estruturalmente
NUNCA chama `acoes_comerciais.propor` nem qualquer outra função de ação
externa -- não há, em nenhum caminho de código aqui, uma chamada dessas.
O parecer e a consolidação só são registrados via `mi_conselho.
registrar_registro` (RECOMENDAÇÃO, nunca execução). `modo_observador_
ativo()` existe para uma etapa futura que viesse a executar ações
condicionadas a ele -- nesta etapa é só informativo.
"""
import json
import os
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from openai import OpenAI

from mi_conselho import AGENTES, registrar_registro
from mi_conselho_gatilho import processar_sinais_pendentes
from mi_conselho_orquestrador import formatar_contexto_factual, montar_prompt, ordenar_execucao

MODELO_PADRAO = os.getenv('OPENAI_MODEL_CONSELHO', 'gpt-5-mini')
TIMEOUT_SEGUNDOS = 30
# gpt-5-mini é um modelo de raciocínio: os tokens de raciocínio (mesmo com
# reasoning.effort='low') saem do MESMO orçamento de max_output_tokens,
# antes do texto/JSON visível. Com 900, o raciocínio consumia o teto
# inteiro e a chamada terminava incompleta, sem nenhum texto de saída --
# a causa real do JSONDecodeError observado em homologação (json.loads('')
# nunca é válido). 2000 dá margem para raciocínio + os ~10 campos do
# parecer sem afrouxar reasoning/timeout/store/modelo.
MAX_OUTPUT_TOKENS = 2000
MAX_ESPECIALISTAS_POR_DEMANDA = 4  # trava de custo -- Conclave completo (8) nunca roda automaticamente aqui

_NAMESPACE_EXECUCAO = uuid5(NAMESPACE_URL, 'maranhao-cordial:mi_conselho_executor')
_SEM_DIVERGENCIA = {'', 'nenhuma', 'não aplicável', 'nao aplicavel', 'n/a',
                     'não há divergência', 'nao ha divergencia', 'não há divergências'}

_SCHEMA_PARECER = {
    'type': 'object',
    'properties': {
        'dados_utilizados': {'type': 'string'},
        'conclusao': {'type': 'string'},
        'confianca': {'type': 'string', 'enum': ['alta', 'media', 'baixa']},
        'riscos': {'type': 'string'},
        'divergencias': {'type': 'string'},
        'acao_sugerida': {'type': 'string'},
        'necessidade_diretor': {'type': 'boolean'},
        'motivo_diretor': {'type': 'string'},
        'veto': {'type': 'boolean'},
        'veto_motivo': {'type': 'string'},
    },
    'required': ['dados_utilizados', 'conclusao', 'confianca', 'riscos', 'divergencias',
                 'acao_sugerida', 'necessidade_diretor', 'motivo_diretor', 'veto', 'veto_motivo'],
    'additionalProperties': False,
}
_CAMPOS_OBRIGATORIOS_PARECER = tuple(_SCHEMA_PARECER['required'])


class RespostaLLMInvalida(RuntimeError):
    """Resposta da OpenAI incompleta, vazia, malformada ou fora do schema
    esperado -- nunca vira parecer registrado. Sem fallback inventado:
    quem chama (`processar_e_registrar`) trata isso como falha do agente,
    igual a qualquer outra exceção, nunca como 'sem objeção'."""


def _extrair_parecer_validado(resposta):
    """Fail-safe completo antes de qualquer uso do conteúdo: status da
    Responses API, presença de texto, JSON bem formado e todos os campos
    do schema presentes -- nessa ordem, cada um com uma causa específica."""
    status = getattr(resposta, 'status', 'completed')
    if status != 'completed':
        detalhe = getattr(getattr(resposta, 'incomplete_details', None), 'reason', None) or status
        raise RespostaLLMInvalida(f'resposta_llm_incompleta:{detalhe}')

    texto = getattr(resposta, 'output_text', None)
    if not texto or not texto.strip():
        raise RespostaLLMInvalida('resposta_llm_sem_conteudo')

    try:
        parecer = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise RespostaLLMInvalida('resposta_llm_json_invalido') from erro

    if not isinstance(parecer, dict):
        raise RespostaLLMInvalida('resposta_llm_formato_invalido')
    faltando = [campo for campo in _CAMPOS_OBRIGATORIOS_PARECER if campo not in parecer]
    if faltando:
        raise RespostaLLMInvalida('resposta_llm_campos_ausentes:' + ','.join(faltando))

    return parecer


def modo_observador_ativo():
    """Fail-safe: só sai do modo observador com o valor exato 'false' --
    ausente, vazio ou mal configurado mantém o modo observador ligado."""
    return os.getenv('CONSELHO_MODO_OBSERVADOR', 'true').strip().lower() != 'false'


def executar_especialista(agente, demanda, snapshot=None, posicao_conflitante=None, ciclo=1, cliente=None):
    """Uma chamada isolada ao LLM já em uso no projeto -- sem histórico
    compartilhado, sem tools, sem banco, sem filesystem. `cliente` é
    injetável só para teste (mesmo padrão de `gerar=chamar_ia` em
    territorio_api.py); em produção usa o cliente OpenAI real."""
    if agente not in AGENTES:
        raise ValueError(f'agente_desconhecido:{agente}')

    contexto_texto = formatar_contexto_factual(snapshot)
    prompt = montar_prompt(agente, demanda, contexto_texto, posicao_conflitante, ciclo)

    cliente = cliente or OpenAI(timeout=TIMEOUT_SEGUNDOS, max_retries=0)
    resposta = cliente.responses.create(
        model=MODELO_PADRAO,
        input=prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        store=False,
        reasoning={'effort': 'low'},
        text={'format': {'type': 'json_schema', 'name': 'parecer_conselho', 'strict': True,
                          'schema': _SCHEMA_PARECER}},
    )
    parecer = _extrair_parecer_validado(resposta)

    # Só Dicio pode vetar -- reforçado aqui mesmo que o modelo tente, para
    # nunca depender só da instrução de persona (mesma disciplina do resto
    # do projeto: governança crítica vive em código, não só em prompt).
    veto = bool(parecer.get('veto')) and agente == 'dicio'
    confianca = parecer.get('confianca')
    if confianca not in ('alta', 'media', 'baixa'):
        confianca = 'baixa'

    return {
        'agente': agente, 'ciclo': ciclo, 'demanda': demanda,
        'gerado_em': datetime.now(timezone.utc).isoformat(),
        'dados_utilizados': parecer.get('dados_utilizados', ''),
        'conclusao': parecer.get('conclusao', ''),
        'confianca': confianca,
        'riscos': parecer.get('riscos', ''),
        'divergencias': parecer.get('divergencias', ''),
        'acao_sugerida': parecer.get('acao_sugerida', ''),
        'necessidade_diretor': bool(parecer.get('necessidade_diretor')) or veto,
        'motivo_diretor': parecer.get('motivo_diretor', ''),
        'veto': veto,
        'veto_motivo': parecer.get('veto_motivo') if veto else None,
        'modelo': MODELO_PADRAO,
    }


def _consolidar(avaliado, pareceres, erros, excedeu_limite=False):
    """Monta o corpo para `mi_conselho.registrar_registro` a partir dos
    pareceres coletados -- reaproveita a estrutura já existente (tipo/
    participantes/posicoes/conflitos/vetos/recomendacoes/precisa_diretor),
    nenhum campo novo no schema."""
    participantes = [p['agente'] for p in pareceres]
    posicoes = {p['agente']: p['conclusao'] for p in pareceres}
    vetos = {p['agente']: p['veto_motivo'] for p in pareceres if p.get('veto')}
    conflitos = {p['agente']: p['divergencias'] for p in pareceres
                 if (p.get('divergencias') or '').strip().lower() not in _SEM_DIVERGENCIA}
    recomendacoes = [{'responsavel': p['agente'], 'descricao': p['acao_sugerida'], 'confianca': p['confianca']}
                      for p in pareceres if (p.get('acao_sugerida') or '').strip()]

    pendencias = {}
    if erros:
        pendencias['agentes_com_falha'] = [e['agente'] for e in erros]
    if excedeu_limite:
        pendencias['especialistas_acima_do_limite'] = True

    precisa_diretor = (bool(vetos) or bool(erros) or excedeu_limite
                       or any(p.get('necessidade_diretor') for p in pareceres))
    conclusao = ('; '.join(f"{AGENTES[p['agente']]['nome']}: {p['conclusao']}" for p in pareceres)
                 or 'Nenhum parecer obtido -- todos os especialistas convocados falharam.')

    return {
        'chave': str(uuid5(_NAMESPACE_EXECUCAO, avaliado['sinal_id'])),
        'tipo': 'reuniao' if len(pareceres) > 1 else 'relatorio',
        'demanda': avaliado['demanda'],
        'participantes': participantes,
        'contexto': avaliado['motivo'],
        'dados_apresentados': {'sinal_id': avaliado['sinal_id'], 'tipo_evento': avaliado['tipo_evento']},
        'posicoes': posicoes or None,
        'conflitos': conflitos or None,
        'conclusao': conclusao,
        'recomendacoes': recomendacoes,
        'vetos': vetos or None,
        'pendencias': pendencias or None,
        'precisa_diretor': precisa_diretor,
    }


def _registrar_conclave_completo_pendente(factory, avaliado):
    """Demanda multidisciplinar o bastante para Conclave completo: não
    executa os 8 automaticamente (regra explícita desta etapa) -- só
    registra que existe e que precisa de decisão humana sobre convocar."""
    corpo = {
        'chave': str(uuid5(_NAMESPACE_EXECUCAO, avaliado['sinal_id'])),
        'tipo': 'relatorio',
        'demanda': avaliado['demanda'],
        'participantes': [],
        'contexto': avaliado['motivo'],
        'dados_apresentados': {'sinal_id': avaliado['sinal_id'], 'tipo_evento': avaliado['tipo_evento']},
        'posicoes': None, 'conflitos': None,
        'conclusao': 'Demanda multidisciplinar (Conclave completo) -- não executado automaticamente neste modo.',
        'recomendacoes': [], 'vetos': None,
        'pendencias': {'motivo': 'aguardando decisão do Diretor sobre convocar Conclave completo'},
        'precisa_diretor': True,
    }
    return registrar_registro(factory, corpo)


def processar_e_registrar(factory, limite=50, max_especialistas=MAX_ESPECIALISTAS_POR_DEMANDA, cliente=None):
    """Ponto único desta etapa: lê sinais pendentes (mi_conselho_gatilho,
    não alterado), para cada demanda relevante executa só os especialistas
    já selecionados pelo classificador existente (nunca mais que
    `max_especialistas`, nunca Conclave completo automático), consolida e
    registra em mi_conselho -- nunca executa nenhuma ação externa."""
    avaliados = processar_sinais_pendentes(factory, limite=limite)
    resultados = []
    for avaliado in avaliados:
        if not avaliado['relevante']:
            resultados.append(avaliado)
            continue

        classificacao = avaliado['classificacao']
        if classificacao['conclave_completo']:
            registro = _registrar_conclave_completo_pendente(factory, avaliado)
            resultados.append({**avaliado, 'pareceres': [], 'erros': [], 'registro': registro,
                                'motivo_execucao': 'conclave_completo_aguardando_diretor'})
            continue

        selecionados = classificacao['selecionados']
        excedeu_limite = len(selecionados) > max_especialistas
        agentes_a_executar = ordenar_execucao(selecionados[:max_especialistas])

        pareceres, erros = [], []
        for agente in agentes_a_executar:
            try:
                pareceres.append(executar_especialista(agente, avaliado['demanda'], cliente=cliente))
            except Exception as erro:
                # Falha de um agente nunca libera ação nem é tratada como
                # "sem objeção" -- fica registrada como pendência explícita
                # e força precisa_diretor=True em _consolidar.
                erros.append({'agente': agente, 'erro': type(erro).__name__})

        consolidado = _consolidar(avaliado, pareceres, erros, excedeu_limite)
        registro = registrar_registro(factory, consolidado)
        resultados.append({**avaliado, 'pareceres': pareceres, 'erros': erros, 'registro': registro})
    return resultados
