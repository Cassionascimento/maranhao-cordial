"""ETAPA 5.0: mi_decisao.py -- SINAL -> PRIORIDADE -> PRÓXIMA AÇÃO -> FILA.

planejar() é DRY-RUN: os testes de 'Analisadores' e 'Planejar' garantem que
nenhuma chamada de escrita (INSERT/UPDATE/DELETE) acontece nesse caminho.
registrar_item_fila/avancar_estado_fila são testados à parte (mesma
disciplina de mi_sinais.py), mas nunca são chamados por planejar().
"""
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import mi_decisao as d


def sem_escrita(cur):
    """Nenhuma chamada de execute() deve conter verbos de escrita."""
    for chamada in cur.execute.call_args_list:
        sql = chamada.args[0].upper()
        assert not any(v in sql for v in ('INSERT ', 'UPDATE ', 'DELETE ', 'DROP ', 'ALTER ')), sql


class AnalisadorPesquisas(unittest.TestCase):
    def test_campanha_abaixo_da_meta_sem_pesquisa_pendente_precisa_pesquisar(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'camp-1', 'codigo': 'X', 'meta_contatos': 20, 'contatos_uteis': 5}]
        cur.fetchone.return_value = {'qtd': 0}
        decisoes = d.analisar_pesquisas_pendentes(cur)
        self.assertEqual(len(decisoes), 1)
        item = decisoes[0]
        self.assertEqual(item['tipo_decisao'], 'pesquisa_necessaria')
        self.assertEqual(item['proxima_acao'], 'pesquisar')
        self.assertFalse(item['exige_aprovacao'])
        self.assertEqual(item['estado'], 'planejada')
        self.assertEqual(item['confianca'], 1.0)
        sem_escrita(cur)

    def test_campanha_com_pesquisa_pendente_nao_repete_decisao(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'camp-1', 'codigo': 'X', 'meta_contatos': 20, 'contatos_uteis': 5}]
        cur.fetchone.return_value = {'qtd': 1}
        self.assertEqual(d.analisar_pesquisas_pendentes(cur), [])

    def test_campanha_na_meta_nao_precisa_pesquisar(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'camp-1', 'codigo': 'X', 'meta_contatos': 20, 'contatos_uteis': 20}]
        self.assertEqual(d.analisar_pesquisas_pendentes(cur), [])

    def test_muitos_contatos_faltando_e_prioridade_alta(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'camp-1', 'codigo': 'X', 'meta_contatos': 20, 'contatos_uteis': 0}]
        cur.fetchone.return_value = {'qtd': 0}
        self.assertEqual(d.analisar_pesquisas_pendentes(cur)[0]['prioridade'], 'alta')


class AnalisadorFollowup(unittest.TestCase):
    def test_prospecto_vencido_gera_decisao_de_followup(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'p-1', 'score': 90, 'proximo_followup_em': '2026-01-01'}]
        decisoes = d.analisar_followups_devidos(cur)
        item = decisoes[0]
        self.assertEqual(item['tipo_decisao'], 'followup_devido')
        self.assertEqual(item['proxima_acao'], 'enviar_followup')
        self.assertTrue(item['exige_aprovacao'])  # tem efeito externo -> política existente
        self.assertEqual(item['estado'], 'aguardando')
        self.assertEqual(item['prioridade'], 'urgente')  # score 90
        self.assertEqual(item['executar_em'], '2026-01-01')  # a agenda já existente define o horário
        sem_escrita(cur)

    def test_sem_prospecto_vencido_lista_vazia(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        self.assertEqual(d.analisar_followups_devidos(cur), [])


class AnalisadorOportunidades(unittest.TestCase):
    def test_negociacao_parada_gera_decisao(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'p-2', 'score': 40, 'ultima_resposta_em': None, 'ultimo_contato_em': '2026-01-01'}]
        decisoes = d.analisar_oportunidades_paradas(cur)
        item = decisoes[0]
        self.assertEqual(item['tipo_decisao'], 'oportunidade_parada')
        self.assertEqual(item['proxima_acao'], 'avaliar_reengajamento')
        self.assertTrue(item['exige_aprovacao'])
        sem_escrita(cur)


