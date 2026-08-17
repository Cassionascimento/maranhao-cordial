from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
import os
import uuid
import re
import requests
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI

# =====================================================
# CONFIGURAÇÃO
# =====================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CONTEXTO_MARANHAO = """
Maranhão Cordial é um concentrado premium não alcoólico de guaraná e gengibre,
apresentado em garrafa de 200 mL.

É utilizado em pequenas doses para preparo de bebidas e outras aplicações
gastronômicas.

Pode ser combinado com água com gás, água tônica, vodka, cachaça, café e
outras preparações.

O produto foi desenvolvido com foco em padronização, praticidade de bancada
e experiência sensorial.

A Maranhão Cordial atende consumidores pelo site oficial
maranhaocordial.com.br e possui atendimento profissional B2B para bares,
restaurantes, hotéis, bartenders, mixologistas e distribuidores.

A empresa não possui lojas físicas próprias.

Quando não houver informação oficial suficiente para responder uma pergunta,
não invente. Informe que o atendimento pode orientar o cliente.
"""


# =====================================================
# IA — RESPOSTAS RÁPIDAS E INTELIGÊNCIA EMPRESARIAL
# =====================================================

RESPOSTAS_RAPIDAS_MARANHAO = {
    "o_que_e": (
        "Maranhão Cordial é um concentrado premium não alcoólico "
        "de guaraná e gengibre, desenvolvido para preparar e "
        "padronizar bebidas em pequenas doses."
    ),

    "o_que_faz": (
        "Maranhão Cordial concentra sabor, aroma e acidez em uma "
        "pequena dose, facilitando o preparo e a padronização de bebidas."
    ),

    "para_que_serve": (
        "Maranhão Cordial é usado no preparo de bebidas e aplicações "
        "gastronômicas, com foco em praticidade, padronização e experiência sensorial."
    ),

    "como_usar": (
        "Use em pequenas doses e ajuste conforme a preparação. "
        "Pode ser combinado com água com gás, tônica, café e diferentes destilados."
    ),

    "onde_comprar": (
        "A compra oficial pode ser realizada em maranhaocordial.com.br. "
        "A Maranhão Cordial não possui lojas físicas próprias."
    )
}


CONTEXTO_EMPRESARIAL_INTERNO = """
INFORMAÇÕES INTERNAS PARA RACIOCÍNIO EMPRESARIAL.

A Maranhão Cordial busca desenvolver mercado B2B com bares,
restaurantes, hotéis, bartenders, mixologistas, eventos,
distribuidores e operações de hospitalidade.

O produto pode ser analisado comercialmente como ingrediente,
ferramenta de padronização de serviço e elemento de experiência
de marca e identidade cultural.

A marca possui o projeto musical GINGA — Five Moments.

O álbum possui cinco faixas:
Black Ginga;
Rhythm of That Look;
Quimbara Cumba;
Maranhão en el Alma;
Maranhão Cordial.

O projeto musical pode ser considerado como ativo de experiência
de marca na identificação de oportunidades envolvendo hotelaria,
bares, gastronomia, turismo, eventos, ambientação e ativações culturais.

A IA pode utilizar informações empresariais internas para analisar
oportunidades, qualificar leads e apoiar prospecção.

Informações classificadas como internas não devem ser reveladas
automaticamente ao consumidor final.

Nunca revele segredos, credenciais, chaves de API, dados bancários,
dados pessoais, fórmulas confidenciais, custos internos ou informações
estratégicas protegidas.
"""


def resposta_rapida_maranhao(mensagem):
    texto = mensagem.strip().lower()

    regras = [
        (
            [
                "o que é o maranhão cordial",
                "o que e o maranhao cordial"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["o_que_e"]
        ),
        (
            [
                "o que esse produto faz",
                "o que o produto faz",
                "o que faz esse produto"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["o_que_faz"]
        ),
        (
            ["para que serve"],
            RESPOSTAS_RAPIDAS_MARANHAO["para_que_serve"]
        ),
        (
            ["como usar", "como usa"],
            RESPOSTAS_RAPIDAS_MARANHAO["como_usar"]
        ),
        (
            [
                "onde comprar",
                "onde eu compro",
                "como comprar",
                "tem loja física",
                "tem loja fisica"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["onde_comprar"]
        )
    ]

    for frases, resposta in regras:
        if any(frase in texto for frase in frases):
            return resposta

    return None


ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# =====================================================
# BANCO DE DADOS — LEADS B2B E DEGUSTAÇÃO
# =====================================================

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada. Adicione a Internal Database URL "
            "do PostgreSQL nas variáveis de ambiente do serviço."
        )

    return psycopg2.connect(
        DATABASE_URL,
        sslmode=os.getenv("DB_SSLMODE", "require")
    )


def inicializar_banco():
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                # ==========================================
                # LEADS B2B
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cadastros_profissionais (
                        id UUID PRIMARY KEY,
                        empresa VARCHAR(180) NOT NULL,
                        cnpj VARCHAR(30) NOT NULL,
                        segmento VARCHAR(80) NOT NULL,
                        responsavel VARCHAR(180) NOT NULL,
                        whatsapp VARCHAR(40) NOT NULL,
                        email VARCHAR(180) NOT NULL,
                        cidade VARCHAR(180) NOT NULL,
                        interesse VARCHAR(80) NOT NULL,
                        mensagem TEXT,
                        consentimento BOOLEAN NOT NULL DEFAULT FALSE,
                        status VARCHAR(40) NOT NULL DEFAULT 'novo_lead',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # SOLICITAÇÕES DE DEGUSTAÇÃO
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS solicitacoes_degustacao (
                        id UUID PRIMARY KEY,
                        empresa VARCHAR(180) NOT NULL,
                        cnpj VARCHAR(30),
                        segmento VARCHAR(80) NOT NULL,
                        cidade VARCHAR(180) NOT NULL,
                        responsavel VARCHAR(180) NOT NULL,
                        whatsapp VARCHAR(40) NOT NULL,
                        email VARCHAR(180) NOT NULL,
                        mensagem TEXT,
                        status VARCHAR(40) NOT NULL DEFAULT 'nova_solicitacao',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # PEDIDOS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS atendimentos_sac (
                        id UUID PRIMARY KEY,
                        atendimento_id VARCHAR(40) UNIQUE NOT NULL,
                        mensagem TEXT NOT NULL,
                        resposta TEXT,
                        origem VARCHAR(40),
                        tipo VARCHAR(40),
                        codigo_pedido VARCHAR(40),
                        cliente_email VARCHAR(180),
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pedidos (
                        id UUID PRIMARY KEY,

                        codigo VARCHAR(40)
                            UNIQUE NOT NULL,

                        cliente_nome VARCHAR(180),
                        cliente_email VARCHAR(180),
                        cliente_whatsapp VARCHAR(40),
                        cpf_cnpj VARCHAR(30),

                        endereco TEXT NOT NULL,

                        quantidade INTEGER NOT NULL,

                        valor_centavos INTEGER NOT NULL,

                        status VARCHAR(50)
                            NOT NULL
                            DEFAULT 'aguardando_pagamento',

                        payment_origin VARCHAR(30),

                        c6_txid VARCHAR(120),
                        c6_status VARCHAR(50),

                        pagarme_id VARCHAR(160),

                        transportadora VARCHAR(160),

                        status_entrega VARCHAR(60)
                            NOT NULL
                            DEFAULT 'aguardando_pagamento',

                        tracking_code VARCHAR(180),
                        tracking_url TEXT,

                        criado_em TIMESTAMPTZ
                            NOT NULL
                            DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL
                            DEFAULT NOW()
                    )
                """)

    finally:
        conn.close()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_FOLDER = os.path.join(
    BASE_DIR,
    "maranhao-backend"
)

