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
import re
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from openai import OpenAI

from mi_conselho import AGENTES, registrar_registro
from mi_conselho_estado import montar_pacote_estado
from mi_conselho_fatos import registrar_fato
from mi_conselho_gatilho import processar_sinais_pendentes
from mi_conselho_orquestrador import formatar_contexto_factual, montar_prompt, ordenar_execucao
from mi_artefatos import TIPOS_ARTEFATO

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

# Todo número que o agente cita e que pesa na decisão precisa vir com
# proveniência -- schema novo, mas os campos são adicionados como
# OPCIONAIS para a validação interna (_CAMPOS_OBRIGATORIOS_PARECER, abaixo,
# continua o mesmo conjunto de sempre): uma resposta antiga/parcial sem
# 'numeros'/'lacunas'/'acao_ja_em_andamento' continua sendo um parecer
# válido (só sem esses extras), nunca vira RespostaLLMInvalida por isso.
TIPOS_ORIGEM_NUMERO = ('FONTE_INTERNA', 'FORNECEDOR', 'POLITICA', 'CALCULO', 'ESTIMATIVA')
_SCHEMA_NUMERO = {
    'type': 'object',
    'properties': {
        'valor': {'type': 'string'},
        'unidade': {'type': 'string'},
        'origem': {'type': 'string', 'enum': list(TIPOS_ORIGEM_NUMERO)},
        'fonte_detalhe': {'type': 'string'},
        'confianca': {'type': 'string', 'enum': ['alta', 'media', 'baixa']},
    },
    'required': ['valor', 'unidade', 'origem', 'fonte_detalhe', 'confianca'],
    'additionalProperties': False,
}

# P5.X M2 -- um agente pode sinalizar que a deliberação se beneficiaria de
# um visual (gráfico factual, conceito de rótulo, etc.), mas NUNCA gera o
# pixel/slide aqui -- só pede; quem atende é o Presentation/Chart Engine
# ou Pirret multimodal (M4-M6), sempre depois de aprovação humana. Campo
# aditivo, mesmo tratamento de 'numeros'/'lacunas': OPCIONAL na validação
# interna (não entra em _CAMPOS_OBRIGATORIOS_PARECER), obrigatório-mas-
# nulável no schema estrito da OpenAI (exigência do `strict: True`).
_SCHEMA_VISUAL_SOLICITADO = {
    'type': ['object', 'null'],
    'properties': {
        'artifact_type': {'type': 'string', 'enum': list(TIPOS_ARTEFATO)},
        'descricao': {'type': 'string'},
    },
    'required': ['artifact_type', 'descricao'],
    'additionalProperties': False,
}

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
        'numeros': {'type': 'array', 'items': _SCHEMA_NUMERO},
        'lacunas': {'type': 'array', 'items': {'type': 'string'}},
        'acao_ja_em_andamento': {'type': 'boolean'},
        'natureza_divergencia': {'type': 'string',
                                  'enum': ['divergencia_real', 'dado_ausente', 'risco', 'hipotese', 'nenhuma']},
        'requested_visual': _SCHEMA_VISUAL_SOLICITADO,
    },
    'required': ['dados_utilizados', 'conclusao', 'confianca', 'riscos', 'divergencias',
                 'acao_sugerida', 'necessidade_diretor', 'motivo_diretor', 'veto', 'veto_motivo',
                 'numeros', 'lacunas', 'acao_ja_em_andamento', 'natureza_divergencia', 'requested_visual'],
    'additionalProperties': False,
}
NATUREZAS_DIVERGENCIA = ('divergencia_real', 'dado_ausente', 'risco', 'hipotese', 'nenhuma')
# Só os campos originais continuam OBRIGATÓRIOS para um parecer ser válido
# -- ver comentário acima. `required` do schema (mais rígido, com os campos
# novos) é o que a OpenAI exige em modo strict; a validação interna é
# deliberadamente mais tolerante para nunca quebrar um parecer só porque
# faltou um campo aditivo.
_CAMPOS_OBRIGATORIOS_PARECER = ('dados_utilizados', 'conclusao', 'confianca', 'riscos', 'divergencias',
                                'acao_sugerida', 'necessidade_diretor', 'motivo_diretor', 'veto', 'veto_motivo')

