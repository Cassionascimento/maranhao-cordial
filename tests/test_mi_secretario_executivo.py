"""P5.X — Milestone 3: Secretário Executivo. Nunca decide, nunca escreve
em mi_fila_operacional/mi_conselho_registros; só transforma um registro
JÁ PERSISTIDO em ata compacta. Testa a única chamada de LLM (síntese
narrativa, mockada) e a rota real via app.test_client() -- nunca importa
main.py."""
import json
import unittest
from unittest.mock import MagicMock

from flask import Flask

import mi_secretario_executivo as secretario


def _resposta_openai(**campos):
    base = {'titulo': 'Conselho — pricing do Bacuri', 'narrativa': 'Margem caiu 3pp; Standard recomenda revisar tabela de preço.'}
    base.update(campos)
    return MagicMock(output_text=json.dumps(base))


def _cliente_mock(**campos):
    cliente = MagicMock()
    cliente.responses.create.return_value = _resposta_openai(**campos)
    return cliente


def _registro(**over):
    base = {
        'id': 'reg-1', 'chave': 'chave-1', 'demanda': 'Devemos ajustar o preço do Bacuri?',
        'participantes': ['standard', 'iris'],
        'conclusao': 'Standard: ajustar pricing do SKU Bacuri.',
        'recomendacoes': [{'responsavel': 'standard', 'descricao': 'revisar tabela de preço', 'confianca': 'alta'}],
        'precisa_diretor': False,
        'dados_apresentados': {
            'sintese_estruturada': {
                'proxima_acao': 'revisar tabela de preço', 'motivos_diretor': None,
            },
            'pareceres_compactos': [
                {'agente': 'standard', 'facts': ['margem caiu 3pp'], 'evidence': [], 'interpretation': ['ajustar pricing'],
                 'recommendation': ['revisar tabela de preço'], 'confidence': 'alta', 'disagreement': [],
                 'requested_visual': {'artifact_type': 'CHART', 'descricao': 'evolução de margem'}},
                {'agente': 'iris', 'facts': [], 'evidence': [], 'interpretation': [], 'recommendation': [],
                 'confidence': 'alta', 'disagreement': [], 'requested_visual': None},
            ],
        },
    }
    base.update(over)
    return base


class VisuaisSugeridos(unittest.TestCase):
    def test_agrega_visuais_pedidos_por_agente(self):
        pareceres = [
            {'agente': 'standard', 'requested_visual': {'artifact_type': 'CHART', 'descricao': 'margem'}},
            {'agente': 'iris', 'requested_visual': None},
        ]
        sugeridos = secretario._visuais_sugeridos(pareceres)
        self.assertEqual(len(sugeridos), 1)
        self.assertEqual(sugeridos[0]['solicitado_por'], 'standard')

    def test_visuais_identicos_de_agentes_diferentes_nao_duplicam(self):
        pareceres = [
            {'agente': 'standard', 'requested_visual': {'artifact_type': 'CHART', 'descricao': 'margem'}},
            {'agente': 'leonard', 'requested_visual': {'artifact_type': 'CHART', 'descricao': 'margem'}},
        ]
        self.assertEqual(len(secretario._visuais_sugeridos(pareceres)), 1)

    def test_sem_pareceres_e_lista_vazia(self):
        self.assertEqual(secretario._visuais_sugeridos(None), [])
        self.assertEqual(secretario._visuais_sugeridos([]), [])


class DecisoesEProximosPassos(unittest.TestCase):
    def test_deriva_das_recomendacoes_existentes_nunca_inventa(self):
        decisoes, _ = secretario._decisoes_e_proximos_passos(_registro())
        self.assertEqual(decisoes, ['standard: revisar tabela de preço'])

    def test_proximo_passo_vem_da_sintese_estruturada(self):
        _, proximos = secretario._decisoes_e_proximos_passos(_registro())
        self.assertIn('revisar tabela de preço', proximos)

    def test_motivo_diretor_vira_proximo_passo_explicito(self):
        registro = _registro()
        registro['dados_apresentados']['sintese_estruturada']['motivos_diretor'] = [
            {'agente': 'Dicio', 'motivo': 'veto jurídico — claim sem comprovação'},
        ]
        _, proximos = secretario._decisoes_e_proximos_passos(registro)
        self.assertTrue(any('claim sem comprovação' in p for p in proximos))

    def test_sem_recomendacao_nem_proxima_acao_listas_vazias_nunca_erro(self):
        registro = _registro(recomendacoes=[], dados_apresentados={'sintese_estruturada': {}})
        decisoes, proximos = secretario._decisoes_e_proximos_passos(registro)
        self.assertEqual(decisoes, [])
        self.assertEqual(proximos, [])


class NarrativaDeterministica(unittest.TestCase):
    def test_usa_conclusao_do_registro(self):
        narrativa = secretario._narrativa_deterministica(_registro())
        self.assertIn('ajustar pricing', narrativa['narrativa'])

    def test_sem_conclusao_usa_texto_generico_explicito(self):
        narrativa = secretario._narrativa_deterministica(_registro(conclusao=''))
        self.assertEqual(narrativa['narrativa'], 'Sem conclusão consolidada disponível para esta demanda.')


