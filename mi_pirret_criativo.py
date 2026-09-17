"""Pirret multimodal (P5.X — Milestone 6).

Pirret continua sendo o agente de Marketing do Conselho (mi_conselho.py:
AGENTES['pirret']) -- este módulo NÃO cria um agente novo, só dá a ele a
capacidade de orquestrar produção visual real. "Pires" mencionado em
ordens anteriores foi confirmado como erro de nomenclatura (ver
P5X_AUDIT.md item 8): o nome correto é sempre Pirret.

Fluxo (nunca alterado, sempre nesta ordem):
brief (usuário) -> creative brief estruturado (1 chamada de LLM, mesmo
cliente/modelo do Conselho) -> ImageGenerationProvider (M6) -> imagem
real -> mi_artefatos (M1, persistência/versionamento) -> aprovação
humana (M1 já garante isso -- artefato nasce 'gerado').

Pirret nunca gera pixel ele mesmo: a geração é sempre delegada a um
ImageGenerationProvider injetável, nunca a um fornecedor fixo."""
import json

from openai import OpenAI
from psycopg2.extras import RealDictCursor

from mi_artefato_storage import PostgresBlobStorage
from mi_artefatos import buscar_artefato, registrar_artefato
from mi_conselho_executor import MODELO_PADRAO
from mi_image_provider import criar_provider_padrao

TIMEOUT_SEGUNDOS_BRIEF = 20
MAX_OUTPUT_TOKENS_BRIEF = 400

_SCHEMA_BRIEF = {
    'type': 'object',
    'properties': {
        'objetivo_comercial': {'type': 'string'},
        'publico': {'type': 'string'},
        'posicionamento': {'type': 'string'},
        'mensagem': {'type': 'string'},
        'direcao_criativa': {'type': 'string'},
        'prompt_geracao': {'type': 'string'},
    },
    'required': ['objetivo_comercial', 'publico', 'posicionamento', 'mensagem',
                 'direcao_criativa', 'prompt_geracao'],
    'additionalProperties': False,
}


def montar_brief_criativo(pedido, brand_context=None, cliente=None):
    """Única chamada de LLM desta etapa: transforma um pedido em
    linguagem natural num brief estruturado (objetivo -> público ->
    posicionamento -> mensagem -> direção -> prompt de geração). Nunca
    gera pixel aqui. Ao contrário do Secretário Executivo (M3), um
    pedido criativo em linguagem livre não tem fallback determinístico
    razoável -- falha de rede/modelo aqui propaga a exceção, nunca
    inventa um brief."""
    contexto = {'pedido': pedido, 'brand_context': brand_context or {}}
    prompt = (
        'Você é Pirret, o diretor de marketing do Conselho da Maranhão Cordial. A partir '
        'do pedido e do contexto de marca (brand_context) abaixo, monte um brief criativo '
        'estruturado -- nunca invente um dado de marca que não esteja em brand_context; se '
        'brand_context estiver vazio, deixe a direção criativa genérica e diga isso na '
        'direcao_criativa.\n\n' + json.dumps(contexto, ensure_ascii=False, default=str)
    )
    cliente = cliente or OpenAI(timeout=TIMEOUT_SEGUNDOS_BRIEF, max_retries=0)
    resposta = cliente.responses.create(
        model=MODELO_PADRAO,
        input=prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS_BRIEF,
        store=False,
        reasoning={'effort': 'low'},
        text={'format': {'type': 'json_schema', 'name': 'brief_pirret', 'strict': True, 'schema': _SCHEMA_BRIEF}},
    )
    brief = json.loads(resposta.output_text or '')
    if not isinstance(brief, dict) or not (brief.get('prompt_geracao') or '').strip():
        raise ValueError('brief_invalido')
    return brief


def gerar_conceitos_visuais(factory, pedido, *, artifact_type, quantidade=3, brand_context=None,
                             meeting_id=None, decision_id=None, provider=None, cliente=None, metadata_extra=None):
    """Fluxo completo: brief -> N gerações -> N artefatos persistidos
    (A/B/C, cada um raiz de sua própria lineage), todos com
    agent_id='pirret'. Sem provider configurado, devolve motivo
    explícito -- nunca finge que gerou uma imagem."""
    provider = provider or criar_provider_padrao()
    if not provider.disponivel():
        return {'success': False, 'motivo': 'image_provider_nao_configurado', 'mensagem': provider.MENSAGEM
                if hasattr(provider, 'MENSAGEM') else 'IMAGE PROVIDER — NOT CONFIGURED'}
    if not isinstance(quantidade, int) or isinstance(quantidade, bool) or not 1 <= quantidade <= 3:
        raise ValueError('quantidade_deve_ser_entre_1_e_3')
    brief = montar_brief_criativo(pedido, brand_context=brand_context, cliente=cliente)
    artefatos_gerados = []
    for _ in range(max(1, int(quantidade))):
        for imagem in provider.gerar(brief['prompt_geracao']):
            resultado = registrar_artefato(
                factory, artifact_type=artifact_type, conteudo=imagem, mime_type='image/png',
                source_type='pirret_brief', agent_id='pirret', meeting_id=meeting_id, decision_id=decision_id,
                metadata={**(metadata_extra or {}), 'brief': brief, 'pedido': pedido, 'brand_context': brand_context},
            )
            artefatos_gerados.append(resultado)
    return {'success': bool(artefatos_gerados) and all(a.get('success') for a in artefatos_gerados),
            'motivo': None if artefatos_gerados else 'provider_sem_imagem', 'brief': brief, 'artefatos': artefatos_gerados}