_PADRAO_NUMERO_CITADO = re.compile(r'(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:%|dias?|semanas?|meses?|reais?|r\$)?', re.I)
_CAMPOS_TEXTO_DECISORIO = ('conclusao', 'riscos', 'acao_sugerida', 'divergencias', 'motivo_diretor')


def _numeros_citados_no_texto(parecer):
    texto = ' '.join(str(parecer.get(campo) or '') for campo in _CAMPOS_TEXTO_DECISORIO)
    return {m.group(1) for m in _PADRAO_NUMERO_CITADO.finditer(texto)}


def validar_proveniencia_numeros(parecer):
    """Validação PROGRAMÁTICA (não só instrução de prompt/persona): todo
    número que aparece nos campos decisórios do parecer (conclusão, riscos,
    ação sugerida, divergências, motivo do Diretor) e não está listado em
    `numeros` (com origem/fonte declaradas) volta aqui como 'sem
    proveniência' -- é isso que impede um '+50%' ou um '7-14 dias' de
    passar como se fosse fato ou política confirmada só porque o modelo
    escreveu um número com confiança.

    Escopo deliberado: números em `dados_utilizados` não entram nesta
    checagem -- ali é onde o agente CITA evidência (ex.: '3 leituras'),
    não onde ele afirma um número que pesa na decisão."""
    citados = _numeros_citados_no_texto(parecer)
    if not citados:
        return []
    tagueados = set()
    for numero in (parecer.get('numeros') or []):
        for m in _PADRAO_NUMERO_CITADO.finditer(str(numero.get('valor') or '')):
            tagueados.add(m.group(1))
    return sorted(citados - tagueados)


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

    # Validação programática de proveniência (não só instrução de persona):
    # um número decisório sem tag em `numeros` força necessidade_diretor,
    # nunca sustenta autorização automática sozinho.
    numeros_sem_evidencia = validar_proveniencia_numeros(parecer)
    necessidade_diretor = bool(parecer.get('necessidade_diretor')) or veto or bool(numeros_sem_evidencia)

    return {
        'agente': agente, 'ciclo': ciclo, 'demanda': demanda,
        'gerado_em': datetime.now(timezone.utc).isoformat(),
        'dados_utilizados': parecer.get('dados_utilizados', ''),
        'conclusao': parecer.get('conclusao', ''),
        'confianca': confianca,
        'riscos': parecer.get('riscos', ''),
        'divergencias': parecer.get('divergencias', ''),
        'acao_sugerida': parecer.get('acao_sugerida', ''),
        'necessidade_diretor': necessidade_diretor,
        'motivo_diretor': parecer.get('motivo_diretor', ''),
        'veto': veto,
        'veto_motivo': parecer.get('veto_motivo') if veto else None,
        'numeros': parecer.get('numeros') or [],
        'numeros_sem_evidencia': numeros_sem_evidencia,
        'lacunas': [l for l in (parecer.get('lacunas') or []) if isinstance(l, str) and l.strip()],
        'acao_ja_em_andamento': bool(parecer.get('acao_ja_em_andamento')),
        # None (não veio do modelo) sinaliza "parecer legado/sem classificação"
        # para _consolidar cair no critério conservador de antes -- nunca
        # tratado como 'nenhuma' (que apagaria uma divergência real por
        # ausência do campo).
        'natureza_divergencia': parecer.get('natureza_divergencia') if parecer.get('natureza_divergencia') in NATUREZAS_DIVERGENCIA else None,
        'requested_visual': _visual_solicitado_valido(parecer.get('requested_visual')),
        'modelo': MODELO_PADRAO,
    }