print("=" * 60)
print("BASE_DIR:", BASE_DIR)
print("FRONTEND_FOLDER:", FRONTEND_FOLDER)
print("PASTA EXISTE?", os.path.isdir(FRONTEND_FOLDER))
print("INDEX EXISTE?",
      os.path.isfile(os.path.join(FRONTEND_FOLDER, "index.html")))
print("=" * 60)

app = Flask(
    __name__,
    static_folder=FRONTEND_FOLDER
)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    "krikati_ancestral_secret"
)

# =====================================================
# CORS — SAC MARANHÃO CORDIAL
# =====================================================

ORIGENS_PERMITIDAS_SAC = {
    "https://maranhaocordial.com.br",
    "https://www.maranhaocordial.com.br",
}


@app.after_request
def adicionar_cors_sac(response):

    if (
        request.path.startswith("/api/sac")
        or request.path.startswith("/api/admin")
    ):

        origem = request.headers.get("Origin")

        if origem in ORIGENS_PERMITIDAS_SAC:

            response.headers[
                "Access-Control-Allow-Origin"
            ] = origem

            response.headers[
                "Vary"
            ] = "Origin"

            response.headers[
                "Access-Control-Allow-Headers"
            ] = "Content-Type, X-Admin-Key"

            response.headers[
                "Access-Control-Allow-Methods"
            ] = "GET, POST, OPTIONS"

    return response


socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)

# =====================================================
# PAGAR.ME
# =====================================================

PAGARME_SECRET_KEY = os.getenv(
    "PAGARME_SECRET_KEY"
)

PAGARME_BASE_URL = os.getenv(
    "PAGARME_BASE_URL",
    "https://sdx-api.pagar.me/core/v5"
)

# Maranhão
PRECO_UNITARIO = 5990  # R$ 59,90 em centavos


# =====================================================
# C6 BANK — CONFIGURAÇÃO DA API
# =====================================================
#
# O C6 libera os endpoints/credenciais definitivos após
# cadastro, sandbox e homologação. Por isso, nada aqui
# inventa URLs bancárias: tudo entra pelo .env.
#

C6_CLIENT_ID = os.getenv("C6_CLIENT_ID")
C6_CLIENT_SECRET = os.getenv("C6_CLIENT_SECRET")
C6_TOKEN_URL = os.getenv("C6_TOKEN_URL")
C6_PIX_CREATE_URL = os.getenv("C6_PIX_CREATE_URL")
C6_PIX_QUERY_URL_TEMPLATE = os.getenv("C6_PIX_QUERY_URL_TEMPLATE")
C6_SCOPE = os.getenv("C6_SCOPE", "")

# Alguns produtos bancários usam certificado cliente (mTLS).
# Se o C6 exigir, coloque os caminhos dos arquivos no Render.
C6_CERT_PATH = os.getenv("C6_CERT_PATH")
C6_KEY_PATH = os.getenv("C6_KEY_PATH")

# Modo de autenticação configurável, conforme documentação
# que o C6 fornecer à sua empresa: basic ou body.
C6_AUTH_MODE = os.getenv("C6_AUTH_MODE", "basic").lower()

# O webhook só libera pedido automaticamente se o evento
# recebido puder ser confirmado consultando a própria API C6.
# Assim, não confiamos cegamente em um POST externo.
C6_PAID_STATUS_VALUES = {
    x.strip().upper()
    for x in os.getenv("C6_PAID_STATUS_VALUES", "").split(",")
    if x.strip()
}

# Nome do campo de status na resposta de consulta do C6.
# Ex.: status, situacao etc. Ajustar após receber a documentação.
C6_STATUS_FIELD = os.getenv("C6_STATUS_FIELD", "status")


# =====================================================
# LOGÍSTICA — CONFIGURAÇÃO FUTURA
# =====================================================
# A empresa de entrega ainda será contratada.
# Este token é opcional e servirá para proteger um webhook
# genérico até adaptarmos ao contrato/API da transportadora.

LOGISTICA_WEBHOOK_TOKEN = os.getenv("LOGISTICA_WEBHOOK_TOKEN")


# =====================================================
# BANCO TEMPORÁRIO DE PEDIDOS
# =====================================================
#
# IMPORTANTE:
# Isso é apenas para teste.
# Na produção, devemos usar seu banco de dados.
#

PEDIDOS = {}

def salvar_pedido_postgres(pedido):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO pedidos (
                        id,
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        cpf_cnpj,
                        endereco,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_txid,
                        c6_status,
                        pagarme_id,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        tracking_url
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (codigo)
                    DO UPDATE SET
                        cliente_nome = EXCLUDED.cliente_nome,
                        cliente_email = EXCLUDED.cliente_email,
                        cliente_whatsapp = EXCLUDED.cliente_whatsapp,
                        cpf_cnpj = EXCLUDED.cpf_cnpj,
                        endereco = EXCLUDED.endereco,
                        quantidade = EXCLUDED.quantidade,
                        valor_centavos = EXCLUDED.valor_centavos,
                        status = EXCLUDED.status,
                        payment_origin = EXCLUDED.payment_origin,
                        c6_txid = EXCLUDED.c6_txid,
                        c6_status = EXCLUDED.c6_status,
                        pagarme_id = EXCLUDED.pagarme_id,
                        transportadora = EXCLUDED.transportadora,
                        status_entrega = EXCLUDED.status_entrega,
                        tracking_code = EXCLUDED.tracking_code,
                        tracking_url = EXCLUDED.tracking_url,
                        atualizado_em = NOW()
                """, (
                    str(uuid.uuid4()),
                    pedido.get("code"),
                    pedido.get("cliente_nome"),
                    pedido.get("cliente_email"),
                    pedido.get("cliente_whatsapp"),
                    pedido.get("cpf_cnpj"),
                    pedido.get("address"),
                    pedido.get("quantity"),
                    pedido.get("amount"),
                    pedido.get("status"),
                    pedido.get("payment_origin"),
                    pedido.get("c6_txid"),
                    pedido.get("c6_status"),
                    pedido.get("pagarme_id"),
                    pedido.get("delivery", {}).get("provider"),
                    pedido.get("delivery", {}).get("status"),
                    pedido.get("delivery", {}).get("tracking_code"),
                    pedido.get("delivery", {}).get("tracking_url")
                ))

    finally:
        conn.close()


def salvar_atendimento_sac(
    atendimento_id,
    mensagem,
    resposta,
    origem,
    tipo,
    codigo_pedido=None,
    cliente_email=None
):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO atendimentos_sac (
                        id,
                        atendimento_id,
                        mensagem,
                        resposta,
                        origem,
                        tipo,
                        codigo_pedido,
                        cliente_email
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (atendimento_id)
                    DO UPDATE SET
                        mensagem = EXCLUDED.mensagem,
                        resposta = EXCLUDED.resposta,
                        origem = EXCLUDED.origem,
                        tipo = EXCLUDED.tipo,
                        codigo_pedido = EXCLUDED.codigo_pedido,
                        cliente_email = EXCLUDED.cliente_email
                """, (
                    str(uuid.uuid4()),
                    atendimento_id,
                    mensagem,
                    resposta,
                    origem,
                    tipo,
                    codigo_pedido,
                    cliente_email
                ))

    finally:
        conn.close()


# =====================================================
# PÁGINA INICIAL
# =====================================================

@app.route("/")
@app.route("/index")
@app.route("/index.html")
def index():
    return send_from_directory(
        FRONTEND_FOLDER,
        "index.html"
    )


