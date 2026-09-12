import unittest
from unittest.mock import MagicMock
from uuid import uuid4
from mi_unidades import (
    validar_unidade,
    gerar_codigo_publico,
    normalizar_codigo_publico,
    criar_unidade,
    buscar_unidade_por_id,
    buscar_unidade_por_codigo,
    unidade_existe,
    ativar_unidade,
    revogar_unidade,
    ALFABETO_CODIGO,
    TAMANHO_CODIGO,
    CAMPOS,
)

PII_SUSPEITA = ('nome', 'email', 'telefone', 'cpf', 'endereco', 'ip', 'consumidor')


class GeracaoDeCodigo(unittest.TestCase):
    def test_formato_e_tamanho(self):
        codigo = gerar_codigo_publico()
        self.assertEqual(len(codigo), TAMANHO_CODIGO)
        self.assertTrue(all(c in ALFABETO_CODIGO for c in codigo))

    def test_alfabeto_sem_caracteres_ambiguos(self):
        for ambiguo in ('0', 'O', '1', 'I', 'L'):
            self.assertNotIn(ambiguo, ALFABETO_CODIGO)

    def test_entropia_minima_do_alfabeto(self):
        import math
        entropia_bits = TAMANHO_CODIGO * math.log2(len(ALFABETO_CODIGO))
        self.assertGreater(entropia_bits, 80)

    def test_codigos_diferentes_entre_geracoes(self):
        codigos = {gerar_codigo_publico() for _ in range(50)}
        self.assertEqual(len(codigos), 50)

    def test_nao_deriva_de_nada_externo(self):
        # Duas chamadas sem nenhum parâmetro em comum não podem coincidir.
        self.assertNotEqual(gerar_codigo_publico(), gerar_codigo_publico())


class Validacao(unittest.TestCase):
    def test_lote_id_valido(self):
        lote_id = str(uuid4())
        self.assertEqual(validar_unidade({'lote_id': lote_id}), lote_id)

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            validar_unidade({'lote_id': str(uuid4()), 'sku': 'MC-100ML'})

    def test_rejeita_lote_id_invalido(self):
        for lote_id in (None, '', 'nao-e-uuid', 123):
            with self.subTest(lote_id=lote_id), self.assertRaises(ValueError):
                validar_unidade({'lote_id': lote_id})

    def test_nao_duplica_sku_no_modelo(self):
        self.assertNotIn('sku', CAMPOS)

    def test_normaliza_codigo_publico(self):
        self.assertEqual(normalizar_codigo_publico('  ab23cd  '), 'AB23CD')
        with self.assertRaises(ValueError):
            normalizar_codigo_publico('   ')


