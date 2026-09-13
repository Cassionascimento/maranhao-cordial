"""Detector de relevância do Conselho -- mi_conselho_gatilho.py. Mesma
disciplina do resto do MI: leitura somente-leitura, idempotência via
tabela já existente (mi_sinais_auditoria), nenhuma conclusão de qualidade
inventada pelo detector (isso é dos especialistas), reaproveita o
classificador já validado (mi_conselho_orquestrador), nunca duplica."""
import unittest
from unittest.mock import MagicMock, patch
import mi_conselho_gatilho as g


def sinal(tipo_evento, origem='producao', sku='GUA-001', lote_id=None, origem_id=None,
          payload=None, criado_em='2026-09-13T10:00:00Z', resultado=None):
    return {'id': 's1', 'origem': origem, 'tipo_evento': tipo_evento, 'sku': sku,
            'lote_id': lote_id, 'origem_id': origem_id, 'payload': payload or {},
            'criado_em': criado_em, 'resultado': resultado}


def sinal_comercial(tipo_evento, origem='crm', origem_id='lead-123', payload=None, resultado=None):
    return sinal(tipo_evento, origem=origem, sku=None, origem_id=origem_id, payload=payload, resultado=resultado)


class AvaliarRelevancia(unittest.TestCase):
    def test_origem_sem_regra_definida_nao_e_relevante(self):
        r = g.avaliar_relevancia(sinal('pagina_visitada', origem='site'))
        self.assertFalse(r['relevante'])
        self.assertIn('site', r['motivo'])

    def test_lead_criado_e_ruido_operacional_mesmo_origem_crm_reconhecida(self):
        # 'crm' passou a ser reconhecida nesta etapa, mas lead_criado
        # continua de fora de propósito -- volume rotineiro do funil.
        r = g.avaliar_relevancia(sinal('lead_criado', origem='crm'))
        self.assertFalse(r['relevante'])

    def test_tipo_evento_de_producao_desconhecido_nao_e_relevante(self):
        r = g.avaliar_relevancia(sinal('temperatura_ambiente', payload={'valor': 25}))
        self.assertFalse(r['relevante'])

    def test_nao_conformidade_e_sempre_relevante(self):
        r = g.avaliar_relevancia(sinal('nao_conformidade', payload={'descricao': 'cor fora do padrão'}))
        self.assertTrue(r['relevante'])

    def test_problema_embalagem_e_sempre_relevante(self):
        r = g.avaliar_relevancia(sinal('problema_embalagem', payload={'descricao': 'tampa vazando'}))
        self.assertTrue(r['relevante'])

    def test_lote_produzido_e_sempre_relevante(self):
        r = g.avaliar_relevancia(sinal('lote_produzido', payload={'valor': 500}))
        self.assertTrue(r['relevante'])

    def test_resultado_bancada_e_sempre_relevante(self):
        r = g.avaliar_relevancia(sinal('resultado_bancada', payload={'nota': 'aprovado no painel sensorial'}))
        self.assertTrue(r['relevante'])

    def test_medicao_sem_valor_anterior_e_relevante_primeira_leitura(self):
        r = g.avaliar_relevancia(sinal('ph_medido', payload={'valor': 3.92}), valor_anterior=None)
        self.assertTrue(r['relevante'])
        self.assertIn('primeira leitura', r['motivo'])

    def test_ph_com_variacao_abaixo_do_limiar_nao_e_relevante(self):
        r = g.avaliar_relevancia(sinal('ph_medido', payload={'valor': 3.65}), valor_anterior=3.61)
        self.assertFalse(r['relevante'])

    def test_ph_com_variacao_igual_ou_acima_do_limiar_e_relevante(self):
        # Exemplo literal do pedido: 3.92 vs 3.61 (diferença 0.31 >= limiar 0.2).
        r = g.avaliar_relevancia(sinal('ph_medido', payload={'valor': 3.92}), valor_anterior=3.61)
        self.assertTrue(r['relevante'])

    def test_medicao_relativa_abaixo_do_limiar_nao_e_relevante(self):
        r = g.avaliar_relevancia(sinal('custo_ingrediente', payload={'valor': 10.1}), valor_anterior=10.0)
        self.assertFalse(r['relevante'])

    def test_medicao_relativa_acima_do_limiar_e_relevante(self):
        r = g.avaliar_relevancia(sinal('custo_ingrediente', payload={'valor': 12.0}), valor_anterior=10.0)
        self.assertTrue(r['relevante'])

    def test_valor_atual_ausente_e_tratado_como_relevante_por_seguranca(self):
        r = g.avaliar_relevancia(sinal('ph_medido', payload={}), valor_anterior=3.5)
        self.assertTrue(r['relevante'])

    def test_valor_nao_numerico_e_tratado_como_relevante_por_seguranca(self):
        r = g.avaliar_relevancia(sinal('ph_medido', payload={'valor': 'nao informado'}), valor_anterior=3.5)
        self.assertTrue(r['relevante'])


