"""Contact Central (resolução de identidade em leads_crm) -- localizar_
contato_central_existente, obter_ou_criar_contato_central e registrar_
identidade_externa_contato, todas definidas em main.py.

Mesma técnica de tests/test_c6_pix.py: extrai só a função por AST e a
executa num namespace isolado (nunca `import main` -- main.py tem efeitos
colaterais reais na importação: Flask app, SocketIO, OAuth Google,
threading -- ver docstring de tests/test_bootstrap_homologacao.py, "Nenhum
teste aqui importa main.py de verdade nem conecta em banco real", mesma
disciplina seguida aqui).

Foco: a garantia central e de maior risco -- NUNCA fundir dois contatos só
por nome (precisa de nome+empresa exatos, ou de um identificador forte:
email/telefone/instagram)."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

_ARVORE = ast.parse(Path('main.py').read_text())


def _extrair_funcao(nome, globais_extra=None):
    node = next(n for n in _ARVORE.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    node = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    from psycopg2.extras import RealDictCursor
    import uuid as uuid_mod
    env = {'RealDictCursor': RealDictCursor, 'uuid': uuid_mod, 'print': lambda *a, **k: None}
    env.update(globais_extra or {})
    exec(compile(node, 'main.py', 'exec'), env)
    return env[nome]


def _cursor_mock(fetchone_side_effect=None, fetchall_side_effect=None):
    cur = Mock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    if fetchone_side_effect is not None:
        cur.fetchone.side_effect = fetchone_side_effect
    if fetchall_side_effect is not None:
        cur.fetchall.side_effect = fetchall_side_effect
    return cur


def _conn_mock(cur):
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.cursor.return_value = cur
    return conn


class LocalizarContatoCentralExistente(unittest.TestCase):
    def setUp(self):
        self.func_nome = 'localizar_contato_central_existente'

    def _carregar(self, cur):
        db = Mock(return_value=_conn_mock(cur))
        return _extrair_funcao(self.func_nome, {'get_db_connection': db}), db

    def test_email_exato_encontra_e_para_na_primeira_consulta(self):
        contato = {'id': 'lead-1', 'email': 'joao@bar.com'}
        cur = _cursor_mock(fetchone_side_effect=[contato])
        func, db = self._carregar(cur)
        resultado = func(email='JOAO@BAR.COM')
        self.assertTrue(resultado['encontrado'])
        self.assertEqual(resultado['criterio_identidade'], 'email')
        self.assertEqual(cur.execute.call_count, 1)

    def test_telefone_normalizado_ignora_formatacao(self):
        candidatos = [{'id': 'lead-2', 'telefone': '(11) 99999-0000'}]
        cur = _cursor_mock(fetchall_side_effect=[candidatos])
        func, db = self._carregar(cur)
        resultado = func(telefone='11999990000')
        self.assertTrue(resultado['encontrado'])
        self.assertEqual(resultado['criterio_identidade'], 'telefone')

    def test_instagram_normalizado_ignora_url_e_arroba(self):
        candidatos = [{'id': 'lead-3', 'instagram': 'https://instagram.com/BarDoJoao/?hl=pt'}]
        cur = _cursor_mock(fetchall_side_effect=[candidatos])
        func, db = self._carregar(cur)
        resultado = func(instagram='@bardojoao')
        self.assertTrue(resultado['encontrado'])
        self.assertEqual(resultado['criterio_identidade'], 'instagram')

    def test_nome_sozinho_nunca_consulta_nem_encontra(self):
        cur = _cursor_mock()
        func, db = self._carregar(cur)
        resultado = func(nome='João')
        self.assertFalse(resultado['encontrado'])
        cur.execute.assert_not_called()

    def test_nome_mais_empresa_e_o_unico_fallback_fraco_aceito(self):
        contato = {'id': 'lead-4', 'nome': 'João', 'empresa': 'Bar do João'}
        cur = _cursor_mock(fetchone_side_effect=[contato])
        func, db = self._carregar(cur)
        resultado = func(nome='João', empresa='Bar do João')
        self.assertTrue(resultado['encontrado'])
        self.assertEqual(resultado['criterio_identidade'], 'nome_empresa')

    def test_nada_encontrado_devolve_encontrado_false(self):
        cur = _cursor_mock(fetchone_side_effect=[None, None])
        func, db = self._carregar(cur)
        resultado = func(email='ninguem@x.com', nome='X', empresa='Y')
        self.assertFalse(resultado['encontrado'])
        self.assertIsNone(resultado['contato'])

    def test_falha_de_banco_nao_propaga_excecao_e_fecha_conexao(self):
        cur = Mock()
        cur.__enter__ = Mock(side_effect=RuntimeError('conexao indisponivel'))
        conn = _conn_mock(cur)
        db = Mock(return_value=conn)
        func = _extrair_funcao(self.func_nome, {'get_db_connection': db})
        resultado = func(email='joao@bar.com')
        self.assertFalse(resultado['success'])
        conn.close.assert_called_once()


class ObterOuCriarContatoCentral(unittest.TestCase):
    def _carregar(self, cur):
        db = Mock(return_value=_conn_mock(cur))
        return _extrair_funcao('obter_ou_criar_contato_central', {'get_db_connection': db}), db

    def test_email_existente_enriquece_sem_apagar_dado(self):
        existente = {'id': 'lead-1', 'categoria_contato': 'lead'}
        atualizado = {'id': 'lead-1', 'nome': 'João', 'categoria_contato': 'bartender'}
        cur = _cursor_mock(fetchone_side_effect=[existente, atualizado])
        func, db = self._carregar(cur)
        resultado = func(email='joao@bar.com', nome='João', categoria_contato='bartender')
        self.assertFalse(resultado['criado'])
        self.assertEqual(resultado['criterio_identidade'], 'email')
        update_sql = cur.execute.call_args_list[1].args[0]
        self.assertIn('UPDATE leads_crm', update_sql)
        self.assertIn('COALESCE', update_sql)

    def test_nome_sozinho_nunca_funde_sempre_cria_novo(self):
        cur = _cursor_mock(fetchone_side_effect=[{'id': 'lead-novo', 'nome': 'João'}])
        func, db = self._carregar(cur)
        resultado = func(nome='João')
        self.assertTrue(resultado['criado'])
        self.assertEqual(resultado['criterio_identidade'], 'novo')
        insert_sql = cur.execute.call_args_list[-1].args[0]
        self.assertIn('INSERT INTO leads_crm', insert_sql)

    def test_nenhum_identificador_forte_e_sem_empresa_cria_novo_contato(self):
        cur = _cursor_mock(fetchone_side_effect=[{'id': 'novo'}])
        func, db = self._carregar(cur)
        resultado = func(nome='Maria', empresa=None, email=None, telefone=None, instagram=None)
        self.assertTrue(resultado['criado'])

    def test_nome_e_empresa_exatos_funde_com_existente(self):
        existente = {'id': 'lead-5', 'categoria_contato': 'lead'}
        atualizado = {'id': 'lead-5', 'categoria_contato': 'bar'}
        cur = _cursor_mock(fetchone_side_effect=[existente, atualizado])
        func, db = self._carregar(cur)
        resultado = func(nome='João', empresa='Bar do João', categoria_contato='bar')
        self.assertFalse(resultado['criado'])
        self.assertEqual(resultado['criterio_identidade'], 'nome_empresa')

    def test_categoria_invalida_cai_para_lead(self):
        cur = _cursor_mock(fetchone_side_effect=[None, {'id': 'novo', 'categoria_contato': 'lead'}])
        func, db = self._carregar(cur)
        resultado = func(email='x@y.com', categoria_contato='categoria-que-nao-existe')
        self.assertTrue(resultado['criado'])
        insert_args = cur.execute.call_args_list[-1].args[1]
        self.assertIn('lead', insert_args)
        self.assertNotIn('categoria-que-nao-existe', insert_args)

    def test_falha_de_banco_nao_propaga_excecao_e_fecha_conexao(self):
        cur = Mock()
        cur.__enter__ = Mock(side_effect=RuntimeError('conexao indisponivel'))
        conn = _conn_mock(cur)
        db = Mock(return_value=conn)
        func = _extrair_funcao('obter_ou_criar_contato_central', {'get_db_connection': db})
        resultado = func(email='joao@bar.com')
        self.assertFalse(resultado['success'])
        conn.close.assert_called_once()


class RegistrarIdentidadeExternaContato(unittest.TestCase):
    def _carregar(self, cur):
        db = Mock(return_value=_conn_mock(cur))
        return _extrair_funcao('registrar_identidade_externa_contato', {'get_db_connection': db}), db

    def test_upsert_grava_canal_identificador_e_proveniencia(self):
        identidade = {'canal': 'whatsapp', 'identificador_externo': '5511999990000',
                      'contato_central_id': 'lead-1', 'confianca': 95.0, 'criterio_vinculo': 'telefone_exato'}
        cur = _cursor_mock(fetchone_side_effect=[identidade])
        func, db = self._carregar(cur)
        resultado = func('whatsapp', '5511999990000', contato_central_id='lead-1',
                          criterio_vinculo='telefone_exato', confianca=95.0)
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['identidade']['contato_central_id'], 'lead-1')
        sql = cur.execute.call_args.args[0]
        self.assertIn('ON CONFLICT', sql)
        self.assertIn('canal', sql)

    def test_canal_ausente_e_rejeitado_sem_tocar_banco(self):
        cur = _cursor_mock()
        func, db = self._carregar(cur)
        resultado = func('', 'algum-id')
        self.assertFalse(resultado['success'])
        db.assert_not_called()

    def test_identificador_ausente_e_rejeitado_sem_tocar_banco(self):
        cur = _cursor_mock()
        func, db = self._carregar(cur)
        resultado = func('whatsapp', '   ')
        self.assertFalse(resultado['success'])
        db.assert_not_called()

    def test_nunca_altera_interacoes_historicas(self):
        # Garantia estrutural: a função só toca identidades_externas_contato,
        # nunca interacoes_omnichannel -- verificado no próprio SQL emitido.
        identidade = {'canal': 'instagram', 'identificador_externo': 'x'}
        cur = _cursor_mock(fetchone_side_effect=[identidade])
        func, db = self._carregar(cur)
        func('instagram', 'x')
        sql = cur.execute.call_args.args[0]
        self.assertNotIn('interacoes_omnichannel', sql)

    def test_falha_de_banco_nao_propaga_excecao_e_fecha_conexao(self):
        cur = Mock()
        cur.__enter__ = Mock(side_effect=RuntimeError('conexao indisponivel'))
        conn = _conn_mock(cur)
        db = Mock(return_value=conn)
        func = _extrair_funcao('registrar_identidade_externa_contato', {'get_db_connection': db})
        resultado = func('whatsapp', '123')
        self.assertFalse(resultado['success'])
        conn.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