def _visual_solicitado_valido(visual):
    """Nunca repassa um requested_visual malformado adiante -- um pedido
    de visual com artifact_type fora do vocabulário canônico de
    mi_artefatos.TIPOS_ARTEFATO é tratado como se o agente não tivesse
    pedido nada (falha fechada, nunca um artefato de tipo inventado)."""
    if not isinstance(visual, dict):
        return None
    if visual.get('artifact_type') not in TIPOS_ARTEFATO:
        return None
    descricao = str(visual.get('descricao') or '').strip()
    if not descricao:
        return None
    return {'artifact_type': visual['artifact_type'], 'descricao': descricao}


def parecer_compacto(parecer):
    """Projeta um parecer já validado (formato interno de sempre, testado
    e usado por _consolidar/validar_proveniencia_numeros/etc, nunca
    alterado por esta função) na estrutura compacta que a Secretaria
    Executiva e o Presentation Engine consomem (P5.X M2) -- reduz volume
    de contexto sem reprocessar o parecer nem duplicar sua validação.
    Nunca substitui o parecer interno; é só uma leitura derivada dele."""
    divergencia_texto = (parecer.get('divergencias') or '').strip()
    return {
        'agente': parecer.get('agente'),
        'facts': [parecer['dados_utilizados']] if (parecer.get('dados_utilizados') or '').strip() else [],
        'evidence': [
            f"{n.get('valor', '')} {n.get('unidade', '')} (origem: {n.get('origem', '')})".strip()
            for n in (parecer.get('numeros') or [])
        ],
        'interpretation': [parecer['conclusao']] if (parecer.get('conclusao') or '').strip() else [],
        'recommendation': [parecer['acao_sugerida']] if (parecer.get('acao_sugerida') or '').strip() else [],
        'confidence': parecer.get('confianca'),
        'disagreement': [divergencia_texto] if divergencia_texto and divergencia_texto.lower() not in _SEM_DIVERGENCIA else [],
        'requested_visual': parecer.get('requested_visual'),
    }


def _classificar_natureza_divergencia(parecer):
    """Correção de classificação de divergência: usa o que o próprio
    agente declarou em `natureza_divergencia` (divergencia_real/
    dado_ausente/risco/hipotese/nenhuma) quando presente. Um parecer
    LEGADO (sem esse campo -- registros de antes desta correção) cai no
    critério conservador de sempre: texto não trivial em `divergencias`
    conta como divergência real, para nunca fazer uma ata antiga perder
    uma divergência que já estava registrada como tal."""
    natureza = parecer.get('natureza_divergencia')
    if natureza is not None:
        return natureza
    texto = (parecer.get('divergencias') or '').strip().lower()
    return 'nenhuma' if texto in _SEM_DIVERGENCIA else 'divergencia_real'


