"""Calendário Inteligente do Maranhão Intelligence (ETAPA 5.1, conteúdo 5.1B,
Conselho de Agentes na integração seguinte).

Superfície HTTP somente leitura sobre mi_decisao.planejar() e
mi_publico.planejar_publico(): mesmo padrão de mi_painel.py (autenticação
administrativa, DRY-RUN, nunca expõe payload interno além do necessário).
Não é um componente novo de decisão -- só organiza o que mi_decisao e
mi_publico já calculam em baldes de calendário. As atividades de conteúdo
sugerido (ETAPA 5.1B) e as recomendações do Conselho de Agentes já
persistidas em mi_fila_operacional (via mi_conselho, sem fila paralela)
chegam pelo mesmo formato de atividade que as demais.
"""
from psycopg2.extras import RealDictCursor
from mi_decisao import planejar, calendario, leitura_calendario
from mi_publico import planejar_publico
from mi_conselho import atividades_pendentes_fila


def gerar_calendario_mi(factory):
    decisoes = planejar(factory)
    publico = planejar_publico(factory)
    decisoes = decisoes + publico['atividades_calendario']

    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            decisoes = decisoes + atividades_pendentes_fila(cur)
    finally:
        conn.close()

    c = calendario(decisoes)
    leitura = leitura_calendario(decisoes)
    return {
        'success': True,
        'resumo': {
            'ia_trabalhando': leitura['ia_trabalhando'],
            'total_hoje': len(c['hoje']),
            'total_proximas': len(c['proximas']),
            'total_aguardando': len(c['aguardando']),
            'total_concluidas': len(c['concluidas']),
            'total_bloqueadas': len(c['bloqueadas']),
            'total_precisa_diretor': len(c['precisa_diretor']),
        },
        'proxima_atividade': c['proxima_atividade'],
        'colunas': {
            'hoje': c['hoje'],
            'proximas': c['proximas'],
            'aguardando': c['aguardando'],
            'concluidas': c['concluidas'],
            'bloqueadas': c['bloqueadas'],
            'precisa_diretor': c['precisa_diretor'],
        },
        'inteligencia_de_publico': {
            'top10': publico['top10'],
            'mudou_desde_ultima_analise': publico['mudou_desde_ultima_analise'],
        },
    }


def registrar_rotas_mi_calendario(app, factory, autorizado):
    from flask import jsonify

    @app.route('/api/admin/mi/calendario', methods=['GET'])
    def mi_calendario():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(gerar_calendario_mi(factory))
        except Exception:
            app.logger.exception('Falha ao gerar calendário Maranhão Intelligence')
            return jsonify(success=False, error='Calendário indisponível.'), 503
