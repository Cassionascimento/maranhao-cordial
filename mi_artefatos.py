"""Contrato canônico de artefatos executivos/criativos (P5.X — Milestone 1).

Não duplica nenhuma tabela/serviço P0-P5 (ver P5X_AUDIT.md): reaproveita o
padrão de versionamento de `documentos_empresariais` (status + ponteiro
para a versão anterior) e o único storage persistente já comprovado em
produção (Postgres BYTEA, via mi_artefato_storage.PostgresBlobStorage).

Um artefato nasce em `gerado` e só vira `aprovado`/`rejeitado` por ação
humana explícita (mesma disciplina de mi_decisao.avancar_estado_fila) --
nenhuma rota aqui publica nada externamente (M13 continua intocado).

Este módulo só PERSISTE e VERSIONA artefatos -- nunca gera slide, gráfico
ou imagem. Presentation Engine (M4), Chart Engine (M5) e Pirret/Image
Generation Provider (M6) chamam `registrar_artefato` com os bytes já
prontos.
"""
import uuid

from psycopg2.extras import Json, RealDictCursor

from mi_artefato_storage import PostgresBlobStorage

TIPOS_ARTEFATO = (
    'PRESENTATION', 'CHART', 'IMAGE', 'LABEL_CONCEPT', 'SOCIAL_CREATIVE',
    'PACKAGING_CONCEPT', 'INFOGRAPHIC', 'REPORT',
)
ESTADOS_ARTEFATO = ('gerado', 'aprovado', 'rejeitado', 'historico')
TRANSICOES_PERMITIDAS_ARTEFATO = {
    'gerado': ('aprovado', 'rejeitado'),
    'aprovado': ('historico',),
    'rejeitado': ('historico',),
    'historico': (),
}


def registrar_artefato(factory, *, artifact_type, conteudo, mime_type, source_type=None,
                        source_id=None, meeting_id=None, agent_id=None, decision_id=None,
                        parent_artifact_id=None, thumbnail_uri=None, metadata=None):
    """Ponto único de escrita de um artefato novo. `conteudo` são os bytes
    reais já gerados por quem chama. Se `parent_artifact_id` for
    informado, `version` = versão do pai + 1 -- nunca sobrescreve a
    versão anterior, sempre encadeia (lineage A -> A2 -> A3)."""
    if artifact_type not in TIPOS_ARTEFATO:
        raise ValueError('artifact_type_invalido')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                versao = 1
                if parent_artifact_id:
                    cur.execute(
                        "SELECT version FROM mi_artefatos WHERE id=%s FOR UPDATE",
                        (str(parent_artifact_id),),
                    )
                    pai = cur.fetchone()
                    if not pai:
                        return {'success': False, 'motivo': 'artefato_pai_nao_encontrado'}
                    versao = pai['version'] + 1
                storage = PostgresBlobStorage(cur)
                storage_uri = storage.salvar(conteudo, mime_type)
                artefato_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_artefatos (id, artifact_type, source_type, source_id, meeting_id, "
                    "agent_id, decision_id, parent_artifact_id, version, status, storage_uri, "
                    "thumbnail_uri, mime_type, metadata) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'gerado',%s,%s,%s,%s)",
                    (str(artefato_id), artifact_type, source_type, source_id, meeting_id, agent_id,
                     decision_id, str(parent_artifact_id) if parent_artifact_id else None, versao,
                     storage_uri, thumbnail_uri, mime_type, Json(metadata or {})),
                )
                return {
                    'success': True, 'id': str(artefato_id), 'version': versao,
                    'storage_uri': storage_uri, 'status': 'gerado',
                }
    finally:
        conn.close()


def avancar_estado_artefato(factory, artefato_id, novo_estado, ator, motivo=None):
    """Transição controlada de estado -- nunca reabre um artefato já
    virado histórico, nunca aprova/rejeita sem ator identificado."""
    if novo_estado not in ESTADOS_ARTEFATO:
        raise ValueError('estado_invalido')
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, status FROM mi_artefatos WHERE id=%s FOR UPDATE",
                    (str(artefato_id),),
                )
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'motivo': 'artefato_nao_encontrado'}
                atual = row['status']
                if novo_estado not in TRANSICOES_PERMITIDAS_ARTEFATO.get(atual, ()):
                    return {
                        'success': False, 'motivo': 'transicao_nao_permitida',
                        'de': atual, 'para': novo_estado,
                    }
                aprovado_em_sql = "NOW()" if novo_estado == 'aprovado' else "NULL"
                cur.execute(
                    "UPDATE mi_artefatos SET status=%s, approved_at=" + aprovado_em_sql + " WHERE id=%s",
                    (novo_estado, str(artefato_id)),
                )
                cur.execute(
                    "INSERT INTO mi_artefatos_auditoria (artefato_id, estado_anterior, estado_novo, ator, motivo) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (str(artefato_id), atual, novo_estado, str(ator), motivo),
                )
                return {'success': True, 'de': atual, 'para': novo_estado}
    finally:
        conn.close()


