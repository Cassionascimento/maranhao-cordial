
"""
FASE 5.6 — Prospecção e negociação autônoma de fábrica-piloto.

Escopo autorizado:
- prospectar fábricas em SP;
- enviar primeiro contato e follow-ups por e-mail;
- negociar questões operacionais e pedir orçamento;
- NÃO revelar teto interno de R$ 4.000;
- NÃO aceitar proposta, assinar contrato ou efetuar pagamento;
- alertar direção somente em respostas promissoras/relevantes;
- descartar respostas inviáveis e armazenar aprendizado.
"""

import os
import re
import json
import base64
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from psycopg2.extras import RealDictCursor

EMAIL_INSTITUCIONAL = "contato@maranhaocordial.com.br"
EMAIL_DIRECAO = "cassionegocios47@gmail.com"
EMAIL_TESTE_SOCIA = "xirleanedutra@gmail.com"

VOLUME_MIN_L = 20
VOLUME_MAX_L = 50
TETO_INTERNO_REAIS = 4000.0
DEADLINE = "2026-09-22"
META_FABRICAS = 20

LOGO_EMAIL = os.path.join(
    os.path.dirname(__file__),
    "maranhao-backend",
    "assets",
    "maranhao-cordial-logo-email.jpg",
)


def _conn(namespace):
    fn = namespace.get("get_db_connection")
    if callable(fn):
        return fn()
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _agora():
    return datetime.now(timezone.utc)


