import unittest
from unittest.mock import MagicMock
from mi_lotes import validar_lote, criar_lote, buscar_lote, lote_existe, normalizar_codigo_lote


class Validacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(sku=' mc-100ml ', codigo_lote=' l001 '), **kw}

    def test_minimo_valido_e_normalizado(self):
        sku, codigo_lote, d = validar_lote(self.body())
        self.assertEqual(sku, 'MC-100ML')
        self.assertEqual(codigo_lote, 'L001')
        self.assertIsNone(d['fabricado_em'])
        self.assertIsNone(d['validade'])
        self.assertIsNone(d['quantidade_produzida'])

    def test_datas_e_quantidade_explicitas(self):
        _, _, d = validar_lote(self.body(fabricado_em='2026-01-01', validade='2027-01-01', quantidade_produzida=500))
        self.assertEqual(d['fabricado_em'], '2026-01-01')
        self.assertEqual(d['validade'], '2027-01-01')
        self.assertEqual(d['quantidade_produzida'], 500)

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            validar_lote(self.body(campo_invalido=True))

    def test_rejeita_sku_invalido(self):
        with self.assertRaises(ValueError):
            validar_lote(self.body(sku='sku com espaço'))

    def test_rejeita_codigo_lote_invalido(self):
        for codigo in ('', '   ', 'l 001', 'l/001', 'a' * 65):
            with self.subTest(codigo=codigo), self.assertRaises(ValueError):
                validar_lote(self.body(codigo_lote=codigo))

    def test_rejeita_datas_invalidas(self):
        for campo, valor in (('fabricado_em', 'ontem'), ('validade', '2026-13-40')):
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                validar_lote(self.body(**{campo: valor}))

    def test_rejeita_validade_anterior_a_fabricacao(self):
        with self.assertRaises(ValueError):
            validar_lote(self.body(fabricado_em='2026-06-01', validade='2026-01-01'))

    def test_rejeita_quantidade_invalida(self):
        for quantidade in (0, -5, True, 'muitas', float('nan'), float('inf')):
            with self.subTest(quantidade=quantidade), self.assertRaises(ValueError):
                validar_lote(self.body(quantidade_produzida=quantidade))

    def test_normaliza_codigo_lote_isoladamente(self):
        self.assertEqual(normalizar_codigo_lote(' l001 '), 'L001')
        with self.assertRaises(ValueError):
            normalizar_codigo_lote('')


class Criacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(sku='MC-100ML', codigo_lote='L001'), **kw}

    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            criar_lote(factory, {'sku': '', 'codigo_lote': ''})
        factory.assert_not_called()

    def test_sku_inexistente_gera_erro_explicito_sem_nenhuma_escrita(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None  # sku_existe falha
        with self.assertRaises(ValueError):
            criar_lote(lambda: conn, self.body())
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn('mi_skus', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_criacao_nova(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            (1,),  # sku_existe
            {'id': 'novo-id'},  # insert
            {'id': 'novo-id', 'fabricado_em': None, 'validade': None, 'quantidade_produzida': None},  # select
        ]
        resposta, status = criar_lote(lambda: conn, self.body())
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertEqual(resposta['sku'], 'MC-100ML')
        self.assertEqual(resposta['codigo_lote'], 'L001')
        self.assertIn('ON CONFLICT(sku,codigo_lote) DO NOTHING', cur.execute.call_args_list[1].args[0])
        conn.close.assert_called_once()

    def test_mesmo_lote_mesmo_conteudo_e_idempotente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            (1,),
            None,
            {'id': 'existente', 'fabricado_em': '2026-01-01', 'validade': None, 'quantidade_produzida': None},
        ]
        resposta, status = criar_lote(lambda: conn, self.body(fabricado_em='2026-01-01'))
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])

    def test_mesmo_lote_conteudo_diferente_e_conflito_explicito(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            (1,),
            None,
            {'id': 'existente', 'fabricado_em': None, 'validade': None, 'quantidade_produzida': 999},
        ]
        resposta, status = criar_lote(lambda: conn, self.body())
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])


class Busca(unittest.TestCase):
    def test_busca_normaliza_e_retorna_none_quando_ausente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        self.assertIsNone(buscar_lote(lambda: conn, ' mc-100ml ', ' l001 '))
        self.assertEqual(cur.execute.call_args.args[1], ('MC-100ML', 'L001'))
        conn.close.assert_called_once()

    def test_busca_retorna_registro_encontrado(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'x', 'sku': 'MC-100ML', 'codigo_lote': 'L001'}
        self.assertEqual(buscar_lote(lambda: conn, 'MC-100ML', 'L001'),
                          {'id': 'x', 'sku': 'MC-100ML', 'codigo_lote': 'L001'})


class ExistenciaNaTransacao(unittest.TestCase):
    def test_existe_retorna_sku_e_codigo_normalizados(self):
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        self.assertEqual(lote_existe(cur, ' mc-100ml ', ' l001 '), ('MC-100ML', 'L001'))

    def test_inexistente_levanta_erro(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            lote_existe(cur, 'MC-100ML', 'L001')


if __name__ == '__main__':
    unittest.main()
