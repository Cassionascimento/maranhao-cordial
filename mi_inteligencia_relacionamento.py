"""P2B-F -- Maranhão Intelligence Core: score explicável, segmentação,
detecção de oportunidade e Next Best Action sobre o Customer/Partner 360
(P1B) e o Unified Signal Model (P2A, mi_sinais_relacionamento.py).

Tudo aqui é determinístico e explicável -- nenhum ML, nenhum forecast
estatístico. Nenhuma escrita, nenhuma chamada externa, nenhuma execução:
o único produto é a RECOMENDAÇÃO; aprovação humana e execução continuam
100% em acoes_comerciais.py/mi_fila_operacional, como já eram antes.

Auditoria prévia (P2F): a estrutura SIGNAL -> RECOMMENDATION -> HUMAN
DECISION -> ACTION -> OUTCOME já existe -- `mi_fila_operacional`
(migrations 014/015) tem exatamente esses estados
(planejada/aguardando/concluida/bloqueada/precisa_diretor) e um campo
`resultado` JSONB, com `mi_decisao.registrar_item_fila`/
`avancar_estado_fila` já implementados e testados (só não persistindo
ainda -- `mi_decisao.planejar()` continua dry-run por desenho, sem
mudança aqui). Por isso este módulo NÃO cria nenhuma tabela nova: só
converte uma recomendação para o formato que `mi_decisao.validar_item_
fila` já aceita (`recomendacao_para_item_fila`), sem chamar
`registrar_item_fila` -- ligar essa persistência é uma decisão sobre
`mi_fila_operacional`, não deste módulo.

Não confunde "probabilidade de compra" (commercial_intent) com "valor
estratégico" (relationship_value) -- são dimensões separadas de propósito.
"""
from datetime import datetime, timezone

from mi_sinais_relacionamento import extrair_sinais

VERSAO_SCORE = 'relacionamento_score_v1'
PRIORIDADES = ('baixa', 'normal', 'alta', 'urgente')
ACOES_RECOMENDADAS = ('CONTACT_REORDER', 'FOLLOW_UP_SAMPLE', 'CREATE_PROPOSAL', 'REVIEW_PARTNER',
                      'FOLLOW_UP_PIPELINE', 'NO_ACTION')
_CATEGORIAS_ESTRATEGICAS = ('distribuidor', 'parceiro', 'fabrica', 'investidor')
_CATEGORIA_FORNECEDOR = 'fornecedor'
_ESTAGIOS_TERMINAIS = ('perdido', 'encerrado', 'inativo', 'descartado', 'novo')
MAX_RECOMENDACOES = 3


def _dias(valor):
    return valor if isinstance(valor, int) else None


# =====================================================================
# P2B -- EXPLAINABLE RELATIONSHIP SCORE
# =====================================================================

def _dimensao_engagement(metricas):
    interacoes = metricas.get('interaction_count') or 0
    dias = _dias(metricas.get('days_since_last_interaction'))
    if interacoes == 0:
        return {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['nenhuma interação registrada']}
    base = min(interacoes * 15, 70)
    if dias is not None and dias <= 7:
        recencia, motivo_recencia = 30, f'última interação há {dias} dia(s)'
    elif dias is not None and dias <= 30:
        recencia, motivo_recencia = 15, f'última interação há {dias} dia(s)'
    else:
        recencia, motivo_recencia = 0, f'última interação há {dias} dia(s)' if dias is not None else 'sem data de última interação'
    valor = min(base + recencia, 100)
    return {'valor': valor, 'explicacao': [f'{interacoes} interação(ões) registrada(s)', motivo_recencia]}


