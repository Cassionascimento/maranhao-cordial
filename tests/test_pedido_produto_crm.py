"""P1A -- Product/Commerce Foundation: SKU -> pedido -> pagamento -> CRM ->
pipeline -> recompra. Mesma técnica de tests/test_contact_central.py: extrai
função por AST de main.py e roda em namespace isolado (nunca importa
main.py inteiro).

Cobre: pedido sem SKU histórico, pedido com SKU, SKU inexistente,
compatibilidade retroativa do checkout (INSERT/ON CONFLICT), associação com
CRM via Contact Central + mi_estabelecimentos.lead_id, e confirma que nada
aqui dispara ação externa real."""
import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

_ARVORE = ast.parse(Path('main.py').read_text())


def _extrair_funcao(nome, globais_extra=None):
    node = next(n for n in _ARVORE.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    node.decorator_list = []
    node = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    from psycopg2.extras import RealDictCursor
    import uuid as uuid_mod
    env = {'RealDictCursor': RealDictCursor, 'uuid': uuid_mod, 'print': lambda *a, **k: None}
    env.update(globais_extra or {})
    exec(compile(node, 'main.py', 'exec'), env)
    return env[nome]


def _cursor_mock(fetchone_side_effect=None):
    cur = MagicMock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    if fetchone_side_effect is not None:
        cur.fetchone.side_effect = fetchone_side_effect
    return cur


def _conn_mock(cur):
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.cursor.return_value = cur
    return conn


class SalvarPedidoPostgres(unittest.TestCase):
    def _carregar(self, cur):
        db = Mock(return_value=_conn_mock(cur))
        return _extrair_funcao('salvar_pedido_postgres', {'get_db_connection': db}), db

    def test_pedido_sem_sku_historico_grava_null_sem_inventar(self):
        cur = _cursor_mock(fetchone_side_effect=[(True,)])
        func, db = self._carregar(cur)
        with patch('mi_sinais.emitir'):
            func({'code': 'MAR-1', 'cliente_email': 'x@y.com', 'address': 'r. x', 'quantity': 1,
                  'amount': 5990, 'status': 'aguardando_pagamento'})
        params = cur.execute.call_args.args[1]
        self.assertIsNone(params[-1])  # sku é o último parâmetro do INSERT

    def test_pedido_com_sku_grava_o_valor_informado(self):
        cur = _cursor_mock(fetchone_side_effect=[(True,)])
        func, db = self._carregar(cur)
        with patch('mi_sinais.emitir'):
            func({'code': 'MAR-2', 'cliente_email': 'x@y.com', 'address': 'r. x', 'quantity': 1,
                  'amount': 5990, 'status': 'aguardando_pagamento', 'sku': 'CORDIAL-GENGIBRE-500ML'})
        params = cur.execute.call_args.args[1]
        self.assertEqual(params[-1], 'CORDIAL-GENGIBRE-500ML')

    def test_upsert_nunca_apaga_sku_ja_gravado_em_reenvio_sem_sku(self):
        cur = _cursor_mock(fetchone_side_effect=[(True,)])
        func, db = self._carregar(cur)
        with patch('mi_sinais.emitir'):
            func({'code': 'MAR-3', 'status': 'pago'})  # atualização de status, sem repassar sku
        update_sql = cur.execute.call_args.args[0]
        self.assertIn('sku = COALESCE(EXCLUDED.sku, pedidos.sku)', update_sql)

    def test_compatibilidade_checkout_no_campo_sku_nunca_quebra_insercao_antiga(self):
        # Simula literalmente uma chamada do checkout ANTES desta mudança
        # (nenhuma chave "sku" no dict) -- precisa continuar funcionando
        # sem exceção, com sku=NULL.
        cur = _cursor_mock(fetchone_side_effect=[(True,)])
        func, db = self._carregar(cur)
        pedido_antigo = {'code': 'MAR-4', 'cliente_nome': 'Fulano', 'cliente_email': 'f@x.com',
                          'address': 'Rua 1', 'quantity': 2, 'amount': 11980, 'status': 'pago',
                          'delivery': {'provider': 'correios', 'status': 'postado'}}
        with patch('mi_sinais.emitir'):
            func(pedido_antigo)  # não deve levantar exceção
        params = cur.execute.call_args.args[1]
        self.assertIsNone(params[-1])


class BuscarPedidoPostgres(unittest.TestCase):
    def test_devolve_sku_quando_presente(self):
        linha = ('MAR-1', 'Fulano', 'f@x.com', '11999990000', None, 'Rua 1', 1, 5990,
                 'pago', 'c6', None, None, None, None, 'entregue', None, None,
                 None, None, 'CORDIAL-GENGIBRE-500ML')
        cur = _cursor_mock(fetchone_side_effect=[linha])
        db = Mock(return_value=_conn_mock(cur))
        func = _extrair_funcao('buscar_pedido_postgres', {'get_db_connection': db})
        resultado = func('MAR-1')
        self.assertEqual(resultado['sku'], 'CORDIAL-GENGIBRE-500ML')

    def test_pedido_historico_sem_sku_devolve_none_nunca_inventa(self):
        linha = ('MAR-0', 'Fulano', 'f@x.com', None, None, 'Rua 1', 1, 5990,
                 'pago', 'c6', None, None, None, None, 'entregue', None, None,
                 None, None, None)
        cur = _cursor_mock(fetchone_side_effect=[linha])
        db = Mock(return_value=_conn_mock(cur))
        func = _extrair_funcao('buscar_pedido_postgres', {'get_db_connection': db})
        resultado = func('MAR-0')
        self.assertIsNone(resultado['sku'])


class ProdutoDoPedido(unittest.TestCase):
    def _carregar(self, buscar_sku_mock):
        db = Mock()
        env = {'get_db_connection': db}
        func = _extrair_funcao('produto_do_pedido', env)
        return func, buscar_sku_mock

    def test_sem_sku_devolve_unknown_sem_consultar_banco(self):
        with patch('mi_skus.buscar_sku') as buscar:
            func, _ = self._carregar(buscar)
            resultado = func(None)
        self.assertFalse(resultado['encontrado'])
        self.assertIsNone(resultado['sku'])
        buscar.assert_not_called()

    def test_sku_inexistente_devolve_encontrado_false_sem_inventar_produto(self):
        with patch('mi_skus.buscar_sku', return_value=None) as buscar:
            func, _ = self._carregar(buscar)
            resultado = func('SKU-QUE-NAO-EXISTE')
        self.assertFalse(resultado['encontrado'])
        self.assertEqual(resultado['sku'], 'SKU-QUE-NAO-EXISTE')
        self.assertIsNone(resultado['produto_nome'])

    def test_sku_existente_devolve_produto_real(self):
        produto = {'sku': 'CORDIAL-GENGIBRE-500ML', 'produto_nome': 'Cordial de Gengibre 500ml',
                   'categoria': 'bebida'}
        with patch('mi_skus.buscar_sku', return_value=produto):
            func, _ = self._carregar(None)
            resultado = func('cordial-gengibre-500ml')
        self.assertTrue(resultado['encontrado'])
        self.assertEqual(resultado['produto_nome'], 'Cordial de Gengibre 500ml')

    def test_sku_mal_formado_nunca_levanta_excecao(self):
        func, _ = self._carregar(None)
        resultado = func('###invalido###')
        self.assertFalse(resultado['encontrado'])


class IdentificarPessoaEEstabelecimentoDoPedido(unittest.TestCase):
    def _carregar(self, localizar_mock, cur):
        db = Mock(return_value=_conn_mock(cur))
        env = {'get_db_connection': db, 'localizar_contato_central_existente': localizar_mock}
        return _extrair_funcao('identificar_pessoa_e_estabelecimento_do_pedido', env)

    def test_sem_correspondencia_devolve_ambos_none(self):
        localizar = Mock(return_value={'success': True, 'encontrado': False, 'contato': None})
        cur = _cursor_mock()
        func = self._carregar(localizar, cur)
        resultado = func({'cliente_email': 'ninguem@x.com'})
        self.assertIsNone(resultado['pessoa'])
        self.assertIsNone(resultado['estabelecimento'])
        cur.execute.assert_not_called()

    def test_pessoa_encontrada_sem_estabelecimento_associado(self):
        lead = {'id': 'lead-1', 'nome': 'Fulano'}
        localizar = Mock(return_value={'success': True, 'encontrado': True, 'contato': lead})
        cur = _cursor_mock(fetchone_side_effect=[None])
        func = self._carregar(localizar, cur)
        resultado = func({'cliente_email': 'fulano@bar.com'})
        self.assertEqual(resultado['pessoa'], lead)
        self.assertIsNone(resultado['estabelecimento'])

    def test_pessoa_e_estabelecimento_associados_via_lead_id_existente(self):
        lead = {'id': 'lead-1', 'nome': 'Fulano'}
        estabelecimento = {'id': 'estab-1', 'nome': 'Bar do Fulano', 'cidade': 'São Luís', 'uf': 'MA'}
        localizar = Mock(return_value={'success': True, 'encontrado': True, 'contato': lead})
        cur = _cursor_mock(fetchone_side_effect=[estabelecimento])
        func = self._carregar(localizar, cur)
        resultado = func({'cliente_email': 'fulano@bar.com'})
        self.assertEqual(resultado['estabelecimento'], estabelecimento)
        sql = cur.execute.call_args.args[0]
        self.assertIn('mi_estabelecimentos', sql)
        self.assertIn('lead_id', sql)

    def test_nunca_cria_nem_funde_identidade_aqui(self):
        # Garantia estrutural: a função nunca chama INSERT/UPDATE -- só lê.
        import inspect
        node = next(n for n in _ARVORE.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'identificar_pessoa_e_estabelecimento_do_pedido')
        codigo = ast.unparse(node)
        for proibido in ('INSERT INTO', 'UPDATE ', 'DELETE ', 'obter_ou_criar_contato_central'):
            self.assertNotIn(proibido, codigo)


class NenhumaAcaoExterna(unittest.TestCase):
    def test_produto_do_pedido_nunca_referencia_transporte_externo(self):
        node = next(n for n in _ARVORE.body if isinstance(n, ast.FunctionDef) and n.name == 'produto_do_pedido')
        codigo = ast.unparse(node)
        for proibido in ('requests.', 'smtplib', 'whatsapp', 'gmail', 'OpenAI('):
            self.assertNotIn(proibido, codigo.lower() if proibido.islower() else codigo)

    def test_rota_de_contexto_do_pedido_e_get_e_exige_autorizacao(self):
        node = next(n for n in _ARVORE.body if isinstance(n, ast.FunctionDef) and n.name == 'contexto_pedido')
        metodos = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'route':
                for kw in dec.keywords:
                    if kw.arg == 'methods':
                        metodos = [e.value for e in kw.value.elts]
        self.assertEqual(metodos, ['GET'])
        codigo = ast.unparse(node)
        self.assertIn('validar_admin_request', codigo)


if __name__ == '__main__':
    unittest.main()
