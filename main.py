from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
import os
import uuid
import requests
from dotenv import load_dotenv

# =====================================================
# CONFIGURAÇÃO
# =====================================================

load_dotenv()

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


@app.route("/administrador")
@app.route("/administrador.html")
def administrador():
    return renderizar_html("administrador.html")


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

    dados = request.get_json(
        silent=True
    ) or {}

    empresa = {
        "id": uuid.uuid4().hex,
        "empresa": dados.get("empresa"),
        "cnpj": dados.get("cnpj"),
        "segmento": dados.get("segmento"),
        "responsavel": dados.get("responsavel"),
        "whatsapp": dados.get("whatsapp"),
        "email": dados.get("email"),
        "status": "novo_lead"
    }

    # futuramente salvar no banco de dados / CRM

    return jsonify({
        "success": True,
        "message": "Cadastro profissional recebido.",
        "empresa_id": empresa["id"]
    })

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

    emit(
        "to_kitchen",
        {
            "code": codigo,
            "quantity": pedido["quantity"]
        },
        broadcast=True
    )

    emit(
        "to_delivery",
        {
            "code": codigo,
            "address": pedido["address"]
        },
        broadcast=True
    )

    emit(
        "to_admin",
        pedido,
        broadcast=True
    )

    print(f"✓ PEDIDO {codigo} PAGO via {origem_pagamento}")
    return True


def c6_cert():
    """Retorna certificado mTLS somente se ambos foram configurados."""
    if C6_CERT_PATH and C6_KEY_PATH:
        return (C6_CERT_PATH, C6_KEY_PATH)
    return None


def get_c6_access_token():
    """
    Obtém token OAuth do C6 usando parâmetros fornecidos pelo banco.
    O formato exato fica configurável para não inventar a especificação.
    """

    faltando = [
        nome for nome, valor in {
            "C6_CLIENT_ID": C6_CLIENT_ID,
            "C6_CLIENT_SECRET": C6_CLIENT_SECRET,
            "C6_TOKEN_URL": C6_TOKEN_URL,
        }.items() if not valor
    ]

    if faltando:
        raise RuntimeError(
            "C6 ainda não configurado: " + ", ".join(faltando)
        )

    data = {"grant_type": "client_credentials"}
    if C6_SCOPE:
        data["scope"] = C6_SCOPE

    auth = None

    if C6_AUTH_MODE == "basic":
        auth = (C6_CLIENT_ID, C6_CLIENT_SECRET)
    elif C6_AUTH_MODE == "body":
        data["client_id"] = C6_CLIENT_ID
        data["client_secret"] = C6_CLIENT_SECRET
    else:
        raise RuntimeError("C6_AUTH_MODE deve ser basic ou body.")

    resposta = requests.post(
        C6_TOKEN_URL,
        data=data,
        auth=auth,
        cert=c6_cert(),
        timeout=20
    )

    resposta.raise_for_status()
    dados = resposta.json()

    token = dados.get("access_token")
    if not token:
        raise RuntimeError("C6 não retornou access_token.")

    return token


def c6_headers():
    return {
        "Authorization": f"Bearer {get_c6_access_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "maranhao-cordial/1.0"
    }


def consultar_pix_c6(txid):
    """Consulta a cobrança diretamente no C6 antes de liberar o pedido."""

    if not C6_PIX_QUERY_URL_TEMPLATE:
        raise RuntimeError("C6_PIX_QUERY_URL_TEMPLATE não configurada.")

    url = C6_PIX_QUERY_URL_TEMPLATE.format(txid=txid)

    resposta = requests.get(
        url,
        headers=c6_headers(),
        cert=c6_cert(),
        timeout=20
    )

    resposta.raise_for_status()
    return resposta.json()


# =====================================================
# C6 BANK — STATUS DA INTEGRAÇÃO
# =====================================================

@app.route("/api/c6/status", methods=["GET"])
def status_c6():
    return jsonify({
        "integration": "C6 Bank",
        "credentials_received": bool(C6_CLIENT_ID and C6_CLIENT_SECRET),
        "token_url_configured": bool(C6_TOKEN_URL),
        "pix_create_configured": bool(C6_PIX_CREATE_URL),
        "pix_query_configured": bool(C6_PIX_QUERY_URL_TEMPLATE),
        "mtls_configured": bool(C6_CERT_PATH and C6_KEY_PATH),
        "ready_for_live_transactions": bool(
            C6_CLIENT_ID
            and C6_CLIENT_SECRET
            and C6_TOKEN_URL
            and C6_PIX_CREATE_URL
            and C6_PIX_QUERY_URL_TEMPLATE
        )
    })


# =====================================================
# C6 BANK — CRIAR COBRANÇA PIX
# =====================================================

