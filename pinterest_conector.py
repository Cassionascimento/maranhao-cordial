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
        "client_id": os.getenv("PINTEREST_CLIENT_ID"),
        "client_secret": os.getenv("PINTEREST_CLIENT_SECRET"),
        "access_token": None if _DESCONECTADO_LOCALMENTE else os.getenv("PINTEREST_ACCESS_TOKEN"),
        "refresh_token": os.getenv("PINTEREST_REFRESH_TOKEN"),
        "expires_at": os.getenv("PINTEREST_TOKEN_EXPIRES_AT"),
        "board_id": os.getenv("PINTEREST_BOARD_ID"),
    }


def status():
    cfg = _config()
    app_configurado = bool(cfg["client_id"] and cfg["client_secret"])
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
        "escrita_disponivel": app_configurado and tem_token and bool(cfg["board_id"]),
        "motivo_pendente": motivo,
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
    return {
        "access_token": corpo.get("access_token"),
        "refresh_token": corpo.get("refresh_token"),
        "expires_in": corpo.get("expires_in"),
    }


def renovar_token(timeout=15):
    """Pinterest v5 emite refresh_token de vida longa junto do access_token
    inicial; usa-o para renovar sem passar pelo consentimento de novo."""
    cfg = _config()
    if not (cfg["client_id"] and cfg["client_secret"]):
        raise PinterestNaoConfigurado("pinterest_client_id_ou_secret_ausente")
    if not cfg["refresh_token"]:
        raise PinterestNaoConfigurado("pinterest_refresh_token_ausente")
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    resposta = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}"},
        data={"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"]},
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


def ler_pins_de_board(board_id, timeout=15):
    """Leitura somente -- pins:read."""
    resposta = requests.get(f"{API_BASE}/boards/{board_id}/pins", headers=_headers(), timeout=timeout)
    resposta.raise_for_status()
    return resposta.json()


def ler_analytics_pin(pin_id, data_inicio, data_fim, timeout=15):
    """Métricas por Pin (impressões, saves, cliques) -- pins:read. Cobre
    'top pins' quando chamada para cada pin de interesse; a API v5 não tem
    endpoint único de ranking, então não inventamos um -- é uma métrica por
    vez, real, oficial."""
    resposta = requests.get(
        f"{API_BASE}/pins/{pin_id}/analytics",
        headers=_headers(),
        params={"start_date": data_inicio, "end_date": data_fim, "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK"},
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


# =====================================================
# Rotas HTTP -- iniciar OAuth, receber callback, status, testar, desconectar.
# Nenhuma delas cria Pin nem board; escrita real continua em criar_pin(),
# que exige aprovado_por e nunca é chamada por uma rota daqui.
# =====================================================
_TTL_STATE_SEGUNDOS = 600
_estados_pendentes = {}  # state -> {"criado_em": ts, "verifier": str} (só memória do processo)


def _limpar_estados_expirados():
    import time
    agora = time.time()
    for chave in [k for k, v in _estados_pendentes.items() if agora - v["criado_em"] > _TTL_STATE_SEGUNDOS]:
        _estados_pendentes.pop(chave, None)


def registrar_rotas_pinterest(app, validar_admin_request):
    import time
    from flask import jsonify, request

    def _redirect_uri():
        return os.getenv("PINTEREST_REDIRECT_URI") or "https://maranhaocordial.com.br/api/admin/pinterest/callback"

    @app.route("/api/admin/pinterest/status", methods=["GET"])
    def pinterest_status_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        return jsonify(success=True, status=status())

    @app.route("/api/admin/pinterest/connect", methods=["GET"])
    def pinterest_connect_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            url, state, verifier = montar_url_autorizacao(_redirect_uri())
        except PinterestNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        _limpar_estados_expirados()
        _estados_pendentes[state] = {"criado_em": time.time(), "verifier": verifier}
        return jsonify(success=True, url=url)

    @app.route("/api/admin/pinterest/callback", methods=["GET"])
    def pinterest_callback_rota():
        # Redirecionamento do próprio Pinterest -- sem X-Admin-Key possível
        # aqui; o `state` (imprevisível, de uso único, criado só depois de
        # /connect já ter exigido a chave admin) é a prova da sessão.
        state = request.args.get("state")
        code = request.args.get("code")
        erro_pinterest = request.args.get("error")
        _limpar_estados_expirados()
        if erro_pinterest:
            return jsonify(success=False, error="pinterest_recusou:" + erro_pinterest), 400
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
        # PINTEREST_ACCESS_TOKEN/PINTEREST_REFRESH_TOKEN no Render.
        return jsonify(
            success=True,
            aviso="Copie access_token e refresh_token para PINTEREST_ACCESS_TOKEN/PINTEREST_REFRESH_TOKEN no Render agora -- não serão mostrados de novo.",
            access_token=resultado.get("access_token"),
            refresh_token=resultado.get("refresh_token"),
            expires_in=resultado.get("expires_in"),
        )

    @app.route("/api/admin/pinterest/testar", methods=["GET"])
    def pinterest_testar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            dados = ler_boards()
            return jsonify(success=True, conexao="ok", amostra=bool(dados))
        except PinterestNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        except Exception:
            return jsonify(success=False, error="falha_ao_testar_conexao"), 502

    @app.route("/api/admin/pinterest/desconectar", methods=["POST"])
    def pinterest_desconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        revogar_localmente()
        return jsonify(success=True, status=status())

    @app.route("/api/admin/pinterest/reconectar", methods=["POST"])
    def pinterest_reconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        reconectar_localmente()
        return jsonify(success=True, status=status())
