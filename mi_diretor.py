"""Modo Diretor do Maranhão Intelligence (ETAPA 5.2).

Não recria Intelligence, calendário ou público -- só agrega o que já existe
(mi_sinais, mi_decisao e mi_publico via mi_calendario.gerar_calendario_mi)
numa leitura pensada para quem acompanha, não para quem planeja todo dia.

Regra central: a rotina fica silenciosa. leitura_diretor()['chamar_diretor']
só fica necessário=True por um destes cinco motivos -- nunca por uma
atividade rotineira concluída com sucesso:
- decisão necessária (propostas aguardando aprovação humana);
- bloqueio relevante (ação comercial bloqueada);
- risco/erro (execução com resultado incerto);
- oportunidade importante (oportunidade parada com prioridade alta/urgente);
- mudança relevante de público (mi_publico já filtra por relevância).

preview_briefing() gera o CONTEÚDO de um futuro briefing sem nunca chamar o
pipeline real de envio (_enviar_briefing_legado / autonomia_supervisionada.
briefing, ambos em main.py/autonomia_supervisionada.py, intocados nesta
etapa). A regra de no máximo 1 briefing a cada 3 dias vive só nesse
pipeline real -- como ele não foi tocado, a regra continua exatamente como
estava; o preview não conta como um envio e por isso não é throttlado.
"""
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor
from mi_sinais import funil_prospeccao, acoes_por_resultado, resumo_site
from mi_calendario import gerar_calendario_mi
from mi_conselho import leitura_conselho

LIMITE_LISTA = 10
PRIORIDADES_IMPORTANTES = ('alta', 'urgente')


def _por_tipo(atividades, tipo_decisao):
    return [a for a in atividades if a.get('tipo_decisao') == tipo_decisao]


