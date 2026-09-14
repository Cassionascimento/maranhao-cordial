"""Adaptador isolado LinkedIn (Community Management API) -- OAuth 2.0 +
publicação SOMENTE via fila/aprovação já existente. Nunca publica sozinho.

Credenciais só por env var (LINKEDIN_CLIENT_ID/SECRET/ACCESS_TOKEN/
TOKEN_EXPIRES_AT/ORGANIZATION_URN), nunca logadas nem persistidas em banco
por este módulo. Sem nenhuma dessas variáveis, toda função de rede recusa
(fail-closed) -- nunca inventa dado nem tenta prosseguir parcialmente.
"""
import os
import secrets

import requests

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com/rest"
API_VERSION = "202405"  # LinkedIn-Version obrigatório na API versionada atual

# Escopos do produto "Community Management API" (gestão da página da empresa).
ESCOPOS_ORGANIZACAO = (
    "r_organization_social",
    "r_organization_followers",
    "rw_organization_admin",
    "w_organization_social",
    "w_organization_social_feed",
    "r_organization_social_feed",
)
# Só se uso pessoal (perfil individual) for realmente necessário.
ESCOPOS_PESSOAL = ("w_member_social",)


class LinkedInNaoConfigurado(RuntimeError):
    """Falta client id/secret/token -- nunca chama a API sem isso."""


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
        "client_id": os.getenv("LINKEDIN_CLIENT_ID"),
        "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET"),
        "access_token": None if _DESCONECTADO_LOCALMENTE else os.getenv("LINKEDIN_ACCESS_TOKEN"),
        "expires_at": os.getenv("LINKEDIN_TOKEN_EXPIRES_AT"),
        "organization_urn": os.getenv("LINKEDIN_ORGANIZATION_URN"),
    }


def status():
    """Nunca retorna o token -- só presença/expiração, para o painel de canais."""
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
        "expira_em": cfg["expires_at"] or None,
        "leitura_disponivel": app_configurado and tem_token,
        "escrita_disponivel": app_configurado and tem_token and bool(cfg["organization_urn"]),
        "motivo_pendente": motivo,
    }


def montar_url_autorizacao(redirect_uri, escopos=ESCOPOS_ORGANIZACAO, state=None):
    """Etapa 1 do OAuth 2.0 (3-legged) -- LinkedIn não usa PKCE, mas exige
    `state` para mitigar CSRF; sempre gera um state aleatório se não vier um."""
    cfg = _config()
    if not cfg["client_id"]:
        raise LinkedInNaoConfigurado("linkedin_client_id_ausente")
    state = state or secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(escopos),
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{AUTH_URL}?{query}", state


def trocar_code_por_token(code, redirect_uri, timeout=15):
    """Etapa 2 -- troca o code pelo access_token. Nunca loga corpo/resposta;
    quem chama decide onde guardar (env var do processo de deploy)."""
    cfg = _config()
    if not (cfg["client_id"] and cfg["client_secret"]):
        raise LinkedInNaoConfigurado("linkedin_client_id_ou_secret_ausente")
    resposta = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    return {"access_token": corpo.get("access_token"), "expires_in": corpo.get("expires_in")}


