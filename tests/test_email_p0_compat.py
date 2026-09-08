"""Regressões pré-deploy: todos os transportes e bancos são simulados."""
import base64
import os
from unittest.mock import Mock, patch
import email_seguranca as seguranca
import gmail_sync_job as job
import test_email_p0 as f


class Job(f.Offline):
    def setUp(self):
        super().setUp()
        os.environ.update(ADMIN_API_KEY='admin-sintetico', FASE58_CRON_SECRET='cron-sintetico')

    def test_sync_falhou_nao_chama_fase58(self):
        respostas = [
            Mock(status_code=401), Mock(status_code=500), Mock(status_code=302),
            Mock(status_code=200, json=Mock(return_value={'success': False})),
            Mock(status_code=200, json=Mock(return_value={'success': True})),
            Mock(status_code=200, json=Mock(return_value={'success': True, 'prospeccao_permitida': True, 'erros': ['dsn']})),
            Mock(status_code=200, json=Mock(return_value=[])),
            Mock(status_code=200, json=Mock(side_effect=ValueError('json inválido'))),
        ]
        for resposta in respostas:
            with self.subTest(resposta=resposta):
                http = Mock(get=Mock(return_value=resposta))
                with self.assertRaises((job.JobAbortado, ValueError)):
                    job.executar_job(http)
                http.post.assert_not_called()

    def test_timeout_nao_chama_fase58(self):
        http = Mock(get=Mock(side_effect=TimeoutError('sintetico')))
        with self.assertRaises(TimeoutError):
            job.executar_job(http)
        http.post.assert_not_called()

    def test_job_autenticado_sequencial_sem_redirects(self):
        http = Mock()
        http.get.return_value = Mock(status_code=200, json=Mock(return_value={'success': True, 'prospeccao_permitida': True, 'erros': []}))
        http.post.return_value = Mock(status_code=200, json=Mock(return_value={'success': True, 'fase58b': {'success': True}}))
        self.assertTrue(job.executar_job(http)['success'])
        self.assertEqual([c[0] for c in http.method_calls], ['get'])
        self.assertEqual(http.get.call_args.kwargs['headers'], {'X-Admin-Key': 'admin-sintetico'})
        http.post.assert_not_called()
        self.assertFalse(http.get.call_args.kwargs['allow_redirects'])

    def test_configuracao_ausente_aborta_antes_de_http(self):
        os.environ.pop('ADMIN_API_KEY')
        http = Mock()
        with self.assertRaises(job.JobAbortado):
            job.executar_job(http)
        self.assertFalse(http.method_calls)

    def test_cli_erro_nao_expoe_detalhes(self):
        with patch.object(job, 'executar_job', side_effect=RuntimeError('segredo-nao-imprimir')), patch('builtins.print') as saida:
            self.assertEqual(job.main(), 1)
            self.assertNotIn('segredo-nao-imprimir', str(saida.call_args))


