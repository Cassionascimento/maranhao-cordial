"""
Fase 5 — IA Empresarial Maranhão Cordial.

Fecha o ciclo:
passivo -> identidade -> relacionamento -> próxima ação -> decisão humana
-> resultado real -> aprendizado -> próximas recomendações.

Não envia mensagens, não publica conteúdo e não aprova ações externas.
"""

import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


def _conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não configurada.")
    return psycopg2.connect(url)


def reconciliar_interacoes_passivas_fase5(limite=500):
    """Vincula somente por identidade forte. Nunca por nome isolado."""
    limite = max(1, min(int(limite or 500), 2000))
    conn = _conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Gmail/e-mail: igualdade exata.
                cur.execute("""
                    WITH c AS (
                        SELECT i.id, l.id contato_id
                        FROM interacoes_omnichannel i
                        JOIN leads_crm l
                          ON LOWER(TRIM(COALESCE(i.sender_id, '')))
                           = LOWER(TRIM(COALESCE(l.email, '')))
                        WHERE i.lead_id IS NULL
                          AND LOWER(COALESCE(i.canal, '')) IN ('gmail','email')
                          AND COALESCE(TRIM(i.sender_id), '') <> ''
                          AND COALESCE(l.valido_para_ia, TRUE) = TRUE
                          AND COALESCE(l.cadastro_teste, FALSE) = FALSE
                          AND COALESCE(l.contato_interno, FALSE) = FALSE
                          AND LOWER(COALESCE(i.tipo_interacao, ''))
                              NOT IN ('mensagem_saida','saida')
                        ORDER BY i.criado_em DESC
                        LIMIT %s
                    )
                    UPDATE interacoes_omnichannel i
                       SET lead_id = c.contato_id
                      FROM c
                     WHERE i.id = c.id
                """, (limite,))
                email = max(cur.rowcount, 0)

                # WhatsApp: número exato após normalização.
                cur.execute("""
                    WITH c AS (
                        SELECT i.id, l.id contato_id
                        FROM interacoes_omnichannel i
                        JOIN leads_crm l
                          ON REGEXP_REPLACE(COALESCE(i.sender_id,''),'\\D','','g')
                           = REGEXP_REPLACE(COALESCE(l.telefone,''),'\\D','','g')
                        WHERE i.lead_id IS NULL
                          AND LOWER(COALESCE(i.canal,'')) = 'whatsapp'
                          AND LENGTH(REGEXP_REPLACE(
                              COALESCE(i.sender_id,''),'\\D','','g'
                          )) >= 8
                          AND COALESCE(l.valido_para_ia, TRUE) = TRUE
                          AND COALESCE(l.cadastro_teste, FALSE) = FALSE
                          AND COALESCE(l.contato_interno, FALSE) = FALSE
                          AND LOWER(COALESCE(i.tipo_interacao,''))
                              NOT IN ('mensagem_saida','saida')
                        ORDER BY i.criado_em DESC
                        LIMIT %s
                    )
                    UPDATE interacoes_omnichannel i
                       SET lead_id = c.contato_id
                      FROM c
                     WHERE i.id = c.id
                """, (limite,))
                whatsapp = max(cur.rowcount, 0)

                # Identidade externa já consolidada pelo sistema.
                cur.execute("""
                    WITH c AS (
                        SELECT i.id, x.contato_central_id contato_id
                        FROM interacoes_omnichannel i
                        JOIN identidades_externas_contato x
                          ON LOWER(COALESCE(x.canal,''))
                           = LOWER(COALESCE(i.canal,''))
                         AND (
                            LOWER(TRIM(LEADING '@' FROM
                                COALESCE(x.identificador_externo,'')))
                            = LOWER(TRIM(LEADING '@' FROM
                                COALESCE(i.sender_id,'')))
                            OR (
                                COALESCE(TRIM(x.username_publico),'') <> ''
                                AND LOWER(TRIM(LEADING '@' FROM
                                    x.username_publico))
                                = LOWER(TRIM(LEADING '@' FROM
                                    COALESCE(i.sender_id,'')))
                            )
                         )
                        JOIN leads_crm l ON l.id = x.contato_central_id
                        WHERE i.lead_id IS NULL
                          AND x.contato_central_id IS NOT NULL
                          AND COALESCE(x.status,'ativo') = 'ativo'
                          AND COALESCE(l.valido_para_ia, TRUE) = TRUE
                          AND COALESCE(l.cadastro_teste, FALSE) = FALSE
                          AND COALESCE(l.contato_interno, FALSE) = FALSE
                          AND COALESCE(TRIM(i.sender_id),'') <> ''
                          AND LOWER(COALESCE(i.tipo_interacao,''))
                              NOT IN ('mensagem_saida','saida')
                        ORDER BY i.criado_em DESC
                        LIMIT %s
                    )
                    UPDATE interacoes_omnichannel i
                       SET lead_id = c.contato_id
                      FROM c
                     WHERE i.id = c.id
                """, (limite,))
                identidade = max(cur.rowcount, 0)

        return {
            "success": True,
            "email": email,
            "whatsapp": whatsapp,
            "identidade_externa": identidade,
            "total": email + whatsapp + identidade,
        }
    finally:
        conn.close()


