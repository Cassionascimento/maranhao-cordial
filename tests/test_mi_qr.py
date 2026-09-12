import inspect
import unittest
from unittest.mock import MagicMock
from uuid import uuid4
from mi_qr import registrar_scan_qr
from mi_eventos import validar_evento


UNIDADE_ID = str(uuid4())


def unidade_row(estado='ativa', unidade_id=UNIDADE_ID):
    return {'id': unidade_id, 'lote_id': str(uuid4()), 'codigo_publico': 'ABCDEFGHJKMNPQRSTUVW',
            'estado': estado, 'revogada_em': None, 'motivo_revogacao': None, 'criado_em': None}


class CodigoInvalido(unittest.TestCase):
    def test_codigo_invalido_retorna_erro_generico_sem_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        resposta, status = registrar_scan_qr(factory, '   ')
        self.assertEqual(status, 404)
        self.assertEqual(resposta, {'success': False, 'error': 'codigo_invalido'})
        factory.assert_not_called()

    def test_codigo_normalizado_antes_de_consultar(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None  # unidade nao encontrada
        registrar_scan_qr(lambda: conn, '  abcdefghjkmnpqrstuv  ')
        self.assertEqual(cur.execute.call_args.args[1], ('ABCDEFGHJKMNPQRSTUV',))


class UnidadeInexistenteOuRevogada(unittest.TestCase):
    def test_unidade_inexistente_retorna_erro_generico(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        resposta, status = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        self.assertEqual(status, 404)
        self.assertEqual(resposta, {'success': False, 'error': 'codigo_invalido'})
        self.assertEqual(cur.execute.call_count, 1)  # só a busca; nenhuma tentativa de registrar evento

    def test_unidade_revogada_retorna_erro_generico_sem_registrar_evento(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = unidade_row(estado='revogada')
        resposta, status = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        self.assertEqual(status, 404)
        self.assertEqual(resposta, {'success': False, 'error': 'codigo_invalido'})
        self.assertEqual(cur.execute.call_count, 1)

    def test_inexistente_e_revogada_produzem_a_mesma_resposta(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        r_inexistente = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        cur.fetchone.return_value = unidade_row(estado='revogada')
        r_revogada = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        self.assertEqual(r_inexistente, r_revogada)


class ScanValido(unittest.TestCase):
    def test_scan_valido_cria_evento(self):
        chave = str(uuid4())
        digest = validar_evento({'chave': chave, 'tipo_evento': 'scan', 'canal': 'qr', 'unidade_id': UNIDADE_ID})[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            unidade_row(),                          # buscar_unidade_por_codigo
            {'estado': 'ativa'},                     # unidade_utilizavel dentro de registrar_evento_mi
            {'id': 'evento-1'},                      # insert
            {'id': 'evento-1', 'payload_hash': digest},  # select por chave
        ]
        resposta, status = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        self.assertEqual(status, 201)
        self.assertEqual(resposta, {'success': True})
        insert_sql = cur.execute.call_args_list[2].args[0]
        insert_valores = cur.execute.call_args_list[2].args[1]
        self.assertIn('mi_eventos', insert_sql)
        self.assertIn('scan', insert_valores)
        self.assertIn('qr', insert_valores)
        self.assertIn(UNIDADE_ID, insert_valores)

    def test_resposta_publica_nunca_expoe_id_sku_ou_lote(self):
        chave = str(uuid4())
        digest = validar_evento({'chave': chave, 'tipo_evento': 'scan', 'canal': 'qr', 'unidade_id': UNIDADE_ID})[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [unidade_row(), {'estado': 'ativa'}, {'id': 'evento-1'},
                                     {'id': 'evento-1', 'payload_hash': digest}]
        resposta, _ = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        self.assertEqual(set(resposta), {'success'})


class RetryTecnico(unittest.TestCase):
    def test_mesma_chave_requisicao_e_idempotente(self):
        chave = str(uuid4())
        digest = validar_evento({'chave': chave, 'tipo_evento': 'scan', 'canal': 'qr', 'unidade_id': UNIDADE_ID})[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            unidade_row(), {'estado': 'ativa'}, {'id': 'evento-1'}, {'id': 'evento-1', 'payload_hash': digest},
            unidade_row(), {'estado': 'ativa'}, None, {'id': 'evento-1', 'payload_hash': digest},
        ]
        r1, s1 = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        r2, s2 = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        self.assertEqual((s1, s2), (201, 200))
        self.assertEqual(r1, r2)

    def test_sem_chave_requisicao_cada_chamada_e_um_scan_novo(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [
            unidade_row(), {'estado': 'ativa'}, {'id': 'evento-1'}, MagicMock(__getitem__=lambda s, k: 'x'),
            unidade_row(), {'estado': 'ativa'}, {'id': 'evento-2'}, MagicMock(__getitem__=lambda s, k: 'x'),
        ]
        registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW')
        chave_1 = cur.execute.call_args_list[2].args[1][1]
        chave_2 = cur.execute.call_args_list[6].args[1][1]
        self.assertNotEqual(chave_1, chave_2)

    def test_chave_requisicao_com_formato_invalido_e_rejeitada(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            registrar_scan_qr(factory, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao='nao-e-uuid')


class NuncaEhAutenticacao(unittest.TestCase):
    def test_resposta_de_sucesso_nao_afirma_autenticidade(self):
        chave = str(uuid4())
        digest = validar_evento({'chave': chave, 'tipo_evento': 'scan', 'canal': 'qr', 'unidade_id': UNIDADE_ID})[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [unidade_row(), {'estado': 'ativa'}, {'id': 'evento-1'},
                                     {'id': 'evento-1', 'payload_hash': digest}]
        resposta, _ = registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        for termo in ('autentic', 'verificad', 'genuin', 'original'):
            for chave_resp in resposta:
                self.assertNotIn(termo, chave_resp.lower())


class AusenciaDePII(unittest.TestCase):
    def test_funcao_nao_aceita_ip_user_agent_ou_contato(self):
        parametros = set(inspect.signature(registrar_scan_qr).parameters)
        for suspeito in ('ip', 'user_agent', 'email', 'telefone', 'nome', 'cpf'):
            self.assertNotIn(suspeito, parametros)

    def test_evento_registrado_nao_carrega_payload(self):
        chave = str(uuid4())
        digest = validar_evento({'chave': chave, 'tipo_evento': 'scan', 'canal': 'qr', 'unidade_id': UNIDADE_ID})[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [unidade_row(), {'estado': 'ativa'}, {'id': 'evento-1'},
                                     {'id': 'evento-1', 'payload_hash': digest}]
        registrar_scan_qr(lambda: conn, 'ABCDEFGHJKMNPQRSTUVW', chave_requisicao=chave)
        insert_valores = cur.execute.call_args_list[2].args[1]
        # payload vira Json({}) -- nunca None nem string livre com dados do chamador.
        payloads_json_vazio = [v for v in insert_valores if getattr(v, 'adapted', None) == {}]
        self.assertEqual(len(payloads_json_vazio), 1)


if __name__ == '__main__':
    unittest.main()
