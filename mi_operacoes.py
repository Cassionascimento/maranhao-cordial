"""Central Empresarial -- Operações Vivas (ver docs/CENTRAL_EMPRESARIAL_
OPERACOES_VIVAS.md e migrations/022_mi_operacoes.sql).

Transforma um item do Calendário Empresarial numa operação viva,
editável e versionada. Reaproveita, sem duplicar: mi_artefatos (visual/
documentos, nenhum storage paralelo), mi_conselho_executor.
executar_especialista (Brainstorm com Conselho -- mesma chamada LLM já
usada pelo pipeline automático, fail-closed sem OPENAI_API_KEY) e
mi_conselho.registrar_registro (trilha de reunião do Conselho).

Human-in-the-loop permanece obrigatório: nenhuma função aqui contata
fornecedor/convidado externo, publica nada ou executa pagamento --
persistência e leitura apenas. Toda mudança relevante grava uma linha
em mi_operacao_auditoria (append-only, nunca sobrescreve histórico).
"""
import uuid

from psycopg2.extras import Json, RealDictCursor

ESTADOS_OPERACAO = ('planejamento', 'confirmada', 'em_andamento', 'concluida', 'cancelada')
PRIORIDADES = ('baixa', 'normal', 'alta', 'critica')
ESTADOS_PESSOA = ('sugerido', 'convidado', 'confirmado', 'cancelado')
TIPOS_ITEM = ('tarefa', 'marco', 'checklist')
STATUS_ITEM = ('pendente', 'em_andamento', 'concluido', 'bloqueado', 'cancelado')
STATUS_BRAINSTORM = (
    'aguardando', 'respondido', 'aceito_como_proposta', 'descartado',
    'transformado_em_tarefa', 'transformado_em_artefato',
)
ESTADOS_DADO_METRICA = ('aguardando_dados', 'estimativa', 'confirmado', 'nao_aplicavel')
TIPOS_FINANCEIRO = ('orcamento', 'realizado', 'comprometido', 'receita_atribuida', 'taxa', 'tributo')
ESTADOS_DADO_FINANCEIRO = ('estimativa', 'confirmado', 'aguardando_dados')
CATEGORIAS_ARQUIVO = ('documento', 'visual', 'briefing', 'planilha', 'outro')
DECISOES_BRAINSTORM = (
    'aceitar_como_proposta', 'editar', 'descartar', 'pedir_nova_rodada',
    'transformar_em_tarefa', 'transformar_em_artefato',
)
# Decisão (verbo, ação do diretor) -> status persistido (particípio, estado
# do registro). 'editar' mantém o registro em 'respondido' (o conteúdo
# editado é gravado em `resposta`, não muda o ciclo de vida); 'pedir_nova_
# rodada' volta para 'aguardando' para permitir uma nova execução.
_STATUS_POR_DECISAO = {
    'aceitar_como_proposta': 'aceito_como_proposta',
    'editar': 'respondido',
    'descartar': 'descartado',
    'pedir_nova_rodada': 'aguardando',
    'transformar_em_tarefa': 'transformado_em_tarefa',
    'transformar_em_artefato': 'transformado_em_artefato',
}


def _uuid(v):
    return str(v) if v is not None else None


def _exigir(valor, nome):
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise ValueError(nome + '_obrigatorio')
    return valor


def _registrar_auditoria(cur, operacao_id, entidade, entidade_id, acao, ator_nome,
                          campo=None, valor_anterior=None, valor_novo=None, ator_tipo='humano'):
    cur.execute(
        "INSERT INTO mi_operacao_auditoria (operacao_id, entidade, entidade_id, acao, campo, "
        "valor_anterior, valor_novo, ator_tipo, ator_nome) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (_uuid(operacao_id), entidade, _uuid(entidade_id), acao, campo,
         valor_anterior, valor_novo, ator_tipo, ator_nome),
    )


# ---------------------------------------------------------------------
# Operação
# ---------------------------------------------------------------------

def criar_operacao(factory, *, titulo, data_inicio, data_fim, criado_por, descricao=None,
                    local=None, prioridade='normal', responsavel=None, origem_fila_id=None):
    _exigir(titulo, 'titulo')
    _exigir(criado_por, 'criado_por')
    if prioridade not in PRIORIDADES:
        raise ValueError('prioridade_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                operacao_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_operacoes (id, titulo, descricao, data_inicio, data_fim, local, "
                    "prioridade, responsavel, origem_fila_id, criado_por) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (str(operacao_id), titulo, descricao, data_inicio, data_fim, local,
                     prioridade, responsavel, origem_fila_id, criado_por),
                )
                operacao = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'operacao', operacao_id, 'criada', criado_por,
                                      valor_novo=titulo)
                return {'success': True, 'operacao': operacao}
    finally:
        conn.close()


