"""Job standalone do Conselho de Agentes -- MODO OBSERVADOR.

Mesmo padrão dos jobs já existentes (script Python simples, conecta com
`DATABASE_URL`, travado por env var explícita) -- processo próprio,
independente: não importa nem roda dentro de gmail_sync_job.py nem de
nenhum prospeccao_*.py. Não configura nenhum scheduler nem Render aqui --
isto é só o script que um agendador externo chamaria, no mesmo formato de
prospeccao_render_job.py/prospeccao_controlada_job.py.

Desabilitado por padrão: só executa quando CONSELHO_JOB_HABILITADO for
exatamente 'true'. CONSELHO_MODO_OBSERVADOR também é seguro por padrão
(mi_conselho_executor.modo_observador_ativo() só desliga com 'false'
exato) -- mas mesmo com o modo observador desligado, nada neste job ou em
mi_conselho_executor chama ação externa: essa etapa não implementa nenhum
caminho de execução, só leitura, análise e registro.
"""
import json
import os

import psycopg2

from mi_conselho_executor import modo_observador_ativo, processar_e_registrar


def conectar():
    return psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require', connect_timeout=10)


def executar(factory=conectar):
    # Exato, sem normalizar maiúscula/minúscula -- mesmo padrão de
    # PROSPECCAO_JOB_HABILITADO/PROSPECCAO_CONTROLADA_HABILITADA: só o
    # literal 'true' habilita, qualquer outra coisa (ausente, 'TRUE',
    # '1', 'yes') mantém desligado.
    if os.getenv('CONSELHO_JOB_HABILITADO') != 'true':
        return {'success': True, 'executado': False, 'motivo': 'conselho_job_desabilitado'}
    resultados = processar_e_registrar(factory)
    return {'success': True, 'executado': True, 'modo_observador': modo_observador_ativo(),
            'total_avaliados': len(resultados)}


if __name__ == '__main__':
    resultado = executar()
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    raise SystemExit(0 if resultado['success'] else 1)
