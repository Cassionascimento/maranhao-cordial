import unittest
from respostas_publicas import normalizar_texto_publico, limpar_resposta_publica, validar_resposta_publica


class Normalizacao(unittest.TestCase):
    def test_remove_acentos_e_minusculiza(self):
        self.assertEqual(normalizar_texto_publico('AÇÃO Não'), 'acao nao')

    def test_coerce_para_texto(self):
        self.assertEqual(normalizar_texto_publico(123), '123')


class Limpeza(unittest.TestCase):
    def test_vazio_ou_none_vira_string_vazia(self):
        self.assertEqual(limpar_resposta_publica(None), '')
        self.assertEqual(limpar_resposta_publica(''), '')

    def test_espaca_pontuacao_colada(self):
        self.assertEqual(limpar_resposta_publica('Ola,mundo.Teste;fim'), 'Ola, mundo. Teste; fim')

    def test_colapsa_espacos_e_quebras_e_tira_bordas(self):
        self.assertEqual(limpar_resposta_publica('  a   b\n\n\nc  '), 'a b\nc')


class Validacao(unittest.TestCase):
    def test_sem_termo_bloqueado_retorna_resposta_original_com_strip(self):
        self.assertEqual(
            validar_resposta_publica('Qual a validade?', '  Validade de 12 meses lacrado.  '),
            'Validade de 12 meses lacrado.',
        )

    def test_termo_bloqueado_detectado_mesmo_com_acento_e_maiusculas(self):
        resposta = validar_resposta_publica('Posso usar em casa?', 'Isso traz REDUÇÃO DE CUSTOS.')
        self.assertNotIn('REDUÇÃO DE CUSTOS', resposta)

    def test_bloqueado_com_restaurante_na_pergunta(self):
        resposta = validar_resposta_publica('Posso usar em restaurante?', 'Serve de molho para carnes.')
        self.assertTrue(resposta.startswith('O Maranhão Cordial pode ampliar a carta de bebidas'))

    def test_bloqueado_com_hotel_na_pergunta(self):
        resposta = validar_resposta_publica('Da para usar no hotel?', 'Vira uma sobremesa no minibar.')
        self.assertTrue(resposta.startswith('O Maranhão Cordial pode integrar a carta de bebidas'))

    def test_bloqueado_com_bar_na_pergunta(self):
        resposta = validar_resposta_publica('Funciona num bar?', 'Fica pronto para servir.')
        self.assertTrue(resposta.startswith('O Maranhão Cordial pode ser utilizado em pequenas'))

    def test_bloqueado_sem_contexto_conhecido_usa_resposta_padrao(self):
        resposta = validar_resposta_publica('E em casa?', 'Reduz custos da operação.')
        self.assertTrue(resposta.startswith('Maranhão Cordial é um concentrado premium'))


if __name__ == '__main__':
    unittest.main()
