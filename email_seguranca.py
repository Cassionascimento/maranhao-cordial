"""Travas P0. Sem conexões, migrações ou envios durante importação.

O schema é aditivo e criado no primeiro uso. Falha do banco impede o envio.
Não infere entrega nem altera estados/histórico das campanhas existentes.
"""
import base64
import hashlib
import hmac
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from urllib.parse import urlsplit


_bloqueio_contexto = ContextVar("email_p0_bloqueio", default=False)


@contextmanager
def bloquear_envios_no_contexto():
    """Protege a requisição mesmo se não for possível gravar a pausa no banco."""
    token = _bloqueio_contexto.set(True)
    try:
        yield
    finally:
        _bloqueio_contexto.reset(token)


def chave_admin_configurada(namespace):
    for nome in ("ADMIN_API_KEY", "ADMIN_KEY", "ADMIN_SECRET", "PAINEL_ADMIN_KEY"):
        valor = namespace.get(nome) or os.getenv(nome)
        if isinstance(valor, str) and valor.strip():
            return valor
    return None


def validar_config_oauth_p0(redirect_uri):
    # Exige estabilidade apenas para OAuth, sem derrubar o restante da aplicação.
    segredo = os.getenv("FLASK_SECRET_KEY") or ""
    uri = urlsplit(redirect_uri or "")
    if len(segredo) < 32:
        raise ValueError("OAuth requer FLASK_SECRET_KEY persistente com pelo menos 32 caracteres.")
    if (uri.scheme != "https" or not uri.hostname or uri.username or uri.password
            or uri.query or uri.fragment or uri.path != "/api/gmail/callback"):
        raise ValueError("OAuth requer GOOGLE_GMAIL_REDIRECT_URI HTTPS com /api/gmail/callback.")


class EnvioBloqueado(RuntimeError):
    pass


def admin_autorizado(chave, namespace):
    # Chave canônica primeiro; aliases apenas se ela não estiver configurada.
    if not isinstance(chave, str) or not chave.strip():
        return False
    esperado = chave_admin_configurada(namespace)
    return bool(esperado and hmac.compare_digest(chave.encode(), esperado.encode()))


def enderecos(valor):
    if not isinstance(valor, str) or any(c in valor for c in "\r\n"):
        raise EnvioBloqueado("destinatario_invalido")
    itens = getaddresses([valor])
    if not itens:
        raise EnvioBloqueado("destinatario_invalido")
    saida = []
    for _, email in itens:
        if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", email):
            raise EnvioBloqueado("destinatario_invalido")
        saida.append(email.strip().lower())
    return sorted(set(saida))


