"""Observabilidade do Conselho de Agentes -- "Saúde dos Agentes".

Um registro por execução real de especialista (sucesso ou falha), escrito
por `mi_conselho_executor.executar_especialista_monitorado` -- nunca decide
nada, nunca chama LLM, só grava/lê telemetria. Mesmo padrão de
mi_conselho_fatos.py (factory, RealDictCursor, append-only).

NUNCA guarda prompt, resposta bruta, segredo ou stack trace -- só categoria
de erro (nome da exceção) e um detalhe truncado e seguro (a mesma string
curta já usada em `erros[]` do Conselho, nunca o conteúdo do parecer).
Falha de um agente é sempre `status='falha'`, nunca reinterpretada como
sucesso parcial em lugar nenhum aqui.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from psycopg2.extras import RealDictCursor

STATUS_VALIDOS = ('sucesso', 'falha')
ORIGENS_VALIDAS = ('automatico', 'interativo')
JANELA_PADRAO_HORAS = 24


def validar_execucao(body):
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    agente = body.get('agente')
    if not isinstance(agente, str) or not agente:
        raise ValueError('agente_invalido')
    status = body.get('status')
    if status not in STATUS_VALIDOS:
        raise ValueError('status_invalido')
    origem = body.get('origem')
    if origem not in ORIGENS_VALIDAS:
        raise ValueError('origem_invalida')
    duracao_ms = body.get('duracao_ms')
    if duracao_ms is not None and (not isinstance(duracao_ms, int) or duracao_ms < 0):
        raise ValueError('duracao_invalida')

    def _texto_curto(campo, tamanho):
        valor = body.get(campo)
        if valor is None:
            return None
        return str(valor)[:tamanho]

    def _inteiro(campo):
        valor = body.get(campo)
        return int(valor) if isinstance(valor, int) else None

    return {
        'agente': agente[:64], 'origem': origem, 'status': status,
        'erro_categoria': _texto_curto('erro_categoria', 100),
        'erro_detalhe': _texto_curto('erro_detalhe', 240),
        'duracao_ms': duracao_ms, 'modelo': _texto_curto('modelo', 100),
        'tentativas': _inteiro('tentativas'),
        'tokens_entrada': _inteiro('tokens_entrada'), 'tokens_saida': _inteiro('tokens_saida'),
        'tokens_raciocinio': _inteiro('tokens_raciocinio'),
    }


def registrar_execucao(factory, body):
    """Sempre um INSERT novo -- telemetria é fato pontual de uma chamada
    real, nunca corrigida/sobrescrita. Quem chama decide se uma falha ao
    gravar aqui deve ou não interromper o fluxo (o executor deliberadamente
    ignora essa falha -- ver comentário em executar_especialista_monitorado)."""
    dados = validar_execucao(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO mi_conselho_execucoes(id,agente,origem,status,erro_categoria,erro_detalhe,"
                    "duracao_ms,modelo,tentativas,tokens_entrada,tokens_saida,tokens_raciocinio) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (str(uuid4()), dados['agente'], dados['origem'], dados['status'], dados['erro_categoria'],
                     dados['erro_detalhe'], dados['duracao_ms'], dados['modelo'], dados['tentativas'],
                     dados['tokens_entrada'], dados['tokens_saida'], dados['tokens_raciocinio']),
                )
                return {'success': True, 'id': str(cur.fetchone()['id'])}, 201
    finally:
        conn.close()


def _resumo_agente(agente, linhas):
    """Agrega as execuções de UM agente dentro da janela consultada --
    última execução (mais recente por executado_em), taxa de sucesso, e
    contagem de falhas por categoria (nunca detalhe cru na agregação, só a
    categoria -- o detalhe fica disponível na lista bruta de execuções)."""
    if not linhas:
        return {
            'agente': agente, 'status': 'sem_execucao', 'ultima_execucao': None, 'duracao_ms': None,
            'modelo': None, 'total_execucoes': 0, 'total_sucesso': 0, 'total_falha': 0,
            'taxa_sucesso': None, 'falhas_por_categoria': {}, 'tokens_saida_total': None,
        }
    linhas_ordenadas = sorted(linhas, key=lambda linha: linha['executado_em'], reverse=True)
    ultima = linhas_ordenadas[0]
    total = len(linhas_ordenadas)
    sucessos = [linha for linha in linhas_ordenadas if linha['status'] == 'sucesso']
    falhas = [linha for linha in linhas_ordenadas if linha['status'] == 'falha']
    falhas_por_categoria = {}
    for falha in falhas:
        categoria = falha.get('erro_categoria') or 'desconhecido'
        falhas_por_categoria[categoria] = falhas_por_categoria.get(categoria, 0) + 1
    tokens_saida = [linha['tokens_saida'] for linha in sucessos if linha.get('tokens_saida') is not None]
    return {
        'agente': agente,
        'status': ultima['status'],
        'ultima_execucao': ultima['executado_em'].isoformat(),
        'duracao_ms': ultima['duracao_ms'],
        'erro_categoria': ultima.get('erro_categoria') if ultima['status'] == 'falha' else None,
        'erro_detalhe': ultima.get('erro_detalhe') if ultima['status'] == 'falha' else None,
        'modelo': ultima.get('modelo'),
        'total_execucoes': total, 'total_sucesso': len(sucessos), 'total_falha': len(falhas),
        'taxa_sucesso': round(len(sucessos) / total, 3) if total else None,
        'falhas_por_categoria': falhas_por_categoria,
        'tokens_saida_total': sum(tokens_saida) if tokens_saida else None,
    }


def saude_agentes(cur, agentes_conhecidos, janela_horas=JANELA_PADRAO_HORAS, agora=None):
    """Um resumo por agente conhecido (mesmo os 8 de AGENTES, mesmo sem
    nenhuma execução ainda -- painel nunca esconde 'nunca rodou') dentro da
    janela pedida. `agentes_conhecidos` vem de mi_conselho.AGENTES -- este
    módulo não depende de mi_conselho para não criar import circular com
    mi_conselho_executor."""
    agora = agora or datetime.now(timezone.utc)
    desde = agora - timedelta(hours=janela_horas)
    cur.execute(
        "SELECT agente, origem, status, erro_categoria, erro_detalhe, duracao_ms, modelo, tentativas, "
        "tokens_entrada, tokens_saida, tokens_raciocinio, executado_em FROM mi_conselho_execucoes "
        "WHERE executado_em >= %s ORDER BY executado_em DESC",
        (desde,),
    )
    por_agente = {}
    for linha in cur.fetchall():
        por_agente.setdefault(linha['agente'], []).append(linha)
    return [_resumo_agente(agente, por_agente.get(agente, [])) for agente in agentes_conhecidos]


def historico_execucoes(cur, agente=None, limite=50):
    """Lista bruta (mais recente primeiro) para o painel expandir detalhe de
    um agente específico -- mesmo dado usado no resumo, sem agregação."""
    if agente:
        cur.execute(
            "SELECT * FROM mi_conselho_execucoes WHERE agente=%s ORDER BY executado_em DESC LIMIT %s",
            (agente, limite),
        )
    else:
        cur.execute("SELECT * FROM mi_conselho_execucoes ORDER BY executado_em DESC LIMIT %s", (limite,))
    linhas = []
    for linha in cur.fetchall():
        d = dict(linha)
        d['executado_em'] = d['executado_em'].isoformat()
        linhas.append(d)
    return linhas


def registrar_rotas_saude(app, factory, autorizado):
    from flask import jsonify, request
    from mi_conselho import AGENTES

    @app.route('/api/admin/mi/conselho/saude', methods=['GET'])
    def mi_conselho_saude_painel():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            janela = int(request.args.get('janela_horas', JANELA_PADRAO_HORAS))
            janela = max(1, min(janela, 24 * 30))
        except ValueError:
            janela = JANELA_PADRAO_HORAS
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                resumo = saude_agentes(cur, list(AGENTES.keys()), janela_horas=janela)
        except Exception:
            app.logger.exception('Falha ao consultar saúde do Conselho')
            return jsonify(success=False, error='Painel de saúde indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, janela_horas=janela, agentes=resumo)

    @app.route('/api/admin/mi/conselho/saude/<agente>/historico', methods=['GET'])
    def mi_conselho_saude_historico(agente):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        if agente not in AGENTES:
            return jsonify(success=False, error='Agente desconhecido.'), 404
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                historico = historico_execucoes(cur, agente=agente)
        except Exception:
            app.logger.exception('Falha ao consultar histórico de execuções do Conselho')
            return jsonify(success=False, error='Histórico indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, agente=agente, historico=historico)