# =====================================================
# PÁGINAS
# =====================================================

def renderizar_html(nome_arquivo):

    caminho = os.path.join(
        FRONTEND_FOLDER,
        nome_arquivo
    )

    if os.path.isfile(caminho):
        return send_from_directory(
            FRONTEND_FOLDER,
            nome_arquivo
        )

    nome_maiusculo = nome_arquivo.replace(
        ".html",
        ".HTML"
    )

    caminho_maiusculo = os.path.join(
        FRONTEND_FOLDER,
        nome_maiusculo
    )

    if os.path.isfile(caminho_maiusculo):
        return send_from_directory(
            FRONTEND_FOLDER,
            nome_maiusculo
        )

    return (
        f"Erro: O arquivo '{nome_arquivo}' "
        "não foi encontrado.",
        404
    )


@app.route("/experience")
def experience():
    return renderizar_html("experience.html")


@app.route("/raizes")
def raizes():
    return renderizar_html("raizes.html")


@app.route("/deposito")
@app.route("/deposito.html")
def deposito():
    return renderizar_html("deposito.html")


@app.route("/entrega")
@app.route("/entrega.html")
def entrega():
    return renderizar_html("entrega.html")


@app.route("/compreaqui")
@app.route("/compreaqui.html")
def compreaqui():
    return renderizar_html("compreaqui.html")


@app.route("/checkout.html")
def checkout():
    return renderizar_html("checkout.html")

@app.route("/home.html")
def home():
    return renderizar_html("home.html")

@app.route("/profissional")
def profissional():
    return renderizar_html("profissional.html")

@app.route("/cadastro-profissional")
def cadastro_profissional():
    return renderizar_html("cadastro-profissional.html")

@app.route("/degustacao")
@app.route("/degustacao.html")
def degustacao():
    return renderizar_html("degustacao.html")

@app.route(
    "/api/profissional/cadastro",
    methods=["POST"]
)
def cadastrar_empresa():
    dados = request.get_json(silent=True) or {}

    obrigatorios = [
        "empresa", "cnpj", "segmento", "responsavel",
        "whatsapp", "email", "cidade", "interesse"
    ]

    faltando = [
        campo for campo in obrigatorios
        if not str(dados.get(campo, "")).strip()
    ]

    if faltando:
        return jsonify({
            "success": False,
            "error": "Preencha todos os campos obrigatórios.",
            "fields": faltando
        }), 400

    if dados.get("consentimento") is not True:
        return jsonify({
            "success": False,
            "error": "É necessário autorizar o contato comercial."
        }), 400

    cadastro_id = str(uuid.uuid4())

    try:
        conn = get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO cadastros_profissionais (
                            id, empresa, cnpj, segmento, responsavel,
                            whatsapp, email, cidade, interesse, mensagem,
                            consentimento, status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s
                        )
                    """, (
                        cadastro_id,
                        str(dados["empresa"]).strip(),
                        str(dados["cnpj"]).strip(),
                        str(dados["segmento"]).strip(),
                        str(dados["responsavel"]).strip(),
                        str(dados["whatsapp"]).strip(),
                        str(dados["email"]).strip().lower(),
                        str(dados["cidade"]).strip(),
                        str(dados["interesse"]).strip(),
                        str(dados.get("mensagem", "")).strip() or None,
                        True,
                        "novo_lead"
                    ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Cadastro profissional recebido.",
            "empresa_id": str(cadastro_id)
        }), 201

    except Exception as erro:
        print("ERRO SALVAR CADASTRO PROFISSIONAL:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível salvar o cadastro agora."
        }), 500


@app.route(
    "/api/degustacao",
    methods=["POST"]
)
def cadastrar_degustacao():
    dados = request.get_json(silent=True) or {}

    obrigatorios = [
        "empresa", "segmento", "cidade", "responsavel",
        "whatsapp", "email"
    ]

    faltando = [
        campo for campo in obrigatorios
        if not str(dados.get(campo, "")).strip()
    ]

    if faltando:
        return jsonify({
            "success": False,
            "error": "Preencha todos os campos obrigatórios.",
            "fields": faltando
        }), 400

    degustacao_id = str(uuid.uuid4())

    try:
        conn = get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO solicitacoes_degustacao (
                            id, empresa, cnpj, segmento, cidade,
                            responsavel, whatsapp, email, mensagem, status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                    """, (
                        degustacao_id,
                        str(dados["empresa"]).strip(),
                        str(dados.get("cnpj", "")).strip() or None,
                        str(dados["segmento"]).strip(),
                        str(dados["cidade"]).strip(),
                        str(dados["responsavel"]).strip(),
                        str(dados["whatsapp"]).strip(),
                        str(dados["email"]).strip().lower(),
                        str(dados.get("mensagem", "")).strip() or None,
                        "nova_solicitacao"
                    ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Solicitação de degustação recebida.",
            "degustacao_id": degustacao_id
        }), 201

    except Exception as erro:
        print("ERRO SALVAR DEGUSTAÇÃO:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível salvar a solicitação agora."
        }), 500


# =====================================================
# SAC MARANHÃO CORDIAL — ETAPA 1 DO BACKEND
# =====================================================
#
# Esta rota recebe mensagens do widget de atendimento.
# Neste primeiro momento ela apenas valida a mensagem
# e confirma que frontend e backend estão se comunicando.
# IA, histórico, CRM e automações serão ligados nas
# próximas etapas sem alterar esta URL pública.
#

