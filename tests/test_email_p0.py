"""Testes offline: extrai funções via AST, sem importar/inicializar main.py."""
import ast
import base64
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from flask import Flask, jsonify, request, session, redirect
import email_seguranca as seguranca

ROOT = Path(__file__).resolve().parents[1]


def carregar_funcoes(arquivo, nomes, namespace):
    arvore = ast.parse((ROOT / arquivo).read_text())
    nos = []
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in nomes:
            no.decorator_list = []
            nos.append(no)
    assert len(nos) == len(nomes), nomes
    exec(compile(ast.Module(body=nos, type_ignores=[]), arquivo, "exec"), namespace)
    return namespace


class Banco:
    """Duplo em memória; não acessa PostgreSQL nem credenciais locais."""
    def __init__(self):
        self.pausado = False
        self.supressoes = set()
        self.eventos = set()
        self.estados = {}
        self.sql = []
        self.resultado = None

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass

    def cursor(self, **kwargs):
        return self

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.sql.append((sql, params))
        self.resultado = None
        if sql.startswith("SELECT pausado"):
            self.resultado = (self.pausado,)
        elif sql.startswith("SELECT email FROM email_supressoes"):
            self.resultado = next(((a,) for a in params[0] if a in self.supressoes), None)
        elif sql.startswith("UPDATE email_controle"):
            self.pausado = params[0]
        elif sql.startswith("INSERT INTO email_supressoes"):
            self.supressoes.add(params[0])
        elif sql.startswith("INSERT INTO email_eventos"):
            self.eventos.add(params)
        elif sql.startswith("INSERT INTO gmail_oauth_estados"):
            self.estados[params[0]] = (params[1], params[2])
        elif sql.startswith("SELECT verifier"):
            valor = self.estados.get(params[0])
            if valor and valor[0] == params[1]:
                self.resultado = (valor[1],)
        elif sql.startswith("UPDATE gmail_oauth_estados"):
            self.estados[params[0]] = None

    def fetchone(self):
        return self.resultado


def dsn(codigo="5.1.1", acao="failed", email="ruim@example.com", original=True):
    anexo = '''--limite
Content-Type: message/rfc822

Message-ID: <original@example.com>
From: contato@maranhaocordial.com.br
To: ruim@example.com
Subject: Contato

Mensagem original.
''' if original else ""
    return f'''From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="limite"

--limite
Content-Type: text/plain

Endereço não encontrado
--limite
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; {email}
Action: {acao}
Status: {codigo}
Diagnostic-Code: smtp; 550 recipient failure

{anexo}--limite--
'''.encode()


def resposta_json(dados):
    return Mock(json=Mock(return_value=dados), raise_for_status=Mock())


