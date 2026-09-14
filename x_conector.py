"""Adaptador isolado X/Twitter (API v2) -- OAuth 2.0 + PKCE, menor
privilégio possível, publicação SOMENTE via fila/aprovação já existente.

Credenciais só por env var, nunca logadas nem persistidas em banco por
este módulo. Sem elas, toda função de rede recusa (fail-closed).
"""
import base64
import hashlib
import os
import secrets

import requests

AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
API_BASE = "https://api.twitter.com/2"

# offline.access só entra porque refresh_token persistente é necessário
# para não pedir login humano a cada expiração de token de curta duração.
ESCOPOS = ("tweet.read", "users.read", "tweet.write", "offline.access")


class XNaoConfigurado(RuntimeError):
    pass


def _config():
    return {
        "client_id": os.getenv("X_CLIENT_ID"),
        "client_secret": os.getenv("X_CLIENT_SECRET"),
        "access_token": os.getenv("X_ACCESS_TOKEN"),
        "refresh_token": os.getenv("X_REFRESH_TOKEN"),
        "expires_at": os.getenv("X_TOKEN_EXPIRES_AT"),
    }


def status():
    cfg = _config()
    app_configurado = bool(cfg["client_id"])
    tem_token = bool(cfg["access_token"])
    return {
        "conectado": app_configurado and tem_token,
        "app_configurado": app_configurado,
        "token_presente": tem_token,
        "expira_em": cfg["expires_at"] or None,
        "leitura_disponivel": app_configurado and tem_token,
        "escrita_disponivel": app_configurado and tem_token,
        "motivo_pendente": None if (app_configurado and tem_token) else "credenciais_ausentes",
    }


def gerar_pkce():
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def montar_url_autorizacao(redirect_uri, escopos=ESCOPOS, state=None):
    cfg = _config()
    if not cfg["client_id"]:
        raise XNaoConfigurado("x_client_id_ausente")
    state = state or secrets.token_urlsafe(24)
    verifier, challenge = gerar_pkce()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(escopos),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{AUTH_URL}?{query}", state, verifier


def trocar_code_por_token(code, redirect_uri, code_verifier, timeout=15):
    cfg = _config()
    if not cfg["client_id"]:
        raise XNaoConfigurado("x_client_id_ausente")
    auth = None
    if cfg["client_secret"]:
        auth = (cfg["client_id"], cfg["client_secret"])
    resposta = requests.post(
        TOKEN_URL,
        auth=auth,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": cfg["client_id"],
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    return {
        "access_token": corpo.get("access_token"),
        "refresh_token": corpo.get("refresh_token"),
        "expires_in": corpo.get("expires_in"),
    }


def _headers():
    cfg = _config()
    if not cfg["access_token"]:
        raise XNaoConfigurado("x_token_ausente")
    return {"Authorization": f"Bearer {cfg['access_token']}"}


def ler_metricas_usuario(timeout=15):
    """Leitura somente -- tweet.read/users.read."""
    resposta = requests.get(
        f"{API_BASE}/users/me",
        headers=_headers(),
        params={"user.fields": "public_metrics"},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()


def publicar_post(texto, aprovado_por, timeout=15):
    """Nunca publica sem aprovação humana explícita já registrada na fila
    existente -- `aprovado_por` vem preenchido só depois desse fluxo."""
    if not aprovado_por:
        raise PermissionError("publicacao_x_exige_aprovacao_humana_previa")
    resposta = requests.post(f"{API_BASE}/tweets", headers=_headers(), json={"text": texto}, timeout=timeout)
    resposta.raise_for_status()
    return {"success": True, "tweet_id": resposta.json().get("data", {}).get("id")}
