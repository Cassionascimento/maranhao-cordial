"""P5 -- Intelligence Core API: fecha o backend para o futuro painel.

NENHUMA lógica de inteligência nova é criada aqui -- este módulo só
INTEGRA e REFORMATA o que P0-P4 já calculam, já persistem e já testam:

- identidade/organização/comercial/produto/comportamento/geografia ->
  mi_relacionamento_360.relacionamento_360() (P1B)
- sinais/score/segmentos/oportunidades/next best actions ->
  mi_inteligencia_relacionamento.inteligencia_do_relacionamento() (P2)
- recomendações apresentadas/decisão humana/outcome/dataset ->
  mi_outcome_relacionamento (P3A/P3B/P4) -- reaproveita
  historico_decisoes/_decisao_humana_de_estado/exportar_dataset_
  aprendizado/contagem_por_estado, nunca duplica a query ou a regra
- território -> mi_territorio_inteligencia.oportunidades_territoriais() (P3C)
- forecast readiness -> mi_forecast_readiness.montar_forecast_readiness() (P3D)

Só leitura -- nenhuma rota de escrita neste módulo. Território e forecast
readiness são cálculos de escopo GLOBAL do negócio (não de UM
relacionamento) e por isso são OPT-IN via query param no contrato
canônico -- computá-los em toda leitura de relacionamento seria o N+1/
"chamada cara óbvia" que esta fase pede para evitar.
"""
from datetime import datetime, timezone

from mi_inteligencia_relacionamento import inteligencia_do_relacionamento
from mi_outcome_relacionamento import (
    LEARNING_DATASET_VERSAO,
    _decisao_humana_de_estado,
    contagem_por_estado,
    exportar_dataset_aprendizado,
    historico_decisoes,
)
from mi_relacionamento_360 import relacionamento_360

CONTRATO_VERSAO = 'intelligence_contract_v1'
LEARNING_MINIMO_LINHAS_NEGOCIO = 20  # limiar para "pronto para aprender" em nível de negócio (Overview)
AMOSTRA_PADRAO_OVERVIEW = 50  # tamanho máximo da amostra usada para distribuição de segmentos/oportunidades


def _provenance_identidade(lead):
    if lead is None:
        return 'UNKNOWN'
    if lead.get('cadastro_teste'):
        return 'SYNTHETIC_TEST'
    return 'REAL'


# =====================================================================
# Item 1 -- CONTRATO CANÔNICO DE INTELLIGENCE (por relacionamento)
# =====================================================================

