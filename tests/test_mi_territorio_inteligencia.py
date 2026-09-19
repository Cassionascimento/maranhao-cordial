"""P3C -- Territory Intelligence v1. Só reformata a saída já calculada de
inteligencia_territorial.recomendar() -- nenhuma agregação nova, nenhuma
escrita."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from flask import Flask

import mi_territorio_inteligencia as terr

AGORA = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _report(decisoes):
    return {'decisoes': decisoes, 'dados_hash': 'abc123'}


class OportunidadesTerritoriais(unittest.TestCase):
    def test_evidencia_suficiente_vira_prioridade_alta(self):
        report = _report({'midia': {'classificacao': 'evidência suficiente', 'territorio': 'São Luís/MA',
                                     'territorio_id': 't1', 'por_que': ['fato real'], 'dados_faltantes': []}})
        resultado = terr.oportunidades_territoriais(report, agora=AGORA)
        op = resultado['opportunities'][0]
        self.assertEqual(op['priority'], 'alta')
        self.assertEqual(op['confidence'], 0.8)
        self.assertEqual(op['evidence'], ['fato real'])

    def test_sinal_inicial_vira_prioridade_normal(self):
        report = _report({'prospeccao': {'classificacao': 'sinal inicial', 'territorio': 'Imperatriz/MA',
                                          'territorio_id': 't2', 'por_que': ['x'], 'dados_faltantes': ['y']}})
        resultado = terr.oportunidades_territoriais(report, agora=AGORA)
        self.assertEqual(resultado['opportunities'][0]['priority'], 'normal')
        self.assertEqual(resultado['opportunities'][0]['confidence'], 0.5)

    def test_dados_insuficientes_nunca_inventa_prioridade(self):
        report = _report({'eventos': {'classificacao': 'dados insuficientes', 'territorio': None,
                                       'territorio_id': None, 'por_que': ['sem evidência'], 'dados_faltantes': ['z']}})
        resultado = terr.oportunidades_territoriais(report, agora=AGORA)
        op = resultado['opportunities'][0]
        self.assertIsNone(op['priority'])
        self.assertEqual(op['confidence'], 'NOT_ENOUGH_DATA')
        self.assertEqual(op['evidence'], [])

    def test_qualidade_de_dados_sempre_presente(self):
        report = _report({'midia': {'classificacao': 'sinal inicial', 'territorio': 'X', 'territorio_id': 't1',
                                     'por_que': [], 'dados_faltantes': ['investimento em mídia']}})
        resultado = terr.oportunidades_territoriais(report, agora=AGORA)
        self.assertEqual(resultado['opportunities'][0]['data_quality']['dados_faltantes'], ['investimento em mídia'])

    def test_sem_decisoes_devolve_lista_vazia(self):
        resultado = terr.oportunidades_territoriais(_report({}), agora=AGORA)
        self.assertEqual(resultado['opportunities'], [])

    def test_nunca_chama_interpretacao_de_ia(self):
        import inspect
        codigo = inspect.getsource(terr)
        self.assertNotIn('interpretar', codigo)
        self.assertNotIn('OpenAI(', codigo)


class RotaLeitura(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        app = Flask(__name__)
        terr.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        resp = app.test_client().get('/api/admin/mi/territorio/oportunidades')
        self.assertEqual(resp.status_code, 401)

    def test_nenhuma_rota_de_escrita(self):
        app = Flask(__name__)
        terr.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


if __name__ == '__main__':
    unittest.main()
