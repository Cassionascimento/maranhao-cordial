import unittest
from unittest.mock import MagicMock
from flask import Flask
from mi_painel import gerar_painel_mi, registrar_rotas_mi_painel

CAMPOS_PROIBIDOS = ('id', 'codigo_publico', 'payload')


def conexao_com_dados(
    total_skus=2, total_lotes=3, unidades=(('emitida', 4), ('ativa', 5), ('revogada', 1)),
    total_eventos=20, total_scans_qr=12, total_estabelecimentos=3,
    territorio=(('Salvador', 'BA', 8), ('São Paulo', 'SP', 4)),
    atividade=(('scan', 'qr', 'MC-100ML', None, 'Salvador', 'BA'),),
    por_sku=(('MC-100ML', 'Concentrado Guaraná e Gengibre', 10),),
    por_lote=(('L001', 6), ('não associado', 4)),
    por_estabelecimento=(('Bar do Zé', 'Salvador', 'BA', 8),),
):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [
        {'total': total_skus},
        {'total': total_lotes},
        {'total': total_eventos},
        {'total': total_scans_qr},
        {'total': total_estabelecimentos},
    ]
    cur.fetchall.side_effect = [
        [{'estado': e, 'total': t} for e, t in unidades],
        [{'cidade': c, 'uf': u, 'total': t} for c, u, t in territorio],
        [{'tipo_evento': te, 'canal': ca, 'sku': sk, 'criado_em': ce, 'cidade': ci, 'uf': uf}
         for te, ca, sk, ce, ci, uf in atividade],
        [{'sku': sk, 'produto_nome': nome, 'total': t} for sk, nome, t in por_sku],
        [{'lote': lote, 'total': t} for lote, t in por_lote],
        [{'nome': n, 'cidade': c, 'uf': u, 'total': t} for n, c, u, t in por_estabelecimento],
    ]
    return conn, cur


class GerarPainel(unittest.TestCase):
    def test_resumo_agrega_totais_esperados(self):
        conn, cur = conexao_com_dados()
        painel = gerar_painel_mi(lambda: conn)
        self.assertEqual(painel['resumo']['unidades'], 10)  # 4+5+1
        self.assertEqual(painel['resumo']['eventos'], 20)
        self.assertEqual(painel['resumo']['scans_qr'], 12)
        self.assertEqual(painel['resumo']['estabelecimentos'], 3)
        self.assertEqual(painel['resumo']['territorios_ativos'], 2)

    def test_secundario_traz_sku_lote_e_estado_das_unidades(self):
        conn, cur = conexao_com_dados()
        painel = gerar_painel_mi(lambda: conn)
        self.assertEqual(painel['secundario']['skus'], 2)
        self.assertEqual(painel['secundario']['lotes'], 3)
        self.assertEqual(painel['secundario']['unidades_por_estado'],
                          {'emitida': 4, 'ativa': 5, 'revogada': 1})

    def test_estado_sem_nenhuma_unidade_aparece_como_zero(self):
        conn, cur = conexao_com_dados(unidades=(('ativa', 5),))
        painel = gerar_painel_mi(lambda: conn)
        self.assertEqual(painel['secundario']['unidades_por_estado'],
                          {'emitida': 0, 'ativa': 5, 'revogada': 0})

    def test_usa_transacao_read_only_para_snapshot_consistente(self):
        conn, cur = conexao_com_dados()
        gerar_painel_mi(lambda: conn)
        conn.set_session.assert_called_once_with(readonly=True, isolation_level='REPEATABLE READ')
        conn.close.assert_called_once()

    def test_nenhuma_consulta_e_escrita(self):
        conn, cur = conexao_com_dados()
        gerar_painel_mi(lambda: conn)
        for chamada in cur.execute.call_args_list:
            sql = chamada.args[0].upper()
            for verbo in ('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP', 'TRUNCATE'):
                self.assertNotIn(verbo, sql)

    def test_resposta_nunca_expoe_campos_proibidos(self):
        conn, cur = conexao_com_dados()
        painel = gerar_painel_mi(lambda: conn)

        def varrer(valor):
            if isinstance(valor, dict):
                for chave, sub in valor.items():
                    self.assertNotIn(chave, CAMPOS_PROIBIDOS)
                    varrer(sub)
            elif isinstance(valor, list):
                for item in valor:
                    varrer(item)

        varrer(painel)


class DistribuicaoPorLoteCanonica(unittest.TestCase):
    def test_consulta_usa_unidade_e_lote_nunca_o_campo_textual_legado(self):
        conn, cur = conexao_com_dados()
        gerar_painel_mi(lambda: conn)
        sql_lote = next(c.args[0] for c in cur.execute.call_args_list if 'codigo_lote' in c.args[0])
        self.assertIn('mi_unidades', sql_lote)
        self.assertIn('mi_lotes', sql_lote)
        self.assertIn('e.unidade_id', sql_lote)
        self.assertNotIn('e.lote', sql_lote)  # nunca o campo textual solto legado

    def test_evento_sem_unidade_aparece_como_nao_associado(self):
        conn, cur = conexao_com_dados(por_lote=(('não associado', 7),))
        painel = gerar_painel_mi(lambda: conn)
        self.assertEqual(painel['produto']['por_lote'], [{'lote': 'não associado', 'total': 7}])


class RotaMiPainel(unittest.TestCase):
    def _app(self, factory, autorizado):
        app = Flask(__name__)
        registrar_rotas_mi_painel(app, factory, autorizado)
        return app.test_client()

    def test_exige_autenticacao_antes_de_qualquer_consulta(self):
        factory = MagicMock(side_effect=AssertionError('nao deveria conectar'))
        client = self._app(factory, lambda: False)
        resposta = client.get('/api/admin/mi/painel')
        self.assertEqual(resposta.status_code, 401)
        factory.assert_not_called()

    def test_retorna_painel_quando_autorizado(self):
        conn, cur = conexao_com_dados()
        client = self._app(lambda: conn, lambda: True)
        resposta = client.get('/api/admin/mi/painel')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()['success'])

    def test_falha_interna_nao_vaza_detalhe(self):
        factory = MagicMock(side_effect=RuntimeError('conexão indisponível'))
        client = self._app(factory, lambda: True)
        resposta = client.get('/api/admin/mi/painel')
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn('conexão indisponível', resposta.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
