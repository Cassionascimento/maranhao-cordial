"""Central Empresarial -- correção do card 'Autonomia empresarial'
(admin.html chamava uma rota que nunca existiu: /api/admin/ia-empresarial/
fase55). Nenhum índice/percentual é fabricado sem base real -- nunca
banco real, nunca chamada externa."""
import unittest
from unittest.mock import MagicMock

from flask import Flask

import mi_governanca_geral as gov


class FakeCursor:
    def __init__(self, linhas_fila, alertas):
        self.linhas_fila = linhas_fila
        self.alertas = alertas
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        sql_norma = ' '.join(sql.split())
        if sql_norma.startswith('SET LOCAL'):
            self._resultado = None
        elif sql_norma.startswith('SELECT estado, COUNT(*)'):
            self._resultado = self.linhas_fila
        elif sql_norma.startswith('SELECT tipo_decisao, inferencia'):
            self._resultado = self.alertas
        else:
            raise AssertionError(f'SQL não coberto pelo fake: {sql_norma[:80]}')

    def fetchall(self):
        return self._resultado


class FakeCursorComFalha(FakeCursor):
    def execute(self, sql, params=()):
        sql_norma = ' '.join(sql.split())
        if sql_norma.startswith('SET LOCAL'):
            return
        raise RuntimeError('banco indisponível')


class FakeConn:
    def __init__(self, linhas_fila, alertas, cursor_cls=FakeCursor):
        self.linhas_fila = linhas_fila
        self.alertas = alertas
        self.cursor_cls = cursor_cls

    def cursor(self, cursor_factory=None):
        return self.cursor_cls(self.linhas_fila, self.alertas)

    def close(self):
        pass

    def set_session(self, **kwargs):
        pass


class ContagemGeralPorEstado(unittest.TestCase):
    def test_banco_vazio_todas_as_contagens_zero(self):
        cur = FakeCursor([], [])
        self.assertEqual(gov.contagem_geral_por_estado(cur),
                          {'planejada': 0, 'aguardando': 0, 'concluida': 0, 'bloqueada': 0, 'precisa_diretor': 0})

    def test_contagens_reais_nunca_fabricadas(self):
        cur = FakeCursor([{'estado': 'precisa_diretor', 'total': 3}, {'estado': 'aguardando', 'total': 5}], [])
        contagens = gov.contagem_geral_por_estado(cur)
        self.assertEqual(contagens['precisa_diretor'], 3)
        self.assertEqual(contagens['aguardando'], 5)
        self.assertEqual(contagens['concluida'], 0)


class VisaoGovernanca(unittest.TestCase):
    def test_sem_base_indice_de_dependencia_fica_ausente(self):
        cur = FakeCursor([], [])
        visao = gov.visao_governanca(cur)
        self.assertNotIn('indice_dependencia_direcao_pct', visao['autonomia'])

    def test_com_base_indice_e_calculado_a_partir_de_contagens_reais(self):
        cur = FakeCursor([{'estado': 'precisa_diretor', 'total': 1}, {'estado': 'concluida', 'total': 3}], [])
        visao = gov.visao_governanca(cur)
        self.assertEqual(visao['autonomia']['indice_dependencia_direcao_pct'], 25.0)

    def test_alertas_usam_motivo_real_do_item_nunca_generico_fabricado(self):
        cur = FakeCursor(
            [{'estado': 'precisa_diretor', 'total': 1}],
            [{'tipo_decisao': 'aprovar_desconto', 'inferencia': 'margem abaixo do teto', 'proxima_acao': 'revisar', 'criado_em': None}],
        )
        visao = gov.visao_governanca(cur)
        self.assertEqual(visao['precisa_de_mim']['alertas_imediatos'][0]['triagem_fase54']['motivo'], 'margem abaixo do teto')

    def test_sem_decisoes_pendentes_lista_vazia_nunca_erro(self):
        cur = FakeCursor([], [])
        visao = gov.visao_governanca(cur)
        self.assertEqual(visao['precisa_de_mim']['alertas_imediatos'], [])


class RotaHTTP(unittest.TestCase):
    def _app(self, linhas_fila=(), alertas=(), autorizado=lambda: True):
        app = Flask(__name__)
        gov.registrar_rotas(app, lambda: FakeConn(list(linhas_fila), list(alertas)), autorizado)
        return app

    def test_exige_autenticacao(self):
        app = self._app(autorizado=lambda: False)
        resp = app.test_client().get('/api/admin/ia-empresarial/fase55')
        self.assertEqual(resp.status_code, 401)

    def test_banco_vazio_retorna_200_nunca_indisponivel(self):
        # Esta é exatamente a causa raiz corrigida: antes a rota não
        # existia (404 sempre); agora banco vazio é um 200 honesto.
        app = self._app()
        resp = app.test_client().get('/api/admin/ia-empresarial/fase55')
        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertTrue(corpo['success'])
        self.assertEqual(corpo['precisa_de_mim']['total_alertas_imediatos'], 0)

    def test_falha_na_consulta_retorna_erro_explicito_503_nunca_mascarado(self):
        # Erro dentro da consulta (não na abertura da conexão) precisa
        # virar um 503 claro -- nunca mais "indisponível" por rota
        # inexistente, e nunca um 500 cru sem contexto.
        app = Flask(__name__)
        gov.registrar_rotas(app, lambda: FakeConn([], [], cursor_cls=FakeCursorComFalha), lambda: True)
        resp = app.test_client().get('/api/admin/ia-empresarial/fase55')
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
