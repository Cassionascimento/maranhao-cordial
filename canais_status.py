"""Camada única de status dos canais externos para o painel do ADM.

Só agrega leituras (env vars + funções de status já existentes) -- nenhuma
chamada de rede, nenhuma ação, nenhum dado inventado. Onde não há como
saber (ex.: última sincronização/último erro de um canal que nunca chamou
a API de verdade), o campo fica None -- o painel mostra estado vazio, não
um valor fabricado.
"""
import os

import linkedin_conector
import pinterest_conector
import x_conector


def _estado(conectado, motivo_pendente):
    if conectado:
        return "conectado"
    if motivo_pendente == "credenciais_ausentes":
        return "pendente"
    return "bloqueado"


# Passo externo concreto por canal/estado -- texto fixo, não é uma métrica;
# só orienta qual credencial/config falta em cada portal quando pendente.
_PROXIMO_PASSO = {
    "LinkedIn": "Criar app no LinkedIn Developer Portal (produto Community Management aprovado) e definir LINKEDIN_CLIENT_ID/SECRET/ACCESS_TOKEN.",
    "Pinterest": "Criar app no Pinterest Developers, cadastrar o callback e completar /api/admin/pinterest/connect para obter PINTEREST_ACCESS_TOKEN/REFRESH_TOKEN.",
    "X": "Criar app no X Developer Portal, cadastrar o callback e completar /api/admin/x/connect para obter X_ACCESS_TOKEN/REFRESH_TOKEN.",
    "Instagram": "Definir INSTAGRAM_ACCESS_TOKEN (ou META_INSTAGRAM_ACCESS_TOKEN) via Meta Business.",
    "Gmail": "Clicar em \"Conectar Gmail institucional\" no ADM e concluir o login Google (rotas /api/gmail/conectar e /api/gmail/callback já existentes).",
}


def _proximo_passo(canal, estado, motivo=None):
    if estado == "conectado":
        return None
    if canal == "WhatsApp":
        return motivo or "Concluir validação Meta (WABA/número/assinatura de webhook)."
    return _PROXIMO_PASSO.get(canal)


def _canal_whatsapp():
    try:
        from whatsapp_omnichannel import status_conector
        s = status_conector()
        prontidao = s.get("prontidao", {})
        conectado = bool(s.get("envio_liberado"))
        estado = "conectado" if conectado else ("pendente" if prontidao.get("estado") in
                 ("nao_configurado", "configurado", "validacao_externa_pendente") else "bloqueado")
        return {
            "canal": "WhatsApp",
            "estado": estado,
            "ultima_sincronizacao": None,
            "leitura_disponivel": prontidao.get("estado") not in (None, "nao_configurado"),
            "escrita_disponivel": conectado,
            "aprovacao_exigida": True,
            "ultimo_erro": prontidao.get("motivo") if estado == "bloqueado" else None,
            "proximo_passo": _proximo_passo("WhatsApp", estado, prontidao.get("motivo")),
        }
    except Exception as erro:
        return {
            "canal": "WhatsApp", "estado": "bloqueado", "ultima_sincronizacao": None,
            "leitura_disponivel": False, "escrita_disponivel": False,
            "aprovacao_exigida": True, "ultimo_erro": type(erro).__name__,
            "proximo_passo": _proximo_passo("WhatsApp", "bloqueado"),
        }


def _canal_instagram():
    conectado = bool(os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("META_INSTAGRAM_ACCESS_TOKEN"))
    return {
        "canal": "Instagram",
        "estado": "conectado" if conectado else "pendente",
        "ultima_sincronizacao": None,
        "leitura_disponivel": conectado,
        "escrita_disponivel": False,
        "aprovacao_exigida": True,
        "ultimo_erro": None,
        "proximo_passo": _proximo_passo("Instagram", "conectado" if conectado else "pendente"),
    }


def _credencial_oauth_gmail(factory):
    """A conexão institucional (botão "Conectar Gmail institucional" no ADM,
    rotas /api/gmail/conectar|callback) persiste em gmail_oauth_credentials,
    não em env var -- só essa tabela reflete se aquele fluxo foi concluído."""
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT atualizado_em FROM gmail_oauth_credentials ORDER BY atualizado_em DESC LIMIT 1")
            linha = cur.fetchone()
            return linha[0] if linha else None
    finally:
        conn.close()


def _canal_gmail(factory):
    via_env = bool(os.getenv("GMAIL_REFRESH_TOKEN") or os.getenv("GOOGLE_REFRESH_TOKEN"))
    ultima_sincronizacao = None
    try:
        atualizado_em = _credencial_oauth_gmail(factory)
    except Exception:
        atualizado_em = None
    conectado = via_env or bool(atualizado_em)
    if atualizado_em:
        ultima_sincronizacao = atualizado_em.isoformat()
    return {
        "canal": "Gmail",
        "estado": "conectado" if conectado else "pendente",
        "ultima_sincronizacao": ultima_sincronizacao,
        "leitura_disponivel": conectado,
        "escrita_disponivel": conectado,
        "aprovacao_exigida": True,
        "ultimo_erro": None,
        "proximo_passo": _proximo_passo("Gmail", "conectado" if conectado else "pendente"),
    }


def _canal_generico(nome, modulo):
    s = modulo.status()
    estado = _estado(s["conectado"], s["motivo_pendente"])
    return {
        "canal": nome,
        "estado": estado,
        "ultima_sincronizacao": None,
        "leitura_disponivel": s["leitura_disponivel"],
        "escrita_disponivel": s["escrita_disponivel"],
        "aprovacao_exigida": True,
        "ultimo_erro": None,
        "proximo_passo": _proximo_passo(nome, estado),
    }


def status_todos_os_canais(factory):
    """Ordem fixa pedida: Instagram, WhatsApp, LinkedIn, Pinterest, X, Gmail."""
    return [
        _canal_instagram(),
        _canal_whatsapp(),
        _canal_generico("LinkedIn", linkedin_conector),
        _canal_generico("Pinterest", pinterest_conector),
        _canal_generico("X", x_conector),
        _canal_gmail(factory),
    ]


def registrar_rotas_canais(app, factory, validar_admin_request):
    from flask import jsonify, request

    @app.route("/api/admin/canais/status", methods=["GET"])
    def canais_status_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        return jsonify(success=True, canais=status_todos_os_canais(factory))