class MontarDemandaFactual(unittest.TestCase):
    def test_segue_o_formato_do_exemplo_do_pedido(self):
        texto = g.montar_demanda_factual(
            sinal('ph_medido', payload={'valor': 3.92, 'codigo_lote': 'L1'}), valor_anterior=3.61
        )
        self.assertIn('pH medido: 3.92', texto)
        self.assertIn('Valor anterior: 3.61', texto)
        self.assertIn('Mudança nos dados detectada', texto)

    def test_primeira_leitura_nao_menciona_valor_anterior(self):
        texto = g.montar_demanda_factual(sinal('brix_medido', payload={'valor': 12.0}), valor_anterior=None)
        self.assertIn('Primeira leitura', texto)
        self.assertNotIn('Valor anterior', texto)

    def test_evento_sempre_relevante_sem_valor_numerico_descreve_o_payload(self):
        texto = g.montar_demanda_factual(sinal('nao_conformidade', payload={'descricao': 'cor fora do padrão'}))
        self.assertIn('descricao', texto)

    def test_codigo_lote_nao_vaza_para_o_texto_de_detalhes(self):
        # codigo_lote já aparece no identificador da série; repeti-lo no
        # dump de payload arrastaria "lote" para a classificação (Rua)
        # mesmo quando o evento não é dela.
        texto = g.montar_demanda_factual(
            sinal('problema_embalagem', payload={'descricao': 'tampa vazando', 'codigo_lote': 'L1'})
        )
        self.assertNotIn('codigo_lote', texto)

    def test_nunca_conclui_qualidade_ou_adequacao_do_produto(self):
        # A conclusão pertence aos especialistas -- o detector só relata fato.
        proibidas = ('inadequado', 'inadequada', 'aprovado', 'reprovado', 'ruim', 'ótimo', 'péssimo')
        casos = [
            (sinal('ph_medido', payload={'valor': 3.92}), 3.61),
            (sinal('nao_conformidade', payload={'descricao': 'cor fora do padrão'}), None),
            (sinal('lote_produzido', payload={'valor': 500}), None),
        ]
        for s, anterior in casos:
            texto = g.montar_demanda_factual(s, anterior).lower()
            for palavra in proibidas:
                self.assertNotIn(palavra, texto)


