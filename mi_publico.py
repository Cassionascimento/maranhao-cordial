"""Inteligência de Público e Conteúdo do Maranhão Intelligence (ETAPA 5.1B).

Reutiliza mi_sinais.py (interesse por produto) e mi_decisao.py (formato de
atividade/chave de idempotência) -- nenhum motor novo. Só lê; nunca publica,
nunca envia, nunca gera conteúdo automaticamente na rede.

FONTES REALMENTE USADAS (o que já existe no banco hoje):
- CRM: leads_crm.interesse -- texto declarado pelo contato/vendedor.
- Interações omnichannel: interacoes_omnichannel.classificacao/.interesse --
  cobre Gmail e WhatsApp hoje (mesma tabela usada por ambos); Instagram e
  TikTok entram automaticamente no mesmo caminho no dia em que também
  gravarem nessa tabela, sem qualquer mudança de código aqui.
- Prospecção: aprendizado_prospeccao_fase57.motivo/.resultado -- é uma
  INFERÊNCIA da IA sobre o resultado de uma campanha, nunca a fala direta
  de alguém.
- Produto/SKU: mi_sinais.interesse_por_produto() (reaproveitada, não
  duplicada) -- é FATO: comportamento real de scan/venda, mais forte que
  texto declarado.
- Site: snapshot GA4 já existente (analytics_service, via
  eventos_empresariais) só entrega um indicador AGREGADO de tráfego
  (usuários/sessões/visualizações) -- sem termo de busca nem página
  individual. Por isso NUNCA vira um "tema" no Top 10; documentado como
  contexto de tendência geral do site, não como fonte por assunto.

O QUE NÃO EXISTE E POR ISSO NÃO É FABRICADO: termos de busca real
(ex.: Search Console), analytics nativo do Instagram/Meta (só o que já
passa por interacoes_omnichannel), TikTok, e qualquer fonte pública de
tendências de mercado. Nenhum desses é simulado -- ficam como pendência
explícita no relatório final.

DIFERENCIAÇÃO EPISTÊMICA (nunca "mais pesquisado" sem evidência de busca):
- interesse_observado: alguém foi classificado ou declarou esse interesse
  -- fato de relacionamento, não de busca.
- inferencia: conclusão da IA sobre um resultado (aprendizado de
  prospecção), não o interesse relatado por ninguém.
- fato: comportamento real e verificável (scan, venda) -- evidência mais
  forte que texto.
- tendencia: leitura agregada de uma métrica ao longo do tempo; hoje só
  existe em nível de site inteiro (GA4), nunca por tema.
- busca: reservado para quando uma fonte real de termos de busca existir.
  Não usado nesta etapa por falta de fonte -- nunca fabricado.

DRY-RUN: planejar_publico() é somente leitura (mesmo padrão de
mi_decisao.planejar). As atividades de conteúdo/mudança que ele calcula têm
o mesmo formato de mi_decisao._decisao() e a mesma chave de idempotência de
mi_decisao.chave_atividade -- prontas para o Calendário Inteligente, nunca
persistidas ou publicadas por esta etapa.
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from psycopg2.extras import RealDictCursor
from mi_sinais import interesse_por_produto
from mi_decisao import _decisao, chave_atividade

NATUREZAS_TEMA = ('interesse_observado', 'inferencia', 'fato', 'tendencia', 'busca')
# Força epistêmica: quando um tema aparece em mais de uma fonte, mantemos a
# natureza de maior evidência já observada para ele.
FORCA_NATUREZA = {'busca': 4, 'fato': 3, 'interesse_observado': 2, 'tendencia': 1, 'inferencia': 0}
CLASSIFICACOES_IGNORADAS = {'spam', 'comunicacao_automatica', 'atendimento', 'suporte'}
SIMBOLOS_TENDENCIA = {'subindo': '↑', 'caindo': '↓', 'estavel': '→', 'novo': '↑', 'saiu_do_top': '↓'}

# Cada slot equilibra marca (manhã), relacionamento (tarde) e venda (noite) --
# nunca só um dos três, como pedido pela ETAPA 5.1B.
SLOTS = {
    'manha': {'hora': 9, 'objetivo': 'descoberta_cultura', 'foco': 'marca',
              'formato': 'reels', 'cta': 'Descubra mais sobre a Maranhão Cordial.'},
    'tarde': {'hora': 14, 'objetivo': 'produto_uso_educacao', 'foco': 'relacionamento',
              'formato': 'carrossel', 'cta': 'Saiba como usar e onde encontrar.'},
    'noite': {'hora': 20, 'objetivo': 'desejo_conversao_comunidade', 'foco': 'venda',
              'formato': 'stories', 'cta': 'Peça o seu ou fale com a gente.'},
}


def _normalizar_tema(texto):
    """Agrupamento simples e honesto: o próprio texto já classificado/
    declarado, normalizado (minúsculas, sem acento/pontuação). Não é
    clusterização semântica -- isso fica para uma etapa futura com uma
    fonte de dados que justifique a complexidade."""
    if not texto or not str(texto).strip():
        return None
    t = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
    t = re.sub(r'[^a-z0-9 ]', ' ', t.lower())
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:120] or None


# =====================================================
# COLETORES -- cada um só lê uma fonte já existente.
# =====================================================

def coletar_interesse_crm(cur, desde, ate, limite=500):
    cur.execute(
        "SELECT interesse, tipo_lead, cidade, estado FROM leads_crm "
        "WHERE interesse IS NOT NULL AND trim(interesse) <> '' "
        "AND COALESCE(cadastro_teste, FALSE) = FALSE "
        "AND atualizado_em >= %s AND atualizado_em < %s LIMIT %s",
        (desde, ate, limite),
    )
    mencoes = []
    for row in cur.fetchall():
        tema = _normalizar_tema(row.get('interesse'))
        if not tema:
            continue
        mencoes.append({'tema': tema, 'peso': 1.0, 'natureza': 'interesse_observado', 'fonte': 'crm',
                         'publico': row.get('tipo_lead'), 'territorio_uf': row.get('estado'),
                         'territorio_cidade': row.get('cidade'), 'sku': None})
    return mencoes


def coletar_interesse_interacoes(cur, desde, ate, limite=500):
    """Cobre Gmail e WhatsApp hoje (mesma tabela); Instagram/TikTok entram
    sozinhos quando também gravarem em interacoes_omnichannel."""
    cur.execute(
        "SELECT i.classificacao, i.interesse, i.canal, l.cidade, l.estado FROM interacoes_omnichannel i "
        "LEFT JOIN leads_crm l ON l.id = i.lead_id "
        "WHERE i.criado_em >= %s AND i.criado_em < %s LIMIT %s",
        (desde, ate, limite),
    )
    mencoes = []
    for row in cur.fetchall():
        base = {'peso': 1.0, 'natureza': 'interesse_observado', 'fonte': 'interacoes_omnichannel',
                'publico': row.get('canal'), 'territorio_uf': row.get('estado'),
                'territorio_cidade': row.get('cidade'), 'sku': None}
        classificacao = (row.get('classificacao') or '').strip().lower()
        if classificacao and classificacao not in CLASSIFICACOES_IGNORADAS:
            tema = _normalizar_tema(classificacao)
            if tema:
                mencoes.append(dict(base, tema=tema))
        tema_livre = _normalizar_tema(row.get('interesse'))
        if tema_livre:
            mencoes.append(dict(base, tema=tema_livre))
    return mencoes


def coletar_inferencia_prospeccao(cur, desde, ate, limite=500):
    cur.execute(
        "SELECT motivo, resultado, publico, regiao, peso FROM aprendizado_prospeccao_fase57 "
        "WHERE criado_em >= %s AND criado_em < %s LIMIT %s",
        (desde, ate, limite),
    )
    mencoes = []
    for row in cur.fetchall():
        tema = _normalizar_tema(row.get('motivo')) or _normalizar_tema(row.get('resultado'))
        if not tema:
            continue
        mencoes.append({'tema': tema, 'peso': float(row.get('peso') or 1.0), 'natureza': 'inferencia',
                         'fonte': 'aprendizado_prospeccao_fase57', 'publico': row.get('publico'),
                         'territorio_uf': None, 'territorio_cidade': row.get('regiao'), 'sku': None})
    return mencoes


def coletar_interesse_produto(cur, dias=30, limite=10):
    """Reaproveita mi_sinais.interesse_por_produto -- nunca reimplementada."""
    mencoes = []
    for row in interesse_por_produto(cur, dias=dias)[:limite]:
        sku = row.get('sku')
        total = row.get('total') or 0
        if not sku or total <= 0:
            continue
        mencoes.append({'tema': _normalizar_tema(sku), 'peso': float(total), 'natureza': 'fato',
                         'fonte': 'mi_sinais', 'publico': None, 'territorio_uf': None,
                         'territorio_cidade': None, 'sku': sku})
    return mencoes


def coletar_interesse_site(cur, desde, ate, limite=500):
    """Site público (ETAPA 5.4): produto visitado e CTA clicado, já
    capturados em mi_sinais (origem='site'). Só vira tema quando há
    evidência real de produto/CTA no payload -- eventos genéricos (ex.:
    'pagina_visitada' sem produto) nunca fabricam um tema aqui."""
    cur.execute(
        "SELECT tipo_evento, payload FROM mi_sinais "
        "WHERE origem='site' AND tipo_evento IN ('produto_visitado','cta_clicado') "
        "AND criado_em >= %s AND criado_em < %s LIMIT %s",
        (desde, ate, limite),
    )
    mencoes = []
    for row in cur.fetchall():
        payload = row.get('payload') or {}
        campo = 'produto' if row['tipo_evento'] == 'produto_visitado' else 'cta'
        tema = _normalizar_tema(payload.get(campo))
        if not tema:
            continue
        mencoes.append({'tema': tema, 'peso': 1.0, 'natureza': 'interesse_observado', 'fonte': 'site',
                         'publico': None, 'territorio_uf': None, 'territorio_cidade': None, 'sku': None})
    return mencoes


# =====================================================
# TOP 10
# =====================================================

def calcular_top10(cur, desde, ate, dias_produto=30, limite=10):
    mencoes = []
    mencoes += coletar_interesse_crm(cur, desde, ate)
    mencoes += coletar_interesse_interacoes(cur, desde, ate)
    mencoes += coletar_inferencia_prospeccao(cur, desde, ate)
    mencoes += coletar_interesse_produto(cur, dias_produto)
    mencoes += coletar_interesse_site(cur, desde, ate)

    agregados = {}
    for m in mencoes:
        item = agregados.setdefault(m['tema'], {
            'tema': m['tema'], 'intensidade': 0.0, 'fontes': set(), 'naturezas': set(),
            'publicos': set(), 'territorios': set(), 'skus': set(),
        })
        item['intensidade'] += m['peso']
        item['fontes'].add(m['fonte'])
        item['naturezas'].add(m['natureza'])
        if m.get('publico'):
            item['publicos'].add(m['publico'])
        if m.get('territorio_uf') or m.get('territorio_cidade'):
            item['territorios'].add((m.get('territorio_uf'), m.get('territorio_cidade')))
        if m.get('sku'):
            item['skus'].add(m['sku'])

    ranking = sorted(agregados.values(), key=lambda i: i['intensidade'], reverse=True)[:limite]
    top10 = []
    for posicao, item in enumerate(ranking, start=1):
        natureza = max(item['naturezas'], key=lambda n: FORCA_NATUREZA.get(n, -1))
        territorio_uf, territorio_cidade = next(iter(item['territorios']), (None, None))
        # Heurística simples e transparente, não uma medida estatística validada:
        # mais fontes distintas corroboram; mais intensidade também soma, com teto.
        confianca = min(1.0, 0.3 + 0.15 * len(item['fontes']) + 0.05 * min(item['intensidade'], 10))
        top10.append({
            'posicao': posicao, 'tema': item['tema'], 'natureza': natureza,
            'fonte': sorted(item['fontes']), 'intensidade': round(item['intensidade'], 2),
            'publico_segmento': sorted(item['publicos']) or None,
            'territorio_uf': territorio_uf, 'territorio_cidade': territorio_cidade,
            'produto_relacionado': sorted(item['skus'])[0] if item['skus'] else None,
            'confianca': round(confianca, 2),
            'periodo': {'desde': desde, 'ate': ate},
        })
    return top10


# =====================================================
# DETECÇÃO DE MUDANÇAS
# =====================================================

def detectar_mudancas(atual, anterior, limite_posicoes=3, limite_intensidade_relativa=0.5):
    """Compara dois períodos por tema. 'Relevante' exige uma mudança de
    verdade (posição ou intensidade) -- pequenas oscilações não disparam
    PRECISA_INFORMAR_DIRETOR."""
    pos_anterior = {item['tema']: item['posicao'] for item in anterior}
    intensidade_anterior = {item['tema']: item['intensidade'] for item in anterior}
    temas_atuais = {item['tema'] for item in atual}
    mudancas = []
    for item in atual:
        tema = item['tema']
        if tema not in pos_anterior:
            mudancas.append({'tema': tema, 'tipo': 'novo', 'posicao_atual': item['posicao'],
                              'posicao_anterior': None, 'relevante': item['posicao'] <= 5})
            continue
        delta_pos = pos_anterior[tema] - item['posicao']  # positivo = subiu no ranking
        i_ant = intensidade_anterior.get(tema) or 0
        delta_rel = (item['intensidade'] - i_ant) / i_ant if i_ant > 0 else (1.0 if item['intensidade'] > 0 else 0.0)
        if delta_pos >= limite_posicoes:
            tipo = 'subindo'
        elif delta_pos <= -limite_posicoes:
            tipo = 'caindo'
        else:
            tipo = 'estavel'
        relevante = abs(delta_pos) >= limite_posicoes or abs(delta_rel) >= limite_intensidade_relativa
        mudancas.append({'tema': tema, 'tipo': tipo, 'posicao_atual': item['posicao'],
                          'posicao_anterior': pos_anterior[tema], 'relevante': relevante})
    for tema in set(pos_anterior) - temas_atuais:
        mudancas.append({'tema': tema, 'tipo': 'saiu_do_top', 'posicao_atual': None,
                          'posicao_anterior': pos_anterior[tema], 'relevante': pos_anterior[tema] <= 5})
    return mudancas


def mudancas_para_atividades(mudancas):
    """Só mudanças relevantes viram PRECISA_DIRETOR -- nunca uma nova
    tentativa automática, nunca um alerta por oscilação pequena."""
    atividades = []
    for m in mudancas:
        if not m['relevante']:
            continue
        item = _decisao(
            'mi_publico', None, 'mudanca_de_interesse', [f"tema:{m['tema']}:{m['tipo']}"],
            f"assunto '{m['tema']}' {m['tipo']} (posição {m['posicao_anterior']} -> {m['posicao_atual']})",
            'alta', 0.7, 'informar_diretor',
        )
        item['estado'] = 'precisa_diretor'
        atividades.append(item)
    return atividades


# =====================================================
# SUGESTÃO DE CONTEÚDO (nunca publica -- só sugere)
# =====================================================

def sugerir_conteudo(top10):
    """Até 3 posts/dia: manhã=descoberta/cultura, tarde=produto/educação,
    noite=desejo/conversão. Evita repetir o mesmo tema entre os slots
    quando o Top 10 tem mais de uma opção."""
    if not top10:
        return []
    usados = set()

    def escolher(preferencia=None):
        for item in top10:
            if item['tema'] not in usados and (preferencia is None or preferencia(item)):
                usados.add(item['tema'])
                return item
        for item in top10:
            if item['tema'] not in usados:
                usados.add(item['tema'])
                return item
        return None  # todos já usados (Top 10 com 1 ou 2 itens só)

    maior_intensidade = top10[0]['intensidade']
    escolhidos = {
        'manha': escolher(),
        'tarde': escolher(lambda i: bool(i.get('produto_relacionado'))),
        'noite': escolher(lambda i: bool(i.get('produto_relacionado')) or i['intensidade'] >= maior_intensidade),
    }

    posts = []
    for slot, item in escolhidos.items():
        if item is None:
            continue
        cfg = SLOTS[slot]
        publico = (item.get('publico_segmento') or ['geral'])[0]
        posts.append({
            'slot': slot, 'tema': item['tema'], 'objetivo': cfg['objetivo'], 'publico': publico,
            'canal': 'instagram', 'formato': cfg['formato'],
            'ideia': f"Post de {cfg['foco']} ({cfg['objetivo']}) a partir do interesse em '{item['tema']}'.",
            'cta': cfg['cta'], 'produto_relacionado': item.get('produto_relacionado'),
            'sinal_que_justificou': {'tema': item['tema'], 'posicao': item['posicao'],
                                      'fonte': item['fonte'], 'intensidade': item['intensidade'],
                                      'natureza': item['natureza']},
            'foco': cfg['foco'],
        })
    return posts


def atividades_de_conteudo(posts, agora=None):
    """Cada post sugerido vira uma atividade autônoma no Calendário
    Inteligente (não exige aprovação porque não publica nada sozinha --
    só chega planejada, pronta para o diretor revisar quando quiser)."""
    agora = agora or datetime.now(timezone.utc)
    fuso = agora.tzinfo or timezone.utc
    atividades = []
    for post in posts:
        hora = SLOTS[post['slot']]['hora']
        executar_em = datetime(agora.year, agora.month, agora.day, hora, tzinfo=fuso)
        item = _decisao(
            'mi_conteudo', None, 'conteudo_sugerido',
            [f"top10:{post['tema']}:{post['sinal_que_justificou']['fonte']}"],
            f"sugestão de conteúdo ({post['slot']}) para o tema '{post['tema']}'",
            'normal', post['sinal_que_justificou'].get('natureza') and 0.6 or 0.5, 'sugerir_conteudo',
            exige_aprovacao=False, executar_em=executar_em,
        )
        # Detalhe completo do post (ideia/CTA/canal/formato): não cabe no
        # contrato estreito de mi_decisao.CAMPOS. Guardado à parte por ora;
        # persistência real precisará de uma coluna própria em
        # mi_fila_operacional -- pendência explícita, não fabricada aqui.
        item['detalhe_conteudo'] = post
        atividades.append(item)
    return atividades


# =====================================================
# ORQUESTRADOR -- DRY-RUN, só lê.
# =====================================================

def planejar_publico(factory, agora=None):
    agora = agora or datetime.now(timezone.utc)
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            desde_atual, ate_atual = agora - timedelta(days=7), agora
            desde_anterior, ate_anterior = agora - timedelta(days=14), agora - timedelta(days=7)
            top10_atual = calcular_top10(cur, desde_atual, ate_atual)
            top10_anterior = calcular_top10(cur, desde_anterior, ate_anterior)
    finally:
        conn.close()

    mudancas = detectar_mudancas(top10_atual, top10_anterior)
    tendencia_por_tema = {m['tema']: m['tipo'] for m in mudancas}
    for item in top10_atual:
        tipo = tendencia_por_tema.get(item['tema'], 'novo')
        item['tendencia'] = tipo
        item['tendencia_simbolo'] = SIMBOLOS_TENDENCIA.get(tipo, '→')

    posts = sugerir_conteudo(top10_atual)
    atividades = mudancas_para_atividades(mudancas) + atividades_de_conteudo(posts, agora)
    for a in atividades:
        a['chave'] = chave_atividade(a, agora)

    return {
        'top10': top10_atual,
        'mudancas': mudancas,
        'mudou_desde_ultima_analise': any(m['relevante'] for m in mudancas),
        'posts_sugeridos': posts,
        'atividades_calendario': atividades,
    }


def leitura_painel_publico(resultado):
    """Prepara as 7 leituras pedidas pelo painel futuro (item 6). Não é o
    painel -- só a agregação que um futuro componente consumiria."""
    top10 = resultado['top10']
    return {
        'o_que_publico_quer_agora': top10[:3],
        'top10_assuntos': top10,
        'subindo': [i for i in top10 if i['tendencia'] == 'subindo'],
        'caindo': [i for i in top10 if i['tendencia'] == 'caindo'],
        'posts_sugeridos_hoje': resultado['posts_sugeridos'],
        'oportunidades_de_venda': [i for i in top10 if i.get('produto_relacionado')],
        'mudou_desde_ultima_analise': resultado['mudou_desde_ultima_analise'],
        'mudancas_relevantes': [m for m in resultado['mudancas'] if m['relevante']],
    }
