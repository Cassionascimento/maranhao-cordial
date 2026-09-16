"""Testing Center do Conselho de Agentes -- bateria de casos repetíveis.

Dois grupos, sempre executados juntos por padrão:

- CASOS UNITÁRIOS: validam regra de negócio pura (schema, proveniência,
  ação já em andamento, divergência real, motivo do Diretor, guardrail de
  veto, fato x estimativa) contra pareceres CRIADOS pelo teste -- nunca
  chamam a OpenAI, custam zero, sempre determinísticos.
- CASOS AO VIVO: chamam `executar_especialista` de verdade (Rua, Iris,
  Marie isolados e os três juntos -- exatamente a regressão relatada em
  produção) com o `cliente` que for passado (real em produção; um cliente
  fake injetado nos testes automatizados, mesmo padrão de
  tests/test_mi_conselho_executor.py). NENHUM caso aqui chama
  acoes_comerciais/WhatsApp/Gmail/Pix -- Conselho já é modo observador por
  natureza (ver mi_conselho_executor.py), então nenhum caso de teste pode
  ter efeito externo mesmo rodando ao vivo.

Cada caso devolve {id, grupo, descricao, passou, motivo} -- nunca prompt,
nunca resposta bruta do modelo (o `motivo` é sempre uma frase curta escrita
pelo teste, nunca `str(resposta)`)."""
from datetime import datetime, timezone

import mi_conselho_executor as executor
from mi_conselho_executor import RespostaLLMInvalida, _consolidar

_AVALIADO_TESTE = {'sinal_id': 'teste', 'demanda': 'demanda de teste', 'motivo': 'Testing Center',
                    'tipo_evento': 'teste'}


def _parecer_base(**campos):
    base = {
        'agente': 'standard', 'ciclo': 1, 'demanda': 'demanda de teste',
        'gerado_em': datetime.now(timezone.utc).isoformat(),
        'dados_utilizados': 'dado de teste', 'conclusao': 'conclusão de teste',
        'confianca': 'media', 'riscos': '', 'divergencias': '', 'acao_sugerida': 'acompanhar',
        'necessidade_diretor': False, 'motivo_diretor': '', 'veto': False, 'veto_motivo': None,
        'numeros': [], 'numeros_sem_evidencia': [], 'lacunas': [], 'acao_ja_em_andamento': False,
        'natureza_divergencia': 'nenhuma', 'modelo': 'teste',
    }
    base.update(campos)
    return base


def _ok(id_, grupo, descricao, motivo=''):
    return {'id': id_, 'grupo': grupo, 'descricao': descricao, 'passou': True, 'motivo': motivo or 'ok'}


def _falhou(id_, grupo, descricao, motivo):
    return {'id': id_, 'grupo': grupo, 'descricao': descricao, 'passou': False, 'motivo': motivo}


# ---------------------------------------------------------------- unitários

def _caso_schema_campos_obrigatorios():
    d = 'Todo parecer consolidado traz os campos obrigatórios do schema.'
    faltando = [c for c in executor._CAMPOS_OBRIGATORIOS_PARECER if c not in _parecer_base()]
    if faltando:
        return _falhou('schema_campos_obrigatorios', 'unitario', d, f'faltando: {faltando}')
    return _ok('schema_campos_obrigatorios', 'unitario', d)


def _caso_proveniencia_numerica_sem_tag_e_sinalizada():
    d = 'Número citado em campo decisório sem entrada correspondente em `numeros` vira numeros_sem_evidencia.'
    parecer = _parecer_base(conclusao='Aumento de 50% no custo do insumo neste mês.', numeros=[])
    sem_evidencia = executor.validar_proveniencia_numeros(parecer)
    if sem_evidencia != ['50']:
        return _falhou('proveniencia_numerica', 'unitario', d, f'esperado [\'50\'], obtido {sem_evidencia}')
    return _ok('proveniencia_numerica', 'unitario', d, f'sinalizado corretamente: {sem_evidencia}')


def _caso_proveniencia_numerica_tagueada_nao_e_sinalizada():
    d = 'Número citado E presente em `numeros` com origem/fonte não é sinalizado como sem evidência.'
    parecer = _parecer_base(conclusao='Aumento de 50% no custo do insumo neste mês.',
                             numeros=[{'valor': '50', 'unidade': '%', 'origem': 'FORNECEDOR',
                                       'fonte_detalhe': 'email do fornecedor X em 10/09', 'confianca': 'alta'}])
    sem_evidencia = executor.validar_proveniencia_numeros(parecer)
    if sem_evidencia:
        return _falhou('proveniencia_numerica_tagueada', 'unitario', d, f'não deveria sinalizar, obtido {sem_evidencia}')
    return _ok('proveniencia_numerica_tagueada', 'unitario', d)


