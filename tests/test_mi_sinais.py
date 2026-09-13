import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import mi_sinais as m


class Validacao(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), natureza='fato', origem='crm', tipo_evento='lead_criado'), **kw}

    def test_sinal_minimo_valido(self):
        chave, d, digest = m.validar_sinal(self.body())
        self.assertEqual(d['origem'], 'crm')
        self.assertIsNone(d['sku'])
        self.assertEqual(d['payload'], {})
        self.assertTrue(digest)

    def test_rejeita_campo_desconhecido(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(campo_invalido=True))

    def test_rejeita_chave_invalida(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(chave='nao-e-uuid'))

    def test_rejeita_natureza_invalida(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(natureza='fato_confirmado'))

    def test_diferencia_fato_de_inferencia(self):
        _, fato, _ = m.validar_sinal(self.body(natureza='fato'))
        _, inferencia, _ = m.validar_sinal(self.body(natureza='inferencia', confianca=0.8))
        self.assertEqual(fato['natureza'], 'fato')
        self.assertEqual(inferencia['natureza'], 'inferencia')
        self.assertEqual(inferencia['confianca'], 0.8)

    def test_todas_as_cinco_naturezas_sao_aceitas(self):
        for natureza in m.NATUREZAS:
            _, d, _ = m.validar_sinal(self.body(natureza=natureza))
            self.assertEqual(d['natureza'], natureza)

    def test_rejeita_origem_fora_do_padrao(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(origem='CRM'))
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(origem='crm com espaco'))

    def test_rejeita_tipo_evento_fora_do_padrao(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(tipo_evento='Lead Criado'))

    def test_rejeita_territorio_uf_invalido(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(territorio_uf='ma'))
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(territorio_uf='Maranhao'))

    def test_aceita_territorio_uf_valido(self):
        _, d, _ = m.validar_sinal(self.body(territorio_uf='MA', territorio_cidade='São Luís'))
        self.assertEqual(d['territorio_uf'], 'MA')

    def test_rejeita_confianca_fora_do_intervalo(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(confianca=1.5))
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(confianca=-0.1))

    def test_rejeita_confianca_booleana(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(confianca=True))

    def test_rejeita_payload_nao_objeto(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(payload=[1, 2]))

    def test_rejeita_ocorrido_em_invalido(self):
        with self.assertRaises(ValueError):
            m.validar_sinal(self.body(ocorrido_em='ontem'))

    def test_normaliza_sku_igual_a_mi_skus(self):
        _, d, _ = m.validar_sinal(self.body(sku=' mc-100ml '))
        self.assertEqual(d['sku'], 'MC-100ML')

    def test_mesmo_conteudo_produz_mesmo_digest(self):
        body = self.body(origem_id='lead-1')
        _, _, d1 = m.validar_sinal(dict(body))
        _, _, d2 = m.validar_sinal(dict(body))
        self.assertEqual(d1, d2)

    def test_conteudo_diferente_produz_digest_diferente(self):
        base = self.body()
        _, _, d1 = m.validar_sinal(dict(base))
        _, _, d2 = m.validar_sinal(dict(base, origem_id='outro'))
        self.assertNotEqual(d1, d2)