class AnalisadorBloqueios(unittest.TestCase):
    def test_bloqueio_vira_precisa_diretor(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'origem_id': 'acao-1', 'criado_em': '2026-01-01'}]
        decisoes = d.analisar_bloqueios(cur)
        item = decisoes[0]
        self.assertEqual(item['estado'], 'precisa_diretor')
        self.assertEqual(item['proxima_acao'], 'revisar_bloqueio')
        self.assertTrue(item['exige_aprovacao'])
        sem_escrita(cur)


class AnalisadorPendenciasDiretor(unittest.TestCase):
    def test_proposta_sem_decisao_vira_precisa_diretor(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'sinal-1', 'origem_id': 'acao-2', 'criado_em': '2026-01-01'}]
        decisoes = d.analisar_pendencias_diretor(cur)
        item = decisoes[0]
        self.assertEqual(item['estado'], 'precisa_diretor')
        self.assertEqual(item['proxima_acao'], 'decidir_proposta')
        sem_escrita(cur)


class AnalisadorLeads(unittest.TestCase):
    def test_lead_com_alto_valor_e_urgente(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'lead-1', 'estagio': 'qualificacao', 'cidade': 'São Luís',
                                       'estado': 'MA', 'valor_potencial_centavos': 2_000_000}]
        item = d.analisar_leads_prioritarios(cur)[0]
        self.assertEqual(item['prioridade'], 'urgente')
        self.assertFalse(item['exige_aprovacao'])  # é leitura de prioridade, não ação externa
        self.assertEqual(item['estado'], 'planejada')
        self.assertEqual(item['lead_id'], 'lead-1')
        sem_escrita(cur)

    def test_lead_sem_valor_declarado_tem_confianca_menor(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': 'lead-2', 'estagio': 'qualificacao', 'cidade': None,
                                       'estado': None, 'valor_potencial_centavos': None}]
        item = d.analisar_leads_prioritarios(cur)[0]
        self.assertEqual(item['confianca'], 0.6)
        self.assertEqual(item['prioridade'], 'normal')