class Criacao(unittest.TestCase):
    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            criar_unidade(factory, {'lote_id': 'nao-e-uuid'})
        factory.assert_not_called()

    def test_lote_inexistente_gera_erro_explicito_sem_nenhuma_escrita(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None  # lote_existe_por_id falha
        with self.assertRaises(ValueError):
            criar_unidade(lambda: conn, {'lote_id': str(uuid4())})
        self.assertEqual(cur.execute.call_count, 1)
        self.assertIn('mi_lotes', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_criacao_nova(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(1,), {'id': 'novo-id'}]  # lote_existe + insert
        resposta, status = criar_unidade(lambda: conn, {'lote_id': str(uuid4())})
        self.assertEqual(status, 201)
        self.assertEqual(resposta['estado'], 'emitida')
        self.assertEqual(len(resposta['codigo_publico']), TAMANHO_CODIGO)
        self.assertIn('ON CONFLICT(codigo_publico) DO NOTHING', cur.execute.call_args_list[1].args[0])
        conn.close.assert_called_once()

    def test_colisao_simulada_tenta_de_novo_e_cria(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # lote_existe ok; 1a tentativa colide (None); 2a tentativa cria.
        cur.fetchone.side_effect = [(1,), None, {'id': 'novo-id'}]
        resposta, status = criar_unidade(lambda: conn, {'lote_id': str(uuid4())})
        self.assertEqual(status, 201)
        self.assertTrue(resposta['success'])
        # 1 checagem de lote + 2 tentativas de insert
        self.assertEqual(cur.execute.call_count, 3)

    def test_colisao_persistente_desiste_apos_limite_de_tentativas(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [(1,)] + [None] * 10  # sempre colide
        with self.assertRaises(RuntimeError):
            criar_unidade(lambda: conn, {'lote_id': str(uuid4())})


class Busca(unittest.TestCase):
    def test_busca_por_id_retorna_none_quando_ausente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        self.assertIsNone(buscar_unidade_por_id(lambda: conn, str(uuid4())))
        conn.close.assert_called_once()

    def test_busca_por_codigo_normaliza(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'x', 'codigo_publico': 'AB23CD'}
        resultado = buscar_unidade_por_codigo(lambda: conn, '  ab23cd  ')
        self.assertEqual(resultado, {'id': 'x', 'codigo_publico': 'AB23CD'})
        self.assertEqual(cur.execute.call_args.args[1], ('AB23CD',))

    def test_registro_retornado_nao_tem_pii(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {
            'id': 'x', 'lote_id': 'y', 'codigo_publico': 'AB23CD', 'estado': 'emitida',
            'revogada_em': None, 'motivo_revogacao': None, 'criado_em': None,
        }
        registro = buscar_unidade_por_codigo(lambda: conn, 'AB23CD')
        for chave in registro:
            self.assertNotIn(chave.lower(), PII_SUSPEITA)


class ExistenciaNaTransacao(unittest.TestCase):
    def test_existe_retorna_id_normalizado(self):
        ident = str(uuid4())
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        self.assertEqual(unidade_existe(cur, ident), ident)

    def test_inexistente_levanta_erro(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            unidade_existe(cur, str(uuid4()))


class Ativacao(unittest.TestCase):
    def test_emitida_vira_ativa(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'x'}
        resposta, status = ativar_unidade(lambda: conn, 'AB23CD')
        self.assertEqual(status, 200)
        self.assertEqual(resposta['estado'], 'ativa')

    def test_nao_reativa_unidade_revogada(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'x', 'estado': 'revogada'}]
        resposta, status = ativar_unidade(lambda: conn, 'AB23CD')
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])

    def test_unidade_inexistente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, None]
        resposta, status = ativar_unidade(lambda: conn, 'AB23CD')
        self.assertEqual(status, 404)


class Revogacao(unittest.TestCase):
    def test_revoga_unidade_emitida_ou_ativa(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'x'}
        resposta, status = revogar_unidade(lambda: conn, 'AB23CD', 'extraviada')
        self.assertEqual(status, 200)
        self.assertFalse(resposta['ja_revogada'])
        self.assertIn('mi_unidades', cur.execute.call_args_list[0].args[0])

    def test_revogacao_exige_motivo(self):
        with self.assertRaises(ValueError):
            revogar_unidade(MagicMock(side_effect=AssertionError('nao deveria conectar')), 'AB23CD', '   ')

    def test_revogacao_repetida_e_informativa_sem_reprocessar(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'x'}]  # UPDATE não pega linha (já revogada); SELECT confirma
        resposta, status = revogar_unidade(lambda: conn, 'AB23CD', 'novo motivo')
        self.assertEqual(status, 200)
        self.assertTrue(resposta['ja_revogada'])
        # apenas 2 comandos: a tentativa de UPDATE e o SELECT de confirmação, nenhum novo UPDATE.
        self.assertEqual(cur.execute.call_count, 2)

    def test_revogacao_de_unidade_inexistente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, None]
        resposta, status = revogar_unidade(lambda: conn, 'AB23CD', 'motivo')
        self.assertEqual(status, 404)
        self.assertFalse(resposta['success'])


if __name__ == '__main__':
    unittest.main()
