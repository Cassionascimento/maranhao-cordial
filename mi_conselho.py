"""Conselho de Agentes -- integração com o Maranhão Intelligence.

Liga os 8 subagentes (.claude/agents/*.md) e o comando /conclave
(.claude/commands/conclave.md) ao software já existente. Não é um motor
novo: reaproveita mi_sinais (fatos/atividade dos agentes, mesmo barramento
da ETAPA 4.9), mi_decisao/mi_fila_operacional (fila e aprovação das
recomendações, mesmo motor da ETAPA 5.0) e mi_calendario (agenda, ETAPA
5.1) -- só acrescenta o que não existia: mensagens entre agentes e
registros estruturados de reunião/conclave/relatório (migration 016, não
executada).

Este módulo é uma API DE REGISTRO, não um executor. Nada aqui decide
invocar um agente, chama a API da Anthropic ou roda em loop. Uma sessão de
/conclave (conduzida por um humano com Claude Code) é quem chama estas
funções para PERSISTIR o que já foi decidido -- nunca o contrário. Sem
demanda real, nada aqui é chamado; não existe "job" ou "scheduler" neste
arquivo.
"""
import hashlib
import json
import re
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor, Json
from mi_decisao import _decisao
from mi_sinais import emitir

AGENTES = {
    'pirret': {'nome': 'Pirret', 'area': 'Marketing'},
    'standard': {'nome': 'Standard', 'area': 'Financeiro'},
    'zilda': {'nome': 'Zilda', 'area': 'Pessoas'},
    'leonard': {'nome': 'Leonard', 'area': 'Vendas'},
    'marie': {'nome': 'Marie', 'area': 'Produto'},
    'rua': {'nome': 'Rua', 'area': 'Operações'},
    'dicio': {'nome': 'Dicio', 'area': 'Jurídico'},
    'iris': {'nome': 'Iris', 'area': 'Dados'},
}
TIPOS_REGISTRO = ('reuniao', 'conclave', 'relatorio')
CAMPOS_REGISTRO = ('tipo', 'demanda', 'participantes', 'contexto', 'dados_apresentados',
                    'posicoes', 'conflitos', 'conclusao', 'recomendacoes', 'vetos',
                    'pendencias', 'precisa_diretor')


def _validar_agente(codigo, obrigatorio=True):
    if codigo is None:
        if obrigatorio:
            raise ValueError('agente_obrigatorio')
        return None
    if codigo not in AGENTES:
        raise ValueError('agente_desconhecido:' + str(codigo))
    return codigo


def validar_mensagem(body):
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    chave = str(UUID(str(body.get('chave'))))
    de_agente = _validar_agente(body.get('de_agente'))
    para_agente = _validar_agente(body.get('para_agente'), obrigatorio=False)
    texto = body.get('texto')
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError('texto_obrigatorio')
    if len(texto) > 4000:
        raise ValueError('texto_muito_longo')
    demanda = body.get('demanda_referencia')
    if demanda is not None and (not isinstance(demanda, str) or len(demanda) > 200):
        raise ValueError('demanda_referencia_invalida')
    return chave, {'de_agente': de_agente, 'para_agente': para_agente, 'texto': texto.strip(),
                   'demanda_referencia': demanda}