def _caso_fato_estimativa_fica_incerto():
    d = 'Fato com origem ESTIMATIVA nunca é lido como ATUAL, mesmo dentro da validade.'
    from mi_conselho_fatos import status_fato
    fato = {'origem_tipo': 'ESTIMATIVA', 'confianca': 'alta', 'valido_ate': None}
    status = status_fato(fato, agora=datetime.now(timezone.utc))
    if status != 'INCERTO':
        return _falhou('fato_vs_estimativa', 'unitario', d, f'esperado INCERTO, obtido {status}')
    return _ok('fato_vs_estimativa', 'unitario', d)


def _caso_acao_ja_em_andamento_nao_duplica_recomendacao():
    d = 'Parecer com acao_ja_em_andamento=True vira confirmação, não recomendação nova.'
    parecer = _parecer_base(agente='rua', acao_sugerida='Reforçar turno de produção', acao_ja_em_andamento=True)
    corpo = _consolidar(_AVALIADO_TESTE, [parecer], [])
    ja_andamento = corpo['dados_apresentados']['recomendacoes_ja_em_andamento'] or []
    if corpo['recomendacoes'] or not ja_andamento:
        return _falhou('acao_ja_em_andamento', 'unitario', d,
                        f'recomendacoes={corpo["recomendacoes"]}, ja_em_andamento={ja_andamento}')
    return _ok('acao_ja_em_andamento', 'unitario', d)


def _caso_divergencia_real_vs_dado_ausente():
    d = 'Só natureza_divergencia=divergencia_real entra em `conflitos`; dado_ausente/risco/hipótese não.'
    p1 = _parecer_base(agente='rua', divergencias='Prazo de 14 dias, incompatível com o prometido.',
                        natureza_divergencia='divergencia_real')
    p2 = _parecer_base(agente='iris', divergencias='Sem dado de estoque atualizado para confirmar.',
                        natureza_divergencia='dado_ausente')
    corpo = _consolidar(_AVALIADO_TESTE, [p1, p2], [])
    conflitos = corpo['conflitos'] or {}
    if 'rua' not in conflitos or 'iris' in conflitos:
        return _falhou('divergencia_real', 'unitario', d, f'conflitos={conflitos}')
    return _ok('divergencia_real', 'unitario', d, f'conflitos={list(conflitos)}')


def _caso_necessidade_diretor_tem_motivo_concreto():
    d = 'precisa_diretor=True sempre vem com motivos_diretor não vazio e com texto (nunca genérico sem motivo).'
    parecer = _parecer_base(agente='marie', necessidade_diretor=True,
                             motivo_diretor='Claim de shelf-life exige validação técnica antes de publicar.')
    corpo = _consolidar(_AVALIADO_TESTE, [parecer], [])
    motivos = (corpo['dados_apresentados']['sintese_estruturada'] or {}).get('motivos_diretor') or []
    if not corpo['precisa_diretor'] or not motivos or not motivos[0].get('motivo'):
        return _falhou('necessidade_diretor_motivo', 'unitario', d, f'precisa_diretor={corpo["precisa_diretor"]}, motivos={motivos}')
    return _ok('necessidade_diretor_motivo', 'unitario', d, motivos[0]['motivo'])


def _caso_guardrail_so_dicio_pode_vetar():
    d = 'Guardrail programático: veto=True de agente que não é dicio é revertido pelo executor, nunca só confiado ao prompt.'
    from unittest.mock import MagicMock
    import json
    resposta = MagicMock(status='completed', output_text=json.dumps(_parecer_base(veto=True, veto_motivo='tentativa indevida')))
    cliente = MagicMock()
    cliente.responses.create.return_value = resposta
    parecer = executor.executar_especialista('leonard', 'demanda', cliente=cliente)
    if parecer['veto'] is not False:
        return _falhou('guardrail_veto_so_dicio', 'unitario', d, f'veto={parecer["veto"]} para agente leonard')
    return _ok('guardrail_veto_so_dicio', 'unitario', d)


def _caso_falha_agente_nao_vira_concordancia():
    d = 'Um agente com falha entra em `erros`, nunca em `pareceres`, e força precisa_diretor=True.'
    corpo = _consolidar(_AVALIADO_TESTE, [_parecer_base(agente='iris')],
                         [{'agente': 'rua', 'erro': 'RespostaLLMInvalida', 'detalhe': 'resposta_llm_incompleta:max_output_tokens'}])
    if not corpo['precisa_diretor'] or corpo['pendencias'].get('agentes_com_falha') != ['rua']:
        return _falhou('falha_agente_nao_e_concordancia', 'unitario', d, f'{corpo["pendencias"]}')
    return _ok('falha_agente_nao_e_concordancia', 'unitario', d)