def _dimensao_commercial_intent(visao_360, metricas):
    propostas = visao_360.get('commercial', {}).get('propostas') or []
    pendentes = [p for p in propostas if p.get('status') == 'aguardando_aprovacao']
    estagio = (visao_360.get('commercial', {}).get('estagio') or 'novo').lower()
    formularios = visao_360.get('behavior', {}).get('formularios', {})
    total_formularios = len(formularios.get('cadastro_profissional') or []) + len(formularios.get('degustacao') or [])

    explicacao = []
    valor = 0
    if pendentes:
        valor += 40
        explicacao.append(f'{len(pendentes)} proposta(s) aguardando aprovação')
    if estagio not in ('novo',):
        valor += 25
        explicacao.append(f'estágio atual: {estagio}')
    if total_formularios:
        valor += 20
        explicacao.append(f'{total_formularios} formulário(s) de interesse preenchido(s)')
    if metricas.get('interaction_count'):
        valor += min(metricas['interaction_count'] * 5, 15)
        explicacao.append('possui interações registradas')
    if not explicacao:
        explicacao.append('nenhum sinal de intenção comercial além do estágio inicial')
    return {'valor': min(valor, 100), 'explicacao': explicacao}


def _dimensao_relationship_value(lead, metricas):
    if lead is None:
        return {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['nenhuma pessoa resolvida para este relacionamento']}
    receita = lead.get('receita_acumulada_centavos') or 0
    categoria = (lead.get('categoria_contato') or '').lower()
    explicacao = []
    valor = min(receita / 1000, 60) if receita else 0
    if receita:
        explicacao.append(f'receita acumulada de {receita} centavos')
    if categoria in _CATEGORIAS_ESTRATEGICAS:
        valor += 30
        explicacao.append(f"categoria '{categoria}' tem piso estratégico "
                           "(valor não depende só de volume de compra)")
    if metricas.get('total_orders'):
        valor += min(metricas['total_orders'] * 5, 10)
        explicacao.append(f"{metricas['total_orders']} pedido(s) no ledger comercial")
    if not explicacao:
        explicacao.append('sem receita acumulada e sem categoria estratégica conhecida')
    return {'valor': round(min(valor, 100), 1), 'explicacao': explicacao}


def _dimensao_reorder_signal(visao_360, metricas, sinais):
    if metricas.get('total_orders', 0) == 0:
        return {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['sem histórico de compra']}
    reorder_due = next((s for s in sinais if s['type'] == 'reorder_due'), None)
    reorder_scheduled = next((s for s in sinais if s['type'] == 'reorder_scheduled'), None)
    recompras_sku = sum(1 for p in (visao_360.get('products') or []) if p.get('recompra'))
    if reorder_due:
        return {'valor': 90, 'explicacao': [f"janela de recompra vencida em {reorder_due['timestamp']}"]}
    if reorder_scheduled:
        return {'valor': 40, 'explicacao': [f"próxima recompra prevista para {reorder_scheduled['timestamp']}"]}
    if recompras_sku:
        return {'valor': 55, 'explicacao': [f'{recompras_sku} SKU(s) já com recompra observada']}
    return {'valor': 15, 'explicacao': ['compra única registrada, sem sinal de recompra ainda']}


def _dimensao_data_quality(sinais):
    if not sinais:
        return {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['nenhum sinal disponível']}
    media = sum(s['confidence'] for s in sinais) / len(sinais)
    diretos = sum(1 for s in sinais if s['confidence'] >= 1.0)
    return {'valor': round(media * 100, 1),
            'explicacao': [f'{diretos}/{len(sinais)} sinais com vínculo direto (FK), restante inferido']}


