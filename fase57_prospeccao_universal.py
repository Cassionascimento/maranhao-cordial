"""
FASE 5.7 — Motor Universal de Prospecção da Maranhão Cordial.

Princípios:
- falta de informação/contato gera pesquisa; não encerra objetivo;
- fontes públicas/profissionais e deduplicação;
- posicionamento premium e cultura maranhense positiva;
- nunca revelar preço, margem, orçamento/teto interno;
- negativas saem da fila operacional, mas permanecem como aprendizado;
- oportunidades promissoras sobem para a direção;
- contrato, pagamento, exclusividade e compromisso estratégico nunca são automáticos.
"""

import os
import re
import json
import unicodedata
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

FASE = "5.7"
STATUS_ATIVOS = ("ativa", "pesquisando", "contatando", "negociando")
PUBLICOS = (
    "bartender", "bar", "restaurante", "hotel", "distribuidor",
    "revendedor", "imprensa", "jornalista", "influenciador",
    "criador", "fornecedor", "fabrica", "empresa", "parceiro",
)
TERMOS_SIGILOSOS = (
    "preco interno", "preço interno", "margem interna", "margem nossa",
    "teto interno", "orcamento interno", "orçamento interno",
    "limite de pagamento", "custo maximo", "custo máximo",
)
TERMOS_COMPROMISSO = (
    "aceitamos a proposta", "aceitamos o valor", "fechado",
    "vamos pagar", "realizaremos o pagamento", "pode produzir",
    "autorizamos a produção", "assinaremos", "assinar contrato",
    "exclusividade", "garantimos a compra",
)


def _conn(namespace):
    fn = namespace.get("get_db_connection")
    if callable(fn):
        return fn()
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _slug(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:48] or "campanha"


def instalar_schema_fase57(namespace):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS campanhas_prospeccao_fase57 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        codigo VARCHAR(100) UNIQUE NOT NULL,
                        objetivo TEXT NOT NULL,
                        publico VARCHAR(50) NOT NULL,
                        regiao TEXT,
                        meta_contatos INTEGER NOT NULL DEFAULT 20,
                        contexto TEXT,
                        regras_adicionais TEXT,
                        origem VARCHAR(30) NOT NULL DEFAULT 'direcao',
                        status VARCHAR(30) NOT NULL DEFAULT 'ativa',
                        prioridade VARCHAR(20) NOT NULL DEFAULT 'normal',
                        permitir_primeiro_contato BOOLEAN NOT NULL DEFAULT TRUE,
                        permitir_followup BOOLEAN NOT NULL DEFAULT TRUE,
                        revelar_preco BOOLEAN NOT NULL DEFAULT FALSE,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prospectos_fase57 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        campanha_id UUID NOT NULL REFERENCES campanhas_prospeccao_fase57(id)
                            ON DELETE CASCADE,
                        nome TEXT,
                        empresa TEXT,
                        cargo TEXT,
                        cidade TEXT,
                        estado TEXT,
                        email TEXT,
                        telefone TEXT,
                        instagram TEXT,
                        linkedin TEXT,
                        site TEXT,
                        fonte_url TEXT,
                        evidencia TEXT,
                        score INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR(40) NOT NULL DEFAULT 'novo',
                        classificacao VARCHAR(40),
                        motivo TEXT,
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        ultimo_contato_em TIMESTAMPTZ,
                        ultima_resposta_em TIMESTAMPTZ,
                        proximo_followup_em TIMESTAMPTZ,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_fase57_campanha_email
                    ON prospectos_fase57(campanha_id, LOWER(email))
                    WHERE email IS NOT NULL AND email <> ''
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pesquisas_fase57 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        campanha_id UUID NOT NULL REFERENCES campanhas_prospeccao_fase57(id)
                            ON DELETE CASCADE,
                        consulta TEXT NOT NULL,
                        motivo TEXT,
                        status VARCHAR(30) NOT NULL DEFAULT 'pendente',
                        prioridade VARCHAR(20) NOT NULL DEFAULT 'normal',
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        iniciado_em TIMESTAMPTZ,
                        concluido_em TIMESTAMPTZ,
                        erro TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS aprendizado_prospeccao_fase57 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        campanha_id UUID REFERENCES campanhas_prospeccao_fase57(id)
                            ON DELETE SET NULL,
                        prospecto_id UUID REFERENCES prospectos_fase57(id)
                            ON DELETE SET NULL,
                        publico VARCHAR(50),
                        regiao TEXT,
                        canal VARCHAR(30),
                        resultado VARCHAR(40) NOT NULL,
                        motivo TEXT,
                        evidencia TEXT,
                        peso NUMERIC(6,3) NOT NULL DEFAULT 1,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
        return {"success": True}
    finally:
        conn.close()


