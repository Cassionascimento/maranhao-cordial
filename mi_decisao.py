"""Camada de decisão do Maranhão Intelligence (ETAPA 5.0, agenda na 5.1).

SINAL -> PRIORIDADE -> PRÓXIMA AÇÃO -> FILA -> CALENDÁRIO -> RESULTADO -> NOVO SINAL.

Esta camada só lê. Ela transforma o estado já existente (prospectos_fase57,
leads_crm, campanhas_prospeccao_fase57, mi_sinais) em uma lista de atividades
-- cada uma com fatos, motivo (inferência), prioridade, confiança, quando
executar, a que lead/estabelecimento se refere, próxima ação e se exige
aprovação humana. Nenhum motor novo é criado:

- "pesquisar" continua sendo executado por executar_pesquisa_publica_fase57
  (fase57_prospeccao_universal.py) / garantir_pesquisa_se_faltar_fase57;
  aqui só REPORTAMOS quando uma campanha precisa disso (mesmo predicado,
  sem o INSERT que aquela função faz).
- qualquer próxima ação com efeito externo (ex.: enviar um follow-up)
  continua exigindo uma proposta em acoes_comerciais.propor() e decisão
  humana em acoes_comerciais.decidir() -- nunca é criada nem aprovada aqui.
- bloqueios e pendências viram PRECISA_DIRETOR, nunca uma nova tentativa
  automática.
- reagendamento automático (item 4 da ETAPA 5.1) só é permitido para
  próximas ações autônomas (ACOES_AUTONOMAS); qualquer ação com efeito
  externo nunca tem seu horário alterado por aqui.

DRY-RUN: planejar() é somente leitura (mesmo padrão de mi_painel.py e
inteligencia_territorial.py -- sessão readonly, sem persistir nada). A
gravação na fila operacional (registrar_item_fila / avancar_estado_fila /
reagendar_automaticamente) existe e está testada, mas planejar() nunca as
chama -- fica pronta para uma etapa futura explicitamente autorizada a
persistir (migrations 013/014/015 continuam arquivos, não executados).
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from psycopg2.extras import RealDictCursor, Json

PRIORIDADES = ('baixa', 'normal', 'alta', 'urgente')
ESTADOS_FILA = ('planejada', 'aguardando', 'concluida', 'bloqueada', 'precisa_diretor')
ESTADOS_TERMINAIS = ('concluida', 'bloqueada')
# Nunca exigem aprovação: não têm efeito externo (não enviam, não publicam,
# não gastam cota). Qualquer outra próxima ação passa pela política existente.
ACOES_AUTONOMAS = ('pesquisar', 'classificar', 'analisar', 'planejar', 'sugerir_conteudo')
CAMPOS = ('origem', 'origem_id', 'tipo_decisao', 'fatos', 'inferencia', 'prioridade',
          'confianca', 'proxima_acao', 'exige_aprovacao', 'executar_em', 'lead_id',
          'estabelecimento_id')
PADRAO_IDENTIFICADOR = re.compile(r'[a-z][a-z0-9_]{0,63}')
_NAMESPACE_FILA = uuid5(NAMESPACE_URL, 'maranhao-cordial:mi_fila_operacional')


def _prioridade_por_score(score):
    score = score or 0
    if score >= 80:
        return 'urgente'
    if score >= 55:
        return 'alta'
    if score >= 30:
        return 'normal'
    return 'baixa'


def _decisao(origem, origem_id, tipo_decisao, fatos, inferencia, prioridade, confianca,
             proxima_acao, exige_aprovacao=None, executar_em=None, lead_id=None,
             estabelecimento_id=None):
    if exige_aprovacao is None:
        exige_aprovacao = proxima_acao not in ACOES_AUTONOMAS
    return {
        'origem': origem, 'origem_id': str(origem_id) if origem_id is not None else None,
        'tipo_decisao': tipo_decisao, 'fatos': list(fatos), 'inferencia': inferencia,
        'motivo': inferencia,  # mesmo conteúdo, nome pedido pela agenda/calendário (5.1)
        'prioridade': prioridade, 'confianca': confianca, 'proxima_acao': proxima_acao,
        'exige_aprovacao': exige_aprovacao, 'executar_em': executar_em,
        'lead_id': str(lead_id) if lead_id is not None else None,
        'estabelecimento_id': str(estabelecimento_id) if estabelecimento_id is not None else None,
        'estado': 'planejada' if not exige_aprovacao else 'aguardando',
    }


# =====================================================
# ANALISADORES -- cada um só lê, nunca escreve.
# =====================================================

def analisar_pesquisas_pendentes(cur, limite=20):
    """'Quando pesquisar?' -- mesmo predicado de
    garantir_pesquisa_se_faltar_fase57 (fase57_prospeccao_universal.py),
    mas só leitura: quem de fato cria a pesquisa continua sendo aquela
    função, nunca duplicada aqui."""
    from prospeccao_controle import elegivel_sql
    cur.execute(
        "SELECT c.id, c.codigo, c.meta_contatos, "
        "COUNT(p.id) FILTER (WHERE " + elegivel_sql() + ")::INTEGER AS contatos_uteis "
        "FROM campanhas_prospeccao_fase57 c "
        "LEFT JOIN prospectos_fase57 p ON p.campanha_id=c.id "
        "WHERE c.status='ativa' GROUP BY c.id LIMIT %s",
        (limite,),
    )
    decisoes = []
    for c in cur.fetchall():
        faltam = max(0, int(c['meta_contatos']) - int(c['contatos_uteis'] or 0))
        if faltam <= 0:
            continue
        cur.execute(
            "SELECT COUNT(*)::INTEGER qtd FROM pesquisas_fase57 WHERE campanha_id=%s "
            "AND (status='pendente' OR (status='executando' AND iniciado_em>NOW()-INTERVAL '30 minutes'))",
            (c['id'],),
        )
        if int((cur.fetchone() or {}).get('qtd') or 0) > 0:
            continue
        decisoes.append(_decisao(
            'prospeccao_fase57', c['id'], 'pesquisa_necessaria',
            [f"campanha:{c['id']}:faltam:{faltam}"],
            f"campanha {c['codigo']} está {faltam} contato(s) abaixo da meta, sem pesquisa em andamento",
            'alta' if faltam >= 10 else 'normal', 1.0, 'pesquisar',
        ))
    return decisoes


def analisar_followups_devidos(cur, limite=50):
    """'Follow-up devido?' -- campo já existente e populado por
    fase57_prospeccao_universal.py logo após o primeiro contato
    (proximo_followup_em = NOW() + 3 dias); aqui só lemos quem venceu."""
    cur.execute(
        "SELECT id, score, proximo_followup_em FROM prospectos_fase57 "
        "WHERE status='contatado' AND proximo_followup_em IS NOT NULL "
        "AND proximo_followup_em <= NOW() ORDER BY proximo_followup_em ASC LIMIT %s",
        (limite,),
    )
    decisoes = []
    for row in cur.fetchall():
        decisoes.append(_decisao(
            'prospeccao_fase57', row['id'], 'followup_devido',
            [f"prospecto:{row['id']}:proximo_followup_em:{row['proximo_followup_em']}"],
            'follow-up agendado já venceu sem nova interação registrada',
            _prioridade_por_score(row['score']), 0.9, 'enviar_followup',
            executar_em=row['proximo_followup_em'],  # a própria agenda já existente define o horário
        ))
    return decisoes


def analisar_oportunidades_paradas(cur, dias_parado=10, limite=50):
    """'Oportunidades paradas?' -- negociações/promissores sem nenhuma
    interação nova há muito tempo."""
    cur.execute(
        "SELECT id, score, ultima_resposta_em, ultimo_contato_em FROM prospectos_fase57 "
        "WHERE status IN ('negociando','promissor') "
        "AND COALESCE(ultima_resposta_em, ultimo_contato_em) < NOW() - (%s || ' days')::interval "
        "ORDER BY score DESC LIMIT %s",
        (dias_parado, limite),
    )
    decisoes = []
    for row in cur.fetchall():
        decisoes.append(_decisao(
            'prospeccao_fase57', row['id'], 'oportunidade_parada',
            [f"prospecto:{row['id']}:sem_interacao_{dias_parado}d"],
            f"negociação sem nova interação há mais de {dias_parado} dias",
            _prioridade_por_score(row['score']), 0.7, 'avaliar_reengajamento',
        ))
    return decisoes


def analisar_bloqueios(cur, limite=50):
    """'Bloqueios?' -- reaproveita o sinal já emitido em acoes_comerciais.py
    (ETAPA 4.9); nunca dispara nova tentativa automática."""
    cur.execute(
        "SELECT origem_id, criado_em FROM mi_sinais "
        "WHERE origem='acoes_comerciais' AND tipo_evento='acao_bloqueada' "
        "ORDER BY criado_em DESC LIMIT %s",
        (limite,),
    )
    decisoes = []
    for row in cur.fetchall():
        d = _decisao(
            'acoes_comerciais', row['origem_id'], 'bloqueio_pendente',
            [f"mi_sinais:acao_bloqueada:{row['origem_id']}"],
            'execução anterior não completou (bloqueada); requer revisão humana',
            'alta', 1.0, 'revisar_bloqueio',
        )
        d['estado'] = 'precisa_diretor'
        decisoes.append(d)
    return decisoes


def analisar_pendencias_diretor(cur, limite=50):
    """'Precisa do diretor?' -- mesma leitura de mi_sinais.pendencias_direcao,
    mas devolvendo cada proposta individualmente (não só a contagem)."""
    cur.execute(
        "SELECT id, origem_id, criado_em FROM mi_sinais "
        "WHERE natureza='recomendacao' AND tipo_evento='acao_proposta' "
        "AND (origem_id IS NULL OR origem_id NOT IN ("
        "  SELECT origem_id FROM mi_sinais "
        "  WHERE tipo_evento IN ('acao_aprovada','acao_rejeitada') AND origem_id IS NOT NULL"
        ")) ORDER BY criado_em ASC LIMIT %s",
        (limite,),
    )
    decisoes = []
    for row in cur.fetchall():
        d = _decisao(
            'acoes_comerciais', row['origem_id'], 'aprovacao_pendente',
            [f"mi_sinais:acao_proposta:{row['id']}"],
            'proposta da IA aguardando decisão humana', 'normal', 1.0, 'decidir_proposta',
        )
        d['estado'] = 'precisa_diretor'
        decisoes.append(d)
    return decisoes


def analisar_leads_prioritarios(cur, limite=50):
    """'Leads/territórios prioritários?' -- leads em estágio de decisão
    comercial, ordenados por potencial e recência. Não cria nenhuma ação;
    só aponta prioridade para quem já atende esses leads."""
    cur.execute(
        "SELECT id, estagio, cidade, estado, valor_potencial_centavos FROM leads_crm "
        "WHERE estagio IN ('qualificacao','proposta','negociacao') "
        "AND COALESCE(cadastro_teste, FALSE) = FALSE "
        "ORDER BY valor_potencial_centavos DESC NULLS LAST, atualizado_em ASC LIMIT %s",
        (limite,),
    )
    decisoes = []
    for row in cur.fetchall():
        valor = row.get('valor_potencial_centavos')
        prioridade = 'urgente' if (valor or 0) >= 1_000_000 else \
            'alta' if row['estagio'] in ('proposta', 'negociacao') else 'normal'
        territorio = ', '.join(x for x in (row.get('cidade'), row.get('estado')) if x) or 'não informado'
        decisoes.append(_decisao(
            'crm', row['id'], 'lead_prioritario',
            [f"lead:{row['id']}:estagio:{row['estagio']}"],
            f"lead em {row['estagio']} ({territorio})",
            prioridade, 0.9 if valor is not None else 0.6, 'priorizar_atendimento',
            exige_aprovacao=False,  # é só uma leitura de prioridade, nunca uma ação externa
            lead_id=row['id'],
        ))
    return decisoes


def chave_atividade(decisao, agora=None):
    """Chave determinística e idempotente: origem+tipo_decisao+origem_id
    identificam o MESMO fato de negócio; o dia (UTC) permite que a mesma
    condição, se ainda existir, gere uma nova atividade em outro dia -- sem
    nunca duplicar dentro do mesmo dia. Mesmo mecanismo de mi_sinais.emitir()."""
    agora = agora or datetime.now(timezone.utc)
    dia = agora.date().isoformat() if isinstance(agora, datetime) else str(agora)
    base = '|'.join(str(decisao.get(k) or '') for k in ('origem', 'tipo_decisao', 'origem_id'))
    base += '|' + dia
    return str(uuid5(_NAMESPACE_FILA, base))


def planejar(factory, agora=None):
    """Ponto único de entrada: computa a agenda de atividades a partir do
    estado atual, já com chave de idempotência (chave_atividade). DRY-RUN --
    só lê (sessão readonly, mesmo padrão de mi_painel.gerar_painel_mi), nunca
    grava em mi_fila_operacional, em mi_sinais ou em qualquer tabela de
    origem."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            decisoes = []
            decisoes += analisar_pesquisas_pendentes(cur)
            decisoes += analisar_followups_devidos(cur)
            decisoes += analisar_oportunidades_paradas(cur)
            decisoes += analisar_bloqueios(cur)
            decisoes += analisar_pendencias_diretor(cur)
            decisoes += analisar_leads_prioritarios(cur)
        for atividade in decisoes:
            atividade['chave'] = chave_atividade(atividade, agora)
        return decisoes
    finally:
        conn.close()


