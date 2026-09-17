"""Central Empresarial -- seção 4 (caso canônico Softdrinks Tech).
Garante que o seed nunca inventa dado além do já confirmado (título e
datas) e nunca cria duplicata em reexecuções. Nunca importa main.py."""
import unittest
from unittest.mock import MagicMock

from scripts.seed_softdrinks_tech import semear, TITULO, DATA_INICIO, DATA_FIM


class SemearValidacao(unittest.TestCase):
    def test_datas_sao_exatamente_as_confirmadas_pela_direcao(self):
        self.assertEqual(DATA_INICIO, '2026-10-15')
        self.assertEqual(DATA_FIM, '2026-10-16')
        self.assertEqual(TITULO, 'Softdrinks Tech')

    def test_nao_semeia_de_novo_quando_ja_existe(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [{'id': 'op-1', 'titulo': TITULO, 'data_inicio': DATA_INICIO, 'data_fim': DATA_FIM}]
        resultado = semear(lambda: conn, criado_por='teste')
        self.assertTrue(resultado['success'])
        self.assertFalse(resultado['criado'])
        self.assertEqual(resultado['operacao']['id'], 'op-1')


if __name__ == '__main__':
    unittest.main()
