"""Rotas reais extraídas sem importar main nem iniciar serviços de produção."""
import ast
import hashlib
import hmac
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request
import whatsapp_aprovacoes
from test_whatsapp_aprovacoes import Banco as BancoAprovacoes
from test_whatsapp_meta import Banco as BancoInbox, payload


class Routes(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch('requests.sessions.Session.request', side_effect=AssertionError('rede proibida')),
            patch.dict(os.environ, {'META_APP_SECRET': 'segredo-sintetico', 'EMAIL_ENVIOS_PAUSADOS': 'true'}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = Flask(__name__)
        self.inbox = BancoInbox()
        self.queue = BancoAprovacoes()
        self.ns = dict(app=self.app, request=request, jsonify=jsonify, os=os,
                       META_WEBHOOK_VERIFY_TOKEN='verificacao-sintetica',
                       get_db_connection=self.inbox,
                       validar_admin_omnichannel=lambda: request.headers.get('X-Admin-Key') == 'admin-sintetico',
                       registrar_interacao_omnichannel=Mock(return_value={'success': True, 'interacao': {'id': 'i'}}),
                       processar_interacao_omnichannel_crm=Mock(return_value={'success': True}),
                       gerar_resposta_sugerida_omnichannel=Mock(return_value={'success': True}))
        tree = ast.parse(Path('main.py').read_text())
        names = {'webhook_meta', 'admin_decidir_resposta_omnichannel', 'admin_enviar_resposta_omnichannel'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), self.ns)
        self.http = self.app.test_client()
        self.webhook = next(rule.rule for rule in self.app.url_map.iter_rules() if rule.endpoint == 'webhook_meta')
        self.message = payload([{'id': 'wamid.synthetic', 'from': '5598999999999',
                                 'type': 'text', 'text': {'body': 'Teste sintético'}}])
        self.message['object'] = 'whatsapp_business_account'

    def post(self, data=None, valid=True):
        body = json.dumps(self.message if data is None else data).encode()
        signature = hmac.new(b'segredo-sintetico', body, hashlib.sha256).hexdigest()
        return self.http.post(self.webhook, data=body, content_type='application/json',
                              headers={'X-Hub-Signature-256': 'sha256=' + (signature if valid else 'invalid')})

    def test_assinatura_invalida_nao_processa(self):
        self.assertEqual(self.post(valid=False).status_code, 403)
        self.ns['registrar_interacao_omnichannel'].assert_not_called()

    def test_entrada_assinada_crm_proposta_redelivery_sem_transporte(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 200)
        for name in ('registrar_interacao_omnichannel', 'processar_interacao_omnichannel_crm', 'gerar_resposta_sugerida_omnichannel'):
            self.ns[name].assert_called_once()
        self.assertTrue(all(self.inbox.rows.values()))

    def test_falha_crm_retorna_503_e_retomada_conclui(self):
        self.ns['processar_interacao_omnichannel_crm'].side_effect = [RuntimeError('falha sintética'), {'success': True}]
        self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.post().status_code, 200)
        self.ns['gerar_resposta_sugerida_omnichannel'].assert_called_once()

    def test_admin_autenticacao_aprovacao_persistida_pausa_impede_execucao(self):
        self.ns['get_db_connection'] = self.queue
        headers = {'X-Admin-Key': 'admin-sintetico'}
        path = '/api/admin/omnichannel/respostas/f'
        with patch.object(whatsapp_aprovacoes, 'canal_resposta', return_value='whatsapp'):
            self.assertEqual(self.http.patch(path, json={'acao': 'aprovar'}).status_code, 401)
            approved = self.http.patch(path, headers=headers, json={'acao': 'aprovar', 'resposta': 'Texto editado'})
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(self.queue.fila['status'], 'aprovada')
            self.assertEqual(self.queue.fila['resposta_sugerida'], 'Texto editado')
            blocked = self.http.post(path + '/enviar', headers=headers)
            self.assertEqual(blocked.status_code, 409)
            self.assertTrue(blocked.json['bloqueado'])
            self.assertEqual(self.queue.fila['status'], 'aprovada')
            self.assertEqual(self.queue.auditoria, ['aprovada', 'bloqueada'])


if __name__ == '__main__':
    unittest.main()
