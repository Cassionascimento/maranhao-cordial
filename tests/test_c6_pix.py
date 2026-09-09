"""Testes offline: configuração, adapter, conciliação e rotas extraídas via AST."""
import ast
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
import c6_pix as c6

TXID = 'a' * 32

class C6Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cert = Path(self.tmp.name) / 'cert'; cert.write_text('fake')
        key = Path(self.tmp.name) / 'key'; key.write_text('fake')
        self.config = c6.C6Config.from_env({'C6_CLIENT_ID': 'secret-id', 'C6_CLIENT_SECRET': 'secret-value',
            'C6_PIX_KEY': 'secret-pix', 'C6_CERT_PATH': str(cert), 'C6_KEY_PATH': str(key)})

    def test_default_disabled_and_redacted(self):
        self.assertTrue(self.config.status()['ready'])
        self.assertFalse(self.config.status()['charges_enabled'])
        self.assertNotIn('secret', repr(self.config))

    def test_create_blocked_before_network(self):
        transport = Mock()
        with self.assertRaises(c6.C6Error):
            c6.C6Client(self.config, transport).criar(TXID, {})
        self.assertFalse(transport.mock_calls)

    def test_no_inherited_production_credentials(self):
        for environment in ['production', 'homologacao']:
            with self.subTest(environment=environment), self.assertRaises(c6.C6Error):
                c6.C6Config.from_env({'C6_ENVIRONMENT': environment, 'C6_CLIENT_ID': 'legacy'})

    def test_endpoint_validation(self):
        for url in ['http://baas-api-sandbox.c6bank.info', 'https://c6bank.info.evil.example',
                    'https://x.c6bank.info?secret=foo', 'https://user:pass@x.c6bank.info', 'https://baas-api.c6bank.info']:
            with self.subTest(url=url), self.assertRaises(c6.C6Error):
                c6.C6Config.from_env({'C6_AUTH_URL': url})

    def test_prod_explicit_approval(self):
        cfg = replace(self.config, environment='production', auth_url='https://api.c6bank.com.br/auth',
                      pix_base_url='https://api.c6bank.com.br/pix')
        with self.assertRaises(c6.C6Error): cfg.validate()
        replace(cfg, production_approved=True).validate()

    def test_missing_mtls_not_ready(self):
        self.assertFalse(replace(self.config, cert_path='/does/not/exist').status()['ready'])

    def test_bad_txid_no_network(self):
        for txid in ['', '../secret', 'a'*36, 'a'*25, None]:
            transport = Mock()
            with self.subTest(txid=txid), self.assertRaises(c6.C6Error):
                c6.C6Client(self.config, transport).consultar(txid)
            self.assertFalse(transport.mock_calls)

    def test_no_secret_error_or_redirect(self):
        transport = Mock()
        transport.post.return_value.status_code = 302
        transport.post.return_value.text = 'secret-bank-body'
        with self.assertRaises(c6.C6Error) as caught: c6.C6Client(self.config, transport).access_token()
        self.assertNotIn('secret', str(caught.exception))
        self.assertFalse(transport.post.call_args.kwargs['allow_redirects'])

    def test_consulta(self):
        transport = Mock()
        transport.post.return_value.status_code = 200
        transport.post.return_value.json.return_value = {'access_token': 'token'}
        transport.get.return_value.status_code = 200
        transport.get.return_value.json.return_value = {'txid': TXID, 'status': 'ATIVA'}
        self.assertEqual(c6.C6Client(self.config, transport).consultar(TXID)['status'], 'ATIVA')
        self.assertEqual(transport.get.call_args.kwargs['cert'], (self.config.cert_path, self.config.key_path))

    def test_webhook_batch_dedup(self):
        self.assertEqual(c6.extrair_txids({'pix': [{'txid': TXID}, {'txid': TXID}, {'txid': 'b'*32}]}), [TXID, 'b'*32])

    def test_invalid_webhook(self):
        for event in [[], {'pix': 'invalid'}, {'pix': [{}]*101}]:
            with self.subTest(event=event), self.assertRaises(c6.C6Error): c6.extrair_txids(event)

    def test_payment_checks(self):
        pedido = {'c6_txid': TXID, 'amount': 5990, 'payment_origin': 'c6'}
        consulta = {'txid': TXID, 'status': 'CONCLUIDA', 'valor': {'original': '59.90'}}
        self.assertTrue(c6.pagamento_confirmado(pedido, consulta))
        for changed in ({'txid': 'b'*32}, {'status': 'ATIVA'}, {'valor': {'original': '1.00'}}, {'valor': {'original': 'NaN'}}):
            self.assertFalse(c6.pagamento_confirmado(pedido, dict(consulta, **changed)))
        self.assertFalse(c6.pagamento_confirmado(dict(pedido, payment_origin='pagarme'), consulta))

    def test_persistent_payment_transition_and_duplicate(self):
        consulta = {'txid': TXID, 'status': 'CONCLUIDA', 'valor': {'original': '59.90'}}
        for old, changed in [('aguardando_pagamento', True), ('pago', False)]:
            conn = Mock(); conn.__enter__ = Mock(return_value=conn); conn.__exit__ = Mock()
            cur = Mock(); cur.__enter__ = Mock(return_value=cur); cur.__exit__ = Mock()
            conn.cursor.return_value = cur
            cur.fetchall.return_value = [('MAR-1', 5990, old, 'c6', TXID)]
            result = c6.reconciliar_persistente(TXID, consulta, lambda: conn)
            self.assertEqual(result['changed'], changed)
            self.assertTrue(result['paid'])
            self.assertIn('FOR UPDATE', cur.execute.call_args_list[0].args[0])
            self.assertEqual(cur.execute.call_count, 3 if changed else 2)
            conn.close.assert_called_once()

    def test_checkout_gate_before_mutation(self):
        tree = ast.parse(Path('main.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'criar_checkout_c6')
        node.decorator_list = []
        client = Mock(); client.config.validate.side_effect = c6.C6Error('disabled')
        env = {'C6Client': lambda: client, 'C6Error': c6.C6Error, 'jsonify': lambda x: x}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), env)
        # No request, globals or network provided: the gate must precede them.
        result, status = env['criar_checkout_c6']()
        self.assertEqual(status, 503)
        self.assertFalse(result['success'])

    def test_routes_compatible(self):
        tree = ast.parse(Path('main.py').read_text())
        routes = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'route' and dec.args and isinstance(dec.args[0], ast.Constant):
                        routes[node.name] = dec.args[0].value
        self.assertEqual(routes['webhook_c6'], '/webhooks/c6')
        self.assertEqual(routes['status_c6'], '/api/c6/status')
        self.assertEqual(routes['criar_checkout_c6'], '/api/c6/pix/checkout')
        self.assertEqual(routes['consultar_cobranca_c6'], '/api/c6/pix/<txid>')

if __name__ == '__main__': unittest.main()