def preencher_proximas_acoes_fase5(limite=500):
    """Backfill interno. Não cria comunicação externa."""
    limite = max(1, min(int(limite or 500), 2000))
    conn = _conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH ids AS (
                        SELECT id
                        FROM leads_crm
                        WHERE COALESCE(valido_para_ia, TRUE) = TRUE
                          AND COALESCE(cadastro_teste, FALSE) = FALSE
                          AND COALESCE(contato_interno, FALSE) = FALSE
                          AND COALESCE(arquivado, FALSE) = FALSE
                          AND COALESCE(TRIM(proxima_acao), '') = ''
                          AND COALESCE(status,'ativo')
                              NOT IN ('arquivado','excluido')
                        ORDER BY
                            ultima_interacao_em DESC NULLS LAST,
                            atualizado_em DESC NULLS LAST
                        LIMIT %s
                    )
                    UPDATE leads_crm l
                    SET proxima_acao = CASE
                        WHEN l.categoria_contato IN ('fabrica','fornecedor')
                            THEN 'avaliar pendência operacional e definir continuidade'
                        WHEN l.categoria_contato = 'bartender'
                            THEN 'avaliar teste, feedback e potencial de relacionamento'
                        WHEN l.categoria_contato IN (
                            'restaurante','bar','hotel','empresa',
                            'distribuidor','revendedor'
                        )
                            THEN 'qualificar oportunidade e definir próximo passo comercial'
                        WHEN l.categoria_contato IN (
                            'profissional','parceiro','estrategico'
                        )
                            THEN 'avaliar oportunidade de relacionamento e continuidade'
                        WHEN l.categoria_contato IN (
                            'imprensa','jornalista','influenciador','criador'
                        )
                            THEN 'avaliar oportunidade de comunicação e relacionamento'
                        WHEN l.categoria_contato = 'investidor'
                            THEN 'avaliar interesse institucional e próxima conversa'
                        WHEN l.categoria_contato = 'consumidor'
                            THEN 'avaliar interesse e próxima etapa do relacionamento'
                        ELSE 'avaliar relacionamento e definir próxima ação'
                    END,
                    motivo_proxima_acao = COALESCE(
                        NULLIF(TRIM(l.motivo_proxima_acao),''),
                        'Fase 5: relacionamento válido sem próxima ação registrada.'
                    ),
                    proximo_followup = COALESCE(
                        l.proximo_followup,
                        NOW() + CASE
                            WHEN l.categoria_contato IN ('fabrica','fornecedor')
                                THEN INTERVAL '2 days'
                            WHEN l.categoria_contato IN (
                                'bartender','restaurante','bar','hotel',
                                'empresa','distribuidor','revendedor'
                            )
                                THEN INTERVAL '3 days'
                            ELSE INTERVAL '5 days'
                        END
                    ),
                    atualizado_em = NOW()
                    FROM ids
                    WHERE l.id = ids.id
                """, (limite,))
                atualizados = max(cur.rowcount, 0)
        return {"success": True, "atualizados": atualizados}
    finally:
        conn.close()


def obter_padroes_aprendidos_fase5(area=None, limite=8):
    """
    Agrega memória real. Aprovação e resultado são sinais diferentes.
    Resultado real pesa mais que aprovação inicial.
    """
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = []
            filtro = ""
            if area:
                filtro = "WHERE LOWER(COALESCE(m.area,'')) = LOWER(%s)"
                params.append(area)

            params.append(max(1, min(int(limite or 8), 30)))

            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(TRIM(m.area),''),'geral') AS area,
                    COALESCE(
                        NULLIF(TRIM(a.tipo_execucao),''),
                        NULLIF(TRIM(a.tipo),''),
                        'acao'
                    ) AS tipo_execucao,
                    COALESCE(NULLIF(TRIM(a.canal),''),'interno') AS canal,
                    COUNT(*)::INTEGER total_decisoes,
                    COUNT(*) FILTER (
                        WHERE m.decisao = 'aprovada'
                    )::INTEGER aprovacoes,
                    COUNT(*) FILTER (
                        WHERE m.decisao = 'recusada'
                    )::INTEGER recusas,
                    COUNT(*) FILTER (
                        WHERE m.avaliacao_resultado IN (
                            'positivo','neutro','negativo','inconclusivo'
                        )
                    )::INTEGER resultados_avaliados,
                    COUNT(*) FILTER (
                        WHERE m.avaliacao_resultado = 'positivo'
                    )::INTEGER positivos,
                    COUNT(*) FILTER (
                        WHERE m.avaliacao_resultado = 'negativo'
                    )::INTEGER negativos,
                    COUNT(*) FILTER (
                        WHERE m.avaliacao_resultado = 'inconclusivo'
                    )::INTEGER inconclusivos,
                    MAX(m.atualizado_em) ultima_evidencia_em
                FROM memoria_decisoes_ia m
                LEFT JOIN acoes_empresariais a ON a.id = m.acao_id
                {filtro}
                GROUP BY 1,2,3
                ORDER BY COUNT(*) DESC, MAX(m.atualizado_em) DESC
                LIMIT %s
            """, tuple(params))
            dados = [dict(x) for x in cur.fetchall()]
    finally:
        conn.close()

    for p in dados:
        total = int(p.get("total_decisoes") or 0)
        avaliados = int(p.get("resultados_avaliados") or 0)
        decisao = (
            (int(p.get("aprovacoes") or 0) - int(p.get("recusas") or 0))
            / max(total, 1)
        )
        resultado = (
            (int(p.get("positivos") or 0) - int(p.get("negativos") or 0))
            / max(avaliados, 1)
            if avaliados else 0.0
        )
        p["score_decisao"] = round(decisao, 3)
        p["score_resultado"] = round(resultado, 3)
        p["score_final"] = round(
            0.35 * decisao + (0.65 * resultado if avaliados else 0),
            3,
        )
        p["confianca"] = (
            "alta" if total >= 8 and avaliados >= 4
            else "media" if total >= 4 and avaliados >= 2
            else "baixa"
        )
        if p.get("ultima_evidencia_em"):
            p["ultima_evidencia_em"] = p[
                "ultima_evidencia_em"
            ].isoformat()

    return dados


