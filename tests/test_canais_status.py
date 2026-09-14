"""Painel único de canais: só agrega leitura, nunca inventa 'conectado'."""
import datetime
import unittest
from unittest.mock import patch

import canais_status as cs


def _factory_sem_banco():
    """Simula ambiente sem DATABASE_URL -- Gmail cai só no fallback por env var."""
    def _levantar():
        raise RuntimeError('DATABASE_URL não configurada.')
    return _levantar


class _CursorFalso:
    def __init__(self, linha):
        self._linha = linha

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, *_args, **_kwargs):
        pass

    def fetchone(self):
        return self._linha


class _ConexaoFalsa:
    def __init__(self, linha):
        self._linha = linha

    def cursor(self):
        return _CursorFalso(self._linha)

    def close(self):
        pass


def _factory_com_credencial_gmail(quando):
    return lambda: _ConexaoFalsa((quando,))


def _factory_sem_credencial_gmail():
    return lambda: _ConexaoFalsa(None)


class StatusTodosOsCanais(unittest.TestCase):
    def test_ordem_fixa_dos_6_canais(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais(_factory_sem_banco())
        self.assertEqual([c['canal'] for c in canais], ['Instagram', 'WhatsApp', 'LinkedIn', 'Pinterest', 'X', 'Gmail'])

    def test_sem_nenhuma_credencial_nenhum_canal_fica_conectado(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais(_factory_sem_banco())
        self.assertTrue(all(c['estado'] != 'conectado' for c in canais))

    def test_campos_obrigatorios_presentes_em_cada_canal(self):
        with patch.dict('os.environ', {}, clear=True):
            canais = cs.status_todos_os_canais(_factory_sem_banco())
        campos = {'canal', 'estado', 'ultima_sincronizacao', 'leitura_disponivel',
                  'escrita_disponivel', 'aprovacao_exigida', 'ultimo_erro', 'proximo_passo'}
        for c in canais:
            self.assertEqual(set(c.keys()), campos)

    def test_instagram_conectado_so_com_token_real_ja_usado_pelo_projeto(self):
        with patch.dict('os.environ', {'INSTAGRAM_ACCESS_TOKEN': 't'}, clear=True):
            canais = cs.status_todos_os_canais(_factory_sem_banco())
        instagram = next(c for c in canais if c['canal'] == 'Instagram')
        self.assertEqual(instagram['estado'], 'conectado')

    def test_proximo_passo_orienta_o_portal_exato_quando_pendente_e_fica_none_quando_conectado(self):
        with patch.dict('os.environ', {}, clear=True):
            linkedin = next(c for c in cs.status_todos_os_canais(_factory_sem_banco()) if c['canal'] == 'LinkedIn')
        self.assertIn('LinkedIn Developer Portal', linkedin['proximo_passo'])
        with patch.dict('os.environ', {'LINKEDIN_CLIENT_ID': 'a', 'LINKEDIN_CLIENT_SECRET': 'b', 'LINKEDIN_ACCESS_TOKEN': 'c'}, clear=True):
            linkedin = next(c for c in cs.status_todos_os_canais(_factory_sem_banco()) if c['canal'] == 'LinkedIn')
        self.assertIsNone(linkedin['proximo_passo'])

    def test_whatsapp_falha_ao_consultar_status_vira_bloqueado_nao_derruba_o_painel(self):
        with patch('whatsapp_omnichannel.status_conector', side_effect=RuntimeError('x')):
            canais = cs.status_todos_os_canais(_factory_sem_banco())
        whatsapp = next(c for c in canais if c['canal'] == 'WhatsApp')
        self.assertEqual(whatsapp['estado'], 'bloqueado')
        # os outros 5 continuam presentes mesmo com a falha de um canal
        self.assertEqual(len(canais), 6)

    def test_gmail_sem_env_var_e_sem_credencial_no_banco_fica_pendente(self):
        with patch.dict('os.environ', {}, clear=True):
            gmail = next(c for c in cs.status_todos_os_canais(_factory_sem_credencial_gmail()) if c['canal'] == 'Gmail')
        self.assertEqual(gmail['estado'], 'pendente')
        self.assertIsNone(gmail['ultima_sincronizacao'])

    def test_gmail_conectado_pelo_fluxo_oauth_institucional_no_banco_sem_precisar_de_env_var(self):
        quando = datetime.datetime(2026, 2, 10, 12, 0, tzinfo=datetime.timezone.utc)
        with patch.dict('os.environ', {}, clear=True):
            gmail = next(c for c in cs.status_todos_os_canais(_factory_com_credencial_gmail(quando)) if c['canal'] == 'Gmail')
        self.assertEqual(gmail['estado'], 'conectado')
        self.assertEqual(gmail['ultima_sincronizacao'], quando.isoformat())

    def test_gmail_falha_ao_consultar_banco_nao_derruba_o_painel_cai_no_fallback_de_env_var(self):
        def _factory_com_erro():
            def _levantar():
                raise RuntimeError('conexao indisponivel')
            return _levantar
        with patch.dict('os.environ', {'GMAIL_REFRESH_TOKEN': 'r'}, clear=True):
            canais = cs.status_todos_os_canais(_factory_com_erro())
        gmail = next(c for c in canais if c['canal'] == 'Gmail')
        self.assertEqual(gmail['estado'], 'conectado')
        self.assertEqual(len(canais), 6)


class RotaHttp(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.app = Flask(__name__)
        self.autorizado = True
        cs.registrar_rotas_canais(self.app, _factory_sem_banco(), lambda: self.autorizado)
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
