"""Identidade única do contato entre canais.

Hoje cada canal resolve o contato do seu jeito: o WhatsApp pelo telefone,
o Gmail pelo e-mail, o site pelo formulário. O mesmo bar que escreveu pelos
dois vira dois registros, e nada liga o `wa_id` ao endereço de e-mail.

Este módulo centraliza três decisões, e só elas:

1. **normalizar** um identificador (telefone só dígitos, e-mail minúsculo);
2. **resolver** qual contato existente corresponde — ou nenhum;
3. **recusar-se a adivinhar** quando há mais de um candidato.

A regra de recusa é a mesma que o WhatsApp já aplicava: ambiguidade vira
`IdentidadePendente` e a entrada fica aguardando decisão humana. Fundir dois
contatos é uma operação explícita, auditada, nunca automática — juntar
errado é pior do que ter duplicata, porque mistura o histórico de duas
empresas.

Não faz rede, não chama IA, não envia nada.
"""
import re
from uuid import uuid4

from psycopg2.extras import RealDictCursor

# Canais que podem carregar identidade. Um canal fora desta lista não é
# recusado: só não participa da deduplicação automática.
TIPOS = ('telefone', 'email', 'usuario', 'id_plataforma')

_EMAIL = re.compile(r'^[^@\s]+@[^@\s.]+\.[^@\s]+$')
_SO_DIGITOS = re.compile(r'[^0-9]')


class IdentidadePendente(ValueError):
    """Mais de um contato possível, ou contato que exige revisão humana."""


def normalizar(valor, tipo):
    """Forma canônica do identificador, ou None quando não serve para
    deduplicar. None nunca casa com nada — é o comportamento seguro."""
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    if not valor:
        return None
    if tipo == 'telefone':
        digitos = _SO_DIGITOS.sub('', valor)
        # Menos de 10 dígitos não identifica ninguém no Brasil (DDD + número);
        # mais de 15 não é telefone E.164.
        return digitos if 10 <= len(digitos) <= 15 else None
    if tipo == 'email':
        minusculo = valor.lower()
        return minusculo if _EMAIL.match(minusculo) and len(minusculo) <= 220 else None
    if tipo in ('usuario', 'id_plataforma'):
        return valor[:220] if len(valor) <= 220 else None
    return None


def _lead_utilizavel(linha):
    """Contato arquivado, interno ou de teste não pode receber vínculo
    automático: ou é lixo de base, ou é da própria casa."""
    return not any(linha.get(campo) for campo in ('arquivado', 'contato_interno', 'cadastro_teste'))


def resolver(cur, *, canal, identificador, tipo):
    """Contato correspondente a este identificador, ou None.

    Procura em duas camadas, nesta ordem:
    1. a tabela de identidades por canal (o vínculo já confirmado antes);
    2. os campos nativos de leads_crm (telefone/e-mail), para aproveitar o
       cadastro que já existia antes deste módulo.

    Dois candidatos distintos => IdentidadePendente. Nunca escolhe o
    primeiro.
    """
    chave = normalizar(identificador, tipo)
    if not chave:
        return None

    cur.execute(
        'SELECT lead_id FROM crm_identidades_canal WHERE canal=%s AND identificador_externo=%s',
        (canal, chave))
    linha = cur.fetchone()
    if linha:
        return str(linha['lead_id'])

    if tipo == 'telefone':
        cur.execute(
            "SELECT id,arquivado,contato_interno,cadastro_teste FROM leads_crm "
            "WHERE fundido_em_lead_id IS NULL AND ("
            "regexp_replace(COALESCE(telefone,''),'[^0-9]','','g')=%s "
            "OR (contato ~ '^[+0-9 ()-]+$' AND regexp_replace(contato,'[^0-9]','','g')=%s)) "
            "ORDER BY id LIMIT 2", (chave, chave))
    elif tipo == 'email':
        cur.execute(
            "SELECT id,arquivado,contato_interno,cadastro_teste FROM leads_crm "
            "WHERE fundido_em_lead_id IS NULL AND "
            "(lower(COALESCE(email,''))=%s OR lower(COALESCE(contato,''))=%s) "
            "ORDER BY id LIMIT 2", (chave, chave))
    else:
        return None

    candidatos = cur.fetchall() or []
    if not candidatos:
        return None
    if len(candidatos) > 1:
        raise IdentidadePendente('mais_de_um_contato_com_este_identificador')
    if not _lead_utilizavel(candidatos[0]):
        raise IdentidadePendente('contato_exige_revisao')
    return str(candidatos[0]['id'])


