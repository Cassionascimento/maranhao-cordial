"""Conselho de Agentes -- mi_conselho.py. Mesma disciplina de mi_sinais.py/
mi_decisao.py: idempotência por chave, correção nunca sobrescreve, DRY-RUN
nas leituras, nenhum motor/fila/calendário paralelo (recomendacao_para_
atividade só monta o dict; quem persiste é mi_decisao.registrar_item_fila,
não duplicado aqui)."""
import unittest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from flask import Flask
import mi_conselho as c


class Agentes(unittest.TestCase):
    def test_sao_exatamente_os_8_pedidos(self):
        self.assertEqual(set(c.AGENTES), {'pirret', 'standard', 'zilda', 'leonard', 'marie', 'rua', 'dicio', 'iris'})

    def test_cada_agente_tem_nome_e_area(self):
        for codigo, info in c.AGENTES.items():
            self.assertIn('nome', info)
            self.assertIn('area', info)


class ValidarMensagem(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), de_agente='leonard', para_agente='rua', texto='Há capacidade?'), **kw}

    def test_mensagem_minima_valida(self):
        chave, dados = c.validar_mensagem(self.body())
        self.assertEqual(dados['de_agente'], 'leonard')
        self.assertEqual(dados['para_agente'], 'rua')

    def test_para_agente_pode_ser_ausente_broadcast(self):
        _, dados = c.validar_mensagem(self.body(para_agente=None))
        self.assertIsNone(dados['para_agente'])

    def test_agente_desconhecido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            c.validar_mensagem(self.body(de_agente='fulano'))
        with self.assertRaises(ValueError):
            c.validar_mensagem(self.body(para_agente='fulano'))

    def test_texto_vazio_e_rejeitado(self):
        with self.assertRaises(ValueError):
            c.validar_mensagem(self.body(texto='   '))

    def test_texto_muito_longo_e_rejeitado(self):
        with self.assertRaises(ValueError):
            c.validar_mensagem(self.body(texto='x' * 5000))


