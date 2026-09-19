"""P3D -- Forecast readiness: só agrega série real e aplica gate de volume
mínimo -- nenhuma previsão estatística."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

from flask import Flask

import mi_forecast_readiness as fr

AGORA = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _cur(fetchall_sequencia):
    cur = MagicMock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    cur.fetchall.side_effect = fetchall_sequencia
    return cur


class Readiness(unittest.TestCase):
    def test_volume_insuficiente_fica_nao_pronto(self):
        serie = [{'mes': f'2026-0{i}', 'total_pedidos': 1} for i in range(1, 4)]
        resultado = fr._readiness(serie, 'total_pedidos')
        self.assertFalse(resultado['forecast_ready'])
        self.assertIn('mínimo exigido', resultado['motivo'])

    def test_volume_suficiente_fica_pronto(self):
        serie = [{'mes': f'2026-0{i}', 'total_pedidos': 2} for i in range(1, 7)]
        resultado = fr._readiness(serie, 'total_pedidos')
        self.assertTrue(resultado['forecast_ready'])

    def test_meses_com_zero_nao_contam_como_dado(self):
        serie = [{'mes': f'2026-0{i}', 'total_pedidos': 0} for i in range(1, 7)]
        resultado = fr._readiness(serie, 'total_pedidos')
        self.assertFalse(resultado['forecast_ready'])
        self.assertEqual(resultado['meses_com_dado'], 0)


class MontarForecastReadiness(unittest.TestCase):
    def test_sem_nenhum_dado_real_fica_explicitamente_nao_pronto(self):
        cur = _cur([[], [], []])
        resultado = fr.montar_forecast_readiness(cur, agora=AGORA)
        self.assertFalse(resultado['readiness']['sales_forecast']['forecast_ready'])
        self.assertFalse(resultado['readiness']['engagement_forecast']['forecast_ready'])
        self.assertEqual(resultado['readiness']['demand_by_sku_forecast'], 'NOT_ENOUGH_DATA')
        self.assertIn('Nenhuma previsão estatística', resultado['nota'])

    def test_series_por_sku_sao_agrupadas_separadamente(self):
        serie_sku = [
            {'sku': 'A', 'mes': '2026-01', 'total_pedidos': 3},
            {'sku': 'A', 'mes': '2026-02', 'total_pedidos': 2},
            {'sku': 'B', 'mes': '2026-01', 'total_pedidos': 1},
        ]
        cur = _cur([[], serie_sku, []])
        resultado = fr.montar_forecast_readiness(cur, agora=AGORA)
        self.assertEqual(set(resultado['series']['pedidos_por_sku_mes'].keys()), {'A', 'B'})
        self.assertEqual(len(resultado['series']['pedidos_por_sku_mes']['A']), 2)

    def test_nenhum_modelo_estatistico_e_treinado_ou_ajustado(self):
        import inspect
        codigo = inspect.getsource(fr)
        for proibido in ('sklearn', 'statsmodels', 'numpy.polyfit', 'ARIMA', 'prophet', '.fit(', '.predict('):
            self.assertNotIn(proibido, codigo)


class RotaLeitura(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        app = Flask(__name__)
        fr.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        resp = app.test_client().get('/api/admin/mi/forecast/readiness')
        self.assertEqual(resp.status_code, 401)

    def test_nenhuma_rota_de_escrita(self):
        app = Flask(__name__)
        fr.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


if __name__ == '__main__':
    unittest.main()
