"""Testing Center -- mi_conselho_testes.py. Bateria repetível: unitários
sempre determinísticos/gratuitos, casos ao vivo só chamam o cliente
injetado (nunca acoes_comerciais/WhatsApp/Gmail/Pix)."""
import json
import unittest
from unittest.mock import MagicMock

import mi_conselho_testes as t


class CasosUnitarios(unittest.TestCase):
    def test_bateria_unitaria_passa_integralmente_hoje(self):
        resultados = t.executar_bateria(incluir_ao_vivo=False)
        falharam = [r for r in resultados if not r['passou']]
        self.assertEqual(falharam, [], f'casos falharam: {falharam}')
        self.assertEqual(len(resultados), len(t.CASOS_UNITARIOS))

    def test_nenhum_caso_unitario_usa_cliente_openai_real(self):
        # Um caso unitário pode injetar um MagicMock em cliente=... (é o
        # caso do guardrail de veto) -- o que nunca pode acontecer é chamar
        # executar_especialista sem `cliente=`, que criaria um OpenAI() real.
        import inspect
        for caso in t.CASOS_UNITARIOS:
            codigo = inspect.getsource(caso)
            if 'executar_especialista(' in codigo:
                self.assertIn('cliente=', codigo)


class CasosAoVivo(unittest.TestCase):
    def _cliente_ok(self):
        base = {'dados_utilizados': 'd', 'conclusao': 'ok', 'confianca': 'media', 'riscos': '',
                'divergencias': '', 'acao_sugerida': 'x', 'necessidade_diretor': False, 'motivo_diretor': '',
                'veto': False, 'veto_motivo': None, 'numeros': [], 'lacunas': [],
                'acao_ja_em_andamento': False, 'natureza_divergencia': 'nenhuma'}
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(output_text=json.dumps(base), status='completed', usage=None)
        return cliente

    def test_agente_isolado_passa_com_resposta_valida(self):
        resultado = t._caso_agente_isolado('rua', self._cliente_ok())
        self.assertTrue(resultado['passou'])

    def test_agente_isolado_falha_com_resposta_incompleta(self):
        incompleto = MagicMock(); incompleto.reason = 'max_output_tokens'
        cliente = MagicMock()
        cliente.responses.create.return_value = MagicMock(output_text=None, status='incomplete',
                                                            incomplete_details=incompleto, usage=None)
        resultado = t._caso_agente_isolado('rua', cliente)
        self.assertFalse(resultado['passou'])
        self.assertIn('max_output_tokens', resultado['motivo'])

    def test_execucao_conjunta_tolera_falha_parcial(self):
        chamadas = {'n': 0}

        def efeito(**kwargs):
            chamadas['n'] += 1
            if chamadas['n'] == 2:
                incompleto = MagicMock(); incompleto.reason = 'max_output_tokens'
                return MagicMock(output_text=None, status='incomplete', incomplete_details=incompleto, usage=None)
            return MagicMock(output_text=json.dumps({
                'dados_utilizados': 'd', 'conclusao': 'ok', 'confianca': 'media', 'riscos': '',
                'divergencias': '', 'acao_sugerida': 'x', 'necessidade_diretor': False, 'motivo_diretor': '',
                'veto': False, 'veto_motivo': None, 'numeros': [], 'lacunas': [],
                'acao_ja_em_andamento': False, 'natureza_divergencia': 'nenhuma',
            }), status='completed', usage=None)

        cliente = MagicMock()
        cliente.responses.create.side_effect = efeito
        resultado = t._caso_execucao_conjunta(['iris', 'marie', 'rua'], cliente)
        self.assertTrue(resultado['passou'])
        self.assertIn('1 falhas', resultado['motivo'])

    def test_nenhum_caso_ao_vivo_chama_acoes_comerciais(self):
        import inspect
        for fabrica in (t._caso_agente_isolado, t._caso_execucao_conjunta):
            codigo = inspect.getsource(fabrica)
            self.assertNotIn('acoes_comerciais', codigo)
            self.assertNotIn('registrar_registro', codigo)


class ExecutarBateria(unittest.TestCase):
    def test_incluir_ao_vivo_falso_nao_cria_cliente_real(self):
        resultados = t.executar_bateria(incluir_ao_vivo=False)
        self.assertTrue(all(r['grupo'] == 'unitario' for r in resultados))

    def test_caso_com_bug_interno_vira_falha_sem_derrubar_bateria(self):
        t.CASOS_UNITARIOS = t.CASOS_UNITARIOS + (lambda: 1 / 0,)
        try:
            resultados = t.executar_bateria(incluir_ao_vivo=False)
        finally:
            t.CASOS_UNITARIOS = t.CASOS_UNITARIOS[:-1]
        self.assertTrue(any(not r['passou'] and 'ZeroDivisionError' in r['motivo'] for r in resultados))


class RegistrarRotasTestes(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        from flask import Flask
        app = Flask(__name__)
        t.registrar_rotas_testes(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.post('/api/admin/mi/conselho/testes/executar').status_code, 401)


if __name__ == '__main__':
    unittest.main()