@app.route(
    "/api/sac",
    methods=["POST"]
)
def sac_maranhao():
    dados = request.get_json(silent=True) or {}

    mensagem = str(dados.get("mensagem", "")).strip()
    origem = str(dados.get("origem", "site")).strip()
    tipo = str(dados.get("tipo", "geral")).strip()

    if not mensagem:
        return jsonify({
            "success": False,
            "error": "Mensagem obrigatória."
        }), 400

    # -------------------------------------------------
    # RESPOSTA INSTANTÂNEA PARA DÚVIDAS SIMPLES
    # -------------------------------------------------

    resposta_rapida = resposta_rapida_maranhao(
        mensagem
    )

    if resposta_rapida:

        atendimento_id = (
            "SAC-"
            + uuid.uuid4().hex[:12].upper()
        )

        try:
            salvar_atendimento_sac(
                atendimento_id=atendimento_id,
                mensagem=mensagem,
                resposta=resposta_rapida,
                origem=origem,
                tipo=tipo,
                codigo_pedido=None,
                cliente_email=None
            )
        except Exception as erro:
            print(
                "ERRO SALVAR SAC RÁPIDO:",
                erro
            )

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": resposta_rapida,
            "origem": origem,
            "tipo": tipo,
            "modo": "resposta_rapida"
        }), 200



    # -------------------------------------------------
    # IDENTIFICA NÚMERO DO PEDIDO NA MENSAGEM
    # -------------------------------------------------

    pedido_encontrado = None

    match_pedido = re.search(
        r"MAR-[A-Z0-9-]+",
        mensagem.upper()
    )

    print(
    "DEBUG PEDIDO SAC:",
    match_pedido.group(0) if match_pedido else "NENHUM"
    )

    if match_pedido:
        codigo_pedido = match_pedido.group(0)

        try:
            pedido_encontrado = buscar_pedido_postgres(
                codigo_pedido
            )

        except Exception as erro:
            print(
                "ERRO SAC CONSULTAR PEDIDO:",
                erro
            )

    # -------------------------------------------------
    # IDENTIFICADOR DO ATENDIMENTO
    # -------------------------------------------------

    atendimento_id = "SAC-" + uuid.uuid4().hex[:12].upper()

    print("=" * 60)
    print("SAC MARANHÃO CORDIAL")
    print("ATENDIMENTO:", atendimento_id)
    print("ORIGEM:", origem)
    print("TIPO:", tipo)
    print("MENSAGEM:", mensagem)
    print("=" * 60)

    # -------------------------------------------------
    # RESPOSTA RÁPIDA PARA PEDIDO ENCONTRADO
    # -------------------------------------------------

    if match_pedido and pedido_encontrado:

        # -----------------------------------------
        # VALIDA E-MAIL DO CLIENTE
        # -----------------------------------------

        email_informado = re.search(
            r"[\w\.-]+@[\w\.-]+\.\w+",
            mensagem.lower()
        )

        if not email_informado:
            return jsonify({
                "success": True,
                "atendimento_id": atendimento_id,
                "resposta": (
                    "Encontrei esse número de pedido. "
                    "Informe o e-mail utilizado na compra para continuar."
                ),
                "origem": origem,
                "tipo": tipo,
                "aguardando_email": True
            }), 200

        email_cliente = (
            pedido_encontrado.get("cliente_email")
            or ""
        ).strip().lower()

        if email_informado.group(0) != email_cliente:
            return jsonify({
                "success": True,
                "atendimento_id": atendimento_id,
                "resposta": (
                    "O e-mail informado não corresponde a esse pedido. "
                    "Confira os dados e tente novamente."
                ),
                "origem": origem,
                "tipo": tipo
            }), 200

        # -----------------------------------------
        # E-MAIL CONFIRMADO → EXIBE STATUS
        # -----------------------------------------

        status_pedido = str(
            pedido_encontrado.get("status")
            or "sem_status"
        ).replace("_", " ")

        status_entrega = str(
            pedido_encontrado.get("status_entrega")
            or ""
        ).replace("_", " ")

        codigo_rastreio = (
            pedido_encontrado.get("tracking_code")
        )

        partes = [
            f"Encontrei o pedido {codigo_pedido}.",
            f"Status: {status_pedido}."
        ]

        if status_entrega:
            partes.append(
                f"Entrega: {status_entrega}."
            )

        if codigo_rastreio:
            partes.append(
                f"Rastreio: {codigo_rastreio}."
            )

        texto_resposta = " ".join(partes)

        try:
            salvar_atendimento_sac(
                atendimento_id=atendimento_id,
                mensagem=mensagem,
                resposta=texto_resposta,
                origem=origem,
                tipo=tipo,
                codigo_pedido=codigo_pedido,
                cliente_email=email_cliente
            )
        except Exception as erro:
            print("ERRO SALVAR SAC:", erro)

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": texto_resposta,
            "origem": origem,
            "tipo": tipo,
            "pedido": codigo_pedido
        }), 200


    # -------------------------------------------------
    # PEDIDO INFORMADO, MAS NÃO ENCONTRADO
    # -------------------------------------------------

    if match_pedido and not pedido_encontrado:

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": (
                f"Não encontrei o pedido {codigo_pedido}. "
                "Confira o número e tente novamente."
            ),
            "origem": origem,
            "tipo": tipo
        }), 200

    if not openai_client:
        texto_resposta = (
            "Recebemos sua mensagem. "
            "O atendimento inteligente está temporariamente indisponível."
        )
    else:
        try:
            resposta_ia = openai_client.responses.create(
                model="gpt-5-mini",
                instructions=(
                    "Você é o atendimento digital oficial do Maranhão Cordial. "
                    + CONTEXTO_MARANHAO
                    + CONTEXTO_EMPRESARIAL_INTERNO
                    + " Responda em português do Brasil com no máximo 2 frases curtas. "
                    "Seja cordial, elegante e objetivo. "
                    "Nunca invente política, prazo, preço, troca, reembolso, envio ou cancelamento. "
                    "Nunca peça CPF, cartão, senha, dados bancários ou documentos pessoais. "
                    "Se houver problema com compra feita no site oficial, peça apenas o número do pedido. "
                    "O Maranhão Cordial não possui lojas físicas. "
                    "Se a compra foi feita fora do site maranhaocordial.com.br, informe que qualquer reclamação "
                    "ou solução deve ser tratada diretamente com o distribuidor ou estabelecimento onde a compra foi feita. "
                    "Faça no máximo uma pergunta por resposta. "
                    "Evite repetir a mesma estrutura, abertura ou conclusão em respostas semelhantes. "
                    "Varie naturalmente o vocabulário sem alterar os fatos oficiais da marca. "
                    "Escolha o foco da resposta de acordo com a necessidade demonstrada pelo cliente. "
                    "Quando pertinente, varie entre eficiência operacional, padronização, experiência do cliente, "
                    "aplicações gastronômicas, hospitalidade, coquetelaria, minibar, eventos, identidade cultural "
                    "e experiência de marca. "
                    "Não tente mencionar todos esses aspectos na mesma resposta. "
                    "Não use sempre expressões como 'agrega valor', 'experiência sensorial' ou 'padronização'. "
                    "Não termine todas as respostas oferecendo atendimento B2B. "
                    "Só faça convite comercial ou próxima pergunta quando isso realmente ajudar a avançar a conversa. "
                    "Quando o cliente já tiver informado seu segmento, adapte a resposta especificamente àquele segmento."
                ),
                input=mensagem,
                reasoning={
                    "effort": "low"
                },
                max_output_tokens=800
            )

            texto_resposta = (resposta_ia.output_text or "").strip()
            if not texto_resposta:
                texto_resposta = "Como posso ajudar com seu pedido?"

        except Exception as erro:
            print("ERRO IA SAC MARANHÃO:", erro)
            texto_resposta = (
                "Recebemos sua mensagem. "
                "O atendimento inteligente está temporariamente indisponível."
            )

    try:
        salvar_atendimento_sac(
            atendimento_id=atendimento_id,
            mensagem=mensagem,
            resposta=texto_resposta,
            origem=origem,
            tipo=tipo,
            codigo_pedido=(
                codigo_pedido
                if match_pedido
                else None
            ),
            cliente_email=None
        )
    except Exception as erro:
        print("ERRO SALVAR SAC:", erro)

    return jsonify({
        "success": True,
        "atendimento_id": atendimento_id,
        "resposta": texto_resposta,
        "origem": origem,
        "tipo": tipo
    }), 200


