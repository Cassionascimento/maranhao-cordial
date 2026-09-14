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


# Kill-switch só de processo (nunca banco, nunca arquivo): permite o ADM
# "desconectar localmente" sem tocar no secret real, que continua só na env
# var do Render -- este módulo não tem permissão nem meio de apagá-la.
_DESCONECTADO_LOCALMENTE = False


def revogar_localmente():
    global _DESCONECTADO_LOCALMENTE
    _DESCONECTADO_LOCALMENTE = True


def reconectar_localmente():
    global _DESCONECTADO_LOCALMENTE
    _DESCONECTADO_LOCALMENTE = False


def _config():
    return {
        "client_id": os.getenv("X_CLIENT_ID"),
        "client_secret": os.getenv("X_CLIENT_SECRET"),
        "access_token": None if _DESCONECTADO_LOCALMENTE else os.getenv("X_ACCESS_TOKEN"),
        "refresh_token": os.getenv("X_REFRESH_TOKEN"),
        "expires_at": os.getenv("X_TOKEN_EXPIRES_AT"),
    }


def status():
    cfg = _config()
    app_configurado = bool(cfg["client_id"])
    tem_token = bool(cfg["access_token"])
    motivo = None if (app_configurado and tem_token) else (
        "desconectado_localmente" if _DESCONECTADO_LOCALMENTE else "credenciais_ausentes"
    )
    return {
        "conectado": app_configurado and tem_token,
        "app_configurado": app_configurado,
        "token_presente": tem_token,
        "renovavel": bool(cfg["refresh_token"]),
        "expira_em": cfg["expires_at"] or None,
        "leitura_disponivel": app_configurado and tem_token,
        "escrita_disponivel": app_configurado and tem_token,
        "motivo_pendente": motivo,
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


def renovar_token(timeout=15):
    """X emite refresh_token junto do access_token inicial quando o escopo
    offline.access foi concedido; usa-o para renovar sem novo consentimento."""
    cfg = _config()
    if not cfg["client_id"]:
        raise XNaoConfigurado("x_client_id_ausente")
    if not cfg["refresh_token"]:
        raise XNaoConfigurado("x_refresh_token_ausente")
    auth = None
    if cfg["client_secret"]:
        auth = (cfg["client_id"], cfg["client_secret"])
    resposta = requests.post(
        TOKEN_URL,
        auth=auth,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cfg["refresh_token"],
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


def ler_tweets_recentes(max_results=10, timeout=15):
    """Posts recentes da própria conta, com métricas públicas por tweet
    (like/retweet/reply/impression count) quando o plano da API permite --
    tweet.read/users.read. A API v2 exige o user id, não o @handle; por
    isso resolve via /users/me antes de listar. Sem acesso de leitura no
    plano contratado, a chamada falha (403/429) e nada é inventado aqui."""
    perfil = ler_metricas_usuario(timeout=timeout)
    user_id = perfil.get("data", {}).get("id")
    if not user_id:
        raise XNaoConfigurado("x_user_id_indisponivel")
    resposta = requests.get(
        f"{API_BASE}/users/{user_id}/tweets",
        headers=_headers(),
        params={"max_results": max(5, min(max_results, 100)), "tweet.fields": "created_at,public_metrics"},
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


# =====================================================
# Rotas HTTP -- iniciar OAuth, receber callback, status, testar, desconectar.
# Nenhuma delas publica tweet; escrita real continua em publicar_post(),
# que exige aprovado_por e nunca é chamada por uma rota daqui.
# =====================================================
_TTL_STATE_SEGUNDOS = 600
_estados_pendentes = {}  # state -> {"criado_em": ts, "verifier": str} (só memória do processo)


def _limpar_estados_expirados():
    import time
    agora = time.time()
    for chave in [k for k, v in _estados_pendentes.items() if agora - v["criado_em"] > _TTL_STATE_SEGUNDOS]:
        _estados_pendentes.pop(chave, None)


def registrar_rotas_x(app, validar_admin_request):
    import time
    from flask import jsonify, request

    def _redirect_uri():
        return os.getenv("X_REDIRECT_URI") or "https://maranhaocordial.com.br/api/admin/x/callback"

    @app.route("/api/admin/x/status", methods=["GET"])
    def x_status_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        return jsonify(success=True, status=status())

    @app.route("/api/admin/x/connect", methods=["GET"])
    def x_connect_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            url, state, verifier = montar_url_autorizacao(_redirect_uri())
        except XNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        _limpar_estados_expirados()
        _estados_pendentes[state] = {"criado_em": time.time(), "verifier": verifier}
        return jsonify(success=True, url=url)

    @app.route("/api/admin/x/callback", methods=["GET"])
    def x_callback_rota():
        # Redirecionamento do próprio X -- sem X-Admin-Key possível aqui;
        # o `state` (imprevisível, de uso único, criado só depois de
        # /connect já ter exigido a chave admin) é a prova da sessão.
        state = request.args.get("state")
        code = request.args.get("code")
        erro_x = request.args.get("error")
        _limpar_estados_expirados()
        if erro_x:
            return jsonify(success=False, error="x_recusou:" + erro_x), 400
        entrada = _estados_pendentes.get(state) if state else None
        if not entrada:
            return jsonify(success=False, error="state_invalido_ou_expirado"), 400
        _estados_pendentes.pop(state, None)
        if not code:
            return jsonify(success=False, error="code_ausente"), 400
        try:
            resultado = trocar_code_por_token(code, _redirect_uri(), entrada["verifier"])
        except Exception:
            return jsonify(success=False, error="falha_ao_trocar_code_por_token"), 502
        # Mostrado só esta vez, só para quem completou o fluxo -- nunca
        # logado, nunca salvo por este processo. Precisa ser colado como
        # X_ACCESS_TOKEN/X_REFRESH_TOKEN no Render.
        return jsonify(
            success=True,
            aviso="Copie access_token e refresh_token para X_ACCESS_TOKEN/X_REFRESH_TOKEN no Render agora -- não serão mostrados de novo.",
            access_token=resultado.get("access_token"),
            refresh_token=resultado.get("refresh_token"),
            expires_in=resultado.get("expires_in"),
        )

    @app.route("/api/admin/x/testar", methods=["GET"])
    def x_testar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            dados = ler_metricas_usuario()
            return jsonify(success=True, conexao="ok", amostra=bool(dados))
        except XNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        except Exception:
            return jsonify(success=False, error="falha_ao_testar_conexao"), 502

    @app.route("/api/admin/x/desconectar", methods=["POST"])
    def x_desconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        revogar_localmente()
        return jsonify(success=True, status=status())

    @app.route("/api/admin/x/reconectar", methods=["POST"])
    def x_reconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        reconectar_localmente()
        return jsonify(success=True, status=status())