def instalar_schema_fase56(namespace):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS campanhas_fase56 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        codigo VARCHAR(80) UNIQUE NOT NULL,
                        objetivo TEXT NOT NULL,
                        deadline DATE NOT NULL,
                        meta_fabricas INTEGER NOT NULL DEFAULT 20,
                        volume_min_l INTEGER NOT NULL DEFAULT 20,
                        volume_max_l INTEGER NOT NULL DEFAULT 50,
                        teto_interno NUMERIC(12,2) NOT NULL DEFAULT 4000,
                        revelar_teto BOOLEAN NOT NULL DEFAULT FALSE,
                        estado VARCHAR(2) NOT NULL DEFAULT 'SP',
                        visita_presencial BOOLEAN NOT NULL DEFAULT TRUE,
                        status VARCHAR(30) NOT NULL DEFAULT 'ativa',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prospectos_fabrica_fase56 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        campanha_codigo VARCHAR(80) NOT NULL,
                        nome TEXT NOT NULL,
                        cidade TEXT,
                        estado VARCHAR(2) DEFAULT 'SP',
                        email TEXT,
                        site TEXT,
                        fonte_url TEXT,
                        capacidade_piloto BOOLEAN,
                        aceita_visita BOOLEAN,
                        prazo_compativel BOOLEAN,
                        preco_estimado NUMERIC(12,2),
                        status VARCHAR(40) NOT NULL DEFAULT 'novo',
                        classificacao VARCHAR(40),
                        motivo TEXT,
                        ultimo_contato_em TIMESTAMPTZ,
                        ultima_resposta_em TIMESTAMPTZ,
                        followup_em TIMESTAMPTZ,
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(campanha_codigo, email)
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS negociacoes_fabrica_fase56 (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        prospecto_id UUID REFERENCES prospectos_fabrica_fase56(id)
                            ON DELETE CASCADE,
                        direcao VARCHAR(10) NOT NULL,
                        email_remetente TEXT,
                        email_destinatario TEXT,
                        assunto TEXT,
                        conteudo TEXT,
                        classificacao VARCHAR(40),
                        preco_detectado NUMERIC(12,2),
                        aprendizado TEXT,
                        message_id TEXT,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    INSERT INTO campanhas_fase56 (
                        codigo, objetivo, deadline, meta_fabricas,
                        volume_min_l, volume_max_l, teto_interno,
                        revelar_teto, estado, visita_presencial, status
                    )
                    VALUES (
                        'FABRICA_PILOTO_SP_SET2026',
                        'Encontrar fábrica em SP para lote piloto de 20 a 50 L, com visita presencial e execução antes de 22/09/2026.',
                        '2026-09-22',
                        20, 20, 50, 4000, FALSE, 'SP', TRUE, 'ativa'
                    )
                    ON CONFLICT (codigo) DO UPDATE SET
                        atualizado_em = NOW(),
                        status = 'ativa'
                """)
        return {"success": True}
    finally:
        conn.close()


def _credenciais_google(namespace):
    candidatos = (
        "obter_credenciais_google",
        "carregar_credenciais_google",
        "obter_credenciais_gmail",
        "carregar_credenciais_gmail",
        "get_google_credentials",
        "get_gmail_credentials",
    )
    for nome in candidatos:
        fn = namespace.get(nome)
        if callable(fn):
            try:
                cred = fn()
                if cred:
                    return cred
            except Exception:
                pass

    try:
        from google.oauth2.credentials import Credentials
        caminhos = [
            os.getenv("GMAIL_TOKEN_FILE"),
            os.getenv("GOOGLE_TOKEN_FILE"),
            os.path.join(os.path.dirname(__file__), "token.json"),
            os.path.join(os.path.dirname(__file__), "gmail_token.json"),
            os.path.join(os.path.dirname(__file__), "token_gmail.json"),
        ]
        for caminho in caminhos:
            if caminho and os.path.exists(caminho):
                try:
                    return Credentials.from_authorized_user_file(
                        caminho,
                        scopes=[
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.modify",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    )
                except Exception:
                    pass

        client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN") or os.getenv("GMAIL_REFRESH_TOKEN")
        if client_id and client_secret and refresh_token:
            return Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=[
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://www.googleapis.com/auth/gmail.send",
                ],
            )
    except Exception:
        pass

    return None


def obter_gmail_service_fase56(namespace):
    for nome in (
        "obter_servico_gmail",
        "get_gmail_service",
        "criar_servico_gmail",
    ):
        fn = namespace.get(nome)
        if callable(fn):
            try:
                servico = fn()
                if servico:
                    return servico
            except Exception:
                pass

    cred = _credenciais_google(namespace)
    if not cred:
        raise RuntimeError(
            "Credenciais Gmail institucionais não localizadas pela Fase 5.6."
        )

    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=cred, cache_discovery=False)


def _assinatura_html():
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="margin-top:30px">
      <tr>
        <td></td>
        <td align="right" style="width:430px;text-align:right;
             border-top:1px solid #c8c8c8;padding-top:12px">
          <img src="cid:logo_maranhao_cordial" width="86"
               alt="Maranhão Cordial"
               style="display:inline-block;border-radius:50%;margin-bottom:8px">
          <div style="font-family:Georgia,'Times New Roman',serif;
               font-size:17px;letter-spacing:2px;font-weight:700">
            MARANHÃO CORDIAL
          </div>
          <div style="font-size:12px;margin-top:4px">Cássio Nascimento · Direção</div>
          <div style="font-size:12px">{EMAIL_INSTITUCIONAL}</div>
          <div style="font-size:12px">maranhaocordial.com.br</div>
          <div style="font-size:11px;color:#666;margin-top:4px">
            Av. Paulista, 1636 · CJ 4 · PAV. 15 · Sala 1504/4643<br>
            Cerqueira César · São Paulo – SP · CEP 01310-200
          </div>
        </td>
      </tr>
    </table>
    """


def _corpo_inicial_html(nome_fabrica=None):
    saudacao = f"Olá, equipe {nome_fabrica}," if nome_fabrica else "Olá,"
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;color:#171717;
                line-height:1.6;font-size:14px">
      <p>{saudacao}</p>
      <p>Sou da <strong>Maranhão Cordial</strong> e estamos selecionando,
      com prioridade, uma indústria no estado de São Paulo para realizar
      um <strong>lote piloto entre 20 e 50 litros</strong> de um concentrado
      premium não alcoólico de guaraná com gengibre, zero açúcar.</p>

      <p>Já temos conceito, especificações técnicas e documentação de apoio.
      Buscamos uma estrutura que consiga realizar o teste em pequena escala
      antes da produção comercial. Temos disponibilidade para
      <strong>ir pessoalmente à fábrica e acompanhar os testes</strong>.</p>

      <p>Gostaria de confirmar:</p>
      <ul>
        <li>vocês trabalham com lote piloto entre 20 e 50 litros?</li>
        <li>é possível acompanhar presencialmente o desenvolvimento/teste?</li>
        <li>qual é o custo estimado do piloto e o que está incluído?</li>
        <li>qual é a data mais próxima disponível?</li>
        <li>em caso de aprovação, existe possibilidade de escala posterior?</li>
      </ul>

      <p>Precisamos concluir essa etapa <strong>antes de 22 de setembro</strong>.
      Havendo viabilidade, podemos avançar rapidamente com as informações
      técnicas necessárias.</p>

      <p>Obrigado pelo retorno.</p>
      {_assinatura_html()}
    </div>
    """


def _corpo_inicial_texto(nome_fabrica=None):
    saudacao = f"Olá, equipe {nome_fabrica}," if nome_fabrica else "Olá,"
    return f"""{saudacao}

Sou da Maranhão Cordial e estamos selecionando, com prioridade, uma indústria no estado de São Paulo para realizar um lote piloto entre 20 e 50 litros de um concentrado premium não alcoólico de guaraná com gengibre, zero açúcar.

Já temos conceito, especificações técnicas e documentação de apoio. Temos disponibilidade para ir pessoalmente à fábrica e acompanhar os testes.

Gostaria de confirmar:
- vocês trabalham com lote piloto entre 20 e 50 litros?
- é possível acompanhar presencialmente o desenvolvimento/teste?
- qual é o custo estimado do piloto e o que está incluído?
- qual é a data mais próxima disponível?
- em caso de aprovação, existe possibilidade de escala posterior?

Precisamos concluir essa etapa antes de 22 de setembro.

Obrigado pelo retorno.

Maranhão Cordial
Cássio Nascimento · Direção
{EMAIL_INSTITUCIONAL}
maranhaocordial.com.br
Av. Paulista, 1636 · CJ 4 · PAV. 15 · Sala 1504/4643
Cerqueira César · São Paulo – SP · CEP 01310-200
"""


def enviar_email_institucional_fase56(
    namespace,
    destinatario,
    assunto,
    html,
    texto,
    cc=None,
    reply_message_id=None,
):
    service = obter_gmail_service_fase56(namespace)

    perfil = service.users().getProfile(userId="me").execute()
    remetente_real = (perfil.get("emailAddress") or "").strip().lower()

    if remetente_real != EMAIL_INSTITUCIONAL.lower():
        raise RuntimeError(
            f"Envio bloqueado: conta Gmail autenticada é {remetente_real or 'desconhecida'}, "
            f"mas a campanha exige {EMAIL_INSTITUCIONAL}."
        )

    msg = MIMEMultipart("related")
    msg["From"] = f"Maranhão Cordial <{EMAIL_INSTITUCIONAL}>"
    msg["To"] = destinatario
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = assunto

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(texto, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)

    if os.path.exists(LOGO_EMAIL):
        with open(LOGO_EMAIL, "rb") as f:
            imagem = MIMEImage(f.read(), _subtype="jpeg")
        imagem.add_header("Content-ID", "<logo_maranhao_cordial>")
        imagem.add_header(
            "Content-Disposition",
            "inline",
            filename="maranhao-cordial-logo.jpg",
        )
        msg.attach(imagem)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    corpo = {"raw": raw}
    if reply_message_id:
        corpo["threadId"] = reply_message_id

    resultado = (
        service.users()
        .messages()
        .send(userId="me", body=corpo)
        .execute()
    )
    return {
        "success": True,
        "message_id": resultado.get("id"),
        "thread_id": resultado.get("threadId"),
        "remetente": remetente_real,
    }



def testar_fluxo_direcao_fase56(namespace):
    """
    Homologação real do canal institucional.
    Usa exatamente o mesmo executor utilizado pela prospecção,
    mas envia somente para a Direção.
    """
    assunto = (
        "HOMOLOGAÇÃO — Maranhão Cordial | "
        "Prospecção automática de fábrica-piloto"
    )

    html = _corpo_inicial_html(
        "Cássio — homologação do fluxo automático"
    )

    texto = _corpo_inicial_texto(
        "Cássio — homologação do fluxo automático"
    )

    return enviar_email_institucional_fase56(
        namespace,
        EMAIL_DIRECAO,
        assunto,
        html,
        texto,
    )


def testar_fluxo_fase56(namespace):
    assunto = "Teste institucional — Maranhão Cordial | Prospecção de lote piloto"
    html = _corpo_inicial_html("Maranhão Cordial — teste interno")
    texto = _corpo_inicial_texto("Maranhão Cordial — teste interno")
    return enviar_email_institucional_fase56(
        namespace,
        EMAIL_TESTE_SOCIA,
        assunto,
        html,
        texto,
        cc=EMAIL_DIRECAO,
    )


def _extrair_preco(texto):
    if not texto:
        return None
    t = texto.lower().replace(".", "")
    candidatos = []
    for m in re.finditer(
        r"(?:r\$\s*)?(\d{1,6}(?:,\d{1,2})?)",
        t,
        flags=re.I,
    ):
        bruto = m.group(1).replace(",", ".")
        try:
            valor = float(bruto)
        except Exception:
            continue
        if 100 <= valor <= 100000:
            candidatos.append(valor)
    return min(candidatos) if candidatos else None


def classificar_resposta_fabrica_fase56(texto):
    t = (texto or "").lower()
    preco = _extrair_preco(texto)

    negativas = (
        "não fazemos lote piloto",
        "nao fazemos lote piloto",
        "não trabalhamos com lote piloto",
        "nao trabalhamos com lote piloto",
        "não atendemos",
        "nao atendemos",
        "lote mínimo de 200",
        "lote minimo de 200",
        "lote mínimo de 500",
        "lote minimo de 500",
        "lote mínimo de 1000",
        "lote minimo de 1000",
        "sem disponibilidade antes",
        "não temos disponibilidade",
        "nao temos disponibilidade",
    )

    if preco is not None and preco > TETO_INTERNO_REAIS:
        return {
            "classificacao": "descartar_custo",
            "boa_resposta": False,
            "descartar": True,
            "preco_detectado": preco,
            "motivo": "Preço acima do teto interno da campanha.",
        }

    if any(x in t for x in negativas):
        return {
            "classificacao": "inviavel",
            "boa_resposta": False,
            "descartar": True,
            "preco_detectado": preco,
            "motivo": "Resposta incompatível com volume, prazo ou disponibilidade.",
        }

    sinais_bons = sum(
        1 for x in (
            "podemos", "conseguimos", "lote piloto", "20 litros",
            "30 litros", "40 litros", "50 litros", "visita",
            "agendar", "desenvolvimento", "teste", "orçamento",
            "orcamento", "disponibilidade",
        )
        if x in t
    )

    if sinais_bons >= 2:
        return {
            "classificacao": "promissora",
            "boa_resposta": True,
            "descartar": False,
            "preco_detectado": preco,
            "motivo": "Há sinais concretos de capacidade/agenda/visita para o piloto.",
        }

    return {
        "classificacao": "negociar",
        "boa_resposta": False,
        "descartar": False,
        "preco_detectado": preco,
        "motivo": "Resposta requer esclarecimento comercial/operacional.",
    }


def _gerar_followup_com_ia(texto_resposta):
    from openai import OpenAI
    client = OpenAI()

    prompt = f"""
Você conduz uma negociação B2B por e-mail em nome da Maranhão Cordial.

Objetivo:
- fábrica em São Paulo;
- lote piloto de 20 a 50 litros;
- possibilidade de visita presencial;
- execução antes de 22/09/2026;
- perguntar preço e o que inclui;
- buscar clareza de prazo, estrutura e possibilidade de escala.

REGRAS ABSOLUTAS:
- nunca revelar que existe teto interno de R$ 4.000;
- nunca aceitar preço;
- nunca prometer pagamento;
- nunca assinar ou aceitar contrato;
- nunca autorizar produção comercial;
- pode pedir esclarecimentos e perguntar se existe alternativa de piloto menor;
- resposta curta, profissional e objetiva;
- não use linguagem agressiva de negociação.

Resposta recebida da fábrica:
{texto_resposta}

Escreva somente o corpo do e-mail de resposta, sem assunto e sem assinatura.
"""
    resp = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-mini"),
        input=prompt,
    )
    texto = getattr(resp, "output_text", None) or ""
    texto = texto.strip()
    if not texto:
        raise RuntimeError("IA não gerou follow-up.")
    return texto


def _validar_followup(texto):
    t = (texto or "").lower()
    proibidos = (
        "r$ 4.000", "r$4.000", "4000", "quatro mil",
        "aceitamos o valor", "fechado", "pode produzir",
        "autorizamos a produção", "realizaremos o pagamento",
        "vamos pagar", "aceitamos a proposta",
    )
    if any(x in t for x in proibidos):
        raise RuntimeError("Follow-up bloqueado pela política financeira da Fase 5.6.")
    return True


def registrar_negociacao_fase56(
    namespace,
    prospecto_id,
    direcao,
    remetente,
    destinatario,
    assunto,
    conteudo,
    classificacao,
    preco=None,
    aprendizado=None,
    message_id=None,
):
    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO negociacoes_fabrica_fase56 (
                        prospecto_id, direcao, email_remetente,
                        email_destinatario, assunto, conteudo,
                        classificacao, preco_detectado,
                        aprendizado, message_id
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    prospecto_id, direcao, remetente,
                    destinatario, assunto, conteudo,
                    classificacao, preco,
                    aprendizado, message_id,
                ))
    finally:
        conn.close()


def _buscar_prospecto_por_email(namespace, email):
    if not email:
        return None
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM prospectos_fabrica_fase56
                WHERE campanha_codigo='FABRICA_PILOTO_SP_SET2026'
                  AND LOWER(email)=LOWER(%s)
                LIMIT 1
            """, (email.strip(),))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def processar_resposta_fabrica_fase56(namespace, interacao):
    canal = str(interacao.get("canal") or "").lower()
    if canal != "gmail":
        return {"processado": False, "motivo": "canal_nao_gmail"}

    remetente = (
        interacao.get("email_remetente")
        or interacao.get("sender_email")
        or interacao.get("sender_id")
        or interacao.get("remetente")
    )
    if not remetente:
        return {"processado": False, "motivo": "sem_remetente"}

    m = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", str(remetente))
    email = m.group(0) if m else str(remetente).strip()

    prospecto = _buscar_prospecto_por_email(namespace, email)
    if not prospecto:
        return {"processado": False, "motivo": "fora_campanha_fase56"}

    texto = (
        interacao.get("texto")
        or interacao.get("mensagem")
        or interacao.get("conteudo")
        or ""
    )
    assunto = interacao.get("assunto") or "Re: Lote piloto Maranhão Cordial"
    classificacao = classificar_resposta_fabrica_fase56(texto)

    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                if classificacao["descartar"]:
                    cur.execute("""
                        UPDATE prospectos_fabrica_fase56
                        SET status='descartado',
                            classificacao=%s,
                            motivo=%s,
                            preco_estimado=COALESCE(%s, preco_estimado),
                            ultima_resposta_em=NOW(),
                            atualizado_em=NOW()
                        WHERE id=%s
                    """, (
                        classificacao["classificacao"],
                        classificacao["motivo"],
                        classificacao["preco_detectado"],
                        prospecto["id"],
                    ))
                elif classificacao["boa_resposta"]:
                    cur.execute("""
                        UPDATE prospectos_fabrica_fase56
                        SET status='promissora',
                            classificacao='promissora',
                            motivo=%s,
                            preco_estimado=COALESCE(%s, preco_estimado),
                            ultima_resposta_em=NOW(),
                            atualizado_em=NOW()
                        WHERE id=%s
                    """, (
                        classificacao["motivo"],
                        classificacao["preco_detectado"],
                        prospecto["id"],
                    ))

                    cur.execute("""
                        INSERT INTO acoes_empresariais (
                            tipo, canal, destinatario, conteudo,
                            justificativa, status, prioridade,
                            tipo_execucao
                        )
                        VALUES (
                            'decisao_fabrica_fase56',
                            'interno',
                            'direcao',
                            %s,
                            %s,
                            'aguardando_aprovacao',
                            'critica',
                            'registrar_analise_interna'
                        )
                    """, (
                        f"Fábrica promissora para lote piloto: {prospecto['nome']} — {email}.",
                        f"Resposta compatível com campanha urgente até {DEADLINE}. {classificacao['motivo']}",
                    ))
                else:
                    cur.execute("""
                        UPDATE prospectos_fabrica_fase56
                        SET status='negociando',
                            classificacao='negociar',
                            motivo=%s,
                            preco_estimado=COALESCE(%s, preco_estimado),
                            ultima_resposta_em=NOW(),
                            atualizado_em=NOW()
                        WHERE id=%s
                    """, (
                        classificacao["motivo"],
                        classificacao["preco_detectado"],
                        prospecto["id"],
                    ))
    finally:
        conn.close()

    registrar_negociacao_fase56(
        namespace,
        prospecto["id"],
        "entrada",
        email,
        EMAIL_INSTITUCIONAL,
        assunto,
        texto,
        classificacao["classificacao"],
        classificacao["preco_detectado"],
        classificacao["motivo"],
        interacao.get("message_id"),
    )

    if (
        not classificacao["descartar"]
        and not classificacao["boa_resposta"]
    ):
        follow = _gerar_followup_com_ia(texto)
        _validar_followup(follow)

        html = f"""
        <div style="font-family:Arial,Helvetica,sans-serif;color:#171717;
                    line-height:1.6;font-size:14px">
          {''.join(f'<p>{p.strip()}</p>' for p in follow.splitlines() if p.strip())}
          {_assinatura_html()}
        </div>
        """
        resultado = enviar_email_institucional_fase56(
            namespace,
            email,
            assunto if assunto.lower().startswith("re:") else f"Re: {assunto}",
            html,
            follow,
        )
        registrar_negociacao_fase56(
            namespace,
            prospecto["id"],
            "saida",
            EMAIL_INSTITUCIONAL,
            email,
            assunto,
            follow,
            "followup_automatico",
            None,
            "Follow-up operacional enviado dentro da política autorizada.",
            resultado.get("message_id"),
        )
        return {
            "processado": True,
            "classificacao": classificacao,
            "followup_enviado": True,
        }

    return {
        "processado": True,
        "classificacao": classificacao,
        "followup_enviado": False,
    }


