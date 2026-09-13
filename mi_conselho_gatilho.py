"""Detector de relevância do Conselho de Agentes -- menor camada para
transformar sinais novos de `mi_sinais` em demandas para o Conselho.

Fluxo: mi_sinais -> este módulo decide "isso vale demanda?" (Python puro,
sem nenhuma chamada de Agent/token) -> se relevante, monta um texto
factual curto -> mi_conselho_orquestrador.classificar_especialistas (já
existente, reaproveitado, nunca duplicado) escolhe os especialistas.
Quem efetivamente executa os agentes continua sendo uma sessão de Claude
Code chamando Agent(...) -- mesma limitação já documentada em
mi_conselho_orquestrador.py: esta interface não tem um mecanismo de
callback/daemon que dispare isso sozinho.

Este módulo NÃO é um scheduler/daemon: expõe funções simples, chamáveis
sob demanda (por uma sessão interativa ou, futuramente, por um worker que
ainda não existe e não é criado aqui). Nenhuma chamada de Agent, nenhuma
alteração de fórmula/lote/unidade, nenhum envio externo -- só leitura de
`mi_sinais` e UMA escrita de auditoria (reaproveitando `mi_sinais_auditoria`,
já existente desde a migration 013, sem tabela nova) para marcar "já
avaliado" e nunca reprocessar o mesmo sinal duas vezes.

Escopo desta versão: regras de relevância detalhadas para `origem=
'producao'` e para as origens comerciais que já emitem sinal real em
`mi_sinais` hoje (`crm`, `acoes_comerciais`, `prospeccao_fase57` --
auditados no código antes de escrever isto, nenhum nome inventado).
Sinais de outras origens (`site`, `pedidos`, etc.) ainda não têm regra
própria aqui -- passam como "sem regra definida" (não relevante),
fail-closed, para nunca gerar ruído com critério inventado. Adicionar uma
origem nova é só um novo caso na mesma função, no mesmo padrão -- não uma
reescrita, não um segundo detector.
"""
from psycopg2.extras import RealDictCursor
from mi_conselho_orquestrador import classificar_especialistas

ATOR = 'mi_conselho_gatilho'
EVENTO_RELEVANTE = 'gatilho_conselho_relevante'
EVENTO_IRRELEVANTE = 'gatilho_conselho_irrelevante'
_EVENTOS_GATILHO = (EVENTO_RELEVANTE, EVENTO_IRRELEVANTE)

# Fatos discretos de produção: cada ocorrência já é, por natureza, um
# evento novo e distinto (não uma leitura repetida de série) -- não há
# "valor anterior" seguro para comparar, então cada um é relevante sempre
# que aparece (nunca vira reunião sozinho -- só define a demanda a
# analisar; o Conselho decide gravidade).
SEMPRE_RELEVANTES = {'nao_conformidade', 'problema_embalagem', 'lote_produzido', 'resultado_bancada'}

# Medições numéricas de produção: só viram demanda quando a variação
# contra a última leitura da MESMA série (mesmo sku ou lote_id) ultrapassa
# o limiar -- ('absoluto', N) compara diferença direta (faz sentido para
# pH/Brix, escalas estreitas); ('relativo', N) compara variação percentual
# sobre o valor anterior (faz sentido para custo/rendimento/perda/
# capacidade/estoque, que variam em ordens de grandeza diferentes por
# insumo/produto). Limiares definidos nesta implementação -- ajustáveis
# quando houver dado real para calibrar.
LIMIARES_PRODUCAO = {
    'ph_medido': ('absoluto', 0.2),
    'brix_medido': ('absoluto', 0.5),
    'custo_ingrediente': ('relativo', 0.05),
    'rendimento': ('relativo', 0.05),
    'perda': ('relativo', 0.15),
    'capacidade': ('relativo', 0.10),
    'estoque': ('relativo', 0.20),
    'estabilidade': ('relativo', 0.10),
}