def criar_campanha_fase57(
    namespace, objetivo, publico, regiao=None, meta_contatos=20,
    contexto=None, regras_adicionais=None, origem="direcao",
    prioridade="normal",
):
    publico = str(publico or "").strip().lower()
    if publico not in PUBLICOS:
        raise ValueError("Público de prospecção não suportado pela política da Fase 5.7.")
    objetivo = str(objetivo or "").strip()
    if len(objetivo) < 12:
        raise ValueError("Objetivo de prospecção muito curto.")
    meta = max(1, min(int(meta_contatos or 20), 100))
    codigo = f"{_slug(publico)}-{_slug(regiao or 'brasil')}-{int(datetime.now(timezone.utc).timestamp())}"

    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO campanhas_prospeccao_fase57 (
                        codigo, objetivo, publico, regiao, meta_contatos,
                        contexto, regras_adicionais, origem, prioridade
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING *
                """, (
                    codigo, objetivo, publico, regiao, meta, contexto,
                    regras_adicionais, origem, prioridade,
                ))
                campanha = dict(cur.fetchone())

                consulta = (
                    f"Encontrar {meta} contatos profissionais públicos de {publico}"
                    f"{' em ' + regiao if regiao else ' no Brasil'} relevantes para: {objetivo}. "
                    "Priorizar site oficial, e-mail profissional público, empresa/cargo e evidência verificável."
                )
                cur.execute("""
                    INSERT INTO pesquisas_fase57 (
                        campanha_id, consulta, motivo, prioridade
                    ) VALUES (%s,%s,%s,%s)
                """, (
                    campanha["id"], consulta,
                    "Pesquisa inicial automática: falta de contatos não pode bloquear o objetivo.",
                    prioridade,
                ))

        campanha["id"] = str(campanha["id"])
        for k, v in list(campanha.items()):
            if hasattr(v, "isoformat"):
                campanha[k] = v.isoformat()
        return {"success": True, "campanha": campanha}
    finally:
        conn.close()


def validar_mensagem_fase57(texto):
    t = str(texto or "").lower()
    if any(x in t for x in TERMOS_SIGILOSOS):
        raise RuntimeError("Mensagem bloqueada: expõe informação comercial interna.")
    if any(x in t for x in TERMOS_COMPROMISSO):
        raise RuntimeError("Mensagem bloqueada: cria compromisso reservado à direção.")
    return True


def contexto_institucional_fase57():
    return """
A Maranhão Cordial é uma marca brasileira premium que transforma referências do
Maranhão em experiências contemporâneas de hospitalidade e bebidas. A comunicação
deve valorizar positivamente a riqueza cultural maranhense, sua identidade,
hospitalidade, criatividade e conexão entre tradição e contemporaneidade.
Evite estereótipos, caricaturas, exotificação ou alegações culturais não verificadas.
Nunca revele preço, margem, orçamento, teto interno ou limite de negociação.
"""


def gerar_primeiro_contato_fase57(campanha, prospecto):
    from openai import OpenAI
    client = OpenAI()
    prompt = f"""
Você escreve um primeiro e-mail B2B curto em nome da Maranhão Cordial.

{contexto_institucional_fase57()}

Campanha:
Objetivo: {campanha.get('objetivo')}
Público: {campanha.get('publico')}
Região: {campanha.get('regiao') or 'Brasil'}
Contexto: {campanha.get('contexto') or ''}
Regras adicionais: {campanha.get('regras_adicionais') or ''}

Prospecto:
Nome: {prospecto.get('nome') or ''}
Empresa: {prospecto.get('empresa') or ''}
Cargo: {prospecto.get('cargo') or ''}

Regras:
- não invente informação;
- não fale preço;
- não prometa pagamento, contrato, exclusividade ou compra;
- explique em uma frase por que o contato faz sentido;
- faça uma pergunta objetiva que permita avançar;
- máximo de 180 palavras;
- devolva somente o corpo do e-mail, sem assinatura.
"""
    resp = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-mini"),
        input=prompt,
    )
    texto = (getattr(resp, "output_text", None) or "").strip()
    validar_mensagem_fase57(texto)
    return texto


def classificar_resposta_fase57(texto):
    t = str(texto or "").lower()
    negativos = (
        "não tenho interesse", "nao tenho interesse", "não temos interesse",
        "nao temos interesse", "não trabalhamos", "nao trabalhamos",
        "não atendemos", "nao atendemos", "remova meu contato",
        "não entre em contato", "nao entre em contato",
    )
    positivos = (
        "temos interesse", "tenho interesse", "podemos conversar",
        "podemos agendar", "envie mais informações", "mande mais informações",
        "gostaria de conhecer", "vamos conversar", "podemos avaliar",
        "podemos testar", "podemos receber", "podemos apresentar",
    )
    estrategicos = (
        "contrato", "exclusividade", "pagamento", "desconto",
        "sociedade", "investimento", "representação exclusiva",
        "representacao exclusiva",
    )
    if any(x in t for x in negativos):
        return {"resultado": "negativo", "descartar": True, "alertar": False}
    if any(x in t for x in estrategicos):
        return {"resultado": "estrategico", "descartar": False, "alertar": True}
    if any(x in t for x in positivos):
        return {"resultado": "promissor", "descartar": False, "alertar": True}
    return {"resultado": "intermediario", "descartar": False, "alertar": False}


def registrar_aprendizado_fase57(
    namespace, campanha_id, prospecto_id, publico, regiao,
    resultado, motivo=None, evidencia=None, canal="email", peso=1,
):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO aprendizado_prospeccao_fase57 (
                        campanha_id, prospecto_id, publico, regiao,
                        canal, resultado, motivo, evidencia, peso
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    campanha_id, prospecto_id, publico, regiao, canal,
                    resultado, motivo, evidencia, peso,
                ))
    finally:
        conn.close()


def garantir_pesquisa_se_faltar_fase57(namespace, campanha_id):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT c.*,
                           COUNT(p.id) FILTER (
                               WHERE p.status NOT IN ('descartado','bloqueado')
                           )::INTEGER AS contatos_uteis
                    FROM campanhas_prospeccao_fase57 c
                    LEFT JOIN prospectos_fase57 p ON p.campanha_id=c.id
                    WHERE c.id=%s
                    GROUP BY c.id
                """, (campanha_id,))
                c = cur.fetchone()
                if not c:
                    return {"success": False, "motivo": "campanha_nao_encontrada"}

                faltam = max(0, int(c["meta_contatos"]) - int(c["contatos_uteis"] or 0))
                if faltam <= 0:
                    return {"success": True, "pesquisa_criada": False, "faltam": 0}

                cur.execute("""
                    SELECT COUNT(*)::INTEGER qtd
                    FROM pesquisas_fase57
                    WHERE campanha_id=%s
                      AND status IN ('pendente','executando')
                """, (campanha_id,))
                if int((cur.fetchone() or {}).get("qtd") or 0) > 0:
                    return {"success": True, "pesquisa_criada": False, "faltam": faltam}

                consulta = (
                    f"Buscar mais {faltam} contatos públicos profissionais de "
                    f"{c['publico']}{' em ' + c['regiao'] if c['regiao'] else ''} "
                    f"para o objetivo: {c['objetivo']}. "
                    "Usar novas fontes e evitar contatos já cadastrados."
                )
                cur.execute("""
                    INSERT INTO pesquisas_fase57 (
                        campanha_id, consulta, motivo, prioridade
                    ) VALUES (%s,%s,%s,%s)
                """, (
                    campanha_id, consulta,
                    "Reposição automática: contatos/informações insuficientes.",
                    c["prioridade"],
                ))
                return {"success": True, "pesquisa_criada": True, "faltam": faltam}
    finally:
        conn.close()