@app.route("/admin")
@app.route("/admin.html")
def admin():
    return renderizar_html("admin.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204




# =====================================================
# FUNÇÕES COMUNS — PAGAMENTO / C6 / LOGÍSTICA
# =====================================================

def finalizar_pedido_pago(codigo, origem_pagamento):
    """
    Centraliza a liberação operacional do pedido.
    Pagar.me e C6 chamam exatamente a mesma função.
    """

    pedido = PEDIDOS.get(codigo)

    if not pedido:
        return False

    # Idempotência: webhook repetido não dispara tudo de novo.
    if pedido.get("status") == "pago":
        return True

    pedido["status"] = "pago"
    pedido["payment_origin"] = origem_pagamento

    pedido.setdefault("delivery", {})
    pedido["delivery"]["status"] = "aguardando_despacho"

    try:
        salvar_pedido_postgres(pedido)
    except Exception as erro:
        print("ERRO PERSISTIR PEDIDO PAGO:", erro)

    emit(
        "to_admin",
        pedido,
        broadcast=True
    )

    print(
        f"✓ PEDIDO PAGO — {codigo} — origem: {origem_pagamento}"
    )

    return True

# =====================================================
# C6 BANK — SANDBOX
# =====================================================

C6_CLIENT_ID = os.getenv("C6_CLIENT_ID")
C6_CLIENT_SECRET = os.getenv("C6_CLIENT_SECRET")
C6_PIX_KEY = os.getenv("C6_PIX_KEY")

C6_AUTH_URL = os.getenv(
    "C6_AUTH_URL",
    "https://baas-api-sandbox.c6bank.info/v1/auth/"
)

C6_PIX_BASE_URL = os.getenv(
    "C6_PIX_BASE_URL",
    "https://baas-api-sandbox.c6bank.info/v2/pix"
)
C6_CERT_PATH = os.getenv(
    "C6_CERT_PATH",
    "/etc/secrets/C6_sandbox.crt"
)

C6_KEY_PATH = os.getenv(
    "C6_KEY_PATH",
    "/etc/secrets/C6_sandbox.key"
)


# =====================================================
# C6 — CERTIFICADO mTLS
# =====================================================

def c6_cert():

    if not C6_CERT_PATH or not C6_KEY_PATH:
        raise RuntimeError(
            "Certificado C6 não configurado."
        )

    return (
        C6_CERT_PATH,
        C6_KEY_PATH
    )


# =====================================================
# C6 — AUTENTICAÇÃO
# =====================================================

def get_c6_access_token():

    faltando = []

    if not C6_CLIENT_ID:
        faltando.append("C6_CLIENT_ID")

    if not C6_CLIENT_SECRET:
        faltando.append("C6_CLIENT_SECRET")

    if not C6_PIX_KEY:
        faltando.append("C6_PIX_KEY")

    if faltando:
        raise RuntimeError(
            "C6 não configurado: "
            + ", ".join(faltando)
        )

    resposta = requests.post(
        C6_AUTH_URL,

        data={
            "client_id":
                C6_CLIENT_ID,

            "client_secret":
                C6_CLIENT_SECRET,

            "grant_type":
                "client_credentials"
        },

        cert=c6_cert(),

        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },

        timeout=30
    )

    if not resposta.ok:

        print(
            "ERRO AUTENTICAÇÃO C6:",
            resposta.status_code,
            resposta.text
        )

        resposta.raise_for_status()

    dados = resposta.json()

    access_token = dados.get(
        "access_token"
    )

    if not access_token:
        raise RuntimeError(
            "C6 não retornou access_token."
        )

    return access_token


# =====================================================
# C6 — HEADERS
# =====================================================

def c6_headers():

    return {

        "Authorization":
            f"Bearer {get_c6_access_token()}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",

        "User-Agent":
            "maranhao-cordial/1.0"
    }


# =====================================================
# C6 — CONSULTAR COBRANÇA PIX
# =====================================================

def consultar_pix_c6(txid):

    if not txid:
        raise RuntimeError(
            "TXID obrigatório."
        )

    url = (
        f"{C6_PIX_BASE_URL}"
        f"/cob/{txid}"
    )

    resposta = requests.get(
        url,

        headers=c6_headers(),

        cert=c6_cert(),

        timeout=30
    )

    if not resposta.ok:

        print(
            "ERRO CONSULTA PIX C6:",
            resposta.status_code,
            resposta.text
        )

        resposta.raise_for_status()

    return resposta.json()


# =====================================================
# C6 — STATUS DA INTEGRAÇÃO
# =====================================================

@app.route(
    "/api/c6/status",
    methods=["GET"]
)
def status_c6():

    return jsonify({

        "integration":
            "C6 Bank",

        "environment":
            "sandbox",

        "credentials_configured":
            bool(
                C6_CLIENT_ID
                and C6_CLIENT_SECRET
            ),

        "pix_key_configured":
            bool(C6_PIX_KEY),

        "mtls_configured":
            bool(
                C6_CERT_PATH
                and C6_KEY_PATH
            ),

        "auth_url":
            C6_AUTH_URL,

        "pix_base_url":
            C6_PIX_BASE_URL,

        "ready":
            bool(
                C6_CLIENT_ID
                and C6_CLIENT_SECRET
                and C6_PIX_KEY
                and C6_CERT_PATH
                and C6_KEY_PATH
            )
    })


# =====================================================
# C6 BANK — CRIAR COBRANÇA PIX
# =====================================================

@app.route(
    "/api/c6/pix/checkout",
    methods=["POST"]
)
def criar_checkout_c6():

    dados = request.get_json(
        silent=True
    ) or {}

    # ---------------------------------------------
    # QUANTIDADE
    # ---------------------------------------------

    try:

        quantidade = int(
            dados.get(
                "quantidade",
                1
            )
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "error":
                "Quantidade inválida."
        }), 400


    if quantidade < 1:

        return jsonify({
            "error":
                "Quantidade inválida."
        }), 400


    # ---------------------------------------------
    # ENDEREÇO
    # ---------------------------------------------

    endereco = str(
        dados.get(
            "endereco",
            ""
        )
    ).strip()


    if not endereco:

        return jsonify({
            "error":
                "Endereço obrigatório."
        }), 400


    # ---------------------------------------------
    # E-MAIL DO CLIENTE
    # ---------------------------------------------

    cliente_email = str(
        dados.get(
            "cliente_email",
            ""
        )
    ).strip().lower()

    if not cliente_email:

        return jsonify({
            "error":
                "E-mail obrigatório."
        }), 400

    # ---------------------------------------------
    # DADOS DO CLIENTE
    # ---------------------------------------------

    cliente_nome = str(
        dados.get(
            "cliente_nome",
            ""
        )
    ).strip()

    cliente_whatsapp = str(
        dados.get(
            "cliente_whatsapp",
            ""
        )
    ).strip()

    
    # ---------------------------------------------
    # CRIA PEDIDO
    # ---------------------------------------------

    codigo = (
        "MAR-"
        + uuid.uuid4().hex[:10].upper()
    )


    # PRECO_UNITARIO está em centavos
    valor_total_centavos = (
        PRECO_UNITARIO
        * quantidade
    )


    # API PIX C6 recebe valor em reais:
    # exemplo: "59.90"
    valor_total_reais = (
        f"{valor_total_centavos / 100:.2f}"
    )


    pedido = {

        "code":
            codigo,

        "quantity":
            quantidade,

        "address":
            endereco,

         "cliente_nome":
            cliente_nome,

        "cliente_email":
            cliente_email,

        "cliente_whatsapp":
            cliente_whatsapp, 

        "amount":
            valor_total_centavos,

        "status":
            "aguardando_pagamento",

        "payment_origin":
            "c6",

        "c6_txid":
            None,

        "c6_location":
            None,

        "c6_status":
            None,

        "pagarme_id":
            None,


        # -----------------------------------------
        # FISCAL
        # -----------------------------------------

        "fiscal": {

            "status":
                "aguardando_definicao_fiscal",

            "icms_st": {

                "aplicavel":
                    None,

                "responsavel":
                    None,

                "recolhido_na_origem":
                    None
            }
        },


        # -----------------------------------------
        # LOGÍSTICA
        # -----------------------------------------

        "delivery": {

            "provider":
                None,

            "status":
                "aguardando_pagamento",

            "tracking_code":
                None,

            "tracking_url":
                None
        }
    }


    PEDIDOS[codigo] = pedido
    salvar_pedido_postgres(pedido)


    # ---------------------------------------------
    # PAYLOAD PIX C6
    # ---------------------------------------------

    payload = {

        "calendario": {

            # 1 hora
            "expiracao":
                3600
        },

        "valor": {

            "original":
                valor_total_reais,

            "modalidadeAlteracao":
                0
        },

        "chave":
            C6_PIX_KEY,

        "solicitacaoPagador":
            f"Maranhão Cordial - {codigo}",


        # Informações úteis para correlação
        "infoAdicionais": [

            {
                "nome":
                    "pedido",

                "valor":
                    codigo
            },

            {
                "nome":
                    "quantidade",

                "valor":
                    str(quantidade)
            }
        ]
    }


    # ---------------------------------------------
    # ENVIA AO C6
    # ---------------------------------------------

    try:

        txid = uuid.uuid4().hex

        resposta = requests.put(

            f"{C6_PIX_BASE_URL}/cob/{txid}",

            json=payload,

            headers=c6_headers(),

            cert=c6_cert(),

            timeout=30
        )


        try:

            dados_c6 = (
                resposta.json()
            )

        except ValueError:

            dados_c6 = {
                "raw":
                    resposta.text
            }


        if resposta.status_code != 201:

            PEDIDOS[codigo][
                "status"
            ] = "erro_pagamento"


            print(
                "ERRO CRIAR PIX C6:",
                resposta.status_code,
                dados_c6
            )


            return jsonify({

                "success":
                    False,

                "error":
                    "C6 recusou a criação da cobrança PIX.",

                "details":
                    dados_c6

            }), resposta.status_code


        # -----------------------------------------
        # COBRANÇA CRIADA
        # -----------------------------------------

        txid = dados_c6.get(
            "txid"
        )

        location = dados_c6.get(
            "location"
        )

        status = dados_c6.get(
            "status"
        )


        PEDIDOS[codigo][
            "c6_txid"
        ] = txid


        PEDIDOS[codigo][
            "c6_location"
        ] = location


        PEDIDOS[codigo][
            "c6_status"
        ] = status

        salvar_pedido_postgres(PEDIDOS[codigo])

        print("=" * 60)

        print(
            f"✓ PIX C6 CRIADO — {codigo}"
        )

        print(
            "TXID:",
            txid
        )

        print(
            "STATUS:",
            status
        )

        print("=" * 60)


        return jsonify({

            "success":
                True,

            "order_code":
                codigo,

            "amount":
                valor_total_reais,

            "c6_txid":
                txid,

            "status":
                status,

            "location":
                location

        }), 201


    except requests.RequestException as erro:

        PEDIDOS[codigo][
            "status"
        ] = "erro_comunicacao_c6"


        print(
            "ERRO DE COMUNICAÇÃO C6:",
            erro
        )


        return jsonify({

            "success":
                False,

            "error":
                "Não foi possível comunicar com o C6 Bank."

        }), 502


    except Exception as erro:

        PEDIDOS[codigo][
            "status"
        ] = "erro_interno_c6"


        print(
            "ERRO INTERNO C6:",
            erro
        )


        return jsonify({

            "success":
                False,

            "error":
                "Erro interno na integração C6."

        }), 500


