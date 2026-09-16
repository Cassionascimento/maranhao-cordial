"""Customer/Partner 360 -- visão consolidada de UM relacionamento (pessoa
e/ou estabelecimento), agregando exclusivamente estruturas já existentes.
Nenhuma tabela nova, nenhuma segunda camada de identidade: a pessoa
continua sendo `leads_crm` (resolvida pelo Contact Central, main.py) e o
estabelecimento continua sendo `mi_estabelecimentos.lead_id` (FK que já
existia). Papel (bartender/bar/restaurante/hotel/distribuidor/.../lead) é
o `leads_crm.categoria_contato` que já existe -- nenhuma taxonomia nova.

Vínculo DIRECT (por FK/identidade formal) x INFERRED (por correspondência
de texto, ex. e-mail/whatsapp) é sempre explícito por seção -- nunca
apresentado como certeza quando é inferência. Nenhuma escrita, nenhuma
fusão, nenhum valor inventado: ausência de dado é sempre None/[]/
'NOT_ENOUGH_DATA', nunca um palpite.
"""
from datetime import datetime, timezone
from uuid import UUID
from psycopg2.extras import RealDictCursor

LIMITE_PADRAO = 50


def _uuid_ou_none(valor):
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        return None


def _dias_desde(quando, agora):
    if not quando:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return (agora - quando).days


# --------------------------------------------------------------- leitura

def _lead_por_id(cur, lead_id):
    cur.execute(
        "SELECT id, nome, empresa, email, telefone, instagram, cidade, estado, origem, canal, "
        "categoria_contato, estagio, status, prioridade, valor_potencial_centavos, "
        "receita_acumulada_centavos, quantidade_compras, ultima_compra_em, proxima_recompra_em, "
        "motivo_perda, proximo_followup, ultima_interacao_em, criado_em, atualizado_em "
        "FROM leads_crm WHERE id=%s",
        (lead_id,),
    )
    linha = cur.fetchone()
    return dict(linha) if linha else None


def _estabelecimento_por_id(cur, estabelecimento_id):
    cur.execute(
        "SELECT id, nome, tipo, cidade, uf, bairro, lead_id, criado_em FROM mi_estabelecimentos WHERE id=%s",
        (estabelecimento_id,),
    )
    linha = cur.fetchone()
    return dict(linha) if linha else None


def _estabelecimento_do_lead(cur, lead_id):
    cur.execute(
        "SELECT id, nome, tipo, cidade, uf, bairro, lead_id, criado_em FROM mi_estabelecimentos "
        "WHERE lead_id=%s ORDER BY criado_em ASC LIMIT 1",
        (lead_id,),
    )
    linha = cur.fetchone()
    return dict(linha) if linha else None


