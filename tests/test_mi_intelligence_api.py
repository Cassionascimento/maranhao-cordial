"""P5 -- Intelligence Core API: contrato canônico, overview e fila de
decisão. Nenhuma lógica de inteligência nova é testada aqui de novo (já
coberta em test_mi_relacionamento_360.py/test_mi_inteligencia_
relacionamento.py/test_mi_outcome_relacionamento.py) -- o foco é a
INTEGRAÇÃO: contrato completo, dados parciais, NOT_ENOUGH_DATA,
provenance, explainability, fila, outcome, readiness, território,
autenticação e ausência de ação externa."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

from flask import Flask

import mi_intelligence_api as api

AGORA = datetime(2026, 9, 30, tzinfo=timezone.utc)
LEAD_ID = '11111111-1111-1111-1111-111111111111'
ESTAB_ID = '22222222-2222-2222-2222-222222222222'


def _visao(pessoa=None, organization=None, cidade=None, uf=None):
    return {
        'identity': {'pessoa': pessoa, 'papel': (pessoa or {}).get('categoria_contato'), 'contatos_e_canais': [],
                     'origem': (pessoa or {}).get('origem'), 'primeira_interacao': None, 'ultima_interacao': None},
        'organization': organization,
        'relationship': {'pessoa_estabelecimento': 'DIRECT' if organization else 'UNKNOWN',
                          'estabelecimento_pedidos': 'UNKNOWN', 'estabelecimento_produtos': 'UNKNOWN',
                          'pessoa_interacoes': 'UNKNOWN'},
        'commercial': {'estagio': (pessoa or {}).get('estagio'), 'motivo_perda': None, 'propostas': [],
                       'compras_relacionamento': [], 'pedidos_vinculados': [],
                       'receita_acumulada_centavos': (pessoa or {}).get('receita_acumulada_centavos'),
                       'quantidade_compras_leads_crm': None, 'ultima_compra_em': None, 'proxima_recompra_em': None},
        'products': [],
        'behavior': {'interacoes_omnichannel': [], 'eventos_do_estabelecimento': [],
                     'formularios': {'cadastro_profissional': [], 'degustacao': []}, 'canais_utilizados': []},
        'geography': {'cidade': cidade, 'uf': uf, 'territorio': 'NOT_ENOUGH_DATA'},
        'derived_metrics': {'total_orders': 0, 'total_revenue_centavos': 0,
                             'average_order_value_centavos': 'NOT_ENOUGH_DATA',
                             'days_since_last_order': 'NOT_ENOUGH_DATA',
                             'days_since_last_interaction': 'NOT_ENOUGH_DATA',
                             'products_purchased': [], 'orders_by_sku': {}, 'reorder_count': 'NOT_ENOUGH_DATA',
                             'interaction_count': 0, 'channels_used': []},
        'data_quality': {'pessoa_resolvida': pessoa is not None, 'estabelecimento_resolvido': organization is not None,
                          'pedidos_vinculo': 'INFERRED', 'propostas_vinculo': 'INFERRED',
                          'formularios_vinculo': 'INFERRED', 'eventos_vinculo': 'INFERRED',
                          'compras_relacionamento_e_autoritativo_para_receita': True,
                          'lead_score_unificado': 'NOT_ENOUGH_DATA'},
    }


def _inteligencia(score_geral='NOT_ENOUGH_DATA', segments=None, opportunities=None, nba=None, signals=None):
    return {
        'relationship_id': LEAD_ID,
        'signals': signals or [],
        'score': {
            'versao': 'relacionamento_score_v1', 'calculado_em': AGORA.isoformat(),
            'dimensoes': {
                'engagement': {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['nenhuma interação registrada']},
                'commercial_intent': {'valor': 10, 'explicacao': ['estágio inicial']},
                'relationship_value': {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['sem lead resolvido']},
                'reorder_signal': {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['sem histórico de compra']},
                'data_quality': {'valor': 'NOT_ENOUGH_DATA', 'explicacao': ['nenhum sinal disponível']},
            },
            'score_geral': score_geral, 'confianca_geral': 'NOT_ENOUGH_DATA', 'dimensoes_usadas_no_geral': [],
        },
        'segments': segments or [],
        'opportunities': opportunities or [],
        'next_best_actions': nba or [{'action': 'NO_ACTION', 'reason': 'sem evidência', 'evidence': [],
                                       'confidence': 1.0, 'generated_at': AGORA.isoformat(),
                                       'relationship_id': None, 'priority': 'baixa'}],
    }


def _cur_historico(linhas):
    cur = MagicMock()
    cur.fetchall.return_value = linhas
    return cur


def _linha_fila(chave='c1', estado='aguardando', acao='CONTACT_REORDER', lead_id=LEAD_ID, resultado=None,
                 criado_em=None, concluido_em=None):
    return {
        'chave': chave, 'tipo_decisao': acao.lower(), 'fatos': ['fato real'], 'inferencia': 'motivo real',
        'prioridade': 'alta', 'confianca': 0.8, 'proxima_acao': acao, 'estado': estado, 'resultado': resultado,
        'lead_id': lead_id, 'estabelecimento_id': None,
        'criado_em': criado_em or (AGORA - timedelta(days=1)), 'atualizado_em': AGORA, 'concluido_em': concluido_em,
    }


class ContratoCanonicoCompleto(unittest.TestCase):
    def test_contrato_traz_todos_os_campos_pedidos(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'bar', 'estagio': 'cliente', 'origem': 'whatsapp',
                  'receita_acumulada_centavos': 5000, 'cadastro_teste': False}
        visao = _visao(pessoa=pessoa, organization={'id': ESTAB_ID, 'lead_id': LEAD_ID}, cidade='São Luís', uf='MA')
        inteligencia = _inteligencia(score_geral=42.0)
        cur = _cur_historico([])
        with patch.object(api, 'relacionamento_360', return_value=visao), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=inteligencia):
            contrato = api.contrato_canonico(cur, LEAD_ID, agora=AGORA)
        campos_esperados = ('identity', 'organization', 'relationship_360', 'data_quality', 'signals', 'score',
                             'score_version', 'confidence', 'segments', 'opportunities', 'next_best_actions',
                             'recommendations', 'human_decisions', 'operational_status', 'outcomes',
                             'learning_status', 'territory', 'forecast_readiness', 'provenance', 'explainability')
        for campo in campos_esperados:
            self.assertIn(campo, contrato, f'campo ausente: {campo}')
        self.assertEqual(contrato['score'], 42.0)
        self.assertEqual(contrato['score_version'], 'relacionamento_score_v1')


class DadosParciais(unittest.TestCase):
    def test_sem_organizacao_ainda_monta_contrato_valido(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'estagio': 'novo', 'cadastro_teste': False}
        visao = _visao(pessoa=pessoa, organization=None)
        with patch.object(api, 'relacionamento_360', return_value=visao), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertIsNone(contrato['organization'])
        self.assertEqual(contrato['provenance']['organization'], 'UNKNOWN')


class RelacionamentoInexistente(unittest.TestCase):
    def test_devolve_none_quando_360_nao_encontra(self):
        with patch.object(api, 'relacionamento_360', return_value=None):
            contrato = api.contrato_canonico(_cur_historico([]), 'nao-existe', agora=AGORA)
        self.assertIsNone(contrato)

    def test_rota_devolve_404(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = _cur_historico([])
        app = Flask(__name__)
        api.registrar_rotas_leitura(app, lambda: conn, lambda: True)
        with patch.object(api, 'relacionamento_360', return_value=None):
            resp = app.test_client().get(f'/api/admin/mi/relacionamento/{LEAD_ID}/contrato')
        self.assertEqual(resp.status_code, 404)


class CamposNotEnoughData(unittest.TestCase):
    def test_score_e_dimensoes_ficam_not_enough_data_quando_sem_evidencia(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertEqual(contrato['score'], 'NOT_ENOUGH_DATA')
        self.assertEqual(contrato['learning_status']['ready'], False)
        self.assertEqual(contrato['territory'], 'not_requested')

    def test_territorio_sem_cidade_uf_fica_not_enough_data(self):
        contrato = {'relationship_360': {'geography': {'cidade': None, 'uf': None}}, 'provenance': {}}
        resultado = api.anexar_territorio(contrato, {'opportunities': []})
        self.assertEqual(resultado['territory'], 'NOT_ENOUGH_DATA')
        self.assertEqual(resultado['provenance']['territory'], 'NOT_ENOUGH_DATA')


class Provenance(unittest.TestCase):
    def test_cadastro_teste_vira_synthetic_test(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': True}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertEqual(contrato['provenance']['identity'], 'SYNTHETIC_TEST')

    def test_pessoa_real_fica_real(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertEqual(contrato['provenance']['identity'], 'REAL')

    def test_sem_pessoa_fica_unknown(self):
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=None, organization={'id': ESTAB_ID})), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), ESTAB_ID, agora=AGORA)
        self.assertEqual(contrato['provenance']['identity'], 'UNKNOWN')

    def test_recomendacoes_sem_historico_ficam_not_enough_data(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertEqual(contrato['provenance']['recommendations'], 'NOT_ENOUGH_DATA')
        self.assertEqual(contrato['provenance']['outcomes'], 'NOT_ENOUGH_DATA')


class Explainability(unittest.TestCase):
    def test_explica_a_recomendacao_principal_com_evidencia_e_dimensoes(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'bar', 'cadastro_teste': False}
        nba = [{'action': 'CONTACT_REORDER', 'reason': 'provavel_recompra (prioridade alta)',
                'evidence': ['proxima_recompra_em vencida'], 'confidence': 1.0,
                'generated_at': AGORA.isoformat(), 'relationship_id': LEAD_ID, 'priority': 'alta'}]
        inteligencia = _inteligencia(score_geral=80.0, segments=[{'segmento': 'reorder_due', 'motivo': 'x'}], nba=nba)
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=inteligencia):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertIsNotNone(contrato['explainability'])
        self.assertEqual(contrato['explainability']['recommendation'], 'CONTACT_REORDER')
        self.assertEqual(contrato['explainability']['evidencias'], ['proxima_recompra_em vencida'])
        self.assertIn('reorder_due', contrato['explainability']['segmentos_associados'])
        self.assertIn('reorder_signal', contrato['explainability']['dimensoes_do_score'])

    def test_sem_recomendacao_real_explainability_e_none(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertIsNone(contrato['explainability'])


class FilaDeDecisao(unittest.TestCase):
    def test_fila_vazia(self):
        cur = _cur_historico([])
        self.assertEqual(api.fila_decisao(cur), [])

    def test_fila_com_recomendacoes_traz_campos_do_painel(self):
        cur = _cur_historico([_linha_fila()])
        pendentes = api.fila_decisao(cur)
        self.assertEqual(len(pendentes), 1)
        item = pendentes[0]
        for campo in ('recommendation', 'reason', 'evidence', 'priority', 'confidence', 'status',
                      'generated_at', 'necessidade_de_aprovacao'):
            self.assertIn(campo, item)
        self.assertTrue(item['necessidade_de_aprovacao'])
        self.assertEqual(item['status'], 'aguardando')


class OutcomeEHistoricoHumano(unittest.TestCase):
    def test_outcome_aparece_so_para_itens_concluidos(self):
        linhas = [
            _linha_fila(chave='c1', estado='aguardando'),
            _linha_fila(chave='c2', estado='bloqueada', resultado={'decisao_humana': 'rejeitada'}),
            _linha_fila(chave='c3', estado='concluida', resultado={'executada': True}, concluido_em=AGORA),
        ]
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico(linhas), LEAD_ID, agora=AGORA)
        self.assertEqual(len(contrato['outcomes']), 1)
        self.assertEqual(contrato['outcomes'][0]['chave'], 'c3')
        decisoes = {d['chave']: d['decision'] for d in contrato['human_decisions']}
        self.assertEqual(decisoes, {'c1': 'pendente', 'c2': 'rejeitada', 'c3': 'aceita'})
        self.assertEqual(contrato['operational_status'], {
            'pendente_decisao': 1, 'bloqueadas': 1, 'concluidas': 1, 'tem_recomendacao_ativa': True,
        })


class LearningReadiness(unittest.TestCase):
    def test_ready_false_sem_outcome(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        linhas = [_linha_fila(estado='aguardando')]
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico(linhas), LEAD_ID, agora=AGORA)
        self.assertFalse(contrato['learning_status']['ready'])
        self.assertIn('nenhum outcome', contrato['learning_status']['motivo'])

    def test_ready_true_com_outcome(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        linhas = [_linha_fila(estado='concluida', resultado={'executada': True}, concluido_em=AGORA)]
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            contrato = api.contrato_canonico(_cur_historico(linhas), LEAD_ID, agora=AGORA)
        self.assertTrue(contrato['learning_status']['ready'])


class Territorio(unittest.TestCase):
    def test_anexa_territorio_quando_ha_correspondencia_de_cidade(self):
        contrato = {'relationship_360': {'geography': {'cidade': 'São Luís', 'uf': 'MA'}}, 'provenance': {}}
        visao_territorio = {'opportunities': [{'type': 'territorial_midia', 'territory': 'São Luís/MA',
                                                'priority': 'alta', 'confidence': 0.8, 'evidence': ['x']}]}
        resultado = api.anexar_territorio(contrato, visao_territorio)
        self.assertNotEqual(resultado['territory'], 'NOT_ENOUGH_DATA')
        self.assertEqual(resultado['provenance']['territory'], 'DERIVED')

    def test_nao_inventa_correspondencia_sem_match(self):
        contrato = {'relationship_360': {'geography': {'cidade': 'Imperatriz', 'uf': 'MA'}}, 'provenance': {}}
        visao_territorio = {'opportunities': [{'type': 'territorial_midia', 'territory': 'São Luís/MA'}]}
        resultado = api.anexar_territorio(contrato, visao_territorio)
        self.assertEqual(resultado['territory'], 'NOT_ENOUGH_DATA')


class Idempotencia(unittest.TestCase):
    def test_chamar_contrato_canonico_duas_vezes_e_puramente_leitura(self):
        pessoa = {'id': LEAD_ID, 'categoria_contato': 'lead', 'cadastro_teste': False}
        with patch.object(api, 'relacionamento_360', return_value=_visao(pessoa=pessoa)), \
             patch.object(api, 'inteligencia_do_relacionamento', return_value=_inteligencia()):
            c1 = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
            c2 = api.contrato_canonico(_cur_historico([]), LEAD_ID, agora=AGORA)
        self.assertEqual(c1, c2)


class AutenticacaoAutorizacao(unittest.TestCase):
    def test_todas_as_rotas_exigem_autorizacao(self):
        app = Flask(__name__)
        api.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.get(f'/api/admin/mi/relacionamento/{LEAD_ID}/contrato').status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/overview').status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/fila-decisao').status_code, 401)

    def test_nenhuma_rota_de_escrita_e_registrada(self):
        app = Flask(__name__)
        api.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


class NenhumaAcaoExterna(unittest.TestCase):
    def test_modulo_nunca_chama_canais_externos_ou_llm(self):
        import inspect
        codigo = inspect.getsource(api)
        for proibido in ('OpenAI(', 'smtplib', 'requests.', 'import whatsapp', 'import gmail',
                          'salvar_pedido_postgres(', 'criar_checkout', '.propor(', 'INSERT INTO', 'UPDATE '):
            self.assertNotIn(proibido, codigo)


class OverviewSemFabricarMetrica(unittest.TestCase):
    def test_overview_reusa_amostra_limitada_nunca_a_base_inteira(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {'total': 0}, {'total': 0}, {'total': 0}, {'total': 0},  # _contagem_dados_suficientes
        ]
        cur.fetchall.side_effect = [
            [],  # _amostra_de_leads
            [],  # contagem_por_estado
        ]
        with patch.object(api, 'exportar_dataset_aprendizado', return_value={'dataset_versao': 'v1', 'total_linhas': 0, 'linhas': []}):
            resultado = api.visao_executiva(cur, amostra_limite=10, agora=AGORA)
        self.assertEqual(resultado['amostra']['limite'], 10)
        self.assertEqual(resultado['learning_status']['ready'], False)
        self.assertEqual(resultado['relacionamentos_conhecidos']['total_pessoas'], 0)


if __name__ == '__main__':
    unittest.main()