class GerarNarrativa(unittest.TestCase):
    def test_chamada_ao_llm_usa_apenas_dados_compactos_nunca_pareceres_verbosos(self):
        cliente = _cliente_mock()
        secretario.gerar_narrativa(_registro(), cliente=cliente)
        prompt_enviado = cliente.responses.create.call_args.kwargs['input']
        self.assertIn('pareceres_compactos', prompt_enviado)
        self.assertNotIn('dados_utilizados', prompt_enviado)  # campo só existe no parecer verboso

    def test_chamada_nunca_usa_tools_nem_historico_nem_persiste_do_lado_openai(self):
        cliente = _cliente_mock()
        secretario.gerar_narrativa(_registro(), cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertNotIn('tools', kwargs)
        self.assertNotIn('previous_response_id', kwargs)
        self.assertFalse(kwargs['store'])

    def test_resposta_valida_e_usada(self):
        cliente = _cliente_mock(titulo='Título real', narrativa='Narrativa real gerada.')
        resultado = secretario.gerar_narrativa(_registro(), cliente=cliente)
        self.assertEqual(resultado, {'titulo': 'Título real', 'narrativa': 'Narrativa real gerada.'})

    def test_falha_de_rede_cai_no_fallback_deterministico_nunca_propaga(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = RuntimeError('timeout')
        resultado = secretario.gerar_narrativa(_registro(), cliente=cliente)
        self.assertIn('ajustar pricing', resultado['narrativa'])

    def test_json_malformado_cai_no_fallback(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(output_text='não é json')
        resultado = secretario.gerar_narrativa(_registro(), cliente=cliente)
        self.assertIn('ajustar pricing', resultado['narrativa'])

    def test_narrativa_vazia_cai_no_fallback(self):
        cliente = _cliente_mock(narrativa='   ')
        resultado = secretario.gerar_narrativa(_registro(), cliente=cliente)
        self.assertIn('ajustar pricing', resultado['narrativa'])


class MontarAtaExecutiva(unittest.TestCase):
    def test_ata_completa_com_todos_os_campos(self):
        cliente = _cliente_mock()
        ata = secretario.montar_ata_executiva(_registro(), cliente=cliente)
        self.assertEqual(ata['meeting_id'], 'reg-1')
        self.assertEqual(ata['participantes'], ['standard', 'iris'])
        self.assertEqual(ata['decisoes'], ['standard: revisar tabela de preço'])
        self.assertEqual(len(ata['visuais_sugeridos']), 1)
        self.assertFalse(ata['precisa_diretor'])

    def test_ata_nunca_expoe_campos_verbosos_do_parecer(self):
        cliente = _cliente_mock()
        ata = secretario.montar_ata_executiva(_registro(), cliente=cliente)
        self.assertNotIn('pareceres_compactos', ata)
        self.assertNotIn('dados_apresentados', ata)


class RotaHTTP(unittest.TestCase):
    def _app(self, registro, autorizado=lambda: True):
        app = Flask(__name__)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = registro
        secretario.registrar_rotas_leitura(app, lambda: conn, autorizado)
        return app

    def test_exige_autenticacao(self):
        app = self._app(None, autorizado=lambda: False)
        resp = app.test_client().get('/api/admin/mi/conselho/reg-1/ata')
        self.assertEqual(resp.status_code, 401)

    def test_registro_inexistente_e_404_json(self):
        app = self._app(None)
        resp = app.test_client().get('/api/admin/mi/conselho/reg-1/ata')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()['success'])

    def test_registro_existente_monta_ata_via_http(self):
        # Linha exatamente como mi_conselho.buscar_registro espera receber
        # de um SELECT * real (todas as CAMPOS_REGISTRO presentes, mesmo
        # que None -- é assim que Postgres devolve uma coluna NULL).
        registro = _registro()
        row = {
            'id': 'reg-1', 'chave': 'chave-1', 'versao': 1, 'criado_em': None,
            'tipo': 'reuniao', 'demanda': registro['demanda'], 'participantes': registro['participantes'],
            'contexto': None, 'dados_apresentados': registro['dados_apresentados'],
            'posicoes': None, 'conflitos': None, 'conclusao': registro['conclusao'],
            'recomendacoes': registro['recomendacoes'], 'vetos': None, 'pendencias': None,
            'precisa_diretor': registro['precisa_diretor'],
        }
        app = self._app(row)
        resp = app.test_client().get('/api/admin/mi/conselho/reg-1/ata')
        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertTrue(corpo['success'])
        self.assertIn('narrativa', corpo)
        self.assertIn('decisoes', corpo)


class NenhumaAcaoExterna(unittest.TestCase):
    def test_modulo_nunca_chama_canais_externos_nem_escreve_fila(self):
        import inspect
        codigo = inspect.getsource(secretario)
        for proibido in ('smtplib', 'requests.', 'import whatsapp', 'import gmail',
                          'registrar_item_fila(', 'avancar_estado_fila(', 'INSERT INTO', 'UPDATE '):
            self.assertNotIn(proibido, codigo)


if __name__ == '__main__':
    unittest.main()
