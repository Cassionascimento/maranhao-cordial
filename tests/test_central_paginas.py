"""Central Empresarial -- item B da ordem de UX: o callback OAuth do
Gmail não pode mais terminar numa tela JSON crua. Testa só a função pura
de montagem de HTML (nunca importa main.py)."""
import unittest

from central_paginas import pagina_gmail_callback, pagina_visao_investidor, pagina_visao_investidor_invalida


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


VISAO_EXEMPLO = {
    'operacao': {'titulo': 'Softdrinks Tech', 'data_inicio': '2026-10-15', 'data_fim': '2026-10-16',
                 'local': None, 'estado': 'planejamento', 'prioridade': 'normal'},
    'equipe_resumo': [{'funcao': 'Bartender', 'estado': 'confirmado'}],
    'plano': [{'titulo': 'Montar bar', 'tipo': 'tarefa', 'status': 'pendente', 'data_prevista': '2026-10-15'}],
    'indicadores': [{'nome': 'CAC', 'valor': None, 'unidade': None, 'periodo': None,
                      'estado_dado': 'aguardando_dados', 'explicacao': None}],
    'financeiro_resumo': [{'categoria': 'staff', 'tipo': 'orcamento', 'valor_centavos': 500000,
                            'estado_dado': 'confirmado', 'periodo': None}],
}


class PaginaVisaoInvestidor(unittest.TestCase):
    def test_mostra_titulo_e_periodo_reais_nunca_json_cru(self):
        html = pagina_visao_investidor(VISAO_EXEMPLO)
        self.assertTrue(html.strip().startswith('<!doctype html>'))
        self.assertIn('Softdrinks Tech', html)
        self.assertIn('2026-10-15', html)

    def test_campos_ausentes_aparecem_como_aguardando_dados_nunca_zero_ou_vazio_silencioso(self):
        html = pagina_visao_investidor(VISAO_EXEMPLO)
        self.assertIn('AGUARDANDO DADOS', html)

    def test_nunca_expoe_telefone_email_ou_chave_administrativa(self):
        html = pagina_visao_investidor(VISAO_EXEMPLO)
        baixo = html.lower()
        for termo in ('telefone', 'email', 'admin_api_key', 'x-admin-key', 'senha', 'token'):
            self.assertNotIn(termo, baixo)

    def test_valor_financeiro_formatado_em_reais_nunca_centavos_crus(self):
        html = pagina_visao_investidor(VISAO_EXEMPLO)
        self.assertIn('R$ 5.000,00', html)

    def test_secoes_vazias_mostram_mensagem_explicita_nunca_lista_em_branco(self):
        vazio = {**VISAO_EXEMPLO, 'equipe_resumo': [], 'plano': [], 'indicadores': [], 'financeiro_resumo': []}
        html = pagina_visao_investidor(vazio)
        self.assertIn('Nenhuma pessoa confirmada ainda.', html)
        self.assertIn('Nenhum item de plano ainda.', html)

    def test_titulo_com_html_e_escapado(self):
        malicioso = {**VISAO_EXEMPLO, 'operacao': {**VISAO_EXEMPLO['operacao'], 'titulo': '<img src=x onerror=alert(1)>'}}
        html = pagina_visao_investidor(malicioso)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img', html)


class PaginaVisaoInvestidorInvalida(unittest.TestCase):
    def test_nunca_revela_se_o_token_um_dia_existiu(self):
        html = pagina_visao_investidor_invalida()
        self.assertTrue(html.strip().startswith('<!doctype html>'))
        self.assertIn('Link indisponível', html)
        self.assertNotIn('token', html.lower())


if __name__ == '__main__':
    unittest.main()
