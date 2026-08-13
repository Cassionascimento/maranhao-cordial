import os
import requests
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("C6_CLIENT_ID")
client_secret = os.getenv("C6_CLIENT_SECRET")
pix_key = os.getenv("C6_PIX_KEY")

cert = (
    os.getenv("C6_CERT_PATH", "C6_sandbox.crt"),
    os.getenv("C6_KEY_PATH", "C6_sandbox.key")
)

auth_url = "https://baas-api-sandbox.c6bank.info/v1/auth/"
pix_base = "https://baas-api-sandbox.c6bank.info/v2/pix"

# 1. Obtém token
r_auth = requests.post(
    auth_url,
    data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    },
    cert=cert,
    headers={
        "Content-Type": "application/x-www-form-urlencoded"
    },
    timeout=30
)

print("AUTH HTTP:", r_auth.status_code)

dados = r_auth.json()
token = dados.get("access_token")

if not token:
    print(dados)
    raise SystemExit

# 2. Registra webhook
url = f"{pix_base}/webhook/{pix_key}"

payload = {
    "webhookUrl":
        "https://maranhao-cordial-api.onrender.com/webhooks/c6"
}

r = requests.put(
    url,
    json=payload,
    cert=cert,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    timeout=30
)

print("WEBHOOK HTTP:", r.status_code)
print(r.text)