# =====================================================
# C6 — CONSULTAR PEDIDO PIX
# =====================================================

@app.route(
    "/api/c6/pix/<txid>",
    methods=["GET"]
)
def consultar_cobranca_c6(txid):

    try:

        dados_c6 = (
            consultar_pix_c6(
                txid
            )
        )


        # -----------------------------------------
        # LOCALIZA PEDIDO PELO TXID
        # -----------------------------------------

        codigo_encontrado = None

        for codigo, pedido in PEDIDOS.items():

            if (
                pedido.get("c6_txid")
                == txid
            ):

                codigo_encontrado = (
                    codigo
                )

                break


        status = str(
            dados_c6.get(
                "status",
                ""
            )
        ).upper()


        # -----------------------------------------
        # ATUALIZA PEDIDO
        # -----------------------------------------

        if codigo_encontrado:

            pedido = PEDIDOS[
                codigo_encontrado
            ]

            pedido[
                "c6_status"
            ] = status


            # Cobrança PIX concluída = paga
            if status == "CONCLUIDA":

                finalizar_pedido_pago(
                    codigo_encontrado,
                    "c6"
                )


        return jsonify({

            "success":
                True,

            "order_code":
                codigo_encontrado,

            "status":
                status,

            "c6":
                dados_c6

        })


    except requests.HTTPError as erro:

        return jsonify({

            "success":
                False,

            "error":
                "C6 recusou a consulta.",

            "details":
                str(erro)

        }), 502


    except Exception as erro:

        print(
            "ERRO CONSULTA C6:",
            erro
        )

        return jsonify({

            "success":
                False,

            "error":
                "Não foi possível consultar a cobrança."

        }), 500


# =====================================================
# C6 — WEBHOOK PIX
# =====================================================

@app.route(
    "/webhooks/c6",
    methods=["POST"]
)
def webhook_c6():

    evento = request.get_json(
        silent=True
    ) or {}


    print("=" * 60)
    print("WEBHOOK C6 PIX")
    print(evento)
    print("=" * 60)


    # O webhook PIX pode trazer txid diretamente.
    txid = evento.get(
        "txid"
    )


    # Alguns formatos podem encapsular
    # os PIX recebidos em uma lista.
    if not txid:

        pix_lista = evento.get(
            "pix"
        )

        if (
            isinstance(
                pix_lista,
                list
            )
            and pix_lista
        ):

            txid = (
                pix_lista[0]
                .get("txid")
            )


    if not txid:

        print(
            "Webhook C6 sem TXID."
        )

        return "", 200


    # ---------------------------------------------
    # LOCALIZA PEDIDO
    # ---------------------------------------------

    codigo = None

    for cod, pedido in PEDIDOS.items():

        if (
            pedido.get("c6_txid")
            == txid
        ):

            codigo = cod
            break


    if not codigo:

        print(
            "Webhook C6 sem pedido correlacionado.",
            txid
        )

        return "", 200


    # ---------------------------------------------
    # CONFIRMA DIRETAMENTE NO C6
    # ---------------------------------------------

    try:

        consulta = consultar_pix_c6(
            txid
        )

        status = str(
            consulta.get(
                "status",
                ""
            )
        ).upper()


        PEDIDOS[codigo][
            "c6_status"
        ] = status


        PEDIDOS[codigo][
            "c6_last_query"
        ] = consulta


        # Só libera operação após
        # confirmação direta no banco.
        if status == "CONCLUIDA":

            finalizar_pedido_pago(
                codigo,
                "c6"
            )


    except Exception as erro:

        print(
            "Falha ao confirmar PIX no C6:",
            erro
        )


    return "", 200
# =====================================================
# LOGÍSTICA — WEBHOOK GENÉRICO (FUTURA TRANSPORTADORA)
# =====================================================

@app.route("/webhooks/logistica", methods=["POST"])
def webhook_logistica():

    if LOGISTICA_WEBHOOK_TOKEN:
        esperado = f"Bearer {LOGISTICA_WEBHOOK_TOKEN}"
        if request.headers.get("Authorization") != esperado:
            return jsonify({"error": "Não autorizado."}), 401

    evento = request.get_json(silent=True) or {}
    codigo = evento.get("order_code") or evento.get("code")

    if not codigo or codigo not in PEDIDOS:
        return jsonify({"error": "Pedido não encontrado."}), 404

    pedido = PEDIDOS[codigo]
    pedido.setdefault("delivery", {})

    for campo in ("provider", "status", "tracking_code"):
        if campo in evento:
            pedido["delivery"][campo] = evento[campo]

    emit("to_admin", pedido, broadcast=True)

    return jsonify({"received": True}), 200


# =====================================================
# PAGAR.ME — CRIAR CHECKOUT
# =====================================================

