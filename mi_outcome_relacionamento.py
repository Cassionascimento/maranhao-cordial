"""P3A/P3B -- Outcome measurement e Learning Dataset.

SIGNAL -> SCORE -> RECOMMENDATION -> HUMAN DECISION -> ACTION -> OUTCOME.

Reaproveita 100% de `mi_fila_operacional` (migrations 014/015) através das
funções já existentes e testadas em `mi_decisao.py`
(`chave_atividade`/`registrar_item_fila`/`avancar_estado_fila`) --
NENHUMA tabela nova é criada aqui. O corpo do item de fila reaproveita
`mi_inteligencia_relacionamento.recomendacao_para_item_fila` (P2F), só
acrescentando a versão do score/regra dentro de `fatos` (lista de strings
que o schema já aceita) -- nenhuma coluna nova.

Mapeamento HUMAN DECISION / ACTION / OUTCOME sobre os estados que já
existem (nenhum estado novo foi inventado):
- REJEITADA -> `bloqueada` (terminal, nunca executada).
- ACEITA, ainda sem execução conhecida -> fica em `aguardando` (só grava
  a decisão na auditoria já existente, mesmo padrão de
  `mi_decisao.reagendar_automaticamente`: estado_anterior == estado_novo
  quando o evento não muda o estado).
- OUTCOME conhecido (executada ou não) -> `concluida`, com `resultado`
  carregando o que de fato aconteceu -- nunca reabre um item já concluído
  ou bloqueado (garantia já embutida em `avancar_estado_fila`/
  `TRANSICOES_PERMITIDAS`).

Nenhuma ação comercial externa é disparada por este módulo -- ele só
registra o que um humano decidiu e o que foi observado depois; execução
real continua exclusivamente em `acoes_comerciais.py`.
"""
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import RealDictCursor

from mi_decisao import ESTADOS_FILA as ESTADOS_FILA_VALIDOS
from mi_decisao import avancar_estado_fila, chave_atividade, registrar_item_fila
from mi_inteligencia_relacionamento import (VERSAO_SCORE, inteligencia_do_relacionamento,
                                             recomendacao_para_item_fila)
from mi_relacionamento_360 import relacionamento_360

MAX_RECOMENDACOES_APRESENTADAS = 3

REGRA_VERSAO = 'mi_inteligencia_relacionamento_v1'
LEARNING_DATASET_VERSAO = 'relacionamento_learning_v1'
ORIGEM_RELACIONAMENTO = 'relacionamento_360'


# =====================================================================
# P3A -- SIGNAL -> SCORE -> RECOMMENDATION (apresentação)
# =====================================================================

def registrar_recomendacao_apresentada(factory, recomendacao, score, lead_id=None,
                                        estabelecimento_id=None, agora=None):
    """Grava a recomendação apresentada (P2E) com a versão do score (P2B) e
    da regra preservadas dentro de `fatos` -- nada é perdido, nenhuma
    coluna nova. Idempotente por dia (mesma chave de `chave_atividade`):
    apresentar a mesma recomendação de novo no mesmo dia nunca duplica."""
    agora = agora or datetime.now(timezone.utc)
    item = recomendacao_para_item_fila(recomendacao, lead_id=lead_id, estabelecimento_id=estabelecimento_id)
    item['fatos'] = list(item['fatos']) + [
        f"score_versao={score.get('versao', VERSAO_SCORE)}",
        f"regra_versao={REGRA_VERSAO}",
        f"score_geral={score.get('score_geral')}",
    ]
    item['chave'] = chave_atividade(item, agora)
    resultado, status = registrar_item_fila(factory, item)
    return {**resultado, 'chave': item['chave']}, status


