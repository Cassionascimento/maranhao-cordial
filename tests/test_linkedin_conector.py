"""LinkedIn: fail-closed sem credenciais, nunca publica sem aprovação, nunca expõe token."""
import os
import unittest
from unittest.mock import patch

import linkedin_conector as li


class Status(unittest.TestCase):
    def test_sem_credenciais_fica_pendente_sem_inventar_conectado(self):
        with patch.dict('os.environ', {}, clear=True):
            s = li.status()
        self.assertFalse(s['conectado'])
        self.assertEqual(s['motivo_pendente'], 'credenciais_ausentes')
        self.assertNotIn('access_token', s)

    def test_com_token_e_app_fica_conectado(self):
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'a', 'LINKEDIN_CLIENT_SECRET': 'b',
                                        'LINKEDIN_ACCESS_TOKEN': 'c'}, clear=True):
            s = li.status()
        self.assertTrue(s['conectado'])


class Autorizacao(unittest.TestCase):
    def test_sem_client_id_recusa(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(li.LinkedInNaoConfigurado):
                li.montar_url_autorizacao('https://x/callback')

    def test_url_usa_escopos_de_organizacao_por_padrao_e_gera_state(self):
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'abc'}, clear=True):
            url, state = li.montar_url_autorizacao('https://x/callback')
        self.assertIn('r_organization_social', url)
        self.assertIn('rw_organization_admin', url)
        self.assertTrue(state)
        self.assertIn(state, url)


class Publicacao(unittest.TestCase):
    def test_nunca_publica_sem_aprovacao_previa(self):
        with self.assertRaises(PermissionError):
            li.publicar_post_organizacao('texto', aprovado_por=None)

    @patch('linkedin_conector.requests.post')
    def test_com_aprovacao_chama_api_mas_nunca_sem_ela(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.headers = {'x-restli-id': 'urn:li:share:1'}
        with patch.dict('os.environ', {'LINKEDIN_ACCESS_TOKEN': 't', 'LINKEDIN_ORGANIZATION_URN': 'urn:li:organization:1'}, clear=True):
            r = li.publicar_post_organizacao('texto', aprovado_por='diretor')
        self.assertTrue(r['success'])
        post_mock.assert_called_once()


class LeituraPostsEAnalytics(unittest.TestCase):
    def test_sem_organization_urn_recusa_ambas(self):
        with patch.dict('os.environ', {'LINKEDIN_ACCESS_TOKEN': 't'}, clear=True):
            with self.assertRaises(li.LinkedInNaoConfigurado):
                li.ler_posts_organizacao()
            with self.assertRaises(li.LinkedInNaoConfigurado):
                li.ler_engajamento_e_analytics()

    @patch('linkedin_conector.requests.get')
    def test_com_config_chama_endpoint_de_share_statistics(self, get_mock):
        get_mock.return_value.raise_for_status.return_value = None
        get_mock.return_value.json.return_value = {'elements': []}
        with patch.dict('os.environ', {'LINKEDIN_ACCESS_TOKEN': 't', 'LINKEDIN_ORGANIZATION_URN': 'urn:li:organization:1'}, clear=True):
            li.ler_engajamento_e_analytics()
        self.assertIn('organizationalEntityShareStatistics', get_mock.call_args.args[0])


class RevogacaoLocal(unittest.TestCase):
    def tearDown(self):
        li.reconectar_localmente()

    def test_revogar_localmente_nao_apaga_env_var_so_ignora_em_processo(self):
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'a', 'LINKEDIN_CLIENT_SECRET': 'b', 'LINKEDIN_ACCESS_TOKEN': 'c'}, clear=True):
            self.assertTrue(li.status()['conectado'])
            li.revogar_localmente()
            s = li.status()
            self.assertFalse(s['conectado'])
            self.assertEqual(s['motivo_pendente'], 'desconectado_localmente')
            self.assertEqual(os.environ['LINKEDIN_ACCESS_TOKEN'], 'c')  # env var intacta
            li.reconectar_localmente()
            self.assertTrue(li.status()['conectado'])


class Rotas(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        li.reconectar_localmente()
        li._estados_pendentes.clear()
        self.app = Flask(__name__)
        self.autorizado = True
        li.registrar_rotas_linkedin(self.app, lambda: self.autorizado)
        self.client = self.app.test_client()

    def tearDown(self):
        li.reconectar_localmente()
        li._estados_pendentes.clear()

    def test_status_e_connect_exigem_admin_key(self):
        self.autorizado = False
        self.assertEqual(self.client.get('/api/admin/linkedin/status').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/linkedin/connect').status_code, 401)

    def test_connect_sem_client_id_recusa_com_412(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/linkedin/connect')
        self.assertEqual(r.status_code, 412)

    def test_connect_retorna_url_e_guarda_state(self):
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'abc'}, clear=True):
            r = self.client.get('/api/admin/linkedin/connect')
        self.assertEqual(r.status_code, 200)
        corpo = r.get_json()
        self.assertTrue(corpo['url'].startswith(li.AUTH_URL))
        self.assertEqual(len(li._estados_pendentes), 1)

    def test_callback_sem_state_valido_recusa(self):
        r = self.client.get('/api/admin/linkedin/callback?state=inventado&code=x')
        self.assertEqual(r.status_code, 400)

    def test_callback_com_erro_do_linkedin_recusa(self):
        r = self.client.get('/api/admin/linkedin/callback?error=access_denied')
        self.assertEqual(r.status_code, 400)

    @patch('linkedin_conector.requests.post')
    def test_callback_com_state_valido_troca_code_e_state_e_de_uso_unico(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'access_token': 'tok123', 'expires_in': 3600}
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'a', 'LINKEDIN_CLIENT_SECRET': 'b'}, clear=True):
            r1 = self.client.get('/api/admin/linkedin/connect')
            state = r1.get_json()['url'].split('state=')[1].split('&')[0]
            r2 = self.client.get(f'/api/admin/linkedin/callback?state={state}&code=xyz')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['access_token'], 'tok123')
        self.assertEqual(len(li._estados_pendentes), 0)  # consumido, uso único
        # reusar o mesmo state de novo tem que falhar
        r3 = self.client.get(f'/api/admin/linkedin/callback?state={state}&code=xyz')
        self.assertEqual(r3.status_code, 400)

    def test_testar_sem_configuracao_e_fail_closed(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/linkedin/testar')
        self.assertEqual(r.status_code, 412)

    def test_desconectar_e_reconectar_exigem_admin_key_e_alteram_status(self):
        self.autorizado = False
        self.assertEqual(self.client.post('/api/admin/linkedin/desconectar').status_code, 401)
        self.autorizado = True
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'a', 'LINKEDIN_CLIENT_SECRET': 'b', 'LINKEDIN_ACCESS_TOKEN': 'c'}, clear=True):
            r = self.client.post('/api/admin/linkedin/desconectar')
            self.assertFalse(r.get_json()['status']['conectado'])
            r = self.client.post('/api/admin/linkedin/reconectar')
            self.assertTrue(r.get_json()['status']['conectado'])


if __name__ == '__main__':
    unittest.main()
