# FASE 5.8B — Motor Autônomo Geral de Busca e Prospecção da Maranhão Cordial

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from psycopg2.extras import RealDictCursor

FASE = "5.8B"
TZ = ZoneInfo("America/Sao_Paulo")

MAX_CICLOS_DIA = int(os.getenv("FASE58B_MAX_CICLOS_DIA", "3"))
MAX_CONTATOS_DIA = int(os.getenv("FASE58B_MAX_CONTATOS_DIA", "6"))
LIMITE_PESQUISA_CICLO = int(os.getenv("FASE58B_PESQUISA_CICLO", "8"))
LIMITE_CONTATOS_CICLO = int(os.getenv("FASE58B_CONTATOS_CICLO", "2"))
HORA_INICIO = int(os.getenv("FASE58B_HORA_INICIO", "9"))
HORA_FIM = int(os.getenv("FASE58B_HORA_FIM", "18"))

PUBLICOS = (
    "bar", "restaurante", "bartender", "hotel", "distribuidor",
    "revendedor", "imprensa", "jornalista", "influenciador",
    "criador", "fornecedor", "parceiro", "empresa",
)

OBJETIVOS = {
    "bar": "Identificar bares brasileiros com posicionamento premium, coquetelaria, hospitalidade ou carta autoral onde a Maranhão Cordial possa ser apresentada como solução contemporânea sem álcool para criação de bebidas.",
    "restaurante": "Identificar restaurantes brasileiros com proposta gastronômica e hospitalidade compatíveis com uma bebida premium sem álcool e experiências autorais.",
    "bartender": "Identificar bartenders e profissionais de coquetelaria com atuação pública relevante para conhecer, testar ou apresentar a Maranhão Cordial.",
    "hotel": "Identificar hotéis, pousadas e operações de hospitalidade premium que possam avaliar a Maranhão Cordial para bar, restaurante, minibar ou experiências.",
    "distribuidor": "Identificar distribuidores profissionais de bebidas, food service ou produtos premium com potencial de distribuição B2B da Maranhão Cordial.",
    "revendedor": "Identificar revendedores e lojas especializadas compatíveis com produtos premium de bebidas e hospitalidade.",
    "imprensa": "Identificar veículos, editorias e canais de imprensa ligados a bebidas, gastronomia, hospitalidade, negócios, cultura e inovação.",
    "jornalista": "Identificar jornalistas com atuação pública em bebidas, gastronomia, hospitalidade, negócios, cultura ou inovação para relacionamento institucional.",
    "influenciador": "Identificar influenciadores com atuação profissional pública e afinidade real com gastronomia, bebidas, hospitalidade, cultura ou lifestyle premium.",
    "criador": "Identificar criadores de conteúdo profissionais com afinidade real com gastronomia, bebidas, hospitalidade, cultura ou lifestyle premium.",
    "fornecedor": "Identificar fornecedores profissionais relevantes para embalagem, ingredientes, logística, ativação, materiais e demais necessidades operacionais da Maranhão Cordial.",
    "parceiro": "Identificar empresas e profissionais com potencial de parceria comercial, institucional, cultural ou de hospitalidade para a Maranhão Cordial.",
    "empresa": "Identificar empresas brasileiras com aderência comercial ou institucional ao universo da Maranhão Cordial e potencial de relacionamento B2B.",
}

CONTEXTO_GERAL = (
    "Prospecção institucional e comercial inicial da Maranhão Cordial. "
    "Usar somente informações públicas e profissionais. "
    "Não revelar fórmula, preço interno, margem, orçamento interno ou teto de negociação. "
    "Não autorizar compra, venda definitiva, produção, pagamento, exclusividade, contrato "
    "ou qualquer compromisso estratégico. O objetivo do primeiro contato é abrir uma "
    "conversa profissional e qualificada."
)

REGRAS_GERAIS = (
    "Priorizar site oficial, e-mail institucional, perfil profissional e evidência verificável. "
    "Não inventar e-mail, telefone, cargo, empresa, capacidade, audiência ou relacionamento. "
    "Evitar contatos pessoais privados. Respeitar recusas e não insistir em prospectos descartados."
)


def _conn(namespace):
    fn = namespace.get("get_db_connection")
    if callable(fn):
        return fn()

    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _agora_sp():
    return datetime.now(TZ)


def _janela_segura(agora):
    if agora.weekday() > 4:
        return False, "fim_de_semana"

    if agora.hour < HORA_INICIO or agora.hour >= HORA_FIM:
        return False, "fora_do_horario_seguro"

    return True, None