def calcular_e_apresentar_recomendacoes(factory, entidade_id, limite=MAX_RECOMENDACOES_APRESENTADAS, agora=None):
    """P4 -- orquestração pura: liga P1B (360) + P2 (inteligência) + P3A
    (apresentação/outcome) sem adicionar nenhuma peça de inteligência nova.
    Fecha o atrito de hoje, em que um chamador precisa fazer 3 chamadas
    manuais (360 -> inteligência -> apresentar) copiando score/recomendação
    à mão entre elas. Cada leitura usa sua própria conexão curta (mesmo
    padrão já usado em todo o P0-P3 -- nunca compartilha uma conexão entre
    chamadas de módulos diferentes)."""
    agora = agora or datetime.now(timezone.utc)
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            visao = relacionamento_360(cur, entidade_id, agora=agora)
    finally:
        conn.close()
    if not visao:
        return None
    inteligencia = inteligencia_do_relacionamento(visao, entidade_id, agora=agora)
    lead = visao.get('identity', {}).get('pessoa')
    estabelecimento = visao.get('organization')
    apresentadas = []
    for recomendacao in inteligencia['next_best_actions'][:limite]:
        if recomendacao['action'] == 'NO_ACTION':
            continue
        resultado, status = registrar_recomendacao_apresentada(
            factory, recomendacao, inteligencia['score'],
            lead_id=(lead or {}).get('id'), estabelecimento_id=(estabelecimento or {}).get('id'), agora=agora,
        )
        apresentadas.append({'recomendacao': recomendacao, 'registro': resultado, 'status': status})
    return {'relationship_id': entidade_id, 'inteligencia': inteligencia, 'recomendacoes_apresentadas': apresentadas}


# =====================================================================
# HUMAN DECISION
# =====================================================================

def registrar_decisao_humana(factory, chave, aceita, ator, motivo=None):
    if not aceita:
        return avancar_estado_fila(factory, chave, 'bloqueada', ator,
                                    resultado={'decisao_humana': 'rejeitada', 'motivo': motivo, 'ator': ator})
    chave = str(UUID(str(chave)))
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, estado FROM mi_fila_operacional WHERE chave=%s", (chave,))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'motivo': 'item_nao_encontrado'}
                cur.execute(
                    "INSERT INTO mi_fila_operacional_auditoria(item_id,estado_anterior,estado_novo,ator) "
                    "VALUES(%s,%s,%s,%s)",
                    (row['id'], row['estado'], row['estado'], ator),
                )
                return {'success': True, 'decisao_humana': 'aceita', 'estado': row['estado']}
    finally:
        conn.close()


# =====================================================================
# ACTION -> OUTCOME
# =====================================================================

def registrar_outcome(factory, chave, resultado_observado, ator, executada):
    """`executada` é sempre explícito (True/False) -- nunca inferido. Um
    resultado_observado=None ainda é um outcome válido (ex.: 'aceita, mas
    ainda sem efeito mensurável') -- não é confundido com ausência de
    registro."""
    resultado = dict(resultado_observado or {})
    resultado['executada'] = bool(executada)
    resultado['ator'] = ator
    return avancar_estado_fila(factory, chave, 'concluida', ator, resultado=resultado)


# =====================================================================
# Leitura -- histórico e dataset de aprendizado (P3B)
# =====================================================================

def historico_decisoes(cur, limite=100, lead_id=None, estabelecimento_id=None, estado=None):
    """`lead_id`/`estabelecimento_id` (P4) e `estado` (P5) são filtros
    OPCIONAIS -- sem eles, comportamento idêntico ao de antes
    (compatibilidade preservada)."""
    condicoes = ['origem=%s']
    parametros = [ORIGEM_RELACIONAMENTO]
    if lead_id is not None:
        condicoes.append('lead_id=%s')
        parametros.append(str(UUID(str(lead_id))))
    if estabelecimento_id is not None:
        condicoes.append('estabelecimento_id=%s')
        parametros.append(str(UUID(str(estabelecimento_id))))
    if estado is not None:
        if estado not in ESTADOS_FILA_VALIDOS:
            raise ValueError('estado_invalido')
        condicoes.append('estado=%s')
        parametros.append(estado)
    parametros.append(limite)
    cur.execute(
        "SELECT chave, tipo_decisao, fatos, inferencia, prioridade, confianca, proxima_acao, estado, "
        "resultado, lead_id, estabelecimento_id, criado_em, atualizado_em, concluido_em "
        "FROM mi_fila_operacional WHERE " + ' AND '.join(condicoes) + " ORDER BY criado_em DESC LIMIT %s",
        parametros,
    )
    return [dict(r) for r in cur.fetchall()]


