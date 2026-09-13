"""Barramento comum e extensível de sinais do Maranhão Intelligence.

Domínio distinto de mi_eventos.py (QR/NFC, migrations 007-012, rastreabilidade
física SKU->lote->unidade -- permanece intocado). mi_sinais observa processos
de negócio internos (CRM, prospecção, ações comerciais, pedidos, e
futuramente Gmail/Instagram/WhatsApp quando a Meta estiver disponível/TikTok)
através de uma única interface: emitir(). Nenhum produtor escreve direto na
tabela; nenhum produtor pode travar o próprio fluxo de negócio caso o
registro do sinal falhe -- isso é só observabilidade, nunca uma dependência
operacional.

O MI não é uma cópia do CRM/Gmail/prospecção: cada sinal carrega origem +
origem_id (referência ao registro original) e um payload mínimo, nunca uma
cópia dos dados de origem. Nomes/e-mails/telefones/endereços não pertencem
ao payload -- quando for preciso saber "quem", quem chama consulta o sistema
de origem pelo origem_id.

Todo sinal declara sua NATUREZA; uma inferência da IA nunca vira fato:
- fato: algo que de fato aconteceu, já commitado no sistema de origem.
- inferencia: leitura/classificação automática, ainda não confirmada por
  decisão humana.
- recomendacao: proposta de ação futura pendente de decisão humana.
- acao: uma decisão ou execução foi de fato tomada (humano ou executor
  aprovado), distinta do fato que a originou.
- resultado: desfecho observável de uma ação já executada.
"""
import hashlib
import json
import re
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from psycopg2.extras import RealDictCursor, Json
from mi_skus import normalizar_sku, sku_existe
from mi_estabelecimentos import estabelecimento_existe
from mi_unidades import unidade_utilizavel
from mi_lotes import lote_existe_por_id

NATUREZAS = ('fato', 'inferencia', 'recomendacao', 'acao', 'resultado')
CAMPOS = ('natureza', 'origem', 'tipo_evento', 'canal', 'origem_id', 'sku',
          'estabelecimento_id', 'unidade_id', 'lote_id', 'territorio_uf',
          'territorio_cidade', 'confianca', 'resultado', 'ocorrido_em', 'payload')
CAMPOS_TEXTO = ('canal', 'origem_id', 'territorio_cidade', 'resultado')
PADRAO_IDENTIFICADOR = re.compile(r'[a-z][a-z0-9_]{0,63}')

# Namespace fixo só para gerar chaves de idempotência determinísticas em
# emitir(); não precisa de significado externo, só precisa ser estável.
_NAMESPACE_SINAIS = uuid5(NAMESPACE_URL, 'maranhao-cordial:mi_sinais')


def validar_sinal(body):
    if not isinstance(body, dict) or set(body) - set(CAMPOS) - {'chave'}:
        raise ValueError('campos_invalidos')
    chave = str(UUID(str(body.get('chave'))))
    d = {k: body.get(k) for k in CAMPOS}

    if d['natureza'] not in NATUREZAS:
        raise ValueError('natureza_invalida')

    if not isinstance(d['origem'], str) or not PADRAO_IDENTIFICADOR.fullmatch(d['origem']):
        raise ValueError('origem_invalida')

    if not isinstance(d['tipo_evento'], str) or not PADRAO_IDENTIFICADOR.fullmatch(d['tipo_evento']):
        raise ValueError('tipo_evento_invalido')

    if d['sku'] is not None:
        d['sku'] = normalizar_sku(d['sku'])

    for campo in ('estabelecimento_id', 'unidade_id', 'lote_id'):
        if d[campo] is not None:
            d[campo] = str(UUID(str(d[campo])))

    for campo in CAMPOS_TEXTO:
        valor = d[campo]
        if valor is not None:
            if not isinstance(valor, str) or len(valor) > 500:
                raise ValueError('texto_invalido:' + campo)
            d[campo] = valor.strip() or None

    if d['territorio_uf'] is not None:
        if not isinstance(d['territorio_uf'], str) or not re.fullmatch(r'[A-Z]{2}', d['territorio_uf']):
            raise ValueError('territorio_uf_invalido')

    if d['confianca'] is not None:
        if isinstance(d['confianca'], bool) or not isinstance(d['confianca'], (int, float)):
            raise ValueError('confianca_invalida')
        if not (0 <= d['confianca'] <= 1):
            raise ValueError('confianca_fora_do_intervalo')
        d['confianca'] = float(d['confianca'])

    if d['ocorrido_em'] is not None:
        if not isinstance(d['ocorrido_em'], str):
            raise ValueError('ocorrido_em_invalido')
        d['ocorrido_em'] = datetime.fromisoformat(d['ocorrido_em']).isoformat()

    payload = d['payload'] if d['payload'] is not None else {}
    if not isinstance(payload, dict):
        raise ValueError('payload_invalido')
    d['payload'] = payload

    digest = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return chave, d, digest