class ClassificacaoViaClassificadorExistente(unittest.TestCase):
    """Não cria segundo classificador -- só confirma que o texto factual
    gerado aciona os especialistas certos no classificador já validado."""

    def _selecionados(self, tipo_evento, payload, valor_anterior=None):
        s = sinal(tipo_evento, payload=payload)
        demanda = g.montar_demanda_factual(s, valor_anterior)
        return g.classificar_especialistas(demanda)['selecionados']

    def test_ph_medido_classifica_para_marie(self):
        self.assertIn('marie', self._selecionados('ph_medido', {'valor': 3.92}, 3.61))

    def test_brix_medido_classifica_para_marie(self):
        self.assertIn('marie', self._selecionados('brix_medido', {'valor': 12.0}, 10.0))

    def test_estabilidade_classifica_para_marie(self):
        self.assertIn('marie', self._selecionados('estabilidade', {'valor': 30}, 20))

    def test_resultado_bancada_classifica_para_marie(self):
        self.assertEqual(self._selecionados('resultado_bancada', {'nota': 'painel sensorial ok'}), ['marie'])

    def test_problema_embalagem_classifica_para_marie(self):
        self.assertEqual(self._selecionados('problema_embalagem', {'descricao': 'tampa vazando'}), ['marie'])

    def test_custo_ingrediente_classifica_para_standard_nao_marie(self):
        selecionados = self._selecionados('custo_ingrediente', {'valor': 12.0}, 10.0)
        self.assertIn('standard', selecionados)
        self.assertNotIn('marie', selecionados)

    def test_rendimento_classifica_para_standard(self):
        self.assertIn('standard', self._selecionados('rendimento', {'valor': 80}, 90))

    def test_perda_classifica_para_standard(self):
        self.assertIn('standard', self._selecionados('perda', {'valor': 5}, 2))

    def test_capacidade_classifica_para_rua(self):
        self.assertIn('rua', self._selecionados('capacidade', {'valor': 1000}, 800))

    def test_estoque_classifica_para_rua(self):
        self.assertIn('rua', self._selecionados('estoque', {'valor': 50}, 200))

    def test_lote_produzido_classifica_para_rua_sozinho(self):
        self.assertEqual(self._selecionados('lote_produzido', {'valor': 500}), ['rua'])

    def test_nao_conformidade_classifica_para_dicio_sozinho(self):
        self.assertEqual(self._selecionados('nao_conformidade', {'descricao': 'cor fora do padrão'}), ['dicio'])

    def test_iris_entra_quando_ha_mudanca_de_verdade_mas_nao_em_fato_discreto(self):
        # "Iris quando análise factual/mudança for necessária": ela entra
        # nas medições com mudança real detectada...
        self.assertIn('iris', self._selecionados('ph_medido', {'valor': 3.92}, 3.61))
        # ...mas não em fatos discretos de primeira ocorrência (não é uma
        # comparação de série, é um fato novo por natureza).
        self.assertNotIn('iris', self._selecionados('lote_produzido', {'valor': 500}))
        self.assertNotIn('iris', self._selecionados('nao_conformidade', {'descricao': 'x'}))

    def test_nenhum_caso_de_producao_vira_conclave_completo(self):
        for tipo, payload, anterior in [
            ('ph_medido', {'valor': 3.92}, 3.61), ('custo_ingrediente', {'valor': 12.0}, 10.0),
            ('nao_conformidade', {'descricao': 'x'}, None),
        ]:
            s = sinal(tipo, payload=payload)
            demanda = g.montar_demanda_factual(s, anterior)
            self.assertFalse(g.classificar_especialistas(demanda)['conclave_completo'])