@app.route("/api/c6/pix/checkout", methods=["POST"])
def criar_checkout_c6():

    if not C6_PIX_CREATE_URL:
        return jsonify({
            "error": "C6 ainda aguardando endpoint/credenciais de homologação."
        }), 503

    dados = request.get_json(silent=True) or {}

    try:
        quantidade = int(dados.get("quantidade", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida."}), 400

    endereco = str(dados.get("endereco", "")).strip()

    if quantidade < 1:
        return jsonify({"error": "Quantidade inválida."}), 400

    if not endereco:
        return jsonify({"error": "Endereço obrigatório."}), 400

    codigo = "MAR-" + uuid.uuid4().hex[:10].upper()
    valor_total = PRECO_UNITARIO * quantidade

    PEDIDOS[codigo] = {
        "code": codigo,
        "quantity": quantidade,
        "address": endereco,
        "amount": valor_total,
        "status": "aguardando_pagamento",
        "payment_origin": "c6",
        "c6_txid": None,
        "pagarme_id": None,

        # Fiscal: propositalmente não calcula ICMS-ST aqui.
        # A responsabilidade deve ser definida por NCM/UF/operação
        # e pelo arranjo fiscal formal com a fábrica/contabilidade.
        "fiscal": {
            "status": "aguardando_definicao_fiscal",
            "icms_st": {
                "aplicavel": None,
                "responsavel": None,
                "recolhido_na_origem": None
            }
        },

        # Logística preparada para a futura transportadora.
        "delivery": {
            "provider": None,
            "status": "aguardando_pagamento",
            "tracking_code": None
        }
    }

    # Payload BASE. Os nomes dos campos devem ser alinhados à
    # especificação que aparecer no portal C6 após homologação.
    payload = {
        "external_id": codigo,
        "amount": valor_total,
        "description": f"Maranhão Cordial - {quantidade} unidade(s)"
    }

    try:
        resposta = requests.post(
            C6_PIX_CREATE_URL,
            headers=c6_headers(),
            cert=c6_cert(),
            json=payload,
            timeout=20
        )

        dados_c6 = resposta.json() if resposta.content else {}

        if not resposta.ok:
            PEDIDOS[codigo]["status"] = "erro_pagamento"
            return jsonify({
                "error": "C6 recusou a criação da cobrança.",
                "details": dados_c6
            }), resposta.status_code

        # Ajustaremos estes campos quando o C6 fornecer o schema real.
        txid = (
            dados_c6.get("txid")
            or dados_c6.get("id")
            or dados_c6.get("transaction_id")
        )

        PEDIDOS[codigo]["c6_txid"] = txid

        return jsonify({
            "success": True,
            "order_code": codigo,
            "c6_txid": txid,
            "c6": dados_c6
        })

    except requests.RequestException as erro:
        PEDIDOS[codigo]["status"] = "erro_comunicacao_c6"
        print("ERRO C6:", erro)
        return jsonify({
            "error": "Não foi possível comunicar com o C6 Bank."
        }), 502


# =====================================================
# C6 BANK — WEBHOOK
# =====================================================

@app.route("/webhooks/c6", methods=["POST"])
def webhook_c6():
    """
    Recebe o aviso do C6, mas só libera o pedido depois de
    consultar a cobrança diretamente na API do banco.
    """

    evento = request.get_json(silent=True) or {}

    print("=" * 60)
    print("WEBHOOK C6")
    print(evento)
    print("=" * 60)

    # O schema exato do webhook será informado pelo C6.
    codigo = (
        evento.get("external_id")
        or evento.get("order_code")
        or evento.get("code")
    )

    txid = (
        evento.get("txid")
        or evento.get("id")
        or evento.get("transaction_id")
    )

    if not codigo:
        # Tenta localizar pelo txid já salvo.
        for cod, pedido in PEDIDOS.items():
            if txid and pedido.get("c6_txid") == txid:
                codigo = cod
                break

    if not codigo or codigo not in PEDIDOS:
        # Retorna 200 para evitar loop agressivo de reenvio,
        # mas registra que o evento não foi correlacionado.
        print("Webhook C6 sem pedido correlacionado.")
        return "", 200

    pedido = PEDIDOS[codigo]
    txid = txid or pedido.get("c6_txid")

    if not txid:
        print("Webhook C6 recebido sem txid identificável.")
        return "", 200

    try:
        consulta = consultar_pix_c6(txid)
        status = str(consulta.get(C6_STATUS_FIELD, "")).upper()

        pedido["c6_last_status"] = status
        pedido["c6_last_query"] = consulta

        # Sem C6_PAID_STATUS_VALUES configurado, NUNCA libera.
        # Isso evita assumir nomenclatura de status bancário.
        if C6_PAID_STATUS_VALUES and status in C6_PAID_STATUS_VALUES:
            finalizar_pedido_pago(codigo, "c6")

    except Exception as erro:
        print("Falha ao confirmar pagamento no C6:", erro)

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
            "tracking_code": None
        }

    }

    PEDIDOS[codigo] = pedido


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
# CONSULTAR PEDIDO
# =====================================================

@app.route(
    "/api/pedido/<codigo>",
    methods=["GET"]
)
def consultar_pedido(codigo):

    pedido = PEDIDOS.get(
        codigo
    )

    if not pedido:

        return jsonify({
            "error":
                "Pedido não encontrado."
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
