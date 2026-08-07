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


@app.route("/lifestyle")
def lifestyle():
    return renderizar_html("lifestyle.html")


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


@app.route("/favicon.ico")
def favicon():
    return "", 204


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

        "pagarme_id": None

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

            pedido = PEDIDOS[codigo]

            # -----------------------------------------
            # MUDA STATUS
            # -----------------------------------------

            pedido["status"] = "pago"


            # -----------------------------------------
            # ENVIA PARA COZINHA
            # -----------------------------------------

            kitchen_data = {

                "code":
                    codigo,

                "quantity":
                    pedido["quantity"]

            }

            emit(
                "to_kitchen",
                kitchen_data,
                broadcast=True
            )


            # -----------------------------------------
            # ENVIA PARA ENTREGA
            # -----------------------------------------

            delivery_data = {

                "code":
                    codigo,

                "address":
                    pedido["address"]

            }

            emit(
                "to_delivery",
                delivery_data,
                broadcast=True
            )


            # -----------------------------------------
            # ENVIA PARA ADMINISTRADOR
            # -----------------------------------------

            emit(
                "to_admin",
                pedido,
                broadcast=True
            )


            print(
                f"✓ PEDIDO {codigo} PAGO"
            )

            print(
                "✓ Enviado para cozinha"
            )

            print(
                "✓ Enviado para entrega"
            )

            print(
                "✓ Enviado para administrador"
            )


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
