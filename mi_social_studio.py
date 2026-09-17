"""Social Creative Studio (P5.X — Milestone 8, parte 2).

Pirret transforma um artefato JÁ APROVADO em conjunto de peças por
formato -- key visual, feed, story, vertical, banner, produto isolado --
sempre reaproveitando produto/brand context/briefing/canal já existentes,
nunca redimensionando cegamente a mesma imagem: cada formato pede uma
recomposição própria ao ImageGenerationProvider (`editar`), igual ao
refinamento de M6, mas gerando VÁRIAS peças relacionadas em vez de uma
substituição.

Exige que o artefato-base esteja `aprovado` -- reforça o princípio
"nada é publicado/expandido sem aprovação humana" também para
campanhas derivadas."""
from psycopg2.extras import RealDictCursor

from mi_artefato_storage import PostgresBlobStorage
from mi_artefatos import buscar_artefato, registrar_artefato
from mi_image_provider import criar_provider_padrao

FORMATOS_SOCIAL = ('key_visual', 'feed', 'story', 'vertical', 'banner', 'produto_isolado', 'mockup')


def gerar_campanha_a_partir_de_artefato(factory, artefato_base_id, formatos, *, canal=None,
                                         briefing=None, provider=None):
    """Uma peça por formato pedido, todas com parent_artifact_id=
    artefato_base_id (lineage explícita: a campanha inteira remonta ao
    conceito aprovado que a originou)."""
    if not isinstance(formatos,list) or len(formatos)>7 or any(f not in FORMATOS_SOCIAL for f in formatos):
        return {'success':False, 'motivo':'nenhum_formato_valido'}
    formatos = list(dict.fromkeys(formatos))
    if not formatos:
        return {'success': False, 'motivo': 'nenhum_formato_valido'}

    provider = provider or criar_provider_padrao()
    if not provider.disponivel():
        return {'success': False, 'motivo': 'image_provider_nao_configurado'}

    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            artefato_base = buscar_artefato(cur, artefato_base_id)
            if not artefato_base:
                return {'success': False, 'motivo': 'artefato_base_nao_encontrado'}
            if artefato_base['status'] != 'aprovado':
                return {'success': False, 'motivo': 'artefato_base_nao_aprovado',
                        'status_atual': artefato_base['status']}
            if not artefato_base['mime_type'].startswith('image/'):
                return {'success':False, 'motivo':'artefato_nao_visual'}
            from mi_brand_context import montar_brand_context_completo
            contexto = montar_brand_context_completo(cur, artifact_type=artefato_base['artifact_type'])
            imagem_base = PostgresBlobStorage(cur).ler(artefato_base['storage_uri'])
    finally:
        conn.close()

    pecas = []
    for formato in formatos:
        instrucao = f'Recomponha esta peça para o formato "{formato}"'
        if canal:
            instrucao += f', canal {canal}'
        if briefing:
            instrucao += f'. Briefing: {briefing}'
        import json
        instrucao += '. Direção premium, composição legível; preserve identidade e não invente informações de produto. Contexto: ' + json.dumps(contexto,ensure_ascii=False)
        imagens = provider.editar(imagem_base, instrucao)
        for imagem in imagens:
            resultado = registrar_artefato(
                factory, artifact_type='SOCIAL_CREATIVE', conteudo=imagem, mime_type='image/png',
                source_type='social_studio', agent_id='pirret', parent_artifact_id=artefato_base_id,
                metadata={'formato': formato, 'canal': canal, 'briefing': briefing,
                          'artefato_base_id': artefato_base_id, 'brand_context':contexto,
                          'confidence':'SYNTHETIC_TEST' if getattr(provider,'sintetico',False) else 'INFERRED'},
            )
            pecas.append(resultado)
    return {'success':bool(pecas) and all(p.get('success') for p in pecas),
            'motivo':None if pecas else 'provider_sem_imagem', 'artefato_base_id': artefato_base_id, 'pecas': pecas}


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/social-studio/campanha/<artefato_base_id>', methods=['POST'])
    def mi_social_studio_gerar_campanha(artefato_base_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        formatos = corpo.get('formatos') or []
        try:
            resultado = gerar_campanha_a_partir_de_artefato(
                factory, artefato_base_id, formatos, canal=corpo.get('canal'), briefing=corpo.get('briefing'),
            )
        except Exception:
            app.logger.exception('Falha ao gerar campanha social')
            return jsonify(success=False, error='Não foi possível gerar a campanha.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            status = (404 if resultado.get('motivo') == 'artefato_base_nao_encontrado'
                      else 409 if resultado.get('motivo') == 'artefato_base_nao_aprovado'
                      else 400 if resultado.get('motivo') == 'nenhum_formato_valido' else 503)
            return jsonify(success=False, **resultado), status
        return jsonify(success=True, **resultado), 201
