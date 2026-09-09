"""Regressões específicas de paginação/cursor e entrada Gmail pendente."""
import base64
import copy
import unittest
from unittest.mock import Mock, patch
from flask import Flask, jsonify
import email_seguranca as seguranca
import gmail_sync_paginacao as pagina
from test_email_p0 import carregar_funcoes


class Banco:
    def __init__(self):
        self.token = None
        self.complete = set()
        self.pending = []
        self.states = {}
        self.rows = {}
        self.lock = True
        self.pause = True
        self.saved = 0
        self.closed = 0
    def __call__(self): return self
    def __enter__(self): self.snapshot = self.token; return self
    def __exit__(self, exc, *_):
        if exc: self.token = self.snapshot
    def cursor(self, **kwargs): return Cursor(self)
    def commit(self): pass
    def close(self): self.closed += 1


class Cursor:
    def __init__(self, b): self.b=b; self.result=None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()):
        sql=' '.join(sql.split())
        if 'FROM gmail_oauth_credentials' in sql:
            self.result={'refresh_token':'synthetic','token_uri':'synthetic','client_id':'synthetic','client_secret':'synthetic','scopes':''}
        elif sql.startswith('SELECT pg_try_advisory_lock'): self.result=(self.b.lock,)
        elif sql.startswith('SELECT page_token'): self.result=(self.b.token,)
        elif sql.startswith('SELECT i.message_id'):
            self.result=[(mid,) for mid in self.b.pending if mid not in self.b.complete][:args[0]]
        elif sql.startswith('SELECT message_id'):
            self.result=[(mid,) for mid in args[0] if mid in self.b.complete]
        elif sql.startswith('UPDATE gmail_sync_cursor'):
            self.b.token=args[0];self.b.saved+=1
        elif sql.startswith('SELECT pg_advisory_xact_lock'): pass
        elif sql.startswith('SELECT estado'):
            self.result=(self.b.states[args[0]],) if args[0] in self.b.states else None
        elif sql.startswith('INSERT INTO gmail_processamentos'): self.b.states[args[0]]='pendente'
        elif sql.startswith('UPDATE gmail_processamentos'):
            self.b.states[args[-1]]='concluido' if "estado='concluido'" in sql else 'falhou'
        elif sql.startswith('UPDATE interacoes_omnichannel'):
            self.b.complete.add(args[0]);self.b.rows[args[0]]['processado_ia']=True
        else: raise AssertionError(sql)
    def fetchone(self): return self.result
    def fetchall(self): return self.result


def response(ids=(), token=None, status=200):
    data={'messages':[{'id':i} for i in ids]}
    if token is not None: data['nextPageToken']=token
    r=Mock(status_code=status);r.json.return_value=data
    if status>=400:r.raise_for_status.side_effect=RuntimeError('HTTP synthetic')
    return r