def contrato_canonico(cur, entidade_id, agora=None):
    """Uma única leitura por relacionamento -- MESMA conexão/cursor para
    360 e histórico de decisões (evita abrir uma segunda conexão só para
    o histórico; ver PERFORMANCE no relatório de entrega). Território e
    forecast_readiness saem como 'not_requested' aqui -- quem tem
    `factory` (a rota) decide se vale o custo de computá-los, nunca este
    núcleo puro."""
    agora = agora or datetime.now(timezone.utc)
    visao = relacionamento_360(cur, entidade_id, agora=agora)
    if not visao:
        return None
    inteligencia = inteligencia_do_relacionamento(visao, entidade_id, agora=agora)

    lead = visao.get('identity', {}).get('pessoa')
    estabelecimento = visao.get('organization')
    historico = historico_decisoes(cur, lead_id=(lead or {}).get('id'),
                                    estabelecimento_id=(estabelecimento or {}).get('id'))

    recomendacoes, decisoes_humanas, outcomes = [], [], []
    for item in historico:
        decisao = _decisao_humana_de_estado(item['estado'])
        recomendacoes.append({
            'chave': item['chave'], 'recommendation': item['proxima_acao'], 'reason': item['inferencia'],
            'evidence': item['fatos'], 'priority': item['prioridade'], 'confidence': item['confianca'],
            'status': item['estado'], 'generated_at': item['criado_em'], 'necessidade_de_aprovacao': True,
        })
        decisoes_humanas.append({
            'chave': item['chave'], 'decision': decisao,
            'decided_at': item['concluido_em'] if decisao != 'pendente' else None,
        })
        if item['estado'] == 'concluida':
            outcomes.append({'chave': item['chave'], 'outcome': item['resultado'],
                              'concluded_at': item['concluido_em']})

    learning_status = {
        'dataset_versao': LEARNING_DATASET_VERSAO,
        'decisoes_registradas': len(historico),
        'outcomes_disponiveis': len(outcomes),
        'ready': bool(historico) and bool(outcomes),
        'motivo': ('nenhuma recomendação apresentada para este relacionamento ainda' if not historico
                   else ('nenhum outcome registrado ainda' if not outcomes
                         else f'{len(outcomes)} outcome(s) disponível(is)')),
    }

    score = inteligencia['score']
    nba_validas = [n for n in inteligencia['next_best_actions'] if n['action'] != 'NO_ACTION']
    explicabilidade = None
    if nba_validas:
        principal = nba_validas[0]
        explicabilidade = {
            'recommendation': principal['action'], 'motivo_principal': principal['reason'],
            'evidencias': principal['evidence'],
            'dimensoes_do_score': {k: v['explicacao'] for k, v in score['dimensoes'].items()},
            'segmentos_associados': [s['segmento'] for s in inteligencia['segments']],
        }

    return {
        'contrato_versao': CONTRATO_VERSAO,
        'relationship_id': entidade_id,
        'identity': visao['identity'],
        'organization': visao['organization'],
        'relationship_360': {
            'relationship': visao['relationship'], 'commercial': visao['commercial'],
            'products': visao['products'], 'behavior': visao['behavior'],
            'geography': visao['geography'], 'derived_metrics': visao['derived_metrics'],
        },
        'data_quality': visao['data_quality'],
        'provenance': {
            'identity': _provenance_identidade(lead),
            'organization': 'REAL' if estabelecimento else 'UNKNOWN',
            'signals': 'DERIVED', 'score': 'DERIVED', 'segments': 'DERIVED', 'opportunities': 'DERIVED',
            'recommendations': 'REAL' if recomendacoes else 'NOT_ENOUGH_DATA',
            'human_decisions': 'REAL' if decisoes_humanas else 'NOT_ENOUGH_DATA',
            'outcomes': 'REAL' if outcomes else 'NOT_ENOUGH_DATA',
            'territory': 'not_requested', 'forecast_readiness': 'not_requested',
        },
        'signals': inteligencia['signals'],
        'score': score['score_geral'], 'score_version': score['versao'], 'confidence': score['confianca_geral'],
        'score_dimensions': score['dimensoes'],
        'segments': inteligencia['segments'],
        'opportunities': inteligencia['opportunities'],
        'next_best_actions': inteligencia['next_best_actions'],
        'recommendations': recomendacoes,
        'human_decisions': decisoes_humanas,
        'operational_status': {
            'pendente_decisao': sum(1 for h in historico if h['estado'] == 'aguardando'),
            'bloqueadas': sum(1 for h in historico if h['estado'] == 'bloqueada'),
            'concluidas': sum(1 for h in historico if h['estado'] == 'concluida'),
            'tem_recomendacao_ativa': any(h['estado'] == 'aguardando' for h in historico),
        },
        'outcomes': outcomes,
        'learning_status': learning_status,
        'territory': 'not_requested',
        'forecast_readiness': 'not_requested',
        'explainability': explicabilidade,
    }


def anexar_territorio(contrato, visao_gerada_territorio):
    """Só chamado pela rota quando `?incluir_territorio=1` -- reaproveita
    mi_territorio_inteligencia.oportunidades_territoriais() já pronto
    (P3C), nunca recalcula agregação territorial aqui. Tenta casar pela
    cidade/UF do relacionamento; sem correspondência, fica NOT_ENOUGH_DATA
    -- nunca atribui um território que não bateu."""
    cidade = (contrato['relationship_360']['geography'] or {}).get('cidade')
    uf = (contrato['relationship_360']['geography'] or {}).get('uf')
    if not cidade and not uf:
        contrato['territory'] = 'NOT_ENOUGH_DATA'
        contrato['provenance']['territory'] = 'NOT_ENOUGH_DATA'
        return contrato
    alvo = f'{cidade}/{uf}'
    correspondencia = [o for o in (visao_gerada_territorio.get('opportunities') or [])
                        if o.get('territory') and (o['territory'] == alvo or (cidade and cidade in (o['territory'] or '')))]
    contrato['territory'] = correspondencia if correspondencia else 'NOT_ENOUGH_DATA'
    contrato['provenance']['territory'] = 'DERIVED' if correspondencia else 'NOT_ENOUGH_DATA'
    return contrato


def anexar_forecast_readiness(contrato, forecast_readiness):
    """Só chamado pela rota quando `?incluir_forecast=1` -- reaproveita
    mi_forecast_readiness.montar_forecast_readiness() (P3D), que é sempre
    um cálculo de negócio inteiro (nunca por relacionamento)."""
    contrato['forecast_readiness'] = forecast_readiness
    contrato['provenance']['forecast_readiness'] = 'DERIVED'
    return contrato


