"""P2 -- Maranhão Intelligence Core: sinal unificado (P2A), score explicável
(P2B), segmentação (P2C), oportunidade (P2D) e Next Best Action (P2E) sobre
o Customer/Partner 360. Tudo função pura sobre o dict já retornado por
mi_relacionamento_360 -- nenhum banco, nenhuma rede aqui."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

from flask import Flask

import mi_inteligencia_relacionamento as intel
import mi_sinais_relacionamento as sinais_mod

AGORA = datetime(2026, 9, 20, tzinfo=timezone.utc)
LEAD_ID = '11111111-1111-1111-1111-111111111111'
ESTAB_ID = '22222222-2222-2222-2222-222222222222'


def _lead(**over):
    base = {'id': LEAD_ID, 'nome': 'Fulano', 'empresa': 'Bar do Fulano', 'email': 'fulano@bar.com',
            'telefone': '11999990000', 'instagram': None, 'cidade': 'São Luís', 'estado': 'MA',
            'origem': 'whatsapp', 'canal': 'whatsapp', 'categoria_contato': 'bar', 'estagio': 'cliente',
            'status': 'ativo', 'prioridade': 'normal', 'valor_potencial_centavos': None,
            'receita_acumulada_centavos': 0, 'quantidade_compras': 0, 'ultima_compra_em': None,
            'proxima_recompra_em': None, 'motivo_perda': None, 'proximo_followup': None,
            'ultima_interacao_em': None, 'criado_em': AGORA - timedelta(days=200), 'atualizado_em': AGORA}
    base.update(over)
    return base


def _visao_vazia():
    """Nem pessoa nem estabelecimento resolvidos -- 'identidade ambígua'/
    'dados UNKNOWN': o mínimo que mi_relacionamento_360 devolveria quando
    só o estabelecimento existe e não tem lead_id."""
    return {
        'identity': {'pessoa': None, 'papel': None, 'contatos_e_canais': [], 'origem': None,
                     'primeira_interacao': None, 'ultima_interacao': None},
        'organization': None,
        'relationship': {'pessoa_estabelecimento': 'UNKNOWN', 'estabelecimento_pedidos': 'UNKNOWN',
                          'estabelecimento_produtos': 'UNKNOWN', 'pessoa_interacoes': 'UNKNOWN'},
        'commercial': {'estagio': None, 'motivo_perda': None, 'propostas': [], 'compras_relacionamento': [],
                       'pedidos_vinculados': [], 'receita_acumulada_centavos': None,
                       'quantidade_compras_leads_crm': None, 'ultima_compra_em': None, 'proxima_recompra_em': None},
        'products': [],
        'behavior': {'interacoes_omnichannel': [], 'eventos_do_estabelecimento': [],
                     'formularios': {'cadastro_profissional': [], 'degustacao': []}, 'canais_utilizados': []},
        'geography': {'cidade': None, 'uf': None, 'territorio': 'NOT_ENOUGH_DATA'},
        'derived_metrics': {
            'total_orders': 0, 'total_revenue_centavos': 0, 'average_order_value_centavos': 'NOT_ENOUGH_DATA',
            'days_since_last_order': 'NOT_ENOUGH_DATA', 'days_since_last_interaction': 'NOT_ENOUGH_DATA',
            'products_purchased': [], 'orders_by_sku': {}, 'reorder_count': 'NOT_ENOUGH_DATA',
            'interaction_count': 0, 'channels_used': [],
        },
        'data_quality': {
            'pessoa_resolvida': False, 'estabelecimento_resolvido': False,
            'pedidos_vinculo': 'INFERRED (e-mail normalizado ou whatsapp por igualdade exata de string)',
            'propostas_vinculo': 'INFERRED (e-mail, só cobre prospecção fase56/fase57)',
            'formularios_vinculo': 'INFERRED (e-mail exato)',
            'eventos_vinculo': 'INFERRED ao estabelecimento, nunca à pessoa (mi_eventos não tem lead_id)',
            'compras_relacionamento_e_autoritativo_para_receita': True,
            'lead_score_unificado': 'NOT_ENOUGH_DATA (scoring fora de escopo desta etapa)',
        },
    }


def _visao_com_pessoa(lead=None, interacoes=None, compras=None, pedidos=None, propostas=None,
                       produtos=None, eventos=None, formularios=None, estabelecimento=None):
    lead = lead if lead is not None else _lead()
    interacoes = interacoes or []
    compras = compras or []
    pedidos = pedidos or []
    produtos = produtos or []
    v = _visao_vazia()
    v['identity'] = {'pessoa': lead, 'papel': lead.get('categoria_contato'), 'contatos_e_canais': [],
                      'origem': lead.get('origem'), 'primeira_interacao': lead.get('criado_em'),
                      'ultima_interacao': max((i['criado_em'] for i in interacoes), default=None)}
    v['organization'] = estabelecimento
    v['relationship']['pessoa_estabelecimento'] = 'DIRECT' if (estabelecimento and estabelecimento.get('lead_id')) else 'UNKNOWN'
    v['relationship']['pessoa_interacoes'] = 'DIRECT' if interacoes else 'UNKNOWN'
    v['commercial'] = {
        'estagio': lead.get('estagio'), 'motivo_perda': lead.get('motivo_perda'),
        'propostas': propostas or [], 'compras_relacionamento': compras, 'pedidos_vinculados': pedidos,
        'receita_acumulada_centavos': lead.get('receita_acumulada_centavos'),
        'quantidade_compras_leads_crm': lead.get('quantidade_compras'),
        'ultima_compra_em': lead.get('ultima_compra_em'), 'proxima_recompra_em': lead.get('proxima_recompra_em'),
    }
    v['products'] = produtos
    v['behavior'] = {
        'interacoes_omnichannel': interacoes, 'eventos_do_estabelecimento': eventos or [],
        'formularios': formularios or {'cadastro_profissional': [], 'degustacao': []},
        'canais_utilizados': sorted({i['canal'] for i in interacoes if i.get('canal')}),
    }
    v['geography'] = {'cidade': lead.get('cidade'), 'uf': lead.get('estado'), 'territorio': 'NOT_ENOUGH_DATA'}
    total_orders = len(compras)
    receitas = [c['valor_centavos'] for c in compras if c.get('valor_centavos') is not None]
    receita_total = sum(receitas) if receitas else (0 if total_orders == 0 else 'NOT_ENOUGH_DATA')
    ultima_compra = max((c['comprado_em'] for c in compras if c.get('comprado_em')), default=None)
    ultima_interacao = max((i['criado_em'] for i in interacoes if i.get('criado_em')), default=None)
    v['derived_metrics'] = {
        'total_orders': total_orders, 'total_revenue_centavos': receita_total,
        'average_order_value_centavos': (receita_total / total_orders) if (isinstance(receita_total, (int, float)) and total_orders) else 'NOT_ENOUGH_DATA',
        'days_since_last_order': (AGORA - ultima_compra).days if ultima_compra else 'NOT_ENOUGH_DATA',
        'days_since_last_interaction': (AGORA - ultima_interacao).days if ultima_interacao else 'NOT_ENOUGH_DATA',
        'products_purchased': sorted({p['sku'] for p in pedidos if p.get('sku')}),
        'orders_by_sku': {}, 'reorder_count': max(total_orders - 1, 0) if total_orders else 'NOT_ENOUGH_DATA',
        'interaction_count': len(interacoes), 'channels_used': sorted({i['canal'] for i in interacoes if i.get('canal')}),
    }
    v['data_quality']['pessoa_resolvida'] = True
    return v


class SinaisUnificados(unittest.TestCase):
    def test_multiplos_sinais_sao_extraidos_e_nunca_inventados(self):
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'mensagem',
                       'classificacao': None, 'interesse': 'alto', 'criado_em': AGORA - timedelta(days=1)}]
        pedidos = [{'codigo': 'MAR-1', 'status': 'pago', 'valor_centavos': 5990, 'quantidade': 1,
                    'sku': 'CORDIAL-GENGIBRE-500ML', 'criado_em': AGORA - timedelta(days=5)}]
        visao = _visao_com_pessoa(interacoes=interacoes, pedidos=pedidos)
        resultado = sinais_mod.extrair_sinais(visao, agora=AGORA)
        tipos = {s['type'] for s in resultado}
        self.assertIn('interaction', tipos)
        self.assertIn('order_product', tipos)
        self.assertIn('pipeline_stage', tipos)
        self.assertIn('origin', tipos)
        for s in resultado:
            self.assertTrue(s['evidence'], f'sinal {s["type"]} sem evidência')

    def test_sinal_relacionamento_multicanal(self):
        interacoes = [
            {'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'mensagem', 'classificacao': None,
             'interesse': None, 'criado_em': AGORA - timedelta(days=1)},
            {'canal': 'instagram', 'plataforma': 'meta', 'tipo_interacao': 'dm', 'classificacao': None,
             'interesse': None, 'criado_em': AGORA - timedelta(days=20)},
        ]
        visao = _visao_com_pessoa(interacoes=interacoes)
        resultado = sinais_mod.extrair_sinais(visao, agora=AGORA)
        canais = {s['object'] for s in resultado if s['type'] == 'interaction'}
        self.assertEqual(canais, {'whatsapp', 'instagram'})

    def test_confianca_direta_e_inferida_tem_pesos_distintos(self):
        pedidos = [{'codigo': 'MAR-1', 'status': 'pago', 'valor_centavos': 5990, 'quantidade': 1,
                    'sku': 'X', 'criado_em': AGORA}]
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'msg', 'classificacao': None,
                       'interesse': None, 'criado_em': AGORA}]
        visao = _visao_com_pessoa(interacoes=interacoes, pedidos=pedidos)
        resultado = sinais_mod.extrair_sinais(visao, agora=AGORA)
        direto = next(s for s in resultado if s['type'] == 'interaction')
        inferido = next(s for s in resultado if s['type'] == 'order_product')
        self.assertEqual(direto['confidence'], 1.0)
        self.assertEqual(inferido['confidence'], 0.6)


class ScoreExplicavel(unittest.TestCase):
    def test_score_traz_explicacao_por_dimensao(self):
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'msg', 'classificacao': None,
                       'interesse': 'alto', 'criado_em': AGORA - timedelta(days=1)}]
        compras = [{'id': 'c1', 'referencia_externa': 'MAR-1', 'origem': 'site', 'valor_centavos': 5990,
                    'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=5)}]
        visao = _visao_com_pessoa(interacoes=interacoes, compras=compras)
        resultado = intel.calcular_score(visao, agora=AGORA)
        self.assertEqual(resultado['versao'], intel.VERSAO_SCORE)
        for dim in ('engagement', 'commercial_intent', 'relationship_value', 'reorder_signal', 'data_quality'):
            self.assertIn(dim, resultado['dimensoes'])
            self.assertTrue(resultado['dimensoes'][dim]['explicacao'], f'dimensão {dim} sem explicação')
        self.assertIsInstance(resultado['score_geral'], float)

    def test_score_sem_dados_suficientes_fica_not_enough_data(self):
        resultado = intel.calcular_score(_visao_vazia(), agora=AGORA)
        self.assertEqual(resultado['score_geral'], 'NOT_ENOUGH_DATA')
        self.assertEqual(resultado['dimensoes']['engagement']['valor'], 'NOT_ENOUGH_DATA')
        self.assertEqual(resultado['dimensoes']['relationship_value']['valor'], 'NOT_ENOUGH_DATA')

    def test_relacionamento_sem_pedido_nao_calcula_reorder_signal(self):
        visao = _visao_com_pessoa()
        resultado = intel.calcular_score(visao, agora=AGORA)
        self.assertEqual(resultado['dimensoes']['reorder_signal']['valor'], 'NOT_ENOUGH_DATA')

    def test_ausencia_de_dado_nunca_vira_score_negativo(self):
        resultado = intel.calcular_score(_visao_vazia(), agora=AGORA)
        for dim in resultado['dimensoes'].values():
            if isinstance(dim['valor'], (int, float)):
                self.assertGreaterEqual(dim['valor'], 0)


class Segmentacao(unittest.TestCase):
    def test_segmentos_multiplos_nao_sao_exclusivos(self):
        compras = [
            {'id': 'c1', 'referencia_externa': 'A', 'origem': 'site', 'valor_centavos': 100,
             'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=200)},
            {'id': 'c2', 'referencia_externa': 'B', 'origem': 'site', 'valor_centavos': 100,
             'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=150)},
        ]
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'msg', 'classificacao': None,
                       'interesse': None, 'criado_em': AGORA - timedelta(days=150)}]
        lead = _lead(categoria_contato='distribuidor')
        visao = _visao_com_pessoa(lead=lead, compras=compras, interacoes=interacoes)
        sinais = sinais_mod.extrair_sinais(visao, agora=AGORA)
        segmentos = intel.segmentar(visao, sinais, agora=AGORA)
        nomes = {s['segmento'] for s in segmentos}
        self.assertIn('repeat_customer', nomes)
        self.assertIn('inactive_customer', nomes)
        self.assertIn('strategic_partner', nomes)

    def test_novo_relacionamento_sem_compra(self):
        lead = _lead(criado_em=AGORA - timedelta(days=5))
        visao = _visao_com_pessoa(lead=lead)
        sinais = sinais_mod.extrair_sinais(visao, agora=AGORA)
        segmentos = {s['segmento'] for s in intel.segmentar(visao, sinais, agora=AGORA)}
        self.assertIn('new_relationship', segmentos)


class Recompra(unittest.TestCase):
    def test_reorder_due_gera_segmento_score_alto_e_oportunidade(self):
        lead = _lead(proxima_recompra_em=AGORA - timedelta(days=3))
        compras = [{'id': 'c1', 'referencia_externa': 'A', 'origem': 'site', 'valor_centavos': 5990,
                    'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=33)}]
        visao = _visao_com_pessoa(lead=lead, compras=compras)
        sinais = sinais_mod.extrair_sinais(visao, agora=AGORA)
        score = intel.calcular_score(visao, sinais=sinais, agora=AGORA)
        segmentos = intel.segmentar(visao, sinais, agora=AGORA)
        oportunidades = intel.detectar_oportunidades(visao, sinais, score, segmentos, LEAD_ID, agora=AGORA)
        self.assertEqual(score['dimensoes']['reorder_signal']['valor'], 90)
        self.assertIn('reorder_due', {s['segmento'] for s in segmentos})
        self.assertTrue(any(o['type'] == 'provavel_recompra' and o['recommended_action'] == 'CONTACT_REORDER'
                             for o in oportunidades))


class InteresseSemCompra(unittest.TestCase):
    def test_interesse_alto_sem_pedido_gera_sampling_interest_e_oportunidade(self):
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'msg', 'classificacao': None,
                       'interesse': 'alto', 'criado_em': AGORA - timedelta(days=1)}]
        visao = _visao_com_pessoa(interacoes=interacoes)
        sinais = sinais_mod.extrair_sinais(visao, agora=AGORA)
        score = intel.calcular_score(visao, sinais=sinais, agora=AGORA)
        segmentos = intel.segmentar(visao, sinais, agora=AGORA)
        self.assertIn('sampling_interest', {s['segmento'] for s in segmentos})
        oportunidades = intel.detectar_oportunidades(visao, sinais, score, segmentos, LEAD_ID, agora=AGORA)
        self.assertTrue(any(o['type'] == 'interesse_sem_conversao' and o['recommended_action'] == 'FOLLOW_UP_SAMPLE'
                             for o in oportunidades))


class OportunidadePorSku(unittest.TestCase):
    def test_sku_com_recompra_observada_gera_oportunidade_com_sku(self):
        produtos = [{'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Gengibre', 'categoria': 'bebida',
                     'encontrado_no_catalogo': True, 'quantidade_pedidos': 2,
                     'primeira_compra': AGORA - timedelta(days=60), 'ultima_compra': AGORA - timedelta(days=5),
                     'recompra': True}]
        visao = _visao_com_pessoa(produtos=produtos)
        sinais = sinais_mod.extrair_sinais(visao, agora=AGORA)
        score = intel.calcular_score(visao, sinais=sinais, agora=AGORA)
        segmentos = intel.segmentar(visao, sinais, agora=AGORA)
        oportunidades = intel.detectar_oportunidades(visao, sinais, score, segmentos, LEAD_ID, agora=AGORA)
        oport_sku = next((o for o in oportunidades if o['type'] == 'sku_com_padrao_de_recompra'), None)
        self.assertIsNotNone(oport_sku)
        self.assertEqual(oport_sku['sku'], 'CORDIAL-GENGIBRE-500ML')


class Recomendacao(unittest.TestCase):
    def test_gera_recomendacao_ordenada_por_prioridade(self):
        oportunidades = [
            {'type': 'a', 'priority': 'normal', 'confidence': 0.5, 'evidence': ['e1'],
             'relationship_id': LEAD_ID, 'sku': None, 'recommended_action': 'FOLLOW_UP_PIPELINE'},
            {'type': 'b', 'priority': 'alta', 'confidence': 0.9, 'evidence': ['e2'],
             'relationship_id': LEAD_ID, 'sku': None, 'recommended_action': 'CONTACT_REORDER'},
        ]
        recomendacoes = intel.gerar_next_best_actions(oportunidades, agora=AGORA)
        self.assertEqual(recomendacoes[0]['action'], 'CONTACT_REORDER')
        self.assertLessEqual(len(recomendacoes), intel.MAX_RECOMENDACOES)

    def test_sem_oportunidade_devolve_no_action_explicito(self):
        recomendacoes = intel.gerar_next_best_actions([], agora=AGORA)
        self.assertEqual(recomendacoes, [{
            'action': 'NO_ACTION', 'reason': 'Nenhuma oportunidade com evidência suficiente foi detectada.',
            'evidence': [], 'confidence': 1.0, 'generated_at': AGORA.isoformat(),
            'relationship_id': None, 'priority': 'baixa',
        }])

    def test_toda_recomendacao_real_carrega_evidencia_nao_vazia(self):
        oportunidades = [{'type': 'a', 'priority': 'alta', 'confidence': 0.8, 'evidence': ['fato real'],
                           'relationship_id': LEAD_ID, 'sku': None, 'recommended_action': 'REVIEW_PARTNER'}]
        recomendacoes = intel.gerar_next_best_actions(oportunidades, agora=AGORA)
        self.assertTrue(recomendacoes[0]['evidence'])
        self.assertIn(recomendacoes[0]['action'], intel.ACOES_RECOMENDADAS)


class AprovacaoHumanaPreservada(unittest.TestCase):
    def test_conversao_para_fila_sempre_exige_aprovacao(self):
        recomendacao = {'action': 'CONTACT_REORDER', 'reason': 'x', 'evidence': ['y'], 'confidence': 0.8,
                         'relationship_id': LEAD_ID, 'priority': 'alta'}
        item = intel.recomendacao_para_item_fila(recomendacao, lead_id=LEAD_ID)
        self.assertTrue(item['exige_aprovacao'])
        self.assertEqual(item['lead_id'], LEAD_ID)
        self.assertIn(item['prioridade'], intel.PRIORIDADES)

    def test_prioridade_desconhecida_cai_para_normal_nunca_quebra(self):
        recomendacao = {'action': 'NO_ACTION', 'reason': 'x', 'evidence': [], 'confidence': 1.0,
                         'relationship_id': None, 'priority': 'inexistente'}
        item = intel.recomendacao_para_item_fila(recomendacao)
        self.assertEqual(item['prioridade'], 'normal')


class IdentidadeAmbiguaEDadosUnknown(unittest.TestCase):
    def test_visao_vazia_nunca_gera_excecao_nem_inventa_dado(self):
        visao = _visao_vazia()
        resultado = intel.inteligencia_do_relacionamento(visao, ESTAB_ID, agora=AGORA)
        self.assertEqual(resultado['score']['score_geral'], 'NOT_ENOUGH_DATA')
        self.assertEqual(resultado['segments'], [])
        self.assertEqual(resultado['next_best_actions'][0]['action'], 'NO_ACTION')

    def test_modulo_nunca_funde_identidade(self):
        import inspect
        for modulo in (intel, sinais_mod):
            codigo = inspect.getsource(modulo)
            for proibido in ('INSERT INTO', 'UPDATE ', 'DELETE FROM', 'obter_ou_criar_contato_central'):
                self.assertNotIn(proibido, codigo)
            # registrar_item_fila/avancar_estado_fila só podem ser CITADOS em
            # comentário/docstring (explicando compatibilidade), nunca CHAMADOS.
            for funcao in ('registrar_item_fila', 'avancar_estado_fila'):
                self.assertNotIn(funcao + '(', codigo)


class CompatibilidadeComPayloadAntigo(unittest.TestCase):
    def test_360_sem_chaves_novas_nao_quebra(self):
        # Simula um payload "antigo" que não tem, por exemplo, 'products'
        # ou 'data_quality' completos -- tudo deve degradar via .get(),
        # nunca KeyError.
        visao_minima = {'identity': {}, 'commercial': {}, 'behavior': {}, 'derived_metrics': {},
                         'geography': {}, 'organization': None}
        sinais = sinais_mod.extrair_sinais(visao_minima, agora=AGORA)
        self.assertEqual(sinais, [])
        score = intel.calcular_score(visao_minima, sinais=sinais, agora=AGORA)
        self.assertEqual(score['score_geral'], 'NOT_ENOUGH_DATA')
        segmentos = intel.segmentar(visao_minima, sinais, agora=AGORA)
        self.assertEqual(segmentos, [])


class NenhumaAcaoExterna(unittest.TestCase):
    def test_nenhum_modulo_chama_openai_smtplib_ou_transporte(self):
        import inspect
        for modulo in (intel, sinais_mod):
            codigo = inspect.getsource(modulo)
            for proibido in ('OpenAI(', 'smtplib', 'requests.', 'whatsapp', 'gmail', '.propor('):
                self.assertNotIn(proibido, codigo.lower() if proibido.islower() else codigo)


class RotaLeitura(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        app = Flask(__name__)
        intel.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        resp = app.test_client().get(f'/api/admin/mi/relacionamento/{LEAD_ID}/inteligencia')
        self.assertEqual(resp.status_code, 401)

    def test_nenhuma_rota_de_escrita_e_registrada(self):
        app = Flask(__name__)
        intel.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})

    def test_relacionamento_inexistente_devolve_404(self):
        cur = MagicMock()
        cur.__enter__ = Mock(return_value=cur)
        cur.__exit__ = Mock(return_value=False)
        cur.fetchone.side_effect = [None, None]
        conn = MagicMock()
        conn.cursor.return_value = cur
        app = Flask(__name__)
        intel.registrar_rotas_leitura(app, lambda: conn, lambda: True)
        resp = app.test_client().get(f'/api/admin/mi/relacionamento/{LEAD_ID}/inteligencia')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
