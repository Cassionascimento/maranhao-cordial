"""Adaptador isolado Pinterest (API v5) -- OAuth 2.0 + PKCE, escopos
mínimos, criação de Pin SOMENTE via fila/aprovação já existente.

Credenciais só por env var, nunca logadas nem persistidas em banco por
este módulo. Sem elas, toda função de rede recusa (fail-closed).
"""
import base64
import hashlib
import os
import secrets

import requests

AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
API_BASE = "https://api.pinterest.com/v5"

ESCOPOS_MINIMOS = ("user_accounts:read", "boards:read", "pins:read", "pins:write")
# Só adicionar se a operação realmente precisar criar boards novos.
ESCOPO_BOARDS_WRITE = "boards:write"


class PinterestNaoConfigurado(RuntimeError):
    pass


def _config():
    return {
        "client_id": os.getenv("PINTEREST_CLIENT_ID"),
        "client_secret": os.getenv("PINTEREST_CLIENT_SECRET"),
        "access_token": os.getenv("PINTEREST_ACCESS_TOKEN"),
        "expires_at": os.getenv("PINTEREST_TOKEN_EXPIRES_AT"),
        "board_id": os.getenv("PINTEREST_BOARD_ID"),
    }


def status():
    cfg = _config()
    app_configurado = bool(cfg["client_id"] and cfg["client_secret"])
    tem_token = bool(cfg["access_token"])
    return {
        "conectado": app_configurado and tem_token,
        "app_configurado": app_configurado,
        "token_presente": tem_token,
        "expira_em": cfg["expires_at"] or None,
        "leitura_disponivel": app_configurado and tem_token,
        "escrita_disponivel": app_configurado and tem_token and bool(cfg["board_id"]),
        "motivo_pendente": None if (app_configurado and tem_token) else "credenciais_ausentes",
    }


def gerar_pkce():
    """Pinterest v5 exige PKCE (S256) no fluxo de authorization code."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def montar_url_autorizacao(redirect_uri, escopos=ESCOPOS_MINIMOS, state=None):
    cfg = _config()
    if not cfg["client_id"]:
        raise PinterestNaoConfigurado("pinterest_client_id_ausente")
    state = state or secrets.token_urlsafe(24)
    verifier, challenge = gerar_pkce()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": ",".join(escopos),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    # `verifier` precisa ser guardado pelo chamador (sessão do fluxo OAuth,
    # nunca em log) para usar em trocar_code_por_token().
    return f"{AUTH_URL}?{query}", state, verifier


def trocar_code_por_token(code, redirect_uri, code_verifier, timeout=15):
    cfg = _config()
    if not (cfg["client_id"] and cfg["client_secret"]):
        raise PinterestNaoConfigurado("pinterest_client_id_ou_secret_ausente")
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    resposta = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    return {"access_token": corpo.get("access_token"), "expires_in": corpo.get("expires_in")}


def _headers():
    cfg = _config()
    if not cfg["access_token"]:
        raise PinterestNaoConfigurado("pinterest_token_ausente")
    return {"Authorization": f"Bearer {cfg['access_token']}"}


def ler_boards(timeout=15):
    resposta = requests.get(f"{API_BASE}/boards", headers=_headers(), timeout=timeout)
    resposta.raise_for_status()
    return resposta.json()


def ler_analytics_conta(data_inicio, data_fim, timeout=15):
    """Analytics orgânico da conta -- user_accounts:read."""
    resposta = requests.get(
        f"{API_BASE}/user_account/analytics",
        headers=_headers(),
        params={"start_date": data_inicio, "end_date": data_fim, "metric_types": "IMPRESSION,PIN_CLICK,OUTBOUND_CLICK"},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()


def criar_pin(titulo, link, imagem_url, aprovado_por, timeout=15):
    """Nunca cria Pin sem aprovação humana explícita já registrada na fila
    existente -- `aprovado_por` vem preenchido só depois desse fluxo."""
    if not aprovado_por:
        raise PermissionError("criacao_pin_exige_aprovacao_humana_previa")
    cfg = _config()
    if not cfg["board_id"]:
        raise PinterestNaoConfigurado("pinterest_board_id_ausente")
    corpo = {
        "board_id": cfg["board_id"],
        "title": titulo,
        "link": link,
        "media_source": {"source_type": "image_url", "url": imagem_url},
    }
    resposta = requests.post(f"{API_BASE}/pins", headers=_headers(), json=corpo, timeout=timeout)
    resposta.raise_for_status()
    return {"success": True, "pin_id": resposta.json().get("id")}