def vincular(cur, *, lead_id, canal, identificador, tipo, verificado=False):
    """Grava (ou revalida) a identidade deste contato neste canal.

    Idempotente: reencontrar o mesmo par só atualiza `ultima_vez_em`.
    Se o par já aponta para OUTRO contato, não sobrescreve — devolve
    IdentidadePendente, porque isso significa que dois cadastros disputam
    o mesmo identificador e alguém precisa decidir.
    """
    chave = normalizar(identificador, tipo)
    if not chave:
        return None
    cur.execute(
        'SELECT id,lead_id FROM crm_identidades_canal WHERE canal=%s AND identificador_externo=%s',
        (canal, chave))
    existente = cur.fetchone()
    if existente:
        if str(existente['lead_id']) != str(lead_id):
            raise IdentidadePendente('identificador_ja_pertence_a_outro_contato')
        cur.execute('UPDATE crm_identidades_canal SET ultima_vez_em=NOW(),verificado=verificado OR %s WHERE id=%s',
                    (bool(verificado), existente['id']))
        return str(existente['id'])
    ident = str(uuid4())
    cur.execute(
        'INSERT INTO crm_identidades_canal(id,lead_id,canal,identificador_externo,tipo,verificado) '
        'VALUES(%s,%s,%s,%s,%s,%s)', (ident, str(lead_id), canal, chave, tipo, bool(verificado)))
    return ident


def candidatos_de_fusao(cur, limite=50):
    """Contatos distintos que compartilham telefone ou e-mail normalizado.

    Só APONTA. Não funde. Serve para o painel mostrar "estes dois parecem
    a mesma empresa" e deixar a decisão com quem conhece o cliente.
    """
    cur.execute("""
        WITH normalizados AS (
            SELECT id,
                   NULLIF(regexp_replace(COALESCE(telefone,''),'[^0-9]','','g'),'') AS telefone,
                   NULLIF(lower(COALESCE(email,'')),'') AS email
            FROM leads_crm
            WHERE fundido_em_lead_id IS NULL AND NOT COALESCE(arquivado,FALSE)
              AND NOT COALESCE(cadastro_teste,FALSE)
        )
        SELECT 'telefone' AS tipo, telefone AS valor, array_agg(id::text ORDER BY id) AS leads
        FROM normalizados WHERE telefone IS NOT NULL AND length(telefone) BETWEEN 10 AND 15
        GROUP BY telefone HAVING count(*) > 1
        UNION ALL
        SELECT 'email' AS tipo, email AS valor, array_agg(id::text ORDER BY id) AS leads
        FROM normalizados WHERE email IS NOT NULL
        GROUP BY email HAVING count(*) > 1
        LIMIT %s
    """, (limite,))
    return [dict(linha) for linha in (cur.fetchall() or [])]


def fundir(cur, *, destino, absorvido, motivo, ator):
    """Funde dois contatos, com auditoria e sem apagar nada.

    O contato absorvido continua na base marcado com `fundido_em_lead_id`,
    para que qualquer link, relatório ou export antigo continue resolvendo.
    Interações e identidades passam para o destino.
    """
    if str(destino) == str(absorvido):
        raise ValueError('fusao_com_o_mesmo_contato')
    if not motivo or not str(motivo).strip():
        raise ValueError('fusao_exige_motivo')

    cur.execute('SELECT id,fundido_em_lead_id FROM leads_crm WHERE id IN (%s,%s)', (str(destino), str(absorvido)))
    encontrados = {str(l['id']): l for l in (cur.fetchall() or [])}
    if len(encontrados) != 2:
        raise ValueError('contato_inexistente')
    if any(l['fundido_em_lead_id'] for l in encontrados.values()):
        raise ValueError('contato_ja_fundido')

    # Identidade que colidiria no destino é descartada em vez de quebrar a
    # unicidade -- o vínculo já existe lá, com o mesmo significado.
    cur.execute("""DELETE FROM crm_identidades_canal
        WHERE lead_id=%s AND EXISTS (
            SELECT 1 FROM crm_identidades_canal AS destino
            WHERE destino.lead_id=%s
              AND destino.canal=crm_identidades_canal.canal
              AND destino.identificador_externo=crm_identidades_canal.identificador_externo)""",
        (str(absorvido), str(destino)))
    cur.execute('UPDATE crm_identidades_canal SET lead_id=%s WHERE lead_id=%s RETURNING id',
                (str(destino), str(absorvido)))
    identidades = len(cur.fetchall() or [])
    cur.execute('UPDATE interacoes_omnichannel SET lead_id=%s,atualizado_em=NOW() WHERE lead_id=%s RETURNING id',
                (str(destino), str(absorvido)))
    interacoes = len(cur.fetchall() or [])
    cur.execute('UPDATE leads_crm SET fundido_em_lead_id=%s,fundido_em=NOW(),fundido_por=%s WHERE id=%s',
                (str(destino), str(ator or 'nao_informado')[:220], str(absorvido)))
    cur.execute('INSERT INTO crm_fusao_auditoria(lead_destino,lead_absorvido,motivo,ator,'
                'identidades_movidas,interacoes_movidas) VALUES(%s,%s,%s,%s,%s,%s)',
                (str(destino), str(absorvido), str(motivo)[:500], str(ator or 'nao_informado')[:220],
                 identidades, interacoes))
    return {'destino': str(destino), 'absorvido': str(absorvido),
            'identidades_movidas': identidades, 'interacoes_movidas': interacoes}


