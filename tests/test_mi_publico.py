"""ETAPA 5.1B: mi_publico.py -- inteligência de público e conteúdo.

planejar_publico() é DRY-RUN: nenhum teste desta classe deve encontrar
INSERT/UPDATE/DELETE nas chamadas de execute() (verificado explicitamente).
Nenhum post é publicado; nenhuma mensagem é enviada.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import mi_publico as p


def sem_escrita(cur):
    for chamada in cur.execute.call_args_list:
        sql = chamada.args[0].upper()
        assert not any(v in sql for v in ('INSERT ', 'UPDATE ', 'DELETE ', 'DROP ', 'ALTER ')), sql


class NormalizarTema(unittest.TestCase):
    def test_remove_acentos_e_pontuacao(self):
        self.assertEqual(p._normalizar_tema('Degustação, B2B!'), 'degustacao b2b')

    def test_none_e_vazio_retornam_none(self):
        self.assertIsNone(p._normalizar_tema(None))
        self.assertIsNone(p._normalizar_tema('   '))

    def test_trunca_textos_muito_longos(self):
        self.assertLessEqual(len(p._normalizar_tema('a' * 500)), 120)


class ColetorCrm(unittest.TestCase):
    def test_coleta_interesse_declarado(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'interesse': 'Degustação de produtos', 'tipo_lead': 'b2b',
                                       'cidade': 'São Luís', 'estado': 'MA'}]
        mencoes = p.coletar_interesse_crm(cur, datetime(2026, 1, 1), datetime(2026, 1, 8))
        self.assertEqual(mencoes[0]['tema'], 'degustacao de produtos')
        self.assertEqual(mencoes[0]['natureza'], 'interesse_observado')
        self.assertEqual(mencoes[0]['fonte'], 'crm')
        sem_escrita(cur)

    def test_interesse_vazio_e_ignorado(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'interesse': '   ', 'tipo_lead': 'b2b', 'cidade': None, 'estado': None}]
        self.assertEqual(p.coletar_interesse_crm(cur, None, None), [])


class ColetorInteracoes(unittest.TestCase):
    def test_classificacao_valida_vira_tema(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'classificacao': 'interesse_comercial_b2b', 'interesse': None,
                                       'canal': 'gmail', 'cidade': None, 'estado': None}]
        mencoes = p.coletar_interesse_interacoes(cur, None, None)
        self.assertEqual(len(mencoes), 1)
        self.assertEqual(mencoes[0]['tema'], 'interesse comercial b2b')
        self.assertEqual(mencoes[0]['publico'], 'gmail')

    def test_classificacoes_tecnicas_sao_ignoradas(self):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {'classificacao': 'spam', 'interesse': None, 'canal': 'gmail', 'cidade': None, 'estado': None},
            {'classificacao': 'suporte', 'interesse': None, 'canal': 'whatsapp', 'cidade': None, 'estado': None},
        ]
        self.assertEqual(p.coletar_interesse_interacoes(cur, None, None), [])

    def test_classificacao_e_interesse_livre_geram_duas_mencoes(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'classificacao': 'degustacao', 'interesse': 'quer saber sobre entrega',
                                       'canal': 'whatsapp', 'cidade': 'São Luís', 'estado': 'MA'}]
        mencoes = p.coletar_interesse_interacoes(cur, None, None)
        self.assertEqual(len(mencoes), 2)


class ColetorProspeccao(unittest.TestCase):
    def test_usa_motivo_e_peso_declarados(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'motivo': 'Interesse em parceria B2B', 'resultado': 'promissor',
                                       'publico': 'bar', 'regiao': 'MA', 'peso': 2.5}]
        mencoes = p.coletar_inferencia_prospeccao(cur, None, None)
        self.assertEqual(mencoes[0]['natureza'], 'inferencia')
        self.assertEqual(mencoes[0]['peso'], 2.5)

    def test_sem_motivo_usa_resultado(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'motivo': None, 'resultado': 'pronto_para_fechamento',
                                       'publico': 'bar', 'regiao': None, 'peso': 1}]
        mencoes = p.coletar_inferencia_prospeccao(cur, None, None)
        self.assertEqual(mencoes[0]['tema'], 'pronto para fechamento')


class ColetorProduto(unittest.TestCase):
    def test_reaproveita_mi_sinais_interesse_por_produto(self):
        cur = MagicMock()
        with patch.object(p, 'interesse_por_produto', return_value=[{'sku': 'MC-100ML', 'total': 12}]) as fake:
            mencoes = p.coletar_interesse_produto(cur, dias=30)
        fake.assert_called_once_with(cur, dias=30)
        self.assertEqual(mencoes[0]['natureza'], 'fato')
        self.assertEqual(mencoes[0]['sku'], 'MC-100ML')
        self.assertEqual(mencoes[0]['peso'], 12.0)

    def test_sku_sem_total_e_ignorado(self):
        with patch.object(p, 'interesse_por_produto', return_value=[{'sku': 'MC-100ML', 'total': 0}]):
            self.assertEqual(p.coletar_interesse_produto(MagicMock(), dias=30), [])


class ColetorSite(unittest.TestCase):
    def test_produto_visitado_com_produto_no_payload_vira_tema(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'tipo_evento': 'produto_visitado', 'payload': {'produto': 'guarana'}}]
        mencoes = p.coletar_interesse_site(cur, None, None)
        self.assertEqual(mencoes[0]['tema'], 'guarana')
        self.assertEqual(mencoes[0]['natureza'], 'interesse_observado')
        self.assertEqual(mencoes[0]['fonte'], 'site')

    def test_cta_clicado_com_cta_no_payload_vira_tema(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'tipo_evento': 'cta_clicado', 'payload': {'cta': 'compreaqui'}}]
        mencoes = p.coletar_interesse_site(cur, None, None)
        self.assertEqual(mencoes[0]['tema'], 'compreaqui')

    def test_evento_sem_produto_ou_cta_nao_fabrica_tema(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'tipo_evento': 'produto_visitado', 'payload': {}}]
        self.assertEqual(p.coletar_interesse_site(cur, None, None), [])


class CalcularTop10(unittest.TestCase):
    def _cur(self, crm=(), interacoes=(), aprendizado=(), produto=(), site=()):
        cur = MagicMock()
        cur.fetchall.side_effect = [list(crm), list(interacoes), list(aprendizado), list(site)]
        return cur

    def test_agrega_por_tema_e_ordena_por_intensidade(self):
        cur = self._cur(
            crm=[{'interesse': 'degustacao', 'tipo_lead': 'b2b', 'cidade': 'São Luís', 'estado': 'MA'}] * 3,
            interacoes=[{'classificacao': None, 'interesse': 'entrega', 'canal': 'gmail',
                         'cidade': None, 'estado': None}],
        )
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            top10 = p.calcular_top10(cur, None, None)
        self.assertEqual(top10[0]['tema'], 'degustacao')
        self.assertEqual(top10[0]['intensidade'], 3.0)
        self.assertEqual(top10[0]['posicao'], 1)
        self.assertEqual(top10[0]['natureza'], 'interesse_observado')
        self.assertEqual(top10[0]['territorio_uf'], 'MA')

    def test_tema_so_de_produto_fica_com_natureza_fato(self):
        cur = self._cur()
        with patch.object(p, 'interesse_por_produto', return_value=[{'sku': 'MC-100ML', 'total': 5}]):
            top10 = p.calcular_top10(cur, None, None)
        self.assertEqual(top10[0]['natureza'], 'fato')
        self.assertEqual(top10[0]['produto_relacionado'], 'MC-100ML')

    def test_tema_corroborado_por_mais_fontes_tem_mais_confianca(self):
        cur = self._cur(
            crm=[{'interesse': 'guarana', 'tipo_lead': 'b2b', 'cidade': None, 'estado': None}],
            interacoes=[{'classificacao': None, 'interesse': 'guarana', 'canal': 'gmail',
                         'cidade': None, 'estado': None}],
        )
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            top10 = p.calcular_top10(cur, None, None)
        cur2 = self._cur(crm=[{'interesse': 'guarana', 'tipo_lead': 'b2b', 'cidade': None, 'estado': None}])
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            top10_unica_fonte = p.calcular_top10(cur2, None, None)
        self.assertGreater(top10[0]['confianca'], top10_unica_fonte[0]['confianca'])

    def test_limite_de_10_posicoes(self):
        crm = [{'interesse': f'tema{i}', 'tipo_lead': 'b2b', 'cidade': None, 'estado': None} for i in range(15)]
        cur = self._cur(crm=crm)
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            top10 = p.calcular_top10(cur, None, None, limite=10)
        self.assertEqual(len(top10), 10)

    def test_interesse_do_site_entra_no_top10_quando_ha_evidencia(self):
        cur = self._cur(site=[{'tipo_evento': 'produto_visitado', 'payload': {'produto': 'acai'}}] * 4)
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            top10 = p.calcular_top10(cur, None, None)
        self.assertEqual(top10[0]['tema'], 'acai')
        self.assertEqual(top10[0]['natureza'], 'interesse_observado')
        self.assertIn('site', top10[0]['fonte'])


class DetectarMudancas(unittest.TestCase):
    def item(self, tema, posicao, intensidade):
        return {'tema': tema, 'posicao': posicao, 'intensidade': intensidade}

    def test_tema_novo_no_top5_e_relevante(self):
        mudancas = p.detectar_mudancas([self.item('novo', 3, 5)], [])
        self.assertEqual(mudancas[0]['tipo'], 'novo')
        self.assertTrue(mudancas[0]['relevante'])

    def test_tema_novo_fora_do_top5_nao_e_relevante(self):
        mudancas = p.detectar_mudancas([self.item('novo', 8, 1)], [])
        self.assertFalse(mudancas[0]['relevante'])

    def test_subida_grande_de_posicao_e_relevante(self):
        atual = [self.item('x', 1, 10)]
        anterior = [self.item('x', 9, 10)]
        mudancas = p.detectar_mudancas(atual, anterior)
        self.assertEqual(mudancas[0]['tipo'], 'subindo')
        self.assertTrue(mudancas[0]['relevante'])

    def test_pequena_oscilacao_de_posicao_nao_e_relevante(self):
        atual = [self.item('x', 2, 10)]
        anterior = [self.item('x', 3, 10)]
        mudancas = p.detectar_mudancas(atual, anterior)
        self.assertEqual(mudancas[0]['tipo'], 'estavel')
        self.assertFalse(mudancas[0]['relevante'])

    def test_queda_de_intensidade_sem_mudar_posicao_e_relevante(self):
        atual = [self.item('x', 5, 2)]
        anterior = [self.item('x', 5, 10)]
        mudancas = p.detectar_mudancas(atual, anterior)
        self.assertTrue(mudancas[0]['relevante'])

    def test_tema_que_saiu_do_top5_e_relevante(self):
        mudancas = p.detectar_mudancas([], [self.item('sumiu', 2, 10)])
        self.assertEqual(mudancas[0]['tipo'], 'saiu_do_top')
        self.assertTrue(mudancas[0]['relevante'])


class MudancasParaAtividades(unittest.TestCase):
    def test_so_mudancas_relevantes_viram_atividade(self):
        mudancas = [
            {'tema': 'a', 'tipo': 'subindo', 'posicao_atual': 1, 'posicao_anterior': 5, 'relevante': True},
            {'tema': 'b', 'tipo': 'estavel', 'posicao_atual': 3, 'posicao_anterior': 3, 'relevante': False},
        ]
        atividades = p.mudancas_para_atividades(mudancas)
        self.assertEqual(len(atividades), 1)
        self.assertEqual(atividades[0]['estado'], 'precisa_diretor')
        self.assertEqual(atividades[0]['origem'], 'mi_publico')
        self.assertEqual(atividades[0]['tipo_decisao'], 'mudanca_de_interesse')


class SugerirConteudo(unittest.TestCase):
    def top10(self):
        return [
            {'posicao': 1, 'tema': 'cultura maranhense', 'intensidade': 10, 'natureza': 'interesse_observado',
             'fonte': ['crm'], 'publico_segmento': None, 'produto_relacionado': None},
            {'posicao': 2, 'tema': 'guarana', 'intensidade': 8, 'natureza': 'fato', 'fonte': ['mi_sinais'],
             'publico_segmento': None, 'produto_relacionado': 'MC-100ML'},
            {'posicao': 3, 'tema': 'promocao', 'intensidade': 6, 'natureza': 'inferencia',
             'fonte': ['aprendizado_prospeccao_fase57'], 'publico_segmento': ['bar'], 'produto_relacionado': None},
        ]

    def test_gera_ate_3_posts_um_por_slot(self):
        posts = p.sugerir_conteudo(self.top10())
        self.assertEqual(len(posts), 3)
        self.assertEqual({post['slot'] for post in posts}, {'manha', 'tarde', 'noite'})

    def test_tarde_prefere_tema_com_produto_relacionado(self):
        posts = {post['slot']: post for post in p.sugerir_conteudo(self.top10())}
        self.assertEqual(posts['tarde']['produto_relacionado'], 'MC-100ML')

    def test_todos_os_campos_obrigatorios_presentes(self):
        campos = {'slot', 'tema', 'objetivo', 'publico', 'canal', 'formato', 'ideia', 'cta',
                  'produto_relacionado', 'sinal_que_justificou'}
        for post in p.sugerir_conteudo(self.top10()):
            self.assertTrue(campos.issubset(post.keys()))

    def test_slots_tem_objetivo_correto(self):
        posts = {post['slot']: post for post in p.sugerir_conteudo(self.top10())}
        self.assertEqual(posts['manha']['objetivo'], 'descoberta_cultura')
        self.assertEqual(posts['tarde']['objetivo'], 'produto_uso_educacao')
        self.assertEqual(posts['noite']['objetivo'], 'desejo_conversao_comunidade')

    def test_lista_vazia_nao_gera_posts(self):
        self.assertEqual(p.sugerir_conteudo([]), [])

    def test_top10_com_um_item_nao_quebra(self):
        posts = p.sugerir_conteudo(self.top10()[:1])
        self.assertGreaterEqual(len(posts), 1)


class AtividadesDeConteudo(unittest.TestCase):
    def test_cada_post_vira_atividade_autonoma_planejada(self):
        posts = [{'slot': 'manha', 'tema': 'cultura', 'sinal_que_justificou': {'fonte': 'crm', 'natureza': 'fato'}}]
        agora = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
        atividades = p.atividades_de_conteudo(posts, agora)
        item = atividades[0]
        self.assertEqual(item['proxima_acao'], 'sugerir_conteudo')
        self.assertFalse(item['exige_aprovacao'])
        self.assertEqual(item['estado'], 'planejada')
        self.assertEqual(item['executar_em'], datetime(2026, 1, 5, 9, tzinfo=timezone.utc))
        self.assertEqual(item['detalhe_conteudo'], posts[0])


class PlanejarPublico(unittest.TestCase):
    def test_e_somente_leitura_e_fecha_conexao(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            resultado = p.planejar_publico(lambda: conn)
        conn.set_session.assert_called_once_with(readonly=True, isolation_level='REPEATABLE READ')
        conn.close.assert_called_once()
        sem_escrita(cur)
        self.assertEqual(resultado['top10'], [])
        self.assertFalse(resultado['mudou_desde_ultima_analise'])

    def test_cada_atividade_tem_chave_de_idempotencia(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        # cada janela (atual/anterior) chama crm, interações, aprendizado e site nesta ordem
        cur.fetchall.side_effect = [
            [{'interesse': 'degustacao', 'tipo_lead': 'b2b', 'cidade': None, 'estado': None}],
            [], [], [],  # janela atual: interações, aprendizado, site
            [], [], [], [],  # janela anterior (comparação): nada
        ]
        with patch.object(p, 'interesse_por_produto', return_value=[]):
            resultado = p.planejar_publico(lambda: conn)
        for atividade in resultado['atividades_calendario']:
            self.assertIn('chave', atividade)


class LeituraPainelPublico(unittest.TestCase):
    def test_agrega_as_7_perguntas(self):
        resultado = {
            'top10': [
                {'tema': 'a', 'tendencia': 'subindo', 'produto_relacionado': 'SKU1'},
                {'tema': 'b', 'tendencia': 'caindo', 'produto_relacionado': None},
                {'tema': 'c', 'tendencia': 'estavel', 'produto_relacionado': None},
            ],
            'mudancas': [{'tema': 'a', 'tipo': 'subindo', 'relevante': True}],
            'mudou_desde_ultima_analise': True,
            'posts_sugeridos': [{'slot': 'manha'}],
        }
        leitura = p.leitura_painel_publico(resultado)
        self.assertEqual(len(leitura['o_que_publico_quer_agora']), 3)
        self.assertEqual(len(leitura['subindo']), 1)
        self.assertEqual(len(leitura['caindo']), 1)
        self.assertEqual(len(leitura['oportunidades_de_venda']), 1)
        self.assertTrue(leitura['mudou_desde_ultima_analise'])
        self.assertEqual(len(leitura['posts_sugeridos_hoje']), 1)
        self.assertEqual(len(leitura['mudancas_relevantes']), 1)


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(p))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'gmail_legado', 'whatsapp_meta',
                          'whatsapp_omnichannel', 'openai'):
            self.assertNotIn(proibido, modulos)

    def test_nunca_escreve_com_dados_reais(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            {'interesse': 'degustacao', 'tipo_lead': 'b2b', 'cidade': 'São Luís', 'estado': 'MA',
             'classificacao': 'degustacao', 'canal': 'gmail', 'motivo': 'x', 'resultado': 'promissor',
             'publico': 'bar', 'regiao': 'MA', 'peso': 1,
             'tipo_evento': 'produto_visitado', 'payload': {'produto': 'guarana'}},
        ]
        with patch.object(p, 'interesse_por_produto', return_value=[{'sku': 'MC-100ML', 'total': 5}]):
            p.planejar_publico(lambda: conn)
        sem_escrita(cur)


if __name__ == '__main__':
    unittest.main()
