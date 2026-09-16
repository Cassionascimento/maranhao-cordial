import io
import unittest
from unittest.mock import patch

import mi_conselho_interativo as ci


class DocumentoInterativo(unittest.TestCase):
    def test_txt_e_extraido_sem_persistencia(self):
        class Arquivo:
            filename = 'decisao.txt'
            def read(self, limite):
                return b'custo margem producao'
        doc = ci.extrair_documento(Arquivo())
        self.assertEqual(doc['nome'], 'decisao.txt')
        self.assertEqual(doc['texto'], 'custo margem producao')
        self.assertFalse(doc['truncado'])

    def test_tipo_desconhecido_e_bloqueado(self):
        class Arquivo:
            filename = 'segredo.exe'
            def read(self, limite):
                return b'abc'
        with self.assertRaisesRegex(ValueError, 'tipo_documento_nao_suportado'):
            ci.extrair_documento(Arquivo())


class SelecaoInterativa(unittest.TestCase):
    def test_especialistas_manuais(self):
        selecionados, classificacao = ci._selecionar('especialistas', 'avaliar', ['marie', 'dicio'], None)
        self.assertEqual(selecionados, ['marie', 'dicio'])
        self.assertFalse(classificacao['conclave_completo'])

    def test_conclave_convoca_os_oito(self):
        selecionados, classificacao = ci._selecionar('conclave', 'avaliar', None, None)
        self.assertEqual(set(selecionados), set(ci.AGENTES))
        self.assertTrue(classificacao['conclave_completo'])

    def test_auto_usa_classificador_existente(self):
        selecionados, _ = ci._selecionar('automatico', 'avaliar custo e margem', None, None)
        self.assertIn('standard', selecionados)


class AnaliseInterativa(unittest.TestCase):
    def _parecer(self, agente):
        return {
            'agente': agente, 'ciclo': 1, 'demanda': 'x', 'gerado_em': 'agora',
            'dados_utilizados': 'dados', 'conclusao': f'parecer {agente}',
            'confianca': 'alta', 'riscos': '', 'divergencias': '',
            'acao_sugerida': f'acao {agente}', 'necessidade_diretor': False,
            'motivo_diretor': '', 'veto': False, 'veto_motivo': None, 'modelo': 'teste',
        }

    def test_analise_nao_registra_nem_executa_acao(self):
        with patch.object(ci, '_snapshot_base', return_value={'empresa': {}}), \
             patch.object(ci, 'executar_especialista_monitorado',
                           side_effect=lambda factory, agente, *a, **k: self._parecer(agente)), \
             patch.object(ci, 'registrar_registro') as registrar:
            resultado = ci.analisar(lambda: None, 'avaliar custo e margem', modo='automatico')
        self.assertTrue(resultado['pareceres'])
        registrar.assert_not_called()

    def test_falha_de_agente_aparece_e_nao_vira_concordancia(self):
        with patch.object(ci, '_snapshot_base', return_value={'empresa': {}}), \
             patch.object(ci, 'executar_especialista_monitorado', side_effect=RuntimeError('falha')):
            resultado = ci.analisar(lambda: None, 'avaliar custo', modo='especialistas', agentes=['standard'])
        self.assertEqual(resultado['pareceres'], [])
        self.assertEqual(resultado['erros'][0]['agente'], 'standard')
        self.assertEqual(resultado['sintese']['total_falhas'], 1)

    def test_enviar_diretor_so_persiste_no_segundo_passo(self):
        resultado = {
            'demanda': 'avaliar custo', 'modo': 'especialistas', 'documento': None,
            'pareceres': [self._parecer('standard')],
        }
        with patch.object(ci, 'registrar_registro', return_value=({'success': True, 'id': 'r1'}, 201)) as registrar:
            retorno = ci.enviar_para_diretor(lambda: None, resultado)
        corpo = registrar.call_args.args[1]
        self.assertTrue(corpo['precisa_diretor'])
        self.assertEqual(corpo['participantes'], ['standard'])
        self.assertTrue(retorno['precisa_diretor'])

    def test_apenas_dicio_pode_vetar_ao_enviar(self):
        base = self._parecer('standard'); base['veto'] = True; base['veto_motivo'] = 'x'
        resultado = {'demanda': 'x', 'modo': 'especialistas', 'pareceres': [base]}
        with patch.object(ci, 'registrar_registro', return_value=({'success': True}, 201)) as registrar:
            ci.enviar_para_diretor(lambda: None, resultado)
        self.assertIsNone(registrar.call_args.args[1]['vetos'])


if __name__ == '__main__':
    unittest.main()
