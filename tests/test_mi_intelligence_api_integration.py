"""Testes de integração ponta a ponta do contrato P5 -- exigidos pela
auditoria do incidente de produção "Consulta indisponível (404)".

Diferença deliberada em relação a tests/test_mi_intelligence_api.py: aquele
arquivo testa as FUNÇÕES puras (contrato_canonico/visao_executiva/
fila_decisao) chamadas diretamente. Este arquivo nunca chama essas funções
-- ele sobe um Flask real, registra as MESMAS rotas que main.py registra em
produção (api.registrar_rotas_leitura) e bate nelas via app.test_client(),
exatamente o caminho HTTP que o painel usa. Só os pontos de acesso a dados
(relacionamento_360/historico_decisoes/exportar_dataset_aprendizado/
contagem_por_estado/oportunidades_territoriais) são simulados -- nunca a
lógica de rota, autenticação ou serialização.

Nunca importa main.py (convenção do projeto: main.py tem efeitos colaterais
pesados de import). A autenticação usa email_seguranca.admin_autorizado, a
MESMA função que validar_admin_request() usa em produção -- não um
lambda True/False author-side."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from flask import Flask, request

import mi_intelligence_api as api
from email_seguranca import admin_autorizado

AGORA = datetime(2026, 9, 17, tzinfo=timezone.utc)
CHAVE_VALIDA = 'segredo-de-teste-com-mais-de-trinta-e-dois-caracteres'
NAMESPACE = {'ADMIN_API_KEY': CHAVE_VALIDA}


def _autorizado_real():
    return admin_autorizado(request.headers.get('X-Admin-Key'), NAMESPACE)


def _conexao_vazia():
    """Simula um banco sem nenhum dado -- fetchone sempre {'total': 0},
    fetchall sempre []. Usado para os cenários de 'banco vazio'."""
    cur = MagicMock()
    cur.fetchone.return_value = {'total': 0}
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def _app_real(conn_factory=None):
    app = Flask(__name__)
    api.registrar_rotas_leitura(app, conn_factory or _conexao_vazia, _autorizado_real)
    return app


class Autenticacao(unittest.TestCase):
    """Auth com a função real de produção (email_seguranca.admin_autorizado),
    não um duble -- cobre exatamente o que o mission pediu: sem chave,
    chave inválida, chave válida."""

    def setUp(self):
        self.app = _app_real()
        self.cliente = self.app.test_client()

    def test_sem_chave_recusa_todas_as_rotas(self):
        for url in ('/api/admin/mi/overview', '/api/admin/mi/fila-decisao',
                    '/api/admin/mi/relacionamento/lead-1/contrato'):
            resp = self.cliente.get(url)
            self.assertEqual(resp.status_code, 401, url)
            self.assertFalse(resp.get_json()['success'])

    def test_chave_invalida_recusa(self):
        resp = self.cliente.get('/api/admin/mi/overview', headers={'X-Admin-Key': 'chave-errada'})
        self.assertEqual(resp.status_code, 401)

    def test_chave_valida_autoriza(self):
        resp = self.cliente.get('/api/admin/mi/overview', headers={'X-Admin-Key': CHAVE_VALIDA})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])


class OverviewComBancoVazio(unittest.TestCase):
    """Overview real, HTTP completo, contra um banco sem nenhum lead --
    nunca deve inventar métrica nem quebrar."""

    def test_overview_com_banco_vazio_retorna_200_com_zeros_reais(self):
        with patch.object(api, 'exportar_dataset_aprendizado',
                           return_value={'dataset_versao': 'v1', 'total_linhas': 0, 'linhas': []}):
            app = _app_real()
            resp = app.test_client().get('/api/admin/mi/overview', headers={'X-Admin-Key': CHAVE_VALIDA})
        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertTrue(corpo['success'])
        self.assertEqual(corpo['relacionamentos_conhecidos']['total_pessoas'], 0)
        self.assertEqual(corpo['segmentos_distribuicao'], {})
        self.assertEqual(corpo['oportunidades_detectadas'], {})

    def test_dataset_de_aprendizado_vazio_fica_ready_false_sem_inventar_prontidao(self):
        with patch.object(api, 'exportar_dataset_aprendizado',
                           return_value={'dataset_versao': 'relacionamento_learning_v1', 'total_linhas': 0, 'linhas': []}):
            app = _app_real()
            resp = app.test_client().get('/api/admin/mi/overview', headers={'X-Admin-Key': CHAVE_VALIDA})
        corpo = resp.get_json()
        self.assertFalse(corpo['learning_status']['ready'])
        self.assertEqual(corpo['learning_status']['total_linhas_dataset'], 0)


class FilaDeDecisaoComBancoVazio(unittest.TestCase):
    def test_fila_de_decisao_com_banco_vazio_retorna_lista_vazia_nunca_erro(self):
        app = _app_real()
        resp = app.test_client().get('/api/admin/mi/fila-decisao', headers={'X-Admin-Key': CHAVE_VALIDA})
        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertTrue(corpo['success'])
        self.assertEqual(corpo['pendentes'], [])


class RelacionamentoInexistenteViaRota(unittest.TestCase):
    def test_relacionamento_inexistente_devolve_404_json_nunca_pagina_de_erro_generica(self):
        with patch.object(api, 'relacionamento_360', return_value=None):
            app = _app_real()
            resp = app.test_client().get(
                '/api/admin/mi/relacionamento/nao-existe/contrato', headers={'X-Admin-Key': CHAVE_VALIDA})
        self.assertEqual(resp.status_code, 404)
        corpo = resp.get_json()
        self.assertIsNotNone(corpo, 'um 404 de negócio (relacionamento não encontrado) deve devolver JSON, não a página padrão do Flask')
        self.assertFalse(corpo['success'])


class TerritorioSemDadosViaRota(unittest.TestCase):
    """?incluir_territorio=1 é o caminho real que o painel usa
    (loadRelationship() em maranhao-intelligence.js). Sem geografia
    resolvida, o contrato nunca inventa cobertura territorial."""

    def _contrato_base(self):
        return {
            'contrato_versao': 'intelligence_contract_v1', 'relationship_id': 'lead-1',
            'identity': {'pessoa': {'id': 'lead-1', 'nome': 'Teste'}}, 'organization': None,
            'relationship_360': {'geography': {'cidade': None, 'uf': None}},
            'data_quality': {}, 'provenance': {}, 'signals': [],
            'score': 'NOT_ENOUGH_DATA', 'score_version': 'relacionamento_score_v1', 'confidence': 'NOT_ENOUGH_DATA',
            'score_dimensions': {}, 'segments': [], 'opportunities': [], 'next_best_actions': [],
            'recommendations': [], 'human_decisions': [], 'operational_status': {}, 'outcomes': [],
            'learning_status': {'ready': False}, 'territory': 'not_requested', 'forecast_readiness': 'not_requested',
            'explainability': None,
        }

    def test_territorio_sem_cidade_uf_fica_not_enough_data_nunca_inventa(self):
        with patch.object(api, 'contrato_canonico', return_value=self._contrato_base()):
            app = _app_real()
            resp = app.test_client().get(
                '/api/admin/mi/relacionamento/lead-1/contrato?incluir_territorio=1',
                headers={'X-Admin-Key': CHAVE_VALIDA})
        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertEqual(corpo['territory'], 'NOT_ENOUGH_DATA')


if __name__ == '__main__':
    unittest.main()