def aprovar_artefato(factory, artefato_id, ator):
    return avancar_estado_artefato(factory, artefato_id, 'aprovado', ator)


def rejeitar_artefato(factory, artefato_id, ator, motivo=None):
    return avancar_estado_artefato(factory, artefato_id, 'rejeitado', ator, motivo=motivo)


def atualizar_metadata_artefato(factory, artefato_id, patch, *, ator="sistema"):
    """Mescla `patch` na metadata existente -- nunca remove uma chave já
    gravada, nunca toca em storage_uri/conteudo/status. Usado por M8
    (Label Studio) para anotar `regulatory_status` sem reabrir o
    contrato de versionamento/aprovação criativa (que continua sendo
    o único dono de `status`)."""
    if not isinstance(patch, dict):
        raise ValueError('patch_invalido')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT metadata FROM mi_artefatos WHERE id=%s FOR UPDATE", (str(artefato_id),))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'motivo': 'artefato_nao_encontrado'}
                nova_metadata = {**(row['metadata'] or {}), **patch}
                cur.execute(
                    "UPDATE mi_artefatos SET metadata=%s WHERE id=%s",
                    (Json(nova_metadata), str(artefato_id)),
                )
                if nova_metadata != (row['metadata'] or {}):
                    cur.execute("SELECT id, status FROM mi_artefatos WHERE id=%s FOR UPDATE", (str(artefato_id),))
                    estado = cur.fetchone()['status']
                    import json
                    cur.execute(
                        "INSERT INTO mi_artefatos_auditoria (artefato_id, estado_anterior, estado_novo, ator, motivo) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (str(artefato_id), estado, estado, str(ator), json.dumps(
                            {'evento':'metadata_atualizada','anterior':row['metadata'] or {},'nova':nova_metadata}, ensure_ascii=False)),
                    )
                return {'success': True, 'metadata': nova_metadata}
    finally:
        conn.close()


_CAMPOS = (
    'id', 'artifact_type', 'source_type', 'source_id', 'meeting_id', 'agent_id',
    'decision_id', 'parent_artifact_id', 'version', 'status', 'storage_uri',
    'thumbnail_uri', 'mime_type', 'metadata', 'created_at', 'approved_at',
)


def _serializar(row):
    return {
        'id': str(row['id']),
        'artifact_type': row['artifact_type'],
        'source_type': row['source_type'],
        'source_id': row['source_id'],
        'meeting_id': row['meeting_id'],
        'agent_id': row['agent_id'],
        'decision_id': row['decision_id'],
        'parent_artifact_id': str(row['parent_artifact_id']) if row['parent_artifact_id'] else None,
        'version': row['version'],
        'status': row['status'],
        'storage_uri': row['storage_uri'],
        'thumbnail_uri': row['thumbnail_uri'],
        'mime_type': row['mime_type'],
        'metadata': row['metadata'] or {},
        'created_at': row['created_at'].isoformat() if row.get('created_at') else None,
        'approved_at': row['approved_at'].isoformat() if row.get('approved_at') else None,
    }


def buscar_artefato(cur, artefato_id):
    cur.execute("SELECT * FROM mi_artefatos WHERE id=%s", (str(artefato_id),))
    row = cur.fetchone()
    return _serializar(row) if row else None


def listar_artefatos(cur, *, meeting_id=None, agent_id=None, artifact_type=None, status=None, limite=50):
    limite = max(1, min(int(limite), 200))
    condicoes, params = [], []
    if meeting_id:
        condicoes.append("meeting_id=%s")
        params.append(meeting_id)
    if agent_id:
        condicoes.append("agent_id=%s")
        params.append(agent_id)
    if artifact_type:
        condicoes.append("artifact_type=%s")
        params.append(artifact_type)
    if status:
        condicoes.append("status=%s")
        params.append(status)
    where = (" WHERE " + " AND ".join(condicoes)) if condicoes else ""
    params.append(limite)
    cur.execute(f"SELECT * FROM mi_artefatos{where} ORDER BY created_at DESC LIMIT %s", params)
    return [_serializar(r) for r in cur.fetchall()]


