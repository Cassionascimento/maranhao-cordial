from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit
import os

# =====================================================
# CONFIGURAÇÃO
# =====================================================

# BASE_DIR será "/Users/cassionascimento/Documents/krikati"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# CORREÇÃO: Aponta para a pasta correta onde estão os HTMLs
FRONTEND_FOLDER = os.path.join(BASE_DIR, "maranhao-backend")

print("=" * 60)
print("BASE_DIR:", BASE_DIR)
print("FRONTEND_FOLDER:", FRONTEND_FOLDER)
print("PASTA EXISTE?", os.path.isdir(FRONTEND_FOLDER))
print("INDEX EXISTE?", os.path.isfile(os.path.join(FRONTEND_FOLDER, "index.html")))
print("=" * 60)

app = Flask(__name__, static_folder=FRONTEND_FOLDER)
app.config["SECRET_KEY"] = "krikati_ancestral_secret"

socketio = SocketIO(app, cors_allowed_origins="*")

# =====================================================
# PÁGINA INICIAL
# =====================================================

@app.route("/")
@app.route("/index")
@app.route("/index.html")
def index():
    return send_from_directory(FRONTEND_FOLDER, "index.html")

# =====================================================
# PÁGINAS (Padronizadas com send_from_directory)
# =====================================================

def renderizar_html(nome_arquivo):
    """Busca o arquivo em minúsculo ou maiúsculo antes de enviar"""
    if os.path.isfile(os.path.join(FRONTEND_FOLDER, nome_arquivo)):
        return send_from_directory(FRONTEND_FOLDER, nome_arquivo)
    
    # Se não achar, tenta com a extensão em maiúsculo (.HTML)
    nome_maiusculo = nome_arquivo.replace(".html", ".HTML")
    if os.path.isfile(os.path.join(FRONTEND_FOLDER, nome_maiusculo)):
        return send_from_directory(FRONTEND_FOLDER, nome_maiusculo)
        
    # Se não achar nenhum, retorna erro descritivo
    return f"Erro: O arquivo '{nome_arquivo}' nao foi encontrado na pasta do backend.", 404







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


@app.route("/favicon.ico")
def favicon():
    return "", 204


# =====================================================
# WEBSOCKET
# =====================================================

@socketio.on("new_ancestral_order")
def handle_new_order(payload):

    order_code = payload.get("code")

    kitchen_data = {
        "code": order_code,
        "potion": payload.get("potion"),
        "size": payload.get("size")
    }

    emit("to_kitchen", kitchen_data, broadcast=True)

    delivery_data = {
        "code": order_code,
        "address": payload.get("address")
    }

    emit("to_delivery", delivery_data, broadcast=True)

    emit("to_admin", payload, broadcast=True)

    print(f"Pedido {order_code} enviado com sucesso.")

print("\nROTAS REGISTRADAS:\n")

for regra in app.url_map.iter_rules():
    print(regra)

# =====================================================
# ROTA DE ARQUIVOS ESTÁTICOS
# =====================================================

@app.route("/<path:filename>")
def arquivos(filename):
    return send_from_directory(FRONTEND_FOLDER, filename)

# =====================================================
# INICIALIZAÇÃO
# =====================================================

if __name__ == "__main__":

    porta = int(os.environ.get("PORT", 3000))

    socketio.run(
        app,
        host="0.0.0.0",
        port=porta,
        debug=True
    )