@app.route("/api/pagarme/checkout", methods=["POST"])
def criar_checkout():

    if not PAGARME_SECRET_KEY:
        return jsonify({
            "error": "PAGARME_SECRET_KEY não configurada."
        }), 500

    dados = request.get_json(
        silent=True
    ) or {}

    quantidade = int(
        dados.get("quantidade", 1)
    )

    endereco = str(
        dados.get("endereco", "")
    ).strip()

    if quantidade < 1:
        return jsonify({
            "error": "Quantidade inválida."
        }), 400

    if not endereco:
        return jsonify({
            "error": "Endereço obrigatório."
        }), 400

    # -------------------------------------------------
    # CRIA PEDIDO INTERNO
    # -------------------------------------------------

    codigo = (
        "MAR-"
        + uuid.uuid4().hex[:10].upper()
    )

    valor_total = (
        PRECO_UNITARIO * quantidade
    )

    pedido = {

        "code": codigo,

        "quantity": quantidade,

        "address": endereco,

        "amount": valor_total,

        "status": "aguardando_pagamento",

        "payment_origin": "pagarme",

        "pagarme_id": None,

        "c6_txid": None,

        "fiscal": {
            "status": "aguardando_definicao_fiscal",
            "icms_st": {
                "aplicavel": None,
                "responsavel": None,
                "recolhido_na_origem": None
            }
        },

        "delivery": {
            "provider": None,
            "status": "aguardando_pagamento",
            "tracking_code": None,
            "tracking_url": None
        }

    }

    PEDIDOS[codigo] = pedido
    salvar_pedido_postgres(pedido)


    # -------------------------------------------------
    # CRIA CHECKOUT PAGAR.ME
    # -------------------------------------------------

    payload = {

        "is_building": False,

        "name": f"Maranhão - {codigo}",

        "order_code": codigo,

        "type": "order",

        "max_paid_sessions": 1,

        "payment_settings": {

            "accepted_payment_methods": [
                "credit_card",
                "pix"
            ],

            "credit_card_settings": {

                "operation_type":
                    "auth_and_capture",

                "installments_setup": {

                    "interest_type":
                        "simple"

                }

            }

        },

        "cart_settings": {

            "items": [

                {

                    "amount":
                        PRECO_UNITARIO,

                    "name":
                        "Maranhão Cordial",

                    "description":
                        "Concentrado premium de guaraná",

                    "default_quantity":
                        quantidade

                }

            ]

        }

    }


    # -------------------------------------------------
    # ENVIA PARA PAGAR.ME
    # -------------------------------------------------

    try:

        resposta = requests.post(

            f"{PAGARME_BASE_URL}/paymentlinks",

            auth=(
                PAGARME_SECRET_KEY,
                ""
            ),

            headers={
                "User-Agent":
                    "maranhao-cordial/1.0",
                "Content-Type":
                    "application/json"
            },

            json=payload,

            timeout=20

        )


        dados_pagarme = resposta.json()


        if not resposta.ok:

            print(
                "ERRO PAGAR.ME:",
                dados_pagarme
            )

            PEDIDOS[codigo]["status"] = \
                "erro_pagamento"

            return jsonify({

                "error":
                    "Erro ao criar pagamento.",

                "details":
                    dados_pagarme

            }), 400


        # -------------------------------------------------
        # SALVA ID DO PAGAR.ME
        # -------------------------------------------------

        PEDIDOS[codigo][
            "pagarme_id"
        ] = dados_pagarme.get("id")

        salvar_pedido_postgres(PEDIDOS[codigo])

        checkout_url = \
            dados_pagarme.get("url")


        return jsonify({

            "success": True,

            "order_code":
                codigo,

            "checkout_url":
                checkout_url

        })


    except Exception as erro:

        print(
            "ERRO DE COMUNICAÇÃO:",
            erro
        )

        return jsonify({

            "error":
                "Não foi possível comunicar com o Pagar.me."

        }), 500


# =====================================================
# WEBHOOK PAGAR.ME
# =====================================================

@app.route(
    "/webhooks/pagarme",
    methods=["POST"]
)
def webhook_pagarme():

    evento = request.get_json(
        silent=True
    ) or {}

    print("=" * 60)
    print("WEBHOOK PAGAR.ME")
    print(evento)
    print("=" * 60)


    tipo = evento.get("type")

    dados = evento.get(
        "data",
        {}
    )


    # =================================================
    # PAGAMENTO APROVADO
    # =================================================

    if tipo == "order.paid":

        codigo = dados.get(
            "code"
        )

        if codigo in PEDIDOS:
            finalizar_pedido_pago(codigo, "pagarme")


    # =================================================
    # PAGAMENTO RECUSADO
    # =================================================

    elif tipo == "order.payment_failed":

        codigo = dados.get(
            "code"
        )

        if codigo in PEDIDOS:

            PEDIDOS[codigo][
                "status"
            ] = "pagamento_recusado"

            print(
                f"✕ PEDIDO {codigo} "
                "PAGAMENTO RECUSADO"
            )


    return "", 200


# =====================================================
# LISTAGEM DE PEDIDOS — POSTGRESQL
# =====================================================

def listar_pedidos_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_status,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        criado_em,
                        atualizado_em
                    FROM pedidos
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "codigo": linha[0],
                        "cliente_nome": linha[1],
                        "cliente_email": linha[2],
                        "cliente_whatsapp": linha[3],
                        "quantidade": linha[4],
                        "valor_centavos": linha[5],
                        "status": linha[6],
                        "payment_origin": linha[7],
                        "c6_status": linha[8],
                        "transportadora": linha[9],
                        "status_entrega": linha[10],
                        "tracking_code": linha[11],
                        "criado_em": linha[12].isoformat() if linha[12] else None,
                        "atualizado_em": linha[13].isoformat() if linha[13] else None
                    }
                    for linha in linhas
                ]

    finally:
        conn.close()


def listar_atendimentos_sac_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        atendimento_id,
                        mensagem,
                        resposta,
                        origem,
                        tipo,
                        codigo_pedido,
                        cliente_email,
                        criado_em
                    FROM atendimentos_sac
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "atendimento_id": linha[0],
                        "mensagem": linha[1],
                        "resposta": linha[2],
                        "origem": linha[3],
                        "tipo": linha[4],
                        "codigo_pedido": linha[5],
                        "cliente_email": linha[6],
                        "criado_em": linha[7].isoformat() if linha[7] else None
                    }
                    for linha in linhas
                ]
    finally:
        conn.close()


@app.route(
    "/api/admin/atendimentos",
    methods=["GET"]
)
def admin_listar_atendimentos():

    chave_recebida = request.headers.get("X-Admin-Key")

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        atendimentos = listar_atendimentos_sac_postgres()

        return jsonify({
            "success": True,
            "total": len(atendimentos),
            "atendimentos": atendimentos
        }), 200

    except Exception as erro:
        print("ERRO ADMIN LISTAR ATENDIMENTOS:", erro)

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os atendimentos."
        }), 500


def listar_b2b_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        empresa,
                        cnpj,
                        segmento,
                        responsavel,
                        whatsapp,
                        email,
                        cidade,
                        interesse,
                        mensagem,
                        status,
                        criado_em
                    FROM cadastros_profissionais
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "empresa": linha[0],
                        "cnpj": linha[1],
                        "segmento": linha[2],
                        "responsavel": linha[3],
                        "whatsapp": linha[4],
                        "email": linha[5],
                        "cidade": linha[6],
                        "interesse": linha[7],
                        "mensagem": linha[8],
                        "status": linha[9],
                        "criado_em": linha[10].isoformat() if linha[10] else None
                    }
                    for linha in linhas
                ]
    finally:
        conn.close()