class AvaliarRelevanciaComercial(unittest.TestCase):
    def test_lead_qualificado_e_relevante(self):
        r = g.avaliar_relevancia(sinal_comercial('lead_qualificado'))
        self.assertTrue(r['relevante'])

    def test_lead_criado_e_ruido_operacional(self):
        r = g.avaliar_relevancia(sinal_comercial('lead_criado'))
        self.assertFalse(r['relevante'])

    def test_prospecto_encontrado_e_ruido_operacional(self):
        r = g.avaliar_relevancia(sinal_comercial('prospecto_encontrado', origem='prospeccao_fase57'))
        self.assertFalse(r['relevante'])

    def test_acao_proposta_e_ruido_ja_coberto_por_aprovacao_humana(self):
        r = g.avaliar_relevancia(sinal_comercial('acao_proposta', origem='acoes_comerciais'))
        self.assertFalse(r['relevante'])

    def test_mudanca_de_estagio_para_negociacao_e_material(self):
        r = g.avaliar_relevancia(sinal_comercial(
            'lead_estagio_mudou', payload={'estagio_anterior': 'qualificacao', 'estagio_novo': 'negociacao'}))
        self.assertTrue(r['relevante'])

    def test_mudanca_de_estagio_para_cliente_e_material(self):
        r = g.avaliar_relevancia(sinal_comercial(
            'lead_estagio_mudou', payload={'estagio_anterior': 'negociacao', 'estagio_novo': 'cliente'}))
        self.assertTrue(r['relevante'])

    def test_mudanca_de_estagio_para_perdido_e_material(self):
        r = g.avaliar_relevancia(sinal_comercial(
            'lead_estagio_mudou', payload={'estagio_anterior': 'negociacao', 'estagio_novo': 'perdido'}))
        self.assertTrue(r['relevante'])

    def test_mudanca_de_estagio_rotineira_nao_e_material(self):
        r = g.avaliar_relevancia(sinal_comercial(
            'lead_estagio_mudou', payload={'estagio_anterior': 'novo', 'estagio_novo': 'contato'}))
        self.assertFalse(r['relevante'])

    def test_prospecto_priorizado_e_a_oportunidade_parada_relevante_ja_existente(self):
        # "oportunidade parada" em si não é um tipo_evento de mi_sinais --
        # é um conceito de mi_decisao.py (fila operacional), fora do
        # alcance deste detector, que só lê mi_sinais. O sinal real mais
        # próximo já emitido em mi_sinais é prospecto_priorizado/
        # prospecto_descartado (fase57), tratado aqui como o equivalente.
        r = g.avaliar_relevancia(sinal_comercial('prospecto_priorizado', origem='prospeccao_fase57'))
        self.assertTrue(r['relevante'])

    def test_prospecto_descartado_e_relevante_perda_de_oportunidade(self):
        r = g.avaliar_relevancia(sinal_comercial('prospecto_descartado', origem='prospeccao_fase57'))
        self.assertTrue(r['relevante'])

    def test_acao_executada_com_resultado_incerto_e_relevante(self):
        r = g.avaliar_relevancia(sinal_comercial('acao_executada', origem='acoes_comerciais', resultado='incerta'))
        self.assertTrue(r['relevante'])

    def test_acao_executada_com_resultado_enviada_e_rotina(self):
        r = g.avaliar_relevancia(sinal_comercial('acao_executada', origem='acoes_comerciais', resultado='enviada'))
        self.assertFalse(r['relevante'])

    def test_acao_bloqueada_e_relevante(self):
        r = g.avaliar_relevancia(sinal_comercial('acao_bloqueada', origem='acoes_comerciais'))
        self.assertTrue(r['relevante'])


class MontarDemandaFactualComercial(unittest.TestCase):
    def test_segue_o_formato_do_exemplo_do_pedido(self):
        texto = g.montar_demanda_factual(sinal_comercial(
            'lead_estagio_mudou', payload={'estagio_anterior': 'contato', 'estagio_novo': 'negociacao'}))
        self.assertIn('Comercial — lead lead-123:', texto)
        self.assertIn('estágio alterado de contato para negociacao', texto)

    def test_nunca_conclui_enviar_proposta_ou_pronto_para_comprar(self):
        proibidas = ('devemos enviar proposta', 'pronto para comprar', 'está pronto para fechar')
        casos = [
            sinal_comercial('lead_qualificado'),
            sinal_comercial('lead_estagio_mudou', payload={'estagio_anterior': 'x', 'estagio_novo': 'negociacao'}),
            sinal_comercial('prospecto_descartado', origem='prospeccao_fase57'),
        ]
        for s in casos:
            texto = g.montar_demanda_factual(s).lower()
            for frase in proibidas:
                self.assertNotIn(frase, texto)