CASOS_UNITARIOS = (
    _caso_schema_campos_obrigatorios,
    _caso_proveniencia_numerica_sem_tag_e_sinalizada,
    _caso_proveniencia_numerica_tagueada_nao_e_sinalizada,
    _caso_fato_estimativa_fica_incerto,
    _caso_acao_ja_em_andamento_nao_duplica_recomendacao,
    _caso_divergencia_real_vs_dado_ausente,
    _caso_necessidade_diretor_tem_motivo_concreto,
    _caso_guardrail_so_dicio_pode_vetar,
    _caso_falha_agente_nao_vira_concordancia,
)


# ------------------------------------------------------------------ ao vivo

def _caso_agente_isolado(agente, cliente):
    d = f'{agente}: chamada real isolada devolve parecer válido (schema completo, sem exceção).'
    id_ = f'ao_vivo_{agente}_isolado'
    try:
        parecer = executor.executar_especialista(agente, f'Teste de regressão do Testing Center para {agente}.', cliente=cliente)
    except RespostaLLMInvalida as erro:
        return _falhou(id_, 'ao_vivo', d, f'RespostaLLMInvalida: {str(erro)[:200]}')
    except Exception as erro:
        return _falhou(id_, 'ao_vivo', d, f'{type(erro).__name__}: {str(erro)[:200]}')
    faltando = [c for c in executor._CAMPOS_OBRIGATORIOS_PARECER if c not in parecer]
    if faltando:
        return _falhou(id_, 'ao_vivo', d, f'campos ausentes no retorno: {faltando}')
    return _ok(id_, 'ao_vivo', d, f"confiança={parecer.get('confianca')}, tentativas={parecer.get('tentativas')}")


def _caso_execucao_conjunta(agentes, cliente):
    d = f'Execução conjunta {"+".join(agentes)}: cada agente isolado, falha de um não derruba os outros.'
    id_ = f'ao_vivo_conjunto_{"_".join(agentes)}'
    pareceres, erros = [], []
    for agente in agentes:
        try:
            pareceres.append(executor.executar_especialista(agente, 'Teste de regressão conjunta do Testing Center.', cliente=cliente))
        except Exception as erro:
            erros.append({'agente': agente, 'erro': type(erro).__name__})
    if not pareceres and erros:
        return _falhou(id_, 'ao_vivo', d, f'todos falharam: {erros}')
    corpo = _consolidar(_AVALIADO_TESTE, pareceres, erros)
    if erros and corpo['precisa_diretor'] is not True:
        return _falhou(id_, 'ao_vivo', d, 'falha parcial não forçou precisa_diretor=True')
    return _ok(id_, 'ao_vivo', d, f'{len(pareceres)} pareceres, {len(erros)} falhas')


def casos_ao_vivo(cliente=None):
    return (
        lambda: _caso_agente_isolado('rua', cliente),
        lambda: _caso_agente_isolado('iris', cliente),
        lambda: _caso_agente_isolado('marie', cliente),
        lambda: _caso_execucao_conjunta(['iris', 'marie', 'rua'], cliente),
    )


def executar_bateria(incluir_ao_vivo=True, cliente=None):
    """Roda os casos unitários (sempre) e, se `incluir_ao_vivo`, também os
    casos que chamam a OpenAI de verdade (custam tokens reais quando
    `cliente` é None em produção -- ver aviso na rota). Nunca levanta
    exceção para fora: um caso que quebra por bug do próprio teste vira
    'passou': False com o motivo, nunca derruba a bateria inteira."""
    resultados = []
    for caso in CASOS_UNITARIOS:
        try:
            resultados.append(caso())
        except Exception as erro:
            resultados.append(_falhou(caso.__name__, 'unitario', caso.__doc__ or caso.__name__,
                                       f'{type(erro).__name__}: {str(erro)[:200]}'))
    if incluir_ao_vivo:
        for caso in casos_ao_vivo(cliente=cliente):
            try:
                resultados.append(caso())
            except Exception as erro:
                resultados.append(_falhou('ao_vivo_erro_inesperado', 'ao_vivo', 'caso ao vivo', f'{type(erro).__name__}: {str(erro)[:200]}'))
    return resultados


def registrar_rotas_testes(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/conselho/testes/executar', methods=['POST'])
    def mi_conselho_testes_executar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        corpo = request.get_json(silent=True) or {}
        incluir_ao_vivo = bool(corpo.get('incluir_ao_vivo', False))  # opt-in: casos ao vivo custam tokens reais
        try:
            resultados = executar_bateria(incluir_ao_vivo=incluir_ao_vivo)
        except Exception:
            app.logger.exception('Falha ao executar bateria de testes do Conselho')
            return jsonify(success=False, error='Não foi possível executar a bateria de testes.'), 503
        total = len(resultados)
        aprovados = sum(1 for r in resultados if r['passou'])
        return jsonify(success=True, total=total, aprovados=aprovados, falharam=total - aprovados, resultados=resultados)