def instalar_schema_fase58b(namespace):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS execucoes_fase58 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        fase VARCHAR(20) NOT NULL,
                        slot_key VARCHAR(100) NOT NULL,
                        publico VARCHAR(50) NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'iniciado',
                        pesquisa_qtd INTEGER NOT NULL DEFAULT 0,
                        contatos_qtd INTEGER NOT NULL DEFAULT 0,
                        erro TEXT,
                        iniciado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        concluido_em TIMESTAMPTZ,
                        UNIQUE (fase, slot_key)
                    )
                """)
        return {"success": True}
    finally:
        conn.close()


def _resumo_dia(namespace, agora):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) FILTER (
                    WHERE status IN ('iniciado','concluido')
                )::INTEGER AS ciclos
                FROM execucoes_fase58
                WHERE fase=%s
                  AND (iniciado_em AT TIME ZONE 'America/Sao_Paulo')::date=%s
            """, (FASE, agora.date()))
            row = cur.fetchone() or {}
            ciclos = int(row.get("ciclos") or 0)

            cur.execute("""
                SELECT COUNT(*)::INTEGER AS contatos
                FROM prospectos_fase57 p
                JOIN campanhas_prospeccao_fase57 c
                  ON c.id=p.campanha_id
                WHERE c.origem='fase58b'
                  AND p.ultimo_contato_em IS NOT NULL
                  AND (
                    p.ultimo_contato_em AT TIME ZONE 'America/Sao_Paulo'
                  )::date=%s
            """, (agora.date(),))
            row = cur.fetchone() or {}
            contatos = int(row.get("contatos") or 0)

            return {"ciclos": ciclos, "contatos": contatos}
    finally:
        conn.close()


def _slot_key(agora):
    if agora.hour < 12:
        periodo = "manha"
    elif agora.hour < 15:
        periodo = "meio"
    else:
        periodo = "tarde"
    return f"{agora.date().isoformat()}:{periodo}"


def _publico_do_ciclo(agora, ciclos_hoje):
    base = agora.toordinal() * max(1, MAX_CICLOS_DIA)
    indice = (base + int(ciclos_hoje or 0)) % len(PUBLICOS)
    return PUBLICOS[indice]


def _claim(namespace, agora, publico):
    slot = _slot_key(agora)
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO execucoes_fase58 (
                        fase, slot_key, publico
                    )
                    VALUES (%s,%s,%s)
                    ON CONFLICT (fase,slot_key) DO NOTHING
                    RETURNING id
                """, (FASE, slot, publico))
                row = cur.fetchone()
                return str(row["id"]) if row else None
    finally:
        conn.close()


def _finalizar(namespace, execucao_id, status, pesquisa=0, contatos=0, erro=None):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE execucoes_fase58
                    SET status=%s,
                        pesquisa_qtd=%s,
                        contatos_qtd=%s,
                        erro=%s,
                        concluido_em=NOW()
                    WHERE id=%s
                """, (
                    status,
                    int(pesquisa or 0),
                    int(contatos or 0),
                    erro,
                    execucao_id,
                ))
    finally:
        conn.close()


def _campanha(namespace, publico):
    from fase57_prospeccao_universal import criar_campanha_fase57

    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM campanhas_prospeccao_fase57
                WHERE publico=%s
                  AND origem='fase58b'
                  AND status IN ('ativa','pesquisando','contatando','negociando')
                ORDER BY criado_em DESC
                LIMIT 1
            """, (publico,))
            row = cur.fetchone()
            if row:
                resultado = dict(row)
                resultado["id"] = str(resultado["id"])
                return resultado
    finally:
        conn.close()

    resultado = criar_campanha_fase57(
        namespace,
        objetivo=OBJETIVOS[publico],
        publico=publico,
        regiao="Brasil",
        meta_contatos=20,
        contexto=CONTEXTO_GERAL,
        regras_adicionais=REGRAS_GERAIS,
        origem="fase58b",
        prioridade="normal",
    )
    return resultado["campanha"]


def _pesquisa_pendente(namespace, campanha_id):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id
                FROM pesquisas_fase57
                WHERE campanha_id=%s
                  AND status='pendente'
                ORDER BY criado_em ASC
                LIMIT 1
            """, (campanha_id,))
            row = cur.fetchone()
            return str(row["id"]) if row else None
    finally:
        conn.close()


def _contar_prospectos(namespace, campanha_id):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*)::INTEGER AS qtd
                FROM prospectos_fase57
                WHERE campanha_id=%s
            """, (campanha_id,))
            row = cur.fetchone() or {}
            return int(row.get("qtd") or 0)
    finally:
        conn.close()


def _contatos_campanha_hoje(namespace, campanha_id, agora):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*)::INTEGER AS qtd
                FROM prospectos_fase57
                WHERE campanha_id=%s
                  AND ultimo_contato_em IS NOT NULL
                  AND (
                    ultimo_contato_em AT TIME ZONE 'America/Sao_Paulo'
                  )::date=%s
            """, (campanha_id, agora.date()))
            row = cur.fetchone() or {}
            return int(row.get("qtd") or 0)
    finally:
        conn.close()


