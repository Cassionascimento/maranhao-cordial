"""Execução real dos especialistas -- mi_conselho_executor.py. Reaproveita
o cliente OpenAI já em uso no projeto (injetado por teste, nunca chamado
de verdade aqui). Modo observador: nenhuma ação externa é chamável a
partir deste módulo -- confirmado por AST, não só por comportamento."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import mi_conselho_executor as e


def resposta_openai(**campos):
    base = {
        'dados_utilizados': 'sinal de produção', 'conclusao': 'sem alteração relevante',
        'confianca': 'media', 'riscos': 'nenhum risco imediato', 'divergencias': '',
        'acao_sugerida': 'acompanhar', 'necessidade_diretor': False,
        'motivo_diretor': '', 'veto': False, 'veto_motivo': None,
    }
    base.update(campos)
    return MagicMock(output_text=json.dumps(base), status='completed', incomplete_details=None)


def cliente_mock(**campos):
    cliente = MagicMock()
    cliente.responses.create.return_value = resposta_openai(**campos)
    return cliente


class ExecutarEspecialista(unittest.TestCase):
    def test_agente_desconhecido_levanta_erro_sem_chamar_llm(self):
        cliente = cliente_mock()
        with self.assertRaises(ValueError):
            e.executar_especialista('fulano', 'demanda', cliente=cliente)
        cliente.responses.create.assert_not_called()

    def test_chamada_nunca_usa_tools_nem_historico_compartilhado(self):
        cliente = cliente_mock()
        e.executar_especialista('marie', 'Fábrica — L1: pH medido: 3.92.', cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertNotIn('tools', kwargs)
        self.assertNotIn('previous_response_id', kwargs)
        self.assertNotIn('conversation', kwargs)

    def test_chamada_define_limite_de_tokens_e_nao_persiste_do_lado_openai(self):
        cliente = cliente_mock()
        e.executar_especialista('rua', 'Fábrica — L1: Estoque: 50.', cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertEqual(kwargs['max_output_tokens'], e.MAX_OUTPUT_TOKENS)
        self.assertFalse(kwargs['store'])

    def test_prompt_enviado_contem_a_persona_correta(self):
        cliente = cliente_mock()
        e.executar_especialista('dicio', 'Fábrica — L1: Não conformidade registrado.', cliente=cliente)
        prompt_enviado = cliente.responses.create.call_args.kwargs['input']
        self.assertIn('Dicio', prompt_enviado)
        self.assertIn('veto', prompt_enviado.lower())

    def test_prompt_nunca_contem_credencial_mesmo_com_snapshot(self):
        cliente = cliente_mock()
        with self.assertRaises(ValueError):
            e.executar_especialista('iris', 'demanda', snapshot={'database_url': 'postgres://x'}, cliente=cliente)
        cliente.responses.create.assert_not_called()

    def test_saida_estruturada_via_json_schema_nunca_texto_livre(self):
        cliente = cliente_mock()
        e.executar_especialista('standard', 'Fábrica — L1: Custo de matéria-prima: 10.', cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertEqual(kwargs['text']['format']['type'], 'json_schema')
        self.assertTrue(kwargs['text']['format']['strict'])

    def test_apenas_dicio_pode_vetar_mesmo_que_o_modelo_tente(self):
        cliente = cliente_mock(veto=True, veto_motivo='risco jurídico')
        parecer = e.executar_especialista('leonard', 'demanda', cliente=cliente)
        self.assertFalse(parecer['veto'])
        self.assertIsNone(parecer['veto_motivo'])

    def test_veto_do_dicio_e_respeitado_e_forca_necessidade_de_diretor(self):
        cliente = cliente_mock(veto=True, veto_motivo='claim sem validação técnica', necessidade_diretor=False)
        parecer = e.executar_especialista('dicio', 'demanda', cliente=cliente)
        self.assertTrue(parecer['veto'])
        self.assertTrue(parecer['necessidade_diretor'])
        self.assertEqual(parecer['veto_motivo'], 'claim sem validação técnica')

    def test_confianca_fora_do_vocabulario_cai_para_baixa_por_seguranca(self):
        cliente = cliente_mock(confianca='altíssima')
        parecer = e.executar_especialista('marie', 'demanda', cliente=cliente)
        self.assertEqual(parecer['confianca'], 'baixa')

    def test_nunca_registra_raciocinio_bruto_so_le_output_text(self):
        cliente = cliente_mock()
        e.executar_especialista('iris', 'demanda', cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertNotIn('include', kwargs)
        self.assertNotIn('reasoning_summary', kwargs)

    def test_resposta_incompleta_por_orcamento_de_raciocinio_levanta_erro_sem_registrar(self):
        # Caso real observado em homologação: gpt-5-mini consumiu todo o
        # orçamento de max_output_tokens em raciocínio, terminou com
        # status='incomplete' e output_text vazio -- json.loads('') sempre
        # levantaria JSONDecodeError sem contexto nenhum. Deve virar
        # RespostaLLMInvalida, nunca um parecer parcial.
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(
            output_text='',
            status='incomplete',
            incomplete_details=MagicMock(reason='max_output_tokens'),
        )
        with self.assertRaises(e.RespostaLLMInvalida) as ctx:
            e.executar_especialista('iris', 'demanda', cliente=cliente)
        self.assertIn('resposta_llm_incompleta', str(ctx.exception))
        self.assertIn('max_output_tokens', str(ctx.exception))

    def test_output_text_vazio_com_status_completo_levanta_erro(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(
            output_text='   ', status='completed', incomplete_details=None,
        )
        with self.assertRaises(e.RespostaLLMInvalida) as ctx:
            e.executar_especialista('leonard', 'demanda', cliente=cliente)
        self.assertIn('resposta_llm_sem_conteudo', str(ctx.exception))

    def test_output_text_json_malformado_levanta_erro(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(
            output_text='{isto nao e json', status='completed', incomplete_details=None,
        )
        with self.assertRaises(e.RespostaLLMInvalida) as ctx:
            e.executar_especialista('marie', 'demanda', cliente=cliente)
        self.assertIn('resposta_llm_json_invalido', str(ctx.exception))

    def test_output_text_json_sem_campos_obrigatorios_levanta_erro(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(
            output_text=json.dumps({'conclusao': 'ok'}), status='completed', incomplete_details=None,
        )
        with self.assertRaises(e.RespostaLLMInvalida) as ctx:
            e.executar_especialista('standard', 'demanda', cliente=cliente)
        self.assertIn('resposta_llm_campos_ausentes', str(ctx.exception))

    def test_output_text_json_que_nao_e_objeto_levanta_erro(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(
            output_text=json.dumps(['nao', 'e', 'dict']), status='completed', incomplete_details=None,
        )
        with self.assertRaises(e.RespostaLLMInvalida) as ctx:
            e.executar_especialista('dicio', 'demanda', cliente=cliente)
        self.assertIn('resposta_llm_formato_invalido', str(ctx.exception))


class Consolidar(unittest.TestCase):
    def parecer(self, agente, **kw):
        base = dict(agente=agente, conclusao='ok', confianca='media', divergencias='',
                    acao_sugerida='', necessidade_diretor=False, veto=False, veto_motivo=None)
        base.update(kw)
        return base

    def test_um_so_parecer_vira_tipo_relatorio(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'ph_medido'}
        corpo = e._consolidar(avaliado, [self.parecer('marie')], [])
        self.assertEqual(corpo['tipo'], 'relatorio')

    def test_dois_ou_mais_pareceres_vira_tipo_reuniao(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'custo_ingrediente'}
        corpo = e._consolidar(avaliado, [self.parecer('standard'), self.parecer('iris')], [])
        self.assertEqual(corpo['tipo'], 'reuniao')

    def test_veto_aparece_em_vetos_e_forca_precisa_diretor(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'nao_conformidade'}
        corpo = e._consolidar(avaliado, [self.parecer('dicio', veto=True, veto_motivo='risco')], [])
        self.assertEqual(corpo['vetos'], {'dicio': 'risco'})
        self.assertTrue(corpo['precisa_diretor'])

    def test_erro_de_agente_vira_pendencia_e_forca_precisa_diretor(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'ph_medido'}
        corpo = e._consolidar(avaliado, [self.parecer('marie')], [{'agente': 'iris', 'erro': 'Timeout'}])
        self.assertEqual(corpo['pendencias']['agentes_com_falha'], ['iris'])
        self.assertTrue(corpo['precisa_diretor'])

    def test_exceder_limite_de_especialistas_forca_precisa_diretor(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'x'}
        corpo = e._consolidar(avaliado, [self.parecer('marie')], [], excedeu_limite=True)
        self.assertTrue(corpo['pendencias']['especialistas_acima_do_limite'])
        self.assertTrue(corpo['precisa_diretor'])

    def test_divergencia_trivial_nao_vira_conflito(self):
        avaliado = {'sinal_id': 's1', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'x'}
        corpo = e._consolidar(avaliado, [self.parecer('marie', divergencias='nenhuma')], [])
        self.assertIsNone(corpo['conflitos'])

    def test_chave_e_deterministica_para_o_mesmo_sinal(self):
        avaliado = {'sinal_id': 'mesmo-sinal', 'demanda': 'd', 'motivo': 'm', 'tipo_evento': 'x'}
        corpo1 = e._consolidar(avaliado, [self.parecer('marie')], [])
        corpo2 = e._consolidar(avaliado, [self.parecer('marie')], [])
        self.assertEqual(corpo1['chave'], corpo2['chave'])


class ProcessarERegistrar(unittest.TestCase):
    def _conn_com_um_pendente(self, sinal):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [sinal]
        return conn

    def test_sinal_irrelevante_nao_chama_llm_nem_registra(self):
        sinal = {'id': 's1', 'origem': 'producao', 'tipo_evento': 'ph_medido', 'sku': 'X',
                  'lote_id': None, 'origem_id': None, 'payload': {'valor': 3.65}, 'criado_em': 'agora'}
        conn = self._conn_com_um_pendente(sinal)
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {'payload': {'valor': 3.61}}
        with patch('mi_conselho_executor.executar_especialista') as executar, \
             patch('mi_conselho_executor.registrar_registro') as registrar:
            resultados = e.processar_e_registrar(lambda: conn)
        executar.assert_not_called()
        registrar.assert_not_called()
        self.assertFalse(resultados[0]['relevante'])

    def test_sinal_relevante_executa_somente_os_agentes_selecionados(self):
        sinal = {'id': 's1', 'origem': 'producao', 'tipo_evento': 'nao_conformidade', 'sku': 'X',
                  'lote_id': None, 'origem_id': None, 'payload': {'descricao': 'x'}, 'criado_em': 'agora'}
        conn = self._conn_com_um_pendente(sinal)
        with patch('mi_conselho_executor.executar_especialista') as executar, \
             patch('mi_conselho_executor.registrar_registro', return_value={'success': True}) as registrar:
            executar.return_value = {
                'agente': 'dicio', 'conclusao': 'ok', 'confianca': 'media', 'divergencias': '',
                'acao_sugerida': '', 'necessidade_diretor': False, 'veto': False, 'veto_motivo': None,
            }
            resultados = e.processar_e_registrar(lambda: conn)
        executar.assert_called_once()
        self.assertEqual(executar.call_args.args[0], 'dicio')
        registrar.assert_called_once()

    def test_falha_de_um_agente_nao_impede_registro_e_marca_precisa_diretor(self):
        sinal = {'id': 's1', 'origem': 'producao', 'tipo_evento': 'custo_ingrediente', 'sku': 'X',
                  'lote_id': None, 'origem_id': None, 'payload': {'valor': 12.0}, 'criado_em': 'agora'}
        conn = self._conn_com_um_pendente(sinal)
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {'payload': {'valor': 10.0}}
        capturado = {}

        def registrar_fake(factory, corpo):
            capturado['corpo'] = corpo
            return {'success': True}

        with patch('mi_conselho_executor.executar_especialista', side_effect=RuntimeError('timeout')), \
             patch('mi_conselho_executor.registrar_registro', side_effect=registrar_fake):
            resultados = e.processar_e_registrar(lambda: conn)
        self.assertEqual(len(resultados[0]['erros']), 2)  # standard + iris (mudança material -> iris entra)
        self.assertTrue(capturado['corpo']['precisa_diretor'])

    def test_conclave_completo_nao_executa_nenhum_agente_automaticamente(self):
        sinal = {'id': 's1', 'origem': 'producao', 'tipo_evento': 'nao_conformidade', 'sku': 'X',
                  'lote_id': None, 'origem_id': None, 'payload': {'descricao': 'x'}, 'criado_em': 'agora'}
        conn = self._conn_com_um_pendente(sinal)
        with patch('mi_conselho_gatilho.classificar_especialistas',
                   return_value={'selecionados': ['dicio'], 'conclave_completo': True, 'motivos': {}, 'excluidos': {}}), \
             patch('mi_conselho_executor.executar_especialista') as executar, \
             patch('mi_conselho_executor.registrar_registro', return_value={'success': True}) as registrar:
            resultados = e.processar_e_registrar(lambda: conn)
        executar.assert_not_called()
        registrar.assert_called_once()
        self.assertEqual(resultados[0]['motivo_execucao'], 'conclave_completo_aguardando_diretor')

    def test_mais_especialistas_que_o_limite_sao_cortados_e_marcados(self):
        sinal = {'id': 's1', 'origem': 'producao', 'tipo_evento': 'x', 'sku': 'X',
                  'lote_id': None, 'origem_id': None, 'payload': {}, 'criado_em': 'agora'}
        conn = self._conn_com_um_pendente(sinal)
        capturado = {}

        def registrar_fake(factory, corpo):
            capturado['corpo'] = corpo
            return {'success': True}

        with patch('mi_conselho_gatilho.classificar_especialistas',
                   return_value={'selecionados': ['dicio', 'marie', 'rua', 'standard', 'leonard'],
                                 'conclave_completo': False, 'motivos': {}, 'excluidos': {}}), \
             patch('mi_conselho_gatilho.avaliar_relevancia', return_value={'relevante': True, 'motivo': 'm'}), \
             patch('mi_conselho_executor.executar_especialista') as executar, \
             patch('mi_conselho_executor.registrar_registro', side_effect=registrar_fake):
            executar.return_value = {
                'agente': 'dicio', 'conclusao': 'ok', 'confianca': 'media', 'divergencias': '',
                'acao_sugerida': '', 'necessidade_diretor': False, 'veto': False, 'veto_motivo': None,
            }
            e.processar_e_registrar(lambda: conn, max_especialistas=4)
        self.assertEqual(executar.call_count, 4)
        self.assertTrue(capturado['corpo']['pendencias']['especialistas_acima_do_limite'])
        self.assertTrue(capturado['corpo']['precisa_diretor'])

    def test_sem_pendentes_nao_chama_llm_nem_registro(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        with patch('mi_conselho_executor.executar_especialista') as executar, \
             patch('mi_conselho_executor.registrar_registro') as registrar:
            resultados = e.processar_e_registrar(lambda: conn)
        self.assertEqual(resultados, [])
        executar.assert_not_called()
        registrar.assert_not_called()


class ModoObservador(unittest.TestCase):
    def test_padrao_e_observador_mesmo_sem_variavel_definida(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CONSELHO_MODO_OBSERVADOR', None)
            self.assertTrue(e.modo_observador_ativo())

    def test_valor_mal_configurado_mantem_observador_fail_safe(self):
        with patch.dict(os.environ, {'CONSELHO_MODO_OBSERVADOR': 'sim'}):
            self.assertTrue(e.modo_observador_ativo())

    def test_somente_false_exato_desliga_observador(self):
        with patch.dict(os.environ, {'CONSELHO_MODO_OBSERVADOR': 'false'}):
            self.assertFalse(e.modo_observador_ativo())
        with patch.dict(os.environ, {'CONSELHO_MODO_OBSERVADOR': 'FALSE'}):
            self.assertFalse(e.modo_observador_ativo())


class SemAcaoExterna(unittest.TestCase):
    def test_modulo_nao_importa_transporte_nem_acoes_comerciais(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(e))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'anthropic', 'acoes_comerciais',
                          'prospeccao_controle', 'email_seguranca', 'email_supervisionado',
                          'whatsapp_meta', 'whatsapp_omnichannel', 'gmail_legado', 'psycopg2'):
            self.assertNotIn(proibido, modulos)

    def test_nenhuma_chamada_a_funcao_de_acao_externa_no_codigo_fonte(self):
        # A prosa do docstring do módulo cita "acoes_comerciais.propor" só
        # para explicar o que NUNCA é chamado -- por isso ela é removida
        # antes da busca; o que importa é o restante do código-fonte.
        import ast
        import inspect
        codigo = inspect.getsource(e)
        docstring = ast.get_docstring(ast.parse(codigo))
        corpo = codigo.replace(docstring, '', 1) if docstring else codigo
        for proibido in ('acoes_comerciais', '.propor(', 'enviar_primeiro_contato', 'executar_prospeccao',
                          'gmail_sync', 'whatsapp_omnichannel', 'whatsapp_meta'):
            self.assertNotIn(proibido, corpo)

    def test_reaproveita_classificador_e_persona_sem_duplicar(self):
        import inspect
        codigo = inspect.getsource(e)
        self.assertIn('from mi_conselho_orquestrador import', codigo)
        self.assertIn('from mi_conselho_gatilho import processar_sinais_pendentes', codigo)
        self.assertNotIn('def carregar_persona', codigo)
        self.assertNotIn('def classificar_especialistas', codigo)

    def test_nenhuma_funcao_roda_em_loop_ou_agenda_sozinha(self):
        import inspect
        codigo = inspect.getsource(e)
        for proibido in ('while True', 'schedule.every', 'BackgroundScheduler', 'threading.Timer', 'APScheduler'):
            self.assertNotIn(proibido, codigo)


class JobStandalone(unittest.TestCase):
    def test_desabilitado_por_padrao_nao_executa_nem_conecta(self):
        import mi_conselho_job as job
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CONSELHO_JOB_HABILITADO', None)
            factory = MagicMock(side_effect=AssertionError('não deveria conectar'))
            with patch('mi_conselho_job.processar_e_registrar') as processar:
                resultado = job.executar(factory=factory)
        self.assertFalse(resultado['executado'])
        processar.assert_not_called()
        factory.assert_not_called()

    def test_valor_diferente_de_true_exato_tambem_nao_executa(self):
        import mi_conselho_job as job
        with patch.dict(os.environ, {'CONSELHO_JOB_HABILITADO': 'TRUE'}):
            with patch('mi_conselho_job.processar_e_registrar') as processar:
                resultado = job.executar(factory=MagicMock())
        self.assertFalse(resultado['executado'])
        processar.assert_not_called()

    def test_habilitado_explicitamente_executa(self):
        import mi_conselho_job as job
        with patch.dict(os.environ, {'CONSELHO_JOB_HABILITADO': 'true'}):
            with patch('mi_conselho_job.processar_e_registrar', return_value=[{'relevante': False}]) as processar:
                resultado = job.executar(factory=MagicMock())
        self.assertTrue(resultado['executado'])
        processar.assert_called_once()

    def test_job_nao_importa_scheduler_nem_configura_render(self):
        import inspect
        import mi_conselho_job as job
        codigo = inspect.getsource(job)
        for proibido in ('schedule.every', 'BackgroundScheduler', 'APScheduler', 'render.yaml', 'crontab'):
            self.assertNotIn(proibido, codigo)


if __name__ == '__main__':
    unittest.main()
