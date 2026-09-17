"""Secretário Executivo do Conselho (P5.X — Milestone 3).

Não substitui nenhum especialista, não decide nada, não escreve na fila
de decisão. Sua única função é transformar uma deliberação já persistida
(mi_conselho.registrar_registro, com os pareceres_compactos/
sintese_estruturada/classificacao_especialistas do Milestone 2) numa ata
executiva pronta para virar apresentação (M4).

Disciplina de custo (M12 antecipado aqui porque é o motivo de existir
desta etapa): a única chamada de LLM desta etapa é UMA síntese narrativa
curta, feita a partir dos dados JÁ COMPACTOS -- nunca reenvia os
pareceres verbosos inteiros, nunca chama o modelo uma vez por
especialista. Decisões e próximos passos são derivados
DETERMINISTICAMENTE do que o Conselho já calculou (recomendações,
próxima ação, motivos de escalada ao Diretor) -- o LLM nunca inventa uma
decisão que os especialistas não tomaram.
"""
import json

from openai import OpenAI

from mi_conselho import buscar_registro
from mi_conselho_executor import MODELO_PADRAO

TIMEOUT_SEGUNDOS_SECRETARIO = 20
MAX_OUTPUT_TOKENS_SECRETARIO = 500

_SCHEMA_NARRATIVA = {
    'type': 'object',
    'properties': {
        'titulo': {'type': 'string'},
        'narrativa': {'type': 'string'},
    },
    'required': ['titulo', 'narrativa'],
    'additionalProperties': False,
}


def _visuais_sugeridos(pareceres_compactos):
    """Agrega os requested_visual já validados por agente (M2) -- nunca
    decide um visual novo, só deduplica o que os especialistas pediram."""
    vistos = set()
    sugeridos = []
    for parecer in (pareceres_compactos or []):
        visual = parecer.get('requested_visual')
        if not visual:
            continue
        chave = (visual.get('artifact_type'), visual.get('descricao'))
        if chave in vistos:
            continue
        vistos.add(chave)
        sugeridos.append({**visual, 'solicitado_por': parecer.get('agente')})
    return sugeridos


def _decisoes_e_proximos_passos(registro):
    """Deriva decisões/próximos passos só do que o Conselho já calculou
    (recomendacoes/sintese_estruturada) -- nenhum texto novo é inventado
    aqui, só reformatado."""
    dados = registro.get('dados_apresentados') or {}
    estruturada = dados.get('sintese_estruturada') or {}
    decisoes = [
        f"{r['responsavel']}: {r['descricao']}" for r in (registro.get('recomendacoes') or [])
        if r.get('responsavel') and r.get('descricao')
    ]
    proximos_passos = []
    if estruturada.get('proxima_acao'):
        proximos_passos.append(estruturada['proxima_acao'])
    for motivo in (estruturada.get('motivos_diretor') or []):
        texto = motivo.get('motivo') if isinstance(motivo, dict) else str(motivo)
        if texto:
            proximos_passos.append(f'Encaminhar ao Diretor: {texto}')
    return decisoes, proximos_passos


def _narrativa_deterministica(registro):
    """Fallback sem LLM -- usado quando a síntese falha (rede/modelo) ou
    quando nenhum `cliente` é fornecido em contexto de teste. Nunca
    bloqueia a ata por indisponibilidade externa, e nunca fabrica um fato
    que o registro não tenha."""
    return {
        'titulo': f"Conselho — {(registro.get('demanda') or '')[:80]}",
        'narrativa': registro.get('conclusao') or 'Sem conclusão consolidada disponível para esta demanda.',
    }


def gerar_narrativa(registro, cliente=None):
    """Única chamada de LLM do Secretário -- reaproveita o mesmo cliente/
    modelo já em uso em mi_conselho_executor.py, mas com um prompt muito
    menor (só pareceres_compactos + sintese_estruturada, nunca os
    pareceres verbosos inteiros). Falha de rede/modelo cai no fallback
    determinístico -- nunca propaga exceção, nunca trava a ata."""
    dados = registro.get('dados_apresentados') or {}
    contexto = {
        'demanda': registro.get('demanda'),
        'participantes': registro.get('participantes'),
        'pareceres_compactos': dados.get('pareceres_compactos'),
        'sintese_estruturada': dados.get('sintese_estruturada'),
    }
    prompt = (
        'Você é o Secretário Executivo do Conselho da Maranhão Cordial. Escreva um '
        'título curto (até 10 palavras) e uma narrativa executiva (2 a 4 frases, tom '
        'direto de reunião de diretoria) A PARTIR SOMENTE dos dados JSON abaixo -- '
        'nunca invente fato, número ou decisão que não esteja neles.\n\n'
        + json.dumps(contexto, ensure_ascii=False, default=str)
    )
    try:
        cliente = cliente or OpenAI(timeout=TIMEOUT_SEGUNDOS_SECRETARIO, max_retries=0)
        resposta = cliente.responses.create(
            model=MODELO_PADRAO,
            input=prompt,
            max_output_tokens=MAX_OUTPUT_TOKENS_SECRETARIO,
            store=False,
            reasoning={'effort': 'low'},
            text={'format': {'type': 'json_schema', 'name': 'narrativa_secretario', 'strict': True,
                              'schema': _SCHEMA_NARRATIVA}},
        )
        corpo = json.loads(resposta.output_text or '')
        if not isinstance(corpo, dict) or not (corpo.get('narrativa') or '').strip():
            raise ValueError('narrativa_invalida')
        return {
            'titulo': (corpo.get('titulo') or '').strip() or _narrativa_deterministica(registro)['titulo'],
            'narrativa': corpo['narrativa'].strip(),
        }
    except Exception:
        return _narrativa_deterministica(registro)


def montar_ata_executiva(registro, cliente=None):
    """Ponto único do Secretário Executivo. Recebe um registro JÁ
    PERSISTIDO (mesma forma que mi_conselho.registrar_registro grava) e
    devolve a ata compacta que o Presentation Engine (M4) consome para
    montar o deck -- nunca decide, nunca aprova, nunca substitui
    especialista."""
    dados = registro.get('dados_apresentados') or {}
    resultado_narrativa = gerar_narrativa(registro, cliente=cliente)
    decisoes, proximos_passos = _decisoes_e_proximos_passos(registro)
    return {
        'meeting_id': registro.get('id') or registro.get('chave'),
        'titulo': resultado_narrativa['titulo'],
        'narrativa': resultado_narrativa['narrativa'],
        'participantes': registro.get('participantes') or [],
        'decisoes': decisoes,
        'proximos_passos': proximos_passos,
        'visuais_sugeridos': _visuais_sugeridos(dados.get('pareceres_compactos')),
        'precisa_diretor': bool(registro.get('precisa_diretor')),
    }


def registrar_rotas_leitura(app, factory, autorizado):
    from flask import jsonify
    from psycopg2.extras import RealDictCursor

    @app.route('/api/admin/mi/conselho/<registro_id>/ata', methods=['GET'])
    def mi_secretario_ata(registro_id):
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout='10s'")
                registro = buscar_registro(cur, registro_id)
        except Exception:
            app.logger.exception('Falha ao buscar registro do Conselho para montar a ata')
            return jsonify(success=False, error='Ata indisponível.'), 503
        finally:
            conn.close()
        if not registro:
            return jsonify(success=False, error='Reunião/registro não encontrado.'), 404
        try:
            ata = montar_ata_executiva(registro)
        except Exception:
            app.logger.exception('Falha ao montar ata executiva')
            return jsonify(success=False, error='Não foi possível montar a ata.'), 503
        return jsonify(success=True, **ata)
