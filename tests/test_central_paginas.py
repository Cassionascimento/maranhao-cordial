"""Central Empresarial -- item B da ordem de UX: o callback OAuth do
Gmail não pode mais terminar numa tela JSON crua. Testa só a função pura
de montagem de HTML (nunca importa main.py)."""
import unittest

from central_paginas import pagina_gmail_callback


class PaginaGmailCallback(unittest.TestCase):
    def test_nunca_e_json_sempre_html_real(self):
        html = pagina_gmail_callback(True, 'Gmail conectado com sucesso.')
        self.assertTrue(html.strip().startswith('<!doctype html>'))
        self.assertNotIn('"success":true', html.replace(' ', ''))

    def test_sucesso_mostra_mensagem_e_identidade_da_central(self):
        html = pagina_gmail_callback(True, 'A caixa institucional já pode ser aberta direto pela Central.')
        self.assertIn('Gmail conectado', html)
        self.assertIn('MARANHÃO CORDIAL', html)
        self.assertIn('A caixa institucional já pode ser aberta direto pela Central.', html)

    def test_erro_mostra_titulo_diferente_e_mensagem_real(self):
        html = pagina_gmail_callback(False, 'Conta institucional incorreta.')
        self.assertIn('Não foi possível conectar', html)
        self.assertIn('Conta institucional incorreta.', html)

    def test_mensagem_e_escapada_nunca_permite_injecao_de_html(self):
        html = pagina_gmail_callback(False, '<script>alert(1)</script>')
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_avisa_janela_que_abriu_via_postmessage_no_mesmo_origin(self):
        html = pagina_gmail_callback(True, 'ok')
        self.assertIn('window.opener.postMessage', html)
        self.assertIn('window.location.origin', html)
        self.assertNotIn("postMessage({tipo: 'gmail-oauth-concluido', sucesso: true}, '*')", html)

    def test_botao_de_fechar_sempre_presente_mesmo_sem_opener(self):
        # Página aberta como navegação normal (não popup) precisa de uma
        # ação explícita -- nunca uma tela morta sem nenhum controle.
        html = pagina_gmail_callback(True, 'ok')
        self.assertIn('onclick="window.close()"', html)


if __name__ == '__main__':
    unittest.main()