def obter_contexto_aprendizado_fase5(area=None):
    padroes = [
        p for p in obter_padroes_aprendidos_fase5(area=area, limite=8)
        if int(p.get("total_decisoes") or 0) >= 2
    ]
    if not padroes:
        return {"contexto": "", "padroes": []}

    linhas = [
        "",
        "=== APRENDIZADO FASE 5 — DECISÕES + RESULTADOS ===",
        (
            "Use apenas como evidência consultiva. Aprovação não significa sucesso. "
            "Resultados reais pesam mais. Confiança baixa é sinal fraco. "
            "Nunca autorize automaticamente comunicação externa, preço, pagamento, "
            "contrato ou compromisso com base nestes padrões."
        ),
    ]
    for p in padroes:
        linhas.append(
            "- "
            f"área={p['area']}; tipo={p['tipo_execucao']}; canal={p['canal']}; "
            f"decisões={p['total_decisoes']}; aprovadas={p['aprovacoes']}; "
            f"recusadas={p['recusas']}; positivos={p['positivos']}; "
            f"negativos={p['negativos']}; score={p['score_final']}; "
            f"confiança={p['confianca']}."
        )
    return {"contexto": "\n".join(linhas) + "\n", "padroes": padroes}


def listar_fila_ativa_fase5(limite=20):
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id, nome, empresa, categoria_contato, estagio,
                    prioridade, proxima_acao, motivo_proxima_acao,
                    proximo_followup, ultimo_resultado, ultima_interacao_em
                FROM leads_crm
                WHERE COALESCE(valido_para_ia, TRUE) = TRUE
                  AND COALESCE(cadastro_teste, FALSE) = FALSE
                  AND COALESCE(contato_interno, FALSE) = FALSE
                  AND COALESCE(TRIM(proxima_acao),'') <> ''
                  AND COALESCE(status,'ativo')
                      NOT IN ('arquivado','excluido')
                ORDER BY
                    CASE WHEN proximo_followup <= NOW() THEN 0 ELSE 1 END,
                    CASE prioridade
                        WHEN 'critica' THEN 0
                        WHEN 'alta' THEN 1
                        WHEN 'media' THEN 2
                        ELSE 3
                    END,
                    proximo_followup ASC NULLS LAST,
                    ultima_interacao_em DESC NULLS LAST
                LIMIT %s
            """, (max(1, min(int(limite or 20), 100)),))
            dados = [dict(x) for x in cur.fetchall()]
    finally:
        conn.close()

    for x in dados:
        x["id"] = str(x["id"])
        for campo in ("proximo_followup","ultima_interacao_em"):
            if x.get(campo):
                x[campo] = x[campo].isoformat()
    return dados


def obter_status_fase5():
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*)::INTEGER total,
                       COUNT(*) FILTER (
                           WHERE lead_id IS NULL
                       )::INTEGER sem_vinculo
                FROM interacoes_omnichannel
            """)
            i = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT COUNT(*)::INTEGER total,
                       COUNT(*) FILTER (
                           WHERE COALESCE(TRIM(proxima_acao),'') <> ''
                       )::INTEGER com_acao
                FROM leads_crm
                WHERE COALESCE(valido_para_ia, TRUE) = TRUE
                  AND COALESCE(cadastro_teste, FALSE) = FALSE
                  AND COALESCE(contato_interno, FALSE) = FALSE
                  AND COALESCE(status,'ativo')
                      NOT IN ('arquivado','excluido')
            """)
            r = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT COUNT(*)::INTEGER total,
                       COUNT(*) FILTER (
                           WHERE avaliacao_resultado IS NOT NULL
                       )::INTEGER avaliadas,
                       COUNT(*) FILTER (
                           WHERE COALESCE(TRIM(aprendizado_resultado),'') <> ''
                       )::INTEGER com_aprendizado
                FROM memoria_decisoes_ia
            """)
            m = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT COUNT(*)::INTEGER total
                FROM acoes_empresariais
                WHERE status = 'aguardando_aprovacao'
            """)
            a = dict(cur.fetchone() or {})
    finally:
        conn.close()

    total_rel = int(r.get("total") or 0)
    com_acao = int(r.get("com_acao") or 0)
    return {
        "success": True,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "interacoes": {
            "total": int(i.get("total") or 0),
            "sem_vinculo": int(i.get("sem_vinculo") or 0),
        },
        "relacionamentos": {
            "total_validos": total_rel,
            "com_proxima_acao": com_acao,
            "cobertura_proxima_acao_pct": (
                round(com_acao / total_rel * 100, 1) if total_rel else 0.0
            ),
        },
        "aprendizado": {
            "memorias": int(m.get("total") or 0),
            "avaliadas": int(m.get("avaliadas") or 0),
            "com_aprendizado": int(m.get("com_aprendizado") or 0),
        },
        "acoes_aguardando_aprovacao": int(a.get("total") or 0),
    }


def executar_ciclo_fase5(limite=500):
    saida = {"success": True}
    for nome, func in (
        ("reconciliacao", reconciliar_interacoes_passivas_fase5),
        ("proximas_acoes", preencher_proximas_acoes_fase5),
    ):
        try:
            saida[nome] = func(limite)
        except Exception as erro:
            saida["success"] = False
            saida[nome] = {"success": False, "error": str(erro)}
    return saida


def instalar_fase5(namespace):
    """Instala wrappers conservadores sobre a arquitetura existente."""
    try:
        print("✓ FASE 5 — CICLO INICIAL:", executar_ciclo_fase5())
    except Exception as erro:
        print("ERRO FASE 5 — CICLO INICIAL:", repr(erro))

    # Memória antiga passa a carregar padrões agregados.
    original = namespace.get("carregar_memoria_decisoes_ia")
    if callable(original) and not getattr(original, "_fase5", False):
        def memoria(*args, _original=original, **kwargs):
            base = _original(*args, **kwargs)
            try:
                area = kwargs.get("area")
                if area is None and args:
                    area = args[0]
                extra = obter_contexto_aprendizado_fase5(area)
                if isinstance(base, dict):
                    base = dict(base)
                    base["contexto"] = (
                        str(base.get("contexto") or "")
                        + str(extra.get("contexto") or "")
                    )
                    base["padroes_fase5"] = extra["padroes"]
            except Exception as erro:
                print("FASE 5 — MEMÓRIA:", repr(erro))
            return base
        memoria._fase5 = True
        namespace["carregar_memoria_decisoes_ia"] = memoria

    # Toda entrada passiva fecha o ciclo interno.
    original = namespace.get("processar_interacao_omnichannel_crm")
    if callable(original) and not getattr(original, "_fase5", False):
        def processar(*args, _original=original, **kwargs):
            resultado = _original(*args, **kwargs)
            try:
                executar_ciclo_fase5(100)
            except Exception as erro:
                print("FASE 5 — PASSIVO/ATIVO:", repr(erro))
            return resultado
        processar._fase5 = True
        namespace["processar_interacao_omnichannel_crm"] = processar

    # Painel Hoje recebe fila ativa + aprendizado sem quebrar chaves antigas.
    original = namespace.get("gerar_painel_executivo_hoje")
    if callable(original) and not getattr(original, "_fase5", False):
        def painel(*args, _original=original, **kwargs):
            base = _original(*args, **kwargs)
            if not isinstance(base, dict):
                return base
            base = dict(base)
            try:
                status = obter_status_fase5()
                fila = listar_fila_ativa_fase5(20)
                padroes = obter_padroes_aprendidos_fase5(limite=8)
                base["fase5"] = {
                    "status": status,
                    "fila_ativa": fila,
                    "padroes_aprendidos": padroes,
                }
                resumo = dict(base.get("resumo") or {})
                resumo["total_fila_ativa"] = len(fila)
                resumo["interacoes_sem_vinculo"] = (
                    status["interacoes"]["sem_vinculo"]
                )
                resumo["memorias_com_aprendizado"] = (
                    status["aprendizado"]["com_aprendizado"]
                )
                resumo["cobertura_proxima_acao_pct"] = (
                    status["relacionamentos"]["cobertura_proxima_acao_pct"]
                )
                base["resumo"] = resumo
            except Exception as erro:
                print("FASE 5 — PAINEL:", repr(erro))
            return base
        painel._fase5 = True
        namespace["gerar_painel_executivo_hoje"] = painel

    app = namespace.get("app")
    validar = (
        namespace.get("validar_admin_request")
        or namespace.get("validar_admin_omnichannel")
    )
    jsonify = namespace.get("jsonify")

    if app and callable(validar) and callable(jsonify):
        if "admin_ia_empresarial_fase5" not in app.view_functions:
            def status():
                if not validar():
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado.",
                    }), 401
                return jsonify({
                    "success": True,
                    "fase5": obter_status_fase5(),
                    "fila_ativa": listar_fila_ativa_fase5(20),
                    "padroes_aprendidos": obter_padroes_aprendidos_fase5(
                        limite=12
                    ),
                }), 200

            app.add_url_rule(
                "/api/admin/ia-empresarial/fase5",
                endpoint="admin_ia_empresarial_fase5",
                view_func=status,
                methods=["GET"],
            )

        if "admin_ia_empresarial_fase5_sincronizar" not in app.view_functions:
            def sincronizar():
                if not validar():
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado.",
                    }), 401
                resultado = executar_ciclo_fase5()
                return jsonify(resultado), (
                    200 if resultado.get("success") else 207
                )

            app.add_url_rule(
                "/api/admin/ia-empresarial/fase5/sincronizar",
                endpoint="admin_ia_empresarial_fase5_sincronizar",
                view_func=sincronizar,
                methods=["POST"],
            )

    try:
        instalar51 = globals().get("instalar_fase51")
        if callable(instalar51):
            instalar51(namespace)
    except Exception as erro:
        print("FASE 5.1 — INTEGRAÇÃO PRINCIPAL:", repr(erro))

    return {"success": True, "fase": 5, "acao_externa_automatica": False}

# ===== FASE 5.1 — PROSPECCAO ATIVA =====

def obter_radar_prospeccao_fase51(limite=20):
    """Radar interno: prioriza onde a IA deve pesquisar mais, sem contatar ninguém."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COALESCE(NULLIF(TRIM(categoria_contato),''),'nao_classificado') categoria,
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (
                        WHERE COALESCE(TRIM(proxima_acao),'') <> ''
                    )::INTEGER com_acao,
                    COUNT(*) FILTER (
                        WHERE ultima_interacao_em >= NOW() - INTERVAL '30 days'
                    )::INTEGER ativos_30d
                FROM leads_crm
                WHERE COALESCE(valido_para_ia, TRUE)=TRUE
                  AND COALESCE(cadastro_teste,FALSE)=FALSE
                  AND COALESCE(contato_interno,FALSE)=FALSE
                  AND COALESCE(arquivado,FALSE)=FALSE
                GROUP BY 1
                ORDER BY COUNT(*) ASC, 1
            """)
            carteira = [dict(x) for x in cur.fetchall()]

            cur.execute("""
                SELECT
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (
                        WHERE COALESCE(status,'') IN (
                            'novo','pendente','qualificado','aprovado'
                        )
                    )::INTEGER abertos
                FROM prospectos_rede
            """)
            prospectos = dict(cur.fetchone() or {})
    finally:
        conn.close()

    alvos = {
        "bar": 8, "restaurante": 8, "hotel": 5,
        "bartender": 8, "distribuidor": 4, "revendedor": 4,
    }
    atuais = {x["categoria"]: int(x["total"] or 0) for x in carteira}
    radar = []
    for categoria, alvo in alvos.items():
        atual = atuais.get(categoria, 0)
        lacuna = max(alvo - atual, 0)
        if lacuna:
            radar.append({
                "categoria": categoria,
                "atual": atual,
                "alvo_operacional_sugerido": alvo,
                "lacuna": lacuna,
                "prioridade_prospeccao": (
                    "alta" if atual == 0 or lacuna >= 5 else "media"
                ),
                "acao_ia": (
                    "pesquisar fontes profissionais públicas, qualificar e "
                    "registrar candidatos sem enviar contato externo"
                ),
            })
    radar.sort(key=lambda x: (-x["lacuna"], x["categoria"]))
    return {
        "carteira": carteira,
        "prospectos": {
            "total": int(prospectos.get("total") or 0),
            "abertos": int(prospectos.get("abertos") or 0),
        },
        "radar": radar[:max(1, min(int(limite or 20), 50))],
    }


def listar_oportunidades_prospeccao_fase51(limite=12):
    """Exibe prospectos existentes de maior qualidade; não cria nem envia mensagens."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM prospectos_rede
                ORDER BY
                    CASE COALESCE(status,'')
                        WHEN 'aprovado' THEN 0
                        WHEN 'qualificado' THEN 1
                        WHEN 'novo' THEN 2
                        WHEN 'pendente' THEN 3
                        ELSE 4
                    END,
                    criado_em DESC
                LIMIT %s
            """, (max(1, min(int(limite or 12), 50)),))
            dados = [dict(x) for x in cur.fetchall()]
    finally:
        conn.close()

    for x in dados:
        for k, v in list(x.items()):
            if hasattr(v, "isoformat"):
                x[k] = v.isoformat()
            elif k == "id" and v is not None:
                x[k] = str(v)
    return dados


def obter_aprendizado_acelerado_fase51(limite=12):
    """
    Aprende cedo sem fingir certeza:
    - resultado real pesa mais;
    - rejeição humana corrige imediatamente;
    - pouca amostra gera confiança baixa;
    - nunca autoriza ação externa.
    """
    padroes = obter_padroes_aprendidos_fase5(limite=limite)
    for p in padroes:
        total = int(p.get("total_decisoes") or 0)
        avaliados = int(p.get("resultados_avaliados") or 0)
        recusas = int(p.get("recusas") or 0)
        positivos = int(p.get("positivos") or 0)
        negativos = int(p.get("negativos") or 0)

        bruto = (
            1.20 * positivos
            - 1.35 * negativos
            - 0.70 * recusas
            + 0.20 * int(p.get("aprovacoes") or 0)
        )
        evidencia = total + (2 * avaliados)
        fator = min(evidencia / 10.0, 1.0)
        p["score_adaptativo"] = round(
            max(-1.0, min(1.0, (bruto / max(evidencia, 1)) * fator)),
            3,
        )
        p["evidencias_ponderadas"] = evidencia
        p["usar_para"] = (
            "ajustar prioridade e recomendação"
            if evidencia >= 2
            else "observar; evidência ainda muito pequena"
        )
        p["autoriza_execucao_externa"] = False
    return padroes


def obter_trabalho_autonomo_fase51():
    """Mede trabalho interno resolvido/preparado pela IA."""
    conn = _conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE COALESCE(valido_para_ia,TRUE)=TRUE
                          AND COALESCE(cadastro_teste,FALSE)=FALSE
                          AND COALESCE(contato_interno,FALSE)=FALSE
                          AND COALESCE(TRIM(proxima_acao),'') <> ''
                    )::INTEGER relacionamentos_preparados,
                    COUNT(*) FILTER (
                        WHERE COALESCE(valido_para_ia,TRUE)=TRUE
                          AND COALESCE(cadastro_teste,FALSE)=FALSE
                          AND COALESCE(contato_interno,FALSE)=FALSE
                          AND proximo_followup <= NOW()
                    )::INTEGER followups_vencidos
                FROM leads_crm
            """)
            rel = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (
                        WHERE status='aguardando_aprovacao'
                    )::INTEGER precisa_direcao
                FROM acoes_empresariais
            """)
            acoes = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (
                        WHERE lead_id IS NOT NULL
                    )::INTEGER vinculadas
                FROM interacoes_omnichannel
            """)
            inter = dict(cur.fetchone() or {})
    finally:
        conn.close()

    return {
        "relacionamentos_preparados": int(
            rel.get("relacionamentos_preparados") or 0
        ),
        "followups_vencidos": int(rel.get("followups_vencidos") or 0),
        "acoes_total": int(acoes.get("total") or 0),
        "precisa_direcao": int(acoes.get("precisa_direcao") or 0),
        "interacoes_vinculadas": int(inter.get("vinculadas") or 0),
        "interacoes_total": int(inter.get("total") or 0),
    }


