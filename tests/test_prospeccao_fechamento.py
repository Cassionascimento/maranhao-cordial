"""Homologação offline da separação entre qualificação e aptidão comercial."""
from unittest.mock import MagicMock, patch

import test_email_p0 as f
import fase57_prospeccao_universal as fase
import prospeccao_controle as controle


class PropostasProtegidas(f.Offline):
    def setUp(self):
        super().setUp()
        self.item = dict(id='00000000-0000-0000-0000-000000000057',
                         campanha_id='campanha', empresa='Empresa',
                         email='contato@empresa.com.br', objetivo='Parceria',
                         fonte_url='https://empresa.com.br/contato',
                         evidencia='Contato público', status='qualificado', score=90)
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        self.enterContext(patch.object(fase, '_conn', return_value=self.conn))

    def test_qualificado_sem_elegibilidade_nao_cria_proposta(self):
        self.cur.fetchone.return_value = None
        with patch('acoes_comerciais.propor') as persistir:
            resultado = fase.propor_mensagem_fase57({}, self.item, 'Olá.', 'Parceria')
        self.assertFalse(resultado['apto_para_contato'])
        self.assertFalse(resultado['proposta_criada'])
        persistir.assert_not_called()
        self.conn.commit.assert_not_called()

    def test_apto_persiste_para_aprovacao_sem_reserva(self):
        self.cur.fetchone.return_value = (self.item['id'],)
        with patch('acoes_comerciais.propor', return_value={'success': True, 'enviado': False}) as persistir, \
                patch.object(fase, '_transportar_primeiro_contato_aprovado') as enviar:
            resultado = fase.propor_mensagem_fase57({}, self.item, 'Olá.', 'Parceria')
        self.assertFalse(resultado['enviado'])
        self.assertTrue(persistir.call_args.args[1]['apto_para_contato'])
        self.assertEqual(persistir.call_args.args[2:], ('prospecto_fase57', self.item['id']))
        self.assertIsNone(controle._reserva.get())
        enviar.assert_not_called()
        self.conn.commit.assert_not_called()

    def test_reconsulta_inclui_supressao_historico_reserva_e_campanha(self):
        self.cur.fetchone.return_value = None
        fase.apto_para_contato_fase57({}, self.item)
        sql, args = self.cur.execute.call_args.args
        for predicado in ('email_supressoes_p0', 'prospeccao_historico_contatados',
                          'prospeccao_reservas', "p.status='qualificado'", 'p.score>=55',
                          'c.permitir_primeiro_contato', 'c.status = ANY', 'p.fonte_url=%s'):
            self.assertIn(predicado, sql)
        self.assertEqual(args[:3], (self.item['id'], self.item['email'], self.item['fonte_url']))
        self.conn.close.assert_called_once()

    def test_falha_banco_nao_produz_apto_nem_proposta(self):
        self.cur.execute.side_effect = RuntimeError('database_unavailable')
        with patch('acoes_comerciais.propor') as persistir:
            with self.assertRaises(RuntimeError):
                fase.propor_mensagem_fase57({}, self.item, 'Olá.', 'Parceria')
        persistir.assert_not_called()
        self.conn.close.assert_called_once()

    def test_fonte_indisponivel_nao_gera_conteudo_ou_proposta(self):
        with patch.object(fase, '_campanha_e_prospecto', return_value=self.item), \
                patch('prospeccao_fonte_publica.validar_associacao', return_value=(False, 'indisponivel')), \
                patch.object(fase, 'gerar_primeiro_contato_fase57') as gerar, \
                patch('acoes_comerciais.propor') as persistir:
            resultado = fase.enviar_primeiro_contato_fase57({}, self.item['id'])
        self.assertFalse(resultado['enviado'])
        gerar.assert_not_called()
        persistir.assert_not_called()

    def test_resposta_nao_reaplica_regra_de_primeiro_contato(self):
        with patch('acoes_comerciais.propor', return_value={'success': True, 'enviado': False}) as persistir:
            fase.propor_mensagem_fase57({}, self.item, 'Olá.', 'Re: Parceria',
                                      tipo='resposta', origem_mensagem='entrada')
        self.cur.execute.assert_not_called()
        self.assertEqual(persistir.call_args.args[1]['tipo'], 'resposta')
