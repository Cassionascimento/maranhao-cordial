"""P1B -- Customer/Partner 360: agrega leads_crm/mi_estabelecimentos/
interacoes_omnichannel/pedidos/compras_relacionamento/acoes_comerciais_
propostas/formulários/mi_eventos, sem nenhuma tabela nova e sem nenhuma
segunda camada de identidade. Só leitura."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

from flask import Flask

import mi_relacionamento_360 as r

AGORA = datetime(2026, 9, 20, tzinfo=timezone.utc)
LEAD_ID = '11111111-1111-1111-1111-111111111111'
ESTAB_ID = '22222222-2222-2222-2222-222222222222'


def _lead(**over):
    base = {'id': LEAD_ID, 'nome': 'Fulano', 'empresa': 'Bar do Fulano', 'email': 'fulano@bar.com',
            'telefone': '11999990000', 'instagram': None, 'cidade': 'São Luís', 'estado': 'MA',
            'origem': 'whatsapp', 'canal': 'whatsapp', 'categoria_contato': 'bartender', 'estagio': 'cliente',
            'status': 'ativo', 'prioridade': 'normal', 'valor_potencial_centavos': None,
            'receita_acumulada_centavos': 0, 'quantidade_compras': 0, 'ultima_compra_em': None,
            'proxima_recompra_em': None, 'motivo_perda': None, 'proximo_followup': None,
            'ultima_interacao_em': None, 'criado_em': AGORA - timedelta(days=100), 'atualizado_em': AGORA}
    base.update(over)
    return base


def _estab(**over):
    base = {'id': ESTAB_ID, 'nome': 'Bar do Fulano', 'tipo': 'bar', 'cidade': 'São Luís', 'uf': 'MA',
            'bairro': 'Centro', 'lead_id': LEAD_ID, 'criado_em': AGORA - timedelta(days=90)}
    base.update(over)
    return base


def _cur(fetchone=None, fetchall=None):
    cur = MagicMock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    cur.fetchone.side_effect = fetchone or []
    cur.fetchall.side_effect = fetchall or []
    return cur


class PessoaSemEstabelecimento(unittest.TestCase):
    def test_360_de_pessoa_sem_estabelecimento(self):
        cur = _cur(
            fetchone=[_lead(), None],  # lead encontrado, sem estabelecimento
            # identidades, interacoes, compras, pedidos, propostas, profissionais, degustacoes
            fetchall=[[], [], [], [], [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertIsNotNone(resultado)
        self.assertIsNone(resultado['organization'])
        self.assertEqual(resultado['identity']['pessoa']['id'], LEAD_ID)
        self.assertEqual(resultado['relationship']['pessoa_estabelecimento'], 'UNKNOWN')


class EstabelecimentoSemPessoa(unittest.TestCase):
    def test_360_de_estabelecimento_sem_lead_associado(self):
        cur = _cur(
            fetchone=[None, _estab(lead_id=None)],  # não é lead; é estabelecimento sem lead_id
            fetchall=[[]],  # eventos do estabelecimento (sem lead -> nenhuma outra consulta roda)
        )
        resultado = r.relacionamento_360(cur, ESTAB_ID, agora=AGORA)
        self.assertIsNotNone(resultado)
        self.assertIsNone(resultado['identity']['pessoa'])
        self.assertEqual(resultado['organization']['id'], ESTAB_ID)
        self.assertEqual(resultado['relationship']['pessoa_estabelecimento'], 'UNKNOWN')


class PessoaEEstabelecimento(unittest.TestCase):
    def test_360_completo_liga_pessoa_e_estabelecimento(self):
        cur = _cur(
            fetchone=[_lead(), _estab()],
            fetchall=[[], [], [], [], [], [], [], []],  # identidades, interacoes, compras, pedidos, propostas, profissionais, degustacoes, eventos
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertEqual(resultado['organization']['id'], ESTAB_ID)
        self.assertEqual(resultado['relationship']['pessoa_estabelecimento'], 'DIRECT')


class RelacionamentoMulticanal(unittest.TestCase):
    def test_canais_utilizados_combina_interacoes_e_identidades_externas(self):
        interacoes = [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'mensagem',
                       'classificacao': None, 'interesse': 'alto', 'criado_em': AGORA - timedelta(days=2)}]
        identidades = [{'canal': 'instagram', 'identificador_externo': 'bardofulano', 'username_publico': 'bardofulano',
                        'status': 'resolvida', 'criterio_vinculo': 'instagram_exato', 'confianca': 95.0,
                        'criado_em': AGORA - timedelta(days=50)}]
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[identidades, interacoes, [], [], [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertEqual(set(resultado['behavior']['canais_utilizados']), {'whatsapp', 'instagram'})
        self.assertEqual(resultado['relationship']['pessoa_interacoes'], 'DIRECT')


class PedidoSemSkuHistorico(unittest.TestCase):
    def test_pedido_historico_sem_sku_nunca_inventa_produto(self):
        pedidos = [{'codigo': 'MAR-1', 'status': 'pago', 'valor_centavos': 5990, 'quantidade': 1,
                    'sku': None, 'criado_em': AGORA - timedelta(days=200)}]
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[[], [], [], pedidos, [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertEqual(resultado['products'], [])
        self.assertEqual(resultado['derived_metrics']['products_purchased'], [])


class PedidoComSku(unittest.TestCase):
    def test_pedido_com_sku_aparece_em_products(self):
        pedidos = [{'codigo': 'MAR-2', 'status': 'pago', 'valor_centavos': 5990, 'quantidade': 1,
                    'sku': 'CORDIAL-GENGIBRE-500ML', 'criado_em': AGORA - timedelta(days=5)}]
        produto = {'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Cordial de Gengibre', 'categoria': 'bebida'}
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[[], [], [], pedidos, [], [], [], [produto]],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertEqual(len(resultado['products']), 1)
        self.assertEqual(resultado['products'][0]['produto_nome'], 'Cordial de Gengibre')
        self.assertFalse(resultado['products'][0]['recompra'])


class MultiplosSkus(unittest.TestCase):
    def test_multiplos_skus_sao_agrupados_separadamente(self):
        pedidos = [
            {'codigo': 'MAR-3', 'status': 'pago', 'valor_centavos': 5990, 'quantidade': 1,
             'sku': 'CORDIAL-GENGIBRE-500ML', 'criado_em': AGORA - timedelta(days=30)},
            {'codigo': 'MAR-4', 'status': 'pago', 'valor_centavos': 6990, 'quantidade': 1,
             'sku': 'CORDIAL-GENGIBRE-500ML', 'criado_em': AGORA - timedelta(days=5)},
            {'codigo': 'MAR-5', 'status': 'pago', 'valor_centavos': 4990, 'quantidade': 2,
             'sku': 'CORDIAL-HIBISCO-500ML', 'criado_em': AGORA - timedelta(days=10)},
        ]
        produtos = [{'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Gengibre', 'categoria': 'bebida'},
                    {'sku': 'CORDIAL-HIBISCO-500ML', 'produto_nome': 'Hibisco', 'categoria': 'bebida'}]
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[[], [], [], pedidos, [], [], [], produtos],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertEqual(len(resultado['products']), 2)
        gengibre = next(p for p in resultado['products'] if p['sku'] == 'CORDIAL-GENGIBRE-500ML')
        self.assertEqual(gengibre['quantidade_pedidos'], 2)
        self.assertTrue(gengibre['recompra'])
        self.assertEqual(resultado['derived_metrics']['orders_by_sku']['CORDIAL-HIBISCO-500ML'], 1)


class ClienteSemPedido(unittest.TestCase):
    def test_sem_pedido_nem_compra_metricas_ficam_not_enough_data(self):
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[[], [], [], [], [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        m = resultado['derived_metrics']
        self.assertEqual(m['total_orders'], 0)
        self.assertEqual(m['average_order_value_centavos'], 'NOT_ENOUGH_DATA')
        self.assertEqual(m['days_since_last_order'], 'NOT_ENOUGH_DATA')
        self.assertEqual(m['reorder_count'], 'NOT_ENOUGH_DATA')


class ClienteComRecompra(unittest.TestCase):
    def test_multiplas_compras_calcula_reorder_count_e_ticket_medio(self):
        compras = [
            {'id': 'c1', 'referencia_externa': 'MAR-1', 'origem': 'site', 'valor_centavos': 5990,
             'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=60)},
            {'id': 'c2', 'referencia_externa': 'MAR-2', 'origem': 'site', 'valor_centavos': 7990,
             'quantidade_itens': 1, 'status': 'confirmada', 'comprado_em': AGORA - timedelta(days=10)},
        ]
        cur = _cur(
            fetchone=[_lead(), None],
            fetchall=[[], [], compras, [], [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        m = resultado['derived_metrics']
        self.assertEqual(m['total_orders'], 2)
        self.assertEqual(m['reorder_count'], 1)
        self.assertEqual(m['total_revenue_centavos'], 13980)
        self.assertEqual(m['average_order_value_centavos'], 6990)
        self.assertEqual(m['days_since_last_order'], 10)


class ComportamentoSemIdentidade(unittest.TestCase):
    def test_eventos_do_estabelecimento_aparecem_mesmo_sem_pessoa_associada(self):
        eventos = [{'tipo_evento': 'scan', 'canal': 'qr', 'sku': 'CORDIAL-GENGIBRE-500ML', 'unidade_id': 'u1',
                    'ocorrido_em': AGORA - timedelta(days=1), 'criado_em': AGORA - timedelta(days=1)}]
        cur = _cur(
            fetchone=[None, _estab(lead_id=None)],
            fetchall=[eventos],
        )
        resultado = r.relacionamento_360(cur, ESTAB_ID, agora=AGORA)
        self.assertIsNone(resultado['identity']['pessoa'])
        self.assertEqual(len(resultado['behavior']['eventos_do_estabelecimento']), 1)
        self.assertEqual(resultado['data_quality']['eventos_vinculo'],
                          'INFERRED ao estabelecimento, nunca à pessoa (mi_eventos não tem lead_id)')


class IdentidadeAmbiguaNuncaSofreFusaoDestrutiva(unittest.TestCase):
    def test_modulo_nunca_escreve_nada(self):
        import inspect
        codigo = inspect.getsource(r)
        for proibido in ('INSERT INTO', 'UPDATE ', 'DELETE FROM', 'DROP ', 'obter_ou_criar_contato_central'):
            self.assertNotIn(proibido, codigo)


class AusenciaDeDadosDevolveUnknown(unittest.TestCase):
    def test_id_que_nao_e_lead_nem_estabelecimento_devolve_none(self):
        cur = _cur(fetchone=[None, None])
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertIsNone(resultado)

    def test_id_mal_formado_devolve_none_sem_consultar_banco(self):
        cur = _cur()
        resultado = r.relacionamento_360(cur, 'nao-e-um-uuid', agora=AGORA)
        self.assertIsNone(resultado)
        cur.execute.assert_not_called()

    def test_campos_ausentes_sao_none_nunca_inventados(self):
        cur = _cur(
            fetchone=[_lead(instagram=None, valor_potencial_centavos=None, motivo_perda=None), None],
            fetchall=[[], [], [], [], [], [], []],
        )
        resultado = r.relacionamento_360(cur, LEAD_ID, agora=AGORA)
        self.assertIsNone(resultado['identity']['pessoa']['instagram'])
        self.assertIsNone(resultado['commercial']['motivo_perda'])
        self.assertEqual(resultado['geography']['territorio'], 'NOT_ENOUGH_DATA')


class RotaLeitura(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        app = Flask(__name__)
        r.registrar_rotas_leitura(app, MagicMock(), lambda: False)
        resp = app.test_client().get(f'/api/admin/mi/relacionamento/{LEAD_ID}/360')
        self.assertEqual(resp.status_code, 401)

    def test_relacionamento_inexistente_devolve_404(self):
        cur = _cur(fetchone=[None, None])
        cur.set_session = Mock()
        conn = MagicMock()
        conn.cursor.return_value = cur
        app = Flask(__name__)
        r.registrar_rotas_leitura(app, lambda: conn, lambda: True)
        resp = app.test_client().get(f'/api/admin/mi/relacionamento/{LEAD_ID}/360')
        self.assertEqual(resp.status_code, 404)

    def test_nenhuma_rota_de_escrita_e_registrada(self):
        app = Flask(__name__)
        r.registrar_rotas_leitura(app, MagicMock(), lambda: True)
        metodos = {m for regra in app.url_map.iter_rules() for m in regra.methods}
        self.assertFalse(metodos & {'POST', 'PUT', 'DELETE', 'PATCH'})


class NenhumaAcaoExterna(unittest.TestCase):
    def test_modulo_nunca_chama_openai_smtplib_ou_transporte_de_mensagem(self):
        import inspect
        codigo = inspect.getsource(r)
        for proibido in ('OpenAI(', 'smtplib', 'requests.', 'whatsapp_meta', 'gmail'):
            self.assertNotIn(proibido, codigo)


if __name__ == '__main__':
    unittest.main()
