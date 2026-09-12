import unittest
from unittest.mock import MagicMock
from mi_skus import validar_sku, criar_sku, buscar_sku


class Validacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(sku='mc-100ml', produto_nome='Concentrado Guaraná e Gengibre'), **kw}

    def test_sku_minimo_valido_e_normalizado(self):
        sku, d = validar_sku(self.body())
        self.assertEqual(sku, 'MC-100ML')
        self.assertEqual(d['produto_nome'], 'Concentrado Guaraná e Gengibre')
        self.assertIsNone(d['categoria'])
        self.assertTrue(d['ativo'])

    def test_categoria_e_ativo_explicitos(self):
        _, d = validar_sku(self.body(categoria=' concentrado ', ativo=False))
        self.assertEqual(d['categoria'], 'concentrado')
        self.assertFalse(d['ativo'])

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            validar_sku(self.body(campo_invalido=True))

    def test_rejeita_sku_vazio_ou_com_espaco_interno(self):
        for sku in ('', '   ', 'MC 100', 'MC/100', 'a' * 65):
            with self.subTest(sku=sku), self.assertRaises(ValueError):
                validar_sku(self.body(sku=sku))

    def test_rejeita_produto_nome_ausente_ou_vazio(self):
        for nome in (None, '', '   ', 123):
            with self.subTest(nome=nome), self.assertRaises(ValueError):
                validar_sku(self.body(produto_nome=nome))

    def test_rejeita_categoria_invalida(self):
        with self.assertRaises(ValueError):
            validar_sku(self.body(categoria=123))

    def test_rejeita_ativo_nao_booleano(self):
        with self.assertRaises(ValueError):
            validar_sku(self.body(ativo='true'))


class Criacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(sku='mc-100ml', produto_nome='Concentrado Guaraná e Gengibre'), **kw}

    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            criar_sku(factory, {'sku': ''})
        factory.assert_not_called()

    def test_criacao_nova(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            {'id': 'novo-id'},
            {'id': 'novo-id', 'produto_nome': 'Concentrado Guaraná e Gengibre', 'categoria': None, 'ativo': True},
        ]
        resposta, status = criar_sku(lambda: conn, self.body())
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertEqual(resposta['sku'], 'MC-100ML')
        self.assertIn('ON CONFLICT(sku) DO NOTHING', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_mesmo_sku_mesmo_conteudo_e_idempotente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            None,
            {'id': 'existente', 'produto_nome': 'Concentrado Guaraná e Gengibre', 'categoria': None, 'ativo': True},
        ]
        resposta, status = criar_sku(lambda: conn, self.body())
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])

    def test_mesmo_sku_conteudo_diferente_e_conflito_explicito(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            None,
            {'id': 'existente', 'produto_nome': 'Outro Produto', 'categoria': None, 'ativo': True},
        ]
        resposta, status = criar_sku(lambda: conn, self.body())
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])


class Busca(unittest.TestCase):
    def test_busca_normaliza_e_retorna_none_quando_ausente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        self.assertIsNone(buscar_sku(lambda: conn, ' mc-100ml '))
        self.assertEqual(cur.execute.call_args.args[1], ('MC-100ML',))
        conn.close.assert_called_once()

    def test_busca_retorna_registro_encontrado(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'x', 'sku': 'MC-100ML'}
        self.assertEqual(buscar_sku(lambda: conn, 'MC-100ML'), {'id': 'x', 'sku': 'MC-100ML'})

    def test_busca_rejeita_sku_vazio(self):
        with self.assertRaises(ValueError):
            buscar_sku(MagicMock(side_effect=AssertionError('nao deveria conectar')), '   ')


if __name__ == '__main__':
    unittest.main()