def _extrair_fato(fatos, prefixo):
    return next((f.split('=', 1)[1] for f in (fatos or []) if f.startswith(prefixo + '=')), None)


def _decisao_humana_de_estado(estado):
    """Única fonte de verdade para mapear estado de mi_fila_operacional em
    decisão humana legível -- usada por exportar_dataset_aprendizado (P3B)
    e pelo contrato canônico do painel (P5), nunca duplicada."""
    if estado == 'bloqueada':
        return 'rejeitada'
    if estado == 'concluida':
        return 'aceita'
    return 'pendente'


def exportar_dataset_aprendizado(cur, limite=500):
    """Learning dataset versionado (`LEARNING_DATASET_VERSAO`) -- projeção
    somente leitura sobre `mi_fila_operacional`, nenhuma tabela nova,
    nenhum dado inventado. Enquanto `mi_fila_operacional` não tiver
    nenhuma linha real (persistência era dormente até este P3), o dataset
    vem vazio de forma explícita -- nunca um valor fabricado no lugar."""
    linhas_brutas = historico_decisoes(cur, limite=limite)
    linhas = []
    for d in linhas_brutas:
        linhas.append({
            'chave': d['chave'],
            'signal_evidence': d['fatos'],
            'score_versao': _extrair_fato(d['fatos'], 'score_versao'),
            'regra_versao': _extrair_fato(d['fatos'], 'regra_versao'),
            'score_geral_no_momento': _extrair_fato(d['fatos'], 'score_geral'),
            'recommendation': d['proxima_acao'],
            'recommendation_confidence': d['confianca'],
            'human_decision': _decisao_humana_de_estado(d['estado']),
            'executada': (d['resultado'] or {}).get('executada') if d['resultado'] else None,
            'outcome': d['resultado'],
            'lead_id': str(d['lead_id']) if d['lead_id'] else None,
            'estabelecimento_id': str(d['estabelecimento_id']) if d['estabelecimento_id'] else None,
            'apresentada_em': d['criado_em'], 'concluido_em': d['concluido_em'],
        })
    return {'dataset_versao': LEARNING_DATASET_VERSAO, 'total_linhas': len(linhas), 'linhas': linhas}


def contagem_por_estado(cur):
    """Agregação barata (1 query, sem loop) do estado atual da fila de
    decisões do relacionamento -- usada pela Overview (P5) para nunca
    precisar escanear/recomputar por relacionamento."""
    cur.execute(
        "SELECT estado, COUNT(*)::INTEGER AS total FROM mi_fila_operacional WHERE origem=%s GROUP BY estado",
        (ORIGEM_RELACIONAMENTO,),
    )
    contagens = {estado: 0 for estado in ESTADOS_FILA_VALIDOS}
    for linha in cur.fetchall():
        contagens[linha['estado']] = linha['total']
    return contagens


# =====================================================================
# Rotas -- únicas com efeito de escrita em todo o P0-P3 (só sobre
# mi_fila_operacional; nunca checkout/WhatsApp/Gmail/Meta/C6-Pix)
# =====================================================================