class ClassificacaoComercialViaClassificadorExistente(unittest.TestCase):
    def _selecionados(self, s):
        demanda = g.montar_demanda_factual(s)
        return g.classificar_especialistas(demanda)['selecionados']

    def test_lead_qualificado_convoca_leonard(self):
        self.assertIn('leonard', self._selecionados(sinal_comercial('lead_qualificado')))

    def test_estagio_negociacao_convoca_leonard(self):
        s = sinal_comercial('lead_estagio_mudou', payload={'estagio_anterior': 'x', 'estagio_novo': 'negociacao'})
        self.assertIn('leonard', self._selecionados(s))

    def test_estagio_perdido_convoca_standard_pelo_impacto_economico(self):
        s = sinal_comercial('lead_estagio_mudou', payload={'estagio_anterior': 'negociacao', 'estagio_novo': 'perdido'})
        self.assertIn('standard', self._selecionados(s))

    def test_iris_e_convocada_quando_ha_mudanca_comercial_relevante(self):
        self.assertIn('iris', self._selecionados(sinal_comercial('lead_qualificado')))

    def test_pirret_nunca_e_convocado_sem_questao_de_marketing(self):
        for s in (sinal_comercial('lead_qualificado'),
                  sinal_comercial('lead_estagio_mudou', payload={'estagio_anterior': 'x', 'estagio_novo': 'cliente'}),
                  sinal_comercial('prospecto_descartado', origem='prospeccao_fase57')):
            self.assertNotIn('pirret', self._selecionados(s))

    def test_nenhum_caso_comercial_vira_conclave_completo(self):
        for s in (sinal_comercial('lead_qualificado'),
                  sinal_comercial('prospecto_descartado', origem='prospeccao_fase57'),
                  sinal_comercial('acao_bloqueada', origem='acoes_comerciais')):
            demanda = g.montar_demanda_factual(s)
            self.assertFalse(g.classificar_especialistas(demanda)['conclave_completo'])