def detectar_lacunas_fase57(namespace):
    """Detecta lacunas operacionais sem criar campanhas em excesso."""
    conn = _conn(namespace)
    sugestoes = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT categoria_contato, COUNT(*)::INTEGER qtd
                FROM leads_crm
                WHERE COALESCE(valido_para_ia,TRUE)=TRUE
                  AND COALESCE(cadastro_teste,FALSE)=FALSE
                  AND COALESCE(contato_interno,FALSE)=FALSE
                  AND COALESCE(arquivado,FALSE)=FALSE
                GROUP BY categoria_contato
            """)
            contagens = {str(r["categoria_contato"] or ""): int(r["qtd"]) for r in cur.fetchall()}

            metas = {
                "bartender": 8, "bar": 8, "restaurante": 8,
                "hotel": 5, "distribuidor": 4, "revendedor": 4,
            }
            for publico, meta in metas.items():
                atual = contagens.get(publico, 0)
                if atual < meta:
                    sugestoes.append({
                        "publico": publico,
                        "atual": atual,
                        "referencia_operacional": meta,
                        "lacuna": meta - atual,
                    })
        sugestoes.sort(key=lambda x: x["lacuna"], reverse=True)
        return sugestoes
    finally:
        conn.close()


def obter_status_fase57(namespace):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = ANY(%s))::INTEGER ativas,
                    COUNT(*)::INTEGER total
                FROM campanhas_prospeccao_fase57
            """, (list(STATUS_ATIVOS),))
            campanhas = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (WHERE status='promissor')::INTEGER promissores,
                    COUNT(*) FILTER (WHERE status='descartado')::INTEGER descartados,
                    COUNT(*) FILTER (WHERE status IN ('novo','qualificado'))::INTEGER fila
                FROM prospectos_fase57
            """)
            prospectos = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT resultado, COUNT(*)::INTEGER qtd
                FROM aprendizado_prospeccao_fase57
                GROUP BY resultado ORDER BY qtd DESC
            """)
            aprendizado = [dict(r) for r in cur.fetchall()]

        return {
            "success": True,
            "fase": FASE,
            "campanhas": campanhas,
            "prospectos": prospectos,
            "aprendizado": aprendizado,
            "lacunas_detectadas": detectar_lacunas_fase57(namespace)[:8],
            "politica": {
                "falta_de_informacao_gera_pesquisa": True,
                "preco_margem_teto_interno_expostos": False,
                "negativas_apagadas": False,
                "negativas_saem_da_fila": True,
                "positivas_sobem_para_direcao": True,
                "contrato_pagamento_exclusividade_automaticos": False,
            },
        }
    finally:
        conn.close()


