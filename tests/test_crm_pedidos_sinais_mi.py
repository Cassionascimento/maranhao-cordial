"""ETAPA 4.9: CRM e pedidos/vendas -> mi_sinais.

Funções extraídas de main.py via AST (mesmo padrão de test_email_p0.py),
sem importar main.py inteiro nem seus efeitos de topo de arquivo. emitir()
é chamado via import local dentro de cada função (from mi_sinais import
emitir) -- por isso os testes interceptam mi_sinais.emitir diretamente.
"""
import re
import unittest
import uuid
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify, request
from psycopg2.extras import RealDictCursor
import test_email_p0 as f


class LeadCriado(unittest.TestCase):
    def _app(self, conn, autorizado=True):
        ns = dict(request=request, jsonify=jsonify, uuid=uuid, re=re, RealDictCursor=RealDictCursor,
                  validar_admin_request=lambda: autorizado, get_db_connection=lambda: conn)
        f.carregar_funcoes('main.py', ['admin_criar_lead_crm'], ns)
        app = Flask('crm-test')
        app.add_url_rule('/api/admin/crm/leads', view_func=ns['admin_criar_lead_crm'], methods=['POST'])
        return app.test_client()

    def _conn(self, lead_row):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = lead_row
        return conn

    def test_lead_criado_emite_fato_com_territorio_normalizado(self):
        conn = self._conn({'id': 'lead-1'})
        client = self._app(conn)
        with patch('uuid.uuid4', return_value=uuid.UUID('00000000-0000-0000-0000-000000000001')), \
             patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/admin/crm/leads', json={
                'tipo_lead': 'b2b', 'origem': 'site', 'estagio': 'novo',
                'cidade': 'São Luís', 'estado': 'ma', 'canal': 'site',
            })
        self.assertEqual(resposta.status_code, 201)
        emitir.assert_called_once()
        kwargs = emitir.call_args.kwargs
        self.assertEqual(kwargs['natureza'], 'fato')
        self.assertEqual(kwargs['origem'], 'crm')
        self.assertEqual(kwargs['tipo_evento'], 'lead_criado')
        self.assertEqual(kwargs['origem_id'], '00000000-0000-0000-0000-000000000001')
        self.assertEqual(kwargs['territorio_uf'], 'MA')
        self.assertEqual(kwargs['territorio_cidade'], 'São Luís')
        self.assertEqual(kwargs['payload'], {'tipo_lead': 'b2b', 'estagio': 'novo'})

    def test_estado_fora_do_padrao_nao_forca_territorio(self):
        conn = self._conn({'id': 'lead-1'})
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.post('/api/admin/crm/leads', json={
                'tipo_lead': 'b2b', 'origem': 'site', 'estagio': 'novo',
                'cidade': 'São Luís', 'estado': 'Maranhão',
            })
        self.assertIsNone(emitir.call_args.kwargs['territorio_uf'])

    def test_requisicao_invalida_nao_emite_nada(self):
        conn = self._conn({'id': 'lead-1'})
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/admin/crm/leads', json={'tipo_lead': 'invalido', 'origem': 'site'})
        self.assertEqual(resposta.status_code, 400)
        emitir.assert_not_called()

    def test_nao_autorizado_nao_emite_nada(self):
        conn = self._conn({'id': 'lead-1'})
        client = self._app(conn, autorizado=False)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/admin/crm/leads', json={'tipo_lead': 'b2b', 'origem': 'site'})
        self.assertEqual(resposta.status_code, 401)
        emitir.assert_not_called()