# =====================================================================
# Item 3 -- DECISION QUEUE canônica para o painel
# =====================================================================

def fila_decisao(cur, limite=100):
    """Reaproveita historico_decisoes(estado='aguardando') (já existente
    desde P3/P4) -- só reformata os nomes de campo para o que o painel
    precisa. Nenhuma recomendação aqui já foi decidida ou executada."""
    pendentes = historico_decisoes(cur, estado='aguardando', limite=limite)
    return [{
        'chave': item['chave'], 'relationship_id': item['lead_id'] or item['estabelecimento_id'],
        'lead_id': item['lead_id'], 'estabelecimento_id': item['estabelecimento_id'],
        'recommendation': item['proxima_acao'], 'reason': item['inferencia'], 'evidence': item['fatos'],
        'priority': item['prioridade'], 'confidence': item['confianca'], 'status': item['estado'],
        'generated_at': item['criado_em'], 'necessidade_de_aprovacao': True,
    } for item in pendentes]


# =====================================================================
# Item 2 -- OVERVIEW (visão executiva agregada)
# =====================================================================

def _amostra_de_leads(cur, limite):
    cur.execute(
        "SELECT id FROM leads_crm WHERE COALESCE(cadastro_teste, FALSE) = FALSE "
        "ORDER BY atualizado_em DESC LIMIT %s",
        (limite,),
    )
    return [str(r['id']) for r in cur.fetchall()]


def _contagem_dados_suficientes(cur):
    """Barato e sem loop -- proxy real (não a pipeline de score inteira)
    de quantos relacionamentos já têm ALGUMA evidência comportamental ou
    comercial. 'Dados suficientes' aqui é sobre EXISTÊNCIA de evidência,
    não sobre o score em si (isso exigiria rodar a pipeline completa por
    lead -- ver PERFORMANCE no relatório)."""
    cur.execute("SELECT COUNT(*)::INTEGER AS total FROM leads_crm WHERE COALESCE(cadastro_teste, FALSE) = FALSE")
    total = cur.fetchone()['total']
    cur.execute(
        "SELECT COUNT(DISTINCT lead_id)::INTEGER AS total FROM interacoes_omnichannel WHERE lead_id IS NOT NULL"
    )
    com_interacao = cur.fetchone()['total']
    cur.execute("SELECT COUNT(DISTINCT contato_id)::INTEGER AS total FROM compras_relacionamento")
    com_compra = cur.fetchone()['total']
    cur.execute(
        "SELECT COUNT(DISTINCT lead_id)::INTEGER AS total FROM ("
        "  SELECT lead_id FROM interacoes_omnichannel WHERE lead_id IS NOT NULL"
        "  UNION SELECT contato_id AS lead_id FROM compras_relacionamento"
        ") unificado"
    )
    com_evidencia = cur.fetchone()['total']
    return {
        'total_pessoas': total, 'com_interacao': com_interacao, 'com_compra': com_compra,
        'dados_suficientes': com_evidencia, 'dados_insuficientes': max(total - com_evidencia, 0),
    }


