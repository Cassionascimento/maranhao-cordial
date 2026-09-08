"""Comando separado, manual e explicitamente habilitado. Não agendar na janela P0."""
import os
import requests
from gmail_sync_job import API_BASE, JobAbortado, _confirmar, executar_job


def executar_prospeccao(http=requests):
    if os.getenv("PROSPECCAO_JOB_HABILITADO") != "true":
        raise JobAbortado("Prospecção não habilitada explicitamente")
    cron = os.getenv("FASE58_CRON_SECRET")
    if not cron:
        raise JobAbortado("Configuração cron incompleta")
    executar_job(http)  # A sincronização precisa passar primeiro.
    dados = _confirmar(http.post(
        API_BASE + "/api/internal/fase58a/executar",
        headers={"X-Fase58-Key": cron}, timeout=(10, 180), allow_redirects=False,
    ), "Fase 5.8")
    if isinstance(dados.get("fase58b"), dict) and dados["fase58b"].get("success") is False:
        raise JobAbortado("Fase 5.8B não confirmou sucesso")
    return dados


if __name__ == "__main__":
    try:
        executar_prospeccao()
    except Exception as erro:
        print(f"Prospecção abortada ({type(erro).__name__}).")
        raise SystemExit(1)
