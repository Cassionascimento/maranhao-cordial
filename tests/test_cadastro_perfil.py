"""O perfil escolhido em cadastro.html tem de chegar ao banco.

Antes: o input hidden não tinha `name` (FormData o omitia) e o backend
nunca lia "perfil". Aqui o backend real recebe o JSON e o INSERT é
inspecionado; nenhum banco nem rede é usado.
"""
import unittest
from unittest.mock import MagicMock, patch

import main


def enviar(**extra):
    corpo = {'segmento': 'Bar', 'responsavel': 'Ana', 'whatsapp': '98999990000', 'email': 'a@b.com',
             'cidade': 'São Luís - MA', 'interesse': 'comprar', 'consentimento': True}
    corpo.update(extra)
    conn = MagicMock()
    with patch.object(main, 'get_db_connection', return_value=conn):
        resposta = main.app.test_client().post('/api/profissional/cadastro', json=corpo)
    inserts = [c for c in conn.cursor.return_value.__enter__.return_value.execute.call_args_list
               if 'INSERT INTO cadastros_profissionais' in str(c.args[0])]
    return resposta, inserts


class CadastroPerfil(unittest.TestCase):
    def test_perfil_conhecido_chega_ao_insert(self):
        _, inserts = enviar(perfil='distribuidor', mensagem='Quero conversar')
        self.assertEqual(len(inserts), 1)
        self.assertIn('[Perfil: distribuidor] Quero conversar', inserts[0].args[1])

    def test_perfil_sem_mensagem(self):
        _, inserts = enviar(perfil='profissional')
        self.assertIn('[Perfil: profissional]', inserts[0].args[1])

    def test_perfil_desconhecido_e_ignorado(self):
        _, inserts = enviar(perfil='<script>', mensagem='oi')
        self.assertIn('oi', inserts[0].args[1])
        self.assertNotIn('<script>', str(inserts[0].args[1]))

    def test_sem_perfil_nada_muda(self):
        _, inserts = enviar(mensagem='oi')
        self.assertIn('oi', inserts[0].args[1])
        self.assertFalse(any('[Perfil' in str(x) for x in inserts[0].args[1]))


if __name__ == '__main__':
    unittest.main()
