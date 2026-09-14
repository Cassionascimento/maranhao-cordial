"""Pinterest: fail-closed sem credenciais, PKCE real, nunca cria Pin sem aprovação."""
import unittest
from unittest.mock import patch

import pinterest_conector as pin


class Status(unittest.TestCase):
    def test_sem_credenciais_fica_pendente(self):
        with patch.dict('os.environ', {}, clear=True):
            s = pin.status()
        self.assertFalse(s['conectado'])
        self.assertEqual(s['motivo_pendente'], 'credenciais_ausentes')


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


if __name__ == '__main__':
    unittest.main()
