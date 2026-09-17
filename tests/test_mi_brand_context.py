"""P5.X — Milestone 7: Brand Visual Context (versionado, nunca
sobrescrito) + Visual Memory (reaproveita mi_artefatos.status=
'aprovado', nenhuma tabela nova). Usa um fake in-memory de
mi_brand_context (nunca banco real) e o fake de mi_artefatos já
existente para a parte de Visual Memory."""
import unittest

from flask import Flask

import mi_artefatos as artefatos
import mi_brand_context as brand
from tests.test_mi_artefatos import FakeArtefatoConn, FakeArtefatoCursor, _db_vazio, _factory


def _valor(v):
    return v.adapted if hasattr(v, 'adapted') else v


class FakeBrandCursor:
    def __init__(self, db):
        self.db = db
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        sql_norma = ' '.join(sql.split())
        if sql_norma.startswith(('SET LOCAL', 'SELECT pg_advisory_xact_lock')):
            self._resultado = None
        elif sql_norma.startswith('SELECT COALESCE(MAX(versao), 0)'):
            self._resultado = {'ultima': max((v['versao'] for v in self.db['brand'].values()), default=0)}
        elif sql_norma.startswith('INSERT INTO mi_brand_context'):
            brand_id, versao, campos, criado_por = params
            self.db['brand'][brand_id] = {
                'id': brand_id, 'versao': versao, 'campos': _valor(campos), 'criado_por': criado_por,
                'criado_em': None,
            }
            self._resultado = None
        elif sql_norma.startswith('SELECT * FROM mi_brand_context ORDER BY versao DESC LIMIT 1'):
            linhas = sorted(self.db['brand'].values(), key=lambda v: v['versao'], reverse=True)
            self._resultado = linhas[0] if linhas else None
        else:
            raise AssertionError(f'SQL não coberto pelo fake: {sql_norma[:80]}')

    def fetchone(self):
        return self._resultado

    def fetchall(self):
        return [self._resultado] if self._resultado else []


class FakeBrandConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return FakeBrandCursor(self.db)

    def close(self):
        pass

    def set_session(self, **kwargs):
        pass


def _db_brand_vazio():
    return {'brand': {}}


class RegistrarVersaoBrandContext(unittest.TestCase):
    def test_primeira_versao_comeca_em_1(self):
        db = _db_brand_vazio()
        resultado = brand.registrar_versao_brand_context(
            lambda: FakeBrandConn(db), {'paleta': ['dourado', 'creme']}, 'diretor@maranhao',
        )
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['versao'], 1)

    def test_segunda_versao_incrementa_nunca_sobrescreve_a_primeira(self):
        db = _db_brand_vazio()
        brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'paleta': ['dourado']}, 'diretor')
        segunda = brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'paleta': ['dourado', 'creme']}, 'diretor')
        self.assertEqual(segunda['versao'], 2)
        self.assertEqual(len(db['brand']), 2)  # a primeira versão continua existindo

    def test_campo_desconhecido_e_recusado(self):
        db = _db_brand_vazio()
        with self.assertRaises(ValueError):
            brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'campo_que_nao_existe': 'x'}, 'diretor')

    def test_ator_vazio_e_recusado(self):
        db = _db_brand_vazio()
        with self.assertRaises(ValueError):
            brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'paleta': []}, '   ')


class BrandContextAtual(unittest.TestCase):
    def test_sem_nenhuma_versao_e_none_nunca_inventa_padrao(self):
        db = _db_brand_vazio()
        cur = FakeBrandCursor(db)
        self.assertIsNone(brand.brand_context_atual(cur))

    def test_devolve_a_versao_mais_recente(self):
        db = _db_brand_vazio()
        brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'paleta': ['v1']}, 'diretor')
        brand.registrar_versao_brand_context(lambda: FakeBrandConn(db), {'paleta': ['v2']}, 'diretor')
        cur = FakeBrandCursor(db)
        atual = brand.brand_context_atual(cur)
        self.assertEqual(atual['campos']['paleta'], ['v2'])
        self.assertEqual(atual['versao'], 2)