ROTULOS_TIPO_EVENTO = {
    'ph_medido': 'pH medido', 'brix_medido': 'Brix medido',
    'custo_ingrediente': 'Custo de matéria-prima', 'rendimento': 'Rendimento',
    'perda': 'Perda', 'capacidade': 'Capacidade', 'estoque': 'Estoque',
    'estabilidade': 'Estabilidade', 'resultado_bancada': 'Resultado de bancada',
    'lote_produzido': 'Lote produzido', 'problema_embalagem': 'Problema de embalagem',
    'nao_conformidade': 'Não conformidade',
}

TIPOS_PRODUCAO_RECONHECIDOS = set(SEMPRE_RELEVANTES) | set(LIMIARES_PRODUCAO)

# Sinais comerciais reais, auditados no código antes desta etapa (main.py,
# acoes_comerciais.py, fase57_prospeccao_universal.py) -- nenhum nome
# inventado. `lead_criado`, `prospecto_encontrado`, `acao_proposta` e
# `acao_aprovada`/`acao_rejeitada` existem mas ficam de fora de propósito:
# são o volume rotineiro do funil (entrada de lead, proposta da IA ainda
# pendente, decisão humana já registrada em outro lugar) -- exatamente o
# "ruído operacional" que não deve chegar ao LLM.
ORIGENS_COMERCIAIS = ('crm', 'acoes_comerciais', 'prospeccao_fase57')

# Marcos comerciais discretos -- cada ocorrência já é, por natureza, um
# fato novo (não uma leitura repetida de série), relevante sempre que
# aparece.
COMERCIAL_SEMPRE_RELEVANTES = {
    'lead_qualificado', 'prospecto_qualificado', 'prospecto_priorizado',
    'prospecto_descartado', 'acao_bloqueada',
}

# lead_estagio_mudou só é material quando o novo estágio é um destes --
# progressão rotineira de funil (ex.: novo -> contato) não é.
ESTAGIOS_COMERCIAIS_RELEVANTES = {'negociacao', 'cliente', 'perdido'}

ROTULOS_TIPO_EVENTO_COMERCIAL = {
    'lead_qualificado': 'Lead qualificado', 'prospecto_qualificado': 'Prospecto qualificado',
    'prospecto_priorizado': 'Prospecto priorizado', 'prospecto_descartado': 'Prospecto descartado',
    'acao_bloqueada': 'Ação comercial bloqueada', 'acao_executada': 'Ação comercial executada',
    'lead_estagio_mudou': 'Estágio alterado',
}


def _identificador_serie(sinal):
    payload = sinal.get('payload') or {}
    return (payload.get('codigo_lote') or sinal.get('sku') or sinal.get('lote_id')
            or sinal.get('origem_id') or 'não identificado')


def _chave_serie(sinal):
    """'Mesma série' para comparar leituras -- por sku quando houver,
    senão por lote_id. Sem nenhum dos dois, não há série para comparar
    (a leitura é tratada como a primeira, nunca como mudança inventada)."""
    return sinal.get('sku') or sinal.get('lote_id')


def _variacao_material(atual, anterior, regra):
    tipo_limiar, limiar = regra
    try:
        atual = float(atual)
        anterior = float(anterior)
    except (TypeError, ValueError):
        return True, 'valor não numérico -- não é possível comparar com segurança, tratado como relevante'
    diferenca = abs(atual - anterior)
    if tipo_limiar == 'absoluto':
        material = diferenca >= limiar
        detalhe = f'variação de {diferenca:g} (limiar {limiar:g})'
    else:
        base = abs(anterior) if anterior else (abs(atual) or 1.0)
        variacao_relativa = diferenca / base
        material = variacao_relativa >= limiar
        detalhe = f'variação de {variacao_relativa:.1%} (limiar {limiar:.0%})'
    return material, detalhe


