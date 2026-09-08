"""Sem rede; modelo transacional com lock de sessão compartilhado."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import test_email_p0 as f
import prospeccao_controle as c
import fase57_prospeccao_universal as fase


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.rows = {}
        self.history = set()
        self.candidates = {str(i): f'contato{i}@empresa.com.br' for i in range(8)}
        self.sent = []
        self.fail_commit = False
        self.day = 1

    def __call__(self):
        return Conn(self)


class Conn:
    def __init__(self, db):
        self.db, self.result = db, None
        self.xlock = self.slock = False
        self.pending = None

    def __enter__(self):
        return self

    def __exit__(self, typ, *_):
        self.rollback() if typ else self.commit()

    def cursor(self, **_):
        return Cursor(self)

    def commit(self):
        if self.db.fail_commit and self.pending:
            raise RuntimeError('commit')
        if self.pending:
            email, row = self.pending
            self.db.rows[email] = row
            self.pending = None
        if self.xlock:
            self.db.lock.release()
            self.xlock = False

    def rollback(self):
        self.pending = None

    def close(self):
        if self.xlock:
            self.db.lock.release()
        if self.slock:
            self.db.lock.release()


class Cursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, args=()):
        q = ' '.join(sql.split())
        conn, db = self.conn, self.conn.db
        conn.result = None
        if q.startswith('SELECT pg_advisory_xact_lock'):
            db.lock.acquire()
            conn.xlock = True
        elif q.startswith('SELECT pg_try_advisory_lock'):
            conn.slock = db.lock.acquire(blocking=False)
            conn.result = (conn.slock,)
        elif q.startswith('SELECT 1 FROM prospeccao_reservas'):
            conn.result = next(((1,) for r in db.rows.values() if r['estado']!='enviado'), None)
        elif q.startswith('SELECT COUNT(DISTINCT email)'):
            conn.result = (len(db.history | {email for email, r in db.rows.items() if r['day']==db.day}),)
        elif q.startswith('SELECT lower(trim(p.email))'):
            email = db.candidates.get(args[0])
            if email and email not in db.history and email not in db.rows:
                conn.result = (email,)
        elif q.startswith('INSERT INTO prospeccao_reservas'):
            conn.pending = (args[0], {'estado':'reservado', 'day':db.day})
            self.rowcount = 1
        elif q.startswith('UPDATE prospeccao_reservas'):
            db.rows[args[-1]]['estado'] = 'incerto' if "'incerto'" in q else 'enviado'

    def fetchone(self):
        return self.conn.result


class Controle(f.Offline):
    def setUp(self):
        super().setUp()
        self.db = DB()
        for patcher in (patch.object(fase, '_conn', side_effect=lambda _: self.db()),
                        patch.object(c, 'verificar_envio'), patch.object(c, 'definir_pausa')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def sender(self, _, ident):
        email = self.db.candidates[ident]
        c.consumir_transporte(email, None, None)
        self.db.sent.append(email)
        return dict(success=True, message_id='gmail-'+ident, thread_id='thread-'+ident)

    def test_concorrencia_limite_global_duas_reservas(self):
        send = c.primeiro_contato(self.sender)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: send({}, str(i)), range(8)))
        self.assertEqual(len(self.db.sent), 2)
        self.assertEqual(len(self.db.rows), 2)

    def test_historico_consumido_no_mesmo_dia(self):
        self.db.history.add('anterior@empresa.com.br')
        send = c.primeiro_contato(self.sender)
        send({}, '0')
        self.assertFalse(send({}, '1')['enviado'])
        self.assertEqual(len(self.db.sent), 1)

    def test_duplicidade_historica_impede_transporte(self):
        self.db.history.add(self.db.candidates['0'])
        with self.assertRaises(c.EnvioBloqueado):
            c.primeiro_contato(self.sender)({}, '0')
        self.assertEqual(self.db.sent, [])

    def test_sem_email_inelegivel(self):
        self.db.candidates['0'] = None
        with self.assertRaises(c.EnvioBloqueado):
            c.primeiro_contato(self.sender)({}, '0')
        self.assertEqual(self.db.rows, {})

    def test_timeout_nao_estorna_e_bloqueia_dia_seguinte(self):
        with self.assertRaises(TimeoutError):
            c.primeiro_contato(Mock(side_effect=TimeoutError))({}, '0')
        self.db.day += 1
        with self.assertRaises(c.EnvioBloqueado):
            c.primeiro_contato(self.sender)({}, '1')
        self.assertEqual(len(self.db.rows), 1)
        c.definir_pausa.assert_called()

    def test_falha_commit_antes_gmail(self):
        self.db.fail_commit = True
        with self.assertRaises(RuntimeError):
            c.primeiro_contato(self.sender)({}, '0')
        self.assertEqual(self.db.sent, [])

    def test_segundo_transporte_e_outro_destinatario_bloqueados(self):
        def duplo(_, ident):
            c.consumir_transporte(self.db.candidates[ident], None, None)
            with self.assertRaises(c.EnvioBloqueado):
                c.consumir_transporte(self.db.candidates[ident], None, None)
            return dict(success=True, message_id='id')
        c.primeiro_contato(duplo)({}, '0')
        token = c._reserva.set({'email':'um@empresa.com.br','consumida':False})
        try:
            with self.assertRaises(c.EnvioBloqueado):
                c.consumir_transporte('outro@empresa.com.br', None, None)
        finally:
            c._reserva.reset(token)

    def test_contexto_restrito_nao_contorna_p0(self):
        import os
        from email_seguranca import verificar_envio
        with patch.dict(os.environ, EMAIL_APENAS_PROSPECCAO_CONTROLADA='true'):
            with self.assertRaises(c.EnvioBloqueado):
                verificar_envio(self.banco, 'um@empresa.com.br')
            token = c._reserva.set({'email':'um@empresa.com.br','consumida':False})
            try:
                with patch.dict(os.environ, EMAIL_ENVIOS_PAUSADOS='true'):
                    with self.assertRaises(c.EnvioBloqueado):
                        verificar_envio(self.banco, 'um@empresa.com.br')
            finally:
                c._reserva.reset(token)

    def test_lote_para_na_primeira_excecao(self):
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=Mock(fetchall=Mock(return_value=[{'id':'0'},{'id':'1'}])))
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        with patch.object(fase, '_conn', return_value=conn), patch.object(fase, '_limite_diario_global_fase57', return_value={'bloqueado':False,'restantes':2}), patch.object(fase, 'enviar_primeiro_contato_fase57', side_effect=TimeoutError) as send, patch('email_seguranca.definir_pausa'):
            result = fase.executar_lote_contatos_fase57({})
        self.assertFalse(result['success'])
        send.assert_called_once()

    def test_reposicao_apos_fila_vazia(self):
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=Mock(fetchall=Mock(return_value=[('campanha',)])))
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        with patch.object(fase, '_conn', return_value=conn), patch.object(c, 'instalar'), patch.object(c, 'status', return_value={'bloqueado':False}), patch.object(fase, 'executar_lote_contatos_fase57', return_value={'success':True,'resultados':[]}), patch.object(fase, 'garantir_pesquisa_se_faltar_fase57') as refill, patch.object(fase, 'executar_pesquisa_publica_fase57', return_value={'success':True,'executada':True,'inseridos':2}) as research:
            r = c.rodada({}, pesquisas_max=1)
        refill.assert_called_once_with({}, 'campanha')
        research.assert_called_once()
        self.assertEqual(len(r['pesquisas']),1)

    def test_erro_lote_nao_pesquisa_nem_continua(self):
        with patch.object(c, 'instalar'), patch.object(c, 'status', return_value={}), patch.object(fase, 'executar_lote_contatos_fase57', return_value={'success':False,'resultados':[]}) as batch, patch.object(fase, 'executar_pesquisa_publica_fase57') as research:
            self.assertFalse(c.rodada({})['success'])
        batch.assert_called_once()
        research.assert_not_called()

    def test_job_desabilitado_nao_executa_sync(self):
        import os
        import prospeccao_controlada_job as job
        with patch.dict(os.environ, {}, clear=True), patch.object(job, 'executar_job') as sync:
            with self.assertRaises(RuntimeError):
                job.executar()
        sync.assert_not_called()

    def test_virada_dia_nao_reutiliza_destinatario(self):
        send = c.primeiro_contato(self.sender)
        send({}, '0')
        self.db.day += 1
        with self.assertRaises(c.EnvioBloqueado):
            send({}, '0')
        self.assertEqual(len(self.db.sent), 1)
