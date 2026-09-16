"""P1A -- conecta em modo READ-ONLY a camada de fábrica (mi_skus/mi_lotes/
mi_unidades/mi_estabelecimentos) ao app. Só GET; nenhuma rota de escrita
nova (criar_sku/criar_lote/criar_unidade/criar_estabelecimento continuam
só chamáveis por código)."""
import unittest
from unittest.mock import MagicMock, Mock

from flask import Flask

import mi_estabelecimentos as estab
import mi_lotes
import mi_skus
import mi_unidades


def _cur(fetchone_return=None, fetchall_return=None):
    cur = MagicMock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    if fetchone_return is not None or fetchall_return is None:
        cur.fetchone.return_value = fetchone_return
    if fetchall_return is not None:
        cur.fetchall.return_value = fetchall_return
    return cur


def _conn(cur):
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def _app_com(registrar, factory):
    app = Flask(__name__)
    registrar(app, factory, lambda: True)
    return app.test_client()


class RotasSkus(unittest.TestCase):
    def test_listar_exige_autorizacao(self):
        app = Flask(__name__)
        mi_skus.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        self.assertEqual(app.test_client().get('/api/admin/mi/skus').status_code, 401)

    def test_listar_devolve_catalogo(self):
        cur = _cur(fetchall_return=[{'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Cordial de Gengibre'}])
        cliente = _app_com(mi_skus.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/skus')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['skus'][0]['sku'], 'CORDIAL-GENGIBRE-500ML')

    def test_buscar_sku_inexistente_devolve_404(self):
        cur = _cur(fetchone_return=None)
        cliente = _app_com(mi_skus.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/skus/NAO-EXISTE')
        self.assertEqual(resp.status_code, 404)

    def test_buscar_sku_existente_devolve_produto(self):
        cur = _cur(fetchone_return={'id': 's1', 'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Cordial'})
        cliente = _app_com(mi_skus.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/skus/cordial-gengibre-500ml')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['sku']['sku'], 'CORDIAL-GENGIBRE-500ML')

    def test_nenhuma_rota_de_escrita_e_registrada(self):
        app = Flask(__name__)
        mi_skus.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


class RotasLotes(unittest.TestCase):
    def test_listar_exige_autorizacao(self):
        app = Flask(__name__)
        mi_lotes.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        self.assertEqual(app.test_client().get('/api/admin/mi/lotes').status_code, 401)

    def test_listar_filtra_por_sku_quando_informado(self):
        cur = _cur(fetchall_return=[])
        cliente = _app_com(mi_lotes.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes?sku=cordial-gengibre-500ml')
        self.assertEqual(resp.status_code, 200)
        sql_chamado = cur.execute.call_args.args[0]
        self.assertIn('WHERE sku=%s', sql_chamado)

    def test_sem_filtro_lista_todos_os_lotes(self):
        cur = _cur(fetchall_return=[])
        cliente = _app_com(mi_lotes.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes')
        self.assertEqual(resp.status_code, 200)
        sql_chamado = cur.execute.call_args.args[0]
        self.assertNotIn('WHERE sku', sql_chamado)

    def test_sku_invalido_na_query_devolve_400(self):
        cur = _cur()
        cliente = _app_com(mi_lotes.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes', query_string={'sku': '###'})
        self.assertEqual(resp.status_code, 400)

    def test_buscar_lote_por_sku_e_codigo(self):
        cur = _cur(fetchone_return={'id': 'l1', 'sku': 'CORDIAL-GENGIBRE-500ML', 'codigo_lote': 'L001'})
        cliente = _app_com(mi_lotes.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes/cordial-gengibre-500ml/l001')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['lote']['codigo_lote'], 'L001')

    def test_lote_inexistente_devolve_404(self):
        cur = _cur(fetchone_return=None)
        cliente = _app_com(mi_lotes.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes/cordial-gengibre-500ml/nao-existe')
        self.assertEqual(resp.status_code, 404)


class RotasUnidades(unittest.TestCase):
    def test_buscar_por_codigo_exige_autorizacao(self):
        app = Flask(__name__)
        mi_unidades.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        self.assertEqual(app.test_client().get('/api/admin/mi/unidades/ABC123').status_code, 401)

    def test_codigo_inexistente_devolve_404(self):
        cur = _cur(fetchone_return=None)
        cliente = _app_com(mi_unidades.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/unidades/CODIGO-QUE-NAO-EXISTE')
        self.assertEqual(resp.status_code, 404)

    def test_codigo_existente_devolve_unidade(self):
        cur = _cur(fetchone_return={'id': 'u1', 'codigo_publico': 'ABC123XYZ0987654321Q', 'estado': 'ativa'})
        cliente = _app_com(mi_unidades.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/unidades/abc123xyz0987654321q')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['unidade']['estado'], 'ativa')

    def test_listar_por_lote_e_escopado_a_um_lote(self):
        cur = _cur(fetchall_return=[])
        lote_id = '11111111-1111-1111-1111-111111111111'
        cliente = _app_com(mi_unidades.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get(f'/api/admin/mi/lotes/{lote_id}/unidades')
        self.assertEqual(resp.status_code, 200)
        sql_chamado, params = cur.execute.call_args.args
        self.assertIn('WHERE lote_id=%s', sql_chamado)
        self.assertEqual(params[0], lote_id)

    def test_lote_id_invalido_devolve_400(self):
        cur = _cur()
        cliente = _app_com(mi_unidades.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/lotes/nao-e-um-uuid/unidades')
        self.assertEqual(resp.status_code, 400)

    def test_nenhuma_rota_de_escrita_e_registrada(self):
        app = Flask(__name__)
        mi_unidades.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


class RotasEstabelecimentos(unittest.TestCase):
    def test_listar_exige_autorizacao(self):
        app = Flask(__name__)
        estab.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        self.assertEqual(app.test_client().get('/api/admin/mi/estabelecimentos').status_code, 401)

    def test_listar_devolve_com_lead_id_quando_associado(self):
        cur = _cur(fetchall_return=[{'id': 'e1', 'nome': 'Bar do Fulano', 'lead_id': 'lead-1'}])
        cliente = _app_com(estab.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/estabelecimentos')
        self.assertEqual(resp.get_json()['estabelecimentos'][0]['lead_id'], 'lead-1')

    def test_id_invalido_devolve_400(self):
        cur = _cur()
        cliente = _app_com(estab.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/estabelecimentos/nao-e-um-uuid')
        self.assertEqual(resp.status_code, 400)

    def test_estabelecimento_inexistente_devolve_404(self):
        cur = _cur(fetchone_return=None)
        cliente = _app_com(estab.registrar_rotas_leitura, lambda: _conn(cur))
        resp = cliente.get('/api/admin/mi/estabelecimentos/11111111-1111-1111-1111-111111111111')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
