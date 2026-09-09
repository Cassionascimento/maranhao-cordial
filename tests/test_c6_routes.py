"""Homologação HTTP sintética: nenhum socket, cobrança ou banco real."""
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from c6_pix import C6Error
from c6_routes import registrar_rotas_c6

TXID = 'a' * 32


class Routes(unittest.TestCase):
    def setUp(self):
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('rede proibida'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.db = Mock(side_effect=AssertionError('banco real proibido'))
        self.bank = Mock()
        self.bank.config.pix_key = 'chave-sintetica'
        self.bank.criar.return_value = {'txid': TXID, 'status': 'ATIVA', 'devedor': 'SEGREDO'}
        self.app = Flask(__name__)
        self.routes = registrar_rotas_c6(self.app, self.db, lambda: 5990, client_factory=lambda: self.bank)
        self.http = self.app.test_client()
        self.order = {'quantidade': 2, 'endereco': 'Endereço sintético', 'cliente_email': 'teste@example.invalid'}

    def checkout(self, data=None):
        return self.http.post('/api/c6/pix/checkout', json=self.order if data is None else data,
                              headers={'Idempotency-Key': 'homologacao-sintetica-001'})

    def test_gate_precede_request_preco_banco_e_transporte(self):
        self.bank.config.validate.side_effect = C6Error('desabilitado')
        self.routes.preco = Mock(side_effect=AssertionError('preço não deve ser lido'))
        self.assertEqual(self.checkout().status_code, 503)
        self.bank.config.validate.assert_called_once_with(create=True)
        self.db.assert_not_called()
        self.bank.criar.assert_not_called()

    def test_invalidos_nao_reservam(self):
        for quantity in (True, 0, -1, '1.5', [], 1.2):
            self.assertEqual(self.checkout(dict(self.order, quantidade=quantity)).status_code, 400)
        self.db.assert_not_called()
        self.bank.criar.assert_not_called()

    def test_checkout_persiste_antes_do_adapter_e_retorna_allowlist(self):
        events = []
        def reserve(*args):
            events.append('reserva')
            self.assertEqual(args[2]['amount'], 11980)
            return {'new': True, 'code': 'MAR-SINTETICO', 'txid': TXID}
        def create(*args):
            events.append('adapter')
            self.assertEqual(events, ['reserva', 'adapter'])
            self.assertEqual(args[1]['valor']['original'], '119.80')
            return {'txid': TXID, 'status': 'ATIVA', 'devedor': 'SEGREDO'}
        self.bank.criar.side_effect = create
        with patch('c6_routes.iniciar_checkout', side_effect=reserve), \
             patch('c6_routes.reconciliar_persistente') as reconcile, \
             patch('c6_routes.concluir_checkout') as finish:
            response = self.checkout()
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('SEGREDO', response.get_data(as_text=True))
        reconcile.assert_called_once()
        finish.assert_called_once()

    def test_retry_incerto_nao_repete_cobranca(self):
        with patch('c6_routes.iniciar_checkout', return_value={'new': False, 'code': 'MAR-SINTETICO', 'txid': TXID, 'response': None}):
            self.assertEqual(self.checkout().status_code, 202)
        self.bank.criar.assert_not_called()

    def test_retry_concluido_reutiliza_resposta_sem_cobranca(self):
        with patch('c6_routes.iniciar_checkout', return_value={'new': False, 'code': 'MAR-SINTETICO', 'txid': TXID,
                   'response': {'status': 'ATIVA', 'devedor': 'SEGREDO'}}):
            response = self.checkout()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('SEGREDO', response.get_data(as_text=True))
        self.bank.criar.assert_not_called()

    def test_timeout_nao_finge_sucesso_nem_repete(self):
        self.bank.criar.side_effect = TimeoutError('SEGREDO')
        with patch('c6_routes.iniciar_checkout', return_value={'new': True, 'code': 'MAR-SINTETICO', 'txid': TXID}), \
             patch('c6_routes.concluir_checkout') as finish:
            response = self.checkout()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('SEGREDO', response.get_data(as_text=True))
        self.bank.criar.assert_called_once()
        finish.assert_not_called()

    def test_webhook_fechado_sem_verificador_homologado(self):
        self.assertEqual(self.http.post('/webhooks/c6', json={'txid': TXID}).status_code, 503)
        self.routes.webhook_homologado = True
        self.assertEqual(self.http.post('/webhooks/c6', json={'txid': TXID}).status_code, 503)
        self.db.assert_not_called()
        self.bank.consultar.assert_not_called()

    def test_webhook_autenticado_sintetico_consulta_e_deduplica(self):
        self.routes.webhook_homologado = True
        self.routes.webhook_verifier = lambda req: req.headers.get('X-Synthetic') == 'ok'
        self.bank.consultar.return_value = {'txid': TXID, 'status': 'CONCLUIDA', 'valor': {'original': '119.80'}}
        with patch.object(self.routes, '_pedido', return_value=('MAR-SINTETICO', 11980)), \
             patch('c6_routes.reconciliar_persistente', return_value={'found': True, 'paid': True}) as reconcile:
            self.assertEqual(self.http.post('/webhooks/c6', json={'txid': TXID}).status_code, 401)
            response = self.http.post('/webhooks/c6', headers={'X-Synthetic': 'ok'},
                                      json={'pix': [{'txid': TXID}, {'txid': TXID}]})
        self.assertEqual(response.status_code, 200)
        self.bank.consultar.assert_called_once_with(TXID)
        reconcile.assert_called_once_with(TXID, self.bank.consultar.return_value, self.db)

    def test_webhook_falha_pede_redelivery(self):
        self.routes.webhook_homologado = True
        self.routes.webhook_verifier = lambda req: True
        with patch.object(self.routes, '_pedido', side_effect=RuntimeError('SEGREDO')):
            response = self.http.post('/webhooks/c6', json={'txid': TXID})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('SEGREDO', response.get_data(as_text=True))

    def test_txid_invalido_e_desconhecido_nao_consultam_banco_externo(self):
        self.assertEqual(self.http.get('/api/c6/pix/invalid').status_code, 400)
        with patch.object(self.routes, '_pedido', return_value=None):
            self.assertEqual(self.http.get('/api/c6/pix/' + TXID).status_code, 404)
        self.bank.consultar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
