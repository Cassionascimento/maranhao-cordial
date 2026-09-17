"""Central Empresarial -- seção 1.D da ordem "Central Empresarial:
Operações Vivas" (ciclo de vida de Contatos/Profissionais/Fábricas).

profissionais_rede e fabricas_parceiras já têm arquivamento e workflow
de status reais em produção (admin_arquivamento_profissional/
admin_workflow_profissional/admin_workflow_fabrica, main.py) -- não
duplicados aqui. `contatos_estrategicos` só tinha LISTAR/CRIAR (mesmo
arquivo): esta é a lacuna real que faltava fechar -- nunca mudava de
status, nunca tinha histórico, nunca podia ser arquivado/excluído,
nunca registrava follow-up. Migration 023 (aditiva) acrescenta as
colunas e a tabela de histórico que este módulo usa.
"""
from psycopg2.extras import RealDictCursor

ESTADOS_CONTATO = ('prospectado', 'em_contato', 'qualificado', 'parceria_ativa', 'descartado')


def _uuid(v):
    return str(v) if v is not None else None


def mudar_status(factory, contato_id, novo_status, ator, motivo=None):
    """Muda o status e sempre grava histórico -- inclusive reversão
    (voltar a um status anterior é uma mudança de status como outra
    qualquer, nunca uma operação especial ou bloqueada)."""
    if novo_status not in ESTADOS_CONTATO:
        raise ValueError('status_invalido')
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM contatos_estrategicos WHERE id=%s FOR UPDATE", (_uuid(contato_id),))
                atual = cur.fetchone()
                if not atual:
                    return {'success': False, 'motivo': 'contato_nao_encontrado'}
                cur.execute(
                    "UPDATE contatos_estrategicos SET status_relacao=%s, atualizado_em=NOW() WHERE id=%s RETURNING *",
                    (novo_status, _uuid(contato_id)),
                )
                contato = cur.fetchone()
                cur.execute(
                    "INSERT INTO contatos_estrategicos_historico_status "
                    "(contato_id, status_anterior, status_novo, motivo, ator) VALUES (%s,%s,%s,%s,%s)",
                    (_uuid(contato_id), atual['status_relacao'], novo_status, motivo, ator),
                )
                return {'success': True, 'contato': contato}
    finally:
        conn.close()


def historico_status(factory, contato_id, limite=100):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute(
                "SELECT * FROM contatos_estrategicos_historico_status WHERE contato_id=%s "
                "ORDER BY criado_em DESC LIMIT %s",
                (_uuid(contato_id), limite),
            )
            return cur.fetchall()
    finally:
        conn.close()


def registrar_interacao(factory, contato_id, ator, *, houve_resposta=False, proxima_acao=None, data_followup=None,
                         observacoes=None):
    """Registra uma tentativa de contato real -- incrementa o contador
    (nunca decrementado, é histórico de esforço) e atualiza último
    contato/última resposta com o horário real do servidor, nunca um
    valor informado pelo cliente."""
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM contatos_estrategicos WHERE id=%s", (_uuid(contato_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'contato_nao_encontrado'}
                sets = ["tentativas_contato = tentativas_contato + 1", "ultimo_contato_em = NOW()", "atualizado_em = NOW()"]
                args = []
                if houve_resposta:
                    sets.append("ultima_resposta_em = NOW()")
                if proxima_acao is not None:
                    sets.append("proxima_acao = %s")
                    args.append(proxima_acao)
                if data_followup is not None:
                    sets.append("data_followup = %s")
                    args.append(data_followup)
                if observacoes is not None:
                    sets.append("observacoes = %s")
                    args.append(observacoes)
                args.append(_uuid(contato_id))
                cur.execute(f"UPDATE contatos_estrategicos SET {', '.join(sets)} WHERE id=%s RETURNING *", args)
                return {'success': True, 'contato': cur.fetchone()}
    finally:
        conn.close()