class Paginacao(unittest.TestCase):
    def setUp(self):
        self.b=Banco()
        self.net=patch('requests.sessions.Session.request',side_effect=AssertionError('rede real proibida'))
        self.net.start();self.addCleanup(self.net.stop)

    def test_avanca_alem_das_vinte_concluidas(self):
        self.b.complete={f'm{i}' for i in range(20)}
        http=Mock();http.get.side_effect=[response(sorted(self.b.complete),'page2'),response(['antiga'])]
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertEqual(lote.mensagens,[{'id':'antiga'}]);lote.confirmar()
        self.assertEqual(http.get.call_args_list[1].kwargs['params']['pageToken'],'page2')
        self.assertEqual(self.b.token,None)
        self.assertTrue(all(c.kwargs['allow_redirects'] is False for c in http.get.call_args_list))
        http.post.assert_not_called()

    def test_limite_vinte_checkpoint_e_retomada_sem_pular_pagina(self):
        http=Mock();http.get.return_value=response([f'm{i}' for i in range(20)],'restante')
        with pagina.selecionar_lote(self.b,'synthetic',limite=999,http=http) as lote:
            self.assertEqual(len(lote.mensagens),20)
            self.assertEqual(lote.paginas,1)
            self.assertIsNone(self.b.token)
            lote.confirmar()
        self.assertEqual(self.b.token,'restante')
        http.get.return_value=response(['antiga'])
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertEqual(lote.mensagens,[{'id':'antiga'}]);lote.confirmar()
        self.assertEqual(http.get.call_args.kwargs['params']['pageToken'],'restante')

    def test_cinco_paginas_maximo_com_cursor_para_proxima_execucao(self):
        self.b.complete={'concluida'}
        http=Mock();http.get.side_effect=[response(['concluida'],f'p{i}') for i in range(1,6)]
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertEqual(lote.paginas,5);self.assertEqual(lote.mensagens,[]);lote.confirmar()
        self.assertEqual(self.b.token,'p5');self.assertEqual(http.get.call_count,5)

    def test_falha_e_crash_nao_avancam_cursor(self):
        self.b.token='inicial';http=Mock();http.get.return_value=response(['nova'],'seguinte')
        with self.assertRaises(RuntimeError):
            with pagina.selecionar_lote(self.b,'synthetic',limite=1,http=http):raise RuntimeError('crash')
        self.assertEqual(self.b.token,'inicial');self.assertEqual(self.b.saved,0)
        self.assertEqual(self.b.closed,1)

    def test_cursor_expirado_reinicia_uma_vez(self):
        self.b.token='expirado';http=Mock();http.get.side_effect=[response(status=400),response(['nova'])]
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertEqual(lote.mensagens,[{'id':'nova'}]);lote.confirmar()
        self.assertNotIn('pageToken',http.get.call_args.kwargs['params'])

    def test_token_repetido_e_pagina_invalida_nao_confirmam(self):
        for respostas in ([response([], 'loop'),response([], 'loop')], [response(['bad/id'])]):
            http=Mock();http.get.side_effect=respostas
            with self.assertRaises(ValueError):
                with pagina.selecionar_lote(self.b,'synthetic',http=http):pass
            self.assertEqual(self.b.saved,0)

    def test_pendentes_e_repeticoes_nas_paginas_deduplicados(self):
        self.b.pending=['antiga'];http=Mock()
        http.get.side_effect=[response(['antiga','nova'],'p2'),response(['nova'])]
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertEqual(lote.mensagens,[{'id':'antiga'},{'id':'nova'}])
        self.assertEqual(http.get.call_args_list[0].kwargs['params']['maxResults'],19)

    def test_sobreposicao_nao_chama_gmail_nem_avanca(self):
        self.b.lock=False;http=Mock()
        with pagina.selecionar_lote(self.b,'synthetic',http=http) as lote:
            self.assertTrue(lote.ocupado);lote.confirmar()
        self.assertEqual(self.b.saved,0);http.get.assert_not_called()

    def endpoint(self, pages, fail=False):
        self.b.rows.setdefault('antiga',{'id':'antiga','processado_ia':False})
        def register(**kw):
            mid=kw['message_id'];duplicate=mid in self.b.rows
            row=self.b.rows.setdefault(mid,{'id':mid,'processado_ia':False})
            return {'success':True,'duplicada':duplicate,'interacao':copy.deepcopy(row)}
        def classify(item):
            self.assertTrue(seguranca._bloqueio_contexto.get())
            with self.assertRaises(seguranca.EnvioBloqueado):
                seguranca.verificar_envio(Mock(),'teste@example.invalid')
            if fail:raise RuntimeError('classificador indisponível')
            self.b.rows[item['id']]['classificacao']='interesse_comercial'
            return {'success':True}
        processor=Mock(side_effect=classify)
        ns=dict(validar_admin_request=lambda:True,get_db_connection=self.b,RealDictCursor=object,
                jsonify=jsonify,base64=base64,bloquear_envios_no_contexto=seguranca.bloquear_envios_no_contexto,
                definir_pausa=Mock(),processar_dsn_gmail=Mock(return_value=False),
                registrar_interacao_omnichannel=register,processar_interacao_omnichannel_crm=processor)
        carregar_funcoes('main.py',['gmail_sincronizar','gmail_buscar_mensagens','gmail_importar_mensagem_p0'],ns)
        app=Flask('gmail-paginacao');app.add_url_rule('/api/gmail/sincronizar',view_func=ns['gmail_sincronizar'])
        def get(url,**kwargs):
            if kwargs.get('params',{}).get('format')=='full':
                self.assertTrue(seguranca._bloqueio_contexto.get())
                r=response();r.json.return_value={'id':url.rsplit('/',1)[1],'payload':{},'snippet':'Teste'};return r
            return pages.pop(0)
        with patch('google.oauth2.credentials.Credentials',return_value=Mock(valid=True,token='synthetic')),patch('requests.get',side_effect=get):
            result=app.test_client().get('/api/gmail/sincronizar')
        return result,processor

    def test_endpoint_processa_pendente_fora_da_inbox_e_retry_nao_reclassifica(self):
        self.b.pending=['antiga']
        result,processor=self.endpoint([response([])])
        self.assertEqual(result.status_code,200);self.assertTrue(result.json['success'])
        self.assertFalse(result.json['envios_automaticos_permitidos'])
        self.assertTrue(self.b.rows['antiga']['processado_ia'])
        self.assertEqual(self.b.rows['antiga']['classificacao'],'interesse_comercial')
        self.assertEqual(self.b.states['antiga'],'concluido');processor.assert_called_once()
        result,processor=self.endpoint([response(['antiga'])])
        self.assertEqual(result.status_code,200);processor.assert_not_called()

    def test_endpoint_falha_na_pendente_preserva_cursor_e_retomada(self):
        self.b.pending=['antiga'];self.b.token='retomar'
        result,_=self.endpoint([response([])],fail=True)
        self.assertEqual(result.status_code,502);self.assertFalse(result.json['success'])
        self.assertEqual(self.b.token,'retomar');self.assertEqual(self.b.saved,0)
        self.assertEqual(self.b.states['antiga'],'falhou')
        result,_=self.endpoint([response([])])
        self.assertTrue(result.json['success']);self.assertEqual(self.b.states['antiga'],'concluido')


if __name__=='__main__':unittest.main()
