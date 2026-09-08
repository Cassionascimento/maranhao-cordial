"""Entrada isolada: nenhuma importação de main, briefing, piloto ou Fases 5.8."""
import json
import os
import psycopg2
from gmail_sync_job import executar_job
from email_seguranca import definir_pausa
from prospeccao_controle import rodada


def executar():
    if os.getenv('PROSPECCAO_CONTROLADA_HABILITADA') != 'true':
        raise RuntimeError('prospeccao_controlada_desabilitada')
    if os.getenv('EMAIL_APENAS_PROSPECCAO_CONTROLADA') != 'true':
        raise RuntimeError('escopo_de_envio_nao_restrito')
    def conn():
        return psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require')
    try:
        executar_job()  # Apenas sync autenticado; nenhum gatilho 5.8.
        return rodada({'get_db_connection': conn})
    except Exception:
        definir_pausa(conn, True, 'Job controlado interrompido')
        raise


if __name__ == '__main__':
    resultado = executar()
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    raise SystemExit(0 if resultado['success'] else 1)
