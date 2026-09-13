"""ETAPA 5.2: mi_diretor.py -- leitura do diretor + preview de briefing.

Não recria mi_decisao/mi_calendario/mi_publico: leitura_diretor() é testada
com gerar_calendario_mi mockado (a fusão em si já é testada em
test_mi_calendario.py). preview_briefing() nunca deve chamar nada do
pipeline real de envio (checado explicitamente via AST)."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
import mi_diretor as md


def calendario_base(**overrides):
    base = {
        'success': True,
        'resumo': {'ia_trabalhando': False},
        'proxima_atividade': None,
        'colunas': {'hoje': [], 'proximas': [], 'aguardando': [], 'concluidas': [],
                    'bloqueadas': [], 'precisa_diretor': []},
        'inteligencia_de_publico': {'top10': [], 'mudou_desde_ultima_analise': False},
    }
    base.update(overrides)
    return base


class LeituraDiretorSilenciosa(unittest.TestCase):
    def test_sem_nada_pendente_ia_trabalhando_falso_e_nao_chama_diretor(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertFalse(leitura['ia_trabalhando'])
        self.assertFalse(leitura['chamar_diretor']['necessario'])
        self.assertEqual(leitura['chamar_diretor']['motivos'], [])
        self.assertIsNone(leitura['proxima_acao_ia'])

    def test_atividade_concluida_de_rotina_nao_chama_diretor(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        concluida = {'tipo_decisao': 'pesquisa_necessaria', 'estado': 'concluida'}
        with patch.object(md, 'gerar_calendario_mi',
                           return_value=calendario_base(colunas={'hoje': [], 'proximas': [], 'aguardando': [],
                                                                   'concluidas': [concluida], 'bloqueadas': [],
                                                                   'precisa_diretor': []})):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertFalse(leitura['chamar_diretor']['necessario'])
        self.assertEqual(leitura['hoje']['concluido'], [concluida])


class LeituraDiretorMotivos(unittest.TestCase):
    def _leitura(self, colunas_extra, acoes=()):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], list(acoes), [], [], [], [], []]
        colunas = {'hoje': [], 'proximas': [], 'aguardando': [], 'concluidas': [],
                   'bloqueadas': [], 'precisa_diretor': []}
        colunas.update(colunas_extra)
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base(colunas=colunas)):
            return md.leitura_diretor(lambda: conn)

    def test_aprovacao_pendente_e_decisao_necessaria(self):
        item = {'tipo_decisao': 'aprovacao_pendente'}
        leitura = self._leitura({'precisa_diretor': [item]})
        self.assertIn('decisão necessária', leitura['chamar_diretor']['motivos'])

    def test_bloqueio_e_bloqueio_relevante(self):
        item = {'tipo_decisao': 'bloqueio_pendente'}
        leitura = self._leitura({'precisa_diretor': [item]})
        self.assertIn('bloqueio relevante', leitura['chamar_diretor']['motivos'])

    def test_acao_incerta_e_risco_erro(self):
        leitura = self._leitura({}, acoes=[{'tipo_evento': 'acao_executada', 'resultado': 'incerta', 'total': 1}])
        self.assertIn('risco/erro em execução', leitura['chamar_diretor']['motivos'])

    def test_acao_executada_com_sucesso_nao_e_risco(self):
        leitura = self._leitura({}, acoes=[{'tipo_evento': 'acao_executada', 'resultado': 'enviada', 'total': 1}])
        self.assertNotIn('risco/erro em execução', leitura['chamar_diretor']['motivos'])

    def test_oportunidade_de_prioridade_alta_e_importante(self):
        item = {'tipo_decisao': 'oportunidade_parada', 'prioridade': 'alta'}
        leitura = self._leitura({'aguardando': [item]})
        self.assertIn('oportunidade importante', leitura['chamar_diretor']['motivos'])

    def test_oportunidade_de_prioridade_baixa_nao_chama(self):
        item = {'tipo_decisao': 'oportunidade_parada', 'prioridade': 'baixa'}
        leitura = self._leitura({'aguardando': [item]})
        self.assertNotIn('oportunidade importante', leitura['chamar_diretor']['motivos'])
        self.assertEqual(leitura['hoje']['oportunidades'], [item])

    def test_mudanca_de_publico_e_mudanca_relevante(self):
        item = {'tipo_decisao': 'mudanca_de_interesse'}
        leitura = self._leitura({'precisa_diretor': [item]})
        self.assertIn('mudança relevante de público', leitura['chamar_diretor']['motivos'])
        self.assertEqual(leitura['publico']['mudancas_relevantes'], [item])


class LeituraDiretorConselho(unittest.TestCase):
    def test_secao_conselho_usa_mi_conselho_leitura_conselho(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], []]
        conselho_mock = {
            'agentes': [{'codigo': 'leonard', 'nome': 'Leonard', 'area': 'Vendas', 'status': 'trabalhando',
                         'ultima_atividade': {'tipo_evento': 'relatorio_agente', 'criado_em': None}}],
            'trabalhando': 1, 'sem_demanda': 7,
            'mensagens_recentes': [{'de_agente': 'leonard', 'para_agente': 'rua', 'texto': 'x'}],
            'reunioes_recentes': [{'id': 'r1', 'tipo': 'conclave', 'conclusao': 'ok'}],
            'relatorios_recentes': [],
            'conflitos': [{'registro_id': 'r1', 'conflitos': ['x']}],
            'vetos': [{'registro_id': 'r1', 'vetos': ['y']}],
            'aguardando_diretor': [{'id': 'r1'}],
        }
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()), \
             patch.object(md, 'leitura_conselho', return_value=conselho_mock):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(leitura['conselho']['trabalhando'], 1)
        self.assertEqual(leitura['conselho']['sem_demanda'], 7)
        self.assertEqual(leitura['conselho']['reuniao_mais_recente']['tipo'], 'conclave')
        self.assertEqual(len(leitura['conselho']['mensagens_recentes']), 1)

    def test_veto_do_conselho_chama_diretor(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], []]
        conselho_mock = {'agentes': [], 'trabalhando': 0, 'sem_demanda': 8, 'mensagens_recentes': [],
                          'reunioes_recentes': [], 'relatorios_recentes': [],
                          'conflitos': [], 'vetos': [{'registro_id': 'r1', 'vetos': ['risco']}],
                          'aguardando_diretor': []}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()), \
             patch.object(md, 'leitura_conselho', return_value=conselho_mock):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertIn('veto do Conselho de Agentes', leitura['chamar_diretor']['motivos'])

    def test_conselho_aguardando_diretor_chama_diretor(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], []]
        conselho_mock = {'agentes': [], 'trabalhando': 0, 'sem_demanda': 8, 'mensagens_recentes': [],
                          'reunioes_recentes': [], 'relatorios_recentes': [],
                          'conflitos': [], 'vetos': [], 'aguardando_diretor': [{'id': 'r2'}]}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()), \
             patch.object(md, 'leitura_conselho', return_value=conselho_mock):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertIn('Conselho de Agentes aguardando decisão', leitura['chamar_diretor']['motivos'])

    def test_sem_atividade_do_conselho_nao_chama_diretor(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], []]
        conselho_mock = {'agentes': [], 'trabalhando': 0, 'sem_demanda': 8, 'mensagens_recentes': [],
                          'reunioes_recentes': [], 'relatorios_recentes': [],
                          'conflitos': [], 'vetos': [], 'aguardando_diretor': []}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()), \
             patch.object(md, 'leitura_conselho', return_value=conselho_mock):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertFalse(leitura['chamar_diretor']['necessario'])


class LeituraDiretorSite(unittest.TestCase):
    def test_site_usa_resumo_site_de_mi_sinais(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [
            [], [],
            [{'tipo_evento': 'pagina_visitada', 'total': 40}, {'tipo_evento': 'produto_visitado', 'total': 10}],
            [], [], [], [],
        ]
        cur.fetchone.side_effect = [{'produto': 'guarana', 'total': 6}, {'canal': 'instagram_bio', 'total': 4}]
        top10 = [{'tema': 'guarana', 'fonte': ['site'], 'tendencia': 'subindo'}]
        with patch.object(md, 'gerar_calendario_mi',
                           return_value=calendario_base(inteligencia_de_publico={'top10': top10,
                                                                                  'mudou_desde_ultima_analise': True})):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(leitura['site']['visitas'], 50)
        self.assertEqual(leitura['site']['produto_em_alta'], 'guarana')
        self.assertEqual(leitura['site']['origem_em_alta'], 'instagram_bio')
        self.assertTrue(leitura['site']['mudanca_relevante'])

    def test_site_sem_tema_no_top10_nao_marca_mudanca_relevante(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        top10 = [{'tema': 'degustacao', 'fonte': ['crm'], 'tendencia': 'subindo'}]
        with patch.object(md, 'gerar_calendario_mi',
                           return_value=calendario_base(inteligencia_de_publico={'top10': top10,
                                                                                  'mudou_desde_ultima_analise': True})):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertFalse(leitura['site']['mudanca_relevante'])


class LeituraDiretorSecoes(unittest.TestCase):
    def test_calendario_reaproveita_contagens_das_colunas_sem_recalcular(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        colunas = {'hoje': [{}], 'proximas': [{}, {}], 'aguardando': [], 'concluidas': [{}],
                   'bloqueadas': [], 'precisa_diretor': []}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base(colunas=colunas)):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(leitura['calendario'], {'hoje': 1, 'proximas': 2, 'concluidas': 1, 'bloqueadas': 0})

    def test_comercial_usa_funil_e_acoes_de_mi_sinais(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [
            [{'tipo_evento': 'prospecto_encontrado', 'total': 8}, {'tipo_evento': 'prospecto_qualificado', 'total': 3}],
            [{'tipo_evento': 'acao_aprovada', 'resultado': None, 'total': 2}],
            [], [], [], [], [],
        ]
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(leitura['comercial']['prospectos_encontrados'], 8)
        self.assertEqual(leitura['comercial']['prospectos_qualificados'], 3)
        self.assertEqual(leitura['comercial']['acoes_comerciais'],
                          [{'tipo_evento': 'acao_aprovada', 'resultado': None, 'total': 2}])

    def test_publico_traz_top10_subindo_e_caindo(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        top10 = [{'tema': 'a', 'tendencia': 'subindo'}, {'tema': 'b', 'tendencia': 'caindo'},
                 {'tema': 'c', 'tendencia': 'estavel'}]
        with patch.object(md, 'gerar_calendario_mi',
                           return_value=calendario_base(inteligencia_de_publico={'top10': top10,
                                                                                  'mudou_desde_ultima_analise': True})):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(len(leitura['publico']['subindo']), 1)
        self.assertEqual(len(leitura['publico']['caindo']), 1)
        self.assertEqual(leitura['publico']['top10'], top10)

    def test_conteudo_sugerido_hoje_e_filtrado_da_coluna_hoje(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        hoje = [{'tipo_decisao': 'conteudo_sugerido'}, {'tipo_decisao': 'pesquisa_necessaria'}]
        colunas = {'hoje': hoje, 'proximas': [], 'aguardando': [], 'concluidas': [],
                   'bloqueadas': [], 'precisa_diretor': []}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base(colunas=colunas)):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(len(leitura['publico']['conteudos_sugeridos_hoje']), 1)

    def test_proxima_acao_ia_extrai_o_que_quando_motivo(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        proxima = {'proxima_acao': 'pesquisar', 'executar_em': '2026-02-01T09:00:00+00:00', 'motivo': 'faltam contatos'}
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base(proxima_atividade=proxima)):
            leitura = md.leitura_diretor(lambda: conn)
        self.assertEqual(leitura['proxima_acao_ia'],
                          {'o_que': 'pesquisar', 'quando': '2026-02-01T09:00:00+00:00', 'motivo': 'faltam contatos'})

    def test_fecha_a_conexao_propria(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[], [], [], [], [], [], []]
        with patch.object(md, 'gerar_calendario_mi', return_value=calendario_base()):
            md.leitura_diretor(lambda: conn)
        # duas conexões próprias nesta chamada: a do próprio leitura_diretor
        # e a de mi_conselho.leitura_conselho (cada módulo fecha a sua).
        self.assertEqual(conn.close.call_count, 2)
        self.assertEqual(conn.set_session.call_count, 2)
        conn.set_session.assert_called_with(readonly=True, isolation_level='REPEATABLE READ')


class PreviewBriefing(unittest.TestCase):
    def test_nunca_marca_como_enviado(self):
        with patch.object(md, 'leitura_diretor', return_value={
            'hoje': {'concluido': [], 'planejado': []},
            'publico': {'mudancas_relevantes': [], 'top10': []},
            'comercial': {'oportunidades': []},
            'chamar_diretor': {'necessario': False, 'motivos': []},
        }):
            briefing = md.preview_briefing(MagicMock())
        self.assertFalse(briefing['enviado'])

    def test_traz_as_6_secoes_pedidas(self):
        with patch.object(md, 'leitura_diretor', return_value={
            'hoje': {'concluido': ['x'], 'planejado': ['y']},
            'publico': {'mudancas_relevantes': ['z'], 'top10': [{'tema': 'a'}, {'tema': 'b'}, {'tema': 'c'}, {'tema': 'd'}]},
            'comercial': {'oportunidades': ['op']},
            'chamar_diretor': {'necessario': True, 'motivos': ['bloqueio relevante']},
        }):
            briefing = md.preview_briefing(MagicMock())
        self.assertEqual(briefing['o_que_fiz'], ['x'])
        self.assertEqual(briefing['o_que_aprendi'], ['z'])
        self.assertEqual(briefing['o_que_farei'], ['y'])
        self.assertEqual(len(briefing['publico_agora']), 3)  # só top3, não o top10 inteiro
        self.assertEqual(briefing['oportunidades'], ['op'])
        self.assertEqual(briefing['preciso_de_voce']['necessario'], True)


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte_nem_pipeline_de_envio(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(md))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'gmail_legado', 'whatsapp_meta',
                          'whatsapp_omnichannel', 'openai', 'autonomia_supervisionada', 'main'):
            self.assertNotIn(proibido, modulos)

    def test_codigo_nunca_referencia_pipeline_real_de_envio(self):
        """Via AST (Name/Attribute), não texto bruto -- o docstring do módulo
        cita esses nomes de propósito, para explicar o que NÃO é chamado."""
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(md))
        nomes = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Name):
                nomes.add(no.id)
            elif isinstance(no, ast.Attribute):
                nomes.add(no.attr)
        for proibido in ('_enviar_briefing_legado', 'enviar_briefing_executivo_email',
                          'briefing', 'gmail_enviar_email'):
            self.assertNotIn(proibido, nomes)


class RotasMiDiretor(unittest.TestCase):
    def _app(self, factory, autorizado):
        app = Flask(__name__)
        md.registrar_rotas_mi_diretor(app, factory, autorizado)
        return app.test_client()

    def test_diretor_exige_autenticacao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        client = self._app(factory, lambda: False)
        self.assertEqual(client.get('/api/admin/mi/diretor').status_code, 401)
        self.assertEqual(client.get('/api/admin/mi/briefing-preview').status_code, 401)
        factory.assert_not_called()

    def test_diretor_retorna_leitura_quando_autorizado(self):
        with patch.object(md, 'leitura_diretor', return_value={'ia_trabalhando': False}):
            client = self._app(lambda: MagicMock(), lambda: True)
            resposta = client.get('/api/admin/mi/diretor')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()['success'])

    def test_briefing_preview_retorna_quando_autorizado(self):
        with patch.object(md, 'preview_briefing', return_value={'enviado': False}):
            client = self._app(lambda: MagicMock(), lambda: True)
            resposta = client.get('/api/admin/mi/briefing-preview')
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.get_json()['briefing']['enviado'])

    def test_falha_interna_nao_vaza_detalhe(self):
        factory = MagicMock(side_effect=RuntimeError('conexão indisponível'))
        client = self._app(factory, lambda: True)
        resposta = client.get('/api/admin/mi/diretor')
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn('conexão indisponível', resposta.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