class RegistrarMensagem(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), de_agente='leonard', para_agente='rua', texto='Há capacidade?'), **kw}

    def test_criacao_grava_uma_unica_vez(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'nova'}, {'id': 'nova'}]
        resposta, status = c.registrar_mensagem(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])

    def test_mensagem_repetida_e_idempotente(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente'}]
        resposta, status = c.registrar_mensagem(lambda: conn, body)
        self.assertEqual(status, 200)
        self.assertFalse(resposta['criado'])

    def test_validacao_falha_antes_de_conectar(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        with self.assertRaises(ValueError):
            c.registrar_mensagem(factory, {'chave': str(uuid4()), 'de_agente': 'fulano', 'texto': 'x'})
        factory.assert_not_called()


class ValidarRegistro(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo='conclave', participantes=['iris', 'leonard'],
                       demanda='oportunidade de 300 unidades'), **kw}

    def test_registro_minimo_valido(self):
        chave, dados, digest = c.validar_registro(self.body())
        self.assertEqual(dados['tipo'], 'conclave')
        self.assertTrue(digest)

    def test_tipo_invalido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            c.validar_registro(self.body(tipo='conversa_informal'))

    def test_participante_desconhecido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            c.validar_registro(self.body(participantes=['fulano']))

    def test_veto_forca_precisa_diretor(self):
        _, dados, _ = c.validar_registro(self.body(vetos=[{'agente': 'dicio', 'motivo': 'risco LGPD'}],
                                                     precisa_diretor=False))
        self.assertTrue(dados['precisa_diretor'])

    def test_sem_veto_respeita_precisa_diretor_informado(self):
        _, dados, _ = c.validar_registro(self.body(precisa_diretor=False))
        self.assertFalse(dados['precisa_diretor'])


class RegistrarRegistro(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), tipo='conclave', participantes=['iris'], demanda='x'), **kw}

    def test_criacao_grava_uma_unica_vez(self):
        body = self.body()
        digest = c.validar_registro(dict(body))[2]
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'nova'}, {'id': 'nova', 'payload_hash': digest}]
        resposta, status = c.registrar_registro(lambda: conn, body)
        self.assertEqual(status, 201)
        self.assertTrue(resposta['criado'])

    def test_chave_repetida_com_conteudo_diferente_e_conflito(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente', 'payload_hash': 'outro'}]
        resposta, status = c.registrar_registro(lambda: conn, body)
        self.assertEqual(status, 409)


class NovaVersaoRegistro(unittest.TestCase):
    def test_correcao_cria_linha_nova_nunca_atualiza_a_anterior(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        id_anterior = str(uuid4())
        anterior = {'id': id_anterior, 'versao': 1, 'chave': 'k1', 'tipo': 'conclave', 'demanda': 'x',
                    'participantes': ['iris'], 'contexto': None, 'dados_apresentados': None,
                    'posicoes': None, 'conflitos': None, 'conclusao': 'v1', 'recomendacoes': [],
                    'vetos': None, 'pendencias': None, 'precisa_diretor': False}
        cur.fetchone.side_effect = [anterior, {'id': 'nova-versao'}]
        resultado = c.nova_versao_registro(lambda: conn, id_anterior, {'conclusao': 'v2 corrigida'}, 'diretor')
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['versao'], 2)
        # nenhuma chamada de UPDATE foi feita -- só SELECT e INSERT
        for chamada in cur.execute.call_args_list:
            self.assertNotIn('UPDATE', chamada.args[0].upper())

    def test_registro_inexistente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        resultado = c.nova_versao_registro(lambda: conn, str(uuid4()), {}, 'diretor')
        self.assertFalse(resultado['success'])


class RecomendacaoParaAtividade(unittest.TestCase):
    def test_shape_compativel_com_mi_decisao(self):
        recomendacao = {'responsavel': 'leonard', 'descricao': 'terceirizar excedente', 'prioridade': 'alta',
                         'confianca': 0.7}
        atividade = c.recomendacao_para_atividade(recomendacao)
        self.assertEqual(atividade['origem'], 'conselho')
        self.assertEqual(atividade['tipo_decisao'], 'recomendacao_conselho')
        self.assertTrue(atividade['exige_aprovacao'])
        self.assertEqual(atividade['estado'], 'aguardando')

    def test_precisa_diretor_forca_estado(self):
        atividade = c.recomendacao_para_atividade({'responsavel': 'dicio', 'descricao': 'veto'}, precisa_diretor=True)
        self.assertEqual(atividade['estado'], 'precisa_diretor')

    def test_pode_ser_persistida_via_mi_decisao_registrar_item_fila_sem_duplicar_logica(self):
        import mi_decisao
        atividade = c.recomendacao_para_atividade({'responsavel': 'leonard', 'descricao': 'x'})
        atividade['chave'] = str(uuid4())
        corpo = mi_decisao._para_fila(atividade)
        self.assertEqual(set(corpo) - {'chave'}, set(mi_decisao.CAMPOS))


class StatusAgentes(unittest.TestCase):
    def test_agente_sem_fato_recente_fica_sem_demanda(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        status = c.status_agentes(cur)
        self.assertEqual(len(status), 8)
        self.assertTrue(all(a['status'] == 'sem_demanda' for a in status))

    def test_agente_com_fato_recente_fica_trabalhando(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'agente': 'leonard', 'tipo_evento': 'relatorio_agente', 'criado_em': 'agora'}]
        status = c.status_agentes(cur)
        leonard = next(a for a in status if a['codigo'] == 'leonard')
        self.assertEqual(leonard['status'], 'trabalhando')
        outros = [a for a in status if a['codigo'] != 'leonard']
        self.assertTrue(all(a['status'] == 'sem_demanda' for a in outros))

    def test_agente_desconhecido_no_sinal_e_ignorado(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'agente': 'fulano', 'tipo_evento': 'x', 'criado_em': 'agora'}]
        status = c.status_agentes(cur)
        self.assertTrue(all(a['status'] == 'sem_demanda' for a in status))


