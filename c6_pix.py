"""C6 Pix: configuração explícita e transporte sem efeitos ao importar.

Não habilita produção: liberação bancária, endpoints e autenticidade do webhook
precisam ser homologados antes de C6_PRODUCTION_APPROVED=true.
"""
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import requests


class C6Error(RuntimeError):
    """Somente mensagens sanitizadas; nunca inclui resposta bancária."""


def validar_txid(txid):
    if not isinstance(txid, str) or not re.fullmatch(r"[A-Za-z0-9]{26,35}", txid):
        raise C6Error("TXID inválido.")
    return txid


@dataclass(frozen=True)
class C6Config:
    environment: str
    auth_url: str
    pix_base_url: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    pix_key: str = field(repr=False)
    cert_path: str = field(repr=False)
    key_path: str = field(repr=False)
    production_approved: bool = False
    charges_enabled: bool = False

    @classmethod
    def from_env(cls, env=None):
        e = os.environ if env is None else env
        name = e.get("C6_ENVIRONMENT", "sandbox").strip().lower()
        if name not in {"sandbox", "homologacao", "production"}:
            raise C6Error("C6_ENVIRONMENT inválido.")
        # Somente sandbox aceita configuração legada. Produção nunca herda secrets.
        prefix = "C6_" + name.upper() + "_"
        def value(key, default=""):
            return e.get(prefix + key, e.get("C6_" + key, default) if name == "sandbox" else default)
        sandbox = name == "sandbox"
        config = cls(name,
            value("AUTH_URL", "https://baas-api-sandbox.c6bank.info/v1/auth/" if sandbox else ""),
            value("PIX_BASE_URL", "https://baas-api-sandbox.c6bank.info/v2/pix" if sandbox else "").rstrip("/"),
            value("CLIENT_ID"), value("CLIENT_SECRET"), value("PIX_KEY"),
            value("CERT_PATH", "/etc/secrets/C6_sandbox.crt" if sandbox else ""),
            value("KEY_PATH", "/etc/secrets/C6_sandbox.key" if sandbox else ""),
            e.get("C6_PRODUCTION_APPROVED", "").lower() == "true",
            e.get("C6_CHARGES_ENABLED", "").lower() == "true")
        config.validate_urls()
        return config

    def validate_urls(self):
        for url in (self.auth_url, self.pix_base_url):
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            if (parsed.scheme != "https" or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                    or not any(host.endswith("." + suffix) for suffix in ("c6bank.info", "c6bank.com.br"))):
                raise C6Error("Endpoint C6 inválido ou ausente para o ambiente.")
            test_host = any(word in host for word in ("sandbox", "homolog", "hml"))
            if (self.environment == "production") == test_host:
                raise C6Error("Endpoint incompatível com ambiente C6.")

    def validate(self, *, create=False):
        self.validate_urls()
        if not all((self.client_id, self.client_secret, self.pix_key)):
            raise C6Error("Credenciais/chave Pix C6 ausentes no ambiente selecionado.")
        if not all(path and Path(path).is_file() for path in (self.cert_path, self.key_path)):
            raise C6Error("Arquivos mTLS C6 ausentes.")
        if self.environment == "production" and not self.production_approved:
            raise C6Error("Produção C6 aguardando liberação explícita.")
        if create and not self.charges_enabled:
            raise C6Error("Criação de cobrança C6 desabilitada.")

    def status(self):
        try:
            self.validate()
            ready = True
        except (C6Error, ValueError):
            ready = False
        return {"integration": "C6 Bank", "environment": self.environment,
                "credentials_configured": bool(self.client_id and self.client_secret),
                "pix_key_configured": bool(self.pix_key),
                "mtls_configured": all(bool(p) and Path(p).is_file() for p in (self.cert_path, self.key_path)),
                "ready": ready, "charges_enabled": ready and self.charges_enabled,
                "production_approved": self.production_approved}


class C6Client:
    def __init__(self, config=None, transport=None):
        self.config = config or C6Config.from_env()
        self.transport = transport or requests

    def _request(self, method, url, **kwargs):
        try:
            response = getattr(self.transport, method)(url,
                cert=(self.config.cert_path, self.config.key_path), timeout=30,
                allow_redirects=False, **kwargs)
            if not 200 <= response.status_code < 300:
                raise C6Error("C6 recusou operação (HTTP %s)." % response.status_code)
            data = response.json()
            if not isinstance(data, dict):
                raise C6Error("Resposta C6 inválida.")
            return data
        except (requests.RequestException, ValueError):
            raise C6Error("Falha de comunicação/resposta C6.") from None

    def access_token(self):
        self.config.validate()
        data = self._request("post", self.config.auth_url, data={
            "grant_type": "client_credentials", "client_id": self.config.client_id,
            "client_secret": self.config.client_secret})
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise C6Error("C6 não retornou access_token.")
        return token

    def headers(self):
        return {"Authorization": "Bearer " + self.access_token(),
                "Content-Type": "application/json", "Accept": "application/json"}

    def consultar(self, txid):
        validar_txid(txid)
        return self._request("get", self.config.pix_base_url + "/cob/" + txid, headers=self.headers())

    def criar(self, txid, payload):
        # TXID deve ser persistido no pedido ANTES da chamada. Retry reutiliza TXID.
        self.config.validate(create=True)
        validar_txid(txid)
        return self._request("put", self.config.pix_base_url + "/cob/" + txid,
                             json=payload, headers=self.headers())