def _consolidar(avaliado, pareceres, erros, excedeu_limite=False, classificacao=None):
    """Monta o corpo para `mi_conselho.registrar_registro` a partir dos
    pareceres coletados -- reaproveita a estrutura já existente (tipo/
    participantes/posicoes/conflitos/vetos/recomendacoes/precisa_diretor),
    só ACRESCENTA campos dentro de `dados_apresentados` (JSONB livre, sem
    migration): `sintese_estruturada` com as 11 seções pedidas (o que
    sabemos / o que não sabemos / convergências / divergências / riscos /
    bloqueios / decisão possível agora / próxima ação / responsável /
    evidência necessária / precisa do Diretor), `motivos_diretor`,
    `classificacao_divergencia` e `recomendacoes_ja_em_andamento` (item 1:
    ações que o agente já viu em curso no pacote de estado e por isso NÃO
    viram recomendação nova).

    `posicoes[agente]` carrega um objeto (conclusao/confianca/dados_utilizados/
    riscos) em vez de só o texto da conclusão -- mesma coluna JSONB de sempre
    (sem migration), só um payload mais rico para o painel Admin poder
    apresentar Evidências/Riscos por agente sem inventar dado nenhum. Um
    registro antigo com `posicoes[agente]` como string simples continua
    válido (o painel trata os dois formatos)."""
    participantes = [p['agente'] for p in pareceres]
    posicoes = {
        p['agente']: {
            'conclusao': p['conclusao'],
            'confianca': p['confianca'],
            'dados_utilizados': p.get('dados_utilizados') or '',
            'riscos': p.get('riscos') or '',
        }
        for p in pareceres
    }
    vetos = {p['agente']: p['veto_motivo'] for p in pareceres if p.get('veto')}

    # Correção de classificação de divergência: dado ausente, risco,
    # hipótese ("caso outro agente...") e dimensões diferentes NÃO são
    # divergência -- só conta quando dois ou mais agentes têm posições
    # incompatíveis sobre a MESMA decisão atual (natureza_divergencia ==
    # 'divergencia_real'). `conflitos` (campo já existente, lido pelo
    # painel/testes de sempre) passa a refletir só divergências reais.
    classificacao_divergencia = [
        {'agente': p['agente'], 'natureza': _classificar_natureza_divergencia(p), 'texto': p.get('divergencias') or ''}
        for p in pareceres if (p.get('divergencias') or '').strip()
    ]
    conflitos = {c['agente']: c['texto'] for c in classificacao_divergencia if c['natureza'] == 'divergencia_real'}

    # Item 1: um agente que sinaliza acao_ja_em_andamento (porque o pacote
    # de estado já mostrava essa ação em curso/concluída) não vira
    # recomendação NOVA -- fica só como confirmação, nunca duplicada na
    # fila operacional.
    recomendacoes = [{'responsavel': p['agente'], 'descricao': p['acao_sugerida'], 'confianca': p['confianca']}
                      for p in pareceres
                      if (p.get('acao_sugerida') or '').strip() and not p.get('acao_ja_em_andamento')]
    recomendacoes_ja_em_andamento = [
        {'responsavel': p['agente'], 'descricao': p['acao_sugerida']}
        for p in pareceres if (p.get('acao_sugerida') or '').strip() and p.get('acao_ja_em_andamento')
    ]

    dados_ausentes = sorted({lacuna for p in pareceres for lacuna in (p.get('lacunas') or [])})
    numeros_sem_evidencia = sorted({n for p in pareceres for n in (p.get('numeros_sem_evidencia') or [])})

    pendencias = {}
    if erros:
        pendencias['agentes_com_falha'] = [e['agente'] for e in erros]
    if excedeu_limite:
        pendencias['especialistas_acima_do_limite'] = True
    if numeros_sem_evidencia:
        pendencias['numeros_sem_evidencia'] = numeros_sem_evidencia

    precisa_diretor = (bool(vetos) or bool(erros) or excedeu_limite
                       or any(p.get('necessidade_diretor') for p in pareceres))
    conclusao = ('; '.join(f"{AGENTES[p['agente']]['nome']}: {p['conclusao']}" for p in pareceres)
                 or 'Nenhum parecer obtido -- todos os especialistas convocados falharam.')

    # Escalonamento do Diretor sempre com MOTIVO explícito -- nunca só
    # "necessidade sinalizada por especialista" (a causa real observada de
    # falsa escalada: dado ausente ou divergência aparente virando "cabe
    # ao Diretor" sem dizer por quê).
    motivos_diretor = []
    for agente, motivo in vetos.items():
        motivos_diretor.append({'agente': AGENTES[agente]['nome'], 'motivo': f'veto jurídico — {motivo}'})
    for p in pareceres:
        if not p.get('necessidade_diretor') or p.get('veto'):
            continue
        motivo_texto = (p.get('motivo_diretor') or '').strip()
        if p.get('numeros_sem_evidencia'):
            extra = f"número(s) sem proveniência: {', '.join(p['numeros_sem_evidencia'])}"
            motivo_texto = f'{motivo_texto} ({extra})' if motivo_texto else extra
        motivos_diretor.append({
            'agente': AGENTES[p['agente']]['nome'],
            'motivo': motivo_texto or 'motivo não especificado pelo agente',
        })
    for erro in erros:
        nome = AGENTES.get(erro['agente'], {}).get('nome', erro['agente'])
        motivos_diretor.append({'agente': nome, 'motivo': 'falha ao consultar este especialista'})
    if excedeu_limite:
        motivos_diretor.append({'agente': None, 'motivo': 'demanda excedeu o limite de especialistas automáticos'})

    sintese_estruturada = {
        'o_que_sabemos': [
            {'agente': AGENTES[p['agente']]['nome'], 'dados_utilizados': p.get('dados_utilizados') or ''}
            for p in pareceres if (p.get('dados_utilizados') or '').strip()
        ],
        'o_que_nao_sabemos': dados_ausentes,
        'convergencias': [
            AGENTES[p['agente']]['nome'] for p in pareceres
            if (p.get('divergencias') or '').strip().lower() in _SEM_DIVERGENCIA
        ],
        'divergencias': {AGENTES[a]['nome']: texto for a, texto in conflitos.items()},
        'riscos': {AGENTES[p['agente']]['nome']: p['riscos'] for p in pareceres if (p.get('riscos') or '').strip()},
        'bloqueios': {
            'veto': {AGENTES[a]['nome']: motivo for a, motivo in vetos.items()} or None,
            'numeros_sem_evidencia': numeros_sem_evidencia or None,
            'agentes_com_falha': [e['agente'] for e in erros] or None,
        },
        'decisao_possivel_agora': bool(recomendacoes) and not precisa_diretor,
        'proxima_acao': recomendacoes[0]['descricao'] if recomendacoes else None,
        'responsavel': AGENTES[recomendacoes[0]['responsavel']]['nome'] if recomendacoes else None,
        'evidencia_necessaria': dados_ausentes,
        'precisa_diretor': precisa_diretor,
        'motivos_diretor': motivos_diretor or None,
    }

    return {
        'chave': str(uuid5(_NAMESPACE_EXECUCAO, avaliado['sinal_id'])),
        'tipo': 'reuniao' if len(pareceres) > 1 else 'relatorio',
        'demanda': avaliado['demanda'],
        'participantes': participantes,
        'contexto': avaliado['motivo'],
        'dados_apresentados': {
            'sinal_id': avaliado['sinal_id'], 'tipo_evento': avaliado['tipo_evento'],
            'sintese_estruturada': sintese_estruturada,
            'recomendacoes_ja_em_andamento': recomendacoes_ja_em_andamento or None,
            'classificacao_divergencia': classificacao_divergencia or None,
            # P5.X M2 -- roteamento já existente (mi_conselho_orquestrador.
            # classificar_especialistas) fica auditável no próprio registro:
            # quem foi convocado, por quê, e quem ficou de fora e por quê.
            'classificacao_especialistas': (
                {
                    'selecionados': classificacao.get('selecionados'),
                    'motivos': classificacao.get('motivos'),
                    'excluidos': classificacao.get('excluidos'),
                    'conclave_completo': classificacao.get('conclave_completo'),
                } if classificacao else None
            ),
            # Estrutura compacta (facts/evidence/interpretation/recommendation/
            # confidence/disagreement/requested_visual) por agente -- o que a
            # Secretaria Executiva (M3) e o Presentation Engine (M4) consomem
            # em vez de reprocessar os pareceres verbosos inteiros.
            'pareceres_compactos': [parecer_compacto(p) for p in pareceres] or None,
        },
        'posicoes': posicoes or None,
        'conflitos': conflitos or None,
        'conclusao': conclusao,
        'recomendacoes': recomendacoes,
        'vetos': vetos or None,
        'pendencias': pendencias or None,
        'precisa_diretor': precisa_diretor,
    }


