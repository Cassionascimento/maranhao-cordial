"""P2A -- Unified Signal Model.

Normaliza o payload do Customer/Partner 360 (mi_relacionamento_360.py) numa
lista plana de sinais com forma comum: type/source/timestamp/subject/
object/strength/confidence/evidence. Não é um substituto de mi_sinais.py
(aquele é o barramento de observabilidade/auditoria de eventos de negócio,
append-only, já em produção) -- este módulo é uma camada de LEITURA
derivada, calculada sob demanda a partir do 360, para alimentar score/
segmentação/oportunidade (P2B-P2D). Nenhuma escrita, nenhuma chamada
externa, nenhum sinal inventado: um sinal só existe aqui se já existir uma
linha real em alguma tabela consumida pelo 360.

`confidence` reaproveita a mesma classificação DIRECT/INFERRED/UNKNOWN já
usada em `mi_relacionamento_360.data_quality`, mapeada para um número fixo
e documentado (não é probabilidade estatística, é peso determinístico):
DIRECT=1.0 (vem de FK), INFERRED=0.6 (vem de correspondência de texto),
UNKNOWN=0.0 (sem evidência)."""
from datetime import datetime, timezone

PESO_CONFIANCA = {'DIRECT': 1.0, 'INFERRED': 0.6, 'UNKNOWN': 0.0}
_INTERESSE_ALTO = ('alto', 'quente', 'interesse_alto')


def _sinal(tipo, fonte, timestamp, subject, obj, strength, confidence, evidence):
    return {
        'type': tipo, 'source': fonte, 'timestamp': timestamp, 'subject': subject, 'object': obj,
        'strength': strength, 'confidence': confidence, 'evidence': evidence,
    }


def extrair_sinais(visao_360, agora=None):
    """`visao_360` é o retorno de mi_relacionamento_360.relacionamento_360()
    -- este módulo nunca consulta o banco diretamente, só interpreta o que
    já foi lido. Devolve lista ordenada por timestamp desc (mais recente
    primeiro); sinais sem timestamp (ex. origem) vão ao final."""
    agora = agora or datetime.now(timezone.utc)
    sinais = []
    lead = visao_360.get('identity', {}).get('pessoa')
    estab = visao_360.get('organization')
    subject = (lead or {}).get('id') or (estab or {}).get('id')
    dq = visao_360.get('data_quality', {})

    for canal in (visao_360.get('behavior', {}).get('interacoes_omnichannel') or []):
        strength = canal.get('interesse') if (canal.get('interesse') or '').lower() in _INTERESSE_ALTO else None
        sinais.append(_sinal(
            'interaction', 'interacoes_omnichannel', canal.get('criado_em'), subject, canal.get('canal'),
            strength, PESO_CONFIANCA['DIRECT'],
            [f"canal={canal.get('canal')}", f"tipo={canal.get('tipo_interacao')}",
             f"classificacao={canal.get('classificacao')}"],
        ))

    for compra in (visao_360.get('commercial', {}).get('compras_relacionamento') or []):
        sinais.append(_sinal(
            'order', 'compras_relacionamento', compra.get('comprado_em'), subject, None,
            compra.get('valor_centavos'), PESO_CONFIANCA['DIRECT'],
            [f"referencia={compra.get('referencia_externa')}", f"valor_centavos={compra.get('valor_centavos')}"],
        ))

    for pedido in (visao_360.get('commercial', {}).get('pedidos_vinculados') or []):
        sinais.append(_sinal(
            'order_product', 'pedidos', pedido.get('criado_em'), subject, pedido.get('sku'),
            pedido.get('valor_centavos'), PESO_CONFIANCA['INFERRED'],
            [f"codigo={pedido.get('codigo')}", f"sku={pedido.get('sku')}"],
        ))

    proxima_recompra = visao_360.get('commercial', {}).get('proxima_recompra_em')
    if proxima_recompra:
        vencida = proxima_recompra <= agora
        sinais.append(_sinal(
            'reorder_due' if vencida else 'reorder_scheduled', 'leads_crm.proxima_recompra_em',
            proxima_recompra, subject, None, None, PESO_CONFIANCA['DIRECT'],
            [f"proxima_recompra_em={proxima_recompra.isoformat()}"],
        ))

    for proposta in (visao_360.get('commercial', {}).get('propostas') or []):
        sinais.append(_sinal(
            'proposal', 'acoes_comerciais_propostas', proposta.get('criado_em'), subject, proposta.get('tipo'),
            None, PESO_CONFIANCA['INFERRED'],
            [f"status={proposta.get('status')}", f"tipo={proposta.get('tipo')}"],
        ))

    estagio = visao_360.get('commercial', {}).get('estagio')
    if estagio:
        sinais.append(_sinal(
            'pipeline_stage', 'leads_crm.estagio', None, subject, estagio, None, PESO_CONFIANCA['DIRECT'],
            [f"estagio={estagio}"],
        ))

    formularios = visao_360.get('behavior', {}).get('formularios', {})
    for tipo_form, lista in (('cadastro_profissional', formularios.get('cadastro_profissional') or []),
                              ('degustacao', formularios.get('degustacao') or [])):
        for item in lista:
            sinais.append(_sinal(
                'form_submission', tipo_form, item.get('criado_em'), subject, None, None,
                PESO_CONFIANCA['INFERRED'], [f"tipo={tipo_form}", f"status={item.get('status')}"],
            ))

    for evento in (visao_360.get('behavior', {}).get('eventos_do_estabelecimento') or []):
        sinais.append(_sinal(
            'qr_event', 'mi_eventos', evento.get('criado_em'), (estab or {}).get('id'), evento.get('sku'),
            None, PESO_CONFIANCA['INFERRED'],
            [f"tipo_evento={evento.get('tipo_evento')}", f"canal={evento.get('canal')}"],
        ))

    for produto in (visao_360.get('products') or []):
        sinais.append(_sinal(
            'product_affinity', 'pedidos_agrupados_por_sku', produto.get('ultima_compra'), subject,
            produto.get('sku'), produto.get('quantidade_pedidos'), PESO_CONFIANCA['INFERRED'],
            [f"quantidade_pedidos={produto.get('quantidade_pedidos')}", f"recompra={produto.get('recompra')}"],
        ))

    if estab:
        sinais.append(_sinal(
            'establishment_link', 'mi_estabelecimentos', estab.get('criado_em'), subject, estab.get('id'),
            None, PESO_CONFIANCA['DIRECT'] if dq.get('pessoa_resolvida') and estab.get('lead_id') else PESO_CONFIANCA['UNKNOWN'],
            [f"estabelecimento_id={estab.get('id')}", f"tipo={estab.get('tipo')}"],
        ))

    origem = visao_360.get('identity', {}).get('origem')
    if origem:
        sinais.append(_sinal(
            'origin', 'leads_crm.origem', None, subject, origem, None, PESO_CONFIANCA['DIRECT'],
            [f"origem={origem}"],
        ))

    geografia = visao_360.get('geography') or {}
    if geografia.get('cidade') or geografia.get('uf'):
        sinais.append(_sinal(
            'geography', 'leads_crm/mi_estabelecimentos', None, subject,
            f"{geografia.get('cidade')}/{geografia.get('uf')}", None, PESO_CONFIANCA['DIRECT'],
            [f"cidade={geografia.get('cidade')}", f"uf={geografia.get('uf')}"],
        ))

    sinais.sort(key=lambda s: s['timestamp'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return sinais