def extrair_txids(evento):
    if not isinstance(evento, dict):
        raise C6Error("Webhook inválido.")
    entries = evento.get("pix", [])
    if not isinstance(entries, list) or len(entries) > 100:
        raise C6Error("Lista Pix inválida.")
    values = ([evento["txid"]] if evento.get("txid") else [])
    values += [item.get("txid") for item in entries if isinstance(item, dict)]
    return list(dict.fromkeys(validar_txid(value) for value in values if value))


def pagamento_confirmado(pedido, consulta):
    """Use exclusivamente resposta da consulta mTLS, nunca o payload do webhook."""
    if not isinstance(consulta, dict) or consulta.get("status") != "CONCLUIDA":
        return False
    if not pedido.get("c6_txid") or pedido["c6_txid"] != consulta.get("txid"):
        return False
    if pedido.get("payment_origin") != "c6":
        return False
    try:
        esperado = Decimal(str(pedido.get("amount"))) / 100
        valor = Decimal(str(consulta.get("valor", {}).get("original")))
        return esperado.is_finite() and valor.is_finite() and esperado > 0 and esperado == valor
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return False


def reconciliar_persistente(txid, consulta, connection_factory):
    """Trava o pedido no PostgreSQL; repetição não duplica transição financeira.

    O callback de CRM continua responsabilidade do app e deve ser idempotente.
    O webhook é apenas um aviso: somente consulta autenticada informa pagamento.
    """
    validar_txid(txid)
    conn = connection_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT codigo, valor_centavos, status, payment_origin, c6_txid "
                            "FROM pedidos WHERE c6_txid=%s FOR UPDATE", (txid,))
                rows = cur.fetchall()
                if len(rows) != 1:
                    return {"found": False, "paid": False}
                codigo, amount, old_status, origin, stored_txid = rows[0]
                pedido = dict(amount=amount, c6_txid=stored_txid, payment_origin=origin)
                paid = pagamento_confirmado(pedido, consulta)
                status = str(consulta.get("status", ""))
                if status not in {"ATIVA", "CONCLUIDA", "REMOVIDA_PELO_USUARIO_RECEBEDOR", "REMOVIDA_PELO_PSP"}:
                    raise C6Error("Status C6 desconhecido.")
                if paid and old_status != "pago":
                    cur.execute("UPDATE pedidos SET c6_status=%s, status='pago', status_entrega='aguardando_despacho', "
                                "atualizado_em=NOW() WHERE codigo=%s", (status, codigo))
                elif old_status != "pago":
                    cur.execute("UPDATE pedidos SET c6_status=%s, atualizado_em=NOW() WHERE codigo=%s", (status, codigo))
                event = "pagamento_confirmado" if paid else ("confirmacao_inconsistente" if status == "CONCLUIDA" else "status_" + status.lower())
                cur.execute("INSERT INTO c6_pix_auditoria (codigo,evento) VALUES (%s,%s) ON CONFLICT DO NOTHING", (codigo, event))
                return {"found": True, "paid": paid, "changed": paid and old_status != "pago", "code": codigo, "status": status}
    finally:
        conn.close()


def iniciar_checkout(connection_factory, chave, payload, pedido=None):
    """Reserva durável. Tentativa ambígua nunca gera uma segunda cobrança."""
    import hashlib
    import json
    if not isinstance(chave, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", chave):
        raise C6Error("Idempotency-Key obrigatório: 16 a 128 caracteres alfanuméricos, _ ou -.")
    key_hash = hashlib.sha256(chave.encode()).hexdigest()
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    codigo = 'MAR-C6-' + key_hash[:20].upper()
    conn = connection_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO c6_checkout_tentativas (chave_hash,payload_hash,codigo) "
                            "VALUES (%s,%s,%s) ON CONFLICT (chave_hash) DO NOTHING RETURNING codigo",
                            (key_hash, payload_hash, codigo))
                if cur.fetchone():
                    if pedido is not None:
                        import uuid
                        txid = key_hash[:32]
                        cur.execute(
                            "INSERT INTO pedidos (id,codigo,cliente_nome,cliente_email,cliente_whatsapp,"
                            "endereco,quantidade,valor_centavos,status,payment_origin,c6_txid,status_entrega) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (str(uuid.uuid4()), codigo, pedido['cliente_nome'], pedido['cliente_email'],
                             pedido['cliente_whatsapp'], pedido['address'], pedido['quantity'],
                             pedido['amount'], 'aguardando_pagamento', 'c6', txid, 'aguardando_pagamento'))
                    cur.execute("INSERT INTO c6_pix_auditoria (codigo,evento) VALUES (%s,'checkout_reservado') "
                                "ON CONFLICT DO NOTHING", (codigo,))
                    return {"new": True, "code": codigo, "txid": key_hash[:32]}
                cur.execute("SELECT payload_hash,codigo,resposta FROM c6_checkout_tentativas WHERE chave_hash=%s", (key_hash,))
                previous = cur.fetchone()
                if not previous or previous[0] != payload_hash:
                    raise C6Error("Idempotency-Key já utilizado com dados diferentes.")
                return {"new": False, "code": previous[1], "response": previous[2], "txid": key_hash[:32]}
    finally:
        conn.close()


def concluir_checkout(connection_factory, codigo, resposta):
    import json
    conn = connection_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE c6_checkout_tentativas SET resposta=%s::jsonb, atualizado_em=NOW() WHERE codigo=%s",
                            (json.dumps(resposta), codigo))
                cur.execute("INSERT INTO c6_pix_auditoria (codigo,evento) VALUES (%s,'cobranca_criada') "
                            "ON CONFLICT DO NOTHING", (codigo,))
    finally:
        conn.close()