class SinaisPendentes(unittest.TestCase):
    def test_consulta_exclui_sinais_ja_avaliados_pelo_gatilho(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        g.sinais_pendentes(cur, limite=10)
        sql = cur.execute.call_args.args[0].upper()
        self.assertIn('NOT EXISTS', sql)
        self.assertIn('MI_SINAIS_AUDITORIA', sql)
        parametros = cur.execute.call_args.args[1]
        self.assertIn(g.EVENTO_RELEVANTE, parametros[1])
        self.assertIn(g.EVENTO_IRRELEVANTE, parametros[1])

    def test_filtra_pelas_origens_reconhecidas_apenas(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        g.sinais_pendentes(cur)
        sql = cur.execute.call_args.args[0]
        self.assertIn('s.origem = ANY(%s)', sql)
        parametros = cur.execute.call_args.args[1]
        self.assertEqual(set(parametros[0]), {'producao', 'crm', 'acoes_comerciais', 'prospeccao_fase57'})


class MarcarAvaliado(unittest.TestCase):
    def test_marca_evento_relevante(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        g.marcar_avaliado(lambda: conn, 's1', relevante=True)
        insercao = cur.execute.call_args
        self.assertIn('INSERT INTO mi_sinais_auditoria', insercao.args[0])
        self.assertEqual(insercao.args[1], ('s1', g.EVENTO_RELEVANTE, g.ATOR))

    def test_marca_evento_irrelevante(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        g.marcar_avaliado(lambda: conn, 's1', relevante=False)
        insercao = cur.execute.call_args
        self.assertEqual(insercao.args[1], ('s1', g.EVENTO_IRRELEVANTE, g.ATOR))

    def test_fecha_conexao(self):
        conn = MagicMock()
        g.marcar_avaliado(lambda: conn, 's1', relevante=True)
        conn.close.assert_called_once()


class ProcessarSinaisPendentes(unittest.TestCase):
    def test_sinal_irrelevante_nao_monta_demanda_nem_chama_classificador(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        pendente = sinal('ph_medido', payload={'valor': 3.65})
        cur.fetchall.return_value = [pendente]
        cur.fetchone.return_value = {'payload': {'valor': 3.61}}  # valor_anterior_mesma_serie
        with patch('mi_conselho_gatilho.classificar_especialistas') as classificar:
            resultados = g.processar_sinais_pendentes(lambda: conn)
        classificar.assert_not_called()
        self.assertEqual(len(resultados), 1)
        self.assertFalse(resultados[0]['relevante'])
        self.assertNotIn('demanda', resultados[0])

    def test_sinal_relevante_monta_demanda_e_classifica_com_o_classificador_existente(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        pendente = sinal('nao_conformidade', payload={'descricao': 'cor fora do padrão'})
        cur.fetchall.return_value = [pendente]
        resultados = g.processar_sinais_pendentes(lambda: conn)
        self.assertEqual(len(resultados), 1)
        self.assertTrue(resultados[0]['relevante'])
        self.assertIn('demanda', resultados[0])
        self.assertEqual(resultados[0]['classificacao']['selecionados'], ['dicio'])

    def test_marca_tanto_relevante_quanto_irrelevante_para_nunca_reprocessar(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [sinal('lote_produzido', payload={'valor': 500})]
        g.processar_sinais_pendentes(lambda: conn)
        insercoes = [c.args[1] for c in cur.execute.call_args_list if 'INSERT INTO mi_sinais_auditoria' in c.args[0]]
        self.assertEqual(len(insercoes), 1)
        self.assertEqual(insercoes[0], ('s1', g.EVENTO_RELEVANTE, g.ATOR))

    def test_usa_sessao_readonly_para_a_leitura(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        g.processar_sinais_pendentes(lambda: conn)
        conn.set_session.assert_any_call(readonly=True, isolation_level='REPEATABLE READ')

    def test_sem_pendentes_no_processa_nada_nem_chama_classificador(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        with patch('mi_conselho_gatilho.classificar_especialistas') as classificar:
            resultados = g.processar_sinais_pendentes(lambda: conn)
        self.assertEqual(resultados, [])
        classificar.assert_not_called()


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_transporte_nem_chama_anthropic(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(g))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'anthropic', 'openai',
                          'whatsapp_meta', 'whatsapp_omnichannel', 'gmail_legado'):
            self.assertNotIn(proibido, modulos)

    def test_nao_chama_nenhuma_funcao_de_escrita_irreversivel(self):
        import inspect
        codigo = inspect.getsource(g)
        for proibido in ('ativar_unidade', 'revogar_unidade', 'criar_unidade', 'criar_lote',
                          'registrar_evento_mi', 'emitir(', 'registrar_registro', 'registrar_mensagem'):
            self.assertNotIn(proibido, codigo)

    def test_nenhuma_funcao_roda_em_loop_ou_agenda_sozinha(self):
        import inspect
        codigo = inspect.getsource(g)
        for proibido in ('while True', 'schedule.every', 'BackgroundScheduler', 'threading.Timer', 'APScheduler'):
            self.assertNotIn(proibido, codigo)

    def test_reaproveita_o_classificador_existente_sem_duplicar(self):
        import inspect
        codigo = inspect.getsource(g)
        self.assertIn('from mi_conselho_orquestrador import classificar_especialistas', codigo)
        self.assertNotIn('def classificar_especialistas', codigo)

    def test_unica_tabela_escrita_e_mi_sinais_auditoria_ja_existente(self):
        import inspect
        codigo = inspect.getsource(g)
        self.assertIn('INSERT INTO mi_sinais_auditoria', codigo)
        self.assertNotIn('CREATE TABLE', codigo)


if __name__ == '__main__':
    unittest.main()