def registrar_sinal_mi(factory, body):
    chave, d, digest = validar_sinal(body)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if d['sku'] is not None:
                    sku_existe(cur, d['sku'])
                if d['estabelecimento_id'] is not None:
                    estabelecimento_existe(cur, d['estabelecimento_id'])
                if d['unidade_id'] is not None:
                    unidade_utilizavel(cur, d['unidade_id'])
                if d['lote_id'] is not None:
                    lote_existe_por_id(cur, d['lote_id'])
                cur.execute(
                    "INSERT INTO mi_sinais(id,chave,payload_hash," + ",".join(CAMPOS) + ") "
                    "VALUES(" + ",".join(["%s"] * (len(CAMPOS) + 3)) + ") "
                    "ON CONFLICT(chave) DO NOTHING RETURNING id",
                    [str(uuid4()), chave, digest] + [Json(d[k]) if k == 'payload' else d[k] for k in CAMPOS],
                )
                novo = cur.fetchone()
                cur.execute("SELECT id, payload_hash FROM mi_sinais WHERE chave=%s", (chave,))
                row = cur.fetchone()
                if row['payload_hash'] != digest:
                    return {'success': False, 'error': 'chave_reutilizada_com_outro_conteudo'}, 409
                if novo:
                    cur.execute(
                        "INSERT INTO mi_sinais_auditoria(sinal_id,evento,ator) VALUES(%s,'recebido',%s)",
                        (novo['id'], d['origem']),
                    )
                return {'success': True, 'id': str(row['id']), 'criado': bool(novo)}, 201 if novo else 200
    finally:
        conn.close()


def emitir(factory, *, discriminador=None, chave=None, **campos):
    """Uso pelos produtores internos (CRM, prospecção, ações comerciais,
    pedidos, ...): nunca propaga exceção e nunca abre uma segunda transação
    dentro da transação de origem -- deve ser chamada só depois que o
    commit do fluxo principal já aconteceu. Falha aqui é observabilidade
    perdida, nunca uma falha operacional do sistema de origem.

    Gera uma chave de idempotência determinística quando não informada,
    a partir de (origem, tipo_evento, origem_id, discriminador) -- assim o
    mesmo fato de negócio nunca alimenta o MI duas vezes, mesmo que o
    produtor seja chamado de novo (retry de webhook, nova tentativa HTTP
    etc.). `discriminador` serve para distinguir sinais que compartilham a
    mesma tripla, ex.: duas mudanças de estágio do mesmo lead.
    """
    try:
        if chave is None:
            base = '|'.join(str(campos.get(k) or '') for k in ('origem', 'tipo_evento', 'origem_id'))
            base += '|' + str(discriminador or '')
            chave = str(uuid5(_NAMESPACE_SINAIS, base))
        return registrar_sinal_mi(factory, dict(campos, chave=chave))
    except Exception as erro:
        print('AVISO MI SINAIS (nao propagado, fluxo de origem continua):', repr(erro))
        return None


# =====================================================
# LEITURA -- consultas preparadas para um futuro painel.
# Nenhuma delas é chamada por mi_painel.py nesta etapa; o painel atual não
# foi redesenhado. Mesmo padrão de mi_painel.gerar_painel_mi(): somente
# leitura, nunca expõe payload bruto.
# =====================================================

def resumo_hoje(cur):
    """'O que aconteceu hoje?' -- contagem por natureza/origem/tipo."""
    cur.execute(
        "SELECT natureza, origem, tipo_evento, count(*) AS total FROM mi_sinais "
        "WHERE criado_em >= date_trunc('day', NOW()) "
        "GROUP BY natureza, origem, tipo_evento ORDER BY total DESC"
    )
    return [dict(r) for r in cur.fetchall()]