class Planejar(unittest.TestCase):
    def test_agrega_todos_os_analisadores_em_snapshot_readonly(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        cur.fetchone.return_value = {'qtd': 0}
        decisoes = d.planejar(lambda: conn)
        self.assertEqual(decisoes, [])
        conn.set_session.assert_called_once_with(readonly=True, isolation_level='REPEATABLE READ')
        conn.close.assert_called_once()
        sem_escrita(cur)

    def test_nunca_escreve_mesmo_com_dados_reais_em_todas_as_analises(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            {'id': 'x', 'codigo': 'X', 'meta_contatos': 20, 'contatos_uteis': 0,
             'score': 90, 'proximo_followup_em': '2026-01-01', 'ultima_resposta_em': None,
             'ultimo_contato_em': '2026-01-01', 'origem_id': 'a', 'criado_em': '2026-01-01',
             'estagio': 'proposta', 'cidade': 'São Luís', 'estado': 'MA',
             'valor_potencial_centavos': 500000},
        ]
        cur.fetchone.return_value = {'qtd': 0, 'id': 'sinal', 'total': 1}
        d.planejar(lambda: conn)
        sem_escrita(cur)

    def test_falha_na_analise_fecha_conexao(self):
        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError('sem conexao')
        with self.assertRaises(RuntimeError):
            d.planejar(lambda: conn)
        conn.close.assert_called_once()

    def test_cada_atividade_sai_com_chave_de_idempotencia(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        with patch.object(d, 'analisar_pesquisas_pendentes', return_value=[]), \
             patch.object(d, 'analisar_followups_devidos', return_value=[]), \
             patch.object(d, 'analisar_oportunidades_paradas', return_value=[]), \
             patch.object(d, 'analisar_bloqueios', return_value=[]), \
             patch.object(d, 'analisar_pendencias_diretor', return_value=[]), \
             patch.object(d, 'analisar_leads_prioritarios',
                          return_value=[d._decisao('crm', 'lead-1', 'lead_prioritario', [], 'x', 'alta', 0.9,
                                                    'priorizar_atendimento', exige_aprovacao=False)]):
            decisoes = d.planejar(lambda: conn)
        self.assertEqual(len(decisoes), 1)
        self.assertIn('chave', decisoes[0])


class ChaveAtividade(unittest.TestCase):
    BASE = {'origem': 'crm', 'tipo_decisao': 'lead_prioritario', 'origem_id': 'lead-1'}

    def test_mesma_decisao_mesmo_dia_gera_a_mesma_chave(self):
        agora = __import__('datetime').datetime(2026, 1, 1, 10, tzinfo=__import__('datetime').timezone.utc)
        c1 = d.chave_atividade(self.BASE, agora)
        c2 = d.chave_atividade(dict(self.BASE), agora)
        self.assertEqual(c1, c2)

    def test_mesma_decisao_dias_diferentes_gera_chaves_diferentes(self):
        import datetime as dt
        c1 = d.chave_atividade(self.BASE, dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        c2 = d.chave_atividade(self.BASE, dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc))
        self.assertNotEqual(c1, c2)

    def test_origem_id_diferente_gera_chave_diferente(self):
        import datetime as dt
        agora = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        c1 = d.chave_atividade(self.BASE, agora)
        c2 = d.chave_atividade(dict(self.BASE, origem_id='lead-2'), agora)
        self.assertNotEqual(c1, c2)


class Calendario(unittest.TestCase):
    def _atividade(self, **kw):
        base = dict(estado='planejada', executar_em=None, tipo_decisao='pesquisa_necessaria')
        base.update(kw)
        return base

    def test_planejada_sem_horario_cai_em_hoje(self):
        c = d.calendario([self._atividade()])
        self.assertEqual(len(c['hoje']), 1)
        self.assertEqual(c['proximas'], [])

    def test_planejada_com_data_futura_cai_em_proximas(self):
        import datetime as dt
        agora = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        futuro = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
        c = d.calendario([self._atividade(executar_em=futuro)], agora=agora)
        self.assertEqual(len(c['proximas']), 1)
        self.assertEqual(c['hoje'], [])

    def test_planejada_com_data_passada_cai_em_hoje(self):
        import datetime as dt
        agora = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
        passado = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        c = d.calendario([self._atividade(executar_em=passado)], agora=agora)
        self.assertEqual(len(c['hoje']), 1)

    def test_cada_estado_cai_no_balde_certo(self):
        atividades = [
            self._atividade(estado='aguardando'),
            self._atividade(estado='concluida'),
            self._atividade(estado='bloqueada'),
            self._atividade(estado='precisa_diretor'),
        ]
        c = d.calendario(atividades)
        self.assertEqual(len(c['aguardando']), 1)
        self.assertEqual(len(c['concluidas']), 1)
        self.assertEqual(len(c['bloqueadas']), 1)
        self.assertEqual(len(c['precisa_diretor']), 1)
        self.assertEqual(c['hoje'], [])

    def test_proxima_atividade_e_a_de_menor_executar_em(self):
        import datetime as dt
        cedo = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
        tarde = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        c = d.calendario([
            self._atividade(estado='aguardando', executar_em=tarde, tipo_decisao='b'),
            self._atividade(estado='aguardando', executar_em=cedo, tipo_decisao='a'),
        ])
        self.assertEqual(c['proxima_atividade']['tipo_decisao'], 'a')

    def test_sem_executar_em_nenhuma_atividade_e_proxima(self):
        c = d.calendario([self._atividade(estado='aguardando', executar_em=None)])
        self.assertIsNone(c['proxima_atividade'])


class LeituraCalendario(unittest.TestCase):
    def test_agrega_as_perguntas_da_5_1(self):
        atividades = [
            {'estado': 'planejada', 'executar_em': None, 'tipo_decisao': 'pesquisa_necessaria'},
            {'estado': 'aguardando', 'executar_em': None, 'tipo_decisao': 'followup_devido'},
            {'estado': 'precisa_diretor', 'executar_em': None, 'tipo_decisao': 'bloqueio_pendente'},
        ]
        r = d.leitura_calendario(atividades)
        self.assertTrue(r['ia_trabalhando'])
        self.assertEqual(len(r['fara_hoje']), 1)
        self.assertEqual(r['fazendo_agora'], [])  # pendente: exige fila persistida
        self.assertEqual(r['concluiu'], [])  # DRY-RUN nunca persiste
        self.assertEqual(len(r['aguardando']), 1)
        self.assertEqual(len(r['precisa_diretor']), 1)

    def test_sem_atividades_ia_nao_esta_trabalhando(self):
        r = d.leitura_calendario([])
        self.assertFalse(r['ia_trabalhando'])
        self.assertIsNone(r['proxima_atividade'])


class ParaFila(unittest.TestCase):
    def test_extrai_somente_campos_aceitos_por_registrar_item_fila(self):
        atividade = d._decisao('crm', 'lead-1', 'lead_prioritario', ['lead:lead-1'], 'motivo x',
                                'alta', 0.9, 'priorizar_atendimento', exige_aprovacao=False, lead_id='lead-1')
        atividade['chave'] = d.chave_atividade(atividade)
        body = d._para_fila(atividade)
        self.assertEqual(set(body) - {'chave'}, set(d.CAMPOS))
        self.assertNotIn('estado', body)
        self.assertNotIn('motivo', body)


class ReagendarAutomaticamente(unittest.TestCase):
    def test_acao_autonoma_pode_ser_reagendada(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'item-1', 'proxima_acao': 'pesquisar', 'estado': 'planejada'}
        r = d.reagendar_automaticamente(lambda: conn, str(uuid4()), '2026-02-01T00:00:00+00:00')
        self.assertTrue(r['success'])

    def test_acao_com_efeito_externo_nao_pode_ser_reagendada(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'item-1', 'proxima_acao': 'enviar_followup', 'estado': 'aguardando'}
        r = d.reagendar_automaticamente(lambda: conn, str(uuid4()), '2026-02-01T00:00:00+00:00')
        self.assertFalse(r['success'])
        self.assertEqual(r['motivo'], 'acao_externa_nao_pode_ser_reagendada_automaticamente')
        update_calls = [c for c in cur.execute.call_args_list if 'SET EXECUTAR_EM' in c.args[0].upper()]
        self.assertEqual(update_calls, [])

    def test_item_concluido_nao_pode_ser_reagendado(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'item-1', 'proxima_acao': 'pesquisar', 'estado': 'concluida'}
        r = d.reagendar_automaticamente(lambda: conn, str(uuid4()), '2026-02-01T00:00:00+00:00')
        self.assertFalse(r['success'])
        self.assertEqual(r['motivo'], 'item_ja_concluido_ou_bloqueado')

    def test_item_inexistente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        r = d.reagendar_automaticamente(lambda: conn, str(uuid4()), '2026-02-01T00:00:00+00:00')
        self.assertFalse(r['success'])
        self.assertEqual(r['motivo'], 'item_nao_encontrado')


class ResumoLeitura(unittest.TestCase):
    def test_agrupa_por_estado_e_tipo(self):
        decisoes = [
            {'estado': 'planejada', 'tipo_decisao': 'pesquisa_necessaria'},
            {'estado': 'aguardando', 'tipo_decisao': 'followup_devido'},
            {'estado': 'aguardando', 'tipo_decisao': 'oportunidade_parada'},
            {'estado': 'precisa_diretor', 'tipo_decisao': 'bloqueio_pendente'},
        ]
        r = d.resumo_leitura(decisoes)
        self.assertTrue(r['ia_trabalhando'])
        self.assertEqual(len(r['hoje_fara']), 1)
        self.assertEqual(len(r['aguardando']), 2)
        self.assertEqual(len(r['oportunidades']), 1)
        self.assertEqual(len(r['precisa_diretor']), 1)
        self.assertEqual(r['total'], 4)

    def test_sem_decisoes_ia_nao_esta_trabalhando(self):
        r = d.resumo_leitura([])
        self.assertFalse(r['ia_trabalhando'])
        self.assertEqual(r['total'], 0)


class ValidacaoFila(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), origem='crm', origem_id='lead-1', tipo_decisao='lead_prioritario',
                       fatos=['lead:lead-1'], inferencia='x', prioridade='alta', confianca=0.8,
                       proxima_acao='priorizar_atendimento', exige_aprovacao=False), **kw}

    def test_item_minimo_valido(self):
        chave, item, digest = d.validar_item_fila(self.body())
        self.assertEqual(item['prioridade'], 'alta')
        self.assertTrue(digest)

    def test_rejeita_prioridade_invalida(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(prioridade='criticalissima'))

    def test_rejeita_fatos_nao_lista_de_strings(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(fatos=[1, 2]))

    def test_rejeita_exige_aprovacao_nao_booleano(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(exige_aprovacao='sim'))

    def test_rejeita_confianca_fora_do_intervalo(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(confianca=2))

    def test_aceita_executar_em_como_datetime_e_normaliza_para_iso(self):
        import datetime as dt
        quando = dt.datetime(2026, 2, 1, 10, tzinfo=dt.timezone.utc)
        _, item, _ = d.validar_item_fila(self.body(executar_em=quando))
        self.assertEqual(item['executar_em'], quando.isoformat())

    def test_aceita_executar_em_como_string_iso(self):
        _, item, _ = d.validar_item_fila(self.body(executar_em='2026-02-01T10:00:00+00:00'))
        self.assertEqual(item['executar_em'], '2026-02-01T10:00:00+00:00')

    def test_rejeita_executar_em_de_tipo_invalido(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(executar_em=12345))

    def test_aceita_lead_id_e_estabelecimento_id_como_uuid(self):
        lead_id = str(uuid4())
        _, item, _ = d.validar_item_fila(self.body(lead_id=lead_id))
        self.assertEqual(item['lead_id'], lead_id)
        self.assertIsNone(item['estabelecimento_id'])

    def test_rejeita_lead_id_mal_formado(self):
        with self.assertRaises(ValueError):
            d.validar_item_fila(self.body(lead_id='nao-e-uuid'))