def listar_operacoes(factory, *, estado=None, desde=None, ate=None):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            filtros, args = [], []
            if estado:
                filtros.append("estado = %s")
                args.append(estado)
            if desde:
                filtros.append("data_fim >= %s")
                args.append(desde)
            if ate:
                filtros.append("data_inicio <= %s")
                args.append(ate)
            sql = "SELECT * FROM mi_operacoes"
            if filtros:
                sql += " WHERE " + " AND ".join(filtros)
            sql += " ORDER BY data_inicio ASC"
            cur.execute(sql, tuple(args))
            return cur.fetchall()
    finally:
        conn.close()


def obter_operacao(factory, operacao_id):
    """Visão geral (aba Visão Geral): a operação + contagens de cada
    aba, para o front decidir o que mostrar sem 8 chamadas separadas."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
            operacao = cur.fetchone()
            if not operacao:
                return None
            contagens = {}
            for entidade, tabela in (
                ('pessoas', 'mi_operacao_pessoas'), ('itens', 'mi_operacao_itens'),
                ('brainstorm', 'mi_operacao_brainstorm'), ('metricas', 'mi_operacao_metricas'),
                ('financeiro', 'mi_operacao_financeiro'), ('arquivos', 'mi_operacao_arquivos'),
            ):
                cur.execute(f"SELECT COUNT(*)::INTEGER AS total FROM {tabela} WHERE operacao_id=%s",
                            (_uuid(operacao_id),))
                contagens[entidade] = cur.fetchone()['total']
            return {'operacao': operacao, 'contagens': contagens}
    finally:
        conn.close()


def atualizar_operacao(factory, operacao_id, campos, ator):
    """Edição inline (título/descrição/local/estado/prioridade/
    responsável/datas). Cada campo alterado grava uma linha de
    auditoria própria -- histórico nunca é apagado nem resumido."""
    _exigir(ator, 'ator')
    permitidos = {
        'titulo', 'descricao', 'data_inicio', 'data_fim', 'local',
        'estado', 'prioridade', 'responsavel',
    }
    campos = {k: v for k, v in (campos or {}).items() if k in permitidos}
    if not campos:
        return {'success': False, 'motivo': 'nenhum_campo_valido'}
    if 'estado' in campos and campos['estado'] not in ESTADOS_OPERACAO:
        raise ValueError('estado_invalido')
    if 'prioridade' in campos and campos['prioridade'] not in PRIORIDADES:
        raise ValueError('prioridade_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM mi_operacoes WHERE id=%s FOR UPDATE", (_uuid(operacao_id),))
                atual = cur.fetchone()
                if not atual:
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                sets = ", ".join(f"{campo}=%s" for campo in campos) + ", atualizado_em=NOW()"
                cur.execute(f"UPDATE mi_operacoes SET {sets} WHERE id=%s RETURNING *",
                            (*campos.values(), _uuid(operacao_id)))
                nova = cur.fetchone()
                for campo, valor in campos.items():
                    if str(atual[campo]) != str(valor):
                        _registrar_auditoria(cur, operacao_id, 'operacao', operacao_id, 'editada', ator,
                                              campo=campo, valor_anterior=str(atual[campo]), valor_novo=str(valor))
                return {'success': True, 'operacao': nova}
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Equipe / staff
# ---------------------------------------------------------------------

def adicionar_pessoa(factory, operacao_id, *, funcao, ator, nome=None, telefone=None, email=None,
                      origem='humano', disponibilidade=None, observacoes=None):
    _exigir(funcao, 'funcao')
    _exigir(ator, 'ator')
    if origem not in ('humano', 'agente'):
        raise ValueError('origem_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                pessoa_id = uuid.uuid4()
                estado_inicial = 'sugerido'
                cur.execute(
                    "INSERT INTO mi_operacao_pessoas (id, operacao_id, funcao, nome, telefone, email, "
                    "estado, origem, disponibilidade, observacoes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING *",
                    (str(pessoa_id), _uuid(operacao_id), funcao, nome, telefone, email,
                     estado_inicial, origem, disponibilidade, observacoes),
                )
                pessoa = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'pessoa', pessoa_id, 'adicionada', ator,
                                      valor_novo=f'{funcao}:{nome or "(sem nome)"}',
                                      ator_tipo='agente' if origem == 'agente' else 'humano')
                return {'success': True, 'pessoa': pessoa}
    finally:
        conn.close()


def listar_pessoas(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacao_pessoas WHERE operacao_id=%s ORDER BY criado_em ASC",
                        (_uuid(operacao_id),))
            return cur.fetchall()
    finally:
        conn.close()


def atualizar_estado_pessoa(factory, pessoa_id, novo_estado, ator):
    """Sugestão da IA nunca vira confirmação sozinha -- toda mudança de
    estado passa por esta função, chamada só a partir de rota
    autenticada (nenhuma automação chama isto direto)."""
    _exigir(ator, 'ator')
    if novo_estado not in ESTADOS_PESSOA:
        raise ValueError('estado_invalido')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM mi_operacao_pessoas WHERE id=%s FOR UPDATE", (_uuid(pessoa_id),))
                atual = cur.fetchone()
                if not atual:
                    return {'success': False, 'motivo': 'pessoa_nao_encontrada'}
                cur.execute(
                    "UPDATE mi_operacao_pessoas SET estado=%s, atualizado_em=NOW() WHERE id=%s RETURNING *",
                    (novo_estado, _uuid(pessoa_id)),
                )
                pessoa = cur.fetchone()
                _registrar_auditoria(cur, pessoa['operacao_id'], 'pessoa', pessoa_id, 'estado_alterado', ator,
                                      valor_anterior=atual['estado'], valor_novo=novo_estado)
                return {'success': True, 'pessoa': pessoa}
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Plano operacional (tarefas/marcos/checklist)
# ---------------------------------------------------------------------

def adicionar_item(factory, operacao_id, *, titulo, ator, tipo='tarefa', descricao=None,
                    data_prevista=None, horario=None, responsavel=None, prioridade='normal',
                    depende_de_item_id=None, plano_b=None, observacoes=None):
    _exigir(titulo, 'titulo')
    _exigir(ator, 'ator')
    if tipo not in TIPOS_ITEM:
        raise ValueError('tipo_invalido')
    if prioridade not in PRIORIDADES:
        raise ValueError('prioridade_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                cur.execute("SELECT COALESCE(MAX(ordem),-1)+1 AS proxima FROM mi_operacao_itens WHERE operacao_id=%s",
                            (_uuid(operacao_id),))
                ordem = cur.fetchone()['proxima']
                item_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_operacao_itens (id, operacao_id, tipo, titulo, descricao, data_prevista, "
                    "horario, responsavel, prioridade, depende_de_item_id, plano_b, observacoes, ordem) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (str(item_id), _uuid(operacao_id), tipo, titulo, descricao, data_prevista, horario,
                     responsavel, prioridade, _uuid(depende_de_item_id), plano_b, observacoes, ordem),
                )
                item = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'item', item_id, 'criado', ator, valor_novo=titulo)
                return {'success': True, 'item': item}
    finally:
        conn.close()


def listar_itens(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacao_itens WHERE operacao_id=%s ORDER BY ordem ASC",
                        (_uuid(operacao_id),))
            return cur.fetchall()
    finally:
        conn.close()


def atualizar_item(factory, item_id, campos, ator):
    _exigir(ator, 'ator')
    permitidos = {
        'titulo', 'descricao', 'data_prevista', 'horario', 'responsavel', 'prioridade',
        'status', 'plano_b', 'observacoes', 'ordem',
    }
    campos = {k: v for k, v in (campos or {}).items() if k in permitidos}
    if not campos:
        return {'success': False, 'motivo': 'nenhum_campo_valido'}
    if 'status' in campos and campos['status'] not in STATUS_ITEM:
        raise ValueError('status_invalido')
    if 'prioridade' in campos and campos['prioridade'] not in PRIORIDADES:
        raise ValueError('prioridade_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM mi_operacao_itens WHERE id=%s FOR UPDATE", (_uuid(item_id),))
                atual = cur.fetchone()
                if not atual:
                    return {'success': False, 'motivo': 'item_nao_encontrado'}
                sets = ", ".join(f"{campo}=%s" for campo in campos) + ", atualizado_em=NOW()"
                cur.execute(f"UPDATE mi_operacao_itens SET {sets} WHERE id=%s RETURNING *",
                            (*campos.values(), _uuid(item_id)))
                item = cur.fetchone()
                for campo, valor in campos.items():
                    if str(atual[campo]) != str(valor):
                        _registrar_auditoria(cur, atual['operacao_id'], 'item', item_id, 'editado', ator,
                                              campo=campo, valor_anterior=str(atual[campo]), valor_novo=str(valor))
                return {'success': True, 'item': item}
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Brainstorm com Conselho
# ---------------------------------------------------------------------

def criar_pergunta_brainstorm(factory, operacao_id, *, pergunta, ator, autor_tipo='humano', autor_nome=None):
    _exigir(pergunta, 'pergunta')
    _exigir(ator, 'ator')
    if autor_tipo not in ('humano', 'agente', 'conselho'):
        raise ValueError('autor_tipo_invalido')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                brainstorm_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_operacao_brainstorm (id, operacao_id, pergunta, autor_tipo, autor_nome) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                    (str(brainstorm_id), _uuid(operacao_id), pergunta, autor_tipo, autor_nome or ator),
                )
                registro = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'brainstorm', brainstorm_id, 'pergunta_criada', ator,
                                      valor_novo=pergunta[:200])
                return {'success': True, 'brainstorm': registro}
    finally:
        conn.close()


def _montar_snapshot_operacao(cur, operacao_id):
    """Contexto real da operação para o especialista opinar sobre fatos,
    nunca sobre uma pergunta no vácuo -- nunca inclui dado sensível/
    interno além do que a própria operação já guarda."""
    cur.execute("SELECT * FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
    operacao = cur.fetchone()
    if not operacao:
        return None
    cur.execute("SELECT funcao, nome, estado FROM mi_operacao_pessoas WHERE operacao_id=%s", (_uuid(operacao_id),))
    pessoas = cur.fetchall()
    cur.execute("SELECT titulo, status, data_prevista FROM mi_operacao_itens WHERE operacao_id=%s ORDER BY ordem",
                (_uuid(operacao_id),))
    itens = cur.fetchall()
    return {
        'operacao': {
            'titulo': operacao['titulo'], 'descricao': operacao['descricao'],
            'data_inicio': str(operacao['data_inicio']), 'data_fim': str(operacao['data_fim']),
            'local': operacao['local'], 'estado': operacao['estado'],
        },
        'equipe': [dict(p) for p in pessoas],
        'plano': [dict(i) for i in itens],
    }


def executar_brainstorm(factory, brainstorm_id, agentes, ator, cliente=None):
    """Envia a pergunta já registrada aos especialistas do Conselho já
    existente (mi_conselho_executor.executar_especialista -- mesma
    chamada usada pelo pipeline automático, mesmo comportamento
    fail-closed sem OPENAI_API_KEY). Só roda quando um humano aciona
    esta função via rota autenticada; nunca em loop/scheduler."""
    from mi_conselho import AGENTES, registrar_registro
    from mi_conselho_executor import executar_especialista

    _exigir(ator, 'ator')
    agentes = [a for a in (agentes or []) if a in AGENTES]
    if not agentes:
        raise ValueError('nenhum_agente_valido')
    if len(agentes) > 3:
        raise ValueError('maximo_3_agentes_por_rodada')

    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM mi_operacao_brainstorm WHERE id=%s", (_uuid(brainstorm_id),))
            registro = cur.fetchone()
            if not registro:
                return {'success': False, 'motivo': 'brainstorm_nao_encontrado'}
            snapshot = _montar_snapshot_operacao(cur, registro['operacao_id'])
    finally:
        conn.close()

    pareceres, erros = [], []
    for agente in agentes:
        try:
            pareceres.append(executar_especialista(agente, registro['pergunta'], snapshot=snapshot, cliente=cliente))
        except Exception as erro:
            erros.append({'agente': agente, 'erro': type(erro).__name__})

    if not pareceres:
        return {'success': False, 'motivo': 'conselho_indisponivel', 'erros': erros}

    resposta = {
        'ideias': [p['conclusao'] for p in pareceres if p.get('conclusao')],
        'riscos': [p['riscos'] for p in pareceres if p.get('riscos')],
        'contrapontos': [p['divergencias'] for p in pareceres if p.get('divergencias')],
        'alternativas': [p['acao_sugerida'] for p in pareceres if p.get('acao_sugerida')],
        'recomendacao': next((p['acao_sugerida'] for p in pareceres if p.get('acao_sugerida')), ''),
        'pendencias': [p['motivo_diretor'] for p in pareceres if p.get('necessidade_diretor') and p.get('motivo_diretor')],
        'agentes_consultados': agentes,
        'erros': erros,
    }

    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "UPDATE mi_operacao_brainstorm SET resposta=%s, status='respondido', versao=versao+1, "
                    "atualizado_em=NOW() WHERE id=%s RETURNING *",
                    (Json(resposta), _uuid(brainstorm_id)),
                )
                atualizado = cur.fetchone()
                registrar_registro(factory, {
                    'chave': str(uuid.uuid4()), 'tipo': 'reuniao', 'demanda': registro['pergunta'],
                    'participantes': agentes, 'contexto': f"operacao:{registro['operacao_id']}",
                    'conclusao': resposta['recomendacao'], 'recomendacoes': resposta['alternativas'],
                    'pendencias': resposta['pendencias'], 'precisa_diretor': bool(resposta['pendencias']),
                })
                _registrar_auditoria(cur, registro['operacao_id'], 'brainstorm', brainstorm_id, 'executado', ator,
                                      valor_novo=','.join(agentes))
                return {'success': True, 'brainstorm': atualizado}
    finally:
        conn.close()


def decidir_brainstorm(factory, brainstorm_id, decisao, ator, item_titulo=None, artifact_type=None,
                        artefato_bytes=None, artefato_mime_type=None):
    """Decisão humana sobre a resposta do Conselho -- nunca automática.
    TRANSFORMAR EM TAREFA cria um item real do plano; TRANSFORMAR EM
    ARTEFATO registra um mi_artefato versionado (reaproveita mi_artefatos,
    nenhum storage novo)."""
    _exigir(ator, 'ator')
    if decisao not in DECISOES_BRAINSTORM:
        raise ValueError('decisao_invalida')
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM mi_operacao_brainstorm WHERE id=%s", (_uuid(brainstorm_id),))
            registro = cur.fetchone()
    finally:
        conn.close()
    if not registro:
        return {'success': False, 'motivo': 'brainstorm_nao_encontrado'}

    resultado_extra = {}
    if decisao == 'transformar_em_tarefa':
        titulo = item_titulo or (registro['pergunta'][:200])
        resultado_extra = adicionar_item(factory, registro['operacao_id'], titulo=titulo, ator=ator,
                                          descricao='Originado do Brainstorm com Conselho.')
        if not resultado_extra.get('success'):
            return resultado_extra
    elif decisao == 'transformar_em_artefato':
        if not artefato_bytes or not artifact_type:
            return {'success': False, 'motivo': 'artefato_bytes_e_artifact_type_obrigatorios'}
        from mi_artefatos import registrar_artefato
        resultado_extra = registrar_artefato(
            factory, artifact_type=artifact_type, conteudo=artefato_bytes,
            mime_type=artefato_mime_type or 'application/octet-stream',
            source_type='mi_operacao_brainstorm', source_id=str(brainstorm_id),
            metadata={'operacao_id': str(registro['operacao_id']), 'pergunta': registro['pergunta']},
        )
        if not resultado_extra.get('success'):
            return resultado_extra

    novo_status = _STATUS_POR_DECISAO[decisao]
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sets = ["status=%s", "atualizado_em=NOW()"]
                args = [novo_status]
                if decisao == 'transformar_em_tarefa':
                    sets.append("item_id=%s")
                    args.append(resultado_extra['item']['id'])
                elif decisao == 'transformar_em_artefato':
                    sets.append("artefato_id=%s")
                    args.append(resultado_extra['id'])
                args.append(_uuid(brainstorm_id))
                cur.execute(f"UPDATE mi_operacao_brainstorm SET {', '.join(sets)} WHERE id=%s RETURNING *", args)
                atualizado = cur.fetchone()
                _registrar_auditoria(cur, registro['operacao_id'], 'brainstorm', brainstorm_id, decisao, ator)
                return {'success': True, 'brainstorm': atualizado, **({'item': resultado_extra.get('item')} if 'item' in resultado_extra else {}),
                        **({'artefato_id': resultado_extra.get('id')} if 'id' in resultado_extra else {})}
    finally:
        conn.close()


def listar_brainstorm(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacao_brainstorm WHERE operacao_id=%s ORDER BY criado_em DESC",
                        (_uuid(operacao_id),))
            return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Indicadores (KPIs)
# ---------------------------------------------------------------------

def upsert_metrica(factory, operacao_id, *, nome, ator, valor=None, unidade=None, periodo=None,
                    formula=None, fonte=None, explicacao=None, estado_dado=None):
    _exigir(nome, 'nome')
    _exigir(ator, 'ator')
    estado_dado = estado_dado or ('confirmado' if valor is not None and fonte else 'aguardando_dados')
    if estado_dado not in ESTADOS_DADO_METRICA:
        raise ValueError('estado_dado_invalido')
    if estado_dado == 'confirmado' and (valor is None or not fonte):
        raise ValueError('confirmado_exige_valor_e_fonte')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                cur.execute("SELECT id FROM mi_operacao_metricas WHERE operacao_id=%s AND nome=%s",
                            (_uuid(operacao_id), nome))
                existente = cur.fetchone()
                if existente:
                    cur.execute(
                        "UPDATE mi_operacao_metricas SET valor=%s, unidade=%s, periodo=%s, formula=%s, "
                        "fonte=%s, explicacao=%s, estado_dado=%s, atualizado_em=NOW() WHERE id=%s RETURNING *",
                        (valor, unidade, periodo, formula, fonte, explicacao, estado_dado, existente['id']),
                    )
                else:
                    cur.execute(
                        "INSERT INTO mi_operacao_metricas (id, operacao_id, nome, valor, unidade, periodo, "
                        "formula, fonte, explicacao, estado_dado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "RETURNING *",
                        (str(uuid.uuid4()), _uuid(operacao_id), nome, valor, unidade, periodo, formula,
                         fonte, explicacao, estado_dado),
                    )
                metrica = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'metrica', metrica['id'], 'atualizada', ator,
                                      campo=nome, valor_novo=str(valor) if valor is not None else estado_dado)
                return {'success': True, 'metrica': metrica}
    finally:
        conn.close()


def listar_metricas(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacao_metricas WHERE operacao_id=%s ORDER BY nome ASC",
                        (_uuid(operacao_id),))
            return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Financeiro / impostos / taxas
# ---------------------------------------------------------------------

def adicionar_lancamento_financeiro(factory, operacao_id, *, categoria, tipo, valor_centavos, ator,
                                     base_calculo=None, formula=None, premissas=None, fonte=None,
                                     periodo=None, estado_dado='estimativa'):
    _exigir(categoria, 'categoria')
    _exigir(ator, 'ator')
    if tipo not in TIPOS_FINANCEIRO:
        raise ValueError('tipo_invalido')
    if estado_dado not in ESTADOS_DADO_FINANCEIRO:
        raise ValueError('estado_dado_invalido')
    if estado_dado == 'confirmado' and not fonte:
        raise ValueError('confirmado_exige_fonte')
    if not isinstance(valor_centavos, int):
        raise ValueError('valor_centavos_deve_ser_inteiro')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                lancamento_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_operacao_financeiro (id, operacao_id, categoria, tipo, valor_centavos, "
                    "base_calculo, formula, premissas, fonte, periodo, estado_dado) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (str(lancamento_id), _uuid(operacao_id), categoria, tipo, valor_centavos, base_calculo,
                     formula, premissas, fonte, periodo, estado_dado),
                )
                lancamento = cur.fetchone()
                _registrar_auditoria(cur, operacao_id, 'financeiro', lancamento_id, 'lancado', ator,
                                      campo=tipo, valor_novo=f'{categoria}:{valor_centavos}')
                return {'success': True, 'lancamento': lancamento}
    finally:
        conn.close()


def resumo_financeiro(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT * FROM mi_operacao_financeiro WHERE operacao_id=%s ORDER BY criado_em ASC",
                        (_uuid(operacao_id),))
            lancamentos = cur.fetchall()
            totais = {tipo: 0 for tipo in TIPOS_FINANCEIRO}
            for l in lancamentos:
                totais[l['tipo']] += l['valor_centavos']
            return {'lancamentos': lancamentos, 'totais_centavos': totais}
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Arquivos / visual (reaproveita mi_artefatos)
# ---------------------------------------------------------------------

def vincular_artefato(factory, operacao_id, artefato_id, ator, categoria='documento'):
    _exigir(ator, 'ator')
    if categoria not in CATEGORIAS_ARQUIVO:
        raise ValueError('categoria_invalida')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'operacao_nao_encontrada'}
                cur.execute("SELECT id FROM mi_artefatos WHERE id=%s", (_uuid(artefato_id),))
                if not cur.fetchone():
                    return {'success': False, 'motivo': 'artefato_nao_encontrado'}
                vinculo_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO mi_operacao_arquivos (id, operacao_id, artefato_id, categoria, adicionado_por) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (operacao_id, artefato_id) DO NOTHING RETURNING *",
                    (str(vinculo_id), _uuid(operacao_id), _uuid(artefato_id), categoria, ator),
                )
                vinculo = cur.fetchone()
                if not vinculo:
                    return {'success': False, 'motivo': 'artefato_ja_vinculado'}
                _registrar_auditoria(cur, operacao_id, 'arquivo', vinculo_id, 'vinculado', ator,
                                      valor_novo=str(artefato_id))
                return {'success': True, 'vinculo': vinculo}
    finally:
        conn.close()


def listar_arquivos(factory, operacao_id):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute(
                "SELECT v.*, a.artifact_type, a.status AS artefato_status, a.mime_type, a.version "
                "FROM mi_operacao_arquivos v JOIN mi_artefatos a ON a.id = v.artefato_id "
                "WHERE v.operacao_id=%s ORDER BY v.criado_em DESC",
                (_uuid(operacao_id),),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Histórico / auditoria
# ---------------------------------------------------------------------

def listar_auditoria(factory, operacao_id, limite=200):
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute(
                "SELECT * FROM mi_operacao_auditoria WHERE operacao_id=%s ORDER BY criado_em DESC LIMIT %s",
                (_uuid(operacao_id), limite),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Visão Investidor -- somente leitura, sanitizada
# ---------------------------------------------------------------------

def visao_investidor(factory, operacao_id):
    """Nunca expõe ADMIN_API_KEY, segredos, prompts internos, dados
    pessoais de equipe (telefone/email) ou controles de execução --
    só o que um investidor autorizado precisa ver."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute("SELECT id, titulo, descricao, data_inicio, data_fim, local, estado, prioridade "
                        "FROM mi_operacoes WHERE id=%s", (_uuid(operacao_id),))
            operacao = cur.fetchone()
            if not operacao:
                return None
            cur.execute("SELECT funcao, estado FROM mi_operacao_pessoas WHERE operacao_id=%s", (_uuid(operacao_id),))
            equipe = cur.fetchall()
            cur.execute("SELECT titulo, tipo, status, data_prevista FROM mi_operacao_itens "
                        "WHERE operacao_id=%s ORDER BY ordem", (_uuid(operacao_id),))
            plano = cur.fetchall()
            cur.execute("SELECT nome, valor, unidade, periodo, estado_dado, explicacao FROM mi_operacao_metricas "
                        "WHERE operacao_id=%s", (_uuid(operacao_id),))
            metricas = cur.fetchall()
            cur.execute("SELECT categoria, tipo, valor_centavos, estado_dado, periodo FROM mi_operacao_financeiro "
                        "WHERE operacao_id=%s", (_uuid(operacao_id),))
            financeiro = cur.fetchall()
            return {
                'operacao': operacao, 'equipe_resumo': equipe, 'plano': plano,
                'indicadores': metricas, 'financeiro_resumo': financeiro,
            }
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Rotas HTTP
# ---------------------------------------------------------------------