def refinar_conceito_visual(factory, artefato_pai_id, instrucao, *, provider=None):
    """"Prefiro B. Deixe mais sofisticado." -> B2, com
    parent_artifact_id=B. Nunca reescreve B: mi_artefatos (M1) já garante
    que uma nova versão sempre encadeia, nunca sobrescreve."""
    provider = provider or criar_provider_padrao()
    if not provider.disponivel():
        return {'success': False, 'motivo': 'image_provider_nao_configurado'}
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            artefato_pai = buscar_artefato(cur, artefato_pai_id)
            if not artefato_pai:
                return {'success': False, 'motivo': 'artefato_pai_nao_encontrado'}
            imagem_base = PostgresBlobStorage(cur).ler(artefato_pai['storage_uri'])
    finally:
        conn.close()
    if not artefato_pai['mime_type'].startswith('image/'):
        return {'success': False, 'motivo': 'artefato_nao_visual'}
    imagens = provider.editar(imagem_base, instrucao)
    if not imagens:
        return {'success': False, 'motivo': 'provider_sem_imagem'}
    return registrar_artefato(
        factory, artifact_type=artefato_pai['artifact_type'], conteudo=imagens[0], mime_type='image/png',
        source_type='pirret_refinamento', agent_id='pirret', parent_artifact_id=artefato_pai_id,
        metadata={**artefato_pai['metadata'], 'instrucao_refinamento': instrucao,
                  **({'regulatory_status':'NAO_VALIDADO', 'production_status':'CONCEITO VISUAL — NÃO APROVADO PARA PRODUÇÃO'}
                     if artefato_pai['artifact_type']=='LABEL_CONCEPT' else {})},
    )


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/pirret/provider-status', methods=['GET'])
    def mi_pirret_provider_status():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        provider = criar_provider_padrao()
        return jsonify(success=True, disponivel=provider.disponivel(),
                        provider=type(provider).__name__)

    @app.route('/api/admin/mi/pirret/conceitos', methods=['POST'])
    def mi_pirret_gerar_conceitos():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        pedido = (corpo.get('pedido') or '').strip()
        if not pedido:
            return jsonify(success=False, error='Campo "pedido" é obrigatório.'), 400
        artifact_type = corpo.get('artifact_type') or 'LABEL_CONCEPT'
        # M7: sem brand_context explícito no pedido, carrega o Brand
        # Visual Context + Visual Memory vigentes -- Pirret nunca confia
        # só em prompt genérico quando há identidade de marca registrada.
        brand_context = corpo.get('brand_context')
        if brand_context is None:
            try:
                from mi_brand_context import montar_brand_context_completo
                conn = factory()
                try:
                    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        brand_context = montar_brand_context_completo(cur, artifact_type=artifact_type)
                finally:
                    conn.close()
            except Exception:
                app.logger.exception('Falha ao carregar Brand Context -- seguindo sem ele')
                brand_context = None
        try:
            resultado = gerar_conceitos_visuais(
                factory, pedido, artifact_type=artifact_type, quantidade=corpo.get('quantidade', 3),
                brand_context=brand_context, meeting_id=corpo.get('meeting_id'),
                decision_id=corpo.get('decision_id'),
            )
        except ValueError as erro:
            return jsonify(success=False, error=str(erro)), 400
        except Exception:
            app.logger.exception('Falha ao gerar conceitos visuais do Pirret')
            return jsonify(success=False, error='Não foi possível gerar os conceitos.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            status = 503 if resultado.get('motivo') == 'image_provider_nao_configurado' else 400
            return jsonify(success=False, **resultado), status
        return jsonify(success=True, **resultado), 201

    @app.route('/api/admin/mi/pirret/refinar/<artefato_id>', methods=['POST'])
    def mi_pirret_refinar(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        instrucao = (corpo.get('instrucao') or '').strip()
        if not instrucao:
            return jsonify(success=False, error='Campo "instrucao" é obrigatório.'), 400
        try:
            resultado = refinar_conceito_visual(factory, artefato_id, instrucao)
        except Exception:
            app.logger.exception('Falha ao refinar conceito visual do Pirret')
            return jsonify(success=False, error='Não foi possível refinar o conceito.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            status = (404 if resultado.get('motivo') == 'artefato_pai_nao_encontrado'
                      else 503 if resultado.get('motivo') == 'image_provider_nao_configurado' else 503)
            return jsonify(success=False, **resultado), status
        return jsonify(success=True, **resultado), 201
