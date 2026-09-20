"""Autorização de canais: CSRF por state, segredo cifrado, nada vazando.

SQL real e isolado; nenhuma chamada de rede — o cliente HTTP é injetado.
"""
import json
import logging
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import canais_credenciais as cc
import meta_oauth
from canais_credenciais import ChaveIndisponivel, EstadoOAuthInvalido

CHAVE = {'CANAIS_CRYPTO_KEY': 'chave-de-teste-suficientemente-longa'}
CONFIG_META = dict(CHAVE, META_APP_ID='123456', META_APP_SECRET='segredo-do-app')


class _Linha(dict):
    """Aceita acesso por nome e por posição, como o cursor real do psycopg2
    em seus dois modos."""

    def __init__(self, linha):
        super().__init__({k: _converter(k, linha[k]) for k in linha.keys()})
        self._ordem = list(linha.keys())

    def __getitem__(self, chave):
        if isinstance(chave, int):
            return super().__getitem__(self._ordem[chave])
        return super().__getitem__(chave)


def _converter(nome, valor):
    """SQLite devolve TIMESTAMPTZ como texto; o código compara com datetime."""
    if isinstance(valor, str) and nome.endswith(('_em',)) and re.match(r'^\d{4}-\d{2}-\d{2}', valor):
        from datetime import datetime, timezone
        try:
            return datetime.fromisoformat(valor.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
        except ValueError:
            return valor
    return valor


class _Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        sql = sql.replace('%s', '?').replace(' FOR UPDATE', '')
        args = [json.dumps(v.adapted) if hasattr(v, 'adapted') else v for v in args]
        if 'make_interval' in sql:
            # SQLite não tem make_interval; o argumento das horas sai junto.
            sql = re.sub(r"NOW\(\) - make_interval\(hours => \?\)", "datetime('now','-1 day')", sql)
            args = []
        self.cur = self.db.execute(sql, list(args))
        self.rowcount = self.cur.rowcount

    def fetchone(self):
        linha = self.cur.fetchone()
        return _Linha(linha) if linha else None

    def fetchall(self):
        return [_Linha(l) for l in self.cur.fetchall()]


class _Conn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, exc, *a):
        self.db.rollback() if exc else self.db.commit()
        return False

    def cursor(self, **kw):
        return _Cursor(self.db)

    def close(self):
        pass


class Banco:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'oauth.db')
        conn = sqlite3.connect(self.path)
        bruto = Path('migrations/028_credenciais_canal.sql').read_text()
        bruto = '\n'.join(l for l in bruto.splitlines() if not l.strip().startswith('--'))
        for comando in bruto.split(';'):
            limpo = comando.strip()
            if not limpo.upper().startswith('CREATE'):
                continue
            conn.executescript(limpo.replace('BYTEA', 'BLOB').replace('JSONB', 'TEXT')
                               .replace('DEFAULT NOW()', 'DEFAULT CURRENT_TIMESTAMP')
                               .replace("'{}'::jsonb", "'{}'") + ';')
        conn.close()
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('NOW', 0, lambda: '2026-09-20 12:00:00')

    def __call__(self):
        return _Conn(self.db)

    def rows(self, tabela):
        return [dict(l) for l in self.db.execute('SELECT * FROM ' + tabela)]

    def close(self):
        self.db.close()
        self.temp.cleanup()


class _Resposta:
    def __init__(self, corpo, codigo=200):
        self._corpo = corpo
        self.status_code = codigo

    def json(self):
        return self._corpo


class _Http:
    def __init__(self, rotas):
        self.rotas = rotas
        self.chamadas = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        self.chamadas.append({'url': url, 'params': params or {}, 'headers': headers or {}})
        for trecho, resposta in self.rotas.items():
            if trecho in url or trecho in json.dumps(params or {}):
                return resposta
        return _Resposta({'error': {'code': 100}}, 400)


class _Base(unittest.TestCase):
    def setUp(self):
        self.banco = Banco()
        self.addCleanup(self.banco.close)