def arquivar(factory, contato_id, ator, arquivado=True):
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM contatos_estrategicos WHERE id=%s", (_uuid(contato_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'contato_nao_encontrado'}
                if arquivado:
                    cur.execute(
                        "UPDATE contatos_estrategicos SET arquivado=TRUE, arquivado_em=NOW(), arquivado_por=%s, "
                        "atualizado_em=NOW() WHERE id=%s RETURNING *", (ator, _uuid(contato_id)),
                    )
                else:
                    cur.execute(
                        "UPDATE contatos_estrategicos SET arquivado=FALSE, arquivado_em=NULL, arquivado_por=NULL, "
                        "atualizado_em=NOW() WHERE id=%s RETURNING *", (_uuid(contato_id),),
                    )
                return {'success': True, 'contato': cur.fetchone()}
    finally:
        conn.close()


def excluir_definitivamente(factory, contato_id, ator, confirmacao):
    """EXCLUSÃO DEFINITIVA -- só para cadastro de teste/fake confirmado
    pelo humano (`confirmacao=True` explícito) e sem NENHUMA dependência
    real: nenhuma mudança de status registrada e nunca verificado por
    alguém. Um contato com histórico ou verificação já é, por definição,
    um registro que a operação usou -- nunca é excluído, só arquivado."""
    if not ator or not str(ator).strip():
        raise ValueError('ator_obrigatorio')
    if confirmacao is not True:
        return {'success': False, 'motivo': 'confirmacao_explicita_obrigatoria'}
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM contatos_estrategicos WHERE id=%s FOR UPDATE", (_uuid(contato_id),))
                contato = cur.fetchone()
                if not contato:
                    return {'success': False, 'motivo': 'contato_nao_encontrado'}
                if contato['verificado_em'] is not None or contato['tentativas_contato'] > 0:
                    return {'success': False, 'motivo': 'possui_interacao_real_use_arquivar'}
                cur.execute(
                    "SELECT COUNT(*)::INTEGER AS total FROM contatos_estrategicos_historico_status WHERE contato_id=%s",
                    (_uuid(contato_id),),
                )
                if cur.fetchone()['total'] > 0:
                    return {'success': False, 'motivo': 'possui_historico_use_arquivar'}
                cur.execute("DELETE FROM contatos_estrategicos WHERE id=%s", (_uuid(contato_id),))
                return {'success': True, 'excluido': True, 'id': str(contato_id)}
    finally:
        conn.close()


def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    def _erro(motivo, status=400):
        return jsonify(success=False, error=motivo), status

    def _ator(corpo):
        return corpo.get('ator') or request.args.get('ator') or 'admin'

    @app.route('/api/admin/contatos-estrategicos/<contato_id>/status', methods=['PATCH'])
    def contato_estrategico_status(contato_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = mudar_status(factory, contato_id, corpo.get('status'), _ator(corpo), motivo=corpo.get('motivo'))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao mudar status do contato %s', contato_id)
            return _erro('Contato indisponível no momento.', 503)

    @app.route('/api/admin/contatos-estrategicos/<contato_id>/historico', methods=['GET'])
    def contato_estrategico_historico(contato_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            return jsonify(success=True, historico=historico_status(factory, contato_id))
        except Exception:
            app.logger.exception('Falha ao ler histórico do contato %s', contato_id)
            return _erro('Histórico indisponível no momento.', 503)

    @app.route('/api/admin/contatos-estrategicos/<contato_id>/interacao', methods=['POST'])
    def contato_estrategico_interacao(contato_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = registrar_interacao(
                factory, contato_id, _ator(corpo), houve_resposta=bool(corpo.get('houve_resposta')),
                proxima_acao=corpo.get('proxima_acao'), data_followup=corpo.get('data_followup'),
                observacoes=corpo.get('observacoes'))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao registrar interação do contato %s', contato_id)
            return _erro('Contato indisponível no momento.', 503)

    @app.route('/api/admin/contatos-estrategicos/<contato_id>/arquivamento', methods=['PATCH'])
    def contato_estrategico_arquivamento(contato_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = arquivar(factory, contato_id, _ator(corpo), arquivado=bool(corpo.get('arquivado', True)))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao arquivar contato %s', contato_id)
            return _erro('Contato indisponível no momento.', 503)

    @app.route('/api/admin/contatos-estrategicos/<contato_id>', methods=['DELETE'])
    def contato_estrategico_excluir(contato_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = excluir_definitivamente(factory, contato_id, _ator(corpo), corpo.get('confirmacao'))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao excluir contato %s', contato_id)
            return _erro('Contato indisponível no momento.', 503)