def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/relacionamento/recomendacao/apresentar', methods=['POST'])
    def mi_outcome_apresentar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        try:
            resultado, status = registrar_recomendacao_apresentada(
                factory, corpo.get('recomendacao') or {}, corpo.get('score') or {},
                lead_id=corpo.get('lead_id'), estabelecimento_id=corpo.get('estabelecimento_id'),
            )
        except (ValueError, KeyError, TypeError) as erro:
            return jsonify(success=False, error=f'Corpo inválido: {erro}'), 400
        except Exception:
            app.logger.exception('Falha ao registrar recomendação apresentada')
            return jsonify(success=False, error='Não foi possível registrar a recomendação.'), 503
        resultado.pop('success', None)
        return jsonify(success=True, **resultado), status

    @app.route('/api/admin/mi/relacionamento/<entidade_id>/inteligencia/apresentar', methods=['POST'])
    def mi_outcome_calcular_e_apresentar(entidade_id):
        """P4: calcula a inteligência (P1B+P2) e já apresenta/registra as
        recomendações (P3A) numa única chamada -- nunca decide nem executa
        nada sozinho; aprovação humana continua exigindo a chamada
        separada a /recomendacao/decisao."""
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            resultado = calcular_e_apresentar_recomendacoes(factory, entidade_id)
        except Exception:
            app.logger.exception('Falha ao calcular e apresentar recomendações')
            return jsonify(success=False, error='Não foi possível calcular e apresentar recomendações.'), 503
        if not resultado:
            return jsonify(success=False, error='Relacionamento não encontrado.'), 404
        return jsonify(success=True, **resultado)

    @app.route('/api/admin/mi/relacionamento/recomendacao/decisao', methods=['POST'])
    def mi_outcome_decisao():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        try:
            resultado = registrar_decisao_humana(
                factory, corpo.get('chave'), bool(corpo.get('aceita')),
                corpo.get('ator') or 'desconhecido', motivo=corpo.get('motivo'),
            )
        except (ValueError, TypeError) as erro:
            return jsonify(success=False, error=f'Corpo inválido: {erro}'), 400
        except Exception:
            app.logger.exception('Falha ao registrar decisão humana')
            return jsonify(success=False, error='Não foi possível registrar a decisão.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            return jsonify(success=False, **resultado), 409
        return jsonify(success=True, **resultado)

    @app.route('/api/admin/mi/relacionamento/recomendacao/outcome', methods=['POST'])
    def mi_outcome_resultado():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        if 'executada' not in corpo:
            return jsonify(success=False, error='Informe "executada" (true/false) explicitamente.'), 400
        try:
            resultado = registrar_outcome(
                factory, corpo.get('chave'), corpo.get('resultado_observado'),
                corpo.get('ator') or 'desconhecido', bool(corpo.get('executada')),
            )
        except (ValueError, TypeError) as erro:
            return jsonify(success=False, error=f'Corpo inválido: {erro}'), 400
        except Exception:
            app.logger.exception('Falha ao registrar outcome')
            return jsonify(success=False, error='Não foi possível registrar o outcome.'), 503
        sucesso = resultado.pop('success', False)
        if not sucesso:
            return jsonify(success=False, **resultado), 409
        return jsonify(success=True, **resultado)

    @app.route('/api/admin/mi/relacionamento/decisoes', methods=['GET'])
    def mi_outcome_historico():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                historico = historico_decisoes(cur, lead_id=request.args.get('lead_id'),
                                                estabelecimento_id=request.args.get('estabelecimento_id'),
                                                estado=request.args.get('estado'))
        except ValueError:
            return jsonify(success=False, error='lead_id/estabelecimento_id/estado inválido.'), 400
        except Exception:
            app.logger.exception('Falha ao ler histórico de decisões')
            return jsonify(success=False, error='Histórico indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, decisoes=historico)

    @app.route('/api/admin/mi/relacionamento/dataset-aprendizado', methods=['GET'])
    def mi_outcome_dataset():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                dataset = exportar_dataset_aprendizado(cur)
        except Exception:
            app.logger.exception('Falha ao exportar dataset de aprendizado')
            return jsonify(success=False, error='Dataset indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, **dataset)
