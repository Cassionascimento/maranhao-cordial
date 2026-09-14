"""Pinterest: fail-closed sem credenciais, PKCE real, nunca cria Pin sem aprovação."""
import os
import unittest
from unittest.mock import patch

import pinterest_conector as pin


class Status(unittest.TestCase):
    def test_sem_credenciais_fica_pendente(self):
        with patch.dict('os.environ', {}, clear=True):
            s = pin.status()
        self.assertFalse(s['conectado'])
        self.assertEqual(s['motivo_pendente'], 'credenciais_ausentes')

    def test_com_token_e_app_fica_conectado(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b',
                                        'PINTEREST_ACCESS_TOKEN': 'c'}, clear=True):
            s = pin.status()
        self.assertTrue(s['conectado'])
        self.assertFalse(s['renovavel'])

    def test_com_refresh_token_fica_renovavel(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b',
                                        'PINTEREST_ACCESS_TOKEN': 'c', 'PINTEREST_REFRESH_TOKEN': 'r'}, clear=True):
            s = pin.status()
        self.assertTrue(s['renovavel'])


class Pkce(unittest.TestCase):
    def test_gera_verifier_e_challenge_diferentes_e_nao_reversiveis_por_string(self):
        v, c = pin.gerar_pkce()
        self.assertTrue(20 <= len(v) <= 128)
        self.assertNotEqual(v, c)

    def test_url_autorizacao_inclui_pkce_e_escopos_minimos(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'abc'}, clear=True):
            url, state, verifier = pin.montar_url_autorizacao('https://x/callback')
        self.assertIn('code_challenge=', url)
        self.assertIn('pins%3Awrite', url)
        self.assertTrue(verifier)

    def test_sem_client_id_recusa(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(pin.PinterestNaoConfigurado):
                pin.montar_url_autorizacao('https://x/callback')


class CriacaoPin(unittest.TestCase):
    def test_nunca_cria_pin_sem_aprovacao_previa(self):
        with self.assertRaises(PermissionError):
            pin.criar_pin('t', 'https://x', 'https://img', aprovado_por=None)

    @patch('pinterest_conector.requests.post')
    def test_com_aprovacao_chama_api(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'id': '1'}
        with patch.dict('os.environ', {'PINTEREST_ACCESS_TOKEN': 't', 'PINTEREST_BOARD_ID': 'b1'}, clear=True):
            r = pin.criar_pin('t', 'https://x', 'https://img', aprovado_por='diretor')
        self.assertTrue(r['success'])
        post_mock.assert_called_once()


class LeituraPinsEAnalytics(unittest.TestCase):
    def test_sem_token_recusa_leituras(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(pin.PinterestNaoConfigurado):
                pin.ler_pins_de_board('b1')
            with self.assertRaises(pin.PinterestNaoConfigurado):
                pin.ler_analytics_pin('p1', '2024-01-01', '2024-01-31')

    @patch('pinterest_conector.requests.get')
    def test_com_token_le_pins_do_board(self, get_mock):
        get_mock.return_value.raise_for_status.return_value = None
        get_mock.return_value.json.return_value = {'items': []}
        with patch.dict('os.environ', {'PINTEREST_ACCESS_TOKEN': 't'}, clear=True):
            pin.ler_pins_de_board('b1')
        self.assertIn('/boards/b1/pins', get_mock.call_args.args[0])

    @patch('pinterest_conector.requests.get')
    def test_com_token_le_analytics_do_pin(self, get_mock):
        get_mock.return_value.raise_for_status.return_value = None
        get_mock.return_value.json.return_value = {}
        with patch.dict('os.environ', {'PINTEREST_ACCESS_TOKEN': 't'}, clear=True):
            pin.ler_analytics_pin('p1', '2024-01-01', '2024-01-31')
        self.assertIn('/pins/p1/analytics', get_mock.call_args.args[0])


class RenovacaoToken(unittest.TestCase):
    def test_sem_refresh_token_recusa(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b'}, clear=True):
            with self.assertRaises(pin.PinterestNaoConfigurado):
                pin.renovar_token()

    @patch('pinterest_conector.requests.post')
    def test_com_refresh_token_chama_api(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'access_token': 'novo', 'expires_in': 3600}
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b',
                                        'PINTEREST_REFRESH_TOKEN': 'r'}, clear=True):
            r = pin.renovar_token()
        self.assertEqual(r['access_token'], 'novo')
        post_mock.assert_called_once()


class RevogacaoLocal(unittest.TestCase):
    def tearDown(self):
        pin.reconectar_localmente()

    def test_revogar_localmente_nao_apaga_env_var_so_ignora_em_processo(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b',
                                        'PINTEREST_ACCESS_TOKEN': 'c'}, clear=True):
            self.assertTrue(pin.status()['conectado'])
            pin.revogar_localmente()
            s = pin.status()
            self.assertFalse(s['conectado'])
            self.assertEqual(s['motivo_pendente'], 'desconectado_localmente')
            self.assertEqual(os.environ['PINTEREST_ACCESS_TOKEN'], 'c')  # env var intacta
            pin.reconectar_localmente()
            self.assertTrue(pin.status()['conectado'])


