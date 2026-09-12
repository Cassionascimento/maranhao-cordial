import unittest
from unittest.mock import MagicMock
from uuid import uuid4
from mi_estabelecimentos import (
    validar_estabelecimento,
    criar_estabelecimento,
    buscar_estabelecimento,
    estabelecimento_existe,
)


class Validacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(nome='Bar do Zé', cidade='Salvador', uf='BA'), **kw}

    def test_minimo_valido(self):
        d = validar_estabelecimento(self.body())
        self.assertEqual(d['nome'], 'Bar do Zé')
        self.assertEqual(d['cidade'], 'Salvador')
        self.assertEqual(d['uf'], 'BA')
        self.assertIsNone(d['tipo'])
        self.assertIsNone(d['bairro'])
        self.assertIsNone(d['lead_id'])

    def test_normaliza_uf_por_nome_do_estado(self):
        d = validar_estabelecimento(self.body(uf='bahia'))
        self.assertEqual(d['uf'], 'BA')

    def test_aceita_tipo_bairro_e_lead_id_explicitos(self):
        lead_id = str(uuid4())
        d = validar_estabelecimento(self.body(tipo=' bar ', bairro=' Barra ', lead_id=lead_id))
        self.assertEqual(d['tipo'], 'bar')
        self.assertEqual(d['bairro'], 'Barra')
        self.assertEqual(d['lead_id'], lead_id)

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            validar_estabelecimento(self.body(campo_invalido=True))

    def test_rejeita_nome_ausente_ou_vazio(self):
        for nome in (None, '', '   ', 123):
            with self.subTest(nome=nome), self.assertRaises(ValueError):
                validar_estabelecimento(self.body(nome=nome))

    def test_rejeita_cidade_ausente_ou_vazia(self):
        for cidade in (None, '', '   ', 123):
            with self.subTest(cidade=cidade), self.assertRaises(ValueError):
                validar_estabelecimento(self.body(cidade=cidade))

    def test_rejeita_uf_desconhecida(self):
        for uf in (None, '', 'XX', 'Neverland'):
            with self.subTest(uf=uf), self.assertRaises(ValueError):
                validar_estabelecimento(self.body(uf=uf))

    def test_rejeita_lead_id_invalido(self):
        with self.assertRaises(ValueError):
            validar_estabelecimento(self.body(lead_id='nao-e-uuid'))

    def test_nao_geocodifica_nunca_inventa_cidade_a_partir_do_nome(self):
        d = validar_estabelecimento(self.body(nome='Bar em Salvador, Bahia', cidade='Salvador', uf='BA'))
        self.assertEqual(d['nome'], 'Bar em Salvador, Bahia')
        self.assertEqual(d['cidade'], 'Salvador')


class Criacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(nome='Bar do Zé', cidade='Salvador', uf='BA'), **kw}

    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            criar_estabelecimento(factory, {'nome': ''})
        factory.assert_not_called()

    def test_criacao_retorna_id_novo(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'novo-id'}
        resposta, status = criar_estabelecimento(lambda: conn, self.body())
        self.assertEqual(status, 201)
        self.assertEqual(resposta['id'], 'novo-id')
        conn.close.assert_called_once()

    def test_cada_chamada_cria_um_registro_novo_sem_deduplicar(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'a'}, {'id': 'b'}]
        r1, _ = criar_estabelecimento(lambda: conn, self.body())
        r2, _ = criar_estabelecimento(lambda: conn, self.body())
        self.assertNotEqual(r1['id'], r2['id'])
        self.assertEqual(cur.execute.call_count, 2)


class Busca(unittest.TestCase):
    def test_busca_retorna_none_quando_ausente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        self.assertIsNone(buscar_estabelecimento(lambda: conn, str(uuid4())))
        conn.close.assert_called_once()

    def test_busca_rejeita_id_invalido(self):
        with self.assertRaises(ValueError):
            buscar_estabelecimento(MagicMock(side_effect=AssertionError('nao deveria conectar')), 'nao-e-uuid')


class ExistenciaNaTransacao(unittest.TestCase):
    def test_existe_retorna_id_normalizado(self):
        ident = str(uuid4())
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        self.assertEqual(estabelecimento_existe(cur, ident), ident)

    def test_inexistente_levanta_erro_sem_abrir_nova_conexao(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            estabelecimento_existe(cur, str(uuid4()))


if __name__ == '__main__':
    unittest.main()