class LeadEstagioMudou(unittest.TestCase):
    def _app(self, conn):
        ns = dict(request=request, jsonify=jsonify, RealDictCursor=RealDictCursor,
                  validar_admin_request=lambda: True, get_db_connection=lambda: conn)
        f.carregar_funcoes('main.py', ['admin_atualizar_lead_crm'], ns)
        app = Flask('crm-test')
        app.add_url_rule('/api/admin/crm/leads/<lead_id>', view_func=ns['admin_atualizar_lead_crm'], methods=['PATCH'])
        return app.test_client()

    def _conn(self, estagio_anterior, lead_row):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'estagio': estagio_anterior}, lead_row]
        return conn

    def test_mudanca_de_estagio_emite_fato(self):
        conn = self._conn('novo', {'id': 'lead-1', 'estagio': 'proposta'})
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.patch('/api/admin/crm/leads/lead-1', json={'estagio': 'proposta'})
        self.assertEqual(resposta.status_code, 200)
        emitir.assert_called_once_with(
            unittest.mock.ANY, natureza='fato', origem='crm', tipo_evento='lead_estagio_mudou',
            origem_id='lead-1', discriminador='proposta',
            payload={'estagio_anterior': 'novo', 'estagio_novo': 'proposta'})

    def test_transicao_para_qualificacao_tambem_emite_lead_qualificado(self):
        conn = self._conn('novo', {'id': 'lead-1', 'estagio': 'qualificacao'})
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.patch('/api/admin/crm/leads/lead-1', json={'estagio': 'qualificacao'})
        self.assertEqual(emitir.call_count, 2)
        tipos = [c.kwargs['tipo_evento'] for c in emitir.call_args_list]
        self.assertEqual(tipos, ['lead_estagio_mudou', 'lead_qualificado'])

    def test_mesmo_estagio_nao_emite_nada(self):
        conn = self._conn('proposta', {'id': 'lead-1', 'estagio': 'proposta'})
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.patch('/api/admin/crm/leads/lead-1', json={'estagio': 'proposta'})
        emitir.assert_not_called()

    def test_atualizacao_sem_estagio_nao_consulta_nem_emite(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'id': 'lead-1', 'observacoes': 'novo texto'}
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.patch('/api/admin/crm/leads/lead-1', json={'observacoes': 'novo texto'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(cur.execute.call_count, 1)  # só o UPDATE, sem SELECT de estagio
        emitir.assert_not_called()

    def test_lead_inexistente_nao_emite_nada(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'estagio': 'novo'}, None]
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.patch('/api/admin/crm/leads/inexistente', json={'estagio': 'proposta'})
        self.assertEqual(resposta.status_code, 404)
        emitir.assert_not_called()


class PedidoCriado(unittest.TestCase):
    def _namespace(self, conn):
        ns = dict(uuid=uuid, get_db_connection=lambda: conn)
        f.carregar_funcoes('main.py', ['salvar_pedido_postgres'], ns)
        return ns

    def _conn(self, foi_criado):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (foi_criado,)
        return conn

    def test_pedido_novo_emite_fato(self):
        conn = self._conn(True)
        ns = self._namespace(conn)
        with patch('mi_sinais.emitir') as emitir:
            ns['salvar_pedido_postgres']({
                'code': 'MAR-1', 'amount': 5990, 'quantity': 1, 'payment_origin': 'c6',
                'status': 'aguardando_pagamento',
            })
        emitir.assert_called_once_with(
            unittest.mock.ANY, natureza='fato', origem='pedidos', tipo_evento='pedido_criado',
            origem_id='MAR-1', canal='c6', payload={'quantidade': 1, 'valor_centavos': 5990})

    def test_atualizacao_de_pedido_existente_nao_emite_pedido_criado(self):
        conn = self._conn(False)
        ns = self._namespace(conn)
        with patch('mi_sinais.emitir') as emitir:
            ns['salvar_pedido_postgres']({'code': 'MAR-1', 'amount': 5990, 'status': 'pago'})
        emitir.assert_not_called()

    def test_pedido_de_teste_nunca_emite_sinal(self):
        conn = self._conn(True)
        ns = self._namespace(conn)
        with patch('mi_sinais.emitir') as emitir:
            ns['salvar_pedido_postgres']({
                'code': 'MAR-TESTE-1', 'amount': 5990, 'status': 'teste', 'payment_origin': 'teste',
            })
        emitir.assert_not_called()

    def test_falha_real_do_registro_de_sinal_nao_impede_salvar_pedido(self):
        """emitir() de verdade: a conexao mockada nao reconhece o SQL de
        mi_sinais e levanta, mas isso nunca deveria escapar desta função."""
        conn = self._conn(True)
        ns = self._namespace(conn)
        ns['salvar_pedido_postgres']({
            'code': 'MAR-1', 'amount': 5990, 'quantity': 1, 'payment_origin': 'c6',
            'status': 'aguardando_pagamento',
        })  # não deve levantar


if __name__ == '__main__':
    unittest.main()