def linhagem_artefato(cur, artefato_id):
    """Caminha parent_artifact_id até a raiz e devolve a cadeia raiz ->
    atual (ex.: Rótulo A -> A2 -> A3). Nunca inventa um elo que não
    exista; para no primeiro id sem correspondência no banco."""
    cadeia = []
    atual_id = str(artefato_id)
    visitados = set()
    while atual_id and atual_id not in visitados:
        visitados.add(atual_id)
        artefato = buscar_artefato(cur, atual_id)
        if not artefato:
            break
        cadeia.append(artefato)
        atual_id = artefato['parent_artifact_id']
    cadeia.reverse()
    return cadeia


def registrar_rotas(app, factory, autorizado):
    from flask import Response, jsonify, request

    @app.route('/api/admin/mi/artefatos', methods=['GET'])
    def mi_artefatos_listar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                itens = listar_artefatos(
                    cur, meeting_id=request.args.get('meeting_id'), agent_id=request.args.get('agent_id'),
                    artifact_type=request.args.get('artifact_type'), status=request.args.get('status'),
                    limite=request.args.get('limite', 50),
                )
        except Exception:
            app.logger.exception('Falha ao listar artefatos')
            return jsonify(success=False, error='Listagem de artefatos indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, artefatos=itens)

    @app.route('/api/admin/mi/artefatos/<artefato_id>', methods=['GET'])
    def mi_artefatos_detalhe(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                artefato = buscar_artefato(cur, artefato_id)
        except Exception:
            app.logger.exception('Falha ao buscar artefato')
            return jsonify(success=False, error='Consulta de artefato indisponível.'), 503
        finally:
            conn.close()
        if not artefato:
            return jsonify(success=False, error='Artefato não encontrado.'), 404
        return jsonify(success=True, **artefato)

    @app.route('/api/admin/mi/artefatos/<artefato_id>/linhagem', methods=['GET'])
    def mi_artefatos_linhagem(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                cadeia = linhagem_artefato(cur, artefato_id)
        except Exception:
            app.logger.exception('Falha ao montar linhagem do artefato')
            return jsonify(success=False, error='Linhagem indisponível.'), 503
        finally:
            conn.close()
        if not cadeia:
            return jsonify(success=False, error='Artefato não encontrado.'), 404
        return jsonify(success=True, linhagem=cadeia)

    @app.route('/api/admin/mi/artefatos/<artefato_id>/download', methods=['GET'])
    def mi_artefatos_download(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                artefato = buscar_artefato(cur, artefato_id)
                if not artefato:
                    return jsonify(success=False, error='Artefato não encontrado.'), 404
                conteudo = PostgresBlobStorage(cur).ler(artefato['storage_uri'])
        except Exception:
            app.logger.exception('Falha ao ler conteúdo do artefato')
            return jsonify(success=False, error='Download indisponível.'), 503
        finally:
            conn.close()
        if conteudo is None:
            return jsonify(success=False, error='Conteúdo do artefato não encontrado no storage.'), 404
        return Response(conteudo, mimetype=artefato['mime_type'],headers={
            'Content-Disposition':'attachment', 'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"sandbox; default-src 'none'", 'Cache-Control':'no-store'})

    @app.route('/api/admin/mi/artefatos/<artefato_id>/aprovar', methods=['POST'])
    def mi_artefatos_aprovar(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        ator = str(corpo.get('ator') or '').strip()
        if not ator:
            return jsonify(success=False, error='Campo "ator" é obrigatório para aprovar um artefato.'), 400
        resultado = aprovar_artefato(factory, artefato_id, ator=ator)
        sucesso = resultado.pop('success', False)
        return jsonify(success=sucesso, **resultado), (200 if sucesso else 409)

    @app.route('/api/admin/mi/artefatos/<artefato_id>/rejeitar', methods=['POST'])
    def mi_artefatos_rejeitar(artefato_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        ator = str(corpo.get('ator') or '').strip()
        if not ator:
            return jsonify(success=False, error='Campo "ator" é obrigatório para rejeitar um artefato.'), 400
        resultado = rejeitar_artefato(factory, artefato_id, ator=ator, motivo=corpo.get('motivo'))
        sucesso = resultado.pop('success', False)
        return jsonify(success=sucesso, **resultado), (200 if sucesso else 409)

    @app.route('/api/admin/mi/artefatos/<artefato_id>/auditoria', methods=['GET'])
    def mi_artefatos_auditoria(artefato_id):
        if not autorizado():
            return jsonify(success=False,error='Não autorizado.'),401
        conn = None
        try:
            conn=factory()
            conn.set_session(readonly=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM mi_artefatos_auditoria WHERE artefato_id=%s ORDER BY criado_em DESC LIMIT 100",(artefato_id,))
                rows=[dict(r) for r in cur.fetchall()]
            return jsonify(success=True,auditoria=rows)
        except Exception:
            app.logger.exception('Auditoria indisponível')
            return jsonify(success=False,error='Auditoria indisponível.'),503
        finally:
            if conn is not None: conn.close()
