"""Serviço mínimo de SKU do Maranhão Intelligence.

sku é a chave de negócio (normalizada para maiúsculas/trim) e já é
UNIQUE no schema (migration 007); nenhuma migration nova é necessária
aqui. Criação duplicada com o mesmo conteúdo é idempotente; com
conteúdo diferente é um conflito explícito, nunca uma sobrescrita
silenciosa.
"""
import re
from uuid import uuid4
from psycopg2.extras import RealDictCursor

CAMPOS = ('sku', 'produto_nome', 'categoria', 'ativo')
PADRAO_SKU = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')


def normalizar_sku(sku):
    """Formato canônico de sku (maiúsculas/trim); usado por qualquer módulo que referencie um SKU."""
    if not isinstance(sku, str) or not PADRAO_SKU.fullmatch(sku.strip()):
        raise ValueError('sku_invalido')
    return sku.strip().upper()


def sku_existe(cur, sku):
    """Confirma existência dentro da transação corrente do chamador; não abre conexão própria."""
    sku = normalizar_sku(sku)
    cur.execute("SELECT 1 FROM mi_skus WHERE sku=%s", (sku,))
    if not cur.fetchone():
        raise ValueError('sku_inexistente')
    return sku


def validar_sku(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS):
        raise ValueError('campos_invalidos')

    sku = normalizar_sku(body.get('sku'))

    nome = body.get('produto_nome')
    if not isinstance(nome, str) or not nome.strip() or len(nome.strip()) > 200:
        raise ValueError('produto_nome_invalido')
    nome = nome.strip()

    categoria = body.get('categoria')
    if categoria is not None:
        if not isinstance(categoria, str) or len(categoria) > 100:
            raise ValueError('categoria_invalida')
        categoria = categoria.strip() or None

    ativo = body.get('ativo', True)
    if not isinstance(ativo, bool):
        raise ValueError('ativo_invalido')

    return sku, {'produto_nome': nome, 'categoria': categoria, 'ativo': ativo}


def criar_sku(factory, body):
    sku, d = validar_sku(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO mi_skus(id,sku,produto_nome,categoria,ativo) VALUES(%s,%s,%s,%s,%s) "
                    "ON CONFLICT(sku) DO NOTHING RETURNING id",
                    (str(uuid4()), sku, d['produto_nome'], d['categoria'], d['ativo']),
                )
                novo = cur.fetchone()
                cur.execute(
                    "SELECT id,produto_nome,categoria,ativo FROM mi_skus WHERE sku=%s",
                    (sku,),
                )
                row = cur.fetchone()
                atual = {'produto_nome': row['produto_nome'], 'categoria': row['categoria'], 'ativo': row['ativo']}
                if atual != d:
                    return {'success': False, 'error': 'sku_ja_existe_com_outro_conteudo'}, 409
                return {'success': True, 'id': str(row['id']), 'sku': sku, 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def buscar_sku(factory, sku):
    sku = normalizar_sku(sku)
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,sku,produto_nome,categoria,ativo,criado_em FROM mi_skus WHERE sku=%s",
                (sku,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def listar_skus(factory, limite=100):
    """Só leitura -- catálogo completo, mais recente primeiro. Usado pelo
    painel/rota de leitura; nunca por um caminho de escrita."""
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,sku,produto_nome,categoria,ativo,criado_em FROM mi_skus "
                "ORDER BY criado_em DESC LIMIT %s",
                (limite,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def registrar_rotas_leitura(app, factory, autorizado):
    """Só GET -- nenhuma rota de escrita nesta etapa (criar_sku continua só
    chamável por código/teste, nunca por HTTP)."""
    from flask import jsonify

    @app.route('/api/admin/mi/skus', methods=['GET'])
    def mi_skus_listar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(success=True, skus=listar_skus(factory))
        except Exception:
            app.logger.exception('Falha ao listar SKUs')
            return jsonify(success=False, error='Catálogo indisponível.'), 503

    @app.route('/api/admin/mi/skus/<sku>', methods=['GET'])
    def mi_skus_buscar(sku):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            resultado = buscar_sku(factory, sku)
        except ValueError:
            return jsonify(success=False, error='SKU inválido.'), 400
        except Exception:
            app.logger.exception('Falha ao buscar SKU')
            return jsonify(success=False, error='Catálogo indisponível.'), 503
        if not resultado:
            return jsonify(success=False, error='SKU não encontrado.'), 404
        return jsonify(success=True, sku=resultado)