class Estado(_Base):
    def test_state_e_guardado_so_como_hash(self):
        state = cc.criar_estado(self.banco, canal='Instagram', navegador='nav', redirect_uri='/cb')
        guardado = self.banco.rows('oauth_estados_canal')[0]
        self.assertNotEqual(guardado['state_hash'], state)
        self.assertNotIn(state, json.dumps(guardado))
        self.assertEqual(len(guardado['state_hash']), 64)

    def test_state_valido_so_uma_vez(self):
        state = cc.criar_estado(self.banco, canal='Instagram', navegador='nav', redirect_uri='/cb')
        self.assertEqual(cc.consumir_estado(self.banco, canal='Instagram', state=state,
                                            navegador='nav')['redirect_uri'], '/cb')
        with self.assertRaises(EstadoOAuthInvalido) as ctx:
            cc.consumir_estado(self.banco, canal='Instagram', state=state, navegador='nav')
        self.assertTrue(getattr(ctx.exception, 'ja_consumido', False))

    def test_state_de_outro_navegador_e_recusado(self):
        state = cc.criar_estado(self.banco, canal='Instagram', navegador='nav-a', redirect_uri='/cb')
        with self.assertRaises(EstadoOAuthInvalido):
            cc.consumir_estado(self.banco, canal='Instagram', state=state, navegador='nav-b')

    def test_state_de_outro_canal_e_recusado(self):
        state = cc.criar_estado(self.banco, canal='Instagram', navegador='nav', redirect_uri='/cb')
        with self.assertRaises(EstadoOAuthInvalido):
            cc.consumir_estado(self.banco, canal='LinkedIn', state=state, navegador='nav')

    def test_state_desconhecido_e_vazio_sao_recusados(self):
        for valor in ('inventado', '', None):
            with self.assertRaises(EstadoOAuthInvalido):
                cc.consumir_estado(self.banco, canal='Instagram', state=valor, navegador='nav')

    def test_resultado_fica_disponivel_para_o_callback_repetido(self):
        state = cc.criar_estado(self.banco, canal='Instagram', navegador='nav', redirect_uri='/cb')
        cc.consumir_estado(self.banco, canal='Instagram', state=state, navegador='nav')
        cc.registrar_resultado(self.banco, state=state, resultado='ok')
        with self.assertRaises(EstadoOAuthInvalido) as ctx:
            cc.consumir_estado(self.banco, canal='Instagram', state=state, navegador='nav')
        self.assertEqual(getattr(ctx.exception, 'resultado', None), 'ok')


class Credenciais(_Base):
    def test_segredo_nunca_fica_em_texto_puro(self):
        cc.salvar(self.banco, canal='Instagram', nome='INSTAGRAM_ACCESS_TOKEN',
                  segredo='TOKEN-SECRETO-123', env=CHAVE)
        linha = self.banco.rows('credenciais_canal')[0]
        bruto = bytes(linha['segredo_cifrado'])
        self.assertNotIn(b'TOKEN-SECRETO-123', bruto)
        self.assertNotIn('TOKEN-SECRETO-123', json.dumps(linha, default=str))

    def test_ida_e_volta_preserva_o_segredo(self):
        cc.salvar(self.banco, canal='Instagram', nome='INSTAGRAM_ACCESS_TOKEN',
                  segredo='TOKEN-SECRETO-123', env=CHAVE)
        self.assertEqual(cc.ler(self.banco, canal='Instagram', nome='INSTAGRAM_ACCESS_TOKEN',
                                env=CHAVE), 'TOKEN-SECRETO-123')

    def test_sem_chave_recusa_em_vez_de_gravar_texto_puro(self):
        with self.assertRaises(ChaveIndisponivel):
            cc.salvar(self.banco, canal='Instagram', nome='X', segredo='t', env={})
        self.assertEqual(self.banco.rows('credenciais_canal'), [])

    def test_chave_trocada_nao_devolve_lixo(self):
        cc.salvar(self.banco, canal='Instagram', nome='T', segredo='abc', env=CHAVE)
        self.assertIsNone(cc.ler(self.banco, canal='Instagram', nome='T',
                                 env={'CANAIS_CRYPTO_KEY': 'outra-chave-totalmente-diferente'}))

    def test_ambiente_tem_precedencia_sobre_o_banco(self):
        cc.salvar(self.banco, canal='Instagram', nome='INSTAGRAM_ACCESS_TOKEN',
                  segredo='do-banco', env=CHAVE)
        env = dict(CHAVE, INSTAGRAM_ACCESS_TOKEN='do-render')
        self.assertEqual(cc.ler(self.banco, canal='Instagram',
                                nome='INSTAGRAM_ACCESS_TOKEN', env=env), 'do-render')

    def test_painel_ve_metadado_e_nunca_o_segredo(self):
        cc.salvar(self.banco, canal='Instagram', nome='INSTAGRAM_ACCESS_TOKEN',
                  segredo='TOKEN-SECRETO-123', metadados={'conta': '@maranhaocordial'}, env=CHAVE)
        descricao = cc.descrever(self.banco, canal='Instagram')
        corpo = json.dumps(descricao, ensure_ascii=False)
        self.assertIn('@maranhaocordial', corpo)
        self.assertNotIn('TOKEN-SECRETO-123', corpo)

    def test_salvar_duas_vezes_atualiza_sem_duplicar(self):
        for valor in ('primeiro', 'segundo'):
            cc.salvar(self.banco, canal='Instagram', nome='T', segredo=valor, env=CHAVE)
        self.assertEqual(len(self.banco.rows('credenciais_canal')), 1)
        self.assertEqual(cc.ler(self.banco, canal='Instagram', nome='T', env=CHAVE), 'segundo')