class Registro(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), natureza='fato', origem='crm', tipo_evento='lead_criado'), **kw}

    def test_validacao_falha_antes_de_abrir_conexao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            m.registrar_sinal_mi(factory, {'chave': 'invalido'})
        factory.assert_not_called()

    def test_criacao_grava_auditoria_uma_unica_vez(self):
        body = self.body()
        digest = m.validar_sinal(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo-id'}, {'id': 'novo-id', 'payload_hash': digest}]
        resposta, status = m.registrar_sinal_mi(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])
        self.assertEqual(cur.execute.call_count, 3)
        self.assertIn('mi_sinais_auditoria', cur.execute.call_args_list[2].args[0])
        self.assertIn('ON CONFLICT(chave) DO NOTHING', cur.execute.call_args_list[0].args[0])
        conn.close.assert_called_once()

    def test_mesma_chave_mesmo_conteudo_e_idempotente_sem_nova_auditoria(self):
        body = self.body()
        digest = m.validar_sinal(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': digest}]
        resposta, status = m.registrar_sinal_mi(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])
        self.assertEqual(cur.execute.call_count, 2)

    def test_mesma_chave_conteudo_diferente_e_conflito_explicito(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': 'outro-hash'}]
        resposta, status = m.registrar_sinal_mi(lambda: conn, body)
        self.assertEqual(status, 409)
        self.assertFalse(resposta['success'])

    def test_origem_referenciada_inexistente_nao_grava(self):
        """sku informado mas inexistente: falha antes do INSERT em mi_sinais."""
        body = self.body(sku='MC-100ML')
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None  # sku_existe não encontra nada
        with self.assertRaises(ValueError):
            m.registrar_sinal_mi(lambda: conn, body)
        self.assertEqual(cur.execute.call_count, 1)  # só a checagem de existência do sku


class Emitir(unittest.TestCase):
    def test_gera_chave_deterministica_e_registra(self):
        with patch('mi_sinais.registrar_sinal_mi') as fake:
            fake.return_value = ({'success': True, 'id': 'x', 'criado': True}, 201)
            factory = MagicMock()
            r1 = m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_criado', origem_id='lead-1')
            r2 = m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_criado', origem_id='lead-1')
            self.assertEqual(fake.call_args_list[0].args[1]['chave'], fake.call_args_list[1].args[1]['chave'])
            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)

    def test_discriminador_muda_a_chave(self):
        with patch('mi_sinais.registrar_sinal_mi') as fake:
            fake.return_value = ({'success': True, 'id': 'x', 'criado': True}, 201)
            factory = MagicMock()
            m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_estagio_mudou',
                     origem_id='lead-1', discriminador='qualificacao')
            m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_estagio_mudou',
                     origem_id='lead-1', discriminador='proposta')
            chave1 = fake.call_args_list[0].args[1]['chave']
            chave2 = fake.call_args_list[1].args[1]['chave']
            self.assertNotEqual(chave1, chave2)

    def test_nunca_propaga_excecao_do_registro(self):
        factory = MagicMock(side_effect=RuntimeError('banco indisponivel'))
        resultado = m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_criado', origem_id='lead-1')
        self.assertIsNone(resultado)

    def test_nunca_propaga_excecao_de_validacao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        resultado = m.emitir(factory, natureza='invalida', origem='crm', tipo_evento='lead_criado')
        self.assertIsNone(resultado)
        factory.assert_not_called()

    def test_nao_abre_conexao_quando_natureza_invalida(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        m.emitir(factory, natureza='invalida', origem='crm', tipo_evento='x')
        factory.assert_not_called()


class Leitura(unittest.TestCase):
    def test_resumo_hoje_agrega_por_natureza_origem_tipo(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'natureza': 'fato', 'origem': 'crm', 'tipo_evento': 'lead_criado', 'total': 3}]
        r = m.resumo_hoje(cur)
        self.assertEqual(r[0]['total'], 3)
        self.assertIn('mi_sinais', cur.execute.call_args.args[0])

    def test_funil_prospeccao_retorna_dict_por_tipo(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'tipo_evento': 'prospecto_encontrado', 'total': 5}]
        r = m.funil_prospeccao(cur)
        self.assertEqual(r, {'prospecto_encontrado': 5})

    def test_pendencias_direcao_conta_propostas_sem_decisao(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'total': 2}
        self.assertEqual(m.pendencias_direcao(cur), 2)

    def test_resumo_site_agrega_visitas_interesses_ctas_conversoes(self):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {'tipo_evento': 'pagina_visitada', 'total': 40},
            {'tipo_evento': 'produto_visitado', 'total': 12},
            {'tipo_evento': 'cta_clicado', 'total': 5},
            {'tipo_evento': 'interesse_degustacao', 'total': 3},
            {'tipo_evento': 'interesse_profissional_b2b', 'total': 2},
        ]
        cur.fetchone.side_effect = [{'produto': 'guarana', 'total': 8}, {'canal': 'instagram_bio', 'total': 6}]
        r = m.resumo_site(cur)
        self.assertEqual(r['visitas'], 52)
        self.assertEqual(r['interesses'], 12)
        self.assertEqual(r['ctas'], 5)
        self.assertEqual(r['conversoes'], 5)
        self.assertEqual(r['produto_em_alta'], 'guarana')
        self.assertEqual(r['origem_em_alta'], 'instagram_bio')

    def test_resumo_site_sem_dados_nao_quebra(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.side_effect = [None, None]
        r = m.resumo_site(cur)
        self.assertEqual(r['visitas'], 0)
        self.assertIsNone(r['produto_em_alta'])
        self.assertIsNone(r['origem_em_alta'])


class SemEfeitosExternos(unittest.TestCase):
    """'nenhuma ação externa é disparada': mi_sinais é só leitura/escrita no
    próprio banco, nunca uma nova via de envio. Checa só imports/chamadas
    reais (via AST), não o texto do docstring -- que cita gmail/whatsapp/
    instagram como futuros produtores, não como dependências atuais."""

    def test_modulo_nao_importa_nenhum_transporte(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(m))
        modulos_importados = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos_importados.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos_importados.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'gmail_legado', 'whatsapp_meta',
                          'whatsapp_omnichannel'):
            self.assertNotIn(proibido, modulos_importados)

    def test_emitir_repassa_o_mesmo_factory_sem_indireção(self):
        factory = MagicMock()
        with patch('mi_sinais.registrar_sinal_mi', return_value=({'success': True}, 201)) as fake:
            m.emitir(factory, natureza='fato', origem='crm', tipo_evento='lead_criado', origem_id='x')
        self.assertIs(fake.call_args.args[0], factory)


if __name__ == '__main__':
    unittest.main()