def resumo_leitura(decisoes):
    """Agrega a saída de planejar() nas perguntas da leitura MI (item 6 da
    ETAPA 5.0). 'Concluiu X' fica de fora: exige histórico de uma fila
    persistida (mi_fila_operacional), que esta etapa não grava -- pendência
    explícita para quando a persistência for ligada."""
    return {
        'ia_trabalhando': any(d['estado'] == 'planejada' for d in decisoes),
        'hoje_fara': [d for d in decisoes if d['estado'] == 'planejada'],
        'aguardando': [d for d in decisoes if d['estado'] == 'aguardando'],
        'oportunidades': [d for d in decisoes if d['tipo_decisao'] == 'oportunidade_parada'],
        'precisa_diretor': [d for d in decisoes if d['estado'] == 'precisa_diretor'],
        'total': len(decisoes),
    }


def _data(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def calendario(decisoes, agora=None):
    """Organiza a saída de planejar() nos baldes do Calendário Inteligente
    (ETAPA 5.1, item 3): HOJE | PRÓXIMAS | AGUARDANDO | CONCLUÍDAS |
    BLOQUEADAS | PRECISA_DIRETOR. Puramente uma projeção sobre as decisões
    já computadas -- não é um novo motor nem uma nova fonte de dados.
    executar_em ausente (None) significa 'assim que possível', então cai em
    HOJE. Atividades já concluídas/bloqueadas/aguardando/precisa_diretor
    ficam no balde do seu próprio estado, independente da data."""
    agora = agora or datetime.now(timezone.utc)
    hoje = _data(agora)
    baldes = {'hoje': [], 'proximas': [], 'aguardando': [], 'concluidas': [], 'bloqueadas': [], 'precisa_diretor': []}
    for atividade in decisoes:
        estado = atividade['estado']
        if estado == 'concluida':
            baldes['concluidas'].append(atividade)
        elif estado == 'bloqueada':
            baldes['bloqueadas'].append(atividade)
        elif estado == 'precisa_diretor':
            baldes['precisa_diretor'].append(atividade)
        elif estado == 'aguardando':
            baldes['aguardando'].append(atividade)
        else:  # planejada
            executar_em = atividade.get('executar_em')
            data_execucao = _data(executar_em)
            if data_execucao is None or data_execucao <= hoje:
                baldes['hoje'].append(atividade)
            else:
                baldes['proximas'].append(atividade)

    candidatas = [a for a in decisoes if a['estado'] in ('planejada', 'aguardando') and a.get('executar_em')]
    proxima = min(candidatas, key=lambda a: a['executar_em']) if candidatas else None
    return dict(baldes, proxima_atividade=proxima)


def leitura_calendario(decisoes, agora=None):
    """Prepara as respostas de leitura pedidas pela ETAPA 5.1 (item 5):
    o que a IA fará hoje, o que está fazendo, o que concluiu, o que aguarda,
    próxima atividade, o que precisa do diretor. Não é o painel -- só a
    agregação que um futuro componente de calendário consumiria.

    'O que concluiu' e 'o que está fazendo agora' dependem de uma fila
    persistida com histórico real de execução (mi_fila_operacional, via
    migrations 013/014/015, nenhuma aplicada nesta etapa) -- em DRY-RUN eles
    vêm sempre vazios; isso é intencional e documentado, não um bug."""
    c = calendario(decisoes, agora)
    return {
        'ia_trabalhando': bool(c['hoje']),
        'fara_hoje': c['hoje'],
        'fazendo_agora': [],  # exige histórico de execução real; pendente até 013/014/015 serem aplicadas
        'concluiu': c['concluidas'],  # sempre [] em DRY-RUN puro (nada foi persistido)
        'aguardando': c['aguardando'],
        'proxima_atividade': c['proxima_atividade'],
        'precisa_diretor': c['precisa_diretor'],
    }


def _para_fila(atividade):
    """Extrai de uma atividade (saída de planejar()) só os campos que
    registrar_item_fila aceita -- nunca passa o dict de decisão inteiro
    (que carrega 'estado'/'motivo', calculados, não persistidos como tal)."""
    body = {k: atividade.get(k) for k in CAMPOS}
    body['chave'] = atividade['chave']
    return body


def reagendar_automaticamente(factory, chave, novo_executar_em, ator='mi_decisao'):
    """Reagendamento automático (ETAPA 5.1, item 4): só é permitido para
    atividades cuja próxima ação é autônoma (ACOES_AUTONOMAS) -- sem efeito
    externo algum. Qualquer atividade com efeito externo é recusada aqui;
    seu horário só muda pela política/aprovação já existente."""
    chave = str(UUID(str(chave)))
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, proxima_acao, estado FROM mi_fila_operacional WHERE chave=%s FOR UPDATE",
                    (chave,),
                )
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'motivo': 'item_nao_encontrado'}
                if row['proxima_acao'] not in ACOES_AUTONOMAS:
                    return {'success': False, 'motivo': 'acao_externa_nao_pode_ser_reagendada_automaticamente'}
                if row['estado'] in ESTADOS_TERMINAIS:
                    return {'success': False, 'motivo': 'item_ja_concluido_ou_bloqueado'}
                cur.execute(
                    "UPDATE mi_fila_operacional SET executar_em=%s, atualizado_em=NOW() WHERE id=%s",
                    (novo_executar_em, row['id']),
                )
                cur.execute(
                    "INSERT INTO mi_fila_operacional_auditoria(item_id,estado_anterior,estado_novo,ator) "
                    "VALUES(%s,%s,%s,%s)",
                    (row['id'], row['estado'], row['estado'], ator),
                )
                return {'success': True, 'executar_em': novo_executar_em}
    finally:
        conn.close()


