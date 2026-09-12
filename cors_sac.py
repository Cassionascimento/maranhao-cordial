from flask import request

# CORS — SAC MARANHÃO CORDIAL
# =====================================================

ORIGENS_PERMITIDAS_SAC = {
    "https://maranhaocordial.com.br",
    "https://www.maranhaocordial.com.br",
    "https://maranhao-cordial.onrender.com",
}


def adicionar_cors_sac(response):

    if request.path.startswith("/api/gmail/"):
        origem = request.headers.get("Origin")
        if origem in ORIGENS_PERMITIDAS_SAC | {"https://maranhao-cordial.onrender.com"}:
            response.headers["Access-Control-Allow-Origin"] = origem
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.vary.add("Origin")
        response.headers["Cache-Control"] = "no-store"

    if (
        request.path.startswith("/api/sac")
        or request.path.startswith("/api/admin")
        or request.path.startswith("/api/profissional/cadastro")
        or request.path.startswith("/api/parceiros/fabricas/cadastro")
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
            ] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"

    return response