class VisualMemory(unittest.TestCase):
    def test_referencias_aprovadas_reaproveita_mi_artefatos_sem_tabela_nova(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'x', mime_type='image/png')
        artefatos.aprovar_artefato(_factory(db), a['id'], ator='diretor')
        artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'y', mime_type='image/png')  # nunca aprovado
        cur = FakeArtefatoCursor(db)
        referencias = brand.referencias_visuais_aprovadas(cur)
        self.assertEqual(len(referencias), 1)
        self.assertEqual(referencias[0]['id'], a['id'])

    def test_rejeitado_nunca_aparece_como_referencia_positiva(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'x', mime_type='image/png')
        artefatos.rejeitar_artefato(_factory(db), a['id'], ator='diretor', motivo='fora da marca')
        cur = FakeArtefatoCursor(db)
        self.assertEqual(brand.referencias_visuais_aprovadas(cur), [])


class MontarBrandContextCompleto(unittest.TestCase):
    def test_combina_campos_e_referencias_aprovadas(self):
        db_brand = _db_brand_vazio()
        db_art = _db_vazio()
        brand.registrar_versao_brand_context(lambda: FakeBrandConn(db_brand), {'paleta': ['dourado']}, 'diretor')
        a = artefatos.registrar_artefato(_factory(db_art), artifact_type='LABEL_CONCEPT', conteudo=b'x', mime_type='image/png')
        artefatos.aprovar_artefato(_factory(db_art), a['id'], ator='diretor')

        # Exercita a função real com um cursor que delega aos dois fakes
        # existentes; não reconstrói a implementação no teste.
        class CursorComposto:
            def execute(self, sql, params=()):
                self.cursor = (FakeBrandCursor(db_brand) if 'mi_brand_context' in sql
                               else FakeArtefatoCursor(db_art))
                self.cursor.execute(sql, params)

            def fetchone(self):
                return self.cursor.fetchone()

            def fetchall(self):
                return self.cursor.fetchall()

        resultado = brand.montar_brand_context_completo(CursorComposto())
        self.assertEqual(resultado['paleta'], ['dourado'])
        self.assertEqual(len(resultado['referencias_aprovadas']), 1)


class RotaHTTP(unittest.TestCase):
    def _app(self, db, autorizado=lambda: True):
        app = Flask(__name__)
        brand.registrar_rotas(app, lambda: FakeBrandConn(db), autorizado)
        return app

    def test_todas_as_rotas_exigem_autorizacao(self):
        db = _db_brand_vazio()
        app = self._app(db, autorizado=lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.get('/api/admin/mi/brand-context').status_code, 401)
        self.assertEqual(cliente.post('/api/admin/mi/brand-context').status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/visual-memory').status_code, 401)

    def test_ler_sem_nenhuma_versao_configurada_false_nunca_erro(self):
        db = _db_brand_vazio()
        resp = self._app(db).test_client().get('/api/admin/mi/brand-context')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()['configurado'])

    def test_registrar_sem_ator_e_400(self):
        db = _db_brand_vazio()
        resp = self._app(db).test_client().post('/api/admin/mi/brand-context', json={'campos': {}})
        self.assertEqual(resp.status_code, 400)

    def test_registrar_com_campo_desconhecido_e_400(self):
        db = _db_brand_vazio()
        resp = self._app(db).test_client().post(
            '/api/admin/mi/brand-context', json={'ator': 'diretor', 'campos': {'campo_invalido': 1}})
        self.assertEqual(resp.status_code, 400)

    def test_registrar_e_depois_ler_via_http(self):
        db = _db_brand_vazio()
        cliente = self._app(db).test_client()
        cliente.post('/api/admin/mi/brand-context', json={'ator': 'diretor', 'campos': {'paleta': ['dourado']}})
        resp = cliente.get('/api/admin/mi/brand-context')
        self.assertTrue(resp.get_json()['configurado'])
        self.assertEqual(resp.get_json()['campos']['paleta'], ['dourado'])


if __name__ == '__main__':
    unittest.main()