# =====================================================
# PERSISTÊNCIA DA FILA -- pronta e testada, não chamada por planejar().
# Reservada para uma etapa futura explicitamente autorizada a gravar
# (ex.: 5.1, o calendário). Mesma disciplina chave+payload_hash de
# mi_sinais.py/mi_eventos.py.
# =====================================================

def validar_item_fila(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS) - {'chave'}:
        raise ValueError('campos_invalidos')
    chave = str(UUID(str(body.get('chave'))))
    d = {k: body.get(k) for k in CAMPOS}

    if not isinstance(d['origem'], str) or not PADRAO_IDENTIFICADOR.fullmatch(d['origem']):
        raise ValueError('origem_invalida')
    if not isinstance(d['tipo_decisao'], str) or not PADRAO_IDENTIFICADOR.fullmatch(d['tipo_decisao']):
        raise ValueError('tipo_decisao_invalido')
    if d['prioridade'] not in PRIORIDADES:
        raise ValueError('prioridade_invalida')
    if not isinstance(d['proxima_acao'], str) or not d['proxima_acao'].strip():
        raise ValueError('proxima_acao_obrigatoria')
    if not isinstance(d['exige_aprovacao'], bool):
        raise ValueError('exige_aprovacao_deve_ser_booleano')
    if not isinstance(d['fatos'], list) or not all(isinstance(f, str) for f in d['fatos']):
        raise ValueError('fatos_invalidos')
    if d['confianca'] is not None:
        if isinstance(d['confianca'], bool) or not isinstance(d['confianca'], (int, float)):
            raise ValueError('confianca_invalida')
        if not (0 <= d['confianca'] <= 1):
            raise ValueError('confianca_fora_do_intervalo')
        d['confianca'] = float(d['confianca'])
    if d['origem_id'] is not None and not isinstance(d['origem_id'], str):
        raise ValueError('origem_id_invalido')
    for campo in ('lead_id', 'estabelecimento_id'):
        if d[campo] is not None:
            d[campo] = str(UUID(str(d[campo])))
    if d['executar_em'] is not None:
        if isinstance(d['executar_em'], datetime):
            d['executar_em'] = d['executar_em'].isoformat()
        elif isinstance(d['executar_em'], str):
            datetime.fromisoformat(d['executar_em'])  # só valida o formato
        else:
            raise ValueError('executar_em_invalido')

    digest = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return chave, d, digest


