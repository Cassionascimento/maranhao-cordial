"""LinkedIn: fail-closed sem credenciais, nunca publica sem aprovação, nunca expõe token."""
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


if __name__ == '__main__':
    unittest.main()
