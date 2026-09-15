"""Banco de fatos confirmados do Conselho de Agentes.

Resolve duas lacunas observadas no teste real da falta de ingredientes: (1)
um número citado por um agente (ex.: "+50%", "7-14 dias") não carregava de
onde veio, e (2) nada distinguia um dado confirmado ontem de um dado
confirmado há três meses -- os dois eram lidos como igualmente "atuais".

Não duplica mi_sinais (barramento de fatos/eventos de negócio) nem
mi_conselho_registros (atas/relatórios completos): este módulo guarda só
VALORES pontuais com proveniência (origem_tipo/fonte/confiança) e validade
temporal, consultáveis por tópico -- a peça que faltava para Iris "manter
fatos confirmados reutilizáveis" (em vez de perguntar/estimar de novo a
cada rodada) e para o Conselho nunca tratar um preço/estoque/prazo antigo
como se fosse a leitura de hoje.

Append-only, mesma disciplina de mi_conselho.py/mi_sinais.py: uma correção
NUNCA sobrescreve -- é sempre uma nova linha com obtido_em mais recente. "O
valor atual" de um tópico é sempre a leitura de maior obtido_em (calculado
em código, nunca um UPDATE); linhas antigas continuam lidas pelo histórico
-- histórico não é a mesma coisa que estado atual (nunca promovido um pelo
outro).

Nenhuma chamada de IA/LLM aqui -- só validação e leitura/escrita simples,
mesmo padrão de mi_sinais.py/mi_decisao.py.
"""
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from psycopg2.extras import RealDictCursor

TIPOS_ORIGEM = ('FONTE_INTERNA', 'FORNECEDOR', 'POLITICA', 'CALCULO', 'ESTIMATIVA')
NIVEIS_CONFIANCA = ('alta', 'media', 'baixa')
PADRAO_TOPICO = re.compile(r'^[a-z][a-z0-9_]{0,127}$')
PADRAO_AGENTE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')

# TTL padrão por categoria de tópico (dias) -- só se aplica quando o
# registro não informa `valido_ate` explicitamente. Preço/estoque/prazo/
# disponibilidade/integração envelhecem rápido (por isso o pedido
# explícito de validade temporal); o restante usa um teto mais folgado em
# vez de ficar "atual" para sempre. Categoria por substring do tópico --
# adicionar uma nova é só uma entrada nova aqui, não uma reescrita.
_TTL_PADRAO_DIAS = (
    ('preco', 3), ('custo', 3), ('estoque', 3), ('disponibilidade', 3),
    ('moq', 7), ('lead_time', 7), ('prazo', 7), ('capacidade', 7),
    ('integracao', 1),
)
_TTL_PADRAO_FALLBACK_DIAS = 30


def _ttl_padrao_dias(topico):
    for prefixo, dias in _TTL_PADRAO_DIAS:
        if prefixo in topico:
            return dias
    return _TTL_PADRAO_FALLBACK_DIAS


def validar_fato(body):
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    chave = str(UUID(str(body.get('chave'))))

    topico = body.get('topico')
    if not isinstance(topico, str) or not PADRAO_TOPICO.fullmatch(topico):
        raise ValueError('topico_invalido')

    valor = body.get('valor')
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 500:
        raise ValueError('valor_invalido')

    origem_tipo = body.get('origem_tipo')
    if origem_tipo not in TIPOS_ORIGEM:
        raise ValueError('origem_tipo_invalida')

    confianca = body.get('confianca')
    if confianca is not None and confianca not in NIVEIS_CONFIANCA:
        raise ValueError('confianca_invalida')

    agente_registrante = body.get('agente_registrante')
    if agente_registrante is not None:
        if not isinstance(agente_registrante, str) or not PADRAO_AGENTE.fullmatch(agente_registrante):
            raise ValueError('agente_registrante_invalido')

    unidade = body.get('unidade')
    if unidade is not None and (not isinstance(unidade, str) or len(unidade) > 50):
        raise ValueError('unidade_invalida')

    fonte_detalhe = body.get('fonte_detalhe')
    if fonte_detalhe is not None and (not isinstance(fonte_detalhe, str) or len(fonte_detalhe) > 500):
        raise ValueError('fonte_detalhe_invalido')

    registro_id = body.get('registro_id')
    if registro_id is not None:
        registro_id = str(UUID(str(registro_id)))

    obtido_em = body.get('obtido_em')
    if obtido_em is None:
        obtido_em = datetime.now(timezone.utc)
    elif isinstance(obtido_em, str):
        obtido_em = datetime.fromisoformat(obtido_em)
    elif not isinstance(obtido_em, datetime):
        raise ValueError('obtido_em_invalido')

    valido_ate = body.get('valido_ate')
    if valido_ate is None:
        # ESTIMATIVA nunca fica "sem prazo" -- some com o mesmo TTL da
        # categoria (nunca inventa confiança maior escapando da expiração).
        valido_ate = obtido_em + timedelta(days=_ttl_padrao_dias(topico))
    elif isinstance(valido_ate, str):
        valido_ate = datetime.fromisoformat(valido_ate)
    elif not isinstance(valido_ate, datetime):
        raise ValueError('valido_ate_invalido')

    return chave, {
        'topico': topico, 'valor': valor.strip(), 'unidade': unidade,
        'origem_tipo': origem_tipo, 'fonte_detalhe': fonte_detalhe, 'confianca': confianca,
        'agente_registrante': agente_registrante, 'registro_id': registro_id,
        'obtido_em': obtido_em, 'valido_ate': valido_ate,
    }


