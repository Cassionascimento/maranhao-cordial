"""Teste de regressão do caso real: falta de ingredientes (extratos,
aromas, gengiróis, sistemas de cor) na fábrica piloto.

Esse caso, analisado manualmente em conversa com o Diretor, revelou os
mesmos oito problemas que motivaram esta etapa inteira. Este arquivo prova
que o pipeline ATUAL (mi_conselho_executor + mi_conselho_fatos + as
personas atualizadas) resolve cada um -- reproduzindo o cenário de perto
o suficiente para servir de regressão real, não um teste de unidade
genérico.

Item 8 (interface apresenta resumo antes dos detalhes) é verificado em
tests/test_conselho_agentes_ui.cjs ('resumo executivo aparece no topo de
cada ata, antes dos pareceres por agente') -- não duplicado aqui porque é
comportamento de DOM, não de Python.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import mi_conselho as c
import mi_conselho_executor as e
import mi_conselho_fatos as f


def resposta(**campos):
    base = {
        'dados_utilizados': '', 'conclusao': '', 'confianca': 'media', 'riscos': '',
        'divergencias': '', 'acao_sugerida': '', 'necessidade_diretor': False,
        'motivo_diretor': '', 'veto': False, 'veto_motivo': None,
        'numeros': [], 'lacunas': [], 'acao_ja_em_andamento': False,
    }
    base.update(campos)
    return MagicMock(output_text=json.dumps(base), status='completed', incomplete_details=None)


def cliente_com(**por_agente_kwargs):
    """Cliente OpenAI fake cuja próxima resposta depende do prompt enviado
    -- basta o prompt conter o nome do agente (sempre presente, é a
    persona) para escolher o parecer certo, sem acoplar à ordem de
    chamadas."""
    cliente = MagicMock()

    def _criar(**kwargs):
        prompt = kwargs.get('input', '')
        for agente_nome, campos in por_agente_kwargs.items():
            # Âncora exclusiva da persona do próprio agente (frase de
            # abertura de cada .md) -- uma simples substring do nome falha
            # porque um agente às vezes cita outro dentro da própria
            # persona (ex.: Standard cita "Rua" em Responsabilidades).
            if f'Você é **{agente_nome}**' in prompt:
                return resposta(**campos)
        return resposta()

    cliente.responses.create.side_effect = _criar
    return cliente


class CasoRealFaltaDeIngredientes(unittest.TestCase):
    DEMANDA = 'Fábrica sinaliza risco de ruptura de extrato de gengibre e aromas para o próximo lote piloto.'

    def setUp(self):
        # Cenário: Rua já acionou um segundo fornecedor (ação em
        # andamento); Standard cita um teto de +50% sem política que
        # sustente; Marie cita uma janela de 7-14 dias sem fonte; Iris
        # aponta as lacunas reais (MOQ/estoque/lead time).
        self.cliente = cliente_com(
            Rua={
                'conclusao': 'Fornecedor alternativo já foi acionado ontem; aguardando retorno.',
                'acao_sugerida': 'Acionar fornecedor alternativo de extrato de gengibre.',
                'acao_ja_em_andamento': True,
            },
            Standard={
                'conclusao': 'Vale pagar mais para não perder o lote piloto.',
                'acao_sugerida': 'Autorizar pagamento de até +50% acima do preço de tabela ao fornecedor.',
                'divergencias': 'Rua avalia o custo de parar a linha como maior que o sobre-preço; '
                                 'aqui a conta ainda não fecha sem confirmar volume.',
            },
            Marie={
                'conclusao': 'Extratos e aromas são os itens tecnicamente mais sensíveis do lote.',
                'acao_sugerida': 'Repor extrato e aromas em 7 a 14 dias para não comprometer a formulação.',
            },
            Iris={
                'conclusao': 'Fatos internos confirmam o risco de ruptura; dados comerciais do fornecedor não confirmados.',
                'lacunas': ['MOQ do fornecedor alternativo não confirmado',
                            'Estoque atual de extrato de gengibre não confirmado',
                            'Lead time do fornecedor alternativo não confirmado'],
            },
        )
        self.pareceres = [
            e.executar_especialista('rua', self.DEMANDA, cliente=self.cliente),
            e.executar_especialista('standard', self.DEMANDA, cliente=self.cliente),
            e.executar_especialista('marie', self.DEMANDA, cliente=self.cliente),
            e.executar_especialista('iris', self.DEMANDA, cliente=self.cliente),
        ]
        self.avaliado = {'sinal_id': 'sinal-ruptura-1', 'demanda': self.DEMANDA,
                          'motivo': 'ruptura de insumo sinalizada pela fábrica', 'tipo_evento': 'nao_conformidade'}
        self.consolidado = e._consolidar(self.avaliado, self.pareceres, [])
        self.sintese = self.consolidado['dados_apresentados']['sintese_estruturada']

    # 1. Fornecedor já acionado não é recomendado de novo como ação nova.
    def test_1_acao_ja_em_andamento_nao_vira_recomendacao_nova(self):
        descricoes = [r['descricao'] for r in self.consolidado['recomendacoes']]
        self.assertNotIn('Acionar fornecedor alternativo de extrato de gengibre.', descricoes)
        ja_em_andamento = self.consolidado['dados_apresentados']['recomendacoes_ja_em_andamento']
        self.assertEqual(ja_em_andamento, [{'responsavel': 'rua', 'descricao': 'Acionar fornecedor alternativo de extrato de gengibre.'}])

    # 2. "+50%" sem fonte não passa como fato/política -- vira pendência,
    # nunca autorização silenciosa.
    def test_2_teto_de_50_por_cento_sem_fonte_forca_necessidade_de_diretor(self):
        parecer_standard = next(p for p in self.pareceres if p['agente'] == 'standard')
        self.assertIn('50', parecer_standard['numeros_sem_evidencia'])
        self.assertTrue(parecer_standard['necessidade_diretor'])
        self.assertIn('50', self.consolidado['pendencias']['numeros_sem_evidencia'])
        self.assertTrue(self.consolidado['precisa_diretor'])

    # 3. "7 a 14 dias" sem fonte aparece sinalizado, nunca como prazo confirmado.
    def test_3_janela_de_dias_sem_fonte_e_sinalizada_nao_confirmada(self):
        parecer_marie = next(p for p in self.pareceres if p['agente'] == 'marie')
        self.assertIn('7', parecer_marie['numeros_sem_evidencia'])
        self.assertIn('14', parecer_marie['numeros_sem_evidencia'])

    # 3b. Quando o mesmo número VEM com origem ESTIMATIVA declarada, ele é
    # aceito -- mas mi_conselho_fatos nunca deixa uma estimativa virar
    # "atual" para sempre (fica INCERTO, com validade curta).
    def test_3b_numero_tagueado_como_estimativa_fica_incerto_no_banco_de_fatos(self):
        agora = datetime.now(timezone.utc)
        _, dados = f.validar_fato({
            'chave': '22222222-2222-2222-2222-222222222222', 'topico': 'prazo_reposicao_gengibre',
            'valor': '7-14 dias', 'origem_tipo': 'ESTIMATIVA', 'confianca': 'media',
        })
        fato = {**dados}
        self.assertEqual(f.status_fato(fato, agora), 'INCERTO')

    # 4. Iris aponta ausência de MOQ/estoque/lead time -- nunca "ver
    # especialista pertinente".
    def test_4_iris_aponta_lacunas_reais_de_moq_estoque_lead_time(self):
        parecer_iris = next(p for p in self.pareceres if p['agente'] == 'iris')
        texto_lacunas = ' '.join(parecer_iris['lacunas']).lower()
        self.assertIn('moq', texto_lacunas)
        self.assertIn('estoque', texto_lacunas)
        self.assertIn('lead time', texto_lacunas)
        self.assertEqual(self.sintese['o_que_nao_sabemos'], sorted(parecer_iris['lacunas']))
        self.assertEqual(self.sintese['evidencia_necessaria'], self.sintese['o_que_nao_sabemos'])

    # 5. Divergências permanecem visíveis -- nunca "fabricamos consenso".
    def test_5_divergencia_entre_rua_e_standard_permanece_visivel(self):
        self.assertIn('standard', self.consolidado['conflitos'])
        self.assertIn('Standard', self.sintese['divergencias'])
        self.assertFalse(self.sintese['decisao_possivel_agora'])

    # 6. Ação irreversível continua protegida -- toda recomendação do
    # Conselho ainda exige aprovação humana ao entrar na fila (mi_decisao),
    # e só Dicio pode vetar mesmo que outro agente tente.
    def test_6_recomendacao_do_conselho_continua_exigindo_aprovacao_humana(self):
        for recomendacao in self.consolidado['recomendacoes']:
            atividade = c.recomendacao_para_atividade(recomendacao)
            self.assertTrue(atividade['exige_aprovacao'])
            self.assertEqual(atividade['estado'], 'aguardando')

        cliente_veto_indevido = cliente_com(Rua={'veto': True, 'veto_motivo': 'tentativa de veto fora de escopo'})
        parecer_rua = e.executar_especialista('rua', self.DEMANDA, cliente=cliente_veto_indevido)
        self.assertFalse(parecer_rua['veto'])

    # 7. Fato vencido não é tratado como atual.
    def test_7_fato_vencido_nunca_e_tratado_como_atual(self):
        agora = datetime.now(timezone.utc)
        preco_antigo = {
            'origem_tipo': 'FORNECEDOR', 'confianca': 'alta',
            'valido_ate': agora - timedelta(days=1),
        }
        self.assertEqual(f.status_fato(preco_antigo, agora), 'DESATUALIZADO')

    # 8. Interface apresenta resumo antes dos detalhes -- ver
    # tests/test_conselho_agentes_ui.cjs ('resumo executivo aparece no
    # topo de cada ata, antes dos pareceres por agente'). Aqui só
    # confirmamos que o BACKEND entrega os dados que essa tela precisa
    # (sintese_estruturada com as 11 seções) para não silenciosamente
    # deixar de existir.
    def test_8_backend_entrega_sintese_estruturada_para_o_resumo_da_interface(self):
        self.assertEqual(set(self.sintese), {
            'o_que_sabemos', 'o_que_nao_sabemos', 'convergencias', 'divergencias', 'riscos', 'bloqueios',
            'decisao_possivel_agora', 'proxima_acao', 'responsavel', 'evidencia_necessaria', 'precisa_diretor',
            'motivos_diretor',
        })


if __name__ == '__main__':
    unittest.main()
