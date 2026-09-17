"""P3D -- Forecast readiness.

Só agrega séries temporais REAIS (compras_relacionamento, pedidos por SKU,
interacoes_omnichannel) e aplica um gate determinístico de volume mínimo --
NENHUMA previsão estatística é calculada aqui. Enquanto o volume real for
insuficiente, `forecast_ready` fica False com o motivo explícito, nunca um
número de previsão inventado.

Reaproveita as mesmas tabelas já usadas por mi_relacionamento_360/
mi_inteligencia_relacionamento -- nenhuma tabela nova, nenhuma migration."""
from datetime import datetime, timezone

MESES_MINIMOS_PARA_FORECAST = 6
LIMITE_MESES_PADRAO = 24


def _serie_mensal_vendas(cur, limite_meses):
    cur.execute(
        "SELECT date_trunc('month', comprado_em) AS mes, COUNT(*)::INTEGER AS total_pedidos, "
        "COALESCE(SUM(valor_centavos),0)::BIGINT AS receita_centavos "
        "FROM compras_relacionamento WHERE comprado_em >= NOW() - (%s || ' months')::interval "
        "GROUP BY 1 ORDER BY 1",
        (limite_meses,),
    )
    return [dict(r) for r in cur.fetchall()]


def _serie_mensal_por_sku(cur, limite_meses):
    cur.execute(
        "SELECT sku, date_trunc('month', criado_em) AS mes, COUNT(*)::INTEGER AS total_pedidos "
        "FROM pedidos WHERE sku IS NOT NULL AND criado_em >= NOW() - (%s || ' months')::interval "
        "GROUP BY 1, 2 ORDER BY 1, 2",
        (limite_meses,),
    )
    return [dict(r) for r in cur.fetchall()]


def _serie_mensal_interacoes(cur, limite_meses):
    cur.execute(
        "SELECT date_trunc('month', criado_em) AS mes, COUNT(*)::INTEGER AS total_interacoes "
        "FROM interacoes_omnichannel WHERE criado_em >= NOW() - (%s || ' months')::interval "
        "GROUP BY 1 ORDER BY 1",
        (limite_meses,),
    )
    return [dict(r) for r in cur.fetchall()]


def _readiness(serie, campo_contagem, minimo=MESES_MINIMOS_PARA_FORECAST):
    meses_com_dado = sum(1 for p in serie if (p.get(campo_contagem) or 0) > 0)
    pronto = meses_com_dado >= minimo
    motivo = (f'{meses_com_dado} mês(es) com dado -- volume mínimo de {minimo} atingido' if pronto
              else f'{meses_com_dado} mês(es) com dado, mínimo exigido é {minimo}')
    return {'forecast_ready': pronto, 'motivo': motivo, 'meses_com_dado': meses_com_dado}


def montar_forecast_readiness(cur, limite_meses=LIMITE_MESES_PADRAO, agora=None):
    agora = agora or datetime.now(timezone.utc)
    serie_vendas = _serie_mensal_vendas(cur, limite_meses)
    serie_sku = _serie_mensal_por_sku(cur, limite_meses)
    serie_interacoes = _serie_mensal_interacoes(cur, limite_meses)

    por_sku = {}
    for linha in serie_sku:
        por_sku.setdefault(linha['sku'], []).append({'mes': linha['mes'], 'total_pedidos': linha['total_pedidos']})

    readiness_por_sku = {sku: _readiness(pontos, 'total_pedidos') for sku, pontos in por_sku.items()}

    return {
        'generated_at': agora.isoformat(),
        'series': {
            'vendas_mensais': serie_vendas,
            'interacoes_mensais': serie_interacoes,
            'pedidos_por_sku_mes': por_sku,
        },
        'readiness': {
            'sales_forecast': _readiness(serie_vendas, 'total_pedidos'),
            'engagement_forecast': _readiness(serie_interacoes, 'total_interacoes'),
            'demand_by_sku_forecast': readiness_por_sku if readiness_por_sku else 'NOT_ENOUGH_DATA',
        },
        'nota': 'Nenhuma previsão estatística é calculada aqui -- só a série real e o gate de volume mínimo.',
    }


def registrar_rotas_leitura(app, factory, autorizado):
    from flask import jsonify
    from psycopg2.extras import RealDictCursor

    @app.route('/api/admin/mi/forecast/readiness', methods=['GET'])
    def mi_forecast_readiness():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                resultado = montar_forecast_readiness(cur)
        except Exception:
            app.logger.exception('Falha ao montar forecast readiness')
            return jsonify(success=False, error='Forecast readiness indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, **resultado)
