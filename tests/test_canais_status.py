"""Painel único de canais: só agrega leitura, nunca inventa 'conectado'."""
import unittest
from unittest.mock import patch

import canais_status as cs


class StatusTodosOsCanais(unittest.TestCase):
    def test_ordem_fixa_dos_6_canais(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais()
        self.assertEqual([c['canal'] for c in canais], ['Instagram', 'WhatsApp', 'LinkedIn', 'Pinterest', 'X', 'Gmail'])

    def test_sem_nenhuma_credencial_nenhum_canal_fica_conectado(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais()
        self.assertTrue(all(c['estado'] != 'conectado' for c in canais))

    def test_campos_obrigatorios_presentes_em_cada_canal(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais()
        campos = {'canal', 'estado', 'ultima_sincronizacao', 'leitura_disponivel',
                  'escrita_disponivel', 'aprovacao_exigida', 'ultimo_erro'}
        for c in canais:
            self.assertEqual(set(c.keys()), campos)

    def test_instagram_conectado_so_com_token_real_ja_usado_pelo_projeto(self):
        with patch.dict('os.environ', {'INSTAGRAM_ACCESS_TOKEN': 't'}, clear=True):
            canais = cs.status_todos_os_canais()
        instagram = next(c for c in canais if c['canal'] == 'Instagram')
        self.assertEqual(instagram['estado'], 'conectado')

    def test_whatsapp_falha_ao_consultar_status_vira_bloqueado_nao_derruba_o_painel(self):
        with patch('whatsapp_omnichannel.status_conector', side_effect=RuntimeError('x')):
            canais = cs.status_todos_os_canais()
        whatsapp = next(c for c in canais if c['canal'] == 'WhatsApp')
        self.assertEqual(whatsapp['estado'], 'bloqueado')
        # os outros 5 continuam presentes mesmo com a falha de um canal
        self.assertEqual(len(canais), 6)


class RotaHttp(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.app = Flask(__name__)
        self.autorizado = True
        cs.registrar_rotas_canais(self.app, lambda: self.autorizado)
        self.client = self.app.test_client()

    def test_sem_autorizacao_recusa(self):
        self.autorizado = False
        resposta = self.client.get('/api/admin/canais/status')
        self.assertEqual(resposta.status_code, 401)

    def test_autorizado_recebe_lista_de_6_canais_via_get(self):
        with patch.dict('os.environ', {}, clear=True):
            resposta = self.client.get('/api/admin/canais/status')
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.get_json()
        self.assertTrue(corpo['success'])
        self.assertEqual(len(corpo['canais']), 6)


if __name__ == '__main__':
    unittest.main()
