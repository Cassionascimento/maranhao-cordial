"""Admin territorial: fatos aditivos e interpretação restrita às evidências. Sem transportes."""
import hashlib
import json
import math
import os
from datetime import date
from uuid import UUID, uuid4
from flask import jsonify, request
from psycopg2.extras import Json, RealDictCursor
from inteligencia_territorial import carregar, DECISOES, REGIOES

CAMPOS = ('tipo_registro','contato_id','estabelecimento','tipo_relacao','bairro','cidade','uf','lote',
          'quantidade','unidade','finalidade','ocorrido_em','origem','responsavel','status','retorno','resultado','metricas')
METRICAS = ('contatos_realizados','respostas','interesses','conversoes','impressoes','cliques','custo_centavos','receita_centavos')
MOTIVOS = {'resposta':'taxa de resposta observada','perfis':'relações de perfis relevantes',
           'interesse':'interesse registrado','conversao':'conversões registradas',
           'estrutura':'fabricantes/distribuidores registrados','evento':'oportunidades de eventos registradas',
           'eficiencia':'custo por conversão observado','insuficiencia':'dados insuficientes'}


def validar_registro(body):
    if not isinstance(body,dict) or set(body)-set(CAMPOS)-{'chave'}:raise ValueError('campos_invalidos')
    chave=str(UUID(str(body.get('chave'))))
    d={k:body.get(k) for k in CAMPOS}
    for k in CAMPOS:
        if k in ('quantidade','metricas'):continue
        if d[k] is not None:
            if not isinstance(d[k],str) or len(d[k])>2000:raise ValueError('texto_invalido:'+k)
            d[k]=d[k].strip() or None
    if d['tipo_registro'] not in ('relacao','circulacao','midia','evento','resultado'):raise ValueError('tipo_invalido')
    if not d['origem'] or not d['responsavel']:raise ValueError('origem_e_responsavel_obrigatorios')
    if d['contato_id']:d['contato_id']=str(UUID(d['contato_id']))
    if d['uf']:
        d['uf']=d['uf'].upper()
        if d['uf'] not in REGIOES:raise ValueError('uf_invalida')
    if d['ocorrido_em']:d['ocorrido_em']=date.fromisoformat(d['ocorrido_em']).isoformat()
    q=d['quantidade']
    if q is not None and (isinstance(q,bool) or not isinstance(q,(int,float)) or not math.isfinite(q) or not 0<q<=100000000):raise ValueError('quantidade_invalida')
    if bool(q is not None)!=bool(d['unidade']):raise ValueError('quantidade_e_unidade_juntas')
    if d['unidade'] and d['unidade'] not in ('garrafas','amostras','litros','unidades'):raise ValueError('unidade_invalida')
    m=d['metricas'] if d['metricas'] is not None else {}
    if not isinstance(m,dict) or set(m)-set(METRICAS):raise ValueError('metricas_invalidas')
    if any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=10**12 for v in m.values()):raise ValueError('metricas_inteiras_nao_negativas')
    if 'respostas' in m and 'contatos_realizados' in m and m['respostas']>m['contatos_realizados']:raise ValueError('respostas_excedem_contatos')
    d['metricas']=m
    digest=hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return chave,d,digest


def registrar_fato(factory,body):
    chave,d,digest=validar_registro(body)
    conn=factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('INSERT INTO territorio_registros(id,chave,payload_hash,'+','.join(CAMPOS)+') VALUES('+','.join(['%s']*(len(CAMPOS)+3))+') ON CONFLICT(chave) DO NOTHING RETURNING id',
                    [str(uuid4()),chave,digest]+[Json(d[k]) if k=='metricas' else d[k] for k in CAMPOS])
                novo=cur.fetchone()
                cur.execute('SELECT id,payload_hash FROM territorio_registros WHERE chave=%s',(chave,))
                row=cur.fetchone()
                if row['payload_hash']!=digest:return {'success':False,'error':'chave_reutilizada_com_outro_conteudo'},409
                return {'success':True,'id':str(row['id']),'criado':bool(novo),'acao_externa':False},201 if novo else 200
    finally:conn.close()


def consultar_leitura(factory,digest):
    conn=factory()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT leitura FROM territorio_leituras WHERE dados_hash=%s',(digest,))
            row=cur.fetchone()
            return row[0] if row else None
    finally:conn.close()


def motivos_disponiveis(b):
    f=b['fatos'];m=b['metricas'];result=[]
    if f.get('respostas_com_abordagem',0) or b.get('respostas_pareadas',0):result.append('resposta')
    if any(b['tipos'].get(k,0) for k in ('bartender','bar','restaurante','hotel','distribuidor')):result.append('perfis')
    if f.get('interesses_confirmados',0) or f.get('classificacoes_interesse',0) or m.get('interesses',0):result.append('interesse')
    if f.get('relacoes_com_conversao',0) or m.get('conversoes',0):result.append('conversao')
    if b['tipos'].get('fabrica',0) or b['tipos'].get('distribuidor',0):result.append('estrutura')
    if f.get('relacoes_com_eventos',0) or f.get('eventos_registrados',0):result.append('evento')
    if b['indicadores']['custo_por_conversao_midia_centavos'] is not None:result.append('eficiencia')
    return result


def contexto_ia(report):
    """Somente agregados; nomes, e-mails, IDs de pessoas e mensagens não saem do sistema."""
    buckets={b['id']:b for b in report['niveis']['cidade']}
    return {key:[{'territorio_id':c['territorio_id'],'territorio':c['territorio'],
        'classificacao_maxima':c['classificacao'],'fatos':buckets[c['territorio_id']]['fatos'],
        'tipos':buckets[c['territorio_id']]['tipos'],'indicadores':buckets[c['territorio_id']]['indicadores'],
        'motivos_permitidos':motivos_disponiveis(buckets[c['territorio_id']])}
        for c in report['decisoes'][key]['candidatos']] for key in DECISOES}


