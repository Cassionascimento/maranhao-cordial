"""
Fases 5.3, 5.4 e 5.5 — IA Empresarial Maranhão Cordial.

5.3: prospecção autônoma controlada.
5.4: triagem de decisões para reduzir dependência da direção.
5.5: governança de autonomia e dependência do fundador.
"""

from datetime import datetime, timezone
import inspect
from psycopg2.extras import RealDictCursor


def _jsonavel(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v) if v is not None else None


def classificar_relevancia_decisao_fase54(acao):
    texto = " ".join([
        str(acao.get("tipo") or ""),
        str(acao.get("tipo_execucao") or ""),
        str(acao.get("canal") or ""),
        str(acao.get("conteudo") or ""),
        str(acao.get("justificativa") or ""),
    ]).lower()

    criticos = (
        "contrato", "pagamento", "pix", "transfer", "preço", "preco",
        "desconto", "invest", "sócio", "socio", "juríd", "jurid",
        "regulat", "anvisa", "mapa", "inpi", "fiscal", "tribut",
        "excluir", "apagar", "delet", "crise", "imprensa", "reput",
        "fornecedor", "fábrica", "fabrica", "produção", "producao",
    )
    externos = (
        "mensagem", "email", "e-mail", "whatsapp", "instagram",
        "linkedin", "pinterest", "youtube", "publicar", "publicacao",
        "publicação", "enviar", "contatar", "responder",
    )
    internos = (
        "pesquisa", "classificar", "qualificar", "reconciliar",
        "organizar", "priorizar", "followup", "follow-up",
        "atualizar crm", "enriquecer", "deduplic", "analisar",
    )

    if any(x in texto for x in criticos):
        return {"nivel":"estrategica","requer_direcao":True,
                "motivo":"Impacto financeiro, jurídico, regulatório, reputacional ou operacional relevante."}
    if any(x in texto for x in externos):
        return {"nivel":"externa","requer_direcao":True,
                "motivo":"Cria compromisso ou comunicação externa em nome da empresa."}
    if any(x in texto for x in internos):
        return {"nivel":"operacional","requer_direcao":False,
                "motivo":"Rotina interna reversível e de baixo risco."}
    return {"nivel":"revisao","requer_direcao":True,
            "motivo":"Ação ainda não classificada como rotina interna segura."}


def listar_decisoes_relevantes_fase54(conn_factory, limite=20):
    conn = conn_factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, tipo, tipo_execucao, canal, destinatario,
                       conteudo, justificativa, prioridade, status,
                       criado_em, atualizado_em
                FROM acoes_empresariais
                WHERE COALESCE(status,'aguardando_aprovacao')
                    IN ('aguardando_aprovacao','pendente','autorizada')
                ORDER BY
                    CASE prioridade
                        WHEN 'critica' THEN 0
                        WHEN 'alta' THEN 1
                        WHEN 'media' THEN 2
                        ELSE 3
                    END,
                    criado_em DESC
                LIMIT %s
            """, (max(20, min(int(limite or 20) * 4, 200)),))
            linhas = [dict(x) for x in cur.fetchall()]
    finally:
        conn.close()

    relevantes, operacionais = [], 0
    for acao in linhas:
        triagem = classificar_relevancia_decisao_fase54(acao)
        if triagem["requer_direcao"]:
            acao["triagem_fase54"] = triagem
            acao["id"] = str(acao["id"])
            for campo in ("criado_em","atualizado_em"):
                if acao.get(campo):
                    acao[campo] = _jsonavel(acao[campo])
            relevantes.append(acao)
        else:
            operacionais += 1

    return {
        "relevantes": relevantes[:max(1, min(int(limite or 20), 50))],
        "total_relevantes": len(relevantes),
        "operacionais_que_nao_precisam_da_direcao": operacionais,
    }


def executar_prospeccao_controlada_fase53(namespace):
    decisor = namespace.get("decidir_prospeccao_autonoma_fase52")
    executar = namespace.get("executar_proxima_pesquisa_rede")
    planejar = (
        namespace.get("planejar_expansao_rede")
        or namespace.get("planejar_pesquisas_rede")
        or namespace.get("planejar_pesquisa_rede")
    )

    if not callable(decisor):
        return {"success":False,"motivo":"motor_fase52_indisponivel"}

    decisao = decisor()
    saida = {
        "success":True,
        "decisao":decisao,
        "planejamento":None,
        "pesquisa":None,
        "acao_externa_automatica":False,
    }
    if not decisao.get("deve_prospectar"):
        return saida

    if callable(planejar):
        try:
            sig = inspect.signature(planejar)
            obrigatorios = [
                p for p in sig.parameters.values()
                if p.default is inspect._empty
                and p.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD
                )
            ]
            if not obrigatorios:
                saida["planejamento"] = planejar()
            else:
                saida["planejamento"] = {
                    "success":False,
                    "motivo":"planejador_exige_parametros",
                    "categoria_prioritaria":decisao.get("categoria_prioritaria"),
                }
        except Exception as erro:
            saida["planejamento"] = {"success":False,"error":repr(erro)}

    if callable(executar):
        try:
            saida["pesquisa"] = executar()
        except Exception as erro:
            saida["success"] = False
            saida["pesquisa"] = {"success":False,"error":repr(erro)}

    return saida


def medir_dependencia_fundador_fase55(conn_factory):
    conn = conn_factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*)::INTEGER total,
                       COUNT(*) FILTER (
                           WHERE COALESCE(status,'') IN
                               ('aguardando_aprovacao','pendente')
                       )::INTEGER aguardando
                FROM acoes_empresariais
                WHERE criado_em >= NOW() - INTERVAL '30 days'
            """)
            a = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT COUNT(*)::INTEGER total
                FROM leads_crm
                WHERE COALESCE(valido_para_ia,TRUE)=TRUE
                  AND COALESCE(cadastro_teste,FALSE)=FALSE
                  AND COALESCE(contato_interno,FALSE)=FALSE
                  AND COALESCE(arquivado,FALSE)=FALSE
                  AND COALESCE(TRIM(proxima_acao),'') <> ''
            """)
            r = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT COUNT(*)::INTEGER total
                FROM prospectos_rede
                WHERE COALESCE(valido_para_ia,TRUE)=TRUE
                  AND COALESCE(status,'') NOT IN ('rejeitado','descartado','arquivado')
            """)
            p = dict(cur.fetchone() or {})
    finally:
        conn.close()

    total = int(a.get("total") or 0)
    aguardando = int(a.get("aguardando") or 0)
    indice = round((aguardando / max(total, 1)) * 100, 1)

    return {
        "indice_dependencia_direcao_pct": indice,
        "acoes_30d": total,
        "aguardando_direcao": aguardando,
        "relacionamentos_com_proxima_acao": int(r.get("total") or 0),
        "prospectos_ativos": int(p.get("total") or 0),
        "leitura": (
            "baixa_dependencia" if indice <= 20
            else "dependencia_moderada" if indice <= 45
            else "alta_dependencia"
        ),
        "objetivo":"reduzir dependência operacional da direção sem liberar riscos externos",
    }


