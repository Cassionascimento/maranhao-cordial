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
from mi_image_provider import (
    MIME_SUPORTADOS_EDICAO,
    ErroImagemNaoSuportada,
    criar_provider_padrao,
    detectar_mime_imagem,
)

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

    # O `mime_type` armazenado (ex.: um gráfico CHART é 'image/svg+xml',
    # passa no filtro genérico 'image/*' acima mas nunca é editável pelo
    # provider) não é confiável para decidir se dá para editar -- deriva
    # do BYTE real, nunca do metadata, e falha local antes de gastar uma
    # chamada ao provider (essa é exatamente a causa raiz confirmada em
    # produção: um SVG chegando em /images/edits como application/octet-stream).
    if detectar_mime_imagem(imagem_base) is None:
        return {'success': False, 'motivo': 'artefato_formato_nao_suportado_para_edicao',
                'formatos_aceitos': list(MIME_SUPORTADOS_EDICAO)}

    pecas = []
    for formato in formatos:
        instrucao = f'Recomponha esta peça para o formato "{formato}"'
        if canal:
            instrucao += f', canal {canal}'
        if briefing:
            instrucao += f'. Briefing: {briefing}'
        import json
        instrucao += '. Direção premium, composição legível; preserve identidade e não invente informações de produto. Contexto: ' + json.dumps(contexto,ensure_ascii=False)
        try:
            imagens = provider.editar(imagem_base, instrucao)
        except ErroImagemNaoSuportada:
            # Rede de segurança: não deveria disparar (já validado acima
            # com os mesmos bytes), mas nunca deixa esse caso específico
            # cair no except genérico da rota.
            return {'success': False, 'motivo': 'artefato_formato_nao_suportado_para_edicao',
                    'formatos_aceitos': list(MIME_SUPORTADOS_EDICAO)}
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
    import openai

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
        except openai.APIStatusError as erro:
            # Causa conhecida e segura de expor: só o status/código que o
            # próprio provider devolveu (nunca o corpo bruto da resposta,
            # o prompt enviado ou qualquer traceback) -- nunca mais um
            # "não foi possível gerar a campanha" genérico quando dá para
            # dizer exatamente o que a OpenAI recusou.
            app.logger.exception('Provider recusou a solicitação de edição de imagem')
            return jsonify(success=False, motivo='provider_recusou_a_solicitacao',
                            provider_status=erro.status_code, provider_code=erro.code), 502
        except Exception:
            app.logger.exception('Falha ao gerar campanha social')
            return jsonify(success=False, error='Não foi possível gerar a campanha.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            motivo = resultado.get('motivo')
            status = (404 if motivo == 'artefato_base_nao_encontrado'
                      else 409 if motivo == 'artefato_base_nao_aprovado'
                      else 400 if motivo == 'nenhum_formato_valido'
                      else 422 if motivo == 'artefato_formato_nao_suportado_para_edicao' else 503)
            return jsonify(success=False, **resultado), status
        return jsonify(success=True, **resultado), 201
