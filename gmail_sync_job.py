"""Sincronização Gmail isolada. Não envia nem chama prospecção."""
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
    if not admin:
        raise JobAbortado("Configuração administrativa incompleta")

    # Sem redirects: nunca encaminha a chave administrativa para outro destino.
    sync = http.get(
        API_BASE + "/api/gmail/sincronizar",
        headers={"X-Admin-Key": admin}, timeout=(10, 120), allow_redirects=False,
    )
    dados = _confirmar(sync, "Gmail")
    if dados.get("prospeccao_permitida") is not True:
        raise JobAbortado("Gmail: prospecção não autorizada pelo resultado da sincronização")

    return dados


def main():
    try:
        executar_job()
    except Exception as erro:
        # Não imprime respostas, headers ou URLs de exceções potencialmente sensíveis.
        print(f"Job Gmail abortado ({type(erro).__name__}).", file=sys.stderr)
        return 1
    print("Gmail sincronizado; nenhuma prospecção disparada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
