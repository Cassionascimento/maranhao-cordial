
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from psycopg2.extras import RealDictCursor

FASE = "5.8A"
TZ = ZoneInfo("America/Sao_Paulo")

MAX_CICLOS_DIA = int(os.getenv("FASE58A_MAX_CICLOS_DIA", "2"))
MAX_CONTATOS_DIA = int(os.getenv("FASE58A_MAX_CONTATOS_DIA", "2"))
LIMITE_PESQUISA_CICLO = int(os.getenv("FASE58A_PESQUISA_CICLO", "5"))
LIMITE_CONTATOS_CICLO = int(os.getenv("FASE58A_CONTATOS_CICLO", "1"))
HORA_INICIO = int(os.getenv("FASE58A_HORA_INICIO", "9"))
HORA_FIM = int(os.getenv("FASE58A_HORA_FIM", "17"))

OBJETIVO_FABRICAS = (
    "Identificar fábricas, copackers e engarrafadores brasileiros capazes "
    "de avaliar produção piloto e escala de bebida ou xarope não alcoólico "
    "premium, com envase em vidro e capacidade compatível com especificação "
    "técnica. Priorizar empresas com presença profissional pública e canal "
    "institucional verificável."
)

CONTEXTO_FABRICAS = (
    "Pesquisa técnica e comercial inicial da Maranhão Cordial. "
    "Não revelar fórmula, preço interno, margem ou teto de orçamento. "
    "Não autorizar produção, pagamento, exclusividade ou contrato."
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


def instalar_schema_fase58(namespace):
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
                SELECT
                    COUNT(*) FILTER (
                        WHERE status IN ('iniciado','concluido')
                    )::INTEGER AS ciclos,
                    COALESCE(SUM(contatos_qtd),0)::INTEGER AS contatos
                FROM execucoes_fase58
                WHERE fase=%s
                  AND (iniciado_em AT TIME ZONE 'America/Sao_Paulo')::date=%s
            """, (FASE, agora.date()))

            row = cur.fetchone() or {}

            return {
                "ciclos": int(row.get("ciclos") or 0),
                "contatos": int(row.get("contatos") or 0),
            }
    finally:
        conn.close()


def _claim(namespace, agora):
    periodo = "manha" if agora.hour < 12 else "tarde"
    slot = f"{agora.date().isoformat()}:{periodo}"

    conn = _conn(namespace)

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO execucoes_fase58 (
                        fase,
                        slot_key,
                        publico
                    )
                    VALUES (%s,%s,'fabrica')
                    ON CONFLICT (fase,slot_key) DO NOTHING
                    RETURNING id
                """, (FASE, slot))

                row = cur.fetchone()

                if not row:
                    return None

                return str(row["id"])
    finally:
        conn.close()


def _finalizar(namespace, execucao_id, status, pesquisa=0, contatos=0, erro=None):
    conn = _conn(namespace)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE execucoes_fase58
                    SET
                        status=%s,
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
                    execucao_id
                ))
    finally:
        conn.close()