_SLUG_INVALIDO = re.compile(r'[^a-z0-9_]+')


def _slug_topico(base, agente, indice):
    """Nome de tópico best-effort para mi_conselho_fatos a partir da
    unidade/descrição que o próprio agente informou -- nunca inventa um
    nome de negócio que não veio do parecer. Sem nada aproveitável, cai
    para `<agente>_numero_<indice>` (ainda assim consultável/auditável)."""
    slug = _SLUG_INVALIDO.sub('_', (base or '').strip().lower()).strip('_')
    slug = f'{agente}_{slug}' if slug else f'{agente}_numero_{indice}'
    if not slug[:1].isalpha():
        slug = 'n_' + slug
    return slug[:128]


def _extrair_registro_id(registro):
    corpo = registro[0] if isinstance(registro, tuple) else registro
    return (corpo or {}).get('id')


def _registrar_fatos_dos_pareceres(factory, pareceres, registro_id):
    """Item 4 (Iris) / item 3 (validade temporal): cada número que um
    especialista citou COM proveniência (parecer['numeros']) vira uma linha
    em mi_conselho_fatos -- é isso que transforma 'fatos confirmados
    reutilizáveis' de expectativa de prompt em tabela consultável de
    verdade. Só registra o que o próprio agente já tagueou (nunca infere
    origem/confiança aqui); um número sem origem reconhecida é ignorado
    (ele já força necessidade_diretor em executar_especialista, não precisa
    também virar 'fato'). Falha ao registrar um fato é só bookkeeping
    perdido -- nunca derruba o registro principal, já persistido."""
    for parecer in pareceres:
        for indice, numero in enumerate(parecer.get('numeros') or []):
            valor = str(numero.get('valor') or '').strip()
            origem = numero.get('origem')
            if not valor or origem not in TIPOS_ORIGEM_NUMERO:
                continue
            chave = str(uuid5(_NAMESPACE_EXECUCAO, f"fato:{registro_id}:{parecer['agente']}:{indice}"))
            try:
                registrar_fato(factory, {
                    'chave': chave,
                    'topico': _slug_topico(numero.get('unidade'), parecer['agente'], indice),
                    'valor': valor, 'unidade': numero.get('unidade'), 'origem_tipo': origem,
                    'fonte_detalhe': numero.get('fonte_detalhe'), 'confianca': numero.get('confianca'),
                    'agente_registrante': parecer['agente'], 'registro_id': registro_id,
                })
            except Exception:
                continue


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
    não alterado), para cada demanda relevante monta o pacote de estado
    (mi_conselho_estado -- item 1: ações concluídas/em andamento,
    bloqueios, prazos, evidências), executa só os especialistas já
    selecionados pelo classificador existente (nunca mais que
    `max_especialistas`, nunca Conclave completo automático) já COM esse
    contexto, consolida e registra em mi_conselho -- nunca executa nenhuma
    ação externa.

    Antes desta etapa, `executar_especialista` nunca recebia snapshot
    algum aqui (bug real, não só melhoria): cada especialista automático
    respondia só com a frase curta da demanda, cego para o que já estava
    em andamento -- causa direta de recomendações duplicadas."""
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

        # Pacote de estado montado UMA vez por demanda e compartilhado por
        # todos os especialistas convocados nesta rodada. Falha ao montar
        # nunca impede a rodada -- cai para snapshot=None, o mesmo
        # marcador "dado indisponível" que mi_conselho_orquestrador já
        # trata (nunca inventa contexto no lugar de uma falha de leitura).
        try:
            pacote_estado = montar_pacote_estado(factory, avaliado['demanda'], classificacao)
        except Exception:
            pacote_estado = None

        pareceres, erros = [], []
        for agente in agentes_a_executar:
            try:
                pareceres.append(executar_especialista(
                    agente, avaliado['demanda'], snapshot=pacote_estado, cliente=cliente,
                ))
            except Exception as erro:
                # Falha de um agente nunca libera ação nem é tratada como
                # "sem objeção" -- fica registrada como pendência explícita
                # e força precisa_diretor=True em _consolidar.
                erros.append({'agente': agente, 'erro': type(erro).__name__})

        consolidado = _consolidar(avaliado, pareceres, erros, excedeu_limite, classificacao=classificacao)
        registro = registrar_registro(factory, consolidado)
        _registrar_fatos_dos_pareceres(factory, pareceres, _extrair_registro_id(registro))
        resultados.append({**avaliado, 'pareceres': pareceres, 'erros': erros, 'registro': registro})
    return resultados