PAGINAS = _Resposta({'data': [{'id': '9', 'name': 'Maranhão Cordial',
                               'access_token': 'TOKEN-DE-PAGINA',
                               'instagram_business_account': {'id': '178414', 'username': 'maranhaocordial'}}]})
PERFIL = _Resposta({'username': 'maranhaocordial', 'name': 'Maranhão Cordial', 'followers_count': 10})


def _http_meta_ok():
    return _Http({'fb_exchange_token': _Resposta({'access_token': 'TOKEN-LONGO', 'expires_in': 5184000}),
                  '/oauth/access_token': _Resposta({'access_token': 'TOKEN-CURTO', 'expires_in': 3600}),
                  '/me/accounts': PAGINAS, '/178414': PERFIL})


class FluxoMeta(_Base):
    def test_url_de_autorizacao_nao_carrega_segredo(self):
        url = meta_oauth.montar_url_autorizacao(redirect_uri='https://x/cb', state='st',
                                                env=CONFIG_META)
        self.assertIn('client_id=123456', url)
        self.assertIn('state=st', url)
        self.assertNotIn('segredo-do-app', url)
        self.assertNotIn('client_secret', url)
        self.assertIn('instagram_basic', url)

    def test_escopo_de_mensagens_fica_fora_do_dialogo(self):
        # Pedir instagram_manage_messages sem App Review faria o diálogo falhar.
        url = meta_oauth.montar_url_autorizacao(redirect_uri='https://x/cb', state='st', env=CONFIG_META)
        self.assertNotIn('instagram_manage_messages', url)

    def test_configuracao_incompleta_e_relatada_por_nome(self):
        self.assertEqual(meta_oauth.faltantes({}), ['META_APP_ID', 'META_APP_SECRET'])
        self.assertEqual(meta_oauth.faltantes({'META_APP_ID': '1'}), ['META_APP_SECRET'])

    def test_conclusao_grava_cifrado_e_devolve_resumo_sem_token(self):
        resumo = meta_oauth.concluir(_http_meta_ok(), self.banco, codigo='CODIGO-OAUTH',
                                     redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertEqual(resumo['conta'], '@maranhaocordial')
        self.assertEqual(resumo['pagina'], 'Maranhão Cordial')
        corpo = json.dumps(resumo, ensure_ascii=False)
        for segredo in ('TOKEN-DE-PAGINA', 'TOKEN-LONGO', 'TOKEN-CURTO', 'CODIGO-OAUTH'):
            self.assertNotIn(segredo, corpo)
        guardado = json.dumps(self.banco.rows('credenciais_canal'), default=str)
        self.assertNotIn('TOKEN-DE-PAGINA', guardado)

    def test_token_de_pagina_e_o_que_fica_guardado(self):
        meta_oauth.concluir(_http_meta_ok(), self.banco, codigo='c',
                            redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertEqual(cc.ler(self.banco, canal='Instagram',
                                nome='INSTAGRAM_ACCESS_TOKEN', env=CHAVE), 'TOKEN-DE-PAGINA')
        self.assertEqual(cc.ler(self.banco, canal='Instagram',
                                nome='INSTAGRAM_ACCOUNT_ID', env=CHAVE), '178414')

    def test_sem_pagina_com_instagram_nada_e_gravado(self):
        http = _Http({'fb_exchange_token': _Resposta({'access_token': 'L'}),
                      '/oauth/access_token': _Resposta({'access_token': 'C'}),
                      '/me/accounts': _Resposta({'data': [{'id': '9', 'name': 'Sem IG'}]})})
        with self.assertRaises(ValueError) as ctx:
            meta_oauth.concluir(http, self.banco, codigo='c', redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertIn('nenhuma_pagina_com_instagram', str(ctx.exception))
        self.assertEqual(self.banco.rows('credenciais_canal'), [])

    def test_erro_190_da_meta_nao_grava_credencial(self):
        http = _Http({'fb_exchange_token': _Resposta({'access_token': 'L'}),
                      '/oauth/access_token': _Resposta({'access_token': 'C'}),
                      '/me/accounts': _Resposta({'error': {'code': 190}}, 401)})
        with self.assertRaises(ValueError) as ctx:
            meta_oauth.concluir(http, self.banco, codigo='c', redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertIn('190', str(ctx.exception))
        self.assertEqual(self.banco.rows('credenciais_canal'), [])

    def test_leitura_autenticada_falha_impede_marcar_conectado(self):
        http = _Http({'fb_exchange_token': _Resposta({'access_token': 'L'}),
                      '/oauth/access_token': _Resposta({'access_token': 'C'}),
                      '/me/accounts': PAGINAS, '/178414': _Resposta({'error': {'code': 100}}, 400)})
        with self.assertRaises(ValueError) as ctx:
            meta_oauth.concluir(http, self.banco, codigo='c', redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertIn('consulta_autenticada_recusada', str(ctx.exception))
        self.assertEqual(self.banco.rows('credenciais_canal'), [])

    def test_mensagem_de_erro_nunca_carrega_codigo_ou_token(self):
        http = _Http({'/oauth/access_token': _Resposta({'error': {'code': 191}}, 400)})
        with self.assertRaises(ValueError) as ctx:
            meta_oauth.concluir(http, self.banco, codigo='CODIGO-OAUTH-SECRETO',
                                redirect_uri='https://x/cb', env=CONFIG_META)
        self.assertNotIn('CODIGO-OAUTH-SECRETO', str(ctx.exception))
        self.assertNotIn('segredo-do-app', str(ctx.exception))

    def test_troca_de_codigo_ocorre_sempre_no_servidor(self):
        http = _http_meta_ok()
        meta_oauth.concluir(http, self.banco, codigo='c', redirect_uri='https://x/cb', env=CONFIG_META)
        trocas = [c for c in http.chamadas if '/oauth/access_token' in c['url']]
        self.assertEqual(len(trocas), 2, 'token curto e depois o de longa duração')
        self.assertTrue(all('client_secret' in c['params'] for c in trocas))


class NadaVazaEmLog(_Base):
    def test_conclusao_nao_registra_token_nem_codigo_no_log(self):
        registro = logging.getLogger('teste-oauth')
        with self.assertLogs(registro, level='DEBUG') as capturado:
            registro.info('inicio')
            meta_oauth.concluir(_http_meta_ok(), self.banco, codigo='CODIGO-OAUTH',
                                redirect_uri='https://x/cb', env=CONFIG_META)
        texto = '\n'.join(capturado.output)
        for segredo in ('CODIGO-OAUTH', 'TOKEN-DE-PAGINA', 'TOKEN-LONGO', 'segredo-do-app'):
            self.assertNotIn(segredo, texto)

    def test_modulo_nao_imprime_nada(self):
        fonte = Path('meta_oauth.py').read_text()
        self.assertNotIn('print(', fonte)
        for proibido in ("logger.info('%s', token", 'access_token=', 'code='):
            self.assertNotIn(proibido, fonte)


class Higiene(_Base):
    def test_limpeza_remove_o_antigo_e_preserva_o_em_uso(self):
        # Um estado recém-criado está em uso: apagá-lo quebraria um fluxo
        # de autorização em andamento.
        cc.criar_estado(self.banco, canal='Instagram', navegador='n', redirect_uri='/cb')
        self.banco.db.execute(
            "INSERT INTO oauth_estados_canal(state_hash,canal,navegador_hash,redirect_uri,criado_em) "
            "VALUES('antigo','Instagram','h','/cb','2020-01-01 00:00:00')")
        self.banco.db.commit()
        self.assertEqual(len(self.banco.rows('oauth_estados_canal')), 2)
        cc.limpar_estados_antigos(self.banco, horas=24)
        restantes = self.banco.rows('oauth_estados_canal')
        self.assertEqual(len(restantes), 1)
        self.assertNotEqual(restantes[0]['state_hash'], 'antigo')


if __name__ == '__main__':
    unittest.main()
