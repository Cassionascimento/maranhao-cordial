"""Serviço mínimo de lote do Maranhão Intelligence: SKU → LOTE.

codigo_lote é único por sku, não globalmente: dois produtos podem usar o
mesmo código de lote em convenções de origem diferentes. sku é validado
por existência na mesma transação, reaproveitando mi_skus.sku_existe (sem
duplicar a checagem). Criação repetida com o mesmo conteúdo é idempotente;
com conteúdo divergente é conflito explícito, nunca sobrescrita silenciosa.
"""
import math
import re
from datetime import date
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor
from mi_skus import normalizar_sku, sku_existe

CAMPOS = ('sku', 'codigo_lote', 'fabricado_em', 'validade', 'quantidade_produzida')
PADRAO_CODIGO_LOTE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')


def normalizar_codigo_lote(codigo_lote):
    if not isinstance(codigo_lote, str) or not PADRAO_CODIGO_LOTE.fullmatch(codigo_lote.strip()):
        raise ValueError('codigo_lote_invalido')
    return codigo_lote.strip().upper()


def validar_lote(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS):
        raise ValueError('campos_invalidos')

    sku = normalizar_sku(body.get('sku'))
    codigo_lote = normalizar_codigo_lote(body.get('codigo_lote'))

    fabricado_em = body.get('fabricado_em')
    if fabricado_em is not None:
        if not isinstance(fabricado_em, str):
            raise ValueError('fabricado_em_invalido')
        fabricado_em = date.fromisoformat(fabricado_em).isoformat()

    validade = body.get('validade')
    if validade is not None:
        if not isinstance(validade, str):
            raise ValueError('validade_invalida')
        validade = date.fromisoformat(validade).isoformat()

    if fabricado_em and validade and validade < fabricado_em:
        raise ValueError('validade_anterior_a_fabricacao')

    quantidade_produzida = body.get('quantidade_produzida')
    if quantidade_produzida is not None:
        if (isinstance(quantidade_produzida, bool) or not isinstance(quantidade_produzida, (int, float))
                or not math.isfinite(quantidade_produzida) or not 0 < quantidade_produzida <= 10 ** 8):
            raise ValueError('quantidade_produzida_invalida')

    d = {'fabricado_em': fabricado_em, 'validade': validade, 'quantidade_produzida': quantidade_produzida}
    return sku, codigo_lote, d


def lote_existe(cur, sku, codigo_lote):
    """Confirma existência dentro da transação corrente do chamador; não abre conexão própria."""
    sku = normalizar_sku(sku)
    codigo_lote = normalizar_codigo_lote(codigo_lote)
    cur.execute("SELECT 1 FROM mi_lotes WHERE sku=%s AND codigo_lote=%s", (sku, codigo_lote))
    if not cur.fetchone():
        raise ValueError('lote_inexistente')
    return sku, codigo_lote


def criar_lote(factory, body):
    sku, codigo_lote, d = validar_lote(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sku_existe(cur, sku)
                cur.execute(
                    "INSERT INTO mi_lotes(id,sku,codigo_lote,fabricado_em,validade,quantidade_produzida) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(sku,codigo_lote) DO NOTHING RETURNING id",
                    (str(uuid4()), sku, codigo_lote, d['fabricado_em'], d['validade'], d['quantidade_produzida']),
                )
                novo = cur.fetchone()
                cur.execute(
                    "SELECT id,fabricado_em,validade,quantidade_produzida FROM mi_lotes "
                    "WHERE sku=%s AND codigo_lote=%s",
                    (sku, codigo_lote),
                )
                row = cur.fetchone()
                atual = {'fabricado_em': row['fabricado_em'], 'validade': row['validade'],
                         'quantidade_produzida': row['quantidade_produzida']}
                if atual != d:
                    return {'success': False, 'error': 'lote_ja_existe_com_outro_conteudo'}, 409
                return {'success': True, 'id': str(row['id']), 'sku': sku, 'codigo_lote': codigo_lote,
                        'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def lote_existe_por_id(cur, lote_id):
    """Confirma existência por id (surrogate); para módulos que só têm a FK, ex. mi_unidades.
    Não abre conexão própria — roda na transação corrente do chamador.
    """
    lote_id = str(UUID(str(lote_id)))
    cur.execute("SELECT 1 FROM mi_lotes WHERE id=%s", (lote_id,))
    if not cur.fetchone():
        raise ValueError('lote_inexistente')
    return lote_id


def buscar_lote(factory, sku, codigo_lote):
    sku = normalizar_sku(sku)
    codigo_lote = normalizar_codigo_lote(codigo_lote)
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,sku,codigo_lote,fabricado_em,validade,quantidade_produzida,criado_em "
                "FROM mi_lotes WHERE sku=%s AND codigo_lote=%s",
                (sku, codigo_lote),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