def registrar_mensagem(factory, body):
    chave, dados = validar_mensagem(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO mi_conselho_mensagens(id,chave,de_agente,para_agente,demanda_referencia,texto) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(chave) DO NOTHING RETURNING id",
                    (str(uuid4()), chave, dados['de_agente'], dados['para_agente'],
                     dados['demanda_referencia'], dados['texto']),
                )
                novo = cur.fetchone()
                cur.execute("SELECT id FROM mi_conselho_mensagens WHERE chave=%s", (chave,))
                row = cur.fetchone()
                return {'success': True, 'id': str(row['id']), 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def validar_registro(body):
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    chave = str(UUID(str(body.get('chave'))))
    tipo = body.get('tipo')
    if tipo not in TIPOS_REGISTRO:
        raise ValueError('tipo_invalido')
    participantes = body.get('participantes') or []
    if not isinstance(participantes, list) or not all(isinstance(p, str) for p in participantes):
        raise ValueError('participantes_invalidos')
    for agente in participantes:
        _validar_agente(agente)
    precisa_diretor = bool(body.get('precisa_diretor'))
    vetos = body.get('vetos')
    if vetos and not precisa_diretor:
        precisa_diretor = True
    dados = {
        'tipo': tipo,
        'demanda': body.get('demanda'),
        'participantes': participantes,
        'contexto': body.get('contexto'),
        'dados_apresentados': body.get('dados_apresentados'),
        'posicoes': body.get('posicoes'),
        'conflitos': body.get('conflitos'),
        'conclusao': body.get('conclusao'),
        'recomendacoes': body.get('recomendacoes') or [],
        'vetos': vetos,
        'pendencias': body.get('pendencias'),
        'precisa_diretor': precisa_diretor,
    }
    digest = hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return chave, dados, digest


_CAMPOS_JSON = {'participantes', 'dados_apresentados', 'posicoes', 'conflitos', 'recomendacoes', 'vetos', 'pendencias'}


def registrar_registro(factory, body):
    chave, dados, digest = validar_registro(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                colunas = ",".join(CAMPOS_REGISTRO)
                valores = [Json(dados[c]) if c in _CAMPOS_JSON else dados[c] for c in CAMPOS_REGISTRO]
                cur.execute(
                    "INSERT INTO mi_conselho_registros(id,chave,payload_hash," + colunas + ") "
                    "VALUES(" + ",".join(["%s"] * (len(CAMPOS_REGISTRO) + 3)) + ") "
                    "ON CONFLICT(chave) DO NOTHING RETURNING id",
                    [str(uuid4()), chave, digest] + valores,
                )
                novo = cur.fetchone()
                cur.execute("SELECT id, payload_hash FROM mi_conselho_registros WHERE chave=%s", (chave,))
                row = cur.fetchone()
                if row['payload_hash'] != digest:
                    return {'success': False, 'error': 'chave_reutilizada_com_outro_conteudo'}, 409
                return {'success': True, 'id': str(row['id']), 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def nova_versao_registro(factory, registro_anterior_id, campos_atualizados, ator):
    registro_anterior_id = str(UUID(str(registro_anterior_id)))
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM mi_conselho_registros WHERE id=%s", (registro_anterior_id,))
                anterior = cur.fetchone()
                if not anterior:
                    return {'success': False, 'motivo': 'registro_nao_encontrado'}
                corpo = {c: anterior[c] for c in CAMPOS_REGISTRO}
                corpo.update(campos_atualizados)
                corpo['chave'] = str(uuid4())
                _, dados, digest = validar_registro(corpo)
                colunas = ",".join(CAMPOS_REGISTRO)
                valores = [Json(dados[c]) if c in _CAMPOS_JSON else dados[c] for c in CAMPOS_REGISTRO]
                cur.execute(
                    "INSERT INTO mi_conselho_registros(id,chave,payload_hash,versao,registro_anterior_id," + colunas + ") "
                    "VALUES(" + ",".join(["%s"] * (len(CAMPOS_REGISTRO) + 5)) + ") RETURNING id",
                    [str(uuid4()), corpo['chave'], digest, anterior['versao'] + 1, anterior['id']] + valores,
                )
                novo = cur.fetchone()
                return {'success': True, 'id': str(novo['id']), 'versao': anterior['versao'] + 1, 'ator': ator}
    finally:
        conn.close()


def buscar_registro(cur, registro_id):
    """Leitura de UM registro (reunião/conclave/relatório) por id -- mesma
    tabela/colunas de registrar_registro/nova_versao_registro, nunca uma
    segunda representação. Usado por P5.X M3 (Secretário Executivo) para
    montar a ata a partir de uma deliberação já persistida, sem reprocessar
    nenhum parecer."""
    cur.execute("SELECT * FROM mi_conselho_registros WHERE id=%s", (str(registro_id),))
    row = cur.fetchone()
    if not row:
        return None
    registro = {c: row[c] for c in CAMPOS_REGISTRO}
    registro['id'] = str(row['id'])
    registro['chave'] = row['chave']
    registro['versao'] = row['versao']
    registro['criado_em'] = row['criado_em'].isoformat() if row.get('criado_em') else None
    return registro


def recomendacao_para_atividade(recomendacao, precisa_diretor=False, executar_em=None):
    responsavel = recomendacao.get('responsavel')
    descricao = recomendacao.get('descricao') or recomendacao.get('acao') or 'recomendação do Conselho'
    item = _decisao(
        'conselho', responsavel, 'recomendacao_conselho',
        [f"conselho:{responsavel}:{descricao}"[:200]],
        descricao,
        recomendacao.get('prioridade', 'normal'),
        recomendacao.get('confianca'),
        'decidir_recomendacao_conselho',
        exige_aprovacao=True,
        executar_em=executar_em,
    )
    if precisa_diretor:
        item['estado'] = 'precisa_diretor'
    return item


def atividades_pendentes_fila(cur):
    cur.execute(
        "SELECT origem, origem_id, tipo_decisao, fatos, inferencia, prioridade, confianca, "
        "proxima_acao, exige_aprovacao, executar_em, estado, chave FROM mi_fila_operacional "
        "WHERE origem='conselho' AND estado NOT IN ('concluida','bloqueada') "
        "ORDER BY criado_em DESC LIMIT 50"
    )
    atividades = []
    for row in cur.fetchall():
        item = dict(row)
        item['motivo'] = item.get('inferencia')
        item['lead_id'] = None
        item['estabelecimento_id'] = None
        atividades.append(item)
    return atividades


def _ultima_versao_apenas(cur, tipos, limite):
    placeholders = ",".join(["%s"] * len(tipos))
    cur.execute(
        "SELECT * FROM mi_conselho_registros r WHERE tipo IN (" + placeholders + ") "
        "AND NOT EXISTS (SELECT 1 FROM mi_conselho_registros r2 WHERE r2.registro_anterior_id = r.id) "
        "ORDER BY criado_em DESC LIMIT %s",
        (*tipos, limite),
    )
    return [dict(r) for r in cur.fetchall()]


def status_agentes(cur, dias=14):
    cur.execute(
        "SELECT payload->>'agente' AS agente, tipo_evento, criado_em FROM mi_sinais "
        "WHERE origem='conselho' AND payload ? 'agente' "
        "AND criado_em >= NOW() - (%s || ' days')::interval "
        "ORDER BY criado_em DESC",
        (dias,),
    )
    ultima_por_agente = {}
    for row in cur.fetchall():
        agente = row.get('agente')
        if agente in AGENTES and agente not in ultima_por_agente:
            ultima_por_agente[agente] = {'tipo_evento': row['tipo_evento'], 'criado_em': row['criado_em']}

    status = []
    for codigo, info in AGENTES.items():
        atividade = ultima_por_agente.get(codigo)
        status.append({
            'codigo': codigo, 'nome': info['nome'], 'area': info['area'],
            'status': 'trabalhando' if atividade else 'sem_demanda',
            'ultima_atividade': atividade,
        })
    return status


# =====================================================
# LOOP DE APRENDIZADO -- DEMANDA -> DECISAO -> ACAO -> RESULTADO ->
# EVIDENCIA -> AVALIACAO. Reaproveita mi_sinais (natureza='resultado', já
# prevista no barramento desde a ETAPA 4.9) -- nenhuma tabela nova. Só um
# humano chama isto: dizer que uma hipótese foi confirmada/refutada é
# julgamento humano, nunca inferido automaticamente só porque uma ação foi
# executada (`emitir` também nunca propaga exceção -- falha aqui é
# observabilidade perdida, nunca um erro que trava o Admin).
# =====================================================

HIPOTESES_RESULTADO = ('confirmada', 'refutada', 'inconclusiva')


def registrar_resultado_recomendacao(factory, body):
    """Liga o resultado observado de uma recomendação de volta ao registro
    (ata/relatório) que a originou. Não promove nada automaticamente: só
    persiste o que um humano observou e como ele classificou a hipótese."""
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    registro_id = str(UUID(str(body.get('registro_id'))))

    resultado_observado = body.get('resultado_observado')
    if not isinstance(resultado_observado, str) or not resultado_observado.strip():
        raise ValueError('resultado_observado_obrigatorio')

    resultado_esperado = body.get('resultado_esperado')
    if resultado_esperado is not None and not isinstance(resultado_esperado, str):
        raise ValueError('resultado_esperado_invalido')

    hipotese = body.get('hipotese')
    if hipotese is not None and hipotese not in HIPOTESES_RESULTADO:
        raise ValueError('hipotese_invalida')

    ator = body.get('ator')
    if not isinstance(ator, str) or not ator.strip():
        raise ValueError('ator_obrigatorio')

    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            cur.execute("SELECT id, demanda FROM mi_conselho_registros WHERE id=%s", (registro_id,))
            registro = cur.fetchone()
    finally:
        conn.close()
    if not registro:
        return {'success': False, 'motivo': 'registro_nao_encontrado'}

    emitido = emitir(
        factory, natureza='resultado', origem='conselho', tipo_evento='resultado_recomendacao',
        origem_id=registro_id,
        payload={
            'demanda': registro['demanda'], 'resultado_esperado': resultado_esperado,
            'resultado_observado': resultado_observado.strip(), 'hipotese': hipotese, 'ator': ator.strip(),
        },
    )
    if emitido is None:
        return {'success': False, 'motivo': 'falha_ao_registrar_sinal'}
    corpo, _status = emitido
    return {**corpo, 'registro_id': registro_id}


def historico_resultados(cur, registro_id, limite=20):
    """Todos os resultados já observados para UM registro -- histórico
    completo, nunca só o mais recente (uma recomendação pode ter sido
    reavaliada mais de uma vez)."""
    cur.execute(
        "SELECT payload, criado_em FROM mi_sinais WHERE origem='conselho' "
        "AND tipo_evento='resultado_recomendacao' AND origem_id=%s "
        "ORDER BY criado_em DESC LIMIT %s",
        (str(registro_id), limite),
    )
    return [dict(r) for r in cur.fetchall()]


def _resultados_recentes(cur, limite):
    cur.execute(
        "SELECT origem_id, payload, criado_em FROM mi_sinais WHERE origem='conselho' "
        "AND tipo_evento='resultado_recomendacao' ORDER BY criado_em DESC LIMIT %s",
        (limite,),
    )
    return [dict(r) for r in cur.fetchall()]


def leitura_conselho(factory, limite=10):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            agentes = status_agentes(cur)
            cur.execute(
                "SELECT * FROM mi_conselho_mensagens ORDER BY criado_em DESC LIMIT %s", (limite,)
            )
            mensagens = [dict(r) for r in cur.fetchall()]
            reunioes = _ultima_versao_apenas(cur, ('reuniao', 'conclave'), limite)
            relatorios = _ultima_versao_apenas(cur, ('relatorio',), limite)
            resultados_recentes = _resultados_recentes(cur, limite)
    finally:
        conn.close()

    conflitos = [{'registro_id': str(r['id']), 'tipo': r['tipo'], 'conflitos': r['conflitos']}
                 for r in reunioes if r.get('conflitos')]
    vetos = [{'registro_id': str(r['id']), 'tipo': r['tipo'], 'vetos': r['vetos']}
             for r in reunioes if r.get('vetos')]
    aguardando_diretor = [r for r in (reunioes + relatorios) if r.get('precisa_diretor')]

    return {
        'agentes': agentes,
        'trabalhando': sum(1 for a in agentes if a['status'] == 'trabalhando'),
        'sem_demanda': sum(1 for a in agentes if a['status'] == 'sem_demanda'),
        'mensagens_recentes': mensagens,
        'reunioes_recentes': reunioes,
        'relatorios_recentes': relatorios,
        'conflitos': conflitos,
        'vetos': vetos,
        'aguardando_diretor': aguardando_diretor,
        'resultados_recentes': resultados_recentes,
    }


def registrar_rotas_conselho(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/conselho', methods=['GET'])
    def mi_conselho():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(success=True, conselho=leitura_conselho(factory))
        except Exception:
            app.logger.exception('Falha ao gerar leitura do Conselho de Agentes')
            return jsonify(success=False, error='Conselho indisponível.'), 503

    @app.route('/api/admin/mi/conselho/resultado', methods=['POST'])
    def mi_conselho_registrar_resultado():
        # Loop de aprendizado: SEMPRE uma escrita humana explícita -- nenhum
        # caminho automático desta aplicação chama esta rota.
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            resultado = registrar_resultado_recomendacao(factory, request.get_json(force=True, silent=True) or {})
        except ValueError as erro:
            return jsonify(success=False, error=str(erro)), 400
        except Exception:
            app.logger.exception('Falha ao registrar resultado de recomendação do Conselho')
            return jsonify(success=False, error='Não foi possível registrar o resultado.'), 503
        if not resultado.get('success', True):
            status = 404 if resultado.get('motivo') == 'registro_nao_encontrado' else 503
            return jsonify(resultado), status
        return jsonify(resultado), 201

    # A camada interativa reutiliza o mesmo Conselho e a mesma autenticação.
    from mi_conselho_interativo import registrar_rotas_conselho_interativo
    registrar_rotas_conselho_interativo(app, factory, autorizado)