def montar_painel_operacional_fase51():
    return {
        "success": True,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "precisa_de_mim": {
            "acoes_aguardando_aprovacao":
                obter_status_fase5()["acoes_aguardando_aprovacao"],
        },
        "ia_trabalhando": obter_trabalho_autonomo_fase51(),
        "prospeccao": obter_radar_prospeccao_fase51(),
        "oportunidades": listar_oportunidades_prospeccao_fase51(),
        "followups": listar_fila_ativa_fase5(20),
        "aprendizado": obter_aprendizado_acelerado_fase51(),
        "seguranca": {
            "pesquisa_publica_automatica": True,
            "qualificacao_automatica": True,
            "envio_externo_automatico": False,
            "publicacao_automatica": False,
            "preco_pagamento_contrato_automatico": False,
        },
    }


def instalar_fase51(namespace):
    app = namespace.get("app")
    validar = (
        namespace.get("validar_admin_request")
        or namespace.get("validar_admin_omnichannel")
    )
    jsonify = namespace.get("jsonify")

    original_ciclo = namespace.get("executar_ciclo_fase5")
    planejar = (
        namespace.get("planejar_expansao_rede")
        or namespace.get("planejar_pesquisas_rede")
        or namespace.get("planejar_pesquisa_rede")
    )
    executar_pesquisa = namespace.get("executar_proxima_pesquisa_rede")

    if callable(original_ciclo) and not getattr(original_ciclo, "_fase51", False):
        def ciclo_ativo(*args, **kwargs):
            resultado = original_ciclo(*args, **kwargs)
            ativo = {"planejamento": None, "pesquisa": None}
            try:
                if callable(planejar):
                    ativo["planejamento"] = planejar()
            except Exception as erro:
                ativo["planejamento"] = {"success": False, "error": str(erro)}
            try:
                if callable(executar_pesquisa):
                    ativo["pesquisa"] = executar_pesquisa()
            except Exception as erro:
                ativo["pesquisa"] = {"success": False, "error": str(erro)}
            if isinstance(resultado, dict):
                resultado = dict(resultado)
                resultado["prospeccao_ativa"] = ativo
            return resultado
        ciclo_ativo._fase51 = True
        namespace["executar_ciclo_fase5"] = ciclo_ativo

    original_painel = namespace.get("gerar_painel_executivo_hoje")
    if callable(original_painel) and not getattr(original_painel, "_fase51", False):
        def painel51(*args, **kwargs):
            base = original_painel(*args, **kwargs)
            if not isinstance(base, dict):
                return base
            base = dict(base)
            try:
                base["fase51"] = montar_painel_operacional_fase51()
            except Exception as erro:
                base["fase51"] = {
                    "success": False,
                    "error": str(erro),
                }
            return base
        painel51._fase51 = True
        namespace["gerar_painel_executivo_hoje"] = painel51

    if app and callable(validar) and callable(jsonify):
        endpoint = "admin_ia_empresarial_fase51"
        if endpoint not in app.view_functions:
            def status51():
                if not validar():
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado.",
                    }), 401
                return jsonify(montar_painel_operacional_fase51()), 200

            app.add_url_rule(
                "/api/admin/ia-empresarial/fase51",
                endpoint=endpoint,
                view_func=status51,
                methods=["GET"],
            )

    return {
        "success": True,
        "fase": "5.1",
        "prospeccao_interna_ativa": True,
        "acao_externa_automatica": False,
    }

# ===== FIM FASE 5.1 =====


try:
    instalar_fase51(globals())
except Exception as erro_fase51:
    print("ERRO AO INSTALAR FASE 5.1:", repr(erro_fase51))