@app.route(
    "/api/admin/b2b",
    methods=["GET"]
)
def admin_listar_b2b():

    chave_recebida = request.headers.get("X-Admin-Key")

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        cadastros = listar_b2b_postgres()

        return jsonify({
            "success": True,
            "total": len(cadastros),
            "cadastros": cadastros
        }), 200

    except Exception as erro:
        print("ERRO ADMIN LISTAR B2B:", erro)

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os cadastros B2B."
        }), 500


def listar_degustacoes_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        empresa,
                        cnpj,
                        segmento,
                        cidade,
                        responsavel,
                        whatsapp,
                        email,
                        mensagem,
                        status,
                        criado_em
                    FROM solicitacoes_degustacao
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "empresa": linha[0],
                        "cnpj": linha[1],
                        "segmento": linha[2],
                        "cidade": linha[3],
                        "responsavel": linha[4],
                        "whatsapp": linha[5],
                        "email": linha[6],
                        "mensagem": linha[7],
                        "status": linha[8],
                        "criado_em": linha[9].isoformat()
                            if linha[9]
                            else None
                    }
                    for linha in linhas
                ]

    finally:
        conn.close()


@app.route(
    "/api/admin/degustacoes",
    methods=["GET"]
)
def admin_listar_degustacoes():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        degustacoes = listar_degustacoes_postgres()

        return jsonify({
            "success": True,
            "total": len(degustacoes),
            "degustacoes": degustacoes
        }), 200

    except Exception as erro:
        print(
            "ERRO ADMIN LISTAR DEGUSTAÇÕES:",
            erro
        )

        return jsonify({
            "success": False,
            "error": "Não foi possível listar as degustações."
        }), 500


# =====================================================
# ADMIN — LISTAR PEDIDOS
# =====================================================

@app.route(
    "/api/admin/pedidos",
    methods=["GET"]
)
def admin_listar_pedidos():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        pedidos = listar_pedidos_postgres()

        return jsonify({
            "success": True,
            "total": len(pedidos),
            "pedidos": pedidos
        }), 200

    except Exception as erro:
        print(
            "ERRO ADMIN LISTAR PEDIDOS:",
            erro
        )

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os pedidos."
        }), 500


# =====================================================
# CONSULTAR PEDIDO
# =====================================================

@app.route(
    "/api/pedido/<codigo>",
    methods=["GET"]
)
def consultar_pedido(codigo):

    try:
        pedido = buscar_pedido_postgres(
            codigo.strip()
        )

    except Exception as erro:
        print(
            "ERRO CONSULTAR PEDIDO:",
            erro
        )
        pedido = None

    if not pedido:
        pedido = PEDIDOS.get(
            codigo
        )

    if not pedido:
        return jsonify({
            "error": "Pedido não encontrado."
        }), 404

    return jsonify(
        pedido
    )


# =====================================================
# WEBSOCKET
# =====================================================

@socketio.on(
    "new_ancestral_order"
)
def handle_new_order(payload):

    print(
        "Evento recebido:",
        payload
    )

    # ATENÇÃO:
    # Não liberamos produção/entrega
    # aqui.
    #
    # O pedido só deve ser liberado
    # após o webhook order.paid.


# =====================================================
# ROTA DE ARQUIVOS
# =====================================================

@app.route("/api/openai/status", methods=["GET"])
def openai_status():
    return jsonify({
        "openai_configured": bool(OPENAI_API_KEY)
    })

@app.route("/api/openai/teste", methods=["GET"])
def openai_teste():

    try:

        resposta = openai_client.responses.create(
            model="gpt-5-mini",
            input="Responda apenas: Maranhão IA funcionando."
        )

        return jsonify({
            "success": True,
            "resposta": resposta.output_text
        }), 200

    except Exception as erro:

        print(
            "ERRO TESTE OPENAI:",
            erro
        )

        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500

def buscar_pedido_postgres(codigo):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        cpf_cnpj,
                        endereco,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_txid,
                        c6_status,
                        pagarme_id,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        tracking_url,
                        criado_em,
                        atualizado_em
                    FROM pedidos
                    WHERE codigo = %s
                    LIMIT 1
                """, (codigo,))

                linha = cur.fetchone()

                if not linha:
                    return None

                return {
                    "codigo": linha[0],
                    "cliente_nome": linha[1],
                    "cliente_email": linha[2],
                    "cliente_whatsapp": linha[3],
                    "cpf_cnpj": linha[4],
                    "endereco": linha[5],
                    "quantidade": linha[6],
                    "valor_centavos": linha[7],
                    "status": linha[8],
                    "payment_origin": linha[9],
                    "c6_txid": linha[10],
                    "c6_status": linha[11],
                    "pagarme_id": linha[12],
                    "transportadora": linha[13],
                    "status_entrega": linha[14],
                    "tracking_code": linha[15],
                    "tracking_url": linha[16],
                    "criado_em": linha[17].isoformat() if linha[17] else None,
                    "atualizado_em": linha[18].isoformat() if linha[18] else None
                }
    finally:
        conn.close()


@app.route("/api/pedidos/teste-postgres", methods=["POST"])
def teste_pedido_postgres():
    codigo = "MAR-TESTE-" + uuid.uuid4().hex[:8].upper()

    pedido_teste = {
        "code": codigo,
        "cliente_nome": "Cliente Teste",
        "cliente_email": "teste@maranhaocordial.com.br",
        "cliente_whatsapp": None,
        "cpf_cnpj": None,
        "address": "Endereço de teste",
        "quantity": 1,
        "amount": 5990,
        "status": "teste",
        "payment_origin": "teste",
        "c6_txid": None,
        "c6_status": None,
        "pagarme_id": None,
        "delivery": {
            "provider": None,
            "status": "teste",
            "tracking_code": None,
            "tracking_url": None
        }
    }

    try:
        salvar_pedido_postgres(pedido_teste)
        return jsonify({
            "success": True,
            "codigo": codigo,
            "mensagem": "Pedido de teste salvo no PostgreSQL."
        }), 201
    except Exception as erro:
        print("ERRO TESTE POSTGRES PEDIDO:", erro)
        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


@app.route(
    "/api/pedidos/<codigo>",
    methods=["GET"]
)
def consultar_pedido_postgres(codigo):
    try:
        pedido = buscar_pedido_postgres(codigo.strip())

        if not pedido:
            return jsonify({
                "success": False,
                "error": "Pedido não encontrado."
            }), 404

        return jsonify({
            "success": True,
            "pedido": pedido
        }), 200

    except Exception as erro:
        print("ERRO CONSULTAR PEDIDO POSTGRES:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível consultar o pedido agora."
        }), 500


@app.route(
    "/<path:filename>"
)
def arquivos(filename):

    return send_from_directory(
        FRONTEND_FOLDER,
        filename
    )


# =====================================================
# ROTAS
# =====================================================

print(
    "\nROTAS REGISTRADAS:\n"
)

for regra in app.url_map.iter_rules():

    print(regra)


# =====================================================
# INICIALIZAÇÃO
# =====================================================


# Cria as tabelas automaticamente quando o serviço inicia.
if DATABASE_URL:
    try:
        inicializar_banco()
        print("✓ BANCO DE LEADS INICIALIZADO")
    except Exception as erro:
        print("ERRO AO INICIALIZAR BANCO DE LEADS:", erro)
else:
    print("AVISO: DATABASE_URL não configurada; formulários B2B não persistirão dados.")


if __name__ == "__main__":

    porta = int(
        os.environ.get(
            "PORT",
            3000
        )
    )

    socketio.run(

        app,

        host="0.0.0.0",

        port=porta,

        debug=True

    )