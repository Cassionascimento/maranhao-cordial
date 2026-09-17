"""Label Studio (P5.X — Milestone 8, parte 1).

Separação obrigatória entre CREATIVE LAYER e REGULATORY LAYER:
- CREATIVE: Pirret controla a criação visual (mi_pirret_criativo.py, M6).
- REGULATORY: ingredientes/tabela nutricional/alegações/registro/volume/
  advertências vêm SEMPRE de mi_regulatorio_produto.py -- Pirret nunca
  inventa esses campos.

Todo LABEL_CONCEPT gerado aqui nasce com
`metadata.production_status = 'CONCEITO VISUAL — NÃO APROVADO PARA
PRODUÇÃO'` e só é liberado (`regulatory_status = 'VALIDADO'`) por ação
humana explícita que confirma a existência de dados regulatórios reais
para o SKU -- nunca automaticamente, nunca por inferência do brief."""
from psycopg2.extras import RealDictCursor

from mi_artefatos import atualizar_metadata_artefato, buscar_artefato
from mi_pirret_criativo import gerar_conceitos_visuais
from mi_regulatorio_produto import dados_regulatorios_atuais

AVISO_PRODUCAO_BLOQUEADA = 'CONCEITO VISUAL — NÃO APROVADO PARA PRODUÇÃO'
RESTRICAO_REGULATORIA_PROMPT = (
    'RESTRIÇÃO OBRIGATÓRIA: este brief é para um CONCEITO VISUAL de rótulo. Nunca inclua, '
    'sugira ou mencione ingredientes, tabela nutricional, alegações de saúde, número de '
    'registro, volume ou advertências legais -- esses dados vêm exclusivamente de uma fonte '
    'regulatória canônica separada, nunca deste brief. direcao_criativa e prompt_geracao '
    'devem descrever só estética (cores, tipografia, composição, materiais).'
)


def gerar_conceito_rotulo(factory, pedido, sku, *, quantidade=3, brand_context=None,
                           meeting_id=None, decision_id=None, provider=None, cliente=None):
    """Wrapper de mi_pirret_criativo.gerar_conceitos_visuais (M6)
    especializado para rótulo: força artifact_type=LABEL_CONCEPT, injeta
    a restrição regulatória no pedido, e anota cada artefato com o aviso
    de produção bloqueada + o status regulatório real do SKU (nunca
    'validado' por padrão)."""
    if not isinstance(sku,str) or not sku.strip():
        raise ValueError('sku_obrigatorio')
    if brand_context is None:
        from mi_brand_context import montar_brand_context_completo
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                brand_context = montar_brand_context_completo(cur, artifact_type='LABEL_CONCEPT')
        except Exception:
            return {'success': False, 'motivo': 'brand_context_indisponivel'}
        finally:
            conn.close()
    pedido_com_restricao = f'{pedido}\n\n{RESTRICAO_REGULATORIA_PROMPT}'
    return gerar_conceitos_visuais(
        factory, pedido_com_restricao, artifact_type='LABEL_CONCEPT', quantidade=quantidade,
        brand_context=brand_context, meeting_id=meeting_id, decision_id=decision_id,
        provider=provider, cliente=cliente,
        metadata_extra={'sku':sku.strip(), 'production_status':AVISO_PRODUCAO_BLOQUEADA,
                        'regulatory_status':'NAO_VALIDADO'},
    )


def validar_regulatoriamente(factory, artefato_id, sku, ator):
    """Único caminho para tirar um LABEL_CONCEPT de 'NÃO APROVADO PARA
    PRODUÇÃO' -- exige que dados_regulatorios_atuais(sku) exista de
    verdade; nunca aprova por inferência ou por confiança no brief."""
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            artefato = buscar_artefato(cur, artefato_id)
            if not artefato:
                return {'success': False, 'motivo': 'artefato_nao_encontrado'}
            regulatorio = dados_regulatorios_atuais(cur, sku)
    finally:
        conn.close()
    if artefato['artifact_type'] != 'LABEL_CONCEPT' or artefato['metadata'].get('sku') != sku:
        return {'success': False, 'motivo': 'artefato_sku_incompativel'}
    if artefato['status'] != 'aprovado':
        return {'success': False, 'motivo': 'aprovacao_criativa_pendente'}
    if not regulatorio or not regulatorio['campos']:
        return {'success': False, 'motivo': 'sem_dados_regulatorios_para_este_sku'}
    resultado = atualizar_metadata_artefato(factory, artefato_id, {
        'regulatory_status': 'VALIDADO',
        'regulatorio_versao_validada': regulatorio['versao'],
        'validado_por': str(ator),
        'production_status': 'REVISÃO HUMANA REGISTRADA — NÃO AUTORIZA PRODUÇÃO OU PUBLICAÇÃO',
    }, ator=ator)
    return resultado


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/label-studio/conceitos', methods=['POST'])
    def mi_label_studio_gerar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        pedido = (corpo.get('pedido') or '').strip()
        sku = (corpo.get('sku') or '').strip()
        if not pedido or not sku:
            return jsonify(success=False, error='Campos "pedido" e "sku" são obrigatórios.'), 400
        try:
            resultado = gerar_conceito_rotulo(
                factory, pedido, sku, quantidade=corpo.get('quantidade', 3),
                brand_context=corpo.get('brand_context'), meeting_id=corpo.get('meeting_id'),
                decision_id=corpo.get('decision_id'),
            )
        except Exception:
            app.logger.exception('Falha ao gerar conceito de rótulo')
            return jsonify(success=False, error='Não foi possível gerar o conceito.'), 503
        sucesso = resultado.pop('success', False)
        status = 201 if sucesso else 503
        return jsonify(success=sucesso, **resultado), status

    @app.route('/api/admin/mi/label-studio/<artefato_id>/validar-regulatorio', methods=['POST'])
    def mi_label_studio_validar(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        sku = (corpo.get('sku') or '').strip()
        ator = (corpo.get('ator') or '').strip()
        if not sku or not ator:
            return jsonify(success=False, error='Campos "sku" e "ator" são obrigatórios.'), 400
        try:
            resultado = validar_regulatoriamente(factory, artefato_id, sku, ator)
        except Exception:
            app.logger.exception('Falha ao validar regulatoriamente o conceito de rótulo')
            return jsonify(success=False, error='Não foi possível validar.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            status = (404 if resultado.get('motivo') == 'artefato_nao_encontrado'
                      else 422 if resultado.get('motivo') == 'sem_dados_regulatorios_para_este_sku' else 503)
            return jsonify(success=False, **resultado), status
        return jsonify(success=True, **resultado), 200
