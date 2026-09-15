"""Pacote de estado da demanda -- mi_conselho_estado.py. Reaproveita
mi_diretor.leitura_diretor e mi_conselho_orquestrador.classificar_
especialistas (mockados aqui -- já testados nos próprios módulos); o que
este teste cobre é a MONTAGEM dos 11 campos pedidos a partir deles, nunca
o cálculo interno de cada um."""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import mi_conselho_estado as estado


def leitura_base(**overrides):
    base = {
        'ia_trabalhando': False,
        'hoje': {'planejado': [], 'concluido': [], 'aguardando': [], 'bloqueado': [],
                 'oportunidades': [], 'precisa_de_mim': []},
        'calendario': {'hoje': 0, 'proximas': 0, 'concluidas': 0, 'bloqueadas': 0},
        'conselho': {'trabalhando': 0, 'sem_demanda': 8, 'vetos': [], 'aguardando_diretor': []},
        'chamar_diretor': {'necessario': False, 'motivos': []},
    }
    base.update(overrides)
    return base


CLASSIFICACAO_BASE = {'selecionados': ['iris'], 'motivos': {'iris': ['x']}, 'excluidos': {}, 'conclave_completo': False}


class MontarPacoteEstado(unittest.TestCase):
    def _montar(self, demanda='Fornecedor de extrato de gengibre confirmou prazo de 7 dias', **leitura_overrides):
        with patch.object(estado, 'leitura_diretor', return_value=leitura_base(**leitura_overrides)), \
             patch.object(estado, 'classificar_especialistas', return_value=CLASSIFICACAO_BASE), \
             patch.object(estado, '_fatos_relacionados', return_value=[]), \
             patch.object(estado, '_objetivos_estrategicos_ativos', return_value=[]):
            return estado.montar_pacote_estado(lambda: MagicMock(), demanda)

    def test_pacote_tem_exatamente_os_11_campos_pedidos(self):
        pacote = self._montar()
        self.assertEqual(set(pacote), {
            'demanda', 'estado_atual', 'acoes_concluidas', 'acoes_em_andamento', 'evidencias',
            'dados_ausentes', 'bloqueios', 'dependencias', 'prazos', 'restricoes', 'agentes_pertinentes',
        })

    def test_demanda_vazia_levanta_erro(self):
        with self.assertRaises(ValueError):
            estado.montar_pacote_estado(lambda: MagicMock(), '   ')

    def test_dados_ausentes_comeca_vazio_e_e_preenchido_depois_pelos_pareceres(self):
        pacote = self._montar()
        self.assertEqual(pacote['dados_ausentes'], [])

    def test_acoes_em_andamento_combina_planejado_e_aguardando_ordenado_por_prioridade(self):
        planejado = {'chave': 'p1', 'prioridade': 'baixa', 'proxima_acao': 'pesquisar'}
        aguardando = {'chave': 'a1', 'prioridade': 'urgente', 'proxima_acao': 'decidir_proposta'}
        pacote = self._montar(hoje={'planejado': [planejado], 'concluido': [], 'aguardando': [aguardando],
                                     'bloqueado': [], 'oportunidades': [], 'precisa_de_mim': []})
        self.assertEqual([a['chave'] for a in pacote['acoes_em_andamento']], ['a1', 'p1'])

    def test_acoes_em_andamento_nunca_duplica_a_mesma_chave(self):
        item = {'chave': 'x1', 'prioridade': 'alta'}
        pacote = self._montar(hoje={'planejado': [item], 'concluido': [], 'aguardando': [item],
                                     'bloqueado': [], 'oportunidades': [], 'precisa_de_mim': []})
        self.assertEqual(len(pacote['acoes_em_andamento']), 1)

    def test_bloqueios_combina_bloqueado_e_precisa_de_mim(self):
        bloqueado = {'chave': 'b1', 'prioridade': 'alta'}
        precisa = {'chave': 'd1', 'prioridade': 'urgente'}
        pacote = self._montar(hoje={'planejado': [], 'concluido': [], 'aguardando': [],
                                     'bloqueado': [bloqueado], 'oportunidades': [], 'precisa_de_mim': [precisa]})
        chaves = {b['chave'] for b in pacote['bloqueios']}
        self.assertEqual(chaves, {'b1', 'd1'})

    def test_acoes_concluidas_vem_do_hoje_concluido(self):
        concluida = {'chave': 'c1', 'prioridade': 'normal'}
        pacote = self._montar(hoje={'planejado': [], 'concluido': [concluida], 'aguardando': [],
                                     'bloqueado': [], 'oportunidades': [], 'precisa_de_mim': []})
        self.assertEqual(pacote['acoes_concluidas'], [concluida])

    def test_prazos_extraidos_apenas_de_acoes_com_executar_em(self):
        com_prazo = {'chave': 'p1', 'prioridade': 'alta', 'executar_em': '2026-09-20T10:00:00+00:00', 'motivo': 'follow-up'}
        sem_prazo = {'chave': 'p2', 'prioridade': 'alta'}
        pacote = self._montar(hoje={'planejado': [com_prazo, sem_prazo], 'concluido': [], 'aguardando': [],
                                     'bloqueado': [], 'oportunidades': [], 'precisa_de_mim': []})
        self.assertEqual(len(pacote['prazos']), 1)
        self.assertEqual(pacote['prazos'][0]['executar_em'], '2026-09-20T10:00:00+00:00')

    def test_agentes_pertinentes_reaproveita_classificacao_ja_calculada_sem_chamar_de_novo(self):
        with patch.object(estado, 'leitura_diretor', return_value=leitura_base()), \
             patch.object(estado, 'classificar_especialistas') as classificar, \
             patch.object(estado, '_fatos_relacionados', return_value=[]), \
             patch.object(estado, '_objetivos_estrategicos_ativos', return_value=[]):
            pacote = estado.montar_pacote_estado(lambda: MagicMock(), 'demanda qualquer', classificacao=CLASSIFICACAO_BASE)
        classificar.assert_not_called()
        self.assertEqual(pacote['agentes_pertinentes'], CLASSIFICACAO_BASE)

    def test_restricoes_sempre_incluem_a_regra_de_nenhum_agente_agir_sozinho(self):
        pacote = self._montar()
        self.assertTrue(any('irreversível' in r for r in pacote['restricoes']))


class TermosDaDemanda(unittest.TestCase):
    def test_ignora_palavras_curtas_e_stopwords(self):
        termos = estado._termos_da_demanda('Para quando temos o preco do gengibre confirmado?')
        self.assertNotIn('para', termos)
        self.assertNotIn('temos', termos)
        self.assertIn('preco', termos)
        self.assertIn('gengibre', termos)

    def test_limite_de_termos_e_respeitado(self):
        termos = estado._termos_da_demanda('alfa beta gama delta epsilon zeta eta teta', limite=3)
        self.assertEqual(len(termos), 3)


class ObjetivosEstrategicosAtivos(unittest.TestCase):
    def test_tabela_ausente_nunca_derruba_o_pacote_devolve_vazio(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.execute.side_effect = [None, Exception('relation "objetivos_estrategicos" does not exist')]
        resultado = estado._objetivos_estrategicos_ativos(lambda: conn)
        self.assertEqual(resultado, [])
        conn.rollback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