def _campanha(namespace):
    from fase57_prospeccao_universal import criar_campanha_fase57

    conn = _conn(namespace)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM campanhas_prospeccao_fase57
                WHERE publico='fabrica'
                  AND status IN (
                    'ativa',
                    'pesquisando',
                    'contatando',
                    'negociando'
                  )
                ORDER BY criado_em DESC
                LIMIT 1
            """)

            row = cur.fetchone()

            if row:
                resultado = dict(row)
                resultado["id"] = str(resultado["id"])
                return resultado
    finally:
        conn.close()

    resultado = criar_campanha_fase57(
        namespace,
        objetivo=OBJETIVO_FABRICAS,
        publico="fabrica",
        regiao="Brasil",
        meta_contatos=20,
        contexto=CONTEXTO_FABRICAS,
        regras_adicionais=(
            "Usar somente fontes públicas e profissionais. "
            "Priorizar site oficial e contato institucional. "
            "Não inventar capacidade técnica ou contato."
        ),
        origem="fase58a",
        prioridade="alta"
    )

    return resultado["campanha"]


def _pesquisa(namespace, campanha_id):
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


def executar_fase58a(namespace):
    from fase57_prospeccao_universal import (
        executar_pesquisa_publica_fase57,
        executar_lote_contatos_fase57,
        garantir_pesquisa_se_faltar_fase57
    )

    agora = _agora_sp()

    permitido, motivo = _janela_segura(agora)

    if not permitido:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": motivo
        }

    resumo = _resumo_dia(namespace, agora)

    if resumo["ciclos"] >= MAX_CICLOS_DIA:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": "limite_ciclos_dia"
        }

    execucao_id = _claim(namespace, agora)

    if not execucao_id:
        return {
            "success": True,
            "executado": False,
            "fase": FASE,
            "motivo": "slot_ja_executado"
        }

    qtd_pesquisa = 0
    qtd_contatos = 0

    try:
        campanha = _campanha(namespace)
        campanha_id = campanha["id"]

        pesquisa_id = _pesquisa(
            namespace,
            campanha_id
        )

        if not pesquisa_id:
            garantir_pesquisa_se_faltar_fase57(
                namespace,
                campanha_id
            )

            pesquisa_id = _pesquisa(
                namespace,
                campanha_id
            )

        if pesquisa_id:
            resultado = executar_pesquisa_publica_fase57(
                namespace,
                pesquisa_id=pesquisa_id,
                limite=LIMITE_PESQUISA_CICLO
            )

            if isinstance(resultado, dict):
                qtd_pesquisa = int(
                    resultado.get("novos")
                    or resultado.get("quantidade")
                    or resultado.get("encontrados")
                    or 0
                )

        resumo = _resumo_dia(
            namespace,
            agora
        )

        if resumo["contatos"] < MAX_CONTATOS_DIA:
            resultado = executar_lote_contatos_fase57(
                namespace,
                campanha_id=campanha_id,
                limite=LIMITE_CONTATOS_CICLO
            )

            if isinstance(resultado, dict):
                qtd_contatos = int(
                    resultado.get("enviados")
                    or resultado.get("quantidade")
                    or resultado.get("contatos_enviados")
                    or 0
                )

        _finalizar(
            namespace,
            execucao_id,
            "concluido",
            qtd_pesquisa,
            qtd_contatos
        )

        return {
            "success": True,
            "executado": True,
            "fase": FASE,
            "publico": "fabrica",
            "pesquisa_qtd": qtd_pesquisa,
            "contatos_qtd": qtd_contatos
        }

    except Exception as erro:
        _finalizar(
            namespace,
            execucao_id,
            "erro",
            qtd_pesquisa,
            qtd_contatos,
            repr(erro)[:2000]
        )

        raise


def instalar_fase58(namespace):
    instalar_schema_fase58(namespace)

    app = namespace.get("app")
    validar_admin = namespace.get("validar_admin_request")

    if app is not None:

        if "fase58a_cron_executar" not in app.view_functions:

            @app.route(
                "/api/internal/fase58a/executar",
                methods=["POST"]
            )
            def fase58a_cron_executar():
                from flask import request, jsonify

                segredo_esperado = os.getenv(
                    "FASE58_CRON_SECRET"
                )

                segredo_recebido = request.headers.get(
                    "X-Fase58-Key"
                )

                if (
                    not segredo_esperado
                    or segredo_recebido != segredo_esperado
                ):
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado."
                    }), 401

                try:
                    resultado = executar_fase58a(
                        namespace
                    )

                    # A Fase 5.8B usa o mesmo relógio já pago da 5.8A.
                    # Falha da 5.8B não derruba Gmail nem 5.8A.
                    try:
                        from fase58b_motor_geral import executar_fase58b

                        resultado_58b = executar_fase58b(
                            namespace
                        )
                    except Exception as erro_58b:
                        resultado_58b = {
                            "success": False,
                            "fase": "5.8B",
                            "executado": False,
                            "error": repr(erro_58b)[:1000]
                        }

                    if isinstance(resultado, dict):
                        resultado = dict(resultado)
                        resultado["fase58b"] = resultado_58b

                    return jsonify(
                        resultado
                    ), 200

                except Exception as erro:
                    return jsonify({
                        "success": False,
                        "fase": FASE,
                        "error": repr(erro)
                    }), 500

    if app is not None and callable(validar_admin):
        if "admin_fase58a_status" not in app.view_functions:

            @app.route(
                "/api/admin/ia-empresarial/fase58a",
                methods=["GET"]
            )
            def admin_fase58a_status():
                from flask import jsonify

                if not validar_admin():
                    return jsonify({
                        "success": False,
                        "error": "Não autorizado."
                    }), 401

                agora = _agora_sp()

                return jsonify({
                    "success": True,
                    "fase": FASE,
                    "motor_busca_internet": True,
                    "publico": "fabrica",
                    "independente_painel": True,
                    "dias": "segunda a sexta",
                    "horario_sp": f"{HORA_INICIO}:00-{HORA_FIM}:00",
                    "max_ciclos_dia": MAX_CICLOS_DIA,
                    "max_contatos_dia": MAX_CONTATOS_DIA,
                    "pesquisa_por_ciclo": LIMITE_PESQUISA_CICLO,
                    "contatos_por_ciclo": LIMITE_CONTATOS_CICLO,
                    "resumo_hoje": _resumo_dia(
                        namespace,
                        agora
                    )
                }), 200

    return {
        "success": True,
        "fase": FASE,
        "motor_busca_internet": True,
        "publico": "fabrica",
        "controle_horario": True,
        "controle_volume": True,
        "deduplicacao_execucao": True,
        "fontes_publicas": True,
        "compromisso_estrategico_automatico": False
    }
