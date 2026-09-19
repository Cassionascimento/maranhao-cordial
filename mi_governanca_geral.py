"""Governança geral da empresa (Central Empresarial — correção de UX,
seção A/C da ordem "Central Empresarial: Operações Vivas").

O card "Autonomia empresarial" do Admin (admin.html, `carregarFase55`)
chamava `GET /api/admin/ia-empresarial/fase55` -- uma rota que nunca
existiu neste backend (confirmado por busca em todo main.py). Por isso
o card sempre caía no `catch` genérico e mostrava "Governança
indisponível no momento", para sempre, sem nenhuma chance de
"Atualizar" resolver -- não era uma falha transitória de rede, era uma
URL sem rota.

Este módulo cria a rota que faltava, reaproveitando exclusivamente
`mi_fila_operacional` (mi_decisao.py, já existente desde a ETAPA 5.0) --
nenhuma tabela nova, nenhum índice de "dependência da direção" é
inventado: cada número devolvido é uma contagem real de linhas, nunca
uma estimativa ou fórmula não verificável. Quando não há base
suficiente para uma proporção, o campo correspondente é omitido (o
frontend já trata a ausência como "-", nunca 0% ou 100% fabricados)."""
from mi_decisao import ESTADOS_FILA


def contagem_geral_por_estado(cur):
    """Mesmo padrão de mi_outcome_relacionamento.contagem_por_estado,
    mas sem filtrar por origem -- visão da empresa inteira, não só de
    relacionamentos P5. Reaproveita a mesma tabela, nunca duplica."""
    cur.execute("SELECT estado, COUNT(*)::INTEGER AS total FROM mi_fila_operacional GROUP BY estado")
    contagens = {estado: 0 for estado in ESTADOS_FILA}
    for linha in cur.fetchall():
        contagens[linha['estado']] = linha['total']
    return contagens


def alertas_imediatos(cur, limite=6):
    """Itens que já escalaram para precisar do Diretor -- 'o que
    realmente precisa de você agora'. `motivo` vem sempre de um campo
    real já registrado pelo próprio item (`inferencia`), nunca de uma
    heurística nova."""
    cur.execute(
        "SELECT tipo_decisao, inferencia, proxima_acao, criado_em FROM mi_fila_operacional "
        "WHERE estado='precisa_diretor' ORDER BY criado_em DESC LIMIT %s",
        (limite,),
    )
    return [
        {
            'tipo': linha['tipo_decisao'],
            'proxima_acao': linha['proxima_acao'],
            'triagem_fase54': {'motivo': linha['inferencia'] or 'Motivo não registrado pelo item.'},
        }
        for linha in cur.fetchall()
    ]


def visao_governanca(cur):
    contagens = contagem_geral_por_estado(cur)
    resultado = {
        'precisa_de_mim': {
            'total_alertas_imediatos': contagens['precisa_diretor'],
            'total_aprovacoes_sem_alerta': contagens['aguardando'],
            'operacionais_que_nao_precisam_da_direcao': contagens['concluida'],
            'alertas_imediatos': alertas_imediatos(cur),
        },
        'autonomia': {},
    }
    # Índice de dependência só existe com uma base real para dividir --
    # sem isso, o campo fica ausente (o frontend já mostra "-" quando
    # ausente); nunca 0%/100% fabricados por falta de dado.
    base = contagens['precisa_diretor'] + contagens['concluida']
    if base > 0:
        resultado['autonomia']['indice_dependencia_direcao_pct'] = round(
            (contagens['precisa_diretor'] / base) * 100, 1,
        )
    return resultado


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify
    from psycopg2.extras import RealDictCursor

    @app.route('/api/admin/ia-empresarial/fase55', methods=['GET'])
    def mi_governanca_geral():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                visao = visao_governanca(cur)
        except Exception:
            app.logger.exception('Falha ao montar a visão de governança geral')
            return jsonify(success=False, error='Governança indisponível no momento.'), 503
        finally:
            conn.close()
        return jsonify(success=True, **visao)
