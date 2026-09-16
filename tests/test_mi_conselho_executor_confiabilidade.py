"""Confiabilidade do executor: retry limitado só para falha transitória,
orçamento de tokens, captura de tokens/tentativas/duração para telemetria.
Este arquivo cobre só o que mudou nesta rodada -- o resto do contrato de
executar_especialista já está coberto em test_mi_conselho_executor.py."""
import json
import unittest
from unittest.mock import MagicMock, patch

from openai import APITimeoutError, RateLimitError

import mi_conselho_executor as e


def _resposta_ok(**campos):
    base = {'dados_utilizados': 'd', 'conclusao': 'ok', 'confianca': 'media', 'riscos': '', 'divergencias': '',
            'acao_sugerida': 'x', 'necessidade_diretor': False, 'motivo_diretor': '', 'veto': False,
            'veto_motivo': None}
    base.update(campos)
    uso = MagicMock(input_tokens=120, output_tokens=340, output_tokens_details=MagicMock(reasoning_tokens=180))
    return MagicMock(output_text=json.dumps(base), status='completed', usage=uso)


class RetryTransitorio(unittest.TestCase):
    def _erro_timeout(self):
        return APITimeoutError(request=MagicMock())

    def test_falha_transitoria_uma_vez_e_recupera_na_segunda_tentativa(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = [self._erro_timeout(), _resposta_ok()]
        parecer = e.executar_especialista('rua', 'demanda', cliente=cliente)
        self.assertEqual(cliente.responses.create.call_count, 2)
        self.assertEqual(parecer['tentativas'], 2)

    def test_falha_transitoria_alem_do_limite_propaga_excecao(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = [self._erro_timeout(), self._erro_timeout()]
        with self.assertRaises(APITimeoutError):
            e.executar_especialista('rua', 'demanda', cliente=cliente)
        self.assertEqual(cliente.responses.create.call_count, 1 + e.MAX_TENTATIVAS_TRANSITORIA)

    def test_resposta_incompleta_nunca_e_reteitada(self):
        # RespostaLLMInvalida é levantada DEPOIS da chamada (na extração) --
        # não é um _ERROS_TRANSITORIOS, então nunca aciona retry.
        cliente = MagicMock()
        incompleto = MagicMock(); incompleto.reason = 'max_output_tokens'
        cliente.responses.create.return_value = MagicMock(output_text=None, status='incomplete',
                                                            incomplete_details=incompleto)
        with self.assertRaises(e.RespostaLLMInvalida):
            e.executar_especialista('rua', 'demanda', cliente=cliente)
        cliente.responses.create.assert_called_once()

    def test_rate_limit_tambem_e_transitorio(self):
        cliente = MagicMock()
        erro = RateLimitError(message='limite', response=MagicMock(status_code=429), body=None)
        cliente.responses.create.side_effect = [erro, _resposta_ok()]
        parecer = e.executar_especialista('rua', 'demanda', cliente=cliente)
        self.assertEqual(parecer['confianca'], 'media')


class CapturaDeTelemetria(unittest.TestCase):
    def test_tokens_e_tentativas_aparecem_no_retorno(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = _resposta_ok()
        parecer = e.executar_especialista('rua', 'demanda', cliente=cliente)
        self.assertEqual(parecer['tentativas'], 1)
        self.assertEqual(parecer['tokens_entrada'], 120)
        self.assertEqual(parecer['tokens_saida'], 340)
        self.assertEqual(parecer['tokens_raciocinio'], 180)


class OrcamentoEBudgetConfig(unittest.TestCase):
    def test_orcamento_de_tokens_tem_folga_para_schema_atual(self):
        # Não é uma prova de que 3000 é suficiente em produção (isso só a
        # API real confirma) -- é uma trava de regressão: ninguém reduz o
        # orçamento de volta a um valor menor que o schema atual sem
        # perceber, já que o schema cresceu desde os 2000 originais.
        self.assertGreaterEqual(e.MAX_OUTPUT_TOKENS, 3000)

    def test_timeout_generoso_o_bastante_para_modelo_de_raciocinio(self):
        self.assertGreaterEqual(e.TIMEOUT_SEGUNDOS, 60)

    def test_limite_de_retry_e_pequeno(self):
        self.assertLessEqual(e.MAX_TENTATIVAS_TRANSITORIA, 1)


class ExecutarEspecialistaMonitorado(unittest.TestCase):
    def test_sucesso_registra_execucao_com_status_sucesso(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = _resposta_ok()
        factory = MagicMock()
        with patch('mi_conselho_saude.registrar_execucao') as registrar:
            parecer = e.executar_especialista_monitorado(factory, 'rua', 'demanda', 'automatico', cliente=cliente)
        self.assertEqual(parecer['conclusao'], 'ok')
        corpo = registrar.call_args.args[1]
        self.assertEqual(corpo['status'], 'sucesso')
        self.assertEqual(corpo['agente'], 'rua')
        self.assertEqual(corpo['origem'], 'automatico')
        self.assertIn('duracao_ms', corpo)

    def test_falha_registra_execucao_com_status_falha_e_propaga_excecao(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = RuntimeError('falha de rede')
        factory = MagicMock()
        with patch('mi_conselho_saude.registrar_execucao') as registrar:
            with self.assertRaises(RuntimeError):
                e.executar_especialista_monitorado(factory, 'rua', 'demanda', 'interativo', cliente=cliente)
        corpo = registrar.call_args.args[1]
        self.assertEqual(corpo['status'], 'falha')
        self.assertEqual(corpo['erro_categoria'], 'RuntimeError')

    def test_falha_ao_registrar_telemetria_nunca_impede_resultado_real(self):
        cliente = MagicMock()
        cliente.responses.create.return_value = _resposta_ok()
        factory = MagicMock()
        with patch('mi_conselho_saude.registrar_execucao', side_effect=RuntimeError('banco fora')):
            parecer = e.executar_especialista_monitorado(factory, 'rua', 'demanda', 'automatico', cliente=cliente)
        self.assertEqual(parecer['conclusao'], 'ok')

    def test_nunca_grava_prompt_ou_resposta_bruta_na_telemetria(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = RuntimeError('falha contendo prompt sensível XYZ123')
        factory = MagicMock()
        with patch('mi_conselho_saude.registrar_execucao') as registrar:
            with self.assertRaises(RuntimeError):
                e.executar_especialista_monitorado(factory, 'rua', 'demanda secreta', 'automatico', cliente=cliente)
        corpo = registrar.call_args.args[1]
        self.assertNotIn('demanda secreta', json.dumps(corpo))
        self.assertLessEqual(len(corpo['erro_detalhe'] or ''), 240)


if __name__ == '__main__':
    unittest.main()