def _identidades_externas(cur, lead_id):
    cur.execute(
        "SELECT canal, identificador_externo, username_publico, status, criterio_vinculo, confianca, "
        "criado_em FROM identidades_externas_contato WHERE contato_central_id=%s ORDER BY criado_em ASC",
        (lead_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _interacoes(cur, lead_id, limite):
    cur.execute(
        "SELECT canal, plataforma, tipo_interacao, classificacao, interesse, criado_em "
        "FROM interacoes_omnichannel WHERE lead_id=%s ORDER BY criado_em DESC LIMIT %s",
        (lead_id, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _compras_relacionamento(cur, lead_id, limite):
    """Ledger comercial autoritativo (FK direta) -- fonte de receita/
    quantidade/ticket médio. Não carrega SKU (isso vem de `pedidos`)."""
    cur.execute(
        "SELECT id, referencia_externa, origem, valor_centavos, quantidade_itens, status, comprado_em "
        "FROM compras_relacionamento WHERE contato_id=%s ORDER BY comprado_em DESC LIMIT %s",
        (lead_id, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _pedidos_vinculados(cur, email, whatsapp, limite):
    """Vínculo INFERRED (pedidos não tem FK para leads_crm): e-mail
    normalizado (mesmo critério do Contact Central) ou whatsapp por
    igualdade exata de string (limitação conhecida -- sem normalização de
    dígitos aqui, documentada em data_quality)."""
    if not email and not whatsapp:
        return []
    cur.execute(
        "SELECT codigo, status, valor_centavos, quantidade, sku, criado_em FROM pedidos "
        "WHERE (%s IS NOT NULL AND lower(trim(cliente_email))=lower(trim(%s))) "
        "OR (%s IS NOT NULL AND cliente_whatsapp=%s) "
        "ORDER BY criado_em DESC LIMIT %s",
        (email, email, whatsapp, whatsapp, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _propostas_vinculadas(cur, email, limite):
    """acoes_comerciais_propostas -- vínculo INFERRED por e-mail (JSONB
    dados->>'destinatario', sem FK). Escopo real hoje: só prospecção de
    fase56/fase57 (e-mail), não qualquer proposta comercial."""
    if not email:
        return []
    cur.execute(
        "SELECT id, status, dados->>'tipo' AS tipo, criado_em FROM acoes_comerciais_propostas "
        "WHERE lower(dados->>'destinatario')=lower(%s) ORDER BY criado_em DESC LIMIT %s",
        (email, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _formularios_vinculados(cur, email, limite):
    """cadastros_profissionais/solicitacoes_degustacao -- vínculo INFERRED
    por e-mail exato (mesmo critério forte que o Contact Central usa para
    email, mas sem passar pela função formal -- por isso INFERRED, não
    DIRECT)."""
    if not email:
        return [], []
    cur.execute(
        "SELECT id, empresa, cidade, status, criado_em FROM cadastros_profissionais "
        "WHERE lower(email)=lower(%s) ORDER BY criado_em DESC LIMIT %s",
        (email, limite),
    )
    profissionais = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT id, empresa, cidade, status, criado_em FROM solicitacoes_degustacao "
        "WHERE lower(email)=lower(%s) ORDER BY criado_em DESC LIMIT %s",
        (email, limite),
    )
    degustacoes = [dict(r) for r in cur.fetchall()]
    return profissionais, degustacoes


def _eventos_do_estabelecimento(cur, estabelecimento_id, limite):
    """mi_eventos nunca tem lead_id (por desenho -- rastreabilidade de
    lote/unidade, nunca PII de consumidor). Só aparece aqui quando o
    relacionamento tem um estabelecimento associado -- vínculo INFERRED ao
    estabelecimento, nunca à pessoa."""
    if not estabelecimento_id:
        return []
    cur.execute(
        "SELECT tipo_evento, canal, sku, unidade_id, ocorrido_em, criado_em FROM mi_eventos "
        "WHERE estabelecimento_id=%s ORDER BY criado_em DESC LIMIT %s",
        (estabelecimento_id, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _produtos_por_sku(cur, skus):
    if not skus:
        return {}
    cur.execute(
        "SELECT sku, produto_nome, categoria FROM mi_skus WHERE sku = ANY(%s)",
        (list(skus),),
    )
    return {r['sku']: dict(r) for r in cur.fetchall()}


# ------------------------------------------------------------- agregação

def _agrupar_pedidos_por_sku(pedidos):
    grupos = {}
    for p in pedidos:
        sku = p.get('sku')
        if not sku:
            continue
        g = grupos.setdefault(sku, {'sku': sku, 'quantidade_pedidos': 0, 'primeira_compra': None,
                                     'ultima_compra': None})
        g['quantidade_pedidos'] += 1
        data = p.get('criado_em')
        if data and (g['primeira_compra'] is None or data < g['primeira_compra']):
            g['primeira_compra'] = data
        if data and (g['ultima_compra'] is None or data > g['ultima_compra']):
            g['ultima_compra'] = data
    return grupos


def _metricas_derivadas(compras, pedidos, interacoes, agora):
    total_orders = len(compras)
    receitas = [c['valor_centavos'] for c in compras if c.get('valor_centavos') is not None]
    total_revenue = sum(receitas) if receitas else (0 if total_orders == 0 else 'NOT_ENOUGH_DATA')
    average_order_value = (total_revenue / total_orders) if (isinstance(total_revenue, (int, float))
                                                               and total_orders > 0) else 'NOT_ENOUGH_DATA'
    ultima_compra = max((c['comprado_em'] for c in compras if c.get('comprado_em')), default=None)
    dias_desde_pedido = _dias_desde(ultima_compra, agora) if ultima_compra else 'NOT_ENOUGH_DATA'
    ultima_interacao = max((i['criado_em'] for i in interacoes if i.get('criado_em')), default=None)
    dias_desde_interacao = _dias_desde(ultima_interacao, agora) if ultima_interacao else 'NOT_ENOUGH_DATA'
    reorder_count = max(total_orders - 1, 0) if total_orders > 0 else 'NOT_ENOUGH_DATA'
    orders_by_sku = {sku: g['quantidade_pedidos'] for sku, g in _agrupar_pedidos_por_sku(pedidos).items()}
    return {
        'total_orders': total_orders,
        'total_revenue_centavos': total_revenue,
        'average_order_value_centavos': average_order_value,
        'days_since_last_order': dias_desde_pedido,
        'days_since_last_interaction': dias_desde_interacao,
        'products_purchased': sorted(orders_by_sku.keys()),
        'orders_by_sku': orders_by_sku,
        'reorder_count': reorder_count,
        'interaction_count': len(interacoes),
        'channels_used': sorted({i['canal'] for i in interacoes if i.get('canal')}),
    }


def relacionamento_360(cur, entidade_id, limite=LIMITE_PADRAO, agora=None):
    """Ponto único de leitura: `entidade_id` pode ser um `leads_crm.id`
    (pessoa) ou um `mi_estabelecimentos.id` (organização) -- detectado por
    tentativa, nunca adivinhado. Devolve None quando não existe nenhum dos
    dois (o chamador HTTP decide o 404)."""
    agora = agora or datetime.now(timezone.utc)
    lead_id = _uuid_ou_none(entidade_id)
    if not lead_id:
        return None

    lead = _lead_por_id(cur, lead_id)
    estabelecimento = None
    if lead:
        estabelecimento = _estabelecimento_do_lead(cur, lead_id)
    else:
        estabelecimento = _estabelecimento_por_id(cur, lead_id)
        if not estabelecimento:
            return None
        if estabelecimento.get('lead_id'):
            lead = _lead_por_id(cur, estabelecimento['lead_id'])

    email = lead.get('email') if lead else None
    whatsapp = lead.get('telefone') if lead else None

    identidades = _identidades_externas(cur, lead['id'], ) if lead else []
    interacoes = _interacoes(cur, lead['id'], limite) if lead else []
    compras = _compras_relacionamento(cur, lead['id'], limite) if lead else []
    pedidos = _pedidos_vinculados(cur, email, whatsapp, limite)
    propostas = _propostas_vinculadas(cur, email, limite)
    profissionais, degustacoes = _formularios_vinculados(cur, email, limite)
    eventos = _eventos_do_estabelecimento(cur, estabelecimento['id'] if estabelecimento else None, limite)

    skus_comprados = sorted({p['sku'] for p in pedidos if p.get('sku')})
    produtos_info = _produtos_por_sku(cur, skus_comprados)
    grupos_sku = _agrupar_pedidos_por_sku(pedidos)
    produtos = [{
        'sku': sku,
        'produto_nome': produtos_info.get(sku, {}).get('produto_nome'),
        'categoria': produtos_info.get(sku, {}).get('categoria'),
        'encontrado_no_catalogo': sku in produtos_info,
        'quantidade_pedidos': dados['quantidade_pedidos'],
        'primeira_compra': dados['primeira_compra'],
        'ultima_compra': dados['ultima_compra'],
        'recompra': dados['quantidade_pedidos'] > 1,
    } for sku, dados in sorted(grupos_sku.items())]

    primeira_interacao = min(
        [i['criado_em'] for i in interacoes if i.get('criado_em')]
        + ([lead['criado_em']] if lead and lead.get('criado_em') else []),
        default=None,
    )
    ultima_interacao = max((i['criado_em'] for i in interacoes if i.get('criado_em')), default=None)

    cidade = (estabelecimento or {}).get('cidade') or (lead or {}).get('cidade')
    uf = (estabelecimento or {}).get('uf') or (lead or {}).get('estado')

    return {
        'identity': {
            'pessoa': lead,
            'papel': (lead or {}).get('categoria_contato'),
            'contatos_e_canais': identidades,
            'origem': (lead or {}).get('origem'),
            'primeira_interacao': primeira_interacao,
            'ultima_interacao': ultima_interacao,
        } if lead else {
            'pessoa': None, 'papel': None, 'contatos_e_canais': [], 'origem': None,
            'primeira_interacao': None, 'ultima_interacao': None,
        },
        'organization': estabelecimento,
        'relationship': {
            'pessoa_estabelecimento': 'DIRECT' if (estabelecimento and estabelecimento.get('lead_id')) else 'UNKNOWN',
            'estabelecimento_pedidos': 'INFERRED' if (estabelecimento and pedidos) else 'UNKNOWN',
            'estabelecimento_produtos': 'INFERRED' if (estabelecimento and produtos) else 'UNKNOWN',
            'pessoa_interacoes': 'DIRECT' if interacoes else 'UNKNOWN',
        },
        'commercial': {
            'estagio': (lead or {}).get('estagio'),
            'motivo_perda': (lead or {}).get('motivo_perda'),
            'propostas': propostas,
            'compras_relacionamento': compras,
            'pedidos_vinculados': pedidos,
            'receita_acumulada_centavos': (lead or {}).get('receita_acumulada_centavos'),
            'quantidade_compras_leads_crm': (lead or {}).get('quantidade_compras'),
            'ultima_compra_em': (lead or {}).get('ultima_compra_em'),
            'proxima_recompra_em': (lead or {}).get('proxima_recompra_em'),
        },
        'products': produtos,
        'behavior': {
            'interacoes_omnichannel': interacoes,
            'eventos_do_estabelecimento': eventos,
            'formularios': {'cadastro_profissional': profissionais, 'degustacao': degustacoes},
            'canais_utilizados': sorted({i['canal'] for i in interacoes if i.get('canal')}
                                         | {i['canal'] for i in identidades if i.get('canal')}),
        },
        'geography': {'cidade': cidade, 'uf': uf, 'territorio': 'NOT_ENOUGH_DATA'},
        'derived_metrics': _metricas_derivadas(compras, pedidos, interacoes, agora),
        'data_quality': {
            'pessoa_resolvida': lead is not None,
            'estabelecimento_resolvido': estabelecimento is not None,
            'pedidos_vinculo': 'INFERRED (e-mail normalizado ou whatsapp por igualdade exata de string)',
            'propostas_vinculo': 'INFERRED (e-mail, só cobre prospecção fase56/fase57)',
            'formularios_vinculo': 'INFERRED (e-mail exato)',
            'eventos_vinculo': 'INFERRED ao estabelecimento, nunca à pessoa (mi_eventos não tem lead_id)',
            'compras_relacionamento_e_autoritativo_para_receita': True,
            'lead_score_unificado': 'NOT_ENOUGH_DATA (scoring fora de escopo desta etapa)',
        },
    }


def registrar_rotas_leitura(app, factory, autorizado):
    """Só GET -- nenhuma rota de escrita."""
    from flask import jsonify

    @app.route('/api/admin/mi/relacionamento/<entidade_id>/360', methods=['GET'])
    def mi_relacionamento_360(entidade_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                resultado = relacionamento_360(cur, entidade_id)
        except Exception:
            app.logger.exception('Falha ao montar visão 360')
            return jsonify(success=False, error='Visão 360 indisponível.'), 503
        finally:
            conn.close()
        if not resultado:
            return jsonify(success=False, error='Relacionamento não encontrado.'), 404
        return jsonify(success=True, **resultado)