def montar_painel_fase55(namespace):
    conn_factory = namespace.get("get_db_connection")
    if not callable(conn_factory):
        raise RuntimeError("get_db_connection indisponível.")
    triagem = listar_decisoes_relevantes_fase54(conn_factory, limite=12)
    autonomia = medir_dependencia_fundador_fase55(conn_factory)
    return {
        "success":True,
        "fase":"5.5",
        "precisa_de_mim":triagem,
        "autonomia":autonomia,
        "politica":{
            "automatico":[
                "reconciliação por identidade forte",
                "organização e priorização interna",
                "follow-up interno",
                "qualificação de prospectos",
                "pesquisa pública profissional controlada",
            ],
            "sempre_sobe_para_direcao":[
                "mensagem ou publicação externa",
                "preço, desconto ou pagamento",
                "contrato ou compromisso jurídico",
                "decisão regulatória/fiscal",
                "fornecedor/fábrica/produção relevante",
                "investidor, sociedade ou reputação",
            ],
        },
    }


def instalar_fases_5355(namespace):
    app = namespace.get("app")
    validar_admin = namespace.get("validar_admin_request")
    conn_factory = namespace.get("get_db_connection")

    ciclo = namespace.get("executar_ciclo_fase5")
    if callable(ciclo) and not getattr(ciclo, "_fase53", False):
        def ciclo53(*args, _original=ciclo, **kwargs):
            base = _original(*args, **kwargs)
            try:
                ativo = executar_prospeccao_controlada_fase53(namespace)
            except Exception as erro:
                ativo = {"success":False,"error":repr(erro)}
            if isinstance(base, dict):
                base = dict(base)
                base["fase53_prospeccao"] = ativo
            return base
        ciclo53._fase53 = True
        namespace["executar_ciclo_fase5"] = ciclo53

    if app is not None and callable(validar_admin) and callable(conn_factory):
        if "admin_fase55_governanca" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase55", methods=["GET"])
            def admin_fase55_governanca():
                if not validar_admin():
                    return {"success":False,"error":"Não autorizado."}, 401
                try:
                    return montar_painel_fase55(namespace), 200
                except Exception as erro:
                    return {"success":False,"error":"Erro ao montar governança de autonomia.","detail":str(erro)}, 500

        if "admin_fase53_executar" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase53/executar", methods=["POST"])
            def admin_fase53_executar():
                if not validar_admin():
                    return {"success":False,"error":"Não autorizado."}, 401
                try:
                    return executar_prospeccao_controlada_fase53(namespace), 200
                except Exception as erro:
                    return {"success":False,"error":"Erro no ciclo autônomo de prospecção.","detail":str(erro)}, 500

    return {
        "success":True,
        "fases":["5.3","5.4","5.5"],
        "acao_externa_automatica":False,
    }