def avaliar_relevancia(sinal, valor_anterior=None):
    """Decide, sozinho (sem banco, sem Agent), se um sinal deve virar
    demanda para o Conselho. `valor_anterior` é o valor numérico já lido
    por `valor_anterior_mesma_serie` (ou None) -- passado pronto para
    manter esta função pura e testável sem banco de dados. Um único
    detector, despachando por origem -- nunca um segundo detector."""
    origem = sinal.get('origem')

    if origem == 'producao':
        return _avaliar_producao(sinal, valor_anterior)
    if origem in ORIGENS_COMERCIAIS:
        return _avaliar_comercial(sinal)

    return {'relevante': False,
            'motivo': f"sem regra de relevância definida para origem={origem!r} nesta versão do detector"}


def _avaliar_producao(sinal, valor_anterior):
    tipo_evento = sinal.get('tipo_evento')

    if tipo_evento in SEMPRE_RELEVANTES:
        rotulo = ROTULOS_TIPO_EVENTO.get(tipo_evento, tipo_evento)
        return {'relevante': True, 'motivo': f'{rotulo} é sempre um fato relevante em produção'}

    if tipo_evento in LIMIARES_PRODUCAO:
        payload = sinal.get('payload') or {}
        valor_atual = payload.get('valor')
        if valor_atual is None:
            return {'relevante': True,
                    'motivo': 'payload sem campo "valor" numérico -- não é possível comparar com segurança, '
                              'tratado como relevante'}
        if valor_anterior is None:
            return {'relevante': True, 'motivo': 'primeira leitura registrada para esta série'}
        material, detalhe = _variacao_material(valor_atual, valor_anterior, LIMIARES_PRODUCAO[tipo_evento])
        if material:
            return {'relevante': True, 'motivo': f'mudança material detectada -- {detalhe}'}
        return {'relevante': False, 'motivo': f'sem mudança material -- {detalhe}'}

    return {'relevante': False,
            'motivo': f"tipo_evento={tipo_evento!r} de produção não reconhecido por este detector"}


def _avaliar_comercial(sinal):
    tipo_evento = sinal.get('tipo_evento')
    payload = sinal.get('payload') or {}

    if tipo_evento in COMERCIAL_SEMPRE_RELEVANTES:
        rotulo = ROTULOS_TIPO_EVENTO_COMERCIAL.get(tipo_evento, tipo_evento)
        return {'relevante': True, 'motivo': f'{rotulo} é sempre um marco comercial relevante'}

    if tipo_evento == 'lead_estagio_mudou':
        novo = (payload.get('estagio_novo') or '').strip().lower()
        if novo in ESTAGIOS_COMERCIAIS_RELEVANTES:
            return {'relevante': True, 'motivo': f'mudança de estágio para "{novo}" é materialmente relevante'}
        return {'relevante': False, 'motivo': f'mudança de estágio para "{novo}" é progressão de funil rotineira'}

    if tipo_evento == 'acao_executada':
        resultado = sinal.get('resultado')
        if resultado == 'incerta':
            return {'relevante': True, 'motivo': 'resultado de ação comercial incerto -- anomalia a revisar'}
        return {'relevante': False, 'motivo': f'resultado {resultado!r} de ação comercial é rotina, sem anomalia'}

    return {'relevante': False,
            'motivo': f"tipo_evento={tipo_evento!r} comercial é ruído operacional ou não reconhecido "
                      "por este detector (ex.: lead_criado, prospecto_encontrado, acao_proposta, "
                      "acao_aprovada/acao_rejeitada -- volume rotineiro do funil)"}


def montar_demanda_factual(sinal, valor_anterior=None):
    """Texto curto, só fato -- nunca uma conclusão ('produto inadequado'
    ou 'devemos enviar proposta' pertencem aos especialistas, não a este
    detector). Alimenta `mi_conselho_orquestrador.classificar_
    especialistas` diretamente -- um único gerador, despachando por
    origem, nunca um segundo detector/classificador."""
    if sinal.get('origem') == 'producao':
        return _montar_demanda_producao(sinal, valor_anterior)
    return _montar_demanda_comercial(sinal)


