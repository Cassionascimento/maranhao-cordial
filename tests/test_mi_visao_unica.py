"""Visão única -- mi_visao_unica.py. Só agrega leads_crm/
identidades_externas_contato/interacoes_omnichannel já existentes; nunca
funde identidade, nunca inclui GA4 (sem identificador válido ligado a lead)."""
import unittest
from unittest.mock import MagicMock

import mi_visao_unica as vu


class BuscarLeads(unittest.TestCase):
    def test_termo_vazio_nao_consulta_banco(self):
        cur = MagicMock()
        resultado = vu.buscar_leads(cur, '   ')
        self.assertEqual(resultado, [])
        cur.execute.assert_not_called()

    def test_termo_valido_consulta_com_curinga(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{'id': '1', 'nome': 'Fulano'}]
        resultado = vu.buscar_leads(cur, 'fulano')
        self.assertEqual(resultado, [{'id': '1', 'nome': 'Fulano'}])
        args = cur.execute.call_args.args[1]
        self.assertEqual(args[0], '%fulano%')


class VisaoUnica(unittest.TestCase):
    def test_lead_inexistente_devolve_none(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        self.assertIsNone(vu.visao_unica(cur, 'id-inexistente'))

    def test_agrega_lead_identidades_e_interacoes(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'id': 'lead1', 'nome': 'Fulano', 'email': 'fulano@x.com'}
        cur.fetchall.side_effect = [
            [{'canal': 'whatsapp', 'identificador_externo': '5511999', 'confianca': 95.0}],
            [{'canal': 'whatsapp', 'plataforma': None, 'tipo_interacao': 'mensagem',
              'classificacao': 'interesse_alto', 'interesse': 'alto', 'criado_em': 'ontem'}],
        ]
        visao = vu.visao_unica(cur, 'lead1')
        self.assertEqual(visao['lead']['id'], 'lead1')
        self.assertEqual(len(visao['identidades_por_canal']), 1)
        self.assertEqual(visao['resumo_canais'], {'whatsapp': 1})
        self.assertEqual(visao['total_interacoes_na_janela'], 1)

    def test_nunca_expoe_texto_bruto_da_mensagem(self):
        import inspect
        codigo = inspect.getsource(vu._interacoes)
        self.assertNotIn('texto', codigo.split('SELECT')[1].split('FROM')[0])


class RegistrarRotasVisaoUnica(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        from flask import Flask
        app = Flask(__name__)
        vu.registrar_rotas_visao_unica(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.get('/api/admin/mi/visao-unica/buscar').status_code, 401)
        self.assertEqual(cliente.get('/api/admin/mi/visao-unica/algum-id').status_code, 401)


if __name__ == '__main__':
    unittest.main()