class RegistroFila(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), origem='crm', origem_id='lead-1', tipo_decisao='lead_prioritario',
                       fatos=['lead:lead-1'], inferencia='x', prioridade='alta', confianca=0.8,
                       proxima_acao='priorizar_atendimento', exige_aprovacao=False), **kw}

    def test_criacao_com_exige_aprovacao_falso_comeca_planejada(self):
        body = self.body()
        digest = d.validar_item_fila(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo'}, {'id': 'novo', 'payload_hash': digest, 'estado': 'planejada'}]
        resposta, status = d.registrar_item_fila(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertEqual(resposta['estado'], 'planejada')

    def test_criacao_com_exige_aprovacao_verdadeiro_comeca_aguardando(self):
        body = self.body(exige_aprovacao=True)
        digest = d.validar_item_fila(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo'}, {'id': 'novo', 'payload_hash': digest, 'estado': 'aguardando'}]
        resposta, status = d.registrar_item_fila(lambda: conn, body)
        self.assertEqual(resposta['estado'], 'aguardando')

    def test_chave_repetida_e_idempotente(self):
        body = self.body()
        digest = d.validar_item_fila(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': digest, 'estado': 'planejada'}]
        resposta, status = d.registrar_item_fila(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])

    def test_chave_repetida_com_conteudo_diferente_e_conflito(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': 'outro', 'estado': 'planejada'}]
        resposta, status = d.registrar_item_fila(lambda: conn, body)
        self.assertEqual(status, 409)


class TransicaoFila(unittest.TestCase):
    def test_planejada_para_concluida_seta_concluido_em(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'item-1', 'estado': 'planejada'}
        r = d.avancar_estado_fila(lambda: conn, str(uuid4()), 'concluida', 'sistema')
        self.assertTrue(r['success'])
        update_sql = cur.execute.call_args_list[1].args[0]
        self.assertIn('NOW()', update_sql)

    def test_concluida_nunca_reabre(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'item-1', 'estado': 'concluida'}
        r = d.avancar_estado_fila(lambda: conn, str(uuid4()), 'planejada', 'sistema')
        self.assertFalse(r['success'])
        self.assertEqual(r['motivo'], 'transicao_nao_permitida')

    def test_item_inexistente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        r = d.avancar_estado_fila(lambda: conn, str(uuid4()), 'concluida', 'sistema')
        self.assertFalse(r['success'])
        self.assertEqual(r['motivo'], 'item_nao_encontrado')

    def test_estado_desconhecido_e_rejeitado_sem_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            d.avancar_estado_fila(factory, str(uuid4()), 'em_progresso', 'sistema')
        factory.assert_not_called()


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(d))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'gmail_legado', 'whatsapp_meta',
                          'whatsapp_omnichannel', 'openai'):
            self.assertNotIn(proibido, modulos)

    def test_planejar_nao_chama_registrar_item_fila_nem_emitir(self):
        with patch('mi_decisao.registrar_item_fila') as registrar:
            conn = MagicMock()
            cur = conn.cursor.return_value.__enter__.return_value
            cur.fetchall.return_value = []
            cur.fetchone.return_value = {'qtd': 0}
            d.planejar(lambda: conn)
        registrar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