def enviar_primeiro_contato_fase56(namespace, prospecto_id):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM prospectos_fabrica_fase56
                WHERE id=%s
                  AND campanha_codigo='FABRICA_PILOTO_SP_SET2026'
                  AND status IN ('novo','qualificado')
            """, (prospecto_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "motivo": "prospecto_nao_disponivel"}
            prospecto = dict(row)
    finally:
        conn.close()

    if not prospecto.get("email"):
        return {"success": False, "motivo": "sem_email_publico"}

    assunto = "Lote piloto 20–50 L — concentrado não alcoólico | visita técnica em SP"
    html = _corpo_inicial_html(prospecto.get("nome"))
    texto = _corpo_inicial_texto(prospecto.get("nome"))

    resultado = enviar_email_institucional_fase56(
        namespace,
        prospecto["email"],
        assunto,
        html,
        texto,
        cc=None,
    )

    conn = _conn(namespace)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE prospectos_fabrica_fase56
                    SET status='contatado',
                        ultimo_contato_em=NOW(),
                        followup_em=NOW()+INTERVAL '2 days',
                        tentativas=tentativas+1,
                        atualizado_em=NOW()
                    WHERE id=%s
                """, (prospecto["id"],))
    finally:
        conn.close()

    registrar_negociacao_fase56(
        namespace,
        prospecto["id"],
        "saida",
        EMAIL_INSTITUCIONAL,
        prospecto["email"],
        assunto,
        texto,
        "primeiro_contato",
        None,
        "Contato inicial autorizado pela direção para campanha urgente.",
        resultado.get("message_id"),
    )
    return resultado