def funil_prospeccao(cur, dias=30):
    """'Quantos prospectos foram encontrados/qualificados?'"""
    cur.execute(
        "SELECT tipo_evento, count(*) AS total FROM mi_sinais "
        "WHERE origem='prospeccao_fase57' AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY tipo_evento",
        (dias,),
    )
    return {r['tipo_evento']: r['total'] for r in cur.fetchall()}


def acoes_por_resultado(cur, dias=30):
    """'O que a IA fez?' / 'O que foi bloqueado?'"""
    cur.execute(
        "SELECT tipo_evento, resultado, count(*) AS total FROM mi_sinais "
        "WHERE origem='acoes_comerciais' AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY tipo_evento, resultado ORDER BY total DESC",
        (dias,),
    )
    return [dict(r) for r in cur.fetchall()]


def atividade_por_territorio(cur, dias=7):
    """'Qual território está reagindo?'"""
    cur.execute(
        "SELECT territorio_uf, territorio_cidade, count(*) AS total FROM mi_sinais "
        "WHERE territorio_uf IS NOT NULL AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY territorio_uf, territorio_cidade ORDER BY total DESC",
        (dias,),
    )
    return [dict(r) for r in cur.fetchall()]


def interesse_por_produto(cur, dias=30):
    """'Qual produto está despertando interesse?'"""
    cur.execute(
        "SELECT sku, count(*) AS total FROM mi_sinais "
        "WHERE sku IS NOT NULL AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY sku ORDER BY total DESC",
        (dias,),
    )
    return [dict(r) for r in cur.fetchall()]


def pendencias_direcao(cur):
    """'O que precisa do diretor?' -- recomendações de ação ainda sem decisão humana registrada."""
    cur.execute(
        "SELECT count(*) AS total FROM mi_sinais "
        "WHERE natureza='recomendacao' AND tipo_evento='acao_proposta' "
        "AND (origem_id IS NULL OR origem_id NOT IN ("
        "  SELECT origem_id FROM mi_sinais "
        "  WHERE tipo_evento IN ('acao_aprovada','acao_rejeitada') AND origem_id IS NOT NULL"
        "))"
    )
    return cur.fetchone()['total']


def resumo_site(cur, dias=7):
    """'Site agora' (ETAPA 5.4): visitas/interesses/CTAs/conversões e
    produto/origem em alta -- tudo já em mi_sinais (origem='site'), sem
    tabela nova. 'conversoes' aqui é interesse com formulário real
    (degustação/B2B), não uma venda confirmada (isso é 'pedidos')."""
    cur.execute(
        "SELECT tipo_evento, count(*) AS total FROM mi_sinais "
        "WHERE origem='site' AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY tipo_evento",
        (dias,),
    )
    por_tipo = {r['tipo_evento']: r['total'] for r in cur.fetchall()}

    cur.execute(
        "SELECT payload->>'produto' AS produto, count(*) AS total FROM mi_sinais "
        "WHERE origem='site' AND payload ? 'produto' "
        "AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY payload->>'produto' ORDER BY total DESC LIMIT 1",
        (dias,),
    )
    produto_em_alta = cur.fetchone()

    cur.execute(
        "SELECT canal, count(*) AS total FROM mi_sinais "
        "WHERE origem='site' AND canal IS NOT NULL AND canal <> 'site' "
        "AND criado_em >= NOW() - (%s || ' days')::interval "
        "GROUP BY canal ORDER BY total DESC LIMIT 1",
        (dias,),
    )
    origem_em_alta = cur.fetchone()

    return {
        'visitas': por_tipo.get('pagina_visitada', 0) + por_tipo.get('produto_visitado', 0),
        'interesses': por_tipo.get('produto_visitado', 0) + por_tipo.get('intencao_contato', 0),
        'ctas': por_tipo.get('cta_clicado', 0),
        'conversoes': por_tipo.get('interesse_degustacao', 0) + por_tipo.get('interesse_profissional_b2b', 0),
        'produto_em_alta': produto_em_alta['produto'] if produto_em_alta else None,
        'origem_em_alta': origem_em_alta['canal'] if origem_em_alta else None,
    }
