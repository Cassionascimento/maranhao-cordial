"""Visão única do relacionamento -- item "DADOS UNIFICADOS".

NÃO cria um CDP novo nem duplica banco: só agrega, para um `lead_id` de
`leads_crm` (o Contact Central que já existe -- ver
`identidades_externas_contato`/`main.py:localizar_contato_central_existente`),
o que já está gravado em três tabelas já existentes e já ligadas por FK:

- `leads_crm` (o contato central em si -- CRM)
- `identidades_externas_contato` (identidades por canal já resolvidas ao
  contato central, cada uma com `confianca`/`criterio_vinculo` -- WhatsApp/
  Instagram/Gmail entram aqui quando o canal identifica a pessoa)
- `interacoes_omnichannel` (histórico de mensagens WhatsApp/Instagram/Gmail
  já unificado em uma tabela só, por `lead_id`)

Site/GA4 fica de fora por desenho: não existe hoje nenhum identificador que
ligue uma sessão de GA4 a um `lead_id` (`analytics_service.py` só lê agregado
ao vivo da API do Google, sem tabela própria) -- incluir aqui seria inventar
identidade, exatamente o que a leitura do Contact Central já evita fazer.
QR/NFC/pedidos: fora de escopo agora (citados como "futuramente" no pedido).

Nenhuma fusão de pessoa acontece aqui -- este módulo só LÊ vínculos que
`identidades_externas_contato`/Contact Central já decidiu (nunca decide por
nome sozinho, ver docstring de `main.py:localizar_contato_central_existente`).
"""
from psycopg2.extras import RealDictCursor

LIMITE_INTERACOES_PADRAO = 30


def buscar_leads(cur, termo, limite=20):
    """Busca por nome/email/telefone/instagram/empresa -- ponto de entrada
    para achar o `lead_id` antes de pedir a visão única (nunca por nome
    isolado como critério de fusão -- aqui é só busca, não vínculo)."""
    termo = (termo or '').strip()
    if not termo:
        return []
    curinga = '%' + termo + '%'
    cur.execute(
        "SELECT id, nome, empresa, email, telefone, instagram, estagio, status "
        "FROM leads_crm WHERE nome ILIKE %s OR empresa ILIKE %s OR email ILIKE %s "
        "OR telefone ILIKE %s OR instagram ILIKE %s ORDER BY atualizado_em DESC LIMIT %s",
        (curinga, curinga, curinga, curinga, curinga, limite),
    )
    return [dict(linha) for linha in cur.fetchall()]


def _lead(cur, lead_id):
    cur.execute(
        "SELECT id, nome, empresa, email, telefone, instagram, estagio, status, prioridade, "
        "origem, canal, criado_em, atualizado_em FROM leads_crm WHERE id=%s",
        (lead_id,),
    )
    linha = cur.fetchone()
    return dict(linha) if linha else None


def _identidades(cur, lead_id):
    cur.execute(
        "SELECT canal, identificador_externo, username_publico, nome_exibicao, status, "
        "criterio_vinculo, confianca, criado_em FROM identidades_externas_contato "
        "WHERE contato_central_id=%s ORDER BY atualizado_em DESC",
        (lead_id,),
    )
    return [dict(linha) for linha in cur.fetchall()]


def _interacoes(cur, lead_id, limite):
    # Texto bruto da mensagem fica de fora do resumo -- painel executivo
    # mostra canal/tipo/classificação/data, não o conteúdo (mesma disciplina
    # de "nunca mostrar prompt/resposta bruta" aplicada aqui a mensagens de
    # cliente real).
    cur.execute(
        "SELECT canal, plataforma, tipo_interacao, classificacao, interesse, criado_em "
        "FROM interacoes_omnichannel WHERE lead_id=%s ORDER BY criado_em DESC LIMIT %s",
        (lead_id, limite),
    )
    return [dict(linha) for linha in cur.fetchall()]


def visao_unica(cur, lead_id, limite_interacoes=LIMITE_INTERACOES_PADRAO):
    lead = _lead(cur, lead_id)
    if not lead:
        return None
    identidades = _identidades(cur, lead_id)
    interacoes = _interacoes(cur, lead_id, limite_interacoes)
    por_canal = {}
    for interacao in interacoes:
        por_canal[interacao['canal']] = por_canal.get(interacao['canal'], 0) + 1
    return {
        'lead': lead,
        'identidades_por_canal': identidades,
        'interacoes_recentes': interacoes,
        'resumo_canais': por_canal,
        'total_interacoes_na_janela': len(interacoes),
    }


def registrar_rotas_visao_unica(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/visao-unica/buscar', methods=['GET'])
    def mi_visao_unica_buscar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        termo = request.args.get('q', '')
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                resultados = buscar_leads(cur, termo)
        except Exception:
            app.logger.exception('Falha ao buscar leads para visão única')
            return jsonify(success=False, error='Busca indisponível.'), 503
        finally:
            conn.close()
        return jsonify(success=True, resultados=resultados)

    @app.route('/api/admin/mi/visao-unica/<lead_id>', methods=['GET'])
    def mi_visao_unica_detalhe(lead_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                visao = visao_unica(cur, lead_id)
        except Exception:
            app.logger.exception('Falha ao montar visão única do contato')
            return jsonify(success=False, error='Visão única indisponível.'), 503
        finally:
            conn.close()
        if not visao:
            return jsonify(success=False, error='Contato não encontrado.'), 404
        return jsonify(success=True, **visao)