def calcular_score(visao_360, sinais=None, agora=None):
    """Score único, versionado (`VERSAO_SCORE`) e explicável por dimensão.
    `score_geral` só existe quando pelo menos 2 das 4 dimensões
    substantivas têm dado real -- nunca um número inventado sobre
    NOT_ENOUGH_DATA."""
    agora = agora or datetime.now(timezone.utc)
    sinais = sinais if sinais is not None else extrair_sinais(visao_360, agora=agora)
    lead = visao_360.get('identity', {}).get('pessoa')
    metricas = visao_360.get('derived_metrics', {})

    dimensoes = {
        'engagement': _dimensao_engagement(metricas),
        'commercial_intent': _dimensao_commercial_intent(visao_360, metricas),
        'relationship_value': _dimensao_relationship_value(lead, metricas),
        'reorder_signal': _dimensao_reorder_signal(visao_360, metricas, sinais),
    }
    substantivas = ('engagement', 'commercial_intent', 'relationship_value', 'reorder_signal')
    disponiveis = [dimensoes[d]['valor'] for d in substantivas if dimensoes[d]['valor'] != 'NOT_ENOUGH_DATA']
    if len(disponiveis) >= 2:
        score_geral = round(sum(disponiveis) / len(disponiveis), 1)
    else:
        score_geral = 'NOT_ENOUGH_DATA'

    dimensoes['data_quality'] = _dimensao_data_quality(sinais)
    confianca_geral = (dimensoes['data_quality']['valor'] / 100
                        if dimensoes['data_quality']['valor'] != 'NOT_ENOUGH_DATA' else 'NOT_ENOUGH_DATA')

    return {
        'versao': VERSAO_SCORE, 'calculado_em': agora.isoformat(),
        'dimensoes': dimensoes, 'score_geral': score_geral, 'confianca_geral': confianca_geral,
        'dimensoes_usadas_no_geral': [d for d in substantivas if dimensoes[d]['valor'] != 'NOT_ENOUGH_DATA'],
    }


# =====================================================================
# P2C -- BEHAVIORAL SEGMENTATION (não exclusiva: 0..N segmentos)
# =====================================================================

def segmentar(visao_360, sinais, agora=None):
    agora = agora or datetime.now(timezone.utc)
    lead = visao_360.get('identity', {}).get('pessoa')
    metricas = visao_360.get('derived_metrics', {})
    total_orders = metricas.get('total_orders', 0)
    dias_interacao = _dias(metricas.get('days_since_last_interaction'))
    interacao_count = metricas.get('interaction_count', 0)
    categoria = ((lead or {}).get('categoria_contato') or '').lower()
    estagio = ((visao_360.get('commercial', {}) or {}).get('estagio') or '').lower()
    reorder_due = any(s['type'] == 'reorder_due' for s in sinais)
    interesse_alto = any(
        (s['type'] == 'interaction' and s.get('strength') in ('alto', 'quente', 'interesse_alto'))
        or (s['type'] == 'form_submission' and s['source'] == 'degustacao')
        for s in sinais
    )
    dias_desde_criacao = _dias((agora - lead['criado_em']).days if lead and lead.get('criado_em') else None)

    segmentos = []

    def add(nome, motivo):
        segmentos.append({'segmento': nome, 'motivo': motivo})

    if lead and dias_desde_criacao is not None and dias_desde_criacao <= 30 and total_orders == 0:
        add('new_relationship', f'criado há {dias_desde_criacao} dia(s), sem compra ainda')
    if interacao_count > 0 and total_orders == 0:
        add('engaged_no_purchase', f'{interacao_count} interação(ões) sem nenhum pedido')
    if interesse_alto and total_orders == 0:
        add('sampling_interest', 'sinal de interesse alto/degustação sem conversão em pedido')
    if total_orders == 1:
        add('first_purchase', 'exatamente 1 pedido no ledger comercial')
    if total_orders >= 2:
        add('repeat_customer', f'{total_orders} pedidos no ledger comercial')
    if reorder_due:
        add('reorder_due', 'janela de recompra prevista já venceu')
    if total_orders >= 1 and dias_interacao is not None and dias_interacao > 90:
        add('inactive_customer', f'{total_orders} pedido(s), mas {dias_interacao} dias sem interação')
    if categoria in _CATEGORIAS_ESTRATEGICAS:
        add('strategic_partner', f"categoria de contato '{categoria}'")
    if categoria == _CATEGORIA_FORNECEDOR:
        add('supplier_relationship', "categoria de contato 'fornecedor'")

    return segmentos


# =====================================================================
# P2D -- OPPORTUNITY DETECTION
# =====================================================================

def _oportunidade(tipo, prioridade, confianca, evidencias, relacionamento_id, acao, sku=None):
    return {'type': tipo, 'priority': prioridade, 'confidence': confianca, 'evidence': evidencias,
            'relationship_id': relacionamento_id, 'sku': sku, 'recommended_action': acao}