def executar_fase58b(namespace):
    from fase57_prospeccao_universal import (
        executar_pesquisa_publica_fase57,
        executar_lote_contatos_fase57,
        garantir_pesquisa_se_faltar_fase57,
    )

    agora = _agora_sp()
    permitido, motivo = _janela_segura(agora)

    if not permitido:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": motivo,
        }

    resumo = _resumo_dia(namespace, agora)

    if resumo["ciclos"] >= MAX_CICLOS_DIA:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": "limite_ciclos_dia",
        }

    if resumo["contatos"] >= MAX_CONTATOS_DIA:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": "limite_contatos_dia",
        }

    publico = _publico_do_ciclo(agora, resumo["ciclos"])
    execucao_id = _claim(namespace, agora, publico)

    if not execucao_id:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": "slot_ja_executado",
        }

    qtd_pesquisa = 0
    qtd_contatos = 0

    try:
        campanha = _campanha(namespace, publico)
        campanha_id = campanha["id"]

        pesquisa_id = _pesquisa_pendente(namespace, campanha_id)

        if not pesquisa_id:
            garantir_pesquisa_se_faltar_fase57(namespace, campanha_id)
            pesquisa_id = _pesquisa_pendente(namespace, campanha_id)

        antes_pesquisa = _contar_prospectos(namespace, campanha_id)

        if pesquisa_id:
            executar_pesquisa_publica_fase57(
                namespace,
                pesquisa_id=pesquisa_id,
                limite=LIMITE_PESQUISA_CICLO,
            )

        depois_pesquisa = _contar_prospectos(namespace, campanha_id)
        qtd_pesquisa = max(0, depois_pesquisa - antes_pesquisa)

        resumo = _resumo_dia(namespace, agora)
        restante = max(0, MAX_CONTATOS_DIA - resumo["contatos"])

        if restante > 0:
            limite_contato = min(LIMITE_CONTATOS_CICLO, restante)
            antes_contatos = _contatos_campanha_hoje(namespace, campanha_id, agora)

            executar_lote_contatos_fase57(
                namespace,
                campanha_id=campanha_id,
                limite=limite_contato,
            )

            depois_contatos = _contatos_campanha_hoje(namespace, campanha_id, agora)
            qtd_contatos = max(0, depois_contatos - antes_contatos)

        _finalizar(
            namespace,
            execucao_id,
            "concluido",
            qtd_pesquisa,
            qtd_contatos,
        )

        return {
            "success": True,
            "executado": True,
            "fase": FASE,
            "publico": publico,
            "campanha_id": campanha_id,
            "pesquisa_qtd": qtd_pesquisa,
            "contatos_qtd": qtd_contatos,
            "limites": {
                "max_ciclos_dia": MAX_CICLOS_DIA,
                "max_contatos_dia": MAX_CONTATOS_DIA,
            },
        }

    except Exception as erro:
        _finalizar(
            namespace,
            execucao_id,
            "erro",
            qtd_pesquisa,
            qtd_contatos,
            repr(erro)[:2000],
        )
        raise


def instalar_fase58b(namespace):
    instalar_schema_fase58b(namespace)

    app = namespace.get("app")
    validar_admin = namespace.get("validar_admin_request")

    if app is not None and "fase58b_cron_executar" not in app.view_functions:
        @app.route("/api/internal/fase58b/executar", methods=["POST"])
        def fase58b_cron_executar():
            from flask import request, jsonify

            segredo_esperado = os.getenv("FASE58_CRON_SECRET")
            segredo_recebido = request.headers.get("X-Fase58-Key")

            if not segredo_esperado or segredo_recebido != segredo_esperado:
                return jsonify({
                    "success": False,
                    "error": "Não autorizado.",
                }), 401

            try:
                resultado = executar_fase58b(namespace)
                return jsonify(resultado), 200
            except Exception as erro:
                return jsonify({
                    "success": False,
                    "fase": FASE,
                    "error": repr(erro),
                }), 500

    if app is not None and callable(validar_admin):
        if "admin_fase58b_status" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase58b", methods=["GET"])
            def admin_fase58b_status():
                from flask import jsonify

                if not validar_admin():
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado.",
                    }), 401

                agora = _agora_sp()

                return jsonify({
                    "success": True,
                    "fase": FASE,
                    "motor_busca_internet": True,
                    "independente_painel": True,
                    "publicos": list(PUBLICOS),
                    "dias": "segunda a sexta",
                    "horario_sp": f"{HORA_INICIO}:00-{HORA_FIM}:00",
                    "max_ciclos_dia": MAX_CICLOS_DIA,
                    "max_contatos_dia": MAX_CONTATOS_DIA,
                    "pesquisa_por_ciclo": LIMITE_PESQUISA_CICLO,
                    "contatos_por_ciclo": LIMITE_CONTATOS_CICLO,
                    "resumo_hoje": _resumo_dia(namespace, agora),
                    "decisao_estrategica_automatica": False,
                    "fontes_publicas": True,
                }), 200

    return {
        "success": True,
        "fase": FASE,
        "motor_busca_internet": True,
        "independente_painel": True,
        "publicos": list(PUBLICOS),
        "controle_horario": True,
        "controle_volume": True,
        "deduplicacao_execucao": True,
        "fontes_publicas": True,
        "compromisso_estrategico_automatico": False,
    }