def registrar_fato(factory, body):
    """Idempotente por chave -- nunca reescreve um fato já registrado; uma
    correção é sempre um novo registrar_fato com chave nova (histórico
    preservado, mesma disciplina do resto do Conselho)."""
    chave, dados = validar_fato(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO mi_conselho_fatos(id,chave,topico,valor,unidade,origem_tipo,fonte_detalhe,"
                    "confianca,agente_registrante,registro_id,obtido_em,valido_ate) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(chave) DO NOTHING RETURNING id",
                    (str(uuid4()), chave, dados['topico'], dados['valor'], dados['unidade'],
                     dados['origem_tipo'], dados['fonte_detalhe'], dados['confianca'],
                     dados['agente_registrante'], dados['registro_id'], dados['obtido_em'], dados['valido_ate']),
                )
                novo = cur.fetchone()
                cur.execute("SELECT id FROM mi_conselho_fatos WHERE chave=%s", (chave,))
                row = cur.fetchone()
                return {'success': True, 'id': str(row['id']), 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def status_fato(fato, agora=None):
    """ATUAL | DESATUALIZADO | INCERTO -- nunca promove um fato expirado a
    'atual' e nunca esconde que uma ESTIMATIVA (ou confiança baixa) é menos
    firme que um FATO de fonte verificada, mesmo dentro da validade."""
    agora = agora or datetime.now(timezone.utc)
    valido_ate = fato.get('valido_ate')
    if valido_ate is not None and agora > valido_ate:
        return 'DESATUALIZADO'
    if fato.get('origem_tipo') == 'ESTIMATIVA' or fato.get('confianca') == 'baixa':
        return 'INCERTO'
    return 'ATUAL'


def _com_status(fato, agora, atual=None):
    d = dict(fato)
    d['status'] = status_fato(fato, agora)
    if atual is not None:
        d['fato_mais_recente_do_topico'] = atual
    return d


def fato_atual(cur, topico, agora=None):
    """A leitura mais recente de um tópico -- 'estado atual', nunca
    histórico. Ausência de linha significa 'nunca confirmado', não deve
    virar suposição em lugar nenhum que chame isto."""
    cur.execute(
        "SELECT * FROM mi_conselho_fatos WHERE topico=%s ORDER BY obtido_em DESC LIMIT 1",
        (topico,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _com_status(dict(row), agora or datetime.now(timezone.utc), atual=True)


def historico_fato(cur, topico, limite=20, agora=None):
    """Todas as leituras de um tópico, mais recente primeiro -- histórico
    completo, nunca apagado. A primeira linha é o mesmo registro que
    fato_atual() devolveria; as demais são só para consulta/comparação,
    nunca tratadas como estado atual em outro lugar do código."""
    agora = agora or datetime.now(timezone.utc)
    cur.execute(
        "SELECT * FROM mi_conselho_fatos WHERE topico=%s ORDER BY obtido_em DESC LIMIT %s",
        (topico, limite),
    )
    linhas = [dict(r) for r in cur.fetchall()]
    return [_com_status(linha, agora, atual=(indice == 0)) for indice, linha in enumerate(linhas)]


def fatos_atuais_por_prefixo(cur, prefixo, limite=20, agora=None):
    """Estado atual de cada tópico que começa com `prefixo` (ex.: 'preco_')
    -- um valor por tópico distinto (o mais recente), nunca a lista bruta
    de todas as linhas históricas misturadas. Usado por mi_conselho_estado
    para montar 'evidencias' sem duplicar leitura_diretor/mi_sinais."""
    agora = agora or datetime.now(timezone.utc)
    cur.execute(
        "SELECT DISTINCT ON (topico) * FROM mi_conselho_fatos "
        "WHERE topico LIKE %s ORDER BY topico, obtido_em DESC LIMIT %s",
        (prefixo + '%', limite),
    )
    return [_com_status(dict(r), agora, atual=True) for r in cur.fetchall()]


def registrar_rotas_fatos(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/conselho/fatos', methods=['GET'])
    def mi_conselho_fatos_listar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        topico = (request.args.get('topico') or '').strip()
        if not topico or not PADRAO_TOPICO.fullmatch(topico):
            return jsonify(success=False, error='Informe ?topico= válido.'), 400
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='15s'")
                historico = historico_fato(cur, topico)
        except Exception:
            app.logger.exception('Falha ao consultar fatos do Conselho')
            return jsonify(success=False, error='Fatos indisponíveis.'), 503
        finally:
            conn.close()
        return jsonify(success=True, topico=topico, historico=historico)