def detectar_oportunidades(visao_360, sinais, score, segmentos, relacionamento_id, agora=None):
    """Cada detector só dispara com evidência real já presente no 360/sinais
    -- nenhuma oportunidade é inventada por ausência de dado. Afinidade
    cruzada entre SKUs de clientes diferentes fica fora deste núcleo
    (exigiria consulta agregada entre relacionamentos, não só deste 360 --
    ver riscos/gaps no relatório de entrega)."""
    agora = agora or datetime.now(timezone.utc)
    metricas = visao_360.get('derived_metrics', {})
    nomes_segmentos = {s['segmento'] for s in segmentos}
    oportunidades = []

    reorder_due = next((s for s in sinais if s['type'] == 'reorder_due'), None)
    if reorder_due:
        oportunidades.append(_oportunidade(
            'provavel_recompra', 'alta', reorder_due['confidence'], reorder_due['evidence'],
            relacionamento_id, 'CONTACT_REORDER',
        ))

    if 'sampling_interest' in nomes_segmentos:
        evidencia = next((s['evidence'] for s in sinais if s['type'] in ('interaction', 'form_submission')), [])
        oportunidades.append(_oportunidade(
            'interesse_sem_conversao', 'normal', 0.6, evidencia, relacionamento_id, 'FOLLOW_UP_SAMPLE',
        ))

    dias_interacao = _dias(metricas.get('days_since_last_interaction'))
    if metricas.get('total_orders', 0) >= 1 and dias_interacao is not None and dias_interacao > 60 \
            and not reorder_due:
        oportunidades.append(_oportunidade(
            'cliente_ativo_sem_contato_recente', 'normal', 0.7,
            [f'{metricas["total_orders"]} pedido(s) no histórico', f'{dias_interacao} dias sem interação'],
            relacionamento_id, 'FOLLOW_UP_PIPELINE',
        ))

    eventos = visao_360.get('behavior', {}).get('eventos_do_estabelecimento') or []
    if len(eventos) >= 2 and metricas.get('interaction_count', 0) == 0:
        oportunidades.append(_oportunidade(
            'estabelecimento_ativo_sem_identidade_direta', 'normal', 0.6,
            [f'{len(eventos)} evento(s) de fábrica/QR no estabelecimento, sem nenhuma interação com uma pessoa'],
            relacionamento_id, 'REVIEW_PARTNER',
        ))

    if 'strategic_partner' in nomes_segmentos and (dias_interacao is None or dias_interacao > 60):
        oportunidades.append(_oportunidade(
            'parceiro_estrategico_sem_acompanhamento', 'alta', 0.7,
            [s['motivo'] for s in segmentos if s['segmento'] == 'strategic_partner']
            + ([f'{dias_interacao} dias sem interação'] if dias_interacao is not None else ['nenhuma interação registrada']),
            relacionamento_id, 'REVIEW_PARTNER',
        ))

    estagio = (visao_360.get('commercial', {}).get('estagio') or '').lower()
    if estagio and estagio not in _ESTAGIOS_TERMINAIS and dias_interacao is not None and dias_interacao > 30:
        oportunidades.append(_oportunidade(
            'pipeline_parado', 'normal', 0.6,
            [f'estágio {estagio}', f'{dias_interacao} dias sem interação'],
            relacionamento_id, 'FOLLOW_UP_PIPELINE',
        ))

    if not reorder_due:
        for produto in (visao_360.get('products') or []):
            if produto.get('recompra'):
                oportunidades.append(_oportunidade(
                    'sku_com_padrao_de_recompra', 'normal', 0.6,
                    [f"{produto.get('quantidade_pedidos')} pedidos do SKU {produto.get('sku')}",
                     f"última compra em {produto.get('ultima_compra')}"],
                    relacionamento_id, 'CONTACT_REORDER', sku=produto.get('sku'),
                ))

    return oportunidades


# =====================================================================
# P2E -- NEXT BEST ACTION (recomenda; nunca executa)
# =====================================================================

