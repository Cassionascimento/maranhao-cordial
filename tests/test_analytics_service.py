"""analytics_service.py -- wrapper de leitura do GA4 (Google Analytics Data
API). Só leitura, nenhuma escrita/persistência dentro do próprio módulo --
os testes aqui confirmam isso e nunca tocam a API real do Google (o client
é sempre mockado, nenhuma credencial é necessária para rodar)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import analytics_service as ga


def _valor(v):
    return SimpleNamespace(value=v)


def _linha(metricas=(), dimensoes=()):
    return SimpleNamespace(
        metric_values=[_valor(v) for v in metricas],
        dimension_values=[_valor(v) for v in dimensoes],
    )


def _resposta(rows):
    return SimpleNamespace(rows=rows)


class PropertyId(unittest.TestCase):
    def test_sem_ga4_property_id_levanta_erro_claro(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'GA4_PROPERTY_ID'):
                ga._property_id()

    def test_com_property_id_configurado_devolve_o_valor(self):
        with patch.dict('os.environ', {'GA4_PROPERTY_ID': '123456'}):
            self.assertEqual(ga._property_id(), '123456')


class ResumoGeral(unittest.TestCase):
    def test_sem_linhas_devolve_dicionario_vazio(self):
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([])
            self.assertEqual(ga.resumo_geral(), {})

    def test_mapeia_metricas_na_ordem_certa(self):
        linha = _linha(metricas=['120', '30', '200', '450', '0.62'])
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([linha])
            resultado = ga.resumo_geral(dias=7)
        self.assertEqual(resultado, {
            'usuarios_ativos': '120', 'novos_usuarios': '30', 'sessoes': '200',
            'visualizacoes': '450', 'taxa_engajamento': '0.62',
        })

    def test_janela_de_dias_e_repassada_na_requisicao(self):
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([])
            ga.resumo_geral(dias=14)
        requisicao = client.return_value.run_report.call_args.args[0]
        self.assertEqual(requisicao.date_ranges[0].start_date, '14daysAgo')

    def test_nunca_chama_api_real_sem_client_mockado(self):
        # _client() real seria a única forma de bater na rede -- garantindo
        # que ele é sempre o ponto de mock, o teste acima nunca toca o Google.
        with patch.object(ga, '_property_id', return_value='1'), \
             patch.object(ga, 'BetaAnalyticsDataClient') as client_cls:
            client_cls.return_value.run_report.return_value = _resposta([])
            ga.resumo_geral()
            client_cls.assert_called_once()


class OrigensTrafego(unittest.TestCase):
    def test_mapeia_origem_meio_sessoes_usuarios(self):
        linhas = [
            _linha(metricas=['100', '80'], dimensoes=['google', 'organic']),
            _linha(metricas=['40', '35'], dimensoes=['instagram', 'social']),
        ]
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta(linhas)
            resultado = ga.origens_trafego(dias=30)
        self.assertEqual(resultado, [
            {'origem': 'google', 'meio': 'organic', 'sessoes': '100', 'usuarios': '80'},
            {'origem': 'instagram', 'meio': 'social', 'sessoes': '40', 'usuarios': '35'},
        ])

    def test_limite_de_20_linhas_na_requisicao(self):
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([])
            ga.origens_trafego()
        requisicao = client.return_value.run_report.call_args.args[0]
        self.assertEqual(requisicao.limit, 20)


class PaginasMaisAcessadas(unittest.TestCase):
    def test_mapeia_pagina_titulo_visualizacoes_usuarios(self):
        linha = _linha(metricas=['500', '300'], dimensoes=['/home', 'Início'])
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([linha])
            resultado = ga.paginas_mais_acessadas()
        self.assertEqual(resultado, [
            {'pagina': '/home', 'titulo': 'Início', 'visualizacoes': '500', 'usuarios': '300'},
        ])

    def test_sem_linhas_devolve_lista_vazia(self):
        with patch.object(ga, '_client') as client, patch.object(ga, '_property_id', return_value='1'):
            client.return_value.run_report.return_value = _resposta([])
            self.assertEqual(ga.paginas_mais_acessadas(), [])


class SemPersistencia(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_driver_de_banco_nem_de_transporte(self):
        import inspect
        codigo = inspect.getsource(ga)
        for proibido in ('psycopg2', 'requests', 'smtplib', 'INSERT INTO', 'UPDATE '):
            self.assertNotIn(proibido, codigo)


if __name__ == '__main__':
    unittest.main()
