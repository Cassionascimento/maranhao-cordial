"""P3A/P3B -- SIGNAL->SCORE->RECOMMENDATION->HUMAN DECISION->ACTION->OUTCOME.

Usa um fake in-memory de mi_fila_operacional/mi_fila_operacional_auditoria
(nunca um banco real) para testar a cadeia de ponta a ponta -- integração,
idempotência e rollback (transição não permitida), além dos testes
unitários de cada função."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

from flask import Flask
from psycopg2.extras import Json

import mi_outcome_relacionamento as outcome

AGORA = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _valor(v):
    return v.adapted if isinstance(v, Json) else v


class FakeFilaCursor:
    """Reimplementa só o subconjunto de SQL que mi_decisao.py/
    mi_outcome_relacionamento.py realmente emitem contra
    mi_fila_operacional/mi_fila_operacional_auditoria -- suficiente para
    exercitar a cadeia completa sem banco real."""

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
        elif sql_norma.startswith('INSERT INTO mi_fila_operacional('):
            campos = ('id', 'chave', 'payload_hash', 'estado', 'origem', 'origem_id', 'tipo_decisao', 'fatos',
                      'inferencia', 'prioridade', 'confianca', 'proxima_acao', 'exige_aprovacao', 'executar_em',
                      'lead_id', 'estabelecimento_id')
            linha = {campo: _valor(valor) for campo, valor in zip(campos, params)}
            if linha['chave'] in self.db['fila']:
                self._resultado = None  # ON CONFLICT DO NOTHING
            else:
                linha['resultado'] = None
                linha['criado_em'] = AGORA
                linha['atualizado_em'] = AGORA
                linha['concluido_em'] = None
                self.db['fila'][linha['chave']] = linha
                self._resultado = {'id': linha['id']}
        elif sql_norma.startswith('SELECT id, payload_hash, estado FROM mi_fila_operacional WHERE chave'):
            linha = self.db['fila'].get(params[0])
            self._resultado = {'id': linha['id'], 'payload_hash': linha['payload_hash'], 'estado': linha['estado']} if linha else None
        elif sql_norma.startswith('SELECT id, estado FROM mi_fila_operacional WHERE chave=%s FOR UPDATE'):
            linha = self.db['fila'].get(params[0])
            self._resultado = {'id': linha['id'], 'estado': linha['estado']} if linha else None
        elif sql_norma.startswith('SELECT id, estado FROM mi_fila_operacional WHERE chave=%s'):
            linha = self.db['fila'].get(params[0])
            self._resultado = {'id': linha['id'], 'estado': linha['estado']} if linha else None
        elif sql_norma.startswith('UPDATE mi_fila_operacional SET estado='):
            novo_estado, resultado, item_id = params
            linha = next(l for l in self.db['fila'].values() if l['id'] == item_id)
            linha['estado'] = novo_estado
            linha['resultado'] = _valor(resultado)
            if novo_estado in ('concluida', 'bloqueada'):
                linha['concluido_em'] = AGORA
            self._resultado = None
        elif sql_norma.startswith('INSERT INTO mi_fila_operacional_auditoria'):
            if "VALUES(%s,NULL,%s,'mi_decisao')" in sql_norma:
                item_id, estado_novo = params
                estado_anterior, ator = None, 'mi_decisao'
            else:
                item_id, estado_anterior, estado_novo, ator = params
            self.db['auditoria'].append({'item_id': item_id, 'estado_anterior': estado_anterior,
                                          'estado_novo': estado_novo, 'ator': ator})
            self._resultado = None
        elif sql_norma.startswith('SELECT chave, tipo_decisao, fatos'):
            origem, limite = params
            linhas = [l for l in self.db['fila'].values() if l['origem'] == origem]
            linhas.sort(key=lambda l: l['criado_em'], reverse=True)
            self._resultado = linhas[:limite]
        else:
            raise AssertionError(f'SQL não coberto pelo fake: {sql_norma[:80]}')

    def fetchone(self):
        if isinstance(self._resultado, list):
            return self._resultado[0] if self._resultado else None
        return self._resultado

    def fetchall(self):
        return self._resultado if isinstance(self._resultado, list) else ([self._resultado] if self._resultado else [])


class FakeFilaConn:
    def __init__(self, db):
        self.db = db
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return FakeFilaCursor(self.db)

    def close(self):
        self.closed = True

    def set_session(self, **kwargs):
        pass


def _fabrica_fila():
    db = {'fila': {}, 'auditoria': []}
    return (lambda: FakeFilaConn(db)), db


def _recomendacao(action='CONTACT_REORDER', priority='alta', confidence=1.0, relationship_id=None):
    return {'action': action, 'reason': 'provavel_recompra (prioridade alta)', 'evidence': ['fato real'],
            'confidence': confidence, 'generated_at': AGORA.isoformat(), 'relationship_id': relationship_id,
            'priority': priority, 'sku': None}


def _score():
    return {'versao': 'relacionamento_score_v1', 'score_geral': 78.5}


class ApresentarRecomendacao(unittest.TestCase):
    def test_grava_recomendacao_com_versao_de_score_e_regra_em_fatos(self):
        factory, db = _fabrica_fila()
        lead_id = str(uuid4())
        resultado, status = outcome.registrar_recomendacao_apresentada(
            factory, _recomendacao(relationship_id=lead_id), _score(), lead_id=lead_id, agora=AGORA,
        )
        self.assertEqual(status, 201)
        self.assertTrue(resultado['criado'])
        linha = next(iter(db['fila'].values()))
        self.assertIn('score_versao=relacionamento_score_v1', linha['fatos'])
        self.assertIn('regra_versao=' + outcome.REGRA_VERSAO, linha['fatos'])
        self.assertEqual(linha['estado'], 'aguardando')  # exige_aprovacao sempre True

    def test_idempotente_no_mesmo_dia_nunca_duplica(self):
        factory, db = _fabrica_fila()
        lead_id = str(uuid4())
        r1, s1 = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(relationship_id=lead_id),
                                                             _score(), lead_id=lead_id, agora=AGORA)
        r2, s2 = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(relationship_id=lead_id),
                                                             _score(), lead_id=lead_id, agora=AGORA)
        self.assertEqual(s1, 201)
        self.assertEqual(s2, 200)
        self.assertFalse(r2['criado'])
        self.assertEqual(len(db['fila']), 1)


class DecisaoHumana(unittest.TestCase):
    def test_rejeicao_vai_para_bloqueada_com_motivo(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        resultado = outcome.registrar_decisao_humana(factory, item['chave'], False, 'diretor-1', motivo='fora de escopo')
        self.assertTrue(resultado['success'])
        linha = db['fila'][item['chave']]
        self.assertEqual(linha['estado'], 'bloqueada')
        self.assertEqual(linha['resultado']['decisao_humana'], 'rejeitada')
        self.assertEqual(linha['resultado']['motivo'], 'fora de escopo')

    def test_aceite_nao_muda_estado_mas_fica_auditado(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        resultado = outcome.registrar_decisao_humana(factory, item['chave'], True, 'diretor-1')
        self.assertTrue(resultado['success'])
        self.assertEqual(db['fila'][item['chave']]['estado'], 'aguardando')
        self.assertTrue(any(a['ator'] == 'diretor-1' for a in db['auditoria']))

    def test_chave_inexistente_falha_sem_quebrar(self):
        factory, _ = _fabrica_fila()
        resultado = outcome.registrar_decisao_humana(factory, str(uuid4()), True, 'diretor-1')
        self.assertFalse(resultado['success'])


class OutcomeERollback(unittest.TestCase):
    def test_outcome_apos_aceite_marca_concluida_com_executada(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        outcome.registrar_decisao_humana(factory, item['chave'], True, 'diretor-1')
        resultado = outcome.registrar_outcome(factory, item['chave'], {'pedido_gerado': 'MAR-9'}, 'diretor-1', True)
        self.assertTrue(resultado['success'])
        linha = db['fila'][item['chave']]
        self.assertEqual(linha['estado'], 'concluida')
        self.assertTrue(linha['resultado']['executada'])
        self.assertEqual(linha['resultado']['pedido_gerado'], 'MAR-9')

    def test_outcome_aceita_mas_nao_executada_e_um_resultado_valido(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        resultado = outcome.registrar_outcome(factory, item['chave'], None, 'diretor-1', False)
        self.assertTrue(resultado['success'])
        self.assertFalse(db['fila'][item['chave']]['resultado']['executada'])

    def test_rollback_nunca_registra_outcome_sobre_item_rejeitado(self):
        # 'bloqueada' só permite ir para 'precisa_diretor' -- nunca direto
        # para 'concluida'. Isso é a garantia já existente em
        # mi_decisao.TRANSICOES_PERMITIDAS; o wrapper nunca a contorna.
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        outcome.registrar_decisao_humana(factory, item['chave'], False, 'diretor-1', motivo='sem evidência')
        resultado = outcome.registrar_outcome(factory, item['chave'], {'x': 1}, 'diretor-1', True)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'transicao_nao_permitida')
        self.assertEqual(db['fila'][item['chave']]['estado'], 'bloqueada')  # nunca mudou

    def test_outcome_nunca_reabre_item_ja_concluido(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        outcome.registrar_outcome(factory, item['chave'], {'a': 1}, 'diretor-1', True)
        segundo = outcome.registrar_outcome(factory, item['chave'], {'b': 2}, 'diretor-1', True)
        self.assertFalse(segundo['success'])
        self.assertEqual(db['fila'][item['chave']]['resultado']['a'], 1)  # preservado, não sobrescrito


class HistoricoEDataset(unittest.TestCase):
    def test_dataset_reflete_toda_a_cadeia(self):
        factory, db = _fabrica_fila()
        item, _ = outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        outcome.registrar_outcome(factory, item['chave'], {'pedido': 'MAR-1'}, 'diretor-1', True)
        cur = FakeFilaCursor(db)
        dataset = outcome.exportar_dataset_aprendizado(cur)
        self.assertEqual(dataset['dataset_versao'], outcome.LEARNING_DATASET_VERSAO)
        self.assertEqual(dataset['total_linhas'], 1)
        linha = dataset['linhas'][0]
        self.assertEqual(linha['human_decision'], 'aceita')
        self.assertTrue(linha['executada'])
        self.assertEqual(linha['score_versao'], 'relacionamento_score_v1')
        self.assertEqual(linha['regra_versao'], outcome.REGRA_VERSAO)

    def test_dataset_vazio_e_explicito_nunca_inventa_linha(self):
        _, db = _fabrica_fila()
        cur = FakeFilaCursor(db)
        dataset = outcome.exportar_dataset_aprendizado(cur)
        self.assertEqual(dataset['total_linhas'], 0)
        self.assertEqual(dataset['linhas'], [])

    def test_historico_filtra_por_origem_relacionamento_360(self):
        factory, db = _fabrica_fila()
        outcome.registrar_recomendacao_apresentada(factory, _recomendacao(), _score(), agora=AGORA)
        cur = FakeFilaCursor(db)
        historico = outcome.historico_decisoes(cur)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]['tipo_decisao'], 'contact_reorder')


class NenhumaAcaoExterna(unittest.TestCase):
    def test_modulo_nunca_importa_ou_chama_canais_externos(self):
        import inspect
        codigo = inspect.getsource(outcome)
        for proibido in ('OpenAI(', 'smtplib', 'requests.', 'import whatsapp', 'from whatsapp',
                          'import gmail', 'from gmail', 'import c6_', 'from c6_', 'salvar_pedido_postgres(',
                          '.propor(', 'acoes_comerciais.executar', 'criar_checkout'):
            self.assertNotIn(proibido, codigo)

    def test_unica_tabela_tocada_e_mi_fila_operacional(self):
        import inspect
        codigo = inspect.getsource(outcome)
        for tabela_proibida in ('leads_crm', 'interacoes_omnichannel', 'pedidos', 'compras_relacionamento',
                                 'identidades_externas_contato'):
            self.assertNotIn(f'INSERT INTO {tabela_proibida}', codigo)
            self.assertNotIn(f'UPDATE {tabela_proibida}', codigo)


class RotasEscrita(unittest.TestCase):
    def _app(self, db=None, autorizado=lambda: True):
        factory, db = (lambda: FakeFilaConn(db)), db if db is not None else _fabrica_fila()
        app = Flask(__name__)
        outcome.registrar_rotas(app, factory, autorizado)
        return app.test_client(), db

    def test_todas_as_rotas_de_escrita_exigem_autorizacao(self):
        app = Flask(__name__)
        outcome.registrar_rotas(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.post('/api/admin/mi/relacionamento/recomendacao/apresentar', json={}).status_code, 401)
        self.assertEqual(cliente.post('/api/admin/mi/relacionamento/recomendacao/decisao', json={}).status_code, 401)
        self.assertEqual(cliente.post('/api/admin/mi/relacionamento/recomendacao/outcome', json={}).status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/relacionamento/decisoes').status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/relacionamento/dataset-aprendizado').status_code, 401)

    def test_outcome_sem_executada_explicito_e_rejeitado(self):
        factory, db = _fabrica_fila()
        app = Flask(__name__)
        outcome.registrar_rotas(app, factory, lambda: True)
        resp = app.test_client().post('/api/admin/mi/relacionamento/recomendacao/outcome',
                                       json={'chave': str(uuid4())})
        self.assertEqual(resp.status_code, 400)

    def test_fluxo_completo_via_rotas_http(self):
        factory, db = _fabrica_fila()
        app = Flask(__name__)
        outcome.registrar_rotas(app, factory, lambda: True)
        cliente = app.test_client()
        r1 = cliente.post('/api/admin/mi/relacionamento/recomendacao/apresentar',
                           json={'recomendacao': _recomendacao(), 'score': _score()})
        self.assertEqual(r1.status_code, 201)
        chave = r1.get_json()['chave']
        r2 = cliente.post('/api/admin/mi/relacionamento/recomendacao/decisao',
                           json={'chave': chave, 'aceita': True, 'ator': 'diretor-1'})
        self.assertEqual(r2.status_code, 200)
        r3 = cliente.post('/api/admin/mi/relacionamento/recomendacao/outcome',
                           json={'chave': chave, 'executada': True, 'resultado_observado': {'ok': True}, 'ator': 'diretor-1'})
        self.assertEqual(r3.status_code, 200)
        r4 = cliente.get('/api/admin/mi/relacionamento/dataset-aprendizado')
        self.assertEqual(r4.get_json()['total_linhas'], 1)


if __name__ == '__main__':
    unittest.main()