class Importacao(f.Offline):
    def namespace(self, processador=None):
        ns = dict(
            base64=base64, definir_pausa=seguranca.definir_pausa,
            bloquear_envios_no_contexto=seguranca.bloquear_envios_no_contexto,
            processar_dsn_gmail=seguranca.processar_dsn_gmail,
            get_db_connection=self.banco,
            registrar_interacao_omnichannel=Mock(side_effect=lambda **kw: {'success': True, 'duplicada': False, 'interacao': kw}),
            processar_interacao_omnichannel_crm=processador or Mock(return_value={'success': True}),
        )
        f.carregar_funcoes('main.py', ['gmail_importar_mensagem_p0', 'gmail_buscar_mensagens'], ns)
        return ns

    def test_dsn_malformado_preserva_restante_e_bloqueia_envio(self):
        dados = [
            {'id': 'bounce', 'payload': {'mimeType': 'multipart/report'}, 'snippet': 'Relatório malformado'},
            {'id': 'normal', 'payload': {'mimeType': 'text/plain'}, 'snippet': 'Temos interesse'},
        ]
        def processar(_):
            banco = Mock()
            with self.assertRaises(seguranca.EnvioBloqueado):
                seguranca.verificar_envio(banco, 'bom@example.com')
            banco.assert_not_called()
            return {'success': True}
        ns = self.namespace(Mock(side_effect=processar))
        respostas = [f.resposta_json({'messages': [{'id': x['id']} for x in dados]}), f.resposta_json(dados[0]), f.resposta_json({'raw': '!!!invalid!!!'}), f.resposta_json(dados[1])]
        with patch('requests.get', side_effect=respostas):
            r = ns['gmail_buscar_mensagens']('token-sintetico')
        self.assertFalse(r['success'])
        self.assertFalse(r['prospeccao_permitida'])
        self.assertEqual(ns['registrar_interacao_omnichannel'].call_count, 2)
        ns['processar_interacao_omnichannel_crm'].assert_called_once()
        self.assertTrue(self.banco.pausado)
        self.assertTrue(r['mensagens'][1]['processado'])

    def test_erro_individual_detalhe_nao_interrompe_proxima(self):
        ns = self.namespace()
        falhou = f.resposta_json({})
        falhou.raise_for_status.side_effect = RuntimeError('erro de rede sintético')
        respostas = [f.resposta_json({'messages': [{'id': 'ruim'}, {'id': 'boa'}]}), falhou, f.resposta_json({'id': 'boa', 'payload': {}, 'snippet': 'Olá'})]
        with patch('requests.get', side_effect=respostas):
            r = ns['gmail_buscar_mensagens']('sintetico')
        self.assertFalse(r['success'])
        ns['registrar_interacao_omnichannel'].assert_called_once()
        self.assertEqual(r['mensagens'][1]['gmail_id'], 'boa')

    def test_erro_registro_isolado(self):
        ns = self.namespace()
        ns['registrar_interacao_omnichannel'].side_effect = [RuntimeError('erro sintético'), {'success': True, 'interacao': {}}]
        with patch('requests.get', side_effect=[f.resposta_json({'messages': [{'id': 'a'}, {'id': 'b'}]})] + [f.resposta_json({'id': x, 'payload': {}}) for x in ('a', 'b')]):
            r = ns['gmail_buscar_mensagens']('sintetico')
        self.assertFalse(r['success'])
        self.assertTrue(r['mensagens'][1]['registrado'])

    def test_falha_pausa_banco_mantem_trava_local(self):
        ns = self.namespace()
        ns['definir_pausa'] = Mock(side_effect=RuntimeError('banco indisponível'))
        ns['processar_dsn_gmail'] = Mock(side_effect=[ValueError('dsn ruim'), False])
        def processar(_):
            with self.assertRaises(seguranca.EnvioBloqueado):
                seguranca.verificar_envio(Mock(), 'bom@example.com')
            return {'success': True}
        ns['processar_interacao_omnichannel_crm'].side_effect = processar
        with patch('requests.get', side_effect=[f.resposta_json({'messages': [{'id': 'a'}, {'id': 'b'}]})] + [f.resposta_json({'id': x, 'payload': {}}) for x in ('a', 'b')]):
            r = ns['gmail_buscar_mensagens']('sintetico')
        self.assertEqual([e['etapa'] for e in r['erros']], ['dsn', 'persistir_pausa'])
        ns['processar_interacao_omnichannel_crm'].assert_called_once()
        # O bloqueio local não vaza para outra requisição; banco saudável decide.
        seguranca.verificar_envio(self.banco, 'bom@example.com')

    def test_dsn_defeito_mime_rejeitado(self):
        raw = b'From: mailer-daemon@example.com\nContent-Type: multipart/report; report-type=delivery-status; boundary="ausente"\n\ncorpo sem boundary'
        with self.assertRaises(ValueError):
            seguranca.extrair_hard_bounces(raw)

    def test_listagem_falhou_aborta_sem_processar(self):
        ns = self.namespace()
        with patch('requests.get', side_effect=RuntimeError('falha sintética')):
            r = ns['gmail_buscar_mensagens']('sintetico')
        self.assertFalse(r['success'])
        self.assertTrue(self.banco.pausado)
        ns['processar_interacao_omnichannel_crm'].assert_not_called()

    def test_payload_nulo_nao_interrompe_lote(self):
        ns = self.namespace()
        with patch('requests.get', side_effect=[f.resposta_json({'messages': [{'id': 'a'}, {'id': 'b'}]}), f.resposta_json({'id': 'a', 'payload': None}), f.resposta_json({'id': 'b', 'payload': {'headers': [{'name': 'Subject', 'value': None}]}})]):
            r = ns['gmail_buscar_mensagens']('sintetico')
        self.assertFalse(r['success'])
        self.assertTrue(r['mensagens'][1]['registrado'])
