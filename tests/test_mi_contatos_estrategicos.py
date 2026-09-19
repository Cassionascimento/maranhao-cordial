"""Central Empresarial -- seção 1.D (ciclo de vida de contatos_
estrategicos, migration 023). Validação + amarração HTTP; ciclo
completo (mudar status/reverter/histórico/interação/arquivar/excluir)
contra PostgreSQL real está em test_mi_contatos_estrategicos_postgres_real.py."""
import unittest
from unittest.mock import MagicMock

from flask import Flask

import mi_contatos_estrategicos as ce


def factory_proibida():
    raise AssertionError('validação deveria falhar antes de abrir conexão com o banco')


class ValidacaoStatus(unittest.TestCase):
    def test_status_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            ce.mudar_status(factory_proibida, 'c1', 'status_inventado', ator='diretor')

    def test_ator_obrigatorio(self):
        with self.assertRaises(ValueError):
            ce.mudar_status(factory_proibida, 'c1', 'qualificado', ator='')

    def test_reversao_de_status_e_permitida_sem_tratamento_especial(self):
        # mudar_status não distingue avanço de reversão -- qualquer valor
        # em ESTADOS_CONTATO é aceito e sempre grava histórico.
        self.assertIn('prospectado', ce.ESTADOS_CONTATO)
        self.assertIn('qualificado', ce.ESTADOS_CONTATO)


class ValidacaoInteracao(unittest.TestCase):
    def test_ator_obrigatorio(self):
        with self.assertRaises(ValueError):
            ce.registrar_interacao(factory_proibida, 'c1', ator='')


class ValidacaoArquivamento(unittest.TestCase):
    def test_ator_obrigatorio(self):
        with self.assertRaises(ValueError):
            ce.arquivar(factory_proibida, 'c1', ator='')


class ValidacaoExclusao(unittest.TestCase):
    def test_ator_obrigatorio(self):
        with self.assertRaises(ValueError):
            ce.excluir_definitivamente(factory_proibida, 'c1', ator='', confirmacao=True)

    def test_sem_confirmacao_explicita_nunca_exclui(self):
        resultado = ce.excluir_definitivamente(factory_proibida, 'c1', ator='diretor', confirmacao=False)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'confirmacao_explicita_obrigatoria')

    def test_confirmacao_string_verdadeira_nao_e_aceita_como_true(self):
        # Só o booleano True conta -- "true"/"1"/1 vindos de um payload mal
        # formado nunca autorizam a exclusão definitiva.
        resultado = ce.excluir_definitivamente(factory_proibida, 'c1', ator='diretor', confirmacao='true')
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'confirmacao_explicita_obrigatoria')


class RotaHTTP(unittest.TestCase):
    def _app(self, autorizado=lambda: True, factory=factory_proibida):
        app = Flask(__name__)
        ce.registrar_rotas(app, factory, autorizado)
        return app

    def test_todas_as_rotas_exigem_autenticacao(self):
        app = self._app(autorizado=lambda: False)
        cliente = app.test_client()
        rotas = [
            ('PATCH', '/api/admin/contatos-estrategicos/x/status'),
            ('GET', '/api/admin/contatos-estrategicos/x/historico'),
            ('POST', '/api/admin/contatos-estrategicos/x/interacao'),
            ('PATCH', '/api/admin/contatos-estrategicos/x/arquivamento'),
            ('DELETE', '/api/admin/contatos-estrategicos/x'),
        ]
        for metodo, rota in rotas:
            resp = cliente.open(rota, method=metodo)
            self.assertEqual(resp.status_code, 401, f'{metodo} {rota} deveria exigir autenticação')

    def test_status_invalido_retorna_400_nunca_500(self):
        app = self._app()
        resp = app.test_client().patch('/api/admin/contatos-estrategicos/x/status', json={'status': 'invalido'})
        self.assertEqual(resp.status_code, 400)

    def test_exclusao_sem_confirmacao_retorna_400(self):
        app = self._app()
        resp = app.test_client().delete('/api/admin/contatos-estrategicos/x', json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['motivo'], 'confirmacao_explicita_obrigatoria')

    def test_falha_inesperada_retorna_503_nunca_traceback_cru(self):
        def factory_com_falha():
            raise RuntimeError('banco indisponível')
        app = self._app(factory=factory_com_falha)
        resp = app.test_client().get('/api/admin/contatos-estrategicos/x/historico')
        self.assertEqual(resp.status_code, 503)
        corpo = resp.get_json()
        self.assertFalse(corpo['success'])
        self.assertNotIn('banco indisponível', corpo['error'])


if __name__ == '__main__':
    unittest.main()