def registrar_item_fila(factory, body):
    """Cria um item da fila (estado inicial: planejada ou aguardando,
    conforme exige_aprovacao). Idempotente: a mesma chave nunca duplica."""
    chave, d, digest = validar_item_fila(body)
    estado_inicial = 'aguardando' if d['exige_aprovacao'] else 'planejada'
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO mi_fila_operacional(id,chave,payload_hash,estado," + ",".join(CAMPOS) + ") "
                    "VALUES(" + ",".join(["%s"] * (len(CAMPOS) + 4)) + ") "
                    "ON CONFLICT(chave) DO NOTHING RETURNING id",
                    [str(uuid4()), chave, digest, estado_inicial] +
                    [Json(d[k]) if k == 'fatos' else d[k] for k in CAMPOS],
                )
                novo = cur.fetchone()
                cur.execute("SELECT id, payload_hash, estado FROM mi_fila_operacional WHERE chave=%s", (chave,))
                row = cur.fetchone()
                if row['payload_hash'] != digest:
                    return {'success': False, 'error': 'chave_reutilizada_com_outro_conteudo'}, 409
                if novo:
                    cur.execute(
                        "INSERT INTO mi_fila_operacional_auditoria(item_id,estado_anterior,estado_novo,ator) "
                        "VALUES(%s,NULL,%s,'mi_decisao')",
                        (novo['id'], estado_inicial),
                    )
                return {'success': True, 'id': str(row['id']), 'estado': row['estado'], 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


TRANSICOES_PERMITIDAS = {
    'planejada': ('aguardando', 'concluida', 'bloqueada', 'precisa_diretor'),
    'aguardando': ('concluida', 'bloqueada', 'precisa_diretor'),
    'precisa_diretor': ('aguardando', 'concluida', 'bloqueada'),
    'bloqueada': ('precisa_diretor',),
    'concluida': (),
}


def avancar_estado_fila(factory, chave, novo_estado, ator, resultado=None):
    """Transição controlada de estado -- nunca reabre um item concluído."""
    chave = str(UUID(str(chave)))
    if novo_estado not in ESTADOS_FILA:
        raise ValueError('estado_invalido')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, estado FROM mi_fila_operacional WHERE chave=%s FOR UPDATE", (chave,))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'motivo': 'item_nao_encontrado'}
                atual = row['estado']
                if novo_estado not in TRANSICOES_PERMITIDAS.get(atual, ()):
                    return {'success': False, 'motivo': 'transicao_nao_permitida', 'de': atual, 'para': novo_estado}
                concluido_em_sql = "NOW()" if novo_estado in ESTADOS_TERMINAIS else "NULL"
                cur.execute(
                    "UPDATE mi_fila_operacional SET estado=%s, resultado=%s, atualizado_em=NOW(), "
                    "concluido_em=" + concluido_em_sql + " WHERE id=%s",
                    (novo_estado, Json(resultado) if resultado is not None else None, row['id']),
                )
                cur.execute(
                    "INSERT INTO mi_fila_operacional_auditoria(item_id,estado_anterior,estado_novo,ator) "
                    "VALUES(%s,%s,%s,%s)",
                    (row['id'], atual, novo_estado, ator),
                )
                return {'success': True, 'de': atual, 'para': novo_estado}
    finally:
        conn.close()
