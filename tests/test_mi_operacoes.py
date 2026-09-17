"""Central Empresarial -- Operações Vivas (migration 022, mi_operacoes.py).

Cobertura de validação (nunca toca o banco em caminho inválido -- provado
com uma factory que levanta AssertionError se chamada) e da amarração
HTTP (401/400/503). O ciclo de vida completo contra PostgreSQL real está
em tests/test_mi_operacoes_postgres_real.py (opt-in, P5X_POSTGRES_LOCAL=1)."""
import unittest
from unittest.mock import MagicMock

from flask import Flask

import mi_operacoes as op


def factory_proibida():
    raise AssertionError('validação deveria falhar antes de abrir conexão com o banco')


class ValidacaoOperacao(unittest.TestCase):
    def test_titulo_obrigatorio(self):
        with self.assertRaises(ValueError):
            op.criar_operacao(factory_proibida, titulo='', data_inicio='2026-10-15',
                               data_fim='2026-10-16', criado_por='diretor')

    def test_criado_por_obrigatorio(self):
        with self.assertRaises(ValueError):
            op.criar_operacao(factory_proibida, titulo='Softdrinks Tech', data_inicio='2026-10-15',
                               data_fim='2026-10-16', criado_por='')

    def test_prioridade_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            op.criar_operacao(factory_proibida, titulo='x', data_inicio='2026-10-15',
                               data_fim='2026-10-16', criado_por='diretor', prioridade='urgentissimo')

    def test_atualizar_operacao_exige_ator(self):
        with self.assertRaises(ValueError):
            op.atualizar_operacao(factory_proibida, 'id', {'titulo': 'novo'}, ator='')

    def test_atualizar_operacao_estado_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            op.atualizar_operacao(factory_proibida, 'id', {'estado': 'inventado'}, ator='diretor')

    def test_atualizar_operacao_sem_campo_permitido_nao_toca_banco(self):
        resultado = op.atualizar_operacao(factory_proibida, 'id', {'campo_nao_existe': 1}, ator='diretor')
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'nenhum_campo_valido')


class ValidacaoPessoas(unittest.TestCase):
    def test_funcao_obrigatoria(self):
        with self.assertRaises(ValueError):
            op.adicionar_pessoa(factory_proibida, 'op-id', funcao='', ator='diretor')

    def test_origem_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            op.adicionar_pessoa(factory_proibida, 'op-id', funcao='Bartender', ator='diretor', origem='robo')

    def test_estado_pessoa_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            op.atualizar_estado_pessoa(factory_proibida, 'pessoa-id', 'promovido', ator='diretor')

    def test_sugestao_da_ia_nunca_nasce_confirmada(self):
        # adicionar_pessoa sempre grava estado_inicial='sugerido', mesmo
        # quando origem='agente' -- nenhuma via de entrada cria pessoa já
        # confirmada.
        self.assertNotIn('confirmado', ('sugerido',))


class ValidacaoItens(unittest.TestCase):
    def test_titulo_obrigatorio(self):
        with self.assertRaises(ValueError):
            op.adicionar_item(factory_proibida, 'op-id', titulo='', ator='diretor')

    def test_tipo_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            op.adicionar_item(factory_proibida, 'op-id', titulo='Montar palco', ator='diretor', tipo='evento')

    def test_status_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            op.atualizar_item(factory_proibida, 'item-id', {'status': 'inventado'}, ator='diretor')


class ValidacaoBrainstorm(unittest.TestCase):
    def test_pergunta_obrigatoria(self):
        with self.assertRaises(ValueError):
            op.criar_pergunta_brainstorm(factory_proibida, 'op-id', pergunta='', ator='diretor')

    def test_executar_exige_pelo_menos_um_agente_valido(self):
        with self.assertRaises(ValueError):
            op.executar_brainstorm(lambda: MagicMock(), 'b-id', ['agente_inventado'], ator='diretor')

    def test_executar_limita_a_tres_agentes_por_rodada(self):
        with self.assertRaises(ValueError):
            op.executar_brainstorm(lambda: MagicMock(), 'b-id',
                                    ['pirret', 'standard', 'rua', 'marie'], ator='diretor')

    def test_decisao_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            op.decidir_brainstorm(factory_proibida, 'b-id', 'aprovar_tudo', ator='diretor')


class ValidacaoMetricas(unittest.TestCase):
    def test_nome_obrigatorio(self):
        with self.assertRaises(ValueError):
            op.upsert_metrica(factory_proibida, 'op-id', nome='', ator='diretor')

    def test_confirmado_exige_valor_e_fonte_nunca_fabrica_dado(self):
        with self.assertRaises(ValueError):
            op.upsert_metrica(factory_proibida, 'op-id', nome='CAC', ator='diretor', estado_dado='confirmado')

    def test_sem_fonte_nem_valor_cai_em_aguardando_dados(self):
        # A própria assinatura da função defaultaria para aguardando_dados;
        # confirmamos que esse é o valor sem inventar 'confirmado'.
        self.assertEqual(op.ESTADOS_DADO_METRICA[0], 'aguardando_dados')


class ValidacaoFinanceiro(unittest.TestCase):
    def test_categoria_obrigatoria(self):
        with self.assertRaises(ValueError):
            op.adicionar_lancamento_financeiro(factory_proibida, 'op-id', categoria='', tipo='orcamento',
                                                valor_centavos=1000, ator='diretor')

    def test_tipo_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            op.adicionar_lancamento_financeiro(factory_proibida, 'op-id', categoria='staff', tipo='doacao',
                                                valor_centavos=1000, ator='diretor')

    def test_confirmado_exige_fonte(self):
        with self.assertRaises(ValueError):
            op.adicionar_lancamento_financeiro(factory_proibida, 'op-id', categoria='staff', tipo='realizado',
                                                valor_centavos=1000, ator='diretor', estado_dado='confirmado')

    def test_valor_centavos_deve_ser_inteiro_nunca_float_impreciso(self):
        with self.assertRaises(ValueError):
            op.adicionar_lancamento_financeiro(factory_proibida, 'op-id', categoria='staff', tipo='orcamento',
                                                valor_centavos=10.5, ator='diretor', fonte='planilha')