def _montar_demanda_producao(sinal, valor_anterior):
    tipo_evento = sinal.get('tipo_evento')
    identificador = _identificador_serie(sinal)
    rotulo = ROTULOS_TIPO_EVENTO.get(tipo_evento, tipo_evento)
    payload = sinal.get('payload') or {}
    valor_atual = payload.get('valor')

    linhas = [f'Fábrica — {identificador}:']
    if valor_atual is not None:
        linhas.append(f'{rotulo}: {valor_atual}.')
        if valor_anterior is not None:
            linhas.append(f'Valor anterior: {valor_anterior}.')
            linhas.append('Mudança nos dados detectada.')
        else:
            linhas.append('Primeira leitura registrada para esta série.')
    else:
        linhas.append(f'{rotulo} registrado.')
        # 'codigo_lote' já aparece no identificador da série (cabeçalho) --
        # excluído aqui também porque o dump bruto do payload não deve
        # vazar palavras que mudem a classificação (ex.: "lote" arrastando
        # Rua para um caso que não é dela).
        detalhes = {k: v for k, v in payload.items() if k not in ('valor', 'codigo_lote')}
        if detalhes:
            linhas.append(f'Informações registradas: {detalhes}.')
    return ' '.join(linhas)


# Frases naturais e factuais por desfecho de estágio -- cada uma já
# carrega, honestamente (não por "forçar palavra-chave"), o vocabulário do
# próprio desfecho de negócio: negociação em andamento é, de fato, uma
# negociação; um lead marcado "perdido" é, de fato, uma perda de
# oportunidade. É esse vocabulário natural que deixa o classificador já
# existente convocar Leonard/Standard sem nenhum mapeamento paralelo aqui.
_FRASES_ESTAGIO = {
    'negociacao': 'negociação em andamento.',
    'cliente': 'cliente fechado.',
    'perdido': 'perda de oportunidade registrada.',
}


def _montar_demanda_comercial(sinal):
    tipo_evento = sinal.get('tipo_evento')
    identificador = _identificador_serie(sinal)
    rotulo = ROTULOS_TIPO_EVENTO_COMERCIAL.get(tipo_evento, tipo_evento)
    payload = sinal.get('payload') or {}

    linhas = [f'Comercial — lead {identificador}:']
    if tipo_evento == 'lead_estagio_mudou':
        anterior = payload.get('estagio_anterior', 'desconhecido')
        novo = (payload.get('estagio_novo') or 'desconhecido').strip().lower()
        linhas.append(f'estágio alterado de {anterior} para {novo} -- {_FRASES_ESTAGIO.get(novo, "mudança de estágio.")}')
    elif tipo_evento == 'acao_executada':
        linhas.append(f'{rotulo} -- resultado de proposta comercial {sinal.get("resultado")} após envio.')
    elif tipo_evento in ('lead_qualificado', 'prospecto_qualificado'):
        linhas.append(f'{rotulo} -- nova oportunidade comercial identificada.')
    elif tipo_evento == 'prospecto_priorizado':
        linhas.append(f'{rotulo} -- oportunidade comercial relevante identificada.')
    elif tipo_evento == 'prospecto_descartado':
        linhas.append(f'{rotulo} -- perda de oportunidade comercial.')
    elif tipo_evento == 'acao_bloqueada':
        linhas.append(f'{rotulo} -- proposta comercial bloqueada antes do envio.')
    else:
        linhas.append(f'{rotulo} registrado.')
    linhas.append('Mudança nos dados registrada.')
    return ' '.join(linhas)


# =====================================================
# LEITURA/ESCRITA -- mi_sinais (leitura) + mi_sinais_auditoria (marca de
# "já avaliado", tabela já existente, sem migration nova).
# =====================================================

_ORIGENS_RECONHECIDAS = ('producao',) + ORIGENS_COMERCIAIS


