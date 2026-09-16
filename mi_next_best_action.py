"""Next Best Action -- até 3 sugestões comerciais por lead, só com base em
evidência já registrada (leads_crm/interacoes_omnichannel/
acoes_comerciais_propostas). Motor de REGRAS determinístico, sem LLM: cada
sugestão é rastreável até linhas reais de banco, nunca um palpite.

NUNCA cria, aprova ou envia nada -- é puramente leitura + recomendação. Uma
ação real continua exigindo o funil já existente
(acoes_comerciais.propor -> decidir -> executar); este módulo só lê esse
funil para não duplicar recomendação de algo que já está proposto/feito
(dedupe) e para respeitar as travas de envio já existentes
(email_seguranca.verificar_travas_envio) quando a sugestão envolve email.

ESTIMATIVA/INFERÊNCIA nunca vira fato: toda sugestão carrega `evidencia`
(fatos concretos, nunca opinião) separada de `confianca` (força do sinal).
"""
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

MAX_SUGESTOES = 3
DIAS_ESTAGIO_AVANCADO_PARADO = 7
ESTAGIOS_AVANCADOS = ('negociacao', 'proposta', 'fechamento')
STATUS_ACAO_ATIVA = ('aguardando_aprovacao', 'aprovada', 'executando', 'enviada')
_INTERESSE_ALTO = ('alto', 'quente', 'interesse_alto')


def _dias_desde(quando, agora):
    if not quando:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return (agora - quando).days


def _acoes_por_email(cur, email):
    if not email:
        return []
    cur.execute(
        "SELECT id, status, dados->>'tipo' AS tipo, criado_em FROM acoes_comerciais_propostas "
        "WHERE lower(dados->>'destinatario')=lower(%s) ORDER BY criado_em DESC",
        (email,),
    )
    return [dict(linha) for linha in cur.fetchall()]


def _bloqueio_email(factory, email):
    """Reaproveita a trava de envio já existente (pausa global/ambiente,
    supressão por hard bounce) -- nunca reimplementa essa lógica aqui. Só
    roda quando a sugestão de fato envolve email e `factory` foi passado
    (rotas de teste sem factory real seguem sem essa checagem, nunca
    quebram por isso)."""
    if not email or not factory:
        return None
    try:
        from email_seguranca import EnvioBloqueado, verificar_travas_envio
    except Exception:
        return None
    try:
        verificar_travas_envio(factory, email)
        return None
    except EnvioBloqueado as bloqueio:
        return str(bloqueio) or 'envio_bloqueado'
    except Exception:
        return None


def sugestoes_lead(lead, interacoes, acoes, factory=None, agora=None):
    """Pura leitura de estruturas já carregadas -- não faz nenhuma query
    aqui dentro (quem chama monta `interacoes`/`acoes` via
    mi_visao_unica/_acoes_por_email), o que torna a regra 100% testável sem
    banco. `lead` é o dict de leads_crm; `interacoes` mais recente primeiro."""
    agora = agora or datetime.now(timezone.utc)
    ultima_interacao = interacoes[0] if interacoes else None
    tem_acao_primeiro_contato_ativa = any(
        a['tipo'] == 'primeiro_contato' and a['status'] in STATUS_ACAO_ATIVA for a in acoes
    )
    acao_pendente_aprovacao = next((a for a in acoes if a['status'] == 'aguardando_aprovacao'), None)
    bloqueio_email = _bloqueio_email(factory, lead.get('email'))

    candidatas = []

    if acao_pendente_aprovacao:
        candidatas.append({
            'tipo': 'aprovar_acao_pendente',
            'motivo': 'Já existe uma proposta de contato aguardando aprovação humana para este lead.',
            'evidencia': [f"proposta {acao_pendente_aprovacao['tipo']} criada em "
                          f"{acao_pendente_aprovacao['criado_em']}, status aguardando_aprovacao"],
            'confianca': 'alta', 'responsavel': 'Direção', 'bloqueio': bloqueio_email,
        })

    sinal_interesse_alto = ultima_interacao and (
        (ultima_interacao.get('interesse') or '').strip().lower() in _INTERESSE_ALTO
        or (ultima_interacao.get('classificacao') or '').strip().lower() in _INTERESSE_ALTO
    )
    if sinal_interesse_alto:
        dias = _dias_desde(ultima_interacao['criado_em'], agora)
        houve_acao_depois = any(a['criado_em'] and ultima_interacao['criado_em']
                                 and a['criado_em'] >= ultima_interacao['criado_em'] for a in acoes)
        if not houve_acao_depois:
            candidatas.append({
                'tipo': 'follow_up_interesse_alto',
                'motivo': f"Última interação ({ultima_interacao['canal']}, há {dias} dia(s)) sinalizou "
                          f"interesse alto e nenhuma ação comercial foi registrada depois.",
                'evidencia': [f"interacoes_omnichannel: canal={ultima_interacao['canal']}, "
                              f"interesse={ultima_interacao.get('interesse') or ultima_interacao.get('classificacao')}, "
                              f"em {ultima_interacao['criado_em']}"],
                'confianca': 'alta', 'responsavel': 'Leonard', 'bloqueio': bloqueio_email,
            })

    if (lead.get('estagio') or '').strip().lower() in ESTAGIOS_AVANCADOS:
        dias = _dias_desde(ultima_interacao['criado_em'] if ultima_interacao else lead.get('atualizado_em'), agora)
        if dias is not None and dias >= DIAS_ESTAGIO_AVANCADO_PARADO:
            candidatas.append({
                'tipo': 'retomar_contato_estagio_parado',
                'motivo': f"Lead em estágio '{lead['estagio']}' sem interação registrada há {dias} dias.",
                'evidencia': [f"leads_crm.estagio={lead['estagio']}",
                              f"última interação/atualização há {dias} dias"],
                'confianca': 'media', 'responsavel': 'Leonard', 'bloqueio': bloqueio_email,
            })

    if not interacoes and not tem_acao_primeiro_contato_ativa and (lead.get('status') or '').strip().lower() == 'ativo':
        candidatas.append({
            'tipo': 'primeiro_contato',
            'motivo': 'Lead ativo sem nenhuma interação registrada em nenhum canal até agora.',
            'evidencia': ['0 linhas em interacoes_omnichannel para este lead_id',
                          'nenhuma proposta de primeiro_contato ativa em acoes_comerciais_propostas'],
            'confianca': 'media', 'responsavel': 'Leonard', 'bloqueio': bloqueio_email,
        })

    return candidatas[:MAX_SUGESTOES]


def montar_sugestoes(cur, lead_id, factory=None, agora=None):
    from mi_visao_unica import _interacoes, _lead
    lead = _lead(cur, lead_id)
    if not lead:
        return None
    interacoes = _interacoes(cur, lead_id, limite=10)
    acoes = _acoes_por_email(cur, lead.get('email'))
    sugestoes = sugestoes_lead(lead, interacoes, acoes, factory=factory, agora=agora)
    return {'lead_id': lead_id, 'sugestoes': sugestoes}


def registrar_rotas_next_best_action(app, factory, autorizado):
    from flask import jsonify

    @app.route('/api/admin/mi/next-best-action/<lead_id>', methods=['GET'])
    def mi_next_best_action(lead_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                resultado = montar_sugestoes(cur, lead_id, factory=factory)
        except Exception:
            app.logger.exception('Falha ao calcular next best action')
            return jsonify(success=False, error='Sugestões indisponíveis.'), 503
        finally:
            conn.close()
        if not resultado:
            return jsonify(success=False, error='Contato não encontrado.'), 404
        return jsonify(success=True, **resultado)