class Rotas(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        pin.reconectar_localmente()
        pin._estados_pendentes.clear()
        self.app = Flask(__name__)
        self.autorizado = True
        pin.registrar_rotas_pinterest(self.app, lambda: self.autorizado)
        self.client = self.app.test_client()

    def tearDown(self):
        pin.reconectar_localmente()
        pin._estados_pendentes.clear()

    def test_status_e_connect_exigem_admin_key(self):
        self.autorizado = False
        self.assertEqual(self.client.get('/api/admin/pinterest/status').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/pinterest/connect').status_code, 401)

    def test_connect_sem_client_id_recusa_com_412(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/pinterest/connect')
        self.assertEqual(r.status_code, 412)

    def test_connect_retorna_url_e_guarda_state_com_verifier(self):
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'abc'}, clear=True):
            r = self.client.get('/api/admin/pinterest/connect')
        self.assertEqual(r.status_code, 200)
        corpo = r.get_json()
        self.assertTrue(corpo['url'].startswith(pin.AUTH_URL))
        self.assertEqual(len(pin._estados_pendentes), 1)
        entrada = list(pin._estados_pendentes.values())[0]
        self.assertIn('verifier', entrada)

    def test_callback_sem_state_valido_recusa(self):
        r = self.client.get('/api/admin/pinterest/callback?state=inventado&code=x')
        self.assertEqual(r.status_code, 400)

    def test_callback_com_erro_do_pinterest_recusa(self):
        r = self.client.get('/api/admin/pinterest/callback?error=access_denied')
        self.assertEqual(r.status_code, 400)

    @patch('pinterest_conector.requests.post')
    def test_callback_com_state_valido_troca_code_e_state_e_de_uso_unico(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {'access_token': 'tok123', 'refresh_token': 'ref123', 'expires_in': 3600}
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b'}, clear=True):
            r1 = self.client.get('/api/admin/pinterest/connect')
            state = r1.get_json()['url'].split('state=')[1].split('&')[0]
            r2 = self.client.get(f'/api/admin/pinterest/callback?state={state}&code=xyz')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['access_token'], 'tok123')
        self.assertEqual(r2.get_json()['refresh_token'], 'ref123')
        self.assertEqual(len(pin._estados_pendentes), 0)  # consumido, uso único
        # reusar o mesmo state de novo tem que falhar
        r3 = self.client.get(f'/api/admin/pinterest/callback?state={state}&code=xyz')
        self.assertEqual(r3.status_code, 400)

    def test_testar_sem_configuracao_e_fail_closed(self):
        with patch.dict('os.environ', {}, clear=True):
            r = self.client.get('/api/admin/pinterest/testar')
        self.assertEqual(r.status_code, 412)

    def test_desconectar_e_reconectar_exigem_admin_key_e_alteram_status(self):
        self.autorizado = False
        self.assertEqual(self.client.post('/api/admin/pinterest/desconectar').status_code, 401)
        self.autorizado = True
        with patch.dict('os.environ', {'PINTEREST_CLIENT_ID': 'a', 'PINTEREST_CLIENT_SECRET': 'b',
                                        'PINTEREST_ACCESS_TOKEN': 'c'}, clear=True):
            r = self.client.post('/api/admin/pinterest/desconectar')
            self.assertFalse(r.get_json()['status']['conectado'])
            r = self.client.post('/api/admin/pinterest/reconectar')
            self.assertTrue(r.get_json()['status']['conectado'])


if __name__ == '__main__':
    unittest.main()
