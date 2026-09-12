"""Serviço mínimo de estabelecimento do Maranhão Intelligence.

cidade/UF usam a mesma normalização de inteligencia_territorial (uf_valida):
só reconhece sigla/nome de UF já conhecido, nunca geocodifica endereço ou
nome de lugar. lead_id é somente uma ponte opcional explícita para
leads_crm; nenhuma heurística automática liga estabelecimento a lead aqui
(a integridade fica a cargo da FK do schema, mesmo padrão já usado em
territorio_registros.contato_id).
"""
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor
from inteligencia_territorial import uf_valida

CAMPOS = ('nome', 'tipo', 'cidade', 'uf', 'bairro', 'lead_id')


def validar_estabelecimento(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS):
        raise ValueError('campos_invalidos')

    nome = body.get('nome')
    if not isinstance(nome, str) or not nome.strip() or len(nome.strip()) > 200:
        raise ValueError('nome_invalido')
    nome = nome.strip()

    tipo = body.get('tipo')
    if tipo is not None:
        if not isinstance(tipo, str) or len(tipo) > 60:
            raise ValueError('tipo_invalido')
        tipo = tipo.strip() or None

    cidade = body.get('cidade')
    if not isinstance(cidade, str) or not cidade.strip() or len(cidade.strip()) > 120:
        raise ValueError('cidade_invalida')
    cidade = cidade.strip()

    uf = uf_valida(body.get('uf'))
    if not uf:
        raise ValueError('uf_invalida')

    bairro = body.get('bairro')
    if bairro is not None:
        if not isinstance(bairro, str) or len(bairro) > 120:
            raise ValueError('bairro_invalido')
        bairro = bairro.strip() or None

    lead_id = body.get('lead_id')
    if lead_id is not None:
        lead_id = str(UUID(str(lead_id)))

    return {'nome': nome, 'tipo': tipo, 'cidade': cidade, 'uf': uf, 'bairro': bairro, 'lead_id': lead_id}


def estabelecimento_existe(cur, estabelecimento_id):
    """Confirma existência dentro da transação corrente do chamador; não abre conexão própria."""
    ident = str(UUID(str(estabelecimento_id)))
    cur.execute("SELECT 1 FROM mi_estabelecimentos WHERE id=%s", (ident,))
    if not cur.fetchone():
        raise ValueError('estabelecimento_inexistente')
    return ident


def criar_estabelecimento(factory, body):
    d = validar_estabelecimento(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                novo_id = str(uuid4())
                cur.execute(
                    "INSERT INTO mi_estabelecimentos(id,nome,tipo,cidade,uf,bairro,lead_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (novo_id, d['nome'], d['tipo'], d['cidade'], d['uf'], d['bairro'], d['lead_id']),
                )
                row = cur.fetchone()
                return {'success': True, 'id': str(row['id'])}, 201
    finally:
        conn.close()


def buscar_estabelecimento(factory, estabelecimento_id):
    ident = str(UUID(str(estabelecimento_id)))
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,nome,tipo,cidade,uf,bairro,lead_id,criado_em FROM mi_estabelecimentos WHERE id=%s",
                (ident,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
