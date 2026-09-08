import os
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import test_email_p0 as f
import prospeccao_render_job as job
import prospeccao_fonte_publica as fonte


class Fontes(f.Offline):
    def test_email_institucional_publicado(self):
        fetch = Mock(return_value=('https://www.empresa.com.br/contato', '<p>comercial@empresa.com.br</p>'))
        self.assertTrue(fonte.validar_associacao('comercial@empresa.com.br', 'https://empresa.com.br', fetch)[0])

    def test_exemplo_terceiro_e_script_nao_qualificam(self):
        for email, page in [('contato@site.com.br','contato@site.com.br'),
                            ('a@outro.com.br','a@outro.com.br'),
                            ('a@empresa.com.br','<script>a@empresa.com.br</script>')]:
            self.assertFalse(fonte.validar_associacao(email, 'https://empresa.com.br', Mock(return_value=('https://empresa.com.br',page)))[0])

    def test_fonte_indisponivel_exclusao_normal(self):
        self.assertFalse(fonte.validar_associacao('a@empresa.com.br', 'https://empresa.com.br', Mock(side_effect=TimeoutError))[0])

    def test_ip_privado_nao_recebe_requisicao(self):
        with patch.object(fonte.socket, 'getaddrinfo', return_value=[(None,None,None,None,('127.0.0.1',443))]), patch.object(fonte.urllib3,'HTTPSConnectionPool') as pool:
            with self.assertRaises(ValueError):
                fonte.pagina_publica('https://empresa.com.br')
        pool.assert_not_called()

    def test_https_ip_fixado_tls_e_sem_retry(self):
        resp = Mock(status=200, headers={'Content-Type':'text/html'}, read=Mock(return_value=b'email'))
        pool = Mock()
        pool.urlopen.return_value = resp
        manager = Mock()
        manager.__enter__ = Mock(return_value=pool)
        manager.__exit__ = Mock(return_value=False)
        with patch.object(fonte.socket,'getaddrinfo',return_value=[(None,None,None,None,('93.184.216.34',443))]), patch.object(fonte.urllib3,'HTTPSConnectionPool',return_value=manager) as make:
            self.assertEqual(fonte.pagina_publica('https://empresa.com.br/contato')[1], 'email')
        self.assertEqual(make.call_args.args[0], '93.184.216.34')
        self.assertEqual(make.call_args.kwargs['assert_hostname'], 'empresa.com.br')
        self.assertFalse(pool.urlopen.call_args.kwargs['retries'])


class Cron(f.Offline):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, PROSPECCAO_RENDER_MODO='ativo',
                                    PROSPECCAO_RENDER_INICIO='2026-09-09', EMAIL_ENVIOS_PAUSADOS='true'))
        self.agora = datetime(2026,9,9,10,0,tzinfo=ZoneInfo('America/Sao_Paulo'))
        self.gmail = Mock()
        self.gmail.users().messages().list().execute.return_value = {'messages':[{'id':'gmail'}]}
        self.db = Mock()
        self.cur = Mock(fetchone=Mock(return_value=(True,)),fetchall=Mock(return_value=[('campanha',)]))
        self.db.cursor.return_value.__enter__ = Mock(return_value=self.cur)
        self.db.cursor.return_value.__exit__ = Mock(return_value=False)
        self.factory = Mock(return_value=self.db)
        self.enterContext(patch.object(job,'dependencias',return_value=(self.gmail,{'bloqueado':False})))
        self.enterContext(patch.object(job,'pausa_rotineira'))
        self.pause = self.enterContext(patch.object(job,'definir_pausa'))
        self.sync = self.enterContext(patch.object(job,'sincronizar'))
        self.research = self.enterContext(patch.object(job,'executar_pesquisa_publica_fase57',return_value={'success':True,'executada':True}))
        self.enterContext(patch.object(job,'garantir_pesquisa_se_faltar_fase57'))
        self.enterContext(patch.object(job,'evento'))
        self.enterContext(patch.object(job,'verificar_resultado'))

    def test_seguro_nunca_despausa_pesquisa_ou_envia(self):
        with patch.dict(os.environ,PROSPECCAO_RENDER_MODO='seguro'), patch.object(job,'enviar_primeiro_contato_fase57') as send:
            r = job.executar(self.factory,self.agora)
        self.assertEqual(r['envios'],0)
        send.assert_not_called()
        self.pause.assert_not_called()
        self.research.assert_not_called()
        self.sync.assert_not_called()

    def test_hoje_e_fim_de_semana_nunca_enviam(self):
        for d in (8,12,13):
            r = job.executar(self.factory,datetime(2026,9,d,10,tzinfo=ZoneInfo('America/Sao_Paulo')))
            self.assertEqual(r['motivo'],'fora_da_janela')
        self.pause.assert_not_called()

    def test_dois_no_contador_nao_faz_sync_nem_reserva(self):
        with patch.object(job,'dependencias',return_value=(self.gmail,{'bloqueado':True})):
            r=job.executar(self.factory,self.agora)
        self.assertEqual(r['motivo'],'cota_diaria')
        self.sync.assert_not_called()
        self.pause.assert_not_called()

    def test_concorrente_nao_prossegue(self):
        self.cur.fetchone.return_value=(False,)
        r=job.executar(self.factory,self.agora)
        self.assertEqual(r['motivo'],'rodada_em_andamento')
        self.pause.assert_not_called()

    def test_inelegivel_nao_consume_e_continua_ate_valido(self):
        items=[{'id':'1','email':'nao@exemplo.com','fonte_url':'https://exemplo.com'},
               {'id':'2','email':'sim@empresa.com.br','fonte_url':'https://empresa.com.br'}]
        used={'n':1}
        def send(*_):
            self.assertEqual(os.environ['EMAIL_ENVIOS_PAUSADOS'],'false')
            used['n']+=1
            return {'enviado':True,'message_id':'gmail','thread_id':'thread'}
        with patch.object(job,'candidatos',return_value=items), patch.object(job,'validar_associacao',side_effect=[(False,'não verificável'),(True,'fonte')]), patch.object(job,'status',side_effect=lambda _: {'bloqueado':used['n']>=2,'usados':used['n']}), patch.object(job,'enviar_primeiro_contato_fase57',side_effect=send) as sender:
            r=job.executar(self.factory,self.agora)
        sender.assert_called_once()
        self.assertEqual((r['envios'],r['excluidos'],r['contador']['usados']),(1,1,2))
        self.assertEqual(os.environ['EMAIL_ENVIOS_PAUSADOS'],'true')

    def test_ausencia_candidatos_e_tres_pesquisas_sucesso_normal(self):
        with patch.object(job,'candidatos',return_value=[]), patch.object(job,'status',return_value={'bloqueado':False}):
            r=job.executar(self.factory,self.agora)
        self.assertTrue(r['success'])
        self.assertEqual(r['pesquisas'],3)
        self.pause.assert_not_called()

    def test_falha_gmail_restabelece_pausa_sem_segundo_envio(self):
        with patch.object(job,'candidatos',return_value=[{'id':'1','email':'a@empresa.com.br','fonte_url':'https://empresa.com.br'}]), patch.object(job,'validar_associacao',return_value=(True,'fonte')), patch.object(job,'status',return_value={'bloqueado':False}), patch.object(job,'enviar_primeiro_contato_fase57',side_effect=TimeoutError) as send:
            with self.assertRaises(TimeoutError):
                job.executar(self.factory,self.agora)
        send.assert_called_once()
        self.pause.assert_called_with(self.factory,True,job.INCIDENTE)
        self.assertEqual(os.environ['EMAIL_ENVIOS_PAUSADOS'],'true')
