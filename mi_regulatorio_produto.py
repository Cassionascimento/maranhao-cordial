"""Fonte regulatória canônica por SKU (P5.X — parte de Milestone 8, Label
Studio). Camada REGULATORY, deliberadamente separada da camada CREATIVE
(Pirret, mi_pirret_criativo.py): ingredientes, tabela nutricional,
alegações, registro, volume e advertências vêm SEMPRE daqui -- nunca de
um brief gerado por IA. Mesmo padrão de versionamento de
mi_brand_context.py: nunca sobrescrita, cada mudança é uma nova versão."""
import uuid

from psycopg2.extras import Json, RealDictCursor

CAMPOS_REGULATORIOS = (
    'ingredientes', 'tabela_nutricional', 'alegacoes', 'registro', 'volume', 'advertencias',
)


def _validar_campos(campos):
    if not isinstance(campos, dict):
        raise ValueError('campos_invalidos')
    desconhecidos = set(campos) - set(CAMPOS_REGULATORIOS)
    if desconhecidos:
        raise ValueError(f'campos_desconhecidos:{sorted(desconhecidos)}')
    return {c: campos[c] for c in CAMPOS_REGULATORIOS if c in campos}


def registrar_versao_regulatoria(factory, sku, campos, ator):
    """Sempre INSERT, nunca UPDATE -- histórico regulatório nunca é
    perdido. `sku` precisa ser uma string não vazia (mesmo identificador
    já usado em pedidos.sku desde P1A)."""
    sku = str(sku or '').strip()
    if not sku:
        raise ValueError('sku_obrigatorio')
    campos_validos = _validar_campos(campos)
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':mi_regulatorio:' || %s, 0))", (sku,))
                cur.execute("SELECT COALESCE(MAX(versao), 0) AS ultima FROM mi_regulatorio_produto WHERE sku=%s", (sku,))
                proxima_versao = cur.fetchone()['ultima'] + 1
                novo_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_regulatorio_produto (id, sku, versao, campos, criado_por) VALUES (%s,%s,%s,%s,%s)",
                    (str(novo_id), sku, proxima_versao, Json(campos_validos), str(ator)),
                )
                return {'success': True, 'id': str(novo_id), 'sku': sku, 'versao': proxima_versao}
    finally:
        conn.close()


def dados_regulatorios_atuais(cur, sku):
    """Última versão registrada para o SKU -- None quando nenhuma foi
    criada ainda (nunca inventa dado regulatório default)."""
    cur.execute(
        "SELECT * FROM mi_regulatorio_produto WHERE sku=%s ORDER BY versao DESC LIMIT 1", (sku,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        'id': str(row['id']), 'sku': row['sku'], 'versao': row['versao'], 'campos': row['campos'] or {},
        'criado_por': row['criado_por'],
        'criado_em': row['criado_em'].isoformat() if row.get('criado_em') else None,
    }


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/regulatorio/<sku>', methods=['GET'])
    def mi_regulatorio_ler(sku):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                atual = dados_regulatorios_atuais(cur, sku)
        except Exception:
            app.logger.exception('Falha ao ler dados regulatórios')
            return jsonify(success=False, error='Dados regulatórios indisponíveis.'), 503
        finally:
            conn.close()
        if not atual:
            return jsonify(success=True, configurado=False, sku=sku, campos=None)
        return jsonify(success=True, configurado=True, **atual)

    @app.route('/api/admin/mi/regulatorio/<sku>', methods=['POST'])
    def mi_regulatorio_registrar(sku):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        ator = str(corpo.get('ator') or '').strip()
        if not ator:
            return jsonify(success=False, error='Campo "ator" é obrigatório.'), 400
        try:
            resultado = registrar_versao_regulatoria(factory, sku, corpo.get('campos') or {}, ator)
        except ValueError as erro:
            return jsonify(success=False, error=str(erro)), 400
        return jsonify(success=True, **{k: v for k, v in resultado.items() if k != 'success'}), 201