class Offline(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch("socket.socket.connect", side_effect=AssertionError("Rede proibida nos testes")).start()
        self.banco = Banco()


class Travas(Offline):
    def test_chaves_ausentes_nunca_autorizam(self):
        for chave in (None, "", " ", "errada"):
            self.assertFalse(seguranca.admin_autorizado(chave, {}))

    def test_aliases_administrativos_e_comparacao_exata(self):
        for nome in ("ADMIN_API_KEY", "ADMIN_KEY", "ADMIN_SECRET", "PAINEL_ADMIN_KEY"):
            self.assertTrue(seguranca.admin_autorizado("segredo", {nome: "segredo"}))
            self.assertFalse(seguranca.admin_autorizado("segredo ", {nome: "segredo"}))

    def test_alias_antigo_nao_sobrepoe_chave_canonica(self):
        self.assertFalse(seguranca.admin_autorizado("antiga", {"ADMIN_API_KEY": "atual", "ADMIN_KEY": "antiga"}))

    def test_endereco_valido_sem_bounce_permanece_liberado(self):
        seguranca.verificar_envio(self.banco, "Pessoa <boa@example.com>")
        self.assertFalse(self.banco.eventos)

    def test_pausa_ambiente_bloqueia_antes_do_banco(self):
        for valor in ("true", "1", "valor_invalido", ""):
            with patch.dict(os.environ, {"EMAIL_ENVIOS_PAUSADOS": valor}):
                banco = Mock()
                with self.assertRaises(seguranca.EnvioBloqueado):
                    seguranca.verificar_envio(banco, "boa@example.com")
                banco.assert_not_called()

    def test_pausa_persistente_e_retomada_preservam_supressao(self):
        self.banco.supressoes.add("ruim@example.com")
        seguranca.definir_pausa(self.banco, True, "Pausa de segurança")
        with self.assertRaises(seguranca.EnvioBloqueado):
            seguranca.verificar_envio(self.banco, "boa@example.com")
        seguranca.definir_pausa(self.banco, False, "Revisão concluída")
        seguranca.verificar_envio(self.banco, "boa@example.com")
        with self.assertRaises(seguranca.EnvioBloqueado):
            seguranca.verificar_envio(self.banco, "ruim@example.com")
        self.assertEqual(len(self.banco.eventos), 2)

    def test_pausa_exige_booleano_e_motivo(self):
        for valor, motivo in (("false", "motivo"), (False, ""), (None, "motivo")):
            with self.assertRaises(ValueError):
                seguranca.definir_pausa(self.banco, valor, motivo)

    def test_supressao_em_to_multiplos_e_cc(self):
        self.banco.supressoes.add("ruim@example.com")
        for to, cc in (("RUIM@example.com", None), ("boa@example.com, ruim@example.com", None), ("boa@example.com", "Ruim <ruim@example.com>")):
            with self.assertRaises(seguranca.EnvioBloqueado):
                seguranca.verificar_envio(self.banco, to, cc)

    def test_destinatarios_invalidos_e_injecao_header(self):
        for valor in ("", "invalido", "a@example.com\nBcc: x@example.com", None):
            with self.assertRaises(seguranca.EnvioBloqueado):
                seguranca.verificar_envio(self.banco, valor)

    def test_banco_indisponivel_falha_fechado(self):
        with self.assertRaises(RuntimeError):
            seguranca.verificar_envio(Mock(side_effect=RuntimeError("indisponível")), "boa@example.com")

    def test_supressao_idempotente_sem_apagar_historico(self):
        falha = seguranca.extrair_hard_bounces(dsn())[0]
        for _ in range(2):
            seguranca.registrar_hard_bounce(self.banco, falha, "dsn-1", "sent-1")
        self.assertEqual(self.banco.supressoes, {"ruim@example.com"})
        self.assertEqual(len(self.banco.eventos), 1)
        self.assertFalse(any(sql.startswith(("DELETE", "DROP", "TRUNCATE")) for sql, _ in self.banco.sql))


class Bounces(Offline):
    def test_hard_bounce_estruturado(self):
        falhas = seguranca.extrair_hard_bounces(dsn())
        self.assertEqual(falhas[0]["email"], "ruim@example.com")
        self.assertEqual(falhas[0]["original_id"], "<original@example.com>")

    def test_temporario_bloqueio_caixa_cheia_e_entrega_nao_suprimem(self):
        for codigo, acao in (("4.1.1", "delayed"), ("5.7.1", "failed"), ("5.2.2", "failed"), ("2.0.0", "delivered"), ("5.1.1", "delayed")):
            self.assertEqual(seguranca.extrair_hard_bounces(dsn(codigo, acao)), [])

    def test_texto_e_dsn_sem_original_nao_confirmam(self):
        for raw in (b"Subject: Endereco nao encontrado\n\nMensagem bloqueada", dsn(original=False), dsn().replace(b"mailer-daemon@", b"pessoa@")):
            self.assertEqual(seguranca.extrair_hard_bounces(raw), [])

    def test_confere_original_em_sent_antes_de_suprimir(self):
        http = Mock()
        http.get.side_effect = [
            resposta_json({"raw": base64.urlsafe_b64encode(dsn()).decode()}),
            resposta_json({"messages": [{"id": "sent-1"}]}),
            resposta_json({"labelIds": ["SENT"], "payload": {"headers": [
                {"name": "Message-ID", "value": "<original@example.com>"},
                {"name": "To", "value": "ruim@example.com"}]}}),
        ]
        self.assertTrue(seguranca.processar_dsn_gmail({"id": "dsn-1", "payload": {"mimeType": "multipart/report"}}, {}, self.banco, http))
        self.assertIn("ruim@example.com", self.banco.supressoes)
        http.post.assert_not_called()

    def test_original_ausente_nao_suprime(self):
        http = Mock()
        http.get.side_effect = [resposta_json({"raw": base64.urlsafe_b64encode(dsn()).decode()}), resposta_json({"messages": []})]
        seguranca.processar_dsn_gmail({"id": "dsn-1", "payload": {"mimeType": "multipart/report"}}, {}, self.banco, http)
        self.assertFalse(self.banco.supressoes)

    def test_original_divergente_nao_suprime(self):
        for labels, message_id, to in (([], "<original@example.com>", "ruim@example.com"), (["SENT"], "<outro@example.com>", "ruim@example.com"), (["SENT"], "<original@example.com>", "outra@example.com")):
            http = Mock()
            http.get.side_effect = [resposta_json({"raw": base64.urlsafe_b64encode(dsn()).decode()}), resposta_json({"messages": [{"id": "sent-1"}]}), resposta_json({"labelIds": labels, "payload": {"headers": [{"name": "Message-ID", "value": message_id}, {"name": "To", "value": to}]}})]
            seguranca.processar_dsn_gmail({"id": "dsn-1", "payload": {"mimeType": "multipart/report"}}, {}, self.banco, http)
            self.assertFalse(self.banco.supressoes)

    def test_resposta_normal_nao_e_dsn(self):
        http = Mock()
        self.assertFalse(seguranca.processar_dsn_gmail({"payload": {"mimeType": "text/plain"}}, {}, self.banco, http))
        http.get.assert_not_called()


class Rotas(Offline):
    def setUp(self):
        super().setUp()
        os.environ["FLASK_SECRET_KEY"] = "segredo-persistente-exclusivamente-sintetico"
        self.app = Flask(__name__)
        self.app.secret_key = "somente-testes"
        self.ns = dict(request=request, session=session, jsonify=jsonify, redirect=redirect,
                       admin_autorizado=seguranca.admin_autorizado, definir_pausa=seguranca.definir_pausa,
                       get_db_connection=self.banco, consumir_oauth=Mock(side_effect=ValueError("expirado")),
                       Flow=Mock(), os=os, ADMIN_API_KEY="chave-teste",
                       validar_config_oauth_p0=seguranca.validar_config_oauth_p0,
                       GMAIL_REDIRECT_URI="https://example.com/api/gmail/callback")
        nomes = ["validar_admin_request", "proteger_administracao_p0", "gmail_conectar", "gmail_callback", "gmail_sincronizar", "admin_email_seguranca_p0", "testar_email_institucional_admin"]
        carregar_funcoes("main.py", nomes, self.ns)
        self.app.before_request(self.ns["proteger_administracao_p0"])
        for path, nome, methods in (("/api/gmail/conectar", "gmail_conectar", ["GET", "POST"]), ("/api/gmail/sincronizar", "gmail_sincronizar", ["GET"]), ("/api/gmail/callback", "gmail_callback", ["GET"]), ("/api/admin/email/seguranca", "admin_email_seguranca_p0", ["POST"]), ("/api/admin/testar-email-institucional", "testar_email_institucional_admin", ["POST"])):
            self.app.add_url_rule(path, nome, self.ns[nome], methods=methods)
        self.client = self.app.test_client()

    def test_rotas_sensiveis_sem_chave(self):
        for path, method in (("/api/gmail/conectar", "get"), ("/api/gmail/sincronizar", "get"), ("/api/admin/email/seguranca", "post"), ("/api/admin/testar-email-institucional", "post")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 401)
        self.assertFalse(self.banco.sql)
        self.ns["Flow"].assert_not_called()

    def test_rota_teste_falha_fechado_sem_configuracao(self):
        self.ns["ADMIN_API_KEY"] = None
        self.assertEqual(self.client.post("/api/admin/testar-email-institucional").status_code, 401)

    def test_rota_pausa_autorizada(self):
        r = self.client.post("/api/admin/email/seguranca", headers={"X-Admin-Key": "chave-teste"}, json={"pausado": True, "motivo": "teste sintético"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.banco.pausado)

    def test_callback_sem_estado_nao_troca_token(self):
        self.assertEqual(self.client.get("/api/gmail/callback?state=forjado&code=x").status_code, 400)
        self.ns["consumir_oauth"].assert_not_called()
        self.ns["Flow"].from_client_config.assert_not_called()

    def test_callback_estado_divergente(self):
        with self.client.session_transaction() as s:
            s["gmail_oauth_state"] = "correto"
            s["gmail_oauth_navegador"] = "nonce"
        self.assertEqual(self.client.get("/api/gmail/callback?state=errado").status_code, 400)
        self.ns["consumir_oauth"].assert_not_called()

    def test_callback_expirado(self):
        with self.client.session_transaction() as s:
            s["gmail_oauth_state"] = "correto"
            s["gmail_oauth_navegador"] = "nonce"
        self.assertEqual(self.client.get("/api/gmail/callback?state=correto").status_code, 400)
        self.ns["Flow"].from_client_config.assert_not_called()

    def test_callback_valido_preserva_segredos_no_servidor(self):
        cred = SimpleNamespace(refresh_token="refresh-sintetico", token_uri="https://oauth.example/token", client_id="cliente", client_secret="segredo-sintetico", scopes=["gmail.send"])
        flow = Mock(credentials=cred)
        self.ns.update(GMAIL_CLIENT_CONFIG={}, GMAIL_SCOPES=[], GMAIL_REDIRECT_URI="https://example.com/api/gmail/callback", build=Mock())
        self.ns["Flow"].from_client_config.return_value = flow
        self.ns["build"]().users().getProfile().execute.return_value = {"emailAddress": "contato@maranhaocordial.com.br"}
        self.ns["consumir_oauth"] = Mock(return_value="verifier")
        with self.client.session_transaction() as s:
            s["gmail_oauth_state"] = "correto"
            s["gmail_oauth_navegador"] = "nonce"
        self.assertEqual(self.client.get("/api/gmail/callback?state=correto&code=sintetico").status_code, 200)
        with self.client.session_transaction() as s:
            self.assertNotIn("gmail_credentials", s)
            self.assertNotIn("gmail_oauth_state", s)
        self.assertEqual(flow.code_verifier, "verifier")
        self.assertTrue(any("INSERT INTO gmail_oauth_credentials" in sql for sql, _ in self.banco.sql))

    def test_conexao_autorizada_guarda_verifier_apenas_no_banco(self):
        flow = Mock(code_verifier="verifier-sintetico")
        flow.authorization_url.return_value = ("https://accounts.example/authorize", "state")
        self.ns["Flow"].from_client_config.return_value = flow
        self.ns.update(GMAIL_CLIENT_ID="id", GMAIL_CLIENT_SECRET="segredo", GMAIL_REDIRECT_URI="https://example.com/api/gmail/callback", GMAIL_CLIENT_CONFIG={}, GMAIL_SCOPES=[], secrets=SimpleNamespace(token_urlsafe=lambda _: "navegador"), guardar_oauth=seguranca.guardar_oauth)
        self.assertEqual(self.client.get("/api/gmail/conectar", headers={"X-Admin-Key": "chave-teste"}).status_code, 302)
        with self.client.session_transaction() as s:
            self.assertNotIn("gmail_code_verifier", s)
            self.assertNotIn("gmail_credentials", s)
        self.assertEqual(seguranca.consumir_oauth(self.banco, "state", "navegador"), "verifier-sintetico")

    def test_remove_credenciais_legadas_do_cookie(self):
        with self.client.session_transaction() as s:
            s["gmail_credentials"] = {"token": "token-sintetico"}
        self.client.get("/api/gmail/conectar")
        with self.client.session_transaction() as s:
            self.assertNotIn("gmail_credentials", s)

    def test_estado_oauth_servidor_uso_unico_e_navegador(self):
        seguranca.guardar_oauth(self.banco, "state", "navegador", "verifier")
        with self.assertRaises(ValueError):
            seguranca.consumir_oauth(self.banco, "state", "outro")
        self.assertEqual(seguranca.consumir_oauth(self.banco, "state", "navegador"), "verifier")
        with self.assertRaises(ValueError):
            seguranca.consumir_oauth(self.banco, "state", "navegador")

    def test_interruptor_payloads_invalidos_retornam_400(self):
        for body in ('[1]', 'null', 'false', '"texto"', '{', '{}', '{"pausado":"true","motivo":"teste"}'):
            with self.subTest(body=body):
                r = self.client.post('/api/admin/email/seguranca', headers={'X-Admin-Key': 'chave-teste'}, data=body, content_type='application/json')
                self.assertEqual(r.status_code, 400)
                self.assertFalse(self.banco.pausado)

    def test_cors_gmail_origens_explicitas_e_sem_bypass(self):
        self.ns['ORIGENS_PERMITIDAS_SAC'] = {'https://maranhaocordial.com.br', 'https://www.maranhaocordial.com.br'}
        carregar_funcoes('main.py', ['adicionar_cors_sac'], self.ns)
        self.app.after_request(self.ns['adicionar_cors_sac'])
        for origem in ('https://maranhaocordial.com.br', 'https://maranhao-cordial.onrender.com'):
            r = self.client.options('/api/gmail/conectar', headers={'Origin': origem, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'X-Admin-Key'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers['Access-Control-Allow-Origin'], origem)
            self.assertEqual(r.headers['Access-Control-Allow-Credentials'], 'true')
            self.assertEqual(self.client.post('/api/gmail/conectar', headers={'Origin': origem}).status_code, 401)
        r = self.client.options('/api/gmail/conectar', headers={'Origin': 'https://malicioso.example'})
        self.assertNotIn('Access-Control-Allow-Origin', r.headers)
        self.assertIn('no-store', r.headers['Cache-Control'])

    def test_inicio_post_retorna_url_sem_redirecionar_fetch(self):
        flow = Mock(code_verifier='verifier')
        flow.authorization_url.return_value = ('https://accounts.google.com/o/oauth2/auth?state=state', 'state')
        self.ns['Flow'].from_client_config.return_value = flow
        self.ns.update(GMAIL_CLIENT_ID='id', GMAIL_CLIENT_SECRET='segredo', GMAIL_CLIENT_CONFIG={}, GMAIL_SCOPES=[], secrets=SimpleNamespace(token_urlsafe=lambda _: 'nonce'), guardar_oauth=seguranca.guardar_oauth)
        r = self.client.post('/api/gmail/conectar', headers={'X-Admin-Key': 'chave-teste'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('Location', r.headers)
        self.assertTrue(r.json['authorization_url'].startswith('https://accounts.google.com/'))
        with self.client.session_transaction() as s:
            self.assertEqual(s['gmail_oauth_state'], 'state')
            self.assertEqual(s['gmail_oauth_navegador'], 'nonce')
            self.assertNotIn('gmail_code_verifier', s)

    def test_oauth_sem_secret_persistente_falha_sem_afetar_admin(self):
        os.environ.pop('FLASK_SECRET_KEY')
        r = self.client.post('/api/gmail/conectar', headers={'X-Admin-Key': 'chave-teste'})
        self.assertEqual(r.status_code, 503)
        self.ns['Flow'].from_client_config.assert_not_called()
        r = self.client.post('/api/admin/email/seguranca', headers={'X-Admin-Key': 'chave-teste'}, json={'pausado': True, 'motivo': 'teste'})
        self.assertEqual(r.status_code, 200)

    def test_callback_usa_https_canonico_sem_confiar_proxy_do_cliente(self):
        cred = SimpleNamespace(refresh_token='refresh', token_uri='https://oauth.example/token', client_id='id', client_secret='sintetico', scopes=[])
        flow = Mock(credentials=cred)
        self.ns.update(GMAIL_CLIENT_CONFIG={}, GMAIL_SCOPES=[], build=Mock())
        self.ns['Flow'].from_client_config.return_value = flow
        self.ns['build']().users().getProfile().execute.return_value = {'emailAddress': 'contato@maranhaocordial.com.br'}
        self.ns['consumir_oauth'] = Mock(return_value='verifier')
        with self.client.session_transaction() as s:
            s['gmail_oauth_state'] = 'state'
            s['gmail_oauth_navegador'] = 'nonce'
        r = self.client.get('/api/gmail/callback?state=state&code=code', headers={'X-Forwarded-Proto': 'http', 'X-Forwarded-Host': 'malicioso.example'})
        self.assertEqual(r.status_code, 200)
        flow.fetch_token.assert_called_once_with(authorization_response='https://example.com/api/gmail/callback?state=state&code=code')

    def test_redirect_inseguro_ou_invalido_rejeitado(self):
        for uri in ('http://example.com/api/gmail/callback', 'https://example.com/outro', 'https://user:senha@example.com/api/gmail/callback', 'https://example.com/api/gmail/callback?extra=1'):
            with self.assertRaises(ValueError):
                seguranca.validar_config_oauth_p0(uri)

    def test_sync_parcial_retorna_502(self):
        self.banco.resultado = None
        dados = dict(refresh_token='refresh', token_uri='https://oauth.example/token', client_id='id', client_secret='sintetico', scopes='gmail.readonly')
        banco = Mock()
        banco.cursor.return_value.__enter__ = Mock(return_value=Mock(fetchone=Mock(return_value=dados)))
        banco.cursor.return_value.__exit__ = Mock(return_value=False)
        self.ns.update(get_db_connection=lambda: banco, RealDictCursor=object, gmail_buscar_mensagens=Mock(return_value={'success': False, 'erros': [{'etapa': 'dsn'}]}))
        with patch('google.oauth2.credentials.Credentials', return_value=SimpleNamespace(valid=True, token='sintetico')):
            r = self.client.get('/api/gmail/sincronizar', headers={'X-Admin-Key': 'chave-teste'})
        self.assertEqual(r.status_code, 502)


class Adaptadores(Offline):
    def setUp(self):
        super().setUp()
        import acoes_comerciais as a
        token = a._aprovacao.set({'destinatario':'boa@example.com','assunto':'assunto','mensagem':'texto'})
        self.addCleanup(a._aprovacao.reset, token)

    def test_fase56_bloqueia_antes_de_obter_gmail(self):
        import acoes_comerciais as a
        a._aprovacao.get()["destinatario"] = "ruim@example.com"
        ns = dict(verificar_envio=seguranca.verificar_envio, _conn=lambda _: self.banco, obter_gmail_service_fase56=Mock())
        carregar_funcoes("fase56_fabrica_piloto.py", ["enviar_email_institucional_fase56"], ns)
        self.banco.supressoes.add("ruim@example.com")
        with self.assertRaises(seguranca.EnvioBloqueado):
            ns["enviar_email_institucional_fase56"]({}, "ruim@example.com", "assunto", "html", "texto")
        ns["obter_gmail_service_fase56"].assert_not_called()

    def test_gmail_legado_bloqueia_antes_de_credenciais(self):
        ns = dict(verificar_envio=seguranca.verificar_envio, get_db_connection=self.banco)
        carregar_funcoes("main.py", ["gmail_enviar_email"], ns)
        self.banco.pausado = True
        with self.assertRaises(PermissionError):
            ns["gmail_enviar_email"]("boa@example.com", "assunto", "texto")

    def test_fase56_permitido_so_envia_ao_mock(self):
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        gmail = Mock()
        gmail.users().getProfile().execute.return_value = {"emailAddress": "contato@maranhaocordial.com.br"}
        gmail.users().messages().send().execute.return_value = {"id": "sintetico", "threadId": "thread"}
        ns = dict(verificar_envio=seguranca.verificar_envio, _conn=lambda _: self.banco,
                  obter_gmail_service_fase56=Mock(return_value=gmail), EMAIL_INSTITUCIONAL="contato@maranhaocordial.com.br",
                  MIMEMultipart=MIMEMultipart, MIMEText=MIMEText, os=os, LOGO_EMAIL="/arquivo-inexistente-p0", base64=base64)
        carregar_funcoes("fase56_fabrica_piloto.py", ["enviar_email_institucional_fase56"], ns)
        resultado = ns["enviar_email_institucional_fase56"]({}, "boa@example.com", "assunto", "html", "texto")
        self.assertTrue(resultado["success"])
        self.assertEqual(resultado["message_id"], "sintetico")
        self.assertNotIn("entregue", resultado)
        self.assertEqual(sum(sql.startswith("SELECT pausado") for sql, _ in self.banco.sql), 2)

    def test_pausa_durante_preparacao_impede_send(self):
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        gmail = Mock()
        def perfil():
            self.banco.pausado = True
            return {"emailAddress": "contato@maranhaocordial.com.br"}
        gmail.users().getProfile().execute.side_effect = perfil
        ns = dict(verificar_envio=seguranca.verificar_envio, _conn=lambda _: self.banco,
                  obter_gmail_service_fase56=Mock(return_value=gmail), EMAIL_INSTITUCIONAL="contato@maranhaocordial.com.br",
                  MIMEMultipart=MIMEMultipart, MIMEText=MIMEText, os=os, LOGO_EMAIL="/arquivo-inexistente-p0", base64=base64)
        carregar_funcoes("fase56_fabrica_piloto.py", ["enviar_email_institucional_fase56"], ns)
        with self.assertRaises(seguranca.EnvioBloqueado):
            ns["enviar_email_institucional_fase56"]({}, "boa@example.com", "assunto", "html", "texto")
        gmail.users().messages().send.assert_not_called()

    def test_fases_57_58_usam_adaptador_protegido(self):
        for arquivo, funcao, alvo in (("fase57_prospeccao_universal.py", "enviar_primeiro_contato_fase57", "propor_mensagem_fase57"), ("fase57_prospeccao_universal.py", "processar_resposta_fase57", "propor_mensagem_fase57"), ("fase58_motor_busca.py", "executar_fase58a", "executar_lote_contatos_fase57"), ("fase58b_motor_geral.py", "executar_fase58b", "executar_lote_contatos_fase57")):
            tree = ast.parse((ROOT / arquivo).read_text())
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == funcao)
            self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == alvo for n in ast.walk(fn)))

    def test_sync_trata_bounce_antes_de_responder_preserva_resposta_valida(self):
        dados = [{"id": "resposta", "payload": {"mimeType": "text/plain"}, "snippet": "Temos interesse"}, {"id": "bounce", "payload": {"mimeType": "multipart/report"}}]
        ordem = []
        def registrar(**kwargs):
            ordem.append("registrar:" + kwargs["message_id"])
            return {"success": True, "duplicada": False, "interacao": dict(kwargs, id="entrada-sintetica")}
        def dsn_mock(d, *args):
            ordem.append("dsn:" + d["id"])
            return d["id"] == "bounce"
        ns = dict(base64=base64, definir_pausa=seguranca.definir_pausa, bloquear_envios_no_contexto=seguranca.bloquear_envios_no_contexto, processar_dsn_gmail=dsn_mock, get_db_connection=self.banco, registrar_interacao_omnichannel=registrar, processar_interacao_omnichannel_crm=Mock(return_value={"success": True}))
        carregar_funcoes("main.py", ["gmail_importar_mensagem_p0", "gmail_buscar_mensagens"], ns)
        with patch("requests.get", side_effect=[resposta_json({"messages": [{"id": d["id"]} for d in dados]})] + [resposta_json(d) for d in dados]):
            resultado = ns["gmail_buscar_mensagens"]("token-sintetico")
        self.assertEqual(resultado["quantidade"], 2)
        self.assertLess(ordem.index("dsn:bounce"), ordem.index("registrar:resposta"))
        ns["processar_interacao_omnichannel_crm"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