def registrar_rotas(app, factory, autorizado):
    from flask import jsonify, request

    def _erro(motivo, status=400):
        return jsonify(success=False, error=motivo), status

    def _ator():
        return (request.get_json(silent=True) or {}).get('ator') or request.args.get('ator') or 'admin'

    @app.route('/api/admin/mi/operacoes', methods=['GET', 'POST'])
    def mi_operacoes_colecao():
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, operacoes=listar_operacoes(
                    factory, estado=request.args.get('estado'),
                    desde=request.args.get('desde'), ate=request.args.get('ate')))
            corpo = request.get_json(silent=True) or {}
            resultado = criar_operacao(
                factory, titulo=corpo.get('titulo'), data_inicio=corpo.get('data_inicio'),
                data_fim=corpo.get('data_fim'), criado_por=corpo.get('criado_por') or _ator(),
                descricao=corpo.get('descricao'), local=corpo.get('local'),
                prioridade=corpo.get('prioridade', 'normal'), responsavel=corpo.get('responsavel'),
                origem_fila_id=corpo.get('origem_fila_id'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar operações vivas')
            return _erro('Operações indisponíveis no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>', methods=['GET', 'PATCH'])
    def mi_operacao_item(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                visao = obter_operacao(factory, operacao_id)
                if not visao:
                    return _erro('Operação não encontrada.', 404)
                return jsonify(success=True, **visao)
            corpo = request.get_json(silent=True) or {}
            resultado = atualizar_operacao(factory, operacao_id, corpo.get('campos') or {}, corpo.get('ator') or _ator())
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar operação viva %s', operacao_id)
            return _erro('Operação indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/pessoas', methods=['GET', 'POST'])
    def mi_operacao_pessoas_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, pessoas=listar_pessoas(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = adicionar_pessoa(
                factory, operacao_id, funcao=corpo.get('funcao'), ator=corpo.get('ator') or _ator(),
                nome=corpo.get('nome'), telefone=corpo.get('telefone'), email=corpo.get('email'),
                origem=corpo.get('origem', 'humano'), disponibilidade=corpo.get('disponibilidade'),
                observacoes=corpo.get('observacoes'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar equipe da operação %s', operacao_id)
            return _erro('Equipe indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/pessoas/<pessoa_id>/estado', methods=['PATCH'])
    def mi_operacao_pessoa_estado(pessoa_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = atualizar_estado_pessoa(factory, pessoa_id, corpo.get('estado'), corpo.get('ator') or _ator())
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao atualizar estado de pessoa %s', pessoa_id)
            return _erro('Equipe indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/itens', methods=['GET', 'POST'])
    def mi_operacao_itens_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, itens=listar_itens(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = adicionar_item(
                factory, operacao_id, titulo=corpo.get('titulo'), ator=corpo.get('ator') or _ator(),
                tipo=corpo.get('tipo', 'tarefa'), descricao=corpo.get('descricao'),
                data_prevista=corpo.get('data_prevista'), horario=corpo.get('horario'),
                responsavel=corpo.get('responsavel'), prioridade=corpo.get('prioridade', 'normal'),
                depende_de_item_id=corpo.get('depende_de_item_id'), plano_b=corpo.get('plano_b'),
                observacoes=corpo.get('observacoes'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar plano da operação %s', operacao_id)
            return _erro('Plano indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/itens/<item_id>', methods=['PATCH'])
    def mi_operacao_item_atualizar(item_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = atualizar_item(factory, item_id, corpo.get('campos') or {}, corpo.get('ator') or _ator())
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao atualizar item %s', item_id)
            return _erro('Plano indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/brainstorm', methods=['GET', 'POST'])
    def mi_operacao_brainstorm_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, brainstorm=listar_brainstorm(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = criar_pergunta_brainstorm(
                factory, operacao_id, pergunta=corpo.get('pergunta'), ator=corpo.get('ator') or _ator(),
                autor_tipo=corpo.get('autor_tipo', 'humano'), autor_nome=corpo.get('autor_nome'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar brainstorm da operação %s', operacao_id)
            return _erro('Brainstorm indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/brainstorm/<brainstorm_id>/executar', methods=['POST'])
    def mi_operacao_brainstorm_executar(brainstorm_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = executar_brainstorm(factory, brainstorm_id, corpo.get('agentes') or [], corpo.get('ator') or _ator())
            return jsonify(resultado), 200 if resultado.get('success') else 502
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao executar brainstorm %s', brainstorm_id)
            return _erro('Conselho indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/brainstorm/<brainstorm_id>/decisao', methods=['POST'])
    def mi_operacao_brainstorm_decisao(brainstorm_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            corpo = request.get_json(silent=True) or {}
            resultado = decidir_brainstorm(factory, brainstorm_id, corpo.get('decisao'), corpo.get('ator') or _ator(),
                                            item_titulo=corpo.get('item_titulo'))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao decidir brainstorm %s', brainstorm_id)
            return _erro('Brainstorm indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/metricas', methods=['GET', 'POST'])
    def mi_operacao_metricas_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, metricas=listar_metricas(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = upsert_metrica(
                factory, operacao_id, nome=corpo.get('nome'), ator=corpo.get('ator') or _ator(),
                valor=corpo.get('valor'), unidade=corpo.get('unidade'), periodo=corpo.get('periodo'),
                formula=corpo.get('formula'), fonte=corpo.get('fonte'), explicacao=corpo.get('explicacao'),
                estado_dado=corpo.get('estado_dado'))
            return jsonify(resultado), 200 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar indicadores da operação %s', operacao_id)
            return _erro('Indicadores indisponíveis no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/financeiro', methods=['GET', 'POST'])
    def mi_operacao_financeiro_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, **resumo_financeiro(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = adicionar_lancamento_financeiro(
                factory, operacao_id, categoria=corpo.get('categoria'), tipo=corpo.get('tipo'),
                valor_centavos=corpo.get('valor_centavos'), ator=corpo.get('ator') or _ator(),
                base_calculo=corpo.get('base_calculo'), formula=corpo.get('formula'),
                premissas=corpo.get('premissas'), fonte=corpo.get('fonte'), periodo=corpo.get('periodo'),
                estado_dado=corpo.get('estado_dado', 'estimativa'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar financeiro da operação %s', operacao_id)
            return _erro('Financeiro indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/arquivos', methods=['GET', 'POST'])
    def mi_operacao_arquivos_colecao(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            if request.method == 'GET':
                return jsonify(success=True, arquivos=listar_arquivos(factory, operacao_id))
            corpo = request.get_json(silent=True) or {}
            resultado = vincular_artefato(factory, operacao_id, corpo.get('artefato_id'),
                                           corpo.get('ator') or _ator(), corpo.get('categoria', 'documento'))
            return jsonify(resultado), 201 if resultado.get('success') else 400
        except ValueError as erro:
            return _erro(str(erro))
        except Exception:
            app.logger.exception('Falha ao processar arquivos da operação %s', operacao_id)
            return _erro('Arquivos indisponíveis no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/historico', methods=['GET'])
    def mi_operacao_historico(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            return jsonify(success=True, auditoria=listar_auditoria(factory, operacao_id))
        except Exception:
            app.logger.exception('Falha ao ler histórico da operação %s', operacao_id)
            return _erro('Histórico indisponível no momento.', 503)

    @app.route('/api/admin/mi/operacoes/<operacao_id>/investidor', methods=['GET'])
    def mi_operacao_investidor(operacao_id):
        if not autorizado():
            return _erro('Não autorizado.', 401)
        try:
            visao = visao_investidor(factory, operacao_id)
            if not visao:
                return _erro('Operação não encontrada.', 404)
            return jsonify(success=True, **visao)
        except Exception:
            app.logger.exception('Falha ao montar visão investidor da operação %s', operacao_id)
            return _erro('Visão do investidor indisponível no momento.', 503)
