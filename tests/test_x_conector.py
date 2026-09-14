"""X: fail-closed sem credenciais, PKCE real, nunca publica sem aprovação."""
import os
import unittest
from unittest.mock import patch

import x_conector as x


class Status(unittest.TestCase):
    def test_sem_credenciais_fica_pendente(self):
        with patch.dict('os.environ', {}, clear=True):
            s = x.status()
        self.assertFalse(s['conectado'])
        self.assertEqual(s['motivo_pendente'], 'credenciais_ausentes')

    def test_com_token_e_app_fica_conectado(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a', 'X_ACCESS_TOKEN': 'c'}, clear=True):
            s = x.status()
        self.assertTrue(s['conectado'])
        self.assertFalse(s['renovavel'])

    def test_com_refresh_token_fica_renovavel(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a', 'X_ACCESS_TOKEN': 'c', 'X_REFRESH_TOKEN': 'r'}, clear=True):
            s = x.status()
        self.assertTrue(s['renovavel'])


class Autorizacao(unittest.TestCase):
    def test_url_usa_menor_privilegio_e_pkce(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'abc'}, clear=True):
            url, state, verifier = x.montar_url_autorizacao('https://y/callback')
        self.assertIn('tweet.read', url)
        self.assertIn('code_challenge=', url)
        self.assertTrue(verifier)

    def test_sem_client_id_recusa(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(x.XNaoConfigurado):
                x.montar_url_autorizacao('https://y/callback')


class Publicacao(unittest.TestCase):
    def test_nunca_publica_sem_aprovacao_previa(self):
        with self.assertRaises(PermissionError):
            x.publicar_post('texto', aprovado_por=None)

    @patch('x_conector.requests.post')
    def test_com_aprovacao_chama_api(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'data': {'id': '1'}}
        with patch.dict('os.environ', {'X_ACCESS_TOKEN': 't'}, clear=True):
            r = x.publicar_post('texto', aprovado_por='diretor')
        self.assertTrue(r['success'])
        post_mock.assert_called_once()


class LeituraPerfilETweets(unittest.TestCase):
    def test_sem_token_recusa_leituras(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(x.XNaoConfigurado):
                x.ler_metricas_usuario()
            with self.assertRaises(x.XNaoConfigurado):
                x.ler_tweets_recentes()

    @patch('x_conector.requests.get')
    def test_com_token_le_perfil(self, get_mock):
        get_mock.return_value.raise_for_status.return_value = None
        get_mock.return_value.json.return_value = {'data': {'id': 'u1'}}
        with patch.dict('os.environ', {'X_ACCESS_TOKEN': 't'}, clear=True):
            x.ler_metricas_usuario()
        self.assertIn('/users/me', get_mock.call_args.args[0])

    @patch('x_conector.requests.get')
    def test_com_token_le_tweets_recentes_via_user_id(self, get_mock):
        get_mock.return_value.raise_for_status.return_value = None
        get_mock.return_value.json.return_value = {'data': {'id': 'u1'}}
        with patch.dict('os.environ', {'X_ACCESS_TOKEN': 't'}, clear=True):
            x.ler_tweets_recentes()
        self.assertIn('/users/u1/tweets', get_mock.call_args.args[0])


class RenovacaoToken(unittest.TestCase):
    def test_sem_refresh_token_recusa(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a'}, clear=True):
            with self.assertRaises(x.XNaoConfigurado):
                x.renovar_token()

    @patch('x_conector.requests.post')
    def test_com_refresh_token_chama_api(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'access_token': 'novo', 'expires_in': 7200}
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a', 'X_REFRESH_TOKEN': 'r'}, clear=True):
            r = x.renovar_token()
        self.assertEqual(r['access_token'], 'novo')
        post_mock.assert_called_once()


class RevogacaoLocal(unittest.TestCase):
    def tearDown(self):
        x.reconectar_localmente()

    def test_revogar_localmente_nao_apaga_env_var_so_ignora_em_processo(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a', 'X_ACCESS_TOKEN': 'c'}, clear=True):
            self.assertTrue(x.status()['conectado'])
            x.revogar_localmente()
            s = x.status()
            self.assertFalse(s['conectado'])
            self.assertEqual(s['motivo_pendente'], 'desconectado_localmente')
            self.assertEqual(os.environ['X_ACCESS_TOKEN'], 'c')  # env var intacta
            x.reconectar_localmente()
            self.assertTrue(x.status()['conectado'])


class Rotas(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        x.reconectar_localmente()
        x._estados_pendentes.clear()
        self.app = Flask(__name__)
        self.autorizado = True
        x.registrar_rotas_x(self.app, lambda: self.autorizado)
        self.client = self.app.test_client()

    def tearDown(self):
        x.reconectar_localmente()
        x._estados_pendentes.clear()

    def test_status_e_connect_exigem_admin_key(self):
        self.autorizado = False
        self.assertEqual(self.client.get('/api/admin/x/status').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/x/connect').status_code, 401)

    def test_connect_sem_client_id_recusa_com_412(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/x/connect')
        self.assertEqual(r.status_code, 412)

    def test_connect_retorna_url_e_guarda_state_com_verifier(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'abc'}, clear=True):
            r = self.client.get('/api/admin/x/connect')
        self.assertEqual(r.status_code, 200)
        corpo = r.get_json()
        self.assertTrue(corpo['url'].startswith(x.AUTH_URL))
        self.assertEqual(len(x._estados_pendentes), 1)
        entrada = list(x._estados_pendentes.values())[0]
        self.assertIn('verifier', entrada)

    def test_callback_sem_state_valido_recusa(self):
        r = self.client.get('/api/admin/x/callback?state=inventado&code=x')
        self.assertEqual(r.status_code, 400)

    def test_callback_com_erro_do_x_recusa(self):
        r = self.client.get('/api/admin/x/callback?error=access_denied')
        self.assertEqual(r.status_code, 400)

    @patch('x_conector.requests.post')
    def test_callback_com_state_valido_troca_code_e_state_e_de_uso_unico(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'access_token': 'tok123', 'refresh_token': 'ref123', 'expires_in': 7200}
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a'}, clear=True):
            r1 = self.client.get('/api/admin/x/connect')
            state = r1.get_json()['url'].split('state=')[1].split('&')[0]
            r2 = self.client.get(f'/api/admin/x/callback?state={state}&code=xyz')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['access_token'], 'tok123')
        self.assertEqual(r2.get_json()['refresh_token'], 'ref123')
        self.assertEqual(len(x._estados_pendentes), 0)  # consumido, uso único
        r3 = self.client.get(f'/api/admin/x/callback?state={state}&code=xyz')
        self.assertEqual(r3.status_code, 400)

    def test_testar_sem_configuracao_e_fail_closed(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/x/testar')
        self.assertEqual(r.status_code, 412)

    def test_desconectar_e_reconectar_exigem_admin_key_e_alteram_status(self):
        self.autorizado = False
        self.assertEqual(self.client.post('/api/admin/x/desconectar').status_code, 401)
        self.autorizado = True
        with patch.dict('os.environ', {'X_CLIENT_ID': 'a', 'X_ACCESS_TOKEN': 'c'}, clear=True):
            r = self.client.post('/api/admin/x/desconectar')
            self.assertFalse(r.get_json()['status']['conectado'])
            r = self.client.post('/api/admin/x/reconectar')
            self.assertTrue(r.get_json()['status']['conectado'])


if __name__ == '__main__':
    unittest.main()