def leitura_diretor(factory, agora=None):
    """Ponto único de leitura do Modo Diretor. Somente leitura -- reaproveita
    gerar_calendario_mi (que já funde mi_decisao + mi_publico) e os
    agregados prontos de mi_sinais; nenhuma consulta nova de negócio."""
    agora = agora or datetime.now(timezone.utc)
    calendario = gerar_calendario_mi(factory)
    colunas = calendario['colunas']
    todas_atividades = [a for lista in colunas.values() for a in lista]

    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            funil = funil_prospeccao(cur)
            acoes = acoes_por_resultado(cur)
            site = resumo_site(cur)
    finally:
        conn.close()

    conselho = leitura_conselho(factory)

    top10 = calendario['inteligencia_de_publico']['top10']
    oportunidades = _por_tipo(todas_atividades, 'oportunidade_parada')
    followups = _por_tipo(todas_atividades, 'followup_devido')
    bloqueios = _por_tipo(todas_atividades, 'bloqueio_pendente')
    aprovacoes = _por_tipo(todas_atividades, 'aprovacao_pendente')
    mudancas_publico = _por_tipo(todas_atividades, 'mudanca_de_interesse')
    acoes_incertas = [r for r in acoes if r.get('tipo_evento') == 'acao_executada' and r.get('resultado') == 'incerta']
    oportunidade_importante = any(o.get('prioridade') in PRIORIDADES_IMPORTANTES for o in oportunidades)
    site_top10 = [i for i in top10 if 'site' in (i.get('fonte') or [])]
    site_mudanca_relevante = any(i.get('tendencia') in ('subindo', 'caindo') for i in site_top10)

    leitura = {
        'ia_trabalhando': calendario['resumo']['ia_trabalhando'],
        'hoje': {
            'planejado': colunas['hoje'][:LIMITE_LISTA],
            'concluido': colunas['concluidas'][:LIMITE_LISTA],
            'aguardando': colunas['aguardando'][:LIMITE_LISTA],
            'bloqueado': colunas['bloqueadas'][:LIMITE_LISTA],
            'oportunidades': oportunidades[:LIMITE_LISTA],
            'precisa_de_mim': colunas['precisa_diretor'][:LIMITE_LISTA],
        },
        'publico': {
            'top10': top10,
            'subindo': [i for i in top10 if i.get('tendencia') == 'subindo'],
            'caindo': [i for i in top10 if i.get('tendencia') == 'caindo'],
            'mudancas_relevantes': mudancas_publico,
            'conteudos_sugeridos_hoje': _por_tipo(colunas['hoje'], 'conteudo_sugerido'),
        },
        'comercial': {
            'prospectos_encontrados': funil.get('prospecto_encontrado', 0),
            'prospectos_qualificados': funil.get('prospecto_qualificado', 0),
            'oportunidades': oportunidades,
            'followups': followups,
            'acoes_comerciais': acoes,
        },
        # Contagens do calendário completo (mi_decisao.calendario -- via
        # mi_calendario.gerar_calendario_mi), não recalculadas aqui.
        'calendario': {
            'hoje': len(colunas['hoje']), 'proximas': len(colunas['proximas']),
            'concluidas': len(colunas['concluidas']), 'bloqueadas': len(colunas['bloqueadas']),
        },
        # mi_sinais.resumo_site -- mesmo bus da ETAPA 4.9, sem tabela nova.
        'site': dict(site, mudanca_relevante=site_mudanca_relevante),
        # mi_conselho.leitura_conselho -- Conselho de Agentes (integração),
        # nenhum motor/fila/calendário paralelo.
        'conselho': {
            'agentes': conselho['agentes'],
            'trabalhando': conselho['trabalhando'],
            'sem_demanda': conselho['sem_demanda'],
            'mensagens_recentes': conselho['mensagens_recentes'][:LIMITE_LISTA],
            'reuniao_mais_recente': (conselho['reunioes_recentes'] or [None])[0],
            'relatorios_recentes': conselho['relatorios_recentes'][:LIMITE_LISTA],
            'conflitos': conselho['conflitos'],
            'vetos': conselho['vetos'],
            'aguardando_diretor': conselho['aguardando_diretor'],
        },
        'proxima_acao_ia': None,
    }

    proxima = calendario['proxima_atividade']
    if proxima:
        leitura['proxima_acao_ia'] = {
            'o_que': proxima.get('proxima_acao'),
            'quando': proxima.get('executar_em'),
            'motivo': proxima.get('motivo') or proxima.get('inferencia'),
        }

    motivos = []
    if aprovacoes:
        motivos.append('decisão necessária')
    if bloqueios:
        motivos.append('bloqueio relevante')
    if acoes_incertas:
        motivos.append('risco/erro em execução')
    if oportunidade_importante:
        motivos.append('oportunidade importante')
    if mudancas_publico:
        motivos.append('mudança relevante de público')
    if conselho['vetos']:
        motivos.append('veto do Conselho de Agentes')
    if conselho['aguardando_diretor']:
        motivos.append('Conselho de Agentes aguardando decisão')
    leitura['chamar_diretor'] = {'necessario': bool(motivos), 'motivos': motivos}
    return leitura


def preview_briefing(factory, agora=None):
    """Conteúdo de um futuro briefing (nunca envia -- 'enviado' é sempre
    False aqui). Não chama _enviar_briefing_legado nem
    autonomia_supervisionada.briefing."""
    agora = agora or datetime.now(timezone.utc)
    leitura = leitura_diretor(factory, agora)
    return {
        'gerado_em': agora.isoformat(),
        'o_que_fiz': leitura['hoje']['concluido'],
        'o_que_aprendi': leitura['publico']['mudancas_relevantes'],
        'o_que_farei': leitura['hoje']['planejado'],
        'publico_agora': leitura['publico']['top10'][:3],
        'oportunidades': leitura['comercial']['oportunidades'],
        'preciso_de_voce': leitura['chamar_diretor'],
        'enviado': False,
    }


def registrar_rotas_mi_diretor(app, factory, autorizado):
    from flask import jsonify

    @app.route('/api/admin/mi/diretor', methods=['GET'])
    def mi_diretor():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(success=True, leitura=leitura_diretor(factory))
        except Exception:
            app.logger.exception('Falha ao gerar leitura do Modo Diretor')
            return jsonify(success=False, error='Leitura do diretor indisponível.'), 503

    @app.route('/api/admin/mi/briefing-preview', methods=['GET'])
    def mi_briefing_preview():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            return jsonify(success=True, briefing=preview_briefing(factory))
        except Exception:
            app.logger.exception('Falha ao gerar preview do briefing')
            return jsonify(success=False, error='Preview de briefing indisponível.'), 503
