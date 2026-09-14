"""X: fail-closed sem credenciais, PKCE real, nunca publica sem aprovação."""
import unittest
from unittest.mock import patch

import x_conector as x


class Status(unittest.TestCase):
    def test_sem_credenciais_fica_pendente(self):
        with patch.dict('os.environ', {}, clear=True):
            s = x.status()
        self.assertFalse(s['conectado'])
        self.assertEqual(s['motivo_pendente'], 'credenciais_ausentes')


class Autorizacao(unittest.TestCase):
    def test_url_usa_menor_privilegio_e_pkce(self):
        with patch.dict('os.environ', {'X_CLIENT_ID': 'abc'}, clear=True):
            url, state, verifier = x.montar_url_autorizacao('https://y/callback')
        self.assertIn('tweet.read', url)
        self.assertIn('code_challenge=', url)
        self.assertTrue(verifier)


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


if __name__ == '__main__':
    unittest.main()