def gerar_next_best_actions(oportunidades, limite=MAX_RECOMENDACOES, agora=None):
    agora = agora or datetime.now(timezone.utc)
    ordem_prioridade = {'urgente': 0, 'alta': 1, 'normal': 2, 'baixa': 3}
    ordenadas = sorted(oportunidades, key=lambda o: (ordem_prioridade.get(o['priority'], 9), -o['confidence']))
    if not ordenadas:
        return [{
            'action': 'NO_ACTION', 'reason': 'Nenhuma oportunidade com evidência suficiente foi detectada.',
            'evidence': [], 'confidence': 1.0, 'generated_at': agora.isoformat(),
            'relationship_id': None, 'priority': 'baixa',
        }]
    recomendacoes = []
    for oportunidade in ordenadas[:limite]:
        recomendacoes.append({
            'action': oportunidade['recommended_action'],
            'reason': f"{oportunidade['type']} (prioridade {oportunidade['priority']})",
            'evidence': oportunidade['evidence'],
            'confidence': oportunidade['confidence'],
            'generated_at': agora.isoformat(),
            'relationship_id': oportunidade['relationship_id'],
            'priority': oportunidade['priority'],
            'sku': oportunidade.get('sku'),
        })
    return recomendacoes


# =====================================================================
# P2F -- compatibilidade com a fila de decisão já existente (mi_decisao)
# =====================================================================

def recomendacao_para_item_fila(recomendacao, lead_id=None, estabelecimento_id=None):
    """Converte só o FORMATO de uma recomendação de NBA para o corpo que
    `mi_decisao.validar_item_fila`/`registrar_item_fila` já aceitam --
    NUNCA chama essas funções aqui (nenhuma persistência nova). Serve para
    provar compatibilidade: se um dia a persistência de mi_fila_operacional
    for ligada, uma recomendação deste módulo já nasce no formato certo.
    `exige_aprovacao=True` sempre -- nenhuma recomendação deste núcleo é
    autônoma."""
    return {
        'origem': 'relacionamento_360',
        'origem_id': recomendacao.get('relationship_id'),
        'tipo_decisao': recomendacao['action'].lower(),
        'fatos': list(recomendacao.get('evidence') or []),
        'inferencia': recomendacao.get('reason'),
        'prioridade': recomendacao.get('priority') if recomendacao.get('priority') in PRIORIDADES else 'normal',
        'confianca': recomendacao.get('confidence'),
        'proxima_acao': recomendacao['action'],
        'exige_aprovacao': True,
        'lead_id': lead_id,
        'estabelecimento_id': estabelecimento_id,
    }


# =====================================================================
# Ponto único de leitura (usado pela rota HTTP)
# =====================================================================

def inteligencia_do_relacionamento(visao_360, relacionamento_id, agora=None):
    agora = agora or datetime.now(timezone.utc)
    sinais = extrair_sinais(visao_360, agora=agora)
    score = calcular_score(visao_360, sinais=sinais, agora=agora)
    segmentos = segmentar(visao_360, sinais, agora=agora)
    oportunidades = detectar_oportunidades(visao_360, sinais, score, segmentos, relacionamento_id, agora=agora)
    next_best_actions = gerar_next_best_actions(oportunidades, agora=agora)
    return {
        'relationship_id': relacionamento_id,
        'signals': sinais,
        'score': score,
        'segments': segmentos,
        'opportunities': oportunidades,
        'next_best_actions': next_best_actions,
    }


def registrar_rotas_leitura(app, factory, autorizado):
    """Só GET -- nenhuma rota de escrita, nenhuma ação disparada."""
    from flask import jsonify
    from mi_relacionamento_360 import relacionamento_360
    from psycopg2.extras import RealDictCursor

    @app.route('/api/admin/mi/relacionamento/<entidade_id>/inteligencia', methods=['GET'])
    def mi_inteligencia_relacionamento(entidade_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                visao = relacionamento_360(cur, entidade_id)
        except Exception:
            app.logger.exception('Falha ao calcular inteligência do relacionamento')
            return jsonify(success=False, error='Inteligência indisponível.'), 503
        finally:
            conn.close()
        if not visao:
            return jsonify(success=False, error='Relacionamento não encontrado.'), 404
        resultado = inteligencia_do_relacionamento(visao, entidade_id)
        return jsonify(success=True, **resultado)
