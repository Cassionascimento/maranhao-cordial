"""Painel administrativo somente leitura do Maranhão Intelligence.

Snapshot consistente: todas as consultas rodam na mesma transação
read-only (mesmo padrão de inteligencia_territorial.carregar()). Nunca
expõe id interno, codigo_publico ou payload. Distribuição por lote usa a
relação canônica (mi_eventos.unidade_id -> mi_unidades.lote_id ->
mi_lotes), nunca o campo textual solto mi_eventos.lote (legado da Fase 1).
"""
from psycopg2.extras import RealDictCursor

ESTADOS_UNIDADE = ('emitida', 'ativa', 'revogada')
LIMITE_LISTAS = 20


def gerar_painel_mi(factory):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")

            cur.execute("SELECT count(*) AS total FROM mi_skus")
            total_skus = cur.fetchone()['total']

            cur.execute("SELECT count(*) AS total FROM mi_lotes")
            total_lotes = cur.fetchone()['total']

            cur.execute("SELECT estado, count(*) AS total FROM mi_unidades GROUP BY estado")
            unidades_por_estado = {estado: 0 for estado in ESTADOS_UNIDADE}
            total_unidades = 0
            for linha in cur.fetchall():
                unidades_por_estado[linha['estado']] = linha['total']
                total_unidades += linha['total']

            cur.execute("SELECT count(*) AS total FROM mi_eventos")
            total_eventos = cur.fetchone()['total']

            cur.execute("SELECT count(*) AS total FROM mi_eventos WHERE tipo_evento='scan' AND canal='qr'")
            total_scans_qr = cur.fetchone()['total']

            cur.execute("SELECT count(*) AS total FROM mi_estabelecimentos")
            total_estabelecimentos = cur.fetchone()['total']

            cur.execute(
                "SELECT b.cidade, b.uf, count(*) AS total "
                "FROM mi_eventos e JOIN mi_estabelecimentos b ON b.id = e.estabelecimento_id "
                "GROUP BY b.cidade, b.uf ORDER BY total DESC"
            )
            territorio = [dict(linha) for linha in cur.fetchall()]

            cur.execute(
                "SELECT e.tipo_evento, e.canal, e.sku, e.criado_em, b.cidade, b.uf "
                "FROM mi_eventos e LEFT JOIN mi_estabelecimentos b ON b.id = e.estabelecimento_id "
                "ORDER BY e.criado_em DESC LIMIT %s",
                (LIMITE_LISTAS,),
            )
            atividade_recente = [dict(linha) for linha in cur.fetchall()]

            cur.execute(
                "SELECT e.sku, s.produto_nome, count(*) AS total "
                "FROM mi_eventos e LEFT JOIN mi_skus s ON s.sku = e.sku "
                "WHERE e.sku IS NOT NULL GROUP BY e.sku, s.produto_nome "
                "ORDER BY total DESC LIMIT %s",
                (LIMITE_LISTAS,),
            )
            por_sku = [dict(linha) for linha in cur.fetchall()]

            # Fonte canônica: unidade_id -> mi_unidades.lote_id -> mi_lotes.
            # Nunca o campo textual solto mi_eventos.lote (legado da Fase 1).
            cur.execute(
                "SELECT COALESCE(l.codigo_lote, 'não associado') AS lote, count(*) AS total "
                "FROM mi_eventos e "
                "LEFT JOIN mi_unidades u ON u.id = e.unidade_id "
                "LEFT JOIN mi_lotes l ON l.id = u.lote_id "
                "GROUP BY l.codigo_lote ORDER BY total DESC LIMIT %s",
                (LIMITE_LISTAS,),
            )
            por_lote = [dict(linha) for linha in cur.fetchall()]

            cur.execute(
                "SELECT b.nome, b.cidade, b.uf, count(*) AS total "
                "FROM mi_eventos e JOIN mi_estabelecimentos b ON b.id = e.estabelecimento_id "
                "GROUP BY b.id, b.nome, b.cidade, b.uf ORDER BY total DESC LIMIT %s",
                (LIMITE_LISTAS,),
            )
            por_estabelecimento = [dict(linha) for linha in cur.fetchall()]

        return {
            'success': True,
            'resumo': {
                'unidades': total_unidades,
                'eventos': total_eventos,
                'scans_qr': total_scans_qr,
                'estabelecimentos': total_estabelecimentos,
                'territorios_ativos': len(territorio),
            },
            'secundario': {
                'skus': total_skus,
                'lotes': total_lotes,
                'unidades_por_estado': unidades_por_estado,
            },
            'atividade_recente': atividade_recente,
            'produto': {
                'por_sku': por_sku,
                'por_lote': por_lote,
            },
            'estabelecimentos_distribuicao': por_estabelecimento,
            'territorio': territorio,
        }
    finally:
        conn.close()


def registrar_rotas_mi_painel(app, factory, autorizado):
    from flask import jsonify

    @app.route('/api/admin/mi/painel', methods=['GET'])
    def mi_painel():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(gerar_painel_mi(factory))
        except Exception:
            app.logger.exception('Falha ao gerar painel Maranhão Intelligence')
            return jsonify(success=False, error='Painel indisponível.'), 503
