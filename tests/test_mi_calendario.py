"""ETAPA 5.1: rota /api/admin/mi/calendario -- mesma disciplina de
test_mi_painel.py (autenticação, DRY-RUN, sem vazar detalhe de erro)."""
import unittest
from unittest.mock import MagicMock, patch
from flask import Flask
from mi_calendario import gerar_calendario_mi, registrar_rotas_mi_calendario


class GerarCalendario(unittest.TestCase):
    def test_agrega_planejar_em_colunas_e_resumo(self):
        atividades = [
            {'estado': 'planejada', 'executar_em': None, 'tipo_decisao': 'pesquisa_necessaria', 'chave': 'a'},
            {'estado': 'aguardando', 'executar_em': None, 'tipo_decisao': 'followup_devido', 'chave': 'b'},
            {'estado': 'precisa_diretor', 'executar_em': None, 'tipo_decisao': 'bloqueio_pendente', 'chave': 'c'},
        ]
        with patch('mi_calendario.planejar', return_value=atividades):
            calendario = gerar_calendario_mi(MagicMock())
        self.assertTrue(calendario['success'])
        self.assertEqual(calendario['resumo']['total_hoje'], 1)
        self.assertEqual(calendario['resumo']['total_aguardando'], 1)
        self.assertEqual(calendario['resumo']['total_precisa_diretor'], 1)
        self.assertTrue(calendario['resumo']['ia_trabalhando'])
        self.assertEqual(len(calendario['colunas']['hoje']), 1)

    def test_sem_atividades_todas_as_colunas_vazias(self):
        with patch('mi_calendario.planejar', return_value=[]), \
             patch('mi_calendario.planejar_publico', return_value={'atividades_calendario': [], 'top10': [],
                                                                     'mudou_desde_ultima_analise': False}):
            calendario = gerar_calendario_mi(MagicMock())
        self.assertFalse(calendario['resumo']['ia_trabalhando'])
        for coluna in calendario['colunas'].values():
            self.assertEqual(coluna, [])
        self.assertIsNone(calendario['proxima_atividade'])

    def test_atividades_de_conteudo_do_mi_publico_entram_no_calendario(self):
        conteudo = [{'estado': 'planejada', 'executar_em': None, 'tipo_decisao': 'conteudo_sugerido', 'chave': 'x'}]
        with patch('mi_calendario.planejar', return_value=[]), \
             patch('mi_calendario.planejar_publico', return_value={'atividades_calendario': conteudo,
                                                                     'top10': [{'tema': 'x'}],
                                                                     'mudou_desde_ultima_analise': True}):
            calendario = gerar_calendario_mi(MagicMock())
        self.assertEqual(len(calendario['colunas']['hoje']), 1)
        self.assertEqual(calendario['colunas']['hoje'][0]['tipo_decisao'], 'conteudo_sugerido')
        self.assertTrue(calendario['inteligencia_de_publico']['mudou_desde_ultima_analise'])
        self.assertEqual(calendario['inteligencia_de_publico']['top10'], [{'tema': 'x'}])


    def test_recomendacoes_pendentes_do_conselho_entram_no_calendario(self):
        pendente = {'origem': 'conselho', 'origem_id': 'leonard', 'tipo_decisao': 'recomendacao_conselho',
                    'fatos': [], 'inferencia': 'x', 'prioridade': 'alta', 'confianca': 0.8,
                    'proxima_acao': 'decidir_recomendacao_conselho', 'exige_aprovacao': True,
                    'executar_em': None, 'estado': 'aguardando', 'chave': 'y'}
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # atividades_pendentes_fila (conselho) é chamado antes de
        # atividades_operacoes_vivas -- cada um faz seu próprio
        # execute()+fetchall(), por isso a lista de retornos é ordenada
        # por chamada, não um valor único compartilhado.
        cur.fetchall.side_effect = [[pendente], []]
        with patch('mi_calendario.planejar', return_value=[]), \
             patch('mi_calendario.planejar_publico', return_value={'atividades_calendario': [], 'top10': [],
                                                                     'mudou_desde_ultima_analise': False}):
            calendario = gerar_calendario_mi(lambda: conn)
        self.assertEqual(len(calendario['colunas']['aguardando']), 1)
        self.assertEqual(calendario['colunas']['aguardando'][0]['tipo_decisao'], 'recomendacao_conselho')

    def test_operacoes_vivas_ativas_entram_no_calendario(self):
        from datetime import date, timedelta
        futura = {'id': 'op-1', 'titulo': 'Softdrinks Tech', 'descricao': None,
                  'data_inicio': date.today() + timedelta(days=5), 'data_fim': date.today() + timedelta(days=6),
                  'local': 'AGUARDANDO DADOS', 'estado': 'confirmada', 'prioridade': 'alta', 'responsavel': 'diretor'}
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [futura]]
        with patch('mi_calendario.planejar', return_value=[]), \
             patch('mi_calendario.planejar_publico', return_value={'atividades_calendario': [], 'top10': [],
                                                                     'mudou_desde_ultima_analise': False}):
            calendario = gerar_calendario_mi(lambda: conn)
        self.assertEqual(len(calendario['colunas']['proximas']), 1)
        atividade = calendario['colunas']['proximas'][0]
        self.assertEqual(atividade['tipo_decisao'], 'operacao_viva')
        self.assertEqual(atividade['operacao_id'], 'op-1')
        self.assertEqual(atividade['titulo'], 'Softdrinks Tech')

    def test_operacao_cancelada_e_filtrada_pela_propria_consulta_sql(self):
        # A consulta em mi_operacoes.atividades_calendario já filtra
        # estado<>'cancelada' -- este teste documenta essa garantia via
        # inspeção da SQL, não infere pelo resultado (o fake não filtra).
        import inspect
        import mi_operacoes as opmod
        origem = inspect.getsource(opmod.atividades_calendario)
        self.assertIn("estado <> 'cancelada'", origem)


class RotaMiCalendario(unittest.TestCase):
    def _app(self, factory, autorizado):
        app = Flask(__name__)
        registrar_rotas_mi_calendario(app, factory, autorizado)
        return app.test_client()

    def test_exige_autenticacao_antes_de_qualquer_consulta(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        client = self._app(factory, lambda: False)
        resposta = client.get('/api/admin/mi/calendario')
        self.assertEqual(resposta.status_code, 401)
        factory.assert_not_called()

    def test_retorna_calendario_quando_autorizado(self):
        with patch('mi_calendario.planejar', return_value=[]):
            client = self._app(lambda: MagicMock(), lambda: True)
            resposta = client.get('/api/admin/mi/calendario')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()['success'])

    def test_falha_interna_nao_vaza_detalhe(self):
        factory = MagicMock(side_effect=RuntimeError('conexão indisponível'))
        client = self._app(factory, lambda: True)
        resposta = client.get('/api/admin/mi/calendario')
        self.assertEqual(resposta.status_code, 503)
        corpo = resposta.get_json()
        self.assertFalse(corpo['success'])
        self.assertNotIn('conexão indisponível', corpo['error'])


if __name__ == '__main__':
    unittest.main()
