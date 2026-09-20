"""Diagnóstico de canais: estado real, motivo real, e nenhum segredo saindo.

Toda chamada externa é injetada — estes testes nunca tocam a rede.
"""
import json
import unittest

import canais_diagnostico as cd


class _Resposta:
    def __init__(self, corpo, codigo=200):
        self._corpo = corpo
        self.status_code = codigo

    def json(self):
        if self._corpo is None:
            raise ValueError('sem corpo')
        return self._corpo


class _Http:
    """Devolve respostas por trecho de URL, na ordem de registro."""

    def __init__(self, rotas, erro=None):
        self.rotas = rotas
        self.erro = erro
        self.chamadas = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        self.chamadas.append({'url': url, 'params': params or {}, 'headers': headers or {}})
        if self.erro:
            raise self.erro
        for trecho, resposta in self.rotas.items():
            if trecho in url:
                return resposta
        return _Resposta({'error': {'code': 100}}, 404)


ENV_WPP = {
    'WHATSAPP_ACCESS_TOKEN': 'token-secreto-nunca-vaza',
    'WHATSAPP_PHONE_NUMBER_ID': '111',
    'WHATSAPP_BUSINESS_ACCOUNT_ID': '222',
    'META_APP_SECRET': 'segredo-app',
    'META_WEBHOOK_VERIFY_TOKEN': 'verify',
}


def _http_whatsapp_ok(permissoes=('whatsapp_business_messaging', 'whatsapp_business_management'),
                      verificado=True, webhook=True):
    return _Http({
        '/debug_token': _Resposta({'data': {'is_valid': True, 'expires_at': 1790000000,
                                            'scopes': list(permissoes), 'type': 'SYSTEM_USER'}}),
        '/subscribed_apps': _Resposta({'data': [{'whatsapp_business_api_data': {'id': '9'}}] if webhook else []}),
        '/111': _Resposta({'display_phone_number': '+55 98 90000-0000',
                           'code_verification_status': 'VERIFIED' if verificado else 'NOT_VERIFIED',
                           'platform_type': 'CLOUD_API'}),
    })


class Contrato(unittest.TestCase):
    def test_todo_canal_devolve_o_mesmo_conjunto_de_campos(self):
        base = set(cd._base('X').keys())
        for canal in cd.REGISTRO:
            dado = cd.diagnosticar(canal, http=_Http({}), env={})
            self.assertEqual(set(dado.keys()), base, canal)

    def test_estado_sempre_pertence_a_enumeracao_fechada(self):
        for canal in cd.REGISTRO:
            dado = cd.diagnosticar(canal, http=_Http({}), env={})
            self.assertIn(dado['estado'], cd.ESTADOS, canal)

    def test_campo_desconhecido_nasce_nulo_nunca_otimista(self):
        base = cd._base('Qualquer')
        self.assertIsNone(base['webhook_ativo'])
        self.assertIsNone(base['permissoes_concedidas'])
        self.assertIsNone(base['ultima_sincronizacao'])
        self.assertFalse(base['leitura_disponivel'])
        self.assertFalse(base['escrita_disponivel'])

    def test_pendente_generico_foi_aposentado(self):
        self.assertNotIn('pendente', cd.ESTADOS)


class SegredosNuncaVazam(unittest.TestCase):
    def test_diagnostico_nao_carrega_token_nem_segredo(self):
        dado = cd.diagnosticar_whatsapp(_http_whatsapp_ok(), ENV_WPP)
        corpo = json.dumps(dado, ensure_ascii=False)
        for segredo in ENV_WPP.values():
            self.assertNotIn(segredo, corpo)

    def test_falha_de_rede_expoe_so_o_nome_da_excecao(self):
        class ErroComUrl(Exception):
            def __str__(self):
                return 'https://graph.facebook.com/?access_token=SEGREDO'

        dado = cd.diagnosticar_whatsapp(_Http({}, erro=ErroComUrl()), ENV_WPP)
        corpo = json.dumps(dado, ensure_ascii=False)
        self.assertNotIn('SEGREDO', corpo)
        self.assertNotIn('access_token', corpo)
        self.assertEqual(dado['codigo_erro'], 'ErroComUrl')
        self.assertEqual(dado['estado'], 'erro')

    def test_token_vai_no_cabecalho_nunca_na_query(self):
        http = _http_whatsapp_ok()
        cd.diagnosticar_whatsapp(http, ENV_WPP)
        for chamada in http.chamadas:
            if 'debug_token' in chamada['url']:
                continue  # debug_token exige app token como parâmetro, por contrato da Meta
            self.assertNotIn('access_token', chamada['params'])