def garantir_schema(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_controle_p0 (
            id INTEGER PRIMARY KEY CHECK (id=1),
            pausado BOOLEAN NOT NULL DEFAULT FALSE,
            atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("INSERT INTO email_controle_p0(id) VALUES(1) ON CONFLICT DO NOTHING")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_eventos_seguranca_p0 (
            id BIGSERIAL PRIMARY KEY,
            tipo TEXT NOT NULL,
            destinatario TEXT,
            mensagem_origem TEXT,
            mensagem_enviada TEXT,
            codigo TEXT,
            motivo TEXT NOT NULL,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tipo, destinatario, mensagem_origem)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_supressoes_p0 (
            email TEXT PRIMARY KEY,
            motivo TEXT NOT NULL,
            codigo TEXT NOT NULL,
            mensagem_origem TEXT NOT NULL,
            mensagem_enviada TEXT NOT NULL,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gmail_oauth_estados_p0 (
            state_hash TEXT PRIMARY KEY,
            navegador_hash TEXT NOT NULL,
            verifier TEXT,
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            consumido_em TIMESTAMPTZ
        )
    """)


def verificar_envio(conn_factory, destinatario, cc=None):
    from prospeccao_controle import validar_contexto
    validar_contexto(destinatario, cc)
    from email_seguranca import verificar_travas_envio
    verificar_travas_envio(conn_factory, destinatario, cc)


def verificar_travas_envio(conn_factory, destinatario, cc=None):
    """Pré-condições P0; não autoriza transporte nem cria contexto de envio."""
    if _bloqueio_contexto.get():
        raise EnvioBloqueado("envios_bloqueados_falha_importacao")
    # Ausente preserva o funcionamento. Valor explícito inválido falha fechado.
    if os.getenv("EMAIL_ENVIOS_PAUSADOS", "false").lower() not in ("false", "0", "no"):
        raise EnvioBloqueado("envios_pausados_ambiente")
    alvos = enderecos(destinatario) + (enderecos(cc) if cc else [])
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                garantir_schema(cur)
                cur.execute("SELECT pausado FROM email_controle_p0 WHERE id=1")
                if cur.fetchone()[0]:
                    raise EnvioBloqueado("envios_pausados")
                cur.execute("SELECT email FROM email_supressoes_p0 WHERE email = ANY(%s)", (alvos,))
                if cur.fetchone():
                    raise EnvioBloqueado("destinatario_suprimido_hard_bounce")
    finally:
        conn.close()


def definir_pausa(conn_factory, pausado, motivo):
    if type(pausado) is not bool or not isinstance(motivo, str) or not motivo.strip():
        raise ValueError("Informe pausado booleano e motivo.")
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                garantir_schema(cur)
                cur.execute("UPDATE email_controle_p0 SET pausado=%s, atualizado_em=NOW() WHERE id=1", (pausado,))
                cur.execute("INSERT INTO email_eventos_seguranca_p0(tipo,motivo) VALUES(%s,%s)",
                            ("pausa" if pausado else "retomada", motivo[:2000]))
    finally:
        conn.close()


def _hash(valor):
    return hashlib.sha256(valor.encode()).hexdigest()


def guardar_oauth(conn_factory, state, navegador, verifier):
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                garantir_schema(cur)
                cur.execute("INSERT INTO gmail_oauth_estados_p0(state_hash,navegador_hash,verifier) VALUES(%s,%s,%s)",
                            (_hash(state), _hash(navegador), verifier))
    finally:
        conn.close()


def consumir_oauth(conn_factory, state, navegador):
    if not state or not navegador:
        raise ValueError("Estado OAuth inválido.")
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                garantir_schema(cur)
                cur.execute("""
                    SELECT verifier FROM gmail_oauth_estados_p0
                    WHERE state_hash=%s AND navegador_hash=%s
                      AND consumido_em IS NULL
                      AND criado_em > NOW() - INTERVAL '10 minutes'
                    FOR UPDATE
                """, (_hash(state), _hash(navegador)))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Estado OAuth expirado ou já utilizado.")
                cur.execute("UPDATE gmail_oauth_estados_p0 SET consumido_em=NOW(), verifier=NULL WHERE state_hash=%s", (_hash(state),))
                return row[0]
    finally:
        conn.close()


def extrair_hard_bounces(raw):
    """Só DSN estruturado de endereço inexistente; nunca assunto/snippet.

    5.7.x (política), 4.x (temporário) e 5.2.x não suprimem endereço.
    Exige mensagem original anexada; casos ambíguos ficam sem supressão.
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if msg.get_content_type() != "multipart/report" or msg.get_param("report-type") != "delivery-status":
        return []
    if any(parte.defects for parte in msg.walk()):
        raise ValueError("DSN MIME malformado")
    remetente = parseaddr(str(msg.get("From", "")))[1].lower()
    if remetente.split("@")[0] not in ("mailer-daemon", "postmaster"):
        return []
    originais = []
    falhas = []
    for parte in msg.iter_parts():
        if parte.get_content_type() == "message/rfc822":
            originais.extend(parte.get_payload() if isinstance(parte.get_payload(), list) else [])
        elif parte.get_content_type() == "text/rfc822-headers":
            originais.append(BytesParser(policy=policy.default).parsebytes(parte.get_payload(decode=True) or b""))
        elif parte.get_content_type() == "message/delivery-status":
            for bloco in parte.get_payload():
                status = str(bloco.get("Status", "")).strip()
                if str(bloco.get("Action", "")).strip().lower() != "failed" or status not in ("5.1.1", "5.1.2", "5.1.3"):
                    continue
                final = str(bloco.get("Final-Recipient", ""))
                if ";" not in final or final.split(";", 1)[0].strip().lower() != "rfc822":
                    continue
                try:
                    alvo = enderecos(final.split(";", 1)[1].strip())
                except EnvioBloqueado:
                    continue
                if len(alvo) == 1:
                    falhas.append({"email": alvo[0], "codigo": status,
                                   "motivo": str(bloco.get("Diagnostic-Code", status))[:2000]})
    if len(originais) != 1:
        return []
    original_id = str(originais[0].get("Message-ID", "")).strip()
    if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", original_id):
        return []
    return [dict(f, original_id=original_id) for f in falhas]


def registrar_hard_bounce(conn_factory, falha, origem_id, enviado_id):
    """Chamado somente após conferir a mensagem original na pasta SENT."""
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                garantir_schema(cur)
                cur.execute("""
                    INSERT INTO email_eventos_seguranca_p0
                    (tipo,destinatario,mensagem_origem,mensagem_enviada,codigo,motivo)
                    VALUES('hard_bounce',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                """, (falha["email"], origem_id, enviado_id, falha["codigo"], falha["motivo"]))
                cur.execute("""
                    INSERT INTO email_supressoes_p0
                    (email,motivo,codigo,mensagem_origem,mensagem_enviada)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT(email) DO NOTHING
                """, (falha["email"], falha["motivo"], falha["codigo"], origem_id, enviado_id))
    finally:
        conn.close()


def processar_dsn_gmail(dados, headers, conn_factory, http):
    """Somente leituras Gmail; confirma ID e destinatário no original enviado."""
    payload = dados.get("payload", {})
    if payload.get("mimeType") != "multipart/report":
        return False
    base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    r = http.get(f"{base}/{dados['id']}", headers=headers, params={"format": "raw"}, timeout=30)
    r.raise_for_status()
    encoded = r.json()["raw"]
    raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    for falha in extrair_hard_bounces(raw):
        r = http.get(base, headers=headers, params={"q": "in:sent rfc822msgid:" + falha["original_id"], "maxResults": 10}, timeout=30)
        r.raise_for_status()
        for candidato in r.json().get("messages", []):
            r = http.get(f"{base}/{candidato['id']}", headers=headers, params={"format": "metadata"}, timeout=30)
            r.raise_for_status()
            enviado = r.json()
            hs = enviado.get("payload", {}).get("headers", [])
            ids = [h["value"].strip() for h in hs if h.get("name", "").lower() == "message-id"]
            alvos = []
            for h in hs:
                if h.get("name", "").lower() in ("to", "cc", "bcc"):
                    alvos.extend(a.lower() for _, a in getaddresses([h.get("value", "")]))
            if "SENT" in enviado.get("labelIds", []) and ids == [falha["original_id"]] and falha["email"] in alvos:
                registrar_hard_bounce(conn_factory, falha, dados["id"], candidato["id"])
                break
    # Relatórios técnicos não passam pelos processadores comerciais, mesmo ambíguos.
    return True
