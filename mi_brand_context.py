"""Brand Visual Context + Visual Memory (P5.X — Milestone 7).

Brand Context: estrutura versionada (nunca sobrescrita -- cada mudança é
uma nova versão) que Pirret usa como fonte real de identidade visual em
vez de confiar só em prompt genérico. `mi_pirret_criativo.
montar_brief_criativo` já aceita `brand_context` como parâmetro (M6);
este módulo formaliza de onde ele vem e o injeta automaticamente quando
a rota de geração não recebe um explícito.

Visual Memory NÃO é uma tabela nova: é a MESMA mi_artefatos (M1) já
existente, consultada por `status`. Um artefato aprovado
(status='aprovado') É a referência positiva; um rejeitado
(status='rejeitado') fica no histórico mas nunca é oferecido como
referência positiva. Terminologia tecnicamente correta: isto é
RECUPERAÇÃO de referência versionada -- nenhum peso de modelo é
ajustado, nenhum fine-tuning acontece, então isto nunca deve ser chamado
de "aprendizado do modelo"."""
import uuid

from psycopg2.extras import Json, RealDictCursor

from mi_artefatos import listar_artefatos

CAMPOS_BRAND_CONTEXT = (
    'logo_artefato_id', 'paleta', 'tipografia', 'garrafa', 'dimensoes', 'materiais',
    'acabamentos', 'fotografia', 'direcao_arte', 'packaging', 'social', 'restricoes',
)


def _validar_campos(campos):
    if not isinstance(campos, dict):
        raise ValueError('campos_invalidos')
    desconhecidos = set(campos) - set(CAMPOS_BRAND_CONTEXT)
    if desconhecidos:
        raise ValueError(f'campos_desconhecidos:{sorted(desconhecidos)}')
    return {c: campos[c] for c in CAMPOS_BRAND_CONTEXT if c in campos}


def registrar_versao_brand_context(factory, campos, ator):
    """Sempre INSERT, nunca UPDATE -- histórico de identidade visual
    nunca é perdido, mesma disciplina de mi_artefatos/documentos_
    empresariais."""
    campos_validos = _validar_campos(campos)
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COALESCE(MAX(versao), 0) AS ultima FROM mi_brand_context")
                proxima_versao = cur.fetchone()['ultima'] + 1
                novo_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_brand_context (id, versao, campos, criado_por) VALUES (%s,%s,%s,%s)",
                    (str(novo_id), proxima_versao, Json(campos_validos), str(ator)),
                )
                return {'success': True, 'id': str(novo_id), 'versao': proxima_versao}
    finally:
        conn.close()


def brand_context_atual(cur):
    """Última versão registrada -- None quando nenhuma foi criada ainda
    (nunca inventa um contexto de marca padrão)."""
    cur.execute("SELECT * FROM mi_brand_context ORDER BY versao DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    return {
        'id': str(row['id']), 'versao': row['versao'], 'campos': row['campos'] or {},
        'criado_por': row['criado_por'],
        'criado_em': row['criado_em'].isoformat() if row.get('criado_em') else None,
    }


def referencias_visuais_aprovadas(cur, *, artifact_type=None, limite=10):
    """Visual Memory -- reaproveita mi_artefatos.listar_artefatos (M1)
    filtrando por status='aprovado'. Nunca uma tabela/consulta nova."""
    return listar_artefatos(cur, artifact_type=artifact_type, status='aprovado', limite=limite)


def montar_brand_context_completo(cur, *, artifact_type=None, limite_referencias=10):
    """Combina o Brand Context vigente com as referências aprovadas
    (Visual Memory) num único dict pronto para
    mi_pirret_criativo.montar_brief_criativo(brand_context=...) --
    Pirret nunca decide isso sozinho."""
    atual = brand_context_atual(cur)
    referencias = referencias_visuais_aprovadas(cur, artifact_type=artifact_type, limite=limite_referencias)
    return {
        'versao': atual['versao'] if atual else None,
        **(atual['campos'] if atual else {}),
        'referencias_aprovadas': [
            {'id': r['id'], 'artifact_type': r['artifact_type'], 'metadata': r['metadata']} for r in referencias
        ],
    }


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/brand-context', methods=['GET'])
    def mi_brand_context_ler():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                atual = brand_context_atual(cur)
        except Exception:
            app.logger.exception('Falha ao ler o Brand Visual Context')
            return jsonify(success=False, error='Brand Context indisponível.'), 503
        finally:
            conn.close()
        if not atual:
            return jsonify(success=True, configurado=False, campos=None)
        return jsonify(success=True, configurado=True, **atual)

    @app.route('/api/admin/mi/brand-context', methods=['POST'])
    def mi_brand_context_registrar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        ator = str(corpo.get('ator') or '').strip()
        if not ator:
            return jsonify(success=False, error='Campo "ator" é obrigatório.'), 400
        try:
            resultado = registrar_versao_brand_context(factory, corpo.get('campos') or {}, ator)
        except ValueError as erro:
            return jsonify(success=False, error=str(erro)), 400
        return jsonify(success=True, **{k: v for k, v in resultado.items() if k != 'success'}), 201

    @app.route('/api/admin/mi/visual-memory', methods=['GET'])
    def mi_visual_memory():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                referencias = referencias_visuais_aprovadas(
                    cur, artifact_type=request.args.get('artifact_type'),
                    limite=request.args.get('limite', 10),
                )
        except Exception:
            app.logger.exception('Falha ao consultar Visual Memory')
            return jsonify(success=False, error='Visual Memory indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, referencias=referencias)