class WhatsApp(unittest.TestCase):
    def test_sem_variaveis_diz_exatamente_quais_faltam(self):
        dado = cd.diagnosticar_whatsapp(_Http({}), {})
        self.assertEqual(dado['estado'], 'nao_configurado')
        self.assertFalse(dado['verificacao_remota'])
        for nome in ('WHATSAPP_ACCESS_TOKEN', 'META_APP_SECRET', 'META_WEBHOOK_VERIFY_TOKEN'):
            self.assertIn(nome, dado['proximo_passo'])

    def test_tudo_certo_vira_conectado_com_escrita(self):
        dado = cd.diagnosticar_whatsapp(_http_whatsapp_ok(), ENV_WPP)
        self.assertEqual(dado['estado'], 'conectado')
        self.assertTrue(dado['leitura_disponivel'])
        self.assertTrue(dado['escrita_disponivel'])
        self.assertTrue(dado['webhook_ativo'])
        self.assertEqual(dado['conta'], '+55 98 90000-0000')
        self.assertIsNone(dado['proximo_passo'])

    def test_permissao_faltando_vira_aguardando_aprovacao_externa(self):
        dado = cd.diagnosticar_whatsapp(_http_whatsapp_ok(permissoes=('whatsapp_business_messaging',)), ENV_WPP)
        self.assertEqual(dado['estado'], 'aguardando_aprovacao_externa')
        self.assertTrue(dado['aguardando_plataforma'])
        self.assertEqual(dado['permissoes_ausentes'], ['whatsapp_business_management'])
        self.assertIn('Aguardando aprovação da Meta', dado['proximo_passo'])
        self.assertFalse(dado['escrita_disponivel'])

    def test_numero_nao_verificado_vira_conectado_parcial(self):
        dado = cd.diagnosticar_whatsapp(_http_whatsapp_ok(verificado=False), ENV_WPP)
        self.assertEqual(dado['estado'], 'conectado_parcial')
        self.assertIn('verificação do número', dado['proximo_passo'])
        self.assertFalse(dado['escrita_disponivel'])

    def test_webhook_sem_assinatura_vira_conectado_parcial(self):
        dado = cd.diagnosticar_whatsapp(_http_whatsapp_ok(webhook=False), ENV_WPP)
        self.assertEqual(dado['estado'], 'conectado_parcial')
        self.assertFalse(dado['webhook_ativo'])
        self.assertIn('webhook', dado['proximo_passo'])

    def test_token_recusado_vira_token_expirado_com_reconexao(self):
        http = _Http({'/111': _Resposta({'error': {'code': 190}}, 401)})
        dado = cd.diagnosticar_whatsapp(http, ENV_WPP)
        self.assertEqual(dado['estado'], 'token_expirado')
        self.assertTrue(dado['exige_reconexao'])
        self.assertIn('meta_190', dado['codigo_erro'])

    def test_nenhuma_chamada_de_escrita_e_feita(self):
        http = _http_whatsapp_ok()
        cd.diagnosticar_whatsapp(http, ENV_WPP)
        self.assertFalse(hasattr(http, 'post'))
        self.assertTrue(http.chamadas)


class LinkedIn(unittest.TestCase):
    ENV = {'LINKEDIN_CLIENT_ID': 'id', 'LINKEDIN_ACCESS_TOKEN': 'tok'}

    def test_sem_app_pede_o_app_antes_do_oauth(self):
        dado = cd.diagnosticar_linkedin(_Http({}), {})
        self.assertEqual(dado['estado'], 'nao_configurado')
        self.assertIn('Developer Portal', dado['proximo_passo'])

    def test_sem_token_pede_autorizacao_nao_erro(self):
        dado = cd.diagnosticar_linkedin(_Http({}), {'LINKEDIN_CLIENT_ID': 'id'})
        self.assertEqual(dado['estado'], 'aguardando_autorizacao')

    def test_so_perfil_pessoal_nao_e_conectado(self):
        http = _Http({'/userinfo': _Resposta({'name': 'Cássio'}),
                      '/organizationAcls': _Resposta({'elements': []})})
        dado = cd.diagnosticar_linkedin(http, self.ENV)
        self.assertEqual(dado['estado'], 'conectado_parcial')
        self.assertEqual(dado['tipo_conta'], 'Perfil pessoal')
        self.assertFalse(dado['escrita_disponivel'])
        self.assertIn('w_organization_social', dado['permissoes_ausentes'])
        self.assertIn('Maranhão Cordial', dado['proximo_passo'])

    def test_pagina_administrada_sem_urn_pede_so_a_variavel(self):
        http = _Http({'/userinfo': _Resposta({'name': 'Cássio'}),
                      '/organizationAcls': _Resposta({'elements': [
                          {'organization~': {'localizedName': 'Maranhão Cordial'}}]})})
        dado = cd.diagnosticar_linkedin(http, self.ENV)
        self.assertEqual(dado['estado'], 'conectado_parcial')
        self.assertEqual(dado['tipo_conta'], 'Página empresarial')
        self.assertIn('LINKEDIN_ORGANIZATION_URN', dado['proximo_passo'])

    def test_pagina_com_urn_libera_escrita_sempre_com_aprovacao(self):
        http = _Http({'/userinfo': _Resposta({'name': 'Cássio'}),
                      '/organizationAcls': _Resposta({'elements': [
                          {'organization~': {'localizedName': 'Maranhão Cordial'}}]})})
        dado = cd.diagnosticar_linkedin(http, dict(self.ENV, LINKEDIN_ORGANIZATION_URN='urn:li:organization:1'))
        self.assertEqual(dado['estado'], 'conectado')
        self.assertTrue(dado['escrita_disponivel'])
        self.assertTrue(dado['aprovacao_exigida'])

    def test_token_revogado_pede_reconexao(self):
        dado = cd.diagnosticar_linkedin(_Http({'/userinfo': _Resposta(None, 401)}), self.ENV)
        self.assertEqual(dado['estado'], 'token_expirado')
        self.assertTrue(dado['exige_reconexao'])


