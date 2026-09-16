"""P3C -- Territory Intelligence v1.

NÃO reimplementa agregação territorial: `inteligencia_territorial.py`
(carregar/recomendar) já agrega cidade/UF, leads_crm, mi_estabelecimentos
(indireto via cidade/UF dos registros), interações omnichannel, pedidos,
propostas/conversões e mi_eventos -- tudo com dados reais, sem inventar
cobertura. Este módulo só reformata a saída já calculada de `recomendar()`
no MESMO envelope de oportunidade usado em `mi_inteligencia_relacionamento`
(P2D): type/priority/confidence/evidence/generated_at + qualidade de dados
explícita -- para os dois níveis (relacionamento e território) ficarem
consistentes para quem consome (painel, mi_decisao, agentes).

Quando `inteligencia_territorial` classifica uma decisão como 'dados
insuficientes', a oportunidade correspondente aparece com
`confidence='NOT_ENOUGH_DATA'` -- nunca é inventada uma prioridade."""
from datetime import datetime, timezone

from inteligencia_territorial import carregar

PRIORIDADE_POR_CLASSIFICACAO = {'evidência suficiente': 'alta', 'sinal inicial': 'normal'}
CONFIANCA_POR_CLASSIFICACAO = {'evidência suficiente': 0.8, 'sinal inicial': 0.5}


def oportunidades_territoriais(report, agora=None):
    """`report` é o retorno de `inteligencia_territorial.carregar(factory)`
    -- este módulo nunca consulta o banco diretamente, só reformata."""
    agora = agora or datetime.now(timezone.utc)
    decisoes = report.get('decisoes') or {}
    oportunidades = []
    for tipo, dados in decisoes.items():
        classificacao = dados.get('classificacao')
        base = {
            'type': f'territorial_{tipo}',
            'territory': dados.get('territorio'),
            'territory_id': dados.get('territorio_id'),
            'generated_at': agora.isoformat(),
            'data_quality': {'classificacao': classificacao, 'dados_faltantes': dados.get('dados_faltantes') or []},
        }
        if classificacao == 'dados insuficientes' or not dados.get('territorio'):
            oportunidades.append({**base, 'priority': None, 'confidence': 'NOT_ENOUGH_DATA', 'evidence': []})
            continue
        oportunidades.append({
            **base,
            'priority': PRIORIDADE_POR_CLASSIFICACAO.get(classificacao, 'normal'),
            'confidence': CONFIANCA_POR_CLASSIFICACAO.get(classificacao, 0.4),
            'evidence': dados.get('por_que') or [],
        })
    return {'generated_at': agora.isoformat(), 'opportunities': oportunidades, 'dados_hash': report.get('dados_hash')}


def registrar_rotas_leitura(app, factory, autorizado):
    """Só GET -- nenhuma escrita; a agregação em si já é read-only
    (inteligencia_territorial.carregar não persiste nada)."""
    from flask import jsonify

    @app.route('/api/admin/mi/territorio/oportunidades', methods=['GET'])
    def mi_territorio_oportunidades():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            report = carregar(factory)
            resultado = oportunidades_territoriais(report)
        except Exception:
            app.logger.exception('Falha ao calcular oportunidades territoriais')
            return jsonify(success=False, error='Território indisponível.'), 503
        return jsonify(success=True, **resultado)
