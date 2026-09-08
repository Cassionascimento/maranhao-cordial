"""Transportes bloqueados; banco transacional simulado para cenários de falha."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from flask import Flask, request, jsonify
import email_seguranca as p0
import email_supervisionado as one
import gmail_sync_job as sync
import prospeccao_job as prospect
import test_email_p0 as f


class Banco:
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()
        self.pause = True
        self.suppressed = set()
        self.audit = []
        self.crm = []
        self.fail_commit = False

    def __call__(self):
        return Connection(self)


class Connection:
    def __init__(self, db):
        self.db = db
        self.result = None

    def __enter__(self):
        self.db.lock.acquire()
        self.before = copy.deepcopy((self.db.rows, self.db.audit, self.db.crm))
        return self

    def __exit__(self, typ, *_):
        if typ or self.db.fail_commit:
            self.db.rows, self.db.audit, self.db.crm = self.before
        self.db.lock.release()
        if not typ and self.db.fail_commit:
            raise RuntimeError('commit indisponível')

    def cursor(self):
        return Cursor(self)

    def close(self):
        pass


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, args=()):
        db = self.conn.db
        q = ' '.join(sql.split())
        self.conn.result = None
        if q.startswith('SELECT pausado'):
            self.conn.result = (db.pause,)
        elif q.startswith('SELECT email FROM'):
            self.conn.result = (args[0],) if args[0] in db.suppressed else None
        elif q.startswith('INSERT INTO email_autorizacoes'):
            ident, alvo, raw, digest, texto, motivo = args
            db.rows[ident] = dict(alvo=alvo, raw=raw, digest=digest, texto=texto, state='autorizado', expired=False)
        elif q.startswith('SELECT destinatario,raw'):
            assert 'FOR UPDATE' in q
            row = db.rows.get(args[0])
            if row and row['state']=='autorizado' and not row['expired']:
                self.conn.result = tuple(row[k] for k in ('alvo','raw','digest','texto'))
        elif q.startswith('UPDATE email_autorizacoes'):
            row = db.rows[args[-1]]
            row['state'] = 'incerto' if "estado='incerto'" in q else 'enviado' if "estado='enviado'" in q else 'consumido'
        elif q.startswith('INSERT INTO email_eventos'):
            db.audit.append(args)
        elif q.startswith('INSERT INTO interacoes'):
            db.crm.append(args)
            self.conn.result = ('00000000-0000-0000-0000-000000000001',)

    def fetchone(self):
        return self.conn.result


class OneShot(f.Offline):
    def setUp(self):
        super().setUp()
        self.env = patch.dict('os.environ', {'EMAIL_ENVIOS_PAUSADOS':'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = Banco()
        self.ns = {'get_db_connection':self.db}
        self.service = Mock()
        self.service.users().getProfile().execute.return_value = {'emailAddress':'contato@maranhaocordial.com.br'}
        self.send = self.service.users().messages().send
        self.send.return_value.execute.return_value = {'id':'gmail-1','threadId':'thread-1'}
        self.google = patch('fase56_fabrica_piloto.obter_gmail_service_fase56', return_value=self.service)
        self.google.start()
        self.addCleanup(self.google.stop)

    def authorize(self, **kw):
        dados = dict(destinatario='interno@example.com', assunto='Teste único', texto='Homologação.', motivo='Autorizado para teste')
        dados.update(kw)
        return one.autorizar(self.db,dados)['autorizacao_id']

    def test_um_envio_e_segundo_bloqueado_com_auditoria_crm(self):
        ident = self.authorize()
        r = one.executar(self.ns,ident)
        self.assertEqual(r['destinatario'],'interno@example.com')
        self.assertEqual(len(self.db.crm),1)
        self.assertEqual([a[0] for a in self.db.audit],['supervisionado_autorizado','supervisionado_consumido','supervisionado_enviado'])
        self.send.return_value.execute.assert_called_once_with(num_retries=0)
        with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        self.assertEqual(self.send.call_count,1)
        self.assertTrue(self.db.pause)

    def test_concorrencia_consumo_unico(self):
        ident=self.authorize()
        def run():
            try: return one.executar(self.ns,ident)['success']
            except p0.EnvioBloqueado: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _:run(),range(2))),[False,True])
        self.send.assert_called_once()

    def test_destinatarios_multiplos_headers_e_cc_rejeitados(self):
        for alvo in ['a@example.com,b@example.com','Pessoa <a@example.com>','a@example.com\r\nBcc: b@example.com']:
            with self.assertRaises((ValueError,p0.EnvioBloqueado)): self.authorize(destinatario=alvo)
        with self.assertRaises(ValueError): self.authorize(cc='terceiro@example.com')
        with self.assertRaises(ValueError): self.authorize(assunto='Teste\nBcc: terceiro@example.com')
        self.send.assert_not_called()

    def test_alteracao_alvo_ou_conteudo_falha_fechada(self):
        for campo in ['alvo','raw']:
            ident=self.authorize()
            self.db.rows[ident][campo]='terceiro@example.com'
            with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        self.send.assert_not_called()

    def test_expiracao_supressao_e_pausa_nao_sobrepostas(self):
        ident=self.authorize()
        self.db.rows[ident]['expired']=True
        with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        ident=self.authorize()
        self.db.suppressed.add('interno@example.com')
        with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        with self.assertRaises(p0.EnvioBloqueado): self.authorize()
        self.db.suppressed.clear()
        self.db.pause=False
        with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        self.send.assert_not_called()

    def test_timeout_consumido_sem_retry(self):
        ident=self.authorize()
        self.send.return_value.execute.side_effect=TimeoutError()
        with self.assertRaises(RuntimeError): one.executar(self.ns,ident)
        with self.assertRaises(p0.EnvioBloqueado): one.executar(self.ns,ident)
        self.send.assert_called_once()
        self.assertEqual(self.db.rows[ident]['state'],'incerto')

    def test_banco_falha_antes_de_consumir_nao_chama_gmail(self):
        ident=self.authorize()
        self.db.fail_commit=True
        with self.assertRaises(RuntimeError): one.executar(self.ns,ident)
        self.send.assert_not_called()

    def test_remetente_errado_nao_envia_e_nao_reabre_autorizacao(self):
        ident=self.authorize()
        self.service.users().getProfile().execute.return_value={'emailAddress':'errado@example.com'}
        with self.assertRaises(RuntimeError): one.executar(self.ns,ident)
        self.send.assert_not_called()
        self.assertEqual(self.db.rows[ident]['state'],'incerto')

    def test_autorizacao_nao_libera_adaptadores_normais(self):
        self.authorize()
        for alvo in ['interno@example.com','terceiro@example.com']:
            with self.assertRaises(p0.EnvioBloqueado): p0.verificar_envio(self.db,alvo)

    def test_rotas_exigem_admin_e_envio_rejeita_troca_de_destinatario(self):
        app=Flask(__name__); app.secret_key='sintetica'
        ns=dict(request=request,jsonify=jsonify,session=__import__('flask').session,
                validar_admin_request=lambda:request.headers.get('X-Admin-Key')=='sintetica',
                get_db_connection=self.db,EnvioBloqueado=p0.EnvioBloqueado)
        f.carregar_funcoes('main.py',['proteger_administracao_p0','autorizar_email_supervisionado','executar_email_supervisionado'],ns)
        app.before_request(ns['proteger_administracao_p0'])
        app.add_url_rule('/api/admin/email/supervisionado/autorizar',view_func=ns['autorizar_email_supervisionado'],methods=['POST'])
        app.add_url_rule('/api/admin/email/supervisionado/<ident>/enviar',view_func=ns['executar_email_supervisionado'],methods=['POST'])
        client=app.test_client()
        for h in [{},{'X-Admin-Key':'errada'}]:
            self.assertEqual(client.post('/api/admin/email/supervisionado/autorizar',json={},headers=h).status_code,401)
            self.assertEqual(client.post('/api/admin/email/supervisionado/abc/enviar',json={},headers=h).status_code,401)
        self.assertEqual(client.post('/api/admin/email/supervisionado/abc/enviar',json={'destinatario':'terceiro@example.com'},headers={'X-Admin-Key':'sintetica'}).status_code,400)
        self.send.assert_not_called()


class Jobs(f.Offline):
    def test_sync_sem_secret_cron_nunca_chama_post(self):
        http=Mock()
        http.get.return_value=f.resposta_json({'success':True,'prospeccao_permitida':True,'erros':[]})
        http.get.return_value.status_code=200
        with patch.dict('os.environ',{'ADMIN_API_KEY':'sintetica'},clear=True):
            sync.executar_job(http)
        http.post.assert_not_called()

    def test_prospeccao_separada_desligada_por_padrao(self):
        http=Mock()
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(sync.JobAbortado): prospect.executar_prospeccao(http)
        self.assertEqual(http.method_calls,[])

    def test_prospeccao_explicita_mantem_sync_primeiro(self):
        http=Mock()
        http.get.return_value=f.resposta_json({'success':True,'prospeccao_permitida':True,'erros':[]})
        http.post.return_value=f.resposta_json({'success':True})
        http.get.return_value.status_code=200
        http.post.return_value.status_code=200
        with patch.dict('os.environ',{'ADMIN_API_KEY':'a','FASE58_CRON_SECRET':'b','PROSPECCAO_JOB_HABILITADO':'true'}):
            prospect.executar_prospeccao(http)
        self.assertEqual([x[0] for x in http.method_calls],['get','post'])