def sinais_pendentes(cur, limite=50):
    """Sinais das origens que este detector sabe avaliar (produção +
    comerciais já auditadas) ainda não avaliados por ele -- idempotência
    via ausência de linha correspondente em `mi_sinais_auditoria`, nunca
    reprocessa o mesmo sinal duas vezes. Origem fora da lista nem chega a
    ser lida aqui -- fail-closed também no SQL, não só no Python."""
    cur.execute(
        "SELECT s.id, s.origem, s.tipo_evento, s.sku, s.lote_id, s.origem_id, "
        "s.resultado, s.payload, s.criado_em FROM mi_sinais s "
        "WHERE s.origem = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM mi_sinais_auditoria a WHERE a.sinal_id = s.id AND a.evento = ANY(%s)) "
        "ORDER BY s.criado_em ASC LIMIT %s",
        (list(_ORIGENS_RECONHECIDAS), list(_EVENTOS_GATILHO), limite),
    )
    return [dict(row) for row in cur.fetchall()]


def valor_anterior_mesma_serie(cur, tipo_evento, chave_serie, antes_de):
    """Somente leitura: última medição do mesmo tipo/série antes deste
    sinal. `chave_serie` casa por sku OU lote_id (o que o sinal atual
    tiver preenchido)."""
    if not chave_serie:
        return None
    cur.execute(
        "SELECT payload FROM mi_sinais WHERE origem='producao' AND tipo_evento=%s "
        "AND (sku=%s OR lote_id=%s) AND criado_em < %s "
        "ORDER BY criado_em DESC LIMIT 1",
        (tipo_evento, chave_serie, chave_serie, antes_de),
    )
    row = cur.fetchone()
    if not row:
        return None
    payload = row['payload'] or {}
    return payload.get('valor')


def marcar_avaliado(factory, sinal_id, relevante, ator=ATOR):
    """Única escrita deste módulo: um registro de auditoria dizendo que
    este sinal já foi avaliado (relevante ou não) -- nunca reescreve
    `mi_sinais`, nunca toca fórmula/lote/unidade/pagamento."""
    evento = EVENTO_RELEVANTE if relevante else EVENTO_IRRELEVANTE
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO mi_sinais_auditoria(sinal_id, evento, ator) VALUES(%s, %s, %s)",
                    (sinal_id, evento, ator),
                )
    finally:
        conn.close()


def processar_sinais_pendentes(factory, limite=50):
    """Ponto único de entrada: lê sinais de produção pendentes (somente
    leitura), avalia relevância, monta demanda + classificação de
    especialistas para os relevantes (reaproveitando o classificador já
    validado), e marca TODOS (relevantes e não) como avaliados -- nunca
    reprocessa o mesmo sinal duas vezes.

    NÃO chama Agent, NÃO executa nenhum especialista, NÃO agenda nada
    sozinho -- só prepara o que uma sessão de Claude Code (ou, no futuro,
    um worker que ainda não existe) precisaria para acionar o Conselho já
    validado em rodadas anteriores."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            pendentes = sinais_pendentes(cur, limite=limite)
            avaliacoes = []
            for sinal in pendentes:
                valor_anterior = None
                if sinal['tipo_evento'] in LIMIARES_PRODUCAO:
                    valor_anterior = valor_anterior_mesma_serie(
                        cur, sinal['tipo_evento'], _chave_serie(sinal), sinal['criado_em']
                    )
                avaliacoes.append((sinal, valor_anterior))
    finally:
        conn.close()

    resultados = []
    for sinal, valor_anterior in avaliacoes:
        relevancia = avaliar_relevancia(sinal, valor_anterior)
        resultado = {
            'sinal_id': str(sinal['id']), 'tipo_evento': sinal['tipo_evento'],
            'relevante': relevancia['relevante'], 'motivo': relevancia['motivo'],
        }
        if relevancia['relevante']:
            demanda = montar_demanda_factual(sinal, valor_anterior)
            resultado['demanda'] = demanda
            resultado['classificacao'] = classificar_especialistas(demanda)
        marcar_avaliado(factory, sinal['id'], relevancia['relevante'])
        resultados.append(resultado)
    return resultados
