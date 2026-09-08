"""Comando versionado para gmail-sync-maranhao-cordial. Nunca importa main.py."""
import os
import sys
import requests
from email_seguranca import chave_admin_configurada


API_BASE = "https://maranhao-cordial-api.onrender.com"


class JobAbortado(RuntimeError):
    pass


def _confirmar(resposta, etapa):
    if resposta.status_code != 200:
        raise JobAbortado(f"{etapa}: HTTP não confirmado")
    dados = resposta.json()
    if not isinstance(dados, dict) or dados.get("success") is not True or dados.get("erros"):
        raise JobAbortado(f"{etapa}: resultado não confirmado")
    return dados


def executar_job(http=requests):
    admin = chave_admin_configurada({})
    cron = os.getenv("FASE58_CRON_SECRET")
    if not admin or not cron:
        raise JobAbortado("Configuração administrativa/cron incompleta")

    # Sem redirects: nunca encaminha a chave administrativa para outro destino.
    sync = http.get(
        API_BASE + "/api/gmail/sincronizar",
        headers={"X-Admin-Key": admin}, timeout=(10, 120), allow_redirects=False,
    )
    dados = _confirmar(sync, "Gmail")
    if dados.get("prospeccao_permitida") is not True:
        raise JobAbortado("Gmail: prospecção não autorizada pelo resultado da sincronização")

    # Único disparo, apenas depois de confirmar toda a sincronização.
    # A rota 5.8A já executa também a 5.8B.
    fase58 = http.post(
        API_BASE + "/api/internal/fase58a/executar",
        headers={"X-Fase58-Key": cron}, timeout=(10, 180), allow_redirects=False,
    )
    resultado = _confirmar(fase58, "Fase 5.8")
    if isinstance(resultado.get("fase58b"), dict) and resultado["fase58b"].get("success") is False:
        raise JobAbortado("Fase 5.8B não confirmou sucesso")
    return {"success": True}


def main():
    try:
        executar_job()
    except Exception as erro:
        # Não imprime respostas, headers ou URLs de exceções potencialmente sensíveis.
        print(f"Job Gmail abortado ({type(erro).__name__}).", file=sys.stderr)
        return 1
    print("Gmail e Fase 5.8 concluídos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