def _headers():
    cfg = _config()
    if not cfg["access_token"]:
        raise LinkedInNaoConfigurado("linkedin_token_ausente")
    return {
        "Authorization": f"Bearer {cfg['access_token']}",
        "LinkedIn-Version": API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def ler_seguidores_organizacao(timeout=15):
    """Leitura somente -- r_organization_followers."""
    cfg = _config()
    if not cfg["organization_urn"]:
        raise LinkedInNaoConfigurado("linkedin_organization_urn_ausente")
    resposta = requests.get(
        f"{API_BASE}/organizationalEntityFollowerStatistics",
        headers=_headers(),
        params={"q": "organizationalEntity", "organizationalEntity": cfg["organization_urn"]},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()


def ler_posts_organizacao(count=10, timeout=15):
    """Leitura somente -- r_organization_social_feed. Posts recentes da
    página, sem nenhuma ação de escrita."""
    cfg = _config()
    if not cfg["organization_urn"]:
        raise LinkedInNaoConfigurado("linkedin_organization_urn_ausente")
    resposta = requests.get(
        f"{API_BASE}/posts",
        headers=_headers(),
        params={"q": "author", "author": cfg["organization_urn"], "count": count},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()


def ler_engajamento_e_analytics(timeout=15):
    """Leitura somente -- r_organization_social_feed. Estatísticas de
    engajamento (impressões, cliques, curtidas, comentários, compartilha-
    mentos) dos posts da organização -- cobre 'posts/engajamento' e
    'analytics' com a mesma chamada real da API (organizationalEntity
    ShareStatistics), sem inventar métrica nenhuma."""
    cfg = _config()
    if not cfg["organization_urn"]:
        raise LinkedInNaoConfigurado("linkedin_organization_urn_ausente")
    resposta = requests.get(
        f"{API_BASE}/organizationalEntityShareStatistics",
        headers=_headers(),
        params={"q": "organizationalEntity", "organizationalEntity": cfg["organization_urn"]},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()


def publicar_post_organizacao(texto, aprovado_por, timeout=15):
    """Nunca publica sem aprovação humana explícita já registrada na fila
    existente (mi_decisao) -- `aprovado_por` precisa vir preenchido pelo
    chamador, que só o faz depois do fluxo de aprovação já existente."""
    if not aprovado_por:
        raise PermissionError("publicacao_linkedin_exige_aprovacao_humana_previa")
    cfg = _config()
    if not cfg["organization_urn"]:
        raise LinkedInNaoConfigurado("linkedin_organization_urn_ausente")
    corpo = {
        "author": cfg["organization_urn"],
        "commentary": texto,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
    }
    resposta = requests.post(f"{API_BASE}/posts", headers=_headers(), json=corpo, timeout=timeout)
    resposta.raise_for_status()
    return {"success": True, "post_id": resposta.headers.get("x-restli-id")}


# =====================================================
# Rotas HTTP -- iniciar OAuth, receber callback, status, testar, desconectar.
# Nenhuma delas publica nada; escrita real continua em publicar_post_
# organizacao(), que exige aprovado_por e nunca é chamada por uma rota daqui.
# =====================================================
_TTL_STATE_SEGUNDOS = 600
_estados_pendentes = {}  # state -> criado_em (só memória do processo, nunca banco)


def _limpar_estados_expirados():
    import time
    agora = time.time()
    for chave in [k for k, criado in _estados_pendentes.items() if agora - criado > _TTL_STATE_SEGUNDOS]:
        _estados_pendentes.pop(chave, None)


def registrar_rotas_linkedin(app, validar_admin_request):
    import time
    from flask import jsonify, request

    def _redirect_uri():
        return os.getenv("LINKEDIN_REDIRECT_URI") or "https://maranhaocordial.com.br/api/admin/linkedin/callback"

    @app.route("/api/admin/linkedin/status", methods=["GET"])
    def linkedin_status_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        return jsonify(success=True, status=status())

    @app.route("/api/admin/linkedin/connect", methods=["GET"])
    def linkedin_connect_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            url, state = montar_url_autorizacao(_redirect_uri())
        except LinkedInNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        _limpar_estados_expirados()
        _estados_pendentes[state] = time.time()
        return jsonify(success=True, url=url)

    @app.route("/api/admin/linkedin/callback", methods=["GET"])
    def linkedin_callback_rota():
        # Redirecionamento do próprio LinkedIn -- sem X-Admin-Key possível
        # aqui; o `state` (imprevisível, de uso único, criado só depois de
        # /connect já ter exigido a chave admin) é a prova da sessão.
        state = request.args.get("state")
        code = request.args.get("code")
        erro_linkedin = request.args.get("error")
        _limpar_estados_expirados()
        if erro_linkedin:
            return jsonify(success=False, error="linkedin_recusou:" + erro_linkedin), 400
        if not state or state not in _estados_pendentes:
            return jsonify(success=False, error="state_invalido_ou_expirado"), 400
        _estados_pendentes.pop(state, None)
        if not code:
            return jsonify(success=False, error="code_ausente"), 400
        try:
            resultado = trocar_code_por_token(code, _redirect_uri())
        except Exception:
            return jsonify(success=False, error="falha_ao_trocar_code_por_token"), 502
        # Mostrado só esta vez, só para quem completou o fluxo -- nunca
        # logado, nunca salvo por este processo. Precisa ser colado como
        # LINKEDIN_ACCESS_TOKEN nas env vars do Render manualmente.
        return jsonify(
            success=True,
            aviso="Copie access_token para a env var LINKEDIN_ACCESS_TOKEN no Render agora -- não será mostrado de novo.",
            access_token=resultado.get("access_token"),
            expires_in=resultado.get("expires_in"),
        )

    @app.route("/api/admin/linkedin/testar", methods=["GET"])
    def linkedin_testar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        try:
            dados = ler_seguidores_organizacao()
            return jsonify(success=True, conexao="ok", amostra=bool(dados))
        except LinkedInNaoConfigurado as erro:
            return jsonify(success=False, error=str(erro)), 412
        except Exception:
            return jsonify(success=False, error="falha_ao_testar_conexao"), 502

    @app.route("/api/admin/linkedin/desconectar", methods=["POST"])
    def linkedin_desconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        revogar_localmente()
        return jsonify(success=True, status=status())

    @app.route("/api/admin/linkedin/reconectar", methods=["POST"])
    def linkedin_reconectar_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        reconectar_localmente()
        return jsonify(success=True, status=status())
