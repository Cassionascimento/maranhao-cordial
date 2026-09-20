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


def _gmail_diagnostico(factory):
    """Gmail não tem probe externo barato aqui: a prova de conexão é a
    credencial OAuth persistida pelo fluxo institucional. Consultar a API
    a cada abertura do painel gastaria cota sem acrescentar informação."""
    import canais_diagnostico as cd
    dado = cd._base("Gmail", grupo="mensageria")
    dado["ultima_tentativa"] = cd._agora()
    try:
        atualizado_em = _credencial_oauth_gmail(factory)
    except Exception as erro:
        dado["estado"] = "erro"
        dado["ultimo_erro"] = "nao_foi_possivel_ler_a_credencial_persistida"
        dado["codigo_erro"] = type(erro).__name__
        return dado
    via_env = bool(os.getenv("GMAIL_REFRESH_TOKEN") or os.getenv("GOOGLE_REFRESH_TOKEN"))
    if not atualizado_em and not via_env:
        dado["estado"] = "aguardando_autorizacao"
        dado["exige_acao_admin"] = True
        dado["proximo_passo"] = ('Abrir Operação → Mensagens → "Conectar Gmail institucional" '
                                 "e concluir o login Google.")
        return dado
    dado["estado"] = "conectado"
    dado["tipo_conta"] = "Caixa institucional (OAuth)"
    dado["leitura_disponivel"] = True
    dado["escrita_disponivel"] = True
    dado["ultima_sincronizacao"] = atualizado_em.isoformat() if atualizado_em else None
    dado["permissoes_concedidas"] = ["gmail.readonly", "gmail.send"] if atualizado_em else None
    return dado


_CAMPOS_COMPARADOS = ("estado", "leitura_disponivel", "escrita_disponivel", "webhook_ativo",
                      "conta", "codigo_erro", "ultimo_erro")


def registrar_diagnostico(factory, dado):
    """Grava no histórico só quando algo MUDOU.

    Abrir o painel dez vezes não pode virar dez linhas iguais -- o histórico
    existe para mostrar quando um canal quebrou ou voltou, não para medir
    quantas vezes alguém olhou. Best-effort: se a tabela ainda não existe
    (migration 025 não aplicada), a leitura continua funcionando.
    """
    try:
        conn = factory()
    except Exception:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT estado,leitura_disponivel,escrita_disponivel,webhook_ativo,conta,"
                    "codigo_erro,ultimo_erro FROM canais_diagnostico_historico "
                    "WHERE canal=%s ORDER BY verificado_em DESC LIMIT 1", (dado["canal"],))
                anterior = cur.fetchone()
                atual = tuple(dado.get(campo) for campo in _CAMPOS_COMPARADOS)
                if anterior and tuple(anterior) == atual:
                    return False
                cur.execute(
                    "INSERT INTO canais_diagnostico_historico(canal,estado,leitura_disponivel,"
                    "escrita_disponivel,webhook_ativo,conta,tipo_conta,permissoes_ausentes,"
                    "token_expira_em,ultimo_erro,codigo_erro,exige_acao_admin,"
                    "aguardando_plataforma,verificacao_remota) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (dado["canal"], dado["estado"], dado["leitura_disponivel"],
                     dado["escrita_disponivel"], dado["webhook_ativo"], dado["conta"],
                     dado["tipo_conta"], dado.get("permissoes_ausentes"),
                     dado.get("token_expira_em"), dado["ultimo_erro"], dado["codigo_erro"],
                     dado["exige_acao_admin"], dado["aguardando_plataforma"],
                     dado["verificacao_remota"]))
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def historico_do_canal(factory, canal, limite=10):
    """Últimas mudanças de estado deste canal. Lista vazia se a tabela não
    existir -- o painel mostra "sem histórico", nunca um erro."""
    try:
        conn = factory()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT estado,codigo_erro,ultimo_erro,verificado_em "
                "FROM canais_diagnostico_historico WHERE canal=%s "
                "ORDER BY verificado_em DESC LIMIT %s", (canal, limite))
            return [{"estado": l[0], "codigo_erro": l[1], "ultimo_erro": l[2],
                     "verificado_em": l[3].isoformat() if l[3] else None}
                    for l in cur.fetchall()]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def diagnostico_todos_os_canais(factory, http=None, env=None):
    """Contrato rico da FASE 2: pergunta a cada plataforma o estado real.

    Custa chamadas externas de LEITURA, por isso não substitui
    status_todos_os_canais() na abertura rápida do painel -- é acionado
    pelo botão de diagnóstico e pelo carregamento da tela de Canais.
    Falha de um canal nunca contamina os outros.
    """
    import time

    import canais_diagnostico as cd
    canais = []
    limite = time.monotonic() + cd.ORCAMENTO_SEGUNDOS
    for nome in ("WhatsApp", "Instagram", "LinkedIn", "TikTok Shop",
                 "TikTok Social", "Pinterest", "X"):
        if time.monotonic() >= limite:
            canais.append(cd.nao_verificado(nome, 'orcamento_de_tempo_esgotado'))
            continue
        canais.append(cd.diagnosticar(nome, http=http, env=env))
    canais.append(_gmail_diagnostico(factory))
    # Ordem de prioridade operacional declarada na ordem de execução.
    prioridade = {"WhatsApp": 0, "TikTok Shop": 1, "LinkedIn": 2, "Instagram": 3,
                  "Gmail": 4, "TikTok Social": 5, "Pinterest": 6, "X": 7}
    canais.sort(key=lambda c: prioridade.get(c["canal"], 99))
    for dado in canais:
        registrar_diagnostico(factory, dado)
    return canais


def registrar_rotas_canais(app, factory, validar_admin_request):
    from flask import jsonify, request

    @app.route("/api/admin/canais/status", methods=["GET"])
    def canais_status_rota():
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        # ?remoto=1 pergunta às plataformas; sem o parâmetro mantém a
        # leitura local barata que o painel antigo já usava.
        if request.args.get("remoto") in ("1", "true", "sim"):
            return jsonify(success=True, diagnostico_remoto=True,
                           canais=diagnostico_todos_os_canais(factory))
        return jsonify(success=True, diagnostico_remoto=False,
                       canais=status_todos_os_canais(factory))

    @app.route("/api/admin/canais/diagnostico", methods=["GET"])
    def canais_diagnostico_rota():
        """Diagnóstico de UM canal -- o botão "Atualizar" de cada cartão."""
        if not validar_admin_request():
            return jsonify(success=False, error="nao_autorizado"), 401
        import canais_diagnostico as cd
        canal = request.args.get("canal") or ""
        if canal == "Gmail":
            dado = _gmail_diagnostico(factory)
            registrar_diagnostico(factory, dado)
            return jsonify(success=True, canal=dado,
                           historico=historico_do_canal(factory, "Gmail"))
        if canal not in cd.REGISTRO:
            return jsonify(success=False, error="canal_desconhecido"), 404
        dado = cd.diagnosticar(canal)
        registrar_diagnostico(factory, dado)
        return jsonify(success=True, canal=dado,
                       historico=historico_do_canal(factory, canal))
