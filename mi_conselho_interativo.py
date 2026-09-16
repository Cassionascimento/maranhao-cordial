"""Consulta interativa do Conselho de Agentes no Admin.

Extensão fina do Conselho existente: escolhe especialistas, aceita documento
como contexto, executa pareceres isolados via mi_conselho_executor e, somente
quando o Diretor clicar explicitamente, registra o resultado como item que
aguarda decisão. Nenhuma ação externa é executada por este módulo.
"""
import io
import json
import zipfile
from uuid import uuid4
from xml.etree import ElementTree

from pypdf import PdfReader

from mi_conselho import AGENTES, registrar_registro
from mi_conselho_executor import _categorizar_erro, _consolidar, executar_especialista_monitorado
from mi_conselho_orquestrador import classificar_especialistas, ordenar_execucao

MAX_DOCUMENTO_BYTES = 8 * 1024 * 1024
MAX_TEXTO_DOCUMENTO = 50000
MAX_DEMANDA = 12000
MODOS = {'automatico', 'especialistas', 'conclave'}


def _texto_docx(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
        xml = pacote.read('word/document.xml')
    raiz = ElementTree.fromstring(xml)
    textos = []
    for no in raiz.iter():
        if no.tag.endswith('}t') and no.text:
            textos.append(no.text)
        elif no.tag.endswith('}p'):
            textos.append('\n')
    return ''.join(textos)


def extrair_documento(arquivo):
    """Extrai texto sem persistir upload. PDF/DOCX e formatos textuais."""
    if not arquivo or not getattr(arquivo, 'filename', None):
        return None
    nome = arquivo.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    conteudo = arquivo.read(MAX_DOCUMENTO_BYTES + 1)
    if len(conteudo) > MAX_DOCUMENTO_BYTES:
        raise ValueError('documento_muito_grande')
    ext = ('.' + nome.rsplit('.', 1)[-1].lower()) if '.' in nome else ''
    if ext == '.pdf':
        leitor = PdfReader(io.BytesIO(conteudo))
        texto = '\n'.join((pagina.extract_text() or '') for pagina in leitor.pages)
    elif ext == '.docx':
        texto = _texto_docx(conteudo)
    elif ext in {'.txt', '.md', '.csv', '.json'}:
        texto = conteudo.decode('utf-8', errors='replace')
    else:
        raise ValueError('tipo_documento_nao_suportado')
    texto = texto.strip()
    if not texto:
        raise ValueError('documento_sem_texto_extraivel')
    truncado = len(texto) > MAX_TEXTO_DOCUMENTO
    return {'nome': nome, 'tipo': ext.lstrip('.'), 'texto': texto[:MAX_TEXTO_DOCUMENTO],
            'truncado': truncado, 'bytes': len(conteudo)}


def _lista_agentes(valor):
    if valor is None:
        return []
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError:
            valor = [p.strip() for p in valor.split(',') if p.strip()]
    if not isinstance(valor, list):
        raise ValueError('agentes_invalidos')
    saida = []
    for agente in valor:
        if agente not in AGENTES:
            raise ValueError('agente_desconhecido:' + str(agente))
        if agente not in saida:
            saida.append(agente)
    return saida


def _selecionar(modo, demanda, agentes, documento):
    if modo not in MODOS:
        raise ValueError('modo_invalido')
    if modo == 'conclave':
        return list(AGENTES.keys()), {'conclave_completo': True, 'motivos': {'todos': ['convocação explícita do Diretor']}}
    if modo == 'especialistas':
        escolhidos = _lista_agentes(agentes)
        if not escolhidos:
            raise ValueError('selecione_ao_menos_um_especialista')
        return escolhidos, {'conclave_completo': False, 'motivos': {a: ['selecionado pelo Diretor'] for a in escolhidos}}
    texto_classificacao = demanda
    if documento:
        texto_classificacao += '\n' + documento['texto'][:8000]
    try:
        classificacao = classificar_especialistas(texto_classificacao)
    except ValueError as erro:
        if str(erro) != 'nenhum_especialista_identificado':
            raise
        classificacao = {'selecionados': ['iris'], 'motivos': {'iris': ['demanda genérica/documento: começar por leitura factual']},
                         'excluidos': {}, 'conclave_completo': False}
    return classificacao['selecionados'], classificacao


def _snapshot_base(factory, documento=None):
    snapshot = {}
    try:
        from mi_diretor import leitura_diretor
        snapshot['empresa'] = leitura_diretor(factory)
    except Exception:
        snapshot['empresa'] = {'status': 'contexto_interno_indisponivel'}
    if documento:
        snapshot['documento_anexado'] = {'nome': documento['nome'], 'tipo': documento['tipo'],
                                         'texto': documento['texto'], 'truncado': documento['truncado']}
    return snapshot


def _avaliado_interativo(demanda):
    """Adapta a consulta interativa ao mesmo consolidador do fluxo automático."""
    return {'sinal_id': str(uuid4()), 'demanda': demanda, 'motivo': 'Análise interativa do Conselho.',
            'tipo_evento': 'consulta_interativa'}


def _corpo_estruturado(demanda, pareceres, erros):
    """Fonte única da síntese: reutiliza _consolidar e bloqueia como ação
    confirmada recomendações que contenham números sem proveniência."""
    seguros = []
    for parecer in pareceres:
        p = dict(parecer)
        if p.get('numeros_sem_evidencia'):
            p['acao_sugerida'] = ''
        seguros.append(p)
    return _consolidar(_avaliado_interativo(demanda), seguros, erros)


def _sintese(demanda, pareceres, erros):
    corpo = _corpo_estruturado(demanda, pareceres, erros)
    estruturada = (corpo.get('dados_apresentados') or {}).get('sintese_estruturada') or {}
    validos = [p for p in pareceres if p.get('conclusao')]
    vetos = [p for p in validos if p.get('veto')]
    return {
        'demanda': demanda,
        'resumo': estruturada.get('proxima_acao') or ('Nenhum parecer válido foi obtido.' if not validos else 'Pareceres disponíveis para revisão.'),
        'total_pareceres': len(validos), 'total_falhas': len(erros), 'ha_veto': bool(vetos),
        'vetos': [{'agente': p['agente'], 'motivo': p.get('veto_motivo')} for p in vetos],
        'precisa_diretor': bool(estruturada.get('precisa_diretor')),
        'recomendacao': estruturada.get('proxima_acao') or 'Revisar evidências e lacunas; nenhuma ação foi executada.',
        'sintese_estruturada': estruturada,
    }


def analisar(factory, demanda, modo='automatico', agentes=None, documento=None, cliente=None):
    demanda = (demanda or '').strip()
    if not demanda:
        raise ValueError('demanda_obrigatoria')
    if len(demanda) > MAX_DEMANDA:
        raise ValueError('demanda_muito_longa')
    selecionados, classificacao = _selecionar(modo, demanda, agentes, documento)
    snapshot = _snapshot_base(factory, documento)
    pareceres, erros = [], []
    for agente in ordenar_execucao(selecionados):
        try:
            contexto = dict(snapshot)
            if pareceres and agente != 'iris':
                iris = next((p for p in pareceres if p['agente'] == 'iris'), None)
                if iris:
                    contexto['base_factual_iris'] = {'dados_utilizados': iris.get('dados_utilizados'),
                                                     'conclusao': iris.get('conclusao'), 'riscos': iris.get('riscos')}
            pareceres.append(executar_especialista_monitorado(
                factory, agente, demanda, 'interativo', snapshot=contexto, cliente=cliente,
            ))
        except Exception as erro:
            # Categoria + detalhe seguro tornam a falha diagnosticável sem expor prompt/segredo.
            categoria, detalhe = _categorizar_erro(erro)
            erros.append({'agente': agente, 'erro': categoria, 'detalhe': detalhe})
    return {
        'demanda': demanda, 'modo': modo, 'selecionados': selecionados, 'classificacao': classificacao,
        'documento': None if not documento else {'nome': documento['nome'], 'tipo': documento['tipo'],
                                                  'truncado': documento['truncado'], 'bytes': documento['bytes']},
        'pareceres': pareceres, 'erros': erros, 'sintese': _sintese(demanda, pareceres, erros),
    }


def _validar_resultado_para_diretor(resultado):
    if not isinstance(resultado, dict):
        raise ValueError('resultado_invalido')
    demanda = (resultado.get('demanda') or '').strip()
    if not demanda or len(demanda) > MAX_DEMANDA:
        raise ValueError('demanda_invalida')
    pareceres = resultado.get('pareceres') or []
    if not isinstance(pareceres, list) or len(pareceres) > len(AGENTES):
        raise ValueError('pareceres_invalidos')
    limpos = []
    for p in pareceres:
        if not isinstance(p, dict) or p.get('agente') not in AGENTES:
            raise ValueError('parecer_invalido')
        numeros = []
        for n in (p.get('numeros') or []):
            if isinstance(n, dict):
                numeros.append({k: str(n.get(k) or '')[:1000] for k in ('valor','unidade','origem','fonte_detalhe','confianca')})
        limpos.append({
            'agente': p['agente'], 'conclusao': str(p.get('conclusao') or '')[:8000],
            'confianca': p.get('confianca') if p.get('confianca') in ('alta','media','baixa') else 'baixa',
            'dados_utilizados': str(p.get('dados_utilizados') or '')[:8000],
            'riscos': str(p.get('riscos') or '')[:6000], 'divergencias': str(p.get('divergencias') or '')[:6000],
            'acao_sugerida': str(p.get('acao_sugerida') or '')[:6000],
            'necessidade_diretor': bool(p.get('necessidade_diretor')),
            'motivo_diretor': str(p.get('motivo_diretor') or '')[:4000],
            'veto': bool(p.get('veto')) and p['agente'] == 'dicio', 'veto_motivo': str(p.get('veto_motivo') or '')[:6000],
            'numeros': numeros, 'numeros_sem_evidencia': [str(x)[:100] for x in (p.get('numeros_sem_evidencia') or [])],
            'lacunas': [str(x)[:2000] for x in (p.get('lacunas') or [])],
            'acao_ja_em_andamento': bool(p.get('acao_ja_em_andamento')),
            'natureza_divergencia': p.get('natureza_divergencia'),
        })
    return demanda, limpos


def enviar_para_diretor(factory, resultado):
    demanda, pareceres = _validar_resultado_para_diretor(resultado)
    modo = resultado.get('modo') if resultado.get('modo') in MODOS else 'automatico'
    erros = resultado.get('erros') if isinstance(resultado.get('erros'), list) else []
    corpo = _corpo_estruturado(demanda, pareceres, erros)
    corpo['chave'] = str(uuid4())
    corpo['tipo'] = 'conclave' if modo == 'conclave' else ('reuniao' if len(pareceres) > 1 else 'relatorio')
    corpo['contexto'] = 'Análise interativa enviada explicitamente pelo Admin ao Modo Diretor.'
    dados = corpo.setdefault('dados_apresentados', {})
    dados['documento'] = resultado.get('documento')
    dados['modo'] = modo
    corpo['precisa_diretor'] = True
    sintese = dados.get('sintese_estruturada') or {}
    sintese['precisa_diretor'] = True
    motivos = list(sintese.get('motivos_diretor') or [])
    motivos.append({'agente': None, 'motivo': 'envio explícito do Diretor pelo Admin'})
    sintese['motivos_diretor'] = motivos
    dados['sintese_estruturada'] = sintese
    retorno, status = registrar_registro(factory, corpo)
    return {'registro': retorno, 'status': status, 'precisa_diretor': True}


def registrar_rotas_conselho_interativo(app, factory, autorizado):
    from flask import jsonify, request

    @app.route('/api/admin/mi/conselho/analisar', methods=['POST'])
    def mi_conselho_analisar():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            documento = extrair_documento(request.files.get('documento'))
            resultado = analisar(factory, request.form.get('demanda'), request.form.get('modo', 'automatico'),
                                request.form.get('agentes'), documento)
            return jsonify(success=True, resultado=resultado)
        except ValueError as erro:
            mapa = {'demanda_obrigatoria': 'Digite uma pergunta ou demanda para o Conselho.',
                    'demanda_muito_longa': 'A pergunta está longa demais.',
                    'documento_muito_grande': 'O documento deve ter no máximo 8 MB.',
                    'tipo_documento_nao_suportado': 'Use PDF, DOCX, TXT, MD, CSV ou JSON.',
                    'documento_sem_texto_extraivel': 'Não foi possível extrair texto do documento.',
                    'selecione_ao_menos_um_especialista': 'Selecione ao menos um especialista.'}
            return jsonify(success=False, error=mapa.get(str(erro), 'Parâmetros inválidos.')), 400
        except Exception:
            app.logger.exception('Falha na análise interativa do Conselho')
            return jsonify(success=False, error='Não foi possível concluir a análise do Conselho.'), 503

    @app.route('/api/admin/mi/conselho/enviar-diretor', methods=['POST'])
    def mi_conselho_enviar_diretor():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            payload = request.get_json(silent=True) or {}
            retorno = enviar_para_diretor(factory, payload.get('resultado'))
            return jsonify(success=True, **retorno), retorno['status']
        except ValueError:
            return jsonify(success=False, error='Resultado da análise inválido.'), 400
        except Exception:
            app.logger.exception('Falha ao enviar análise do Conselho ao Diretor')
            return jsonify(success=False, error='Não foi possível enviar ao Modo Diretor.'), 503
