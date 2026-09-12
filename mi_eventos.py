"""Núcleo do Maranhão Intelligence: eventos aditivos e idempotentes.

Fase 1: lote segue como referência textual solta (sem ligação com
mi_lotes ainda). sku, estabelecimento_id e unidade_id são relações reais
(FK validada na própria transação antes de qualquer escrita); os campos
`lote`/`unidade`/`estabelecimento` textuais soltos originais continuam
aceitos em paralelo, sem ligação com as tabelas normalizadas. O evento
alcança SKU/lote da unidade só por junção (unidade_id -> mi_unidades.lote_id
-> mi_lotes.sku), nunca duplicado aqui. Nenhum adaptador escreve direto no
banco; tudo passa por registrar_evento_mi.
"""
import hashlib
import json
import re
from datetime import datetime
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor, Json
from mi_skus import normalizar_sku, sku_existe
from mi_estabelecimentos import estabelecimento_existe
from mi_unidades import unidade_utilizavel

CAMPOS = ('tipo_evento', 'canal', 'sku', 'lote', 'unidade', 'estabelecimento', 'estabelecimento_id',
          'unidade_id', 'origem_tipo', 'origem_id', 'ocorrido_em', 'payload')
TIPOS_EVENTO = ('ativacao', 'scan', 'venda', 'feedback', 'presenca')
CAMPOS_TEXTO = ('lote', 'unidade', 'estabelecimento', 'origem_tipo', 'origem_id')


def validar_evento(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS) - {'chave'}:
        raise ValueError('campos_invalidos')
    chave = str(UUID(str(body.get('chave'))))
    d = {k: body.get(k) for k in CAMPOS}

    if d['tipo_evento'] not in TIPOS_EVENTO:
        raise ValueError('tipo_evento_invalido')

    if not isinstance(d['canal'], str) or not d['canal'].strip():
        raise ValueError('canal_obrigatorio')
    d['canal'] = d['canal'].strip()

    if d['sku'] is not None:
        d['sku'] = normalizar_sku(d['sku'])

    if d['estabelecimento_id'] is not None:
        d['estabelecimento_id'] = str(UUID(str(d['estabelecimento_id'])))

    if d['unidade_id'] is not None:
        d['unidade_id'] = str(UUID(str(d['unidade_id'])))

    for campo in CAMPOS_TEXTO:
        valor = d[campo]
        if valor is not None:
            if not isinstance(valor, str) or len(valor) > 500:
                raise ValueError('texto_invalido:' + campo)
            d[campo] = valor.strip() or None

    if bool(d['origem_tipo']) != bool(d['origem_id']):
        raise ValueError('origem_tipo_e_origem_id_juntos')
    if d['origem_tipo'] and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', d['origem_tipo']):
        raise ValueError('origem_tipo_invalido')

    if d['ocorrido_em'] is not None:
        if not isinstance(d['ocorrido_em'], str):
            raise ValueError('ocorrido_em_invalido')
        d['ocorrido_em'] = datetime.fromisoformat(d['ocorrido_em']).isoformat()

    payload = d['payload'] if d['payload'] is not None else {}
    if not isinstance(payload, dict):
        raise ValueError('payload_invalido')
    d['payload'] = payload

    digest = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return chave, d, digest


def registrar_evento_mi(factory, body):
    chave, d, digest = validar_evento(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if d['sku'] is not None:
                    sku_existe(cur, d['sku'])
                if d['estabelecimento_id'] is not None:
                    estabelecimento_existe(cur, d['estabelecimento_id'])
                if d['unidade_id'] is not None:
                    unidade_utilizavel(cur, d['unidade_id'])
                cur.execute(
                    "INSERT INTO mi_eventos(id,chave,payload_hash," + ",".join(CAMPOS) + ") "
                    "VALUES(" + ",".join(["%s"] * (len(CAMPOS) + 3)) + ") "
                    "ON CONFLICT(chave) DO NOTHING RETURNING id",
                    [str(uuid4()), chave, digest] + [Json(d[k]) if k == 'payload' else d[k] for k in CAMPOS],
                )
                novo = cur.fetchone()
                cur.execute("SELECT id, payload_hash FROM mi_eventos WHERE chave=%s", (chave,))
                row = cur.fetchone()
                if row['payload_hash'] != digest:
                    return {'success': False, 'error': 'chave_reutilizada_com_outro_conteudo'}, 409
                if novo:
                    cur.execute(
                        "INSERT INTO mi_eventos_auditoria(evento_id,evento,ator) VALUES(%s,'recebido',%s)",
                        (novo['id'], d['canal']),
                    )
                return {'success': True, 'id': str(row['id']), 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def consumo_territorial(cur):
    """Leitura para inteligencia_territorial.carregar(): usa o cursor do chamador
    (mesmo snapshot/transação). Nunca inclui payload (minimização de dados);
    cidade/uf/bairro vêm de mi_estabelecimentos quando o evento está ligado a
    um, sem geocodificação.
    """
    cur.execute(
        "SELECT e.id, e.tipo_evento, e.canal, e.sku, e.ocorrido_em, "
        "b.cidade, b.uf, b.bairro "
        "FROM mi_eventos e LEFT JOIN mi_estabelecimentos b ON b.id = e.estabelecimento_id "
        "ORDER BY e.id LIMIT 5001"
    )
    return [dict(row) for row in cur.fetchall()]