def instalar_fase57(namespace):
    instalar_schema_fase57(namespace)
    app = namespace.get("app")
    validar_admin = namespace.get("validar_admin_request")

    if app is not None and callable(validar_admin):
        if "admin_fase57_status" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase57", methods=["GET"])
            def admin_fase57_status():
                if not validar_admin():
                    return {"success": False, "error": "Não autorizado."}, 401
                try:
                    return obter_status_fase57(namespace), 200
                except Exception as erro:
                    return {"success": False, "error": str(erro)}, 500

        if "admin_fase57_campanha" not in app.view_functions:
            from flask import request

            @app.route("/api/admin/ia-empresarial/fase57/campanhas", methods=["POST"])
            def admin_fase57_campanha():
                if not validar_admin():
                    return {"success": False, "error": "Não autorizado."}, 401
                dados = request.get_json(silent=True) or {}
                try:
                    return criar_campanha_fase57(
                        namespace,
                        objetivo=dados.get("objetivo"),
                        publico=dados.get("publico"),
                        regiao=dados.get("regiao"),
                        meta_contatos=dados.get("meta_contatos", 20),
                        contexto=dados.get("contexto"),
                        regras_adicionais=dados.get("regras_adicionais"),
                        origem="direcao",
                        prioridade=dados.get("prioridade", "normal"),
                    ), 201
                except Exception as erro:
                    return {"success": False, "error": str(erro)}, 400

    return {
        "success": True,
        "fase": FASE,
        "motor_universal_prospeccao": True,
        "comando_painel": True,
        "deteccao_lacunas": True,
        "reposicao_automatica_pesquisa": True,
        "aprendizado_negativas": True,
        "preco_margem_teto_expostos": False,
        "compromisso_estrategico_automatico": False,
    }