def obter_status_fase56(namespace):
    conn = _conn(namespace)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)::INTEGER total,
                    COUNT(*) FILTER (WHERE status='novo')::INTEGER novos,
                    COUNT(*) FILTER (WHERE status='contatado')::INTEGER contatados,
                    COUNT(*) FILTER (WHERE status='negociando')::INTEGER negociando,
                    COUNT(*) FILTER (WHERE status='promissora')::INTEGER promissoras,
                    COUNT(*) FILTER (WHERE status='descartado')::INTEGER descartados
                FROM prospectos_fabrica_fase56
                WHERE campanha_codigo='FABRICA_PILOTO_SP_SET2026'
            """)
            resumo = dict(cur.fetchone() or {})

            cur.execute("""
                SELECT id,nome,cidade,email,site,status,classificacao,
                       preco_estimado,motivo,ultimo_contato_em,
                       ultima_resposta_em,followup_em
                FROM prospectos_fabrica_fase56
                WHERE campanha_codigo='FABRICA_PILOTO_SP_SET2026'
                ORDER BY
                    CASE status
                      WHEN 'promissora' THEN 0
                      WHEN 'negociando' THEN 1
                      WHEN 'contatado' THEN 2
                      WHEN 'novo' THEN 3
                      ELSE 4
                    END,
                    atualizado_em DESC
                LIMIT 30
            """)
            itens = []
            for r in cur.fetchall():
                d = dict(r)
                d["id"] = str(d["id"])
                for c in ("ultimo_contato_em","ultima_resposta_em","followup_em"):
                    if d.get(c):
                        d[c] = d[c].isoformat()
                if d.get("preco_estimado") is not None:
                    d["preco_estimado"] = float(d["preco_estimado"])
                itens.append(d)

        return {
            "success": True,
            "fase": "5.6",
            "campanha": "FABRICA_PILOTO_SP_SET2026",
            "deadline": DEADLINE,
            "meta_fabricas": META_FABRICAS,
            "volume_l": [VOLUME_MIN_L, VOLUME_MAX_L],
            "teto_interno_revelado": False,
            "resumo": resumo,
            "prospectos": itens,
        }
    finally:
        conn.close()


def instalar_fase56(namespace):
    instalar_schema_fase56(namespace)

    app = namespace.get("app")
    validar_admin = namespace.get("validar_admin_request")

    processar = namespace.get("processar_interacao_omnichannel_crm")
    if callable(processar) and not getattr(processar, "_fase56", False):
        def processar56(*args, _original=processar, **kwargs):
            resultado = _original(*args, **kwargs)
            interacao = args[0] if args else kwargs.get("interacao")
            if isinstance(interacao, dict):
                try:
                    processar_resposta_fabrica_fase56(namespace, interacao)
                except Exception as erro:
                    print("FASE 5.6 — PROCESSAMENTO RESPOSTA:", repr(erro))
            return resultado
        processar56._fase56 = True
        namespace["processar_interacao_omnichannel_crm"] = processar56

    if app is not None and callable(validar_admin):
        if "admin_fase56_status" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase56", methods=["GET"])
            def admin_fase56_status():
                if not validar_admin():
                    return {"success": False, "error": "Não autorizado."}, 401
                try:
                    return obter_status_fase56(namespace), 200
                except Exception as erro:
                    return {"success": False, "error": str(erro)}, 500

        if "admin_fase56_teste" not in app.view_functions:
            @app.route("/api/admin/ia-empresarial/fase56/teste", methods=["POST"])
            def admin_fase56_teste():
                if not validar_admin():
                    return {"success": False, "error": "Não autorizado."}, 401
                try:
                    return testar_fluxo_fase56(namespace), 200
                except Exception as erro:
                    return {"success": False, "error": str(erro)}, 500

        if "admin_fase56_enviar" not in app.view_functions:
            @app.route(
                "/api/admin/ia-empresarial/fase56/prospectos/<prospecto_id>/enviar",
                methods=["POST"],
            )
            def admin_fase56_enviar(prospecto_id):
                if not validar_admin():
                    return {"success": False, "error": "Não autorizado."}, 401
                try:
                    return enviar_primeiro_contato_fase56(
                        namespace, prospecto_id
                    ), 200
                except Exception as erro:
                    return {"success": False, "error": str(erro)}, 500

    return {
        "success": True,
        "fase": "5.6",
        "campanha": "FABRICA_PILOTO_SP_SET2026",
        "email_institucional_obrigatorio": EMAIL_INSTITUCIONAL,
        "negociacao_operacional_automatica": True,
        "contrato_pagamento_aceite_automatico": False,
        "teto_interno_revelado": False,
    }
