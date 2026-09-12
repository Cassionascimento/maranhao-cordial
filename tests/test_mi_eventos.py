import unittest
from unittest.mock import MagicMock
from uuid import uuid4
from mi_eventos import validar_evento, registrar_evento_mi, consumo_territorial


class Validacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo_evento='scan', canal='qr'), **kw}

    def test_evento_minimo_valido(self):
        chave, d, digest = validar_evento(self.body())
        self.assertEqual(d['canal'], 'qr')
        self.assertIsNone(d['lote'])
        self.assertEqual(d['payload'], {})
        self.assertTrue(digest)

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(campo_invalido=True))

    def test_rejeita_chave_invalida(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(chave='nao-e-uuid'))

    def test_rejeita_tipo_evento_invalido(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(tipo_evento='outro'))

    def test_rejeita_canal_vazio(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(canal='   '))

    def test_rejeita_origem_parcial(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(origem_tipo='whatsapp_mensagem'))
        with self.assertRaises(ValueError):
            validar_evento(self.body(origem_id='123'))

    def test_rejeita_origem_tipo_fora_do_padrao(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(origem_tipo='Whatsapp Mensagem', origem_id='123'))

    def test_rejeita_payload_nao_objeto(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(payload=[1, 2]))

    def test_rejeita_ocorrido_em_invalido(self):
        with self.assertRaises(ValueError):
            validar_evento(self.body(ocorrido_em='ontem'))

    def test_mesmo_conteudo_produz_mesmo_digest(self):
        body = self.body(lote='L1')
        _, _, d1 = validar_evento(dict(body))
        _, _, d2 = validar_evento(dict(body))
        self.assertEqual(d1, d2)

    def test_conteudo_diferente_produz_digest_diferente(self):
        base = self.body()
        _, _, d1 = validar_evento(dict(base))
        _, _, d2 = validar_evento(dict(base, lote='L1'))
        self.assertNotEqual(d1, d2)


class Registro(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo_evento='scan', canal='qr'), **kw}

    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            registrar_evento_mi(factory, {'chave': 'invalido'})
        factory.assert_not_called()

    def test_criacao_grava_auditoria_uma_unica_vez(self):
        body = self.body()
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertEqual(cur.execute.call_count, 3)
        self.assertIn('mi_eventos_auditoria', cur.execute.call_args_list[2].args[0])
        self.assertIn('ON CONFLICT(chave) DO NOTHING', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_mesma_chave_mesmo_conteudo_e_idempotente_sem_nova_auditoria(self):
        body = self.body()
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])
        self.assertEqual(cur.execute.call_count, 2)

    def test_mesma_chave_conteudo_diferente_e_conflito_explicito(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': 'outro-hash'}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])
        self.assertEqual(cur.execute.call_count, 2)


class RegistroComSku(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo_evento='scan', canal='qr'), **kw}

    def test_normaliza_sku_igual_a_mi_skus(self):
        _, d, _ = validar_evento(self.body(sku=' mc-100ml '))
        self.assertEqual(d['sku'], 'MC-100ML')

    def test_rejeita_formato_de_sku_invalido_sem_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            registrar_evento_mi(factory, self.body(sku='sku com espaço'))
        factory.assert_not_called()

    def test_sku_existente_e_aceito_e_gravado_normalizado(self):
        body = self.body(sku=' mc-100ml ')
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'existe': 1}, {'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertIn('mi_skus', cur.execute.call_args_list[0].args[0])
        self.assertEqual(cur.execute.call_args_list[0].args[1], ('MC-100ML',))
        insert_valores = cur.execute.call_args_list[1].args[1]
        self.assertIn('MC-100ML', insert_valores)

    def test_sku_inexistente_gera_erro_explicito_sem_nenhuma_escrita(self):
        body = self.body(sku='MC-INEXISTENTE')
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            registrar_evento_mi(lambda: conn, body)
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn('mi_skus', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_evento_sem_sku_nao_verifica_existencia(self):
        body = self.body()
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertEqual(cur.execute.call_count, 3)  # insert + select + auditoria, sem checagem de sku

    def test_repeticao_idempotente_com_mesmo_sku(self):
        body = self.body(sku='MC-100ML')
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'existe': 1}, None, {'id': 'existente', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])
        self.assertEqual(cur.execute.call_count, 3)  # sku_existe + insert(sem novo) + select; sem auditoria

    def test_mesma_chave_com_sku_diferente_e_conflito(self):
        body = self.body(sku='MC-200ML')
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'existe': 1}, None, {'id': 'existente', 'payload_hash': 'hash-com-outro-sku'}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])