def historico(cur, lead_id, limite=100):
    """Linha do tempo única do contato, com o tipo de cada evento preservado.

    Mensagem, comentário e pedido não viram "interação genérica": o canal e
    o tipo continuam no registro, porque a leitura muda conforme a origem.
    """
    cur.execute("""
        SELECT id,canal,plataforma,tipo_interacao,classificacao,texto,message_id,criado_em
        FROM interacoes_omnichannel
        WHERE lead_id=%s AND NOT COALESCE(arquivado,FALSE)
        ORDER BY criado_em DESC LIMIT %s
    """, (str(lead_id), limite))
    return [{'id': str(l['id']), 'canal': l['canal'], 'plataforma': l['plataforma'],
             'tipo': l['tipo_interacao'], 'classificacao': l['classificacao'],
             'texto': l['texto'], 'identificador_externo': l['message_id'],
             'quando': l['criado_em'].isoformat() if hasattr(l['criado_em'], 'isoformat') else l['criado_em']}
            for l in (cur.fetchall() or [])]


def registrar_rotas_crm_identidade(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/crm/duplicados', methods=['GET'])
    def crm_duplicados():
        """Aponta possíveis duplicatas. Nunca funde sozinho."""
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                return jsonify(success=True, candidatos=candidatos_de_fusao(cur))
        except Exception:
            app.logger.exception('Falha ao listar duplicados')
            return jsonify(success=False, error='Consulta indisponível.'), 503
        finally:
            conn.close()

    @app.route('/api/admin/crm/leads/<lead_id>/historico', methods=['GET'])
    def crm_historico(lead_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT canal,identificador_externo,tipo,verificado,ultima_vez_em '
                            'FROM crm_identidades_canal WHERE lead_id=%s ORDER BY ultima_vez_em DESC', (lead_id,))
                identidades = [dict(l) for l in (cur.fetchall() or [])]
                return jsonify(success=True, identidades=identidades,
                               historico=historico(cur, lead_id))
        except Exception:
            app.logger.exception('Falha ao montar histórico do contato')
            return jsonify(success=False, error='Histórico indisponível.'), 503
        finally:
            conn.close()

    @app.route('/api/admin/crm/leads/fundir', methods=['POST'])
    def crm_fundir():
        """Fusão explícita: exige destino, absorvido, motivo e ator.

        É escrita, e por isso nunca acontece por inferência automática --
        a rota existe para o humano confirmar o que o painel sugeriu.
        """
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        conn = factory()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    resultado = fundir(cur, destino=corpo.get('destino'),
                                       absorvido=corpo.get('absorvido'),
                                       motivo=corpo.get('motivo'), ator=corpo.get('ator'))
            return jsonify(success=True, **resultado)
        except (ValueError, IdentidadePendente) as erro:
            return jsonify(success=False, error=str(erro)), 400
        except Exception:
            app.logger.exception('Falha ao fundir contatos')
            return jsonify(success=False, error='Fusão não confirmada.'), 503
        finally:
            conn.close()