class AtividadesPendentesFila(unittest.TestCase):
    def test_le_mi_fila_operacional_com_origem_conselho(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'origem': 'conselho', 'origem_id': 'leonard', 'tipo_decisao': 'recomendacao_conselho',
                                       'fatos': [], 'inferencia': 'x', 'prioridade': 'alta', 'confianca': 0.8,
                                       'proxima_acao': 'decidir_recomendacao_conselho', 'exige_aprovacao': True,
                                       'executar_em': None, 'estado': 'aguardando', 'chave': 'k'}]
        atividades = c.atividades_pendentes_fila(cur)
        self.assertEqual(len(atividades), 1)
        sql = cur.execute.call_args.args[0]
        self.assertIn("origem='conselho'", sql)
        self.assertIn("NOT IN ('concluida','bloqueada')", sql)


class LeituraConselho(unittest.TestCase):
    def test_agrega_agentes_mensagens_reunioes_relatorios(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [
            [],  # status_agentes
            [{'de_agente': 'leonard', 'para_agente': 'rua', 'texto': 'x'}],  # mensagens
            [{'id': 'r1', 'tipo': 'conclave', 'conflitos': ['x'], 'vetos': None, 'precisa_diretor': True}],  # reunioes
            [],  # relatorios
        ]
        resultado = c.leitura_conselho(lambda: conn)
        self.assertEqual(resultado['trabalhando'], 0)
        self.assertEqual(resultado['sem_demanda'], 8)
        self.assertEqual(len(resultado['mensagens_recentes']), 1)
        self.assertEqual(len(resultado['conflitos']), 1)
        self.assertEqual(len(resultado['aguardando_diretor']), 1)

    def test_e_somente_leitura_e_fecha_conexao(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        c.leitura_conselho(lambda: conn)
        conn.set_session.assert_called_once_with(readonly=True, isolation_level='REPEATABLE READ')
        conn.close.assert_called_once()
        for chamada in cur.execute.call_args_list:
            sql = chamada.args[0].upper()
            self.assertNotIn('INSERT ', sql)
            self.assertNotIn('UPDATE ', sql)
            self.assertNotIn('DELETE ', sql)


class RotaConselho(unittest.TestCase):
    def _app(self, factory, autorizado):
        app = Flask(__name__)
        c.registrar_rotas_conselho(app, factory, autorizado)
        return app.test_client()

    def test_exige_autenticacao(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        client = self._app(factory, lambda: False)
        resposta = client.get('/api/admin/mi/conselho')
        self.assertEqual(resposta.status_code, 401)
        factory.assert_not_called()

    def test_retorna_quando_autorizado(self):
        with patch.object(c, 'leitura_conselho', return_value={'agentes': []}):
            client = self._app(lambda: MagicMock(), lambda: True)
            resposta = client.get('/api/admin/mi/conselho')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()['success'])

    def test_falha_interna_nao_vaza_detalhe(self):
        factory = MagicMock(side_effect=RuntimeError('conexão indisponível'))
        client = self._app(factory, lambda: True)
        resposta = client.get('/api/admin/mi/conselho')
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn('conexão indisponível', resposta.get_json()['error'])


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte_nem_chama_anthropic(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(c))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'anthropic', 'openai', 'whatsapp_meta',
                          'whatsapp_omnichannel', 'gmail_legado'):
            self.assertNotIn(proibido, modulos)

    def test_nenhuma_funcao_roda_em_loop_ou_agenda_sozinha(self):
        import inspect
        codigo = inspect.getsource(c)
        for proibido in ('while True', 'schedule.every', 'BackgroundScheduler', 'threading.Timer'):
            self.assertNotIn(proibido, codigo)


if __name__ == '__main__':
    unittest.main()
