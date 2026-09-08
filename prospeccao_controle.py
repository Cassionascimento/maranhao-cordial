"""Primeiro contato: orçamento durável, serialização global e histórico intacto.

Não contorna as pausas P0. Reserva não é confirmação de envio nem de entrega.
"""
from contextvars import ContextVar
from functools import wraps
import os

from email_seguranca import EnvioBloqueado, definir_pausa, verificar_envio, verificar_travas_envio

LOCK = 5702001
_reserva = ContextVar('reserva_prospeccao', default=None)
EMAIL = r'^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'


def schema(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS prospeccao_reservas (
        email TEXT PRIMARY KEY, prospecto_id UUID NOT NULL,
        dia DATE NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')::date,
        vaga INTEGER NOT NULL CHECK(vaga BETWEEN 1 AND 2),
        estado TEXT NOT NULL DEFAULT 'reservado'
            CHECK(estado IN ('reservado','enviado','incerto')),
        gmail_id TEXT, thread_id TEXT, erro TEXT,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(dia,vaga))''')
    cur.execute("SELECT to_regclass('public.prospeccao_historico_contatados')")
    reg = cur.fetchone()
    if not reg or reg[0] is None:
        cur.execute('''CREATE VIEW prospeccao_historico_contatados AS
        SELECT lower(trim(email)) email, ultimo_contato_em contato_em
        FROM prospectos_fase57
        WHERE ultimo_contato_em IS NOT NULL OR tentativas>0
           OR status IN ('contatado','negociando','promissor')
        UNION ALL
        SELECT lower(trim(email)), ultimo_contato_em FROM prospectos_fabrica_fase56
        WHERE ultimo_contato_em IS NOT NULL OR tentativas>0
           OR status IN ('contatado','negociando','promissor')
        UNION ALL
        SELECT lower(trim(recipient_id)), criado_em FROM interacoes_omnichannel
        WHERE canal IN ('gmail','email') AND
          (tipo_interacao LIKE '%%saida%%'
           OR lower(trim(sender_id))='contato@maranhaocordial.com.br')
        ''')


def elegivel_sql():
    # Mesmo predicado na seleção, reposição e revalidação sob lock.
    return """p.status='qualificado' AND p.score>=55
        AND trim(COALESCE(p.email,'')) ~ '^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'
        AND p.fonte_url ~ '^https?://' AND length(trim(COALESCE(p.evidencia,'')))>0
        AND NOT EXISTS (SELECT 1 FROM prospeccao_historico_contatados h
            WHERE h.email=lower(trim(p.email)))
        AND NOT EXISTS (SELECT 1 FROM email_supressoes_p0 s
            WHERE s.email=lower(trim(p.email)))
        AND NOT EXISTS (SELECT 1 FROM prospeccao_reservas r
            WHERE r.email=lower(trim(p.email)))"""


def instalar(factory):
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
                schema(cur)
    finally:
        conn.close()


def quota(cur):
    cur.execute('''SELECT COUNT(DISTINCT email) FROM (
        SELECT email FROM prospeccao_historico_contatados
        WHERE (contato_em AT TIME ZONE 'America/Sao_Paulo')::date =
              (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
        UNION ALL SELECT email FROM prospeccao_reservas WHERE dia=
              (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
    ) x''')
    usados = cur.fetchone()[0]
    return dict(limite=2, usados=usados, restantes=max(0, 2-usados), bloqueado=usados>=2)


def status(factory):
    instalar(factory)
    conn = factory()
    try:
        with conn.cursor() as cur:
            return quota(cur)
    finally:
        conn.close()


def primeiro_contato(fn):
    @wraps(fn)
    def protegido(namespace, prospecto_id):
        from fase57_prospeccao_universal import _conn
        factory = lambda: _conn(namespace)
        instalar(factory)
        conn = factory()
        reservado = False
        token = None
        email = None
        try:
            # Lock de sessão permanece durante commits e Gmail. Crash o libera,
            # mas a reserva pendente impede a próxima tentativa, mesmo amanhã.
            with conn.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,))
                if not cur.fetchone()[0]:
                    return {'success': True, 'enviado': False, 'motivo': 'rodada_em_andamento'}
                cur.execute("SELECT 1 FROM prospeccao_reservas WHERE estado<>'enviado' LIMIT 1")
                if cur.fetchone():
                    raise EnvioBloqueado('reserva_pendente_requer_reconciliacao')
                if quota(cur)['bloqueado']:
                    return {'success': True, 'enviado': False, 'motivo': 'limite_diario_global'}
                cur.execute('''SELECT lower(trim(p.email)) FROM prospectos_fase57 p
                    JOIN campanhas_prospeccao_fase57 c ON c.id=p.campanha_id
                    WHERE p.id=%s AND c.status IN ('ativa','pesquisando','contatando','negociando')
                      AND c.permitir_primeiro_contato AND ''' + elegivel_sql(), (prospecto_id,))
                row = cur.fetchone()
                if not row:
                    raise EnvioBloqueado('prospecto_inelegivel_ou_duplicado')
                email = row[0]
                verificar_travas_envio(factory, email)
                cur.execute('''INSERT INTO prospeccao_reservas(email,prospecto_id,vaga)
                    SELECT %s,%s,n FROM generate_series(1,2) n
                    WHERE NOT EXISTS (SELECT 1 FROM prospeccao_reservas r
                      WHERE r.dia=(NOW() AT TIME ZONE 'America/Sao_Paulo')::date AND r.vaga=n)
                    ORDER BY n LIMIT 1''', (email, prospecto_id))
                if cur.rowcount != 1:
                    raise EnvioBloqueado('sem_vaga_diaria')
                cur.execute('''INSERT INTO email_eventos_seguranca_p0
                    (tipo,destinatario,mensagem_origem,motivo)
                    VALUES ('prospeccao_reservada',%s,%s,'Reserva diária; não confirma envio ou entrega')''',
                    (email, str(prospecto_id)))
            conn.commit()  # Obrigatoriamente antes do transporte; nunca estornar.
            reservado = True
            token = _reserva.set({'email': email, 'consumida': False})
            verificar_envio(factory, email)
            resultado = fn(namespace, prospecto_id)
            if not resultado.get('success') or not resultado.get('message_id'):
                raise RuntimeError('primeiro_contato_sem_confirmacao')
            with conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE prospeccao_reservas SET estado='enviado',gmail_id=%s,thread_id=%s WHERE email=%s",
                                (resultado['message_id'], resultado.get('thread_id'), email))
                    cur.execute('''INSERT INTO email_eventos_seguranca_p0
                        (tipo,destinatario,mensagem_origem,mensagem_enviada,motivo)
                        VALUES ('prospeccao_enviada',%s,%s,%s,'Gmail aceitou; entrega não confirmada')''',
                        (email, str(prospecto_id), resultado['message_id']))
            return dict(resultado, enviado=True)
        except Exception as erro:
            conn.rollback()
            if reservado:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE prospeccao_reservas SET estado='incerto',erro=%s WHERE email=%s",
                                    (type(erro).__name__, email))
            definir_pausa(factory, True, 'Prospecção interrompida: ' + type(erro).__name__)
            raise
        finally:
            if token is not None:
                _reserva.reset(token)
            conn.close()  # Libera advisory lock inclusive em falha de commit.
    return protegido


def consumir_transporte(destinatario, cc, reply):
    """Só a reserva normal de primeiro contato pode usar este contexto uma vez."""
    r = _reserva.get()
    if r is None:
        return
    if r['consumida'] or cc or reply or destinatario.strip().lower() != r['email']:
        raise EnvioBloqueado('transporte_fora_da_reserva')
    r['consumida'] = True


def validar_contexto(destinatario, cc=None):
    if os.getenv('EMAIL_APENAS_PROSPECCAO_CONTROLADA') != 'true':
        return
    r = _reserva.get()
    if not r or r['consumida'] or cc or destinatario.strip().lower() != r['email']:
        raise EnvioBloqueado('somente_primeiro_contato_com_reserva')


def rodada(namespace, pesquisas_max=3):
    """Rodada finita: reposição somente quando necessário, sem follow-up/5.8."""
    from fase57_prospeccao_universal import (
        _conn, executar_lote_contatos_fase57, executar_pesquisa_publica_fase57,
        garantir_pesquisa_se_faltar_fase57,
    )
    factory = lambda: _conn(namespace)
    instalar(factory)
    pesquisas, resultados = [], []
    try:
        for indice in range(pesquisas_max + 1):
            lote = executar_lote_contatos_fase57(namespace, limite=2)
            resultados.extend(lote['resultados'])
            if not lote['success']:
                return dict(success=False, pesquisas=pesquisas, resultados=resultados, contador=status(factory))
            if status(factory)['bloqueado'] or indice == pesquisas_max:
                break
            conn = factory()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM campanhas_prospeccao_fase57 WHERE status='ativa' AND permitir_primeiro_contato ORDER BY criado_em")
                    ids = [str(r[0]) for r in cur.fetchall()]
            finally:
                conn.close()
            for ident in ids:
                garantir_pesquisa_se_faltar_fase57(namespace, ident)
            pesquisa = executar_pesquisa_publica_fase57(namespace, limite=4)
            pesquisas.append(pesquisa)
            if not pesquisa.get('success'):
                raise RuntimeError('pesquisa_falhou')
            if not pesquisa.get('executada'):
                break
        return dict(success=True, pesquisas=pesquisas, resultados=resultados, contador=status(factory))
    except Exception:
        definir_pausa(factory, True, 'Rodada de prospecção interrompida')
        raise