class TikTok(unittest.TestCase):
    def test_shop_e_social_sao_canais_distintos(self):
        self.assertIn('TikTok Shop', cd.REGISTRO)
        self.assertIn('TikTok Social', cd.REGISTRO)
        shop = cd.diagnosticar_tiktok_shop(_Http({}), {})
        social = cd.diagnosticar_tiktok_social(_Http({}), {})
        self.assertEqual(shop['grupo'], 'comercial')
        self.assertEqual(social['grupo'], 'social')

    def test_shop_sem_app_aponta_o_partner_center(self):
        dado = cd.diagnosticar_tiktok_shop(_Http({}), {})
        self.assertEqual(dado['estado'], 'nao_configurado')
        self.assertIn('partner.tiktokshop.com', dado['proximo_passo'])

    def test_shop_com_app_mas_sem_loja_pede_autorizacao_da_loja(self):
        dado = cd.diagnosticar_tiktok_shop(_Http({}), {'TIKTOK_SHOP_APP_KEY': 'k', 'TIKTOK_SHOP_APP_SECRET': 's'})
        self.assertEqual(dado['estado'], 'aguardando_autorizacao')
        self.assertIn('Seller Center', dado['proximo_passo'])

    def test_shop_autorizado_lista_a_loja(self):
        http = _Http({'/shops': _Resposta({'data': {'shops': [{'name': 'Maranhão Cordial'}]}})})
        dado = cd.diagnosticar_tiktok_shop(http, {'TIKTOK_SHOP_APP_KEY': 'k', 'TIKTOK_SHOP_APP_SECRET': 's',
                                                  'TIKTOK_SHOP_ACCESS_TOKEN': 't'})
        self.assertEqual(dado['estado'], 'conectado')
        self.assertEqual(dado['conta'], 'Maranhão Cordial')
        self.assertTrue(dado['leitura_disponivel'])


class NaoPriorizados(unittest.TestCase):
    def test_pinterest_e_x_declaram_motivo_em_vez_de_pendencia_eterna(self):
        for funcao in (cd.diagnosticar_pinterest, cd.diagnosticar_x):
            dado = funcao(_Http({}), {})
            self.assertEqual(dado['estado'], 'nao_priorizado')
            self.assertTrue(dado['motivo_nao_priorizado'])
            self.assertTrue(dado['proximo_passo'])

    def test_x_declara_o_custo_sem_assumi_lo(self):
        dado = cd.diagnosticar_x(_Http({}), {})
        self.assertIn('plano pago', dado['motivo_nao_priorizado'])
        self.assertIn('Nenhum custo foi assumido', dado['proximo_passo'])


class FalhaIsolada(unittest.TestCase):
    def test_excecao_inesperada_nao_derruba_o_painel(self):
        class Explode:
            def get(self, *a, **k):
                raise RuntimeError('boom')

        dado = cd.diagnosticar('WhatsApp', http=Explode(), env=ENV_WPP)
        self.assertEqual(dado['estado'], 'erro')
        self.assertEqual(dado['codigo_erro'], 'RuntimeError')

    def test_canal_desconhecido_nao_quebra(self):
        dado = cd.diagnosticar('Telex', http=_Http({}), env={})
        self.assertEqual(dado['estado'], 'nao_configurado')


if __name__ == '__main__':
    unittest.main()


class OrcamentoDeTempo(unittest.TestCase):
    """O painel consulta vários canais em sequência: a soma dos piores casos
    não pode estourar o limite de requisição do servidor."""

    def test_timeout_por_chamada_cabe_no_orcamento_total(self):
        # Pior caso do canal mais pesado (WhatsApp faz até 3 chamadas).
        self.assertLessEqual(cd.TIMEOUT * 3, cd.ORCAMENTO_SEGUNDOS)
        self.assertLessEqual(cd.ORCAMENTO_SEGUNDOS, 30)

    def test_canal_fora_do_orcamento_diz_que_nao_foi_consultado(self):
        dado = cd.nao_verificado('LinkedIn', 'orcamento_de_tempo_esgotado')
        self.assertEqual(dado['estado'], 'erro')
        self.assertEqual(dado['ultimo_erro'], 'nao_consultado_nesta_leitura')
        self.assertFalse(dado['leitura_disponivel'])
        self.assertFalse(dado['verificacao_remota'])
        self.assertIn('Diagnosticar', dado['proximo_passo'])
        self.assertEqual(set(dado.keys()), set(cd._base('X').keys()))

    def test_todo_get_leva_timeout_explicito(self):
        http = _http_whatsapp_ok()
        cd.diagnosticar_whatsapp(http, ENV_WPP)
        self.assertTrue(http.chamadas)