class RegistroComEstabelecimento(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo_evento='presenca', canal='qr'), **kw}

    def test_evento_sem_estabelecimento_nao_verifica_existencia(self):
        body = self.body()
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertEqual(cur.execute.call_count, 3)  # insert + select + auditoria, sem checagem

    def test_rejeita_formato_de_estabelecimento_id_invalido_sem_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            registrar_evento_mi(factory, self.body(estabelecimento_id='nao-e-uuid'))
        factory.assert_not_called()

    def test_estabelecimento_existente_e_aceito(self):
        estab_id = str(uuid4())
        body = self.body(estabelecimento_id=estab_id)
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(1,), {'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertIn('mi_estabelecimentos', cur.execute.call_args_list[0].args[0])

    def test_estabelecimento_inexistente_gera_erro_explicito_sem_nenhuma_escrita(self):
        body = self.body(estabelecimento_id=str(uuid4()))
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            registrar_evento_mi(lambda: conn, body)
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn('mi_estabelecimentos', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_estabelecimento_id_participa_do_hash_mesma_chave_diferente_e_conflito(self):
        body = self.body(estabelecimento_id=str(uuid4()))
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(1,), None, {'id': 'existente', 'payload_hash': 'hash-com-outro-estabelecimento'}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])

    def test_repeticao_idempotente_com_mesmo_estabelecimento(self):
        body = self.body(estabelecimento_id=str(uuid4()))
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(1,), None, {'id': 'existente', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])


class RegistroComUnidade(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo_evento='scan', canal='qr'), **kw}

    def test_evento_sem_unidade_nao_verifica_existencia(self):
        body = self.body()
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertEqual(cur.execute.call_count, 3)  # insert + select + auditoria, sem checagem

    def test_rejeita_formato_de_unidade_id_invalido_sem_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            registrar_evento_mi(factory, self.body(unidade_id='nao-e-uuid'))
        factory.assert_not_called()

    def test_unidade_valida_e_aceita(self):
        unidade_id = str(uuid4())
        body = self.body(unidade_id=unidade_id)
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'estado': 'ativa'}, {'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertIn('mi_unidades', cur.execute.call_args_list[0].args[0])

    def test_unidade_inexistente_gera_erro_explicito_sem_nenhuma_escrita(self):
        body = self.body(unidade_id=str(uuid4()))
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            registrar_evento_mi(lambda: conn, body)
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn('mi_unidades', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_unidade_revogada_bloqueia_evento_novo_sem_nenhuma_escrita(self):
        body = self.body(unidade_id=str(uuid4()))
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'estado': 'revogada'}
        with self.assertRaises(ValueError):
            registrar_evento_mi(lambda: conn, body)
        self.assertEqual(cur.execute.call_count, 1)
        conn.close.assert_called_once()

    def test_unidade_id_participa_do_hash_mesma_chave_diferente_e_conflito(self):
        body = self.body(unidade_id=str(uuid4()))
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'estado': 'ativa'}, None, {'id': 'existente', 'payload_hash': 'hash-com-outra-unidade'}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])

    def test_repeticao_idempotente_com_mesma_unidade(self):
        body = self.body(unidade_id=str(uuid4()))
        digest = validar_evento(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'estado': 'ativa'}, None, {'id': 'existente', 'payload_hash': digest}]
        resposta, status = registrar_evento_mi(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])


class ConsumoTerritorial(unittest.TestCase):
    def test_faz_left_join_com_estabelecimento_e_usa_limite_5001(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        consumo_territorial(cur)
        sql = cur.execute.call_args.args[0]
        self.assertIn('LEFT JOIN mi_estabelecimentos', sql)
        self.assertIn('LIMIT 5001', sql)

    def test_nunca_inclui_payload(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        consumo_territorial(cur)
        sql = cur.execute.call_args.args[0]
        self.assertNotIn('payload', sql)

    def test_retorna_localizacao_do_estabelecimento_ligado(self):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {'id': 1, 'tipo_evento': 'scan', 'canal': 'qr', 'sku': 'MC-100ML', 'ocorrido_em': None,
             'cidade': 'Salvador', 'uf': 'BA', 'bairro': 'Barra'},
        ]
        linhas = consumo_territorial(cur)
        self.assertEqual(linhas[0]['cidade'], 'Salvador')
        self.assertEqual(linhas[0]['uf'], 'BA')
        self.assertNotIn('payload', linhas[0])

    def test_evento_sem_estabelecimento_vem_com_localizacao_nula(self):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {'id': 2, 'tipo_evento': 'venda', 'canal': 'qr', 'sku': None, 'ocorrido_em': None,
             'cidade': None, 'uf': None, 'bairro': None},
        ]
        linhas = consumo_territorial(cur)
        self.assertIsNone(linhas[0]['cidade'])
        self.assertIsNone(linhas[0]['uf'])


if __name__ == '__main__':
    unittest.main()