def validar_interpretacao(report,result):
    if not isinstance(result,dict) or set(result)!=set(DECISOES):raise ValueError('interpretacao_invalida')
    context=contexto_ia(report);out={}
    for key in DECISOES:
        choice=result[key]
        if not isinstance(choice,dict) or set(choice)!={'territorio_id','motivos'}:raise ValueError('escolha_invalida')
        reasons=choice['motivos'];ident=choice['territorio_id']
        if not isinstance(reasons,list) or not reasons or any(not isinstance(r,str) for r in reasons):raise ValueError('motivos_invalidos')
        if ident is None:
            if reasons!=['insuficiencia']:raise ValueError('abstencao_invalida')
            chosen={'territorio_id':None,'territorio':None,'classificacao':'dados insuficientes',
                    'por_que':['A IA não indicou prioridade com as evidências disponíveis.'],'evidencias':[]}
        else:
            allowed=next((c for c in context[key] if c['territorio_id']==ident),None)
            if not allowed or set(reasons)-set(allowed['motivos_permitidos']):raise ValueError('evidencia_nao_suportada')
            chosen=next(dict(c) for c in report['decisoes'][key]['candidatos'] if c['territorio_id']==ident)
        out[key]=dict(chosen,motivos_ia=[MOTIVOS[r] for r in reasons],dados_faltantes=report['decisoes'][key]['dados_faltantes'],
                      natureza='recomendação da IA; fatos e confiança limitados às evidências cadastradas')
    return out


def chamar_ia(context):
    from openai import OpenAI
    model=os.getenv('OPENAI_MODEL_PROSPECCAO','gpt-5-mini')
    prompt=('Você assessora a direção da Maranhão Cordial. Analise quatro decisões territoriais. '
        'Não execute ações. Compare taxas/base de resposta e perfis; volume não é tamanho de mercado. '
        'Escolha somente um territorio_id fornecido por decisão, ou null se insuficiente. '
        'Retorne SOMENTE JSON com as quatro chaves midia,prospeccao,producao_distribuicao,eventos. '
        'Cada valor deve ter apenas territorio_id e motivos (lista de códigos motivos_permitidos desse candidato). '
        'Se null, motivos deve ser ["insuficiencia"]. Sem fatos novos, texto livre, ferramentas ou pesquisa. '
        'A ausência de custo/conversão impede recomendar investimento de mídia agora; abstenha-se nessa decisão. '
        'Produção exige demanda confirmada; eventos exigem oportunidade identificada. '
        'Dados agregados: '+json.dumps(context,ensure_ascii=False,default=str))
    client=OpenAI(timeout=35,max_retries=0)
    response=client.responses.create(model=model,input=prompt,max_output_tokens=3000)
    return json.loads(response.output_text),model


def interpretar(factory,report,gerar=chamar_ia):
    conn=factory()
    try:
        with conn:
            with conn.cursor() as cur:
                # Apenas uma interpretação paga simultânea; cache por snapshot.
                cur.execute('SELECT pg_try_advisory_xact_lock(730051)')
                if not cur.fetchone()[0]:return {'success':False,'error':'interpretacao_em_andamento'},409
                cur.execute('SELECT leitura FROM territorio_leituras WHERE dados_hash=%s',(report['dados_hash'],))
                row=cur.fetchone()
                if row:return {'success':True,'interpretacao_ia':row[0],'cache':True},200
                raw,model=gerar(contexto_ia(report))
                leitura={'dados_hash':report['dados_hash'],'decisoes':validar_interpretacao(report,raw),'modelo':model}
                cur.execute('INSERT INTO territorio_leituras(id,dados_hash,leitura,modelo) VALUES(%s,%s,%s,%s)',
                            (str(uuid4()),report['dados_hash'],Json(leitura),model))
                return {'success':True,'interpretacao_ia':leitura,'cache':False},200
    finally:conn.close()


def registrar_rotas(app,factory,autorizado):
    base='/api/admin/inteligencia-territorial'
    @app.route(base,methods=['GET'])
    def territorio_ler():
        if not autorizado():return jsonify(success=False,error='Não autorizado.'),401
        try:
            report=carregar(factory)
            report['interpretacao_ia']=consultar_leitura(factory,report['dados_hash'])
            return jsonify(report)
        except Exception:
            app.logger.exception('Falha na leitura territorial')
            return jsonify(success=False,error='Leitura territorial indisponível.'),503
    @app.route(base+'/registros',methods=['POST'])
    def territorio_registrar():
        if not autorizado():return jsonify(success=False,error='Não autorizado.'),401
        if request.content_length and request.content_length>20000:return jsonify(success=False,error='Registro muito grande.'),413
        try:
            body,status=registrar_fato(factory,request.get_json(silent=True))
            return jsonify(body),status
        except (ValueError,TypeError,AttributeError):return jsonify(success=False,error='Registro inválido. Confira origem, responsável, localização e métricas.'),400
        except Exception:
            app.logger.exception('Falha no registro territorial')
            return jsonify(success=False,error='Registro não confirmado. Reenvie o mesmo conteúdo para verificar.'),503
    @app.route(base+'/interpretar',methods=['POST'])
    def territorio_interpretar():
        if not autorizado():return jsonify(success=False,error='Não autorizado.'),401
        try:
            body,status=interpretar(factory,carregar(factory))
            return jsonify(body),status
        except Exception:
            app.logger.exception('Interpretação territorial indisponível')
            return jsonify(success=False,error='IA indisponível; fatos e sinais continuam acessíveis.'),503
