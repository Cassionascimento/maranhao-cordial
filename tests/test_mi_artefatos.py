"""P5.X — Milestone 1: contrato canônico de artefatos (mi_artefatos.py +
mi_artefato_storage.py). Usa um fake in-memory de mi_artefatos/
mi_artefatos_blobs/mi_artefatos_auditoria (nunca banco real) para testar
versionamento, lineage, transições de estado e as rotas Flask reais via
app.test_client() -- nunca importa main.py."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

import mi_artefatos as artefatos
from mi_artefato_storage import ErroStorageNaoConfigurado, PostgresBlobStorage, StorageNaoConfigurado

AGORA = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _valor(v):
    # Json e Binary (psycopg2.extensions) expõem .adapted da mesma forma --
    # unwrap genérico em vez de checar cada tipo de adapter isoladamente.
    return v.adapted if hasattr(v, 'adapted') else v


class FakeArtefatoCursor:
    def __init__(self, db):
        self.db = db
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        sql_norma = ' '.join(sql.split())
        if sql_norma.startswith('SET LOCAL'):
            self._resultado = None
        elif sql_norma.startswith('INSERT INTO mi_artefatos_blobs'):
            blob_id, conteudo, mime_type, tamanho = params
            self.db['blobs'][blob_id] = {
                'conteudo': _valor(conteudo), 'mime_type': mime_type, 'tamanho_bytes': tamanho,
            }
            self._resultado = None
        elif sql_norma.startswith('SELECT conteudo FROM mi_artefatos_blobs WHERE id=%s'):
            blob = self.db['blobs'].get(params[0])
            self._resultado = {'conteudo': blob['conteudo']} if blob else None
        elif sql_norma.startswith('SELECT version FROM mi_artefatos WHERE id=%s FOR UPDATE'):
            linha = self.db['artefatos'].get(params[0])
            self._resultado = {'version': linha['version']} if linha else None
        elif sql_norma.startswith('SELECT id, status FROM mi_artefatos WHERE id=%s FOR UPDATE'):
            linha = self.db['artefatos'].get(params[0])
            self._resultado = {'id': linha['id'], 'status': linha['status']} if linha else None
        elif sql_norma.startswith('INSERT INTO mi_artefatos ('):
            campos = ('id', 'artifact_type', 'source_type', 'source_id', 'meeting_id', 'agent_id',
                      'decision_id', 'parent_artifact_id', 'version', 'storage_uri', 'thumbnail_uri',
                      'mime_type', 'metadata')
            linha = {campo: _valor(valor) for campo, valor in zip(campos, params)}
            linha['status'] = 'gerado'
            linha['created_at'] = AGORA
            linha['approved_at'] = None
            self.db['artefatos'][linha['id']] = linha
            self._resultado = None
        elif sql_norma.startswith('UPDATE mi_artefatos SET status='):
            novo_estado, artefato_id = params
            linha = self.db['artefatos'][artefato_id]
            linha['status'] = novo_estado
            linha['approved_at'] = AGORA if novo_estado == 'aprovado' else None
            self._resultado = None
        elif sql_norma.startswith('INSERT INTO mi_artefatos_auditoria'):
            artefato_id, estado_anterior, estado_novo, ator, motivo = params
            self.db['auditoria'].append({
                'artefato_id': artefato_id, 'estado_anterior': estado_anterior,
                'estado_novo': estado_novo, 'ator': ator, 'motivo': motivo,
            })
            self._resultado = None
        elif sql_norma.startswith('SELECT * FROM mi_artefatos WHERE id=%s'):
            self._resultado = self.db['artefatos'].get(params[0])
        elif sql_norma.startswith('SELECT * FROM mi_artefatos'):
            linhas = list(self.db['artefatos'].values())
            *filtros, limite = params
            where_clause = sql_norma.split('WHERE ', 1)[1].split(' ORDER BY')[0] if ' WHERE ' in sql_norma else None
            if where_clause:
                for condicao, valor in zip(where_clause.split(' AND '), filtros):
                    campo = condicao.split('=')[0]
                    linhas = [l for l in linhas if l.get(campo) == valor]
            linhas.sort(key=lambda l: l['created_at'], reverse=True)
            self._resultado = linhas[:limite]
        else:
            raise AssertionError(f'SQL não coberto pelo fake: {sql_norma[:90]}')

    def fetchone(self):
        if isinstance(self._resultado, list):
            return self._resultado[0] if self._resultado else None
        return self._resultado

    def fetchall(self):
        return self._resultado if isinstance(self._resultado, list) else ([self._resultado] if self._resultado else [])


class FakeArtefatoConn:
    def __init__(self, db):
        self.db = db
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return FakeArtefatoCursor(self.db)

    def close(self):
        self.closed = True

    def set_session(self, **kwargs):
        pass


def _db_vazio():
    return {'artefatos': {}, 'blobs': {}, 'auditoria': []}


def _factory(db):
    return lambda: FakeArtefatoConn(db)


class RegistrarArtefato(unittest.TestCase):
    def test_registra_artefato_raiz_com_version_1(self):
        db = _db_vazio()
        resultado = artefatos.registrar_artefato(
            _factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'fake-png-bytes',
            mime_type='image/png', source_type='sku', source_id='MC-BACURI-100ML',
            agent_id='pirret', metadata={'brief': 'rótulo Bacuri, direção A'},
        )
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['version'], 1)
        self.assertTrue(resultado['storage_uri'].startswith('pg-blob:'))
        self.assertEqual(len(db['blobs']), 1)

    def test_tipo_invalido_recusa(self):
        db = _db_vazio()
        with self.assertRaises(ValueError):
            artefatos.registrar_artefato(
                _factory(db), artifact_type='RELATORIO_QUALQUER', conteudo=b'x', mime_type='text/plain',
            )

    def test_conteudo_nunca_e_perdido_bytes_identicos_na_leitura(self):
        db = _db_vazio()
        conteudo_original = b'\x89PNG\r\n conteudo binario real \x00\x01'
        artefatos.registrar_artefato(
            _factory(db), artifact_type='IMAGE', conteudo=conteudo_original, mime_type='image/png',
        )
        blob_id = next(iter(db['blobs']))
        cur = FakeArtefatoCursor(db)
        lido = PostgresBlobStorage(cur).ler(f'pg-blob:{blob_id}')
        self.assertEqual(lido, conteudo_original)


class VersionamentoELineage(unittest.TestCase):
    def test_versao_filha_incrementa_a_partir_do_pai_nunca_sobrescreve(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A', mime_type='image/png')
        a2 = artefatos.registrar_artefato(
            _factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A2', mime_type='image/png',
            parent_artifact_id=a['id'],
        )
        self.assertEqual(a2['version'], 2)
        # a versão anterior continua existindo e legível -- nunca é apagada/sobrescrita
        cur = FakeArtefatoCursor(db)
        original = artefatos.buscar_artefato(cur, a['id'])
        self.assertIsNotNone(original)
        self.assertEqual(original['version'], 1)

    def test_pai_inexistente_nao_cria_orfao(self):
        db = _db_vazio()
        resultado = artefatos.registrar_artefato(
            _factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png',
            parent_artifact_id=str(uuid4()),
        )
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'artefato_pai_nao_encontrado')
        self.assertEqual(db['artefatos'], {})

    def test_linhagem_a_a2_a3_vem_em_ordem_raiz_para_atual(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A', mime_type='image/png')
        a2 = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A2',
                                           mime_type='image/png', parent_artifact_id=a['id'])
        a3 = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A3',
                                           mime_type='image/png', parent_artifact_id=a2['id'])
        cur = FakeArtefatoCursor(db)
        cadeia = artefatos.linhagem_artefato(cur, a3['id'])
        self.assertEqual([c['id'] for c in cadeia], [a['id'], a2['id'], a3['id']])
        self.assertEqual([c['version'] for c in cadeia], [1, 2, 3])

    def test_linhagem_de_artefato_sem_pai_e_lista_de_um_elemento(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='CHART', conteudo=b'x', mime_type='image/png')
        cur = FakeArtefatoCursor(db)
        cadeia = artefatos.linhagem_artefato(cur, a['id'])
        self.assertEqual(len(cadeia), 1)

    def test_linhagem_de_id_inexistente_e_lista_vazia_nunca_erro(self):
        db = _db_vazio()
        cur = FakeArtefatoCursor(db)
        self.assertEqual(artefatos.linhagem_artefato(cur, str(uuid4())), [])


class TransicaoDeEstadoHumana(unittest.TestCase):
    def test_gerado_pode_ser_aprovado(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        resultado = artefatos.aprovar_artefato(_factory(db), a['id'], ator='diretor@maranhao')
        self.assertTrue(resultado['success'])
        self.assertEqual(db['artefatos'][a['id']]['status'], 'aprovado')
        self.assertIsNotNone(db['artefatos'][a['id']]['approved_at'])

    def test_gerado_pode_ser_rejeitado_com_motivo(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        resultado = artefatos.rejeitar_artefato(_factory(db), a['id'], ator='diretor', motivo='fora da direção de marca')
        self.assertTrue(resultado['success'])
        self.assertEqual(db['auditoria'][-1]['motivo'], 'fora da direção de marca')

    def test_aprovado_nunca_volta_a_gerado_transicao_bloqueada(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        artefatos.aprovar_artefato(_factory(db), a['id'], ator='diretor')
        resultado = artefatos.avancar_estado_artefato(_factory(db), a['id'], 'gerado', ator='alguem')
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'transicao_nao_permitida')
        self.assertEqual(db['artefatos'][a['id']]['status'], 'aprovado')  # nunca regride silenciosamente

    def test_rejeitado_nao_pode_virar_aprovado_direto(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        artefatos.rejeitar_artefato(_factory(db), a['id'], ator='diretor')
        resultado = artefatos.aprovar_artefato(_factory(db), a['id'], ator='diretor')
        self.assertFalse(resultado['success'])

    def test_ator_vazio_e_recusado_antes_de_tocar_o_banco(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        with self.assertRaises(ValueError):
            artefatos.aprovar_artefato(_factory(db), a['id'], ator='   ')
        self.assertEqual(db['artefatos'][a['id']]['status'], 'gerado')

    def test_artefato_inexistente_nao_derruba_o_processo(self):
        db = _db_vazio()
        resultado = artefatos.aprovar_artefato(_factory(db), str(uuid4()), ator='diretor')
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'artefato_nao_encontrado')


class Listagem(unittest.TestCase):
    def test_filtra_por_meeting_id_e_agent_id(self):
        db = _db_vazio()
        artefatos.registrar_artefato(_factory(db), artifact_type='PRESENTATION', conteudo=b'x',
                                      mime_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                                      meeting_id='reuniao-1', agent_id='pirret')
        artefatos.registrar_artefato(_factory(db), artifact_type='CHART', conteudo=b'y', mime_type='image/png',
                                      meeting_id='reuniao-2', agent_id='iris')
        cur = FakeArtefatoCursor(db)
        self.assertEqual(len(artefatos.listar_artefatos(cur, meeting_id='reuniao-1')), 1)
        self.assertEqual(len(artefatos.listar_artefatos(cur, agent_id='iris')), 1)
        self.assertEqual(len(artefatos.listar_artefatos(cur)), 2)

    def test_lista_vazia_quando_nao_ha_artefatos_nunca_fabrica_exemplo(self):
        db = _db_vazio()
        cur = FakeArtefatoCursor(db)
        self.assertEqual(artefatos.listar_artefatos(cur), [])


class StorageAbstrato(unittest.TestCase):
    def test_provider_nao_configurado_nunca_finge_persistencia(self):
        provider = StorageNaoConfigurado()
        self.assertFalse(provider.disponivel())
        with self.assertRaises(ErroStorageNaoConfigurado):
            provider.salvar(b'x', 'image/png')
        with self.assertRaises(ErroStorageNaoConfigurado):
            provider.ler('pg-blob:qualquer')

    def test_postgres_blob_storage_disponivel_e_true(self):
        db = _db_vazio()
        cur = FakeArtefatoCursor(db)
        self.assertTrue(PostgresBlobStorage(cur).disponivel())

    def test_ler_storage_uri_com_formato_invalido_recusa(self):
        db = _db_vazio()
        cur = FakeArtefatoCursor(db)
        with self.assertRaises(ValueError):
            PostgresBlobStorage(cur).ler('s3://bucket/objeto')


class RotasHTTP(unittest.TestCase):
    def _app(self, db, autorizado=lambda: True):
        app = Flask(__name__)
        artefatos.registrar_rotas(app, _factory(db), autorizado)
        return app

    def test_todas_as_rotas_exigem_autorizacao(self):
        db = _db_vazio()
        app = self._app(db, autorizado=lambda: False)
        cliente = app.test_client()
        artefato_id = str(uuid4())
        self.assertEqual(cliente.get('/api/admin/mi/artefatos').status_code, 401)
        self.assertEqual(cliente.get(f'/api/admin/mi/artefatos/{artefato_id}').status_code, 401)
        self.assertEqual(cliente.get(f'/api/admin/mi/artefatos/{artefato_id}/linhagem').status_code, 401)
        self.assertEqual(cliente.get(f'/api/admin/mi/artefatos/{artefato_id}/download').status_code, 401)
        self.assertEqual(cliente.post(f'/api/admin/mi/artefatos/{artefato_id}/aprovar').status_code, 401)
        self.assertEqual(cliente.post(f'/api/admin/mi/artefatos/{artefato_id}/rejeitar').status_code, 401)

    def test_nenhuma_rota_de_escrita_alem_de_aprovar_rejeitar(self):
        db = _db_vazio()
        app = self._app(db)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertTrue({'POST'} <= metodos)
        # só os dois endpoints humanos de decisão escrevem -- nada de PUT/DELETE/PATCH
        self.assertFalse(metodos & {'PUT', 'DELETE', 'PATCH'})

    def test_listar_vazio_retorna_200_lista_vazia_nunca_erro(self):
        db = _db_vazio()
        cliente = self._app(db).test_client()
        resp = cliente.get('/api/admin/mi/artefatos')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['artefatos'], [])

    def test_detalhe_de_artefato_inexistente_e_404_json_real(self):
        db = _db_vazio()
        cliente = self._app(db).test_client()
        resp = cliente.get(f'/api/admin/mi/artefatos/{uuid4()}')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()['success'])

    def test_fluxo_completo_criar_listar_aprovar_via_http(self):
        db = _db_vazio()
        resultado = artefatos.registrar_artefato(
            _factory(db), artifact_type='CHART', conteudo=b'grafico-png', mime_type='image/png',
        )
        cliente = self._app(db).test_client()
        listagem = cliente.get('/api/admin/mi/artefatos').get_json()
        self.assertEqual(len(listagem['artefatos']), 1)

        aprovar = cliente.post(f"/api/admin/mi/artefatos/{resultado['id']}/aprovar",
                                json={'ator': 'diretor@maranhao'})
        self.assertEqual(aprovar.status_code, 200)
        self.assertTrue(aprovar.get_json()['success'])

        detalhe = cliente.get(f"/api/admin/mi/artefatos/{resultado['id']}").get_json()
        self.assertEqual(detalhe['status'], 'aprovado')

    def test_aprovar_sem_ator_e_recusado_400(self):
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=b'x', mime_type='image/png')
        cliente = self._app(db).test_client()
        resp = cliente.post(f"/api/admin/mi/artefatos/{a['id']}/aprovar", json={})
        self.assertEqual(resp.status_code, 400)

    def test_download_devolve_bytes_originais_com_mime_type_correto(self):
        db = _db_vazio()
        conteudo = b'PNG-bytes-de-teste'
        a = artefatos.registrar_artefato(_factory(db), artifact_type='IMAGE', conteudo=conteudo, mime_type='image/png')
        cliente = self._app(db).test_client()
        resp = cliente.get(f"/api/admin/mi/artefatos/{a['id']}/download")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, conteudo)
        self.assertEqual(resp.mimetype, 'image/png')

    def test_linhagem_via_http_traz_cadeia_completa(self):
        # Lineage é consultada A PARTIR da versão de interesse (tipicamente
        # a mais recente) e sobe até a raiz via parent_artifact_id -- nunca
        # o contrário (a raiz não "conhece" seus filhos).
        db = _db_vazio()
        a = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A', mime_type='image/png')
        a2 = artefatos.registrar_artefato(_factory(db), artifact_type='LABEL_CONCEPT', conteudo=b'A2',
                                           mime_type='image/png', parent_artifact_id=a['id'])
        cliente = self._app(db).test_client()
        resp = cliente.get(f"/api/admin/mi/artefatos/{a2['id']}/linhagem")
        self.assertEqual(resp.status_code, 200)
        linhagem = resp.get_json()['linhagem']
        self.assertEqual(len(linhagem), 2)
        self.assertEqual([item['id'] for item in linhagem], [a['id'], a2['id']])


class NenhumaAcaoExternaNemEscritaFantasma(unittest.TestCase):
    def test_modulo_nunca_chama_canais_externos(self):
        import inspect
        codigo = inspect.getsource(artefatos)
        for proibido in ('OpenAI(', 'smtplib', 'requests.', 'import whatsapp', 'import gmail',
                          'INSERT INTO leads_crm', 'UPDATE leads_crm', 'salvar_pedido_postgres('):
            self.assertNotIn(proibido, codigo)

    def test_jsonify_nunca_recebe_chave_success_duplicada(self):
        # mesma classe de bug real encontrada e corrigida em
        # mi_outcome_relacionamento.py durante P3 -- aqui a rota já faz
        # resultado.pop('success', False) antes de repassar **resultado.
        import inspect
        codigo = inspect.getsource(artefatos)
        self.assertIn("resultado.pop('success'", codigo)


if __name__ == '__main__':
    unittest.main()