def visao_executiva(cur, amostra_limite=AMOSTRA_PADRAO_OVERVIEW, agora=None):
    """Overview -- verificado antes de criar: mi_painel.py cobre a camada
    de fábrica (SKU/lote/unidade/estabelecimento), mi_diretor.py cobre a
    leitura de governança do Conselho; NENHUM dos dois agrega relacionamento
    x inteligência x decisão x outcome x território x forecast. Esta é a
    consolidação que faltava (P5), reaproveitando os módulos já existentes.

    Distribuição de segmentos/oportunidades é calculada sobre uma AMOSTRA
    limitada (mais recentes primeiro, `amostra_limite`), nunca a base
    inteira -- rodar a pipeline de score/segmento por lead é caro; escanear
    toda a base a cada requisição de Overview seria o N+1 que esta fase
    pede para evitar. A amostra é sempre explícita na resposta."""
    agora = agora or datetime.now(timezone.utc)
    dados = _contagem_dados_suficientes(cur)

    ids_amostra = _amostra_de_leads(cur, amostra_limite)
    segmentos_contagem, oportunidades_contagem = {}, {}
    for lead_id in ids_amostra:
        visao = relacionamento_360(cur, lead_id, agora=agora)
        if not visao:
            continue
        inteligencia = inteligencia_do_relacionamento(visao, lead_id, agora=agora)
        for seg in inteligencia['segments']:
            segmentos_contagem[seg['segmento']] = segmentos_contagem.get(seg['segmento'], 0) + 1
        for op in inteligencia['opportunities']:
            oportunidades_contagem[op['type']] = oportunidades_contagem.get(op['type'], 0) + 1

    fila = contagem_por_estado(cur)
    dataset = exportar_dataset_aprendizado(cur)
    learning_ready = dataset['total_linhas'] >= LEARNING_MINIMO_LINHAS_NEGOCIO
    learning_status = {
        'dataset_versao': dataset['dataset_versao'], 'total_linhas_dataset': dataset['total_linhas'],
        'ready': learning_ready,
        'motivo': (f"{dataset['total_linhas']} linha(s) no dataset, mínimo de {LEARNING_MINIMO_LINHAS_NEGOCIO} exigido"
                   if not learning_ready else f"{dataset['total_linhas']} linha(s) -- volume mínimo atingido"),
    }

    return {
        'generated_at': agora.isoformat(),
        'relacionamentos_conhecidos': dados,
        'segmentos_distribuicao': segmentos_contagem,
        'oportunidades_detectadas': oportunidades_contagem,
        'amostra': {'tamanho': len(ids_amostra), 'limite': amostra_limite,
                    'nota': 'segmentos/oportunidades calculados sobre amostra recente, não a base inteira'},
        'fila_decisao': {
            'pendentes': fila['aguardando'], 'bloqueadas': fila['bloqueada'],
            'concluidas': fila['concluida'], 'precisa_diretor': fila['precisa_diretor'],
        },
        'outcomes_registrados': fila['concluida'],
        'learning_status': learning_status,
    }


# =====================================================================
# Rotas -- só leitura (nenhuma rota de escrita neste módulo)
# =====================================================================

def registrar_rotas_leitura(app, factory, autorizado):
    from flask import jsonify, request
    from psycopg2.extras import RealDictCursor

    @app.route('/api/admin/mi/relacionamento/<entidade_id>/contrato', methods=['GET'])
    def mi_intelligence_contrato(entidade_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                contrato = contrato_canonico(cur, entidade_id)
        except Exception:
            app.logger.exception('Falha ao montar contrato canônico de inteligência')
            return jsonify(success=False, error='Contrato de inteligência indisponível.'), 503
        finally:
            conn.close()
        if not contrato:
            return jsonify(success=False, error='Relacionamento não encontrado.'), 404

        if request.args.get('incluir_territorio') == '1':
            try:
                from inteligencia_territorial import carregar
                from mi_territorio_inteligencia import oportunidades_territoriais
                contrato = anexar_territorio(contrato, oportunidades_territoriais(carregar(factory)))
            except Exception:
                app.logger.exception('Falha ao anexar território ao contrato -- contrato segue sem território')
                contrato['territory'] = 'NOT_ENOUGH_DATA'

        if request.args.get('incluir_forecast') == '1':
            try:
                from mi_forecast_readiness import montar_forecast_readiness
                conn2 = factory()
                try:
                    conn2.set_session(readonly=True, isolation_level='REPEATABLE READ')
                    with conn2.cursor(cursor_factory=RealDictCursor) as cur2:
                        cur2.execute("SET LOCAL statement_timeout='15s'")
                        contrato = anexar_forecast_readiness(contrato, montar_forecast_readiness(cur2))
                finally:
                    conn2.close()
            except Exception:
                app.logger.exception('Falha ao anexar forecast readiness -- contrato segue sem forecast')
                contrato['forecast_readiness'] = 'NOT_ENOUGH_DATA'

        return jsonify(success=True, **contrato)

    @app.route('/api/admin/mi/overview', methods=['GET'])
    def mi_intelligence_overview():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            amostra_limite = max(1, min(int(request.args.get('amostra_limite', AMOSTRA_PADRAO_OVERVIEW)), 500))
        except ValueError:
            amostra_limite = AMOSTRA_PADRAO_OVERVIEW
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='20s'")
                resultado = visao_executiva(cur, amostra_limite=amostra_limite)
        except Exception:
            app.logger.exception('Falha ao montar overview de inteligência')
            return jsonify(success=False, error='Overview indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, **resultado)

    @app.route('/api/admin/mi/fila-decisao', methods=['GET'])
    def mi_intelligence_fila_decisao():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                pendentes = fila_decisao(cur)
        except Exception:
            app.logger.exception('Falha ao ler fila de decisão')
            return jsonify(success=False, error='Fila de decisão indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, pendentes=pendentes)
