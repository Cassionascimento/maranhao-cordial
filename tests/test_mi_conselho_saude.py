"""Observabilidade -- mi_conselho_saude.py. Nunca guarda prompt/resposta
bruta/stack trace; agrega por agente mesmo sem nenhuma execução ainda."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import mi_conselho_saude as saude


class ValidarExecucao(unittest.TestCase):
    def test_corpo_minimo_valido(self):
        dados = saude.validar_execucao({'agente': 'rua', 'origem': 'automatico', 'status': 'sucesso'})
        self.assertEqual(dados['agente'], 'rua')
        self.assertIsNone(dados['erro_categoria'])

    def test_status_invalido_e_rejeitado(self):
        with self.assertRaisesRegex(ValueError, 'status_invalido'):
            saude.validar_execucao({'agente': 'rua', 'origem': 'automatico', 'status': 'parcial'})

    def test_origem_invalida_e_rejeitada(self):
        with self.assertRaisesRegex(ValueError, 'origem_invalida'):
            saude.validar_execucao({'agente': 'rua', 'origem': 'batch', 'status': 'sucesso'})

    def test_duracao_negativa_e_rejeitada(self):
        with self.assertRaisesRegex(ValueError, 'duracao_invalida'):
            saude.validar_execucao({'agente': 'rua', 'origem': 'automatico', 'status': 'sucesso', 'duracao_ms': -1})

    def test_campos_de_erro_sao_truncados_com_seguranca(self):
        dados = saude.validar_execucao({
            'agente': 'rua', 'origem': 'interativo', 'status': 'falha',
            'erro_categoria': 'RespostaLLMInvalida', 'erro_detalhe': 'x' * 500,
        })
        self.assertEqual(len(dados['erro_detalhe']), 240)


class ResumoAgente(unittest.TestCase):
    def test_agente_sem_execucao_aparece_como_sem_execucao(self):
        resumo = saude._resumo_agente('iris', [])
        self.assertEqual(resumo['status'], 'sem_execucao')
        self.assertEqual(resumo['total_execucoes'], 0)

    def test_ultima_execucao_e_a_mais_recente_por_data(self):
        agora = datetime.now(timezone.utc)
        linhas = [
            {'status': 'sucesso', 'executado_em': agora - timedelta(hours=2), 'duracao_ms': 900,
             'erro_categoria': None, 'erro_detalhe': None, 'modelo': 'gpt-5-mini', 'tokens_saida': 300},
            {'status': 'falha', 'executado_em': agora - timedelta(minutes=5), 'duracao_ms': 31000,
             'erro_categoria': 'APITimeoutError', 'erro_detalhe': 'timeout', 'modelo': 'gpt-5-mini', 'tokens_saida': None},
        ]
        resumo = saude._resumo_agente('rua', linhas)
        self.assertEqual(resumo['status'], 'falha')
        self.assertEqual(resumo['erro_categoria'], 'APITimeoutError')
        self.assertEqual(resumo['total_execucoes'], 2)
        self.assertAlmostEqual(resumo['taxa_sucesso'], 0.5)

    def test_falha_sucesso_nunca_e_confundida_com_falha_de_todos(self):
        agora = datetime.now(timezone.utc)
        linhas = [{'status': 'sucesso', 'executado_em': agora, 'duracao_ms': 500,
                   'erro_categoria': None, 'erro_detalhe': None, 'modelo': 'gpt-5-mini', 'tokens_saida': 200}]
        resumo = saude._resumo_agente('marie', linhas)
        self.assertEqual(resumo['status'], 'sucesso')
        self.assertIsNone(resumo['erro_categoria'])

    def test_categorias_de_falha_sao_agrupadas(self):
        agora = datetime.now(timezone.utc)
        linhas = [
            {'status': 'falha', 'executado_em': agora, 'duracao_ms': 1, 'erro_categoria': 'RespostaLLMInvalida',
             'erro_detalhe': 'a', 'modelo': 'm', 'tokens_saida': None},
            {'status': 'falha', 'executado_em': agora, 'duracao_ms': 1, 'erro_categoria': 'RespostaLLMInvalida',
             'erro_detalhe': 'b', 'modelo': 'm', 'tokens_saida': None},
            {'status': 'falha', 'executado_em': agora, 'duracao_ms': 1, 'erro_categoria': 'APITimeoutError',
             'erro_detalhe': 'c', 'modelo': 'm', 'tokens_saida': None},
        ]
        resumo = saude._resumo_agente('rua', linhas)
        self.assertEqual(resumo['falhas_por_categoria'], {'RespostaLLMInvalida': 2, 'APITimeoutError': 1})


class SaudeAgentes(unittest.TestCase):
    def test_agentes_conhecidos_sem_linha_aparecem_com_sem_execucao(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        resumo = saude.saude_agentes(cur, ['rua', 'iris'])
        self.assertEqual({r['agente'] for r in resumo}, {'rua', 'iris'})
        self.assertTrue(all(r['status'] == 'sem_execucao' for r in resumo))


class RegistrarRotasSaude(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        from flask import Flask
        app = Flask(__name__)
        saude.registrar_rotas_saude(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        resp = cliente.get('/api/admin/mi/conselho/saude')
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
