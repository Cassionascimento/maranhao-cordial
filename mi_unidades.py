"""Serviço mínimo de unidade física do Maranhão Intelligence: LOTE → UNIDADE.

codigo_publico é o identificador público (etiqueta/QR/NFC futuros): opaco,
gerado por CSPRNG, nunca derivado de sku/lote_id/timestamp. Ele só identifica
a unidade — não é prova criptográfica de autenticidade. sku é sempre
alcançado via lote_id -> mi_lotes.sku, nunca duplicado aqui. Cada criação
gera uma unidade física nova; não existe "mesmo conteúdo" significativo
entre duas unidades, então não há idempotência por conteúdo aqui (seria
idempotência artificial). Revogação é terminal: uma vez revogada, a unidade
nunca reativa. Nenhum campo de PII de consumidor.
"""
import secrets
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor
from mi_lotes import lote_existe_por_id

CAMPOS = ('lote_id',)
ESTADOS = ('emitida', 'ativa', 'revogada')
ALFABETO_CODIGO = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'  # sem 0/O, 1/I/L — reduz erro de digitação
TAMANHO_CODIGO = 20
TENTATIVAS_COLISAO = 5


def gerar_codigo_publico():
    """Isolado para ser reaproveitado por uma futura criação em massa sem duplicar a geração."""
    return ''.join(secrets.choice(ALFABETO_CODIGO) for _ in range(TAMANHO_CODIGO))


def normalizar_codigo_publico(codigo_publico):
    if not isinstance(codigo_publico, str) or not codigo_publico.strip():
        raise ValueError('codigo_publico_invalido')
    return codigo_publico.strip().upper()


def validar_unidade(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS):
        raise ValueError('campos_invalidos')
    lote_id = body.get('lote_id')
    if not isinstance(lote_id, str):
        raise ValueError('lote_id_invalido')
    return str(UUID(lote_id))


def unidade_existe(cur, unidade_id):
    """Confirma existência dentro da transação corrente do chamador; não abre conexão própria."""
    unidade_id = str(UUID(str(unidade_id)))
    cur.execute("SELECT 1 FROM mi_unidades WHERE id=%s", (unidade_id,))
    if not cur.fetchone():
        raise ValueError('unidade_inexistente')
    return unidade_id


def unidade_utilizavel(cur, unidade_id):
    """Confirma existência e que a unidade não está revogada, na transação corrente do
    chamador (não abre conexão própria). Usado por quem associa um fato novo a uma
    unidade — ex. mi_eventos — para nunca aceitar unidade revogada em evento novo.
    """
    unidade_id = str(UUID(str(unidade_id)))
    cur.execute("SELECT estado FROM mi_unidades WHERE id=%s", (unidade_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError('unidade_inexistente')
    if row['estado'] == 'revogada':
        raise ValueError('unidade_revogada')
    return unidade_id


def criar_unidade(factory, body):
    lote_id = validar_unidade(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                lote_existe_por_id(cur, lote_id)
                for _ in range(TENTATIVAS_COLISAO):
                    codigo = gerar_codigo_publico()
                    cur.execute(
                        "INSERT INTO mi_unidades(id,lote_id,codigo_publico) VALUES(%s,%s,%s) "
                        "ON CONFLICT(codigo_publico) DO NOTHING RETURNING id",
                        (str(uuid4()), lote_id, codigo),
                    )
                    row = cur.fetchone()
                    if row:
                        return {'success': True, 'id': str(row['id']), 'codigo_publico': codigo,
                                'estado': 'emitida'}, 201
                raise RuntimeError('nao_foi_possivel_gerar_codigo_publico_unico')
    finally:
        conn.close()


def buscar_unidade_por_id(factory, unidade_id):
    unidade_id = str(UUID(str(unidade_id)))
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,lote_id,codigo_publico,estado,revogada_em,motivo_revogacao,criado_em "
                "FROM mi_unidades WHERE id=%s",
                (unidade_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def buscar_unidade_por_codigo(factory, codigo_publico):
    codigo_publico = normalizar_codigo_publico(codigo_publico)
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,lote_id,codigo_publico,estado,revogada_em,motivo_revogacao,criado_em "
                "FROM mi_unidades WHERE codigo_publico=%s",
                (codigo_publico,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def ativar_unidade(factory, codigo_publico):
    """Emitida -> ativa. Nunca reativa uma unidade revogada (terminal)."""
    codigo_publico = normalizar_codigo_publico(codigo_publico)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE mi_unidades SET estado='ativa' WHERE codigo_publico=%s AND estado='emitida' "
                    "RETURNING id",
                    (codigo_publico,),
                )
                atualizada = cur.fetchone()
                if atualizada:
                    return {'success': True, 'id': str(atualizada['id']), 'estado': 'ativa'}, 200
                cur.execute("SELECT id,estado FROM mi_unidades WHERE codigo_publico=%s", (codigo_publico,))
                existente = cur.fetchone()
                if not existente:
                    return {'success': False, 'error': 'unidade_inexistente'}, 404
                if existente['estado'] == 'revogada':
                    return {'success': False, 'error': 'unidade_revogada_nao_pode_reativar'}, 409
                return {'success': True, 'id': str(existente['id']), 'estado': existente['estado']}, 200
    finally:
        conn.close()


def revogar_unidade(factory, codigo_publico, motivo):
    codigo_publico = normalizar_codigo_publico(codigo_publico)
    if not isinstance(motivo, str) or not motivo.strip():
        raise ValueError('motivo_obrigatorio')
    motivo = motivo.strip()
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE mi_unidades SET estado='revogada', revogada_em=NOW(), motivo_revogacao=%s "
                    "WHERE codigo_publico=%s AND estado<>'revogada' RETURNING id",
                    (motivo, codigo_publico),
                )
                atualizada = cur.fetchone()
                if atualizada:
                    return {'success': True, 'id': str(atualizada['id']), 'ja_revogada': False}, 200
                cur.execute("SELECT id FROM mi_unidades WHERE codigo_publico=%s", (codigo_publico,))
                existente = cur.fetchone()
                if not existente:
                    return {'success': False, 'error': 'unidade_inexistente'}, 404
                return {'success': True, 'id': str(existente['id']), 'ja_revogada': True}, 200
    finally:
        conn.close()