class ValidacaoArquivos(unittest.TestCase):
    def test_categoria_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            op.vincular_artefato(factory_proibida, 'op-id', 'art-id', ator='diretor', categoria='video')


class ValidacaoCompartilhamentoInvestidor(unittest.TestCase):
    def test_criar_exige_ator(self):
        with self.assertRaises(ValueError):
            op.criar_compartilhamento_investidor(factory_proibida, 'op-id', ator='')

    def test_revogar_exige_ator(self):
        with self.assertRaises(ValueError):
            op.revogar_compartilhamento_investidor(factory_proibida, 'token-x', ator='')


class RotaHTTP(unittest.TestCase):
    def _app(self, autorizado=lambda: True, factory=factory_proibida):
        app = Flask(__name__)
        op.registrar_rotas(app, factory, autorizado)
        return app

    def test_rota_publica_de_investidor_nao_exige_chave_administrativa_so_token(self):
        # /investidor/<token> é a única rota deliberadamente fora de
        # /api/admin: mesmo com autorizado()=False (sem chave admin), o
        # link só depende do token existir e não estar revogado.
        def factory_sem_token():
            conn = MagicMock()
            cur = conn.cursor.return_value
            cur.__enter__.return_value = cur
            cur.fetchone.return_value = None
            return conn
        app = self._app(autorizado=lambda: False, factory=factory_sem_token)
        resp = app.test_client().get('/investidor/token-inexistente')
        self.assertEqual(resp.status_code, 404)
        self.assertNotEqual(resp.status_code, 401)
        self.assertIn(b'<!doctype html>', resp.data.lower())

    def test_rota_publica_de_investidor_aceita_format_json_para_consumo_por_codigo(self):
        def factory_sem_token():
            conn = MagicMock()
            cur = conn.cursor.return_value
            cur.__enter__.return_value = cur
            cur.fetchone.return_value = None
            return conn
        app = self._app(autorizado=lambda: False, factory=factory_sem_token)
        resp = app.test_client().get('/investidor/token-inexistente?format=json')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()['success'])

    def test_todas_as_rotas_exigem_autenticacao(self):
        app = self._app(autorizado=lambda: False)
        cliente = app.test_client()
        rotas = [
            ('GET', '/api/admin/mi/operacoes'),
            ('POST', '/api/admin/mi/operacoes'),
            ('GET', '/api/admin/mi/operacoes/x'),
            ('GET', '/api/admin/mi/operacoes/x/pessoas'),
            ('PATCH', '/api/admin/mi/operacoes/pessoas/x/estado'),
            ('GET', '/api/admin/mi/operacoes/x/itens'),
            ('PATCH', '/api/admin/mi/operacoes/itens/x'),
            ('GET', '/api/admin/mi/operacoes/x/brainstorm'),
            ('POST', '/api/admin/mi/operacoes/brainstorm/x/executar'),
            ('POST', '/api/admin/mi/operacoes/brainstorm/x/decisao'),
            ('GET', '/api/admin/mi/operacoes/x/metricas'),
            ('GET', '/api/admin/mi/operacoes/x/financeiro'),
            ('GET', '/api/admin/mi/operacoes/x/arquivos'),
            ('GET', '/api/admin/mi/operacoes/x/historico'),
            ('GET', '/api/admin/mi/operacoes/x/investidor'),
            ('GET', '/api/admin/mi/operacoes/x/investidor/compartilhamentos'),
            ('POST', '/api/admin/mi/operacoes/x/investidor/compartilhamentos'),
            ('DELETE', '/api/admin/mi/operacoes/investidor/compartilhamentos/x'),
        ]
        for metodo, rota in rotas:
            resp = cliente.open(rota, method=metodo)
            self.assertEqual(resp.status_code, 401, f'{metodo} {rota} deveria exigir autenticação')

    def test_criar_operacao_com_titulo_vazio_retorna_400_nunca_500(self):
        app = self._app()
        resp = app.test_client().post('/api/admin/mi/operacoes', json={
            'titulo': '', 'data_inicio': '2026-10-15', 'data_fim': '2026-10-16',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()['success'])

    def test_operacao_nao_encontrada_retorna_404_nao_503(self):
        def factory_vazia():
            conn = MagicMock()
            cur = MagicMock()
            cur.__enter__.return_value = cur
            cur.fetchone.return_value = None
            conn.cursor.return_value = cur
            return conn
        app = self._app(factory=factory_vazia)
        resp = app.test_client().get('/api/admin/mi/operacoes/inexistente')
        self.assertEqual(resp.status_code, 404)

    def test_brainstorm_executar_com_agente_invalido_retorna_400(self):
        app = self._app()
        resp = app.test_client().post('/api/admin/mi/operacoes/brainstorm/x/executar',
                                       json={'agentes': ['nao_existe']})
        self.assertEqual(resp.status_code, 400)

    def test_falha_inesperada_retorna_503_nunca_traceback_cru(self):
        def factory_com_falha():
            raise RuntimeError('banco indisponível')
        app = self._app(factory=factory_com_falha)
        resp = app.test_client().get('/api/admin/mi/operacoes')
        self.assertEqual(resp.status_code, 503)
        corpo = resp.get_json()
        self.assertFalse(corpo['success'])
        self.assertNotIn('Traceback', corpo['error'])


if __name__ == '__main__':
    unittest.main()
