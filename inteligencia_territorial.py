"""Leitura territorial de dados existentes. Sem rede, IA, escrita ou efeitos no import."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parseaddr
import hashlib
import json
import math
import re
import unicodedata
from psycopg2.extras import RealDictCursor

FONTES = ('leads_crm','profissionais_rede','cadastros_profissionais','fabricas_parceiras',
          'contatos_estrategicos','relacionamentos_b2b','prospectos_fase57',
          'prospectos_fabrica_fase56','prospectos_rede','solicitacoes_degustacao')
REGIOES = {uf:regiao for regiao,ufs in (
    ('Norte','AC AP AM PA RO RR TO'),('Nordeste','AL BA CE MA PB PE PI RN SE'),
    ('Centro-Oeste','DF GO MT MS'),('Sudeste','ES MG RJ SP'),('Sul','PR RS SC')) for uf in ufs.split()}
ESTADOS = dict(zip(('acre','alagoas','amapa','amazonas','bahia','ceara','distrito federal','espirito santo',
    'goias','maranhao','mato grosso','mato grosso do sul','minas gerais','para','paraiba','parana',
    'pernambuco','piaui','rio de janeiro','rio grande do norte','rio grande do sul','rondonia','roraima',
    'santa catarina','sao paulo','sergipe','tocantins'),
    'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split()))
DECISOES = ('midia','prospeccao','producao_distribuicao','eventos')


def texto(value):
    return str(value).strip() if value is not None else ''


def normal(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',texto(value).lower()) if not unicodedata.combining(c)).split())


def uf_valida(value):
    value=texto(value)
    return value.upper() if value.upper() in REGIOES else ESTADOS.get(normal(value))


def localizacao(row):
    cidade=texto(row.get('cidade')) or None
    uf=uf_valida(row.get('uf') or row.get('estado'))
    bairro=texto(row.get('bairro')) or None
    # Apenas separa UF literalmente escrita, nunca geocodifica nome/endereço/IP.
    match=re.fullmatch(r'(.+?)\s*(?:/| - )\s*([A-Za-z]{2})',cidade or '')
    if match and uf_valida(match[2]):
        explicita=uf_valida(match[2])
        if uf and uf!=explicita:return {'bairro':None,'cidade':None,'uf':None,'conflito':True}
        cidade,uf=match[1].strip(),explicita
    elif uf_valida(cidade) and len(cidade or '')==2:
        if uf and uf!=uf_valida(cidade):return {'bairro':None,'cidade':None,'uf':None,'conflito':True}
        uf,cidade=uf_valida(cidade),None
    if normal(cidade) in ('desconhecido','nao informado','nao informada','brasil','n/a'):cidade=None
    return {'bairro':bairro,'cidade':cidade,'uf':uf,'conflito':False}


def email(row):
    for campo in ('email','contato_email','email_publico','contato'):
        value=parseaddr(texto(row.get(campo)))[1].lower()
        if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):return value
    return None


def excluido(row):
    origem=normal(row.get('origem') or row.get('origem_cadastro') or row.get('origem_contato'))
    dominio=(email(row) or '').split('@')[-1]
    return (row.get('arquivado') is True or row.get('cadastro_teste') is True or row.get('contato_interno') is True
        or normal(row.get('status')) in ('teste','invalido','descartado','rejeitado')
        or origem.startswith(('teste','homologacao','sintetico'))
        or dominio in ('example.com','example.org','example.invalid') or dominio.endswith(('.invalid','.test')))


def carregar(factory):
    """Snapshot consistente, somente leitura; limite declarado, nunca truncamento silencioso."""
    conn=factory();data={};limitadas=[]
    try:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")
            for fonte in (*FONTES,'interacoes_omnichannel','pedidos','territorio_registros'):
                cur.execute('SELECT * FROM '+fonte+' ORDER BY id LIMIT 5001')
                rows=[dict(row) for row in cur.fetchall()]
                if len(rows)>5000:limitadas.append(fonte)
                data[fonte]=rows[:5000]
            cur.execute("SELECT id,payload_json,criado_em FROM eventos_empresariais WHERE fonte='google_analytics' AND tipo='snapshot_ga4' ORDER BY id DESC LIMIT 1")
            data['snapshot_ga4']=[dict(row) for row in cur.fetchall()]
            from mi_eventos import consumo_territorial
            mi_rows=consumo_territorial(cur)
            if len(mi_rows)>5000:limitadas.append('mi_eventos')
            data['mi_eventos']=mi_rows[:5000]
        return agregar(data,limitadas)
    finally:conn.close()


def consolidar(data):
    rows=[];parent={};identity={};excluidos=0
    def root(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    for fonte in (*FONTES, 'territorio_registros'):
        for raw in data.get(fonte,[]):
            if fonte == 'territorio_registros' and raw.get('tipo_registro') != 'relacao':continue
            if excluido(raw):excluidos+=1;continue
            row=dict(raw,_fonte=fonte);key=fonte+':'+str(row['id']);parent[key]=key
            keys=[key]
            for campo in ('lead_id','contato_central_id','contato_id'):
                if row.get(campo):keys.append('leads_crm:'+str(row[campo]))
            mail=email(row)
            if mail:keys.append('email:'+mail)
            # Somente identidade documental exata, nunca aproximação por nome.
            cnpj=re.sub(r'\D','',texto(row.get('cnpj')))
            if len(cnpj)==14:keys.append('cnpj:'+cnpj)
            for token in keys:
                if token in identity:parent[root(key)]=root(identity[token])
                else:identity[token]=key
            rows.append((key,row))
    groups=defaultdict(list)
    for key,row in rows:groups[root(key)].append(row)
    entities=[];lookup={}
    for key,rs in groups.items():
        locs=[]
        for row in rs:
            loc=localizacao(row)
            if row['_fonte']=='prospectos_fabrica_fase56':
                # SP era default de schema, não comprova UF desta fábrica.
                loc['uf']=None
            locs.append(loc)
        ufs={loc['uf'] for loc in locs if loc['uf']}
        cidades={normal(loc['cidade']):loc['cidade'] for loc in locs if loc['cidade']}
        bairros={normal(loc['bairro']):loc['bairro'] for loc in locs if loc['bairro']}
        conflict=len(ufs)>1 or len(cidades)>1 or any(loc['conflito'] for loc in locs)
        loc={'uf':next(iter(ufs)) if len(ufs)==1 else None,
             'cidade':next(iter(cidades.values())) if len(cidades)==1 and len(ufs)<=1 else None,
             'bairro':next(iter(bairros.values())) if len(bairros)==1 and not conflict else None,'conflito':conflict}
        tipos=set()
        for row in rs:
            labels=' '.join(normal(row.get(k)) for k in ('tipo_relacao','tipo_lead','tipo','cargo','cargo_funcao','estabelecimento_tipo','segmento','categoria_sugerida'))
            for kind,words in {'bartender':('bartender','mixologista'),'bar':('bar','bares'),'restaurante':('restaurante',),
                               'hotel':('hotel','hoteis','pousada'),'fabrica':('fabrica','fabricante','industria'),'distribuidor':('distribuidor',)}.items():
                if any(re.search(r'\b'+word+r'\b',labels) for word in words):tipos.add(kind)
            if row['_fonte'] in ('fabricas_parceiras','prospectos_fabrica_fase56'):tipos.add('fabrica')
        e={'id':key,'local':loc,'rows':rs,'tipos':tipos,'interacoes':0,'entradas':[], 'saidas':[],
           'contatado':any(r.get('ultimo_contato_em') or r.get('ultimo_contato') or r.get('primeiro_contato') for r in rs),
           'respondeu':any(r.get('respondeu') is True or r.get('ultima_resposta_em') for r in rs),
           'interesse':any(r.get('interessado') is True or r.get('interesse_demonstrado') is True for r in rs),
           'sinal_interesse':False,
           'conversao':any(r.get('compra_confirmada') is True or (r.get('quantidade_compras') or 0)>0 for r in rs),
           'amostra':any(r.get('recebeu_amostra') is True or r.get('amostra_enviada') is True for r in rs),
           'evento':any(r.get('evento_relacionado') or r.get('eventos') for r in rs),
           'potencial_evento':any(r.get('potencial_eventos') is True for r in rs),
           'digital':any(any(r.get(k) for k in ('instagram','instagram_publico','linkedin','linkedin_publico','site','site_publico')) for r in rs),
           'verificado':any(r.get('validado_em') or r.get('verificado_em') for r in rs)}
        entities.append(e)
        for row in rs:
            lookup[row['_fonte']+':'+str(row['id'])]=e
            if email(row):lookup['email:'+email(row)]=e
    return entities,lookup,excluidos


def wilson(respostas,contatos):
    if not contatos:return 0
    z=1.96;p=respostas/contatos
    return (p+z*z/(2*contatos)-z*math.sqrt((p*(1-p)+z*z/(4*contatos))/contatos))/(1+z*z/contatos)


def agrupo(loc,nivel):
    if nivel=='bairro':values=(loc['uf'],normal(loc['cidade']) or None,normal(loc['bairro']) or None)
    elif nivel=='cidade':values=(loc['uf'],normal(loc['cidade']) or None)
    elif nivel=='uf':values=(loc['uf'],)
    else:values=(REGIOES.get(loc['uf']),)
    label=((' / '.join(filter(None,(loc['bairro'],loc['cidade'],loc['uf'])))) if nivel=='bairro'
        else (' / '.join(filter(None,(loc['cidade'],loc['uf']))) if nivel=='cidade'
        else loc['uf'] if nivel=='uf' else REGIOES.get(loc['uf'])))
    known=bool(loc['bairro'] and loc['cidade'] and loc['uf']) if nivel=='bairro' else bool(loc['cidade'] and loc['uf']) if nivel=='cidade' else bool(values[0])
    if not known:label=(label+' — localização incompleta') if label else 'Localização desconhecida'
    ident=hashlib.sha256(json.dumps([nivel,values]).encode()).hexdigest()[:20]
    return ident,label,known


def agregar(data,limitadas=()):
    entities,lookup,excluded=consolidar(data)
    without_links=0
    for row in data.get('interacoes_omnichannel',[]):
        if row.get('arquivado'):continue
        e=lookup.get('leads_crm:'+str(row.get('lead_id')))
        outbound='saida' in texto(row.get('tipo_interacao')) or parseaddr(texto(row.get('sender_id')))[1].lower()=='contato@maranhaocordial.com.br'
        if not e:
            address=parseaddr(texto(row.get('recipient_id') if outbound else row.get('sender_id')))[1].lower()
            e=lookup.get('email:'+address)
        if not e:without_links+=1;continue
        e['interacoes']+=1
        when=texto(row.get('criado_em'))
        if outbound:e['saidas'].append(when)
        elif row.get('tipo_interacao')!='email_tecnico' and row.get('classificacao') not in ('comunicacao_automatica','financeiro','fiscal_contabil','seguranca_rotina'):
            e['entradas'].append(when)
            if row.get('classificacao') in ('interesse_comercial','interesse_comercial_b2b'):e['sinal_interesse']=True
    for e in entities:
        if e['saidas']:e['contatado']=True
        if e['saidas'] and any(t>=min(e['saidas']) for t in e['entradas'] if t):e['respondeu']=True
    for row in data.get('pedidos',[]):
        if row.get('status')!='pago':continue
        e=lookup.get('email:'+texto(row.get('cliente_email')).lower())
        if e:e['conversao']=True
        # Pagamento NÃO é circulação física; endereço livre não é geocodificado.
    niveis={};details={};records=[r for r in data.get('territorio_registros',[]) if not excluido(r)]
    excluded+=sum(excluido(r) and r.get('tipo_registro')!='relacao' for r in data.get('territorio_registros',[]))
    for nivel in ('bairro','cidade','uf','regiao'):
        buckets={}
        def bucket(loc):
            ident,label,known=agrupo(loc,nivel)
            if ident not in buckets:
                buckets[ident]={'id':ident,'territorio':label,'localizacao_completa':known,'fatos':Counter(),
                    'tipos':Counter(),'evidencias':[],'circulacao':Counter(),'metricas':Counter(),'fatos_mi':Counter(),
                    'metricas_presentes':set(),'midia_custo_pareado':0,'midia_conversoes_pareadas':0,'contatos_pareados':0,'respostas_pareadas':0}
            return buckets[ident]
        for e in entities:
            b=bucket(e['local']);f=b['fatos'];f['relacoes']+=1;f['interacoes']+=e['interacoes'];f['entradas_relevantes']+=len(e['entradas'])
            for flag,key in [('contatado','contatados'),('interesse','interesses_confirmados'),('sinal_interesse','classificacoes_interesse'),
                             ('conversao','relacoes_com_conversao'),('amostra','relacoes_com_amostra_registrada'),('evento','relacoes_com_eventos'),
                             ('digital','presencas_digitais'),('verificado','relacoes_verificadas'),('potencial_evento','sinais_potencial_eventos')]:
                f[key]+=int(bool(e[flag]))
            f['respostas_registradas']+=int(bool(e['respondeu']))
            f['respostas_com_abordagem']+=int(bool(e['respondeu'] and e['contatado']))
            f['conflitos_localizacao']+=int(e['local']['conflito']);b['tipos'].update(e['tipos'])
            for row in e['rows']:
                b['evidencias'].append({'fonte':row['_fonte'],'id':str(row['id']),
                    'nome':row.get('nome') or row.get('empresa') or row.get('estabelecimento_nome') or row.get('estabelecimento') or row.get('responsavel') or 'Registro sem nome',
                    'localizacao_registrada':{k:row.get(k) for k in ('bairro','cidade','estado','uf') if row.get(k)},
                    'verificada':bool(row.get('validado_em') or row.get('verificado_em'))})
        for record in records:
            loc=localizacao(record)
            # Só herda localização por FK explícita quando não há local informado.
            if not any(loc[k] for k in ('bairro','cidade','uf')) and record.get('contato_id'):
                linked=lookup.get('leads_crm:'+str(record['contato_id']))
                if linked:loc=linked['local']
            b=bucket(loc);b['fatos']['registros_operacionais']+=1
            b['evidencias'].append({'fonte':'territorio_registros','id':str(record['id']),
                'nome':record.get('estabelecimento') or record.get('finalidade') or record['tipo_registro'],
                'data':texto(record.get('ocorrido_em')) or None,'status':record.get('status')})
            done=normal(record.get('status')) in ('realizada','realizado','enviada','enviado','entregue','concluida','concluido')
            if record['tipo_registro']=='circulacao' and done:
                b['fatos']['circulacoes_registradas']+=1
                if record.get('quantidade') is not None and record.get('unidade'):
                    b['circulacao'][record['unidade']]+=float(record['quantidade'])
                else:b['fatos']['circulacoes_sem_quantidade']+=1
            if record['tipo_registro']=='evento':b['fatos']['eventos_registrados']+=1
            # Planejamento não entra em desempenho/custo observado.
            if done:
                m=record.get('metricas') or {}
                for key,value in m.items():
                    if isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0:
                        b['metricas'][key]+=value;b['metricas_presentes'].add(key)
                if m.get('contatos_realizados') is not None and m.get('respostas') is not None:
                    b['contatos_pareados']+=m['contatos_realizados'];b['respostas_pareadas']+=m['respostas']
                if record['tipo_registro']=='midia' and m.get('custo_centavos') is not None and m.get('conversoes',0)>0:
                    b['midia_custo_pareado']+=m['custo_centavos'];b['midia_conversoes_pareadas']+=m['conversoes']
        for evento in data.get('mi_eventos',[]):
            # Fato isolado do Maranhão Intelligence: nenhum contador antigo (fatos/metricas/
            # circulacao) tem equivalência semântica com scan/ativacao/presenca/venda/feedback.
            bucket(localizacao(evento))['fatos_mi'][evento['tipo_evento']]+=1
        total=sum(b['fatos']['relacoes'] for b in buckets.values() if b['localizacao_completa'])
        for b in buckets.values():
            f=b['fatos'];n=f['contatados'];r=f['respostas_com_abordagem']
            b['indicadores']={'taxa_resposta':round(r/n,4) if n else None,
                'base_taxa_resposta':n,
                'taxa_resposta_registros':round(b['respostas_pareadas']/b['contatos_pareados'],4) if b['contatos_pareados'] else None,
                'base_taxa_registros':b['contatos_pareados'],'densidade_relativa_base_localizada':round(f['relacoes']/total,4) if total and b['localizacao_completa'] else None,
                'custo_por_conversao_midia_centavos':round(b['midia_custo_pareado']/b['midia_conversoes_pareadas'],2) if b['midia_conversoes_pareadas'] else None}
            b['sinais']=[]
            if n:b['sinais'].append(f'{r}/{n} relações abordadas têm resposta registrada; isso não mede entrega de e-mail.')
            if b['tipos']:b['sinais'].append('Concentração na base cadastrada, não densidade populacional ou tamanho do mercado.')
            if f['classificacoes_interesse']:b['sinais'].append('Classificações de interesse pela IA são sinais, não compra confirmada.')
            if f['relacoes_com_amostra_registrada']:b['sinais'].append('Amostra registrada por relação; quantidade/lote não disponíveis nesse indicador.')
            if f['sinais_potencial_eventos']:b['sinais'].append('Potencial para eventos foi sinalizado no cadastro; isso não comprova evento identificado ou participação.')
            if f['presencas_digitais']:b['sinais'].append('Perfil/site cadastrado não comprova audiência, alcance ou engajamento territorial.')
            b['score_resposta']=max(wilson(r,n),wilson(b['respostas_pareadas'],b['contatos_pareados']))
            b['metricas']={k:b['metricas'][k] for k in b.pop('metricas_presentes')}
            details[b['id']]=b['evidencias']
        niveis[nivel]=sorted(buckets.values(),key=lambda b:(not b['localizacao_completa'],-b['score_resposta'],-b['fatos']['relacoes'],b['territorio']))
    report={'success':True,'periodo':'histórico registrado; datas ausentes permanecem desconhecidas',
            'niveis':niveis,'cobertura':{'relacoes_unicas':len(entities),'registros_excluidos':excluded,
                'relacoes_sem_cidade_uf':sum(not(e['local']['cidade'] and e['local']['uf']) for e in entities),
                'interacoes_sem_vinculo':without_links,'fontes_limitadas':list(limitadas)},
            'governanca':'Somente análise e registro de fatos. Nenhuma ação externa ou movimentação de estoque.',
            'limites':['Ranking usa limite inferior de Wilson da resposta, volumes limitados e custo/conversão pareado quando disponível; não autoriza investimento.',
                'Localizações são declaradas nas fontes; validação aparece nas evidências.',
                'UF escrita junto à cidade é separada literalmente; região é agrupamento administrativo da UF.',
                'Taxa de resposta usa relações abordadas; entradas espontâneas ficam fora do numerador.',
                'Custos de aquisição do CRM não são tratados como investimento em mídia.',
                'Não há geocodificação por endereço, nome, telefone ou IP. Dados conflitantes não são resolvidos por suposição.']}
    report['presenca_digital']={'snapshot_existente':None,'territorializacao':'desconhecida; snapshot global não é atribuído a cidades'}
    if data.get('snapshot_ga4'):
        raw=data['snapshot_ga4'][0]
        try:
            values=json.loads(raw.get('payload_json') or '{}')
            allowed={k:float(values[k]) for k in ('usuarios_ativos','sessoes','visualizacoes','taxa_engajamento')
                     if k in values and math.isfinite(float(values[k])) and float(values[k])>=0}
            report['presenca_digital']['snapshot_existente']={'fonte':'eventos_empresariais','id':str(raw['id']),
                'data':texto(raw.get('criado_em')),'janela':'7 dias do snapshot','metricas_globais':allowed}
        except (ValueError,TypeError,KeyError,AttributeError):
            report['presenca_digital']['erro']='snapshot existente sem métricas válidas'
    report['decisoes']=recomendar(niveis['cidade'],bool(limitadas))
    report['dados_hash']=hashlib.sha256(json.dumps(report,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    return report


def recomendar(territorios,incompleto=False):
    result={}
    faltas={'midia':['investimento em mídia por território/período','conversões atribuídas ao mesmo investimento','respostas e interesse com localização'],
            'prospeccao':['localização dos contatos CRM','perfil/estabelecimento validado','respostas por relação abordada'],
            'producao_distribuicao':['demanda e volume confirmados por território','capacidade/custo/cobertura verificados de fabricantes e distribuidores','circulação com lote e quantidade'],
            'eventos':['oportunidades de eventos identificadas','custo/participação previstos e resultados anteriores','demanda e respostas locais']}
    for decisao in DECISOES:
        candidates=[]
        for b in territorios:
            if not b['localizacao_completa']:continue
            f=b['fatos'];types=b['tipos'];response=b['score_resposta'];interest=f['interesses_confirmados']+f['classificacoes_interesse']+b['metricas'].get('interesses',0)
            alvo=sum(types[t] for t in ('bartender','bar','restaurante','hotel','distribuidor'))
            estrutura=types['fabrica']+types['distribuidor'];demand=interest+f['respostas_com_abordagem']+f['relacoes_com_conversao']+f['relacoes_com_amostra_registrada']+b['metricas'].get('conversoes',0)
            eligible={'midia':bool(interest or f['relacoes_com_conversao'] or b['metricas'].get('conversoes',0) or f['respostas_com_abordagem']>=3 or b['respostas_pareadas']>=3),
                      'prospeccao':bool(alvo), 'producao_distribuicao':bool(estrutura and demand),
                      'eventos':bool(f['eventos_registrados'] or f['relacoes_com_eventos'] or (alvo and demand>=3))}[decisao]
            if not eligible:continue
            score=response*100+min(interest,10)*2+min(f['relacoes_com_conversao'],5)*4+min(alvo if decisao=='prospeccao' else estrutura if decisao=='producao_distribuicao' else f['relacoes_com_eventos'] if decisao=='eventos' else 0,10)
            custo=b['indicadores']['custo_por_conversao_midia_centavos']
            if decisao=='midia' and custo is not None:score+=10/(1+custo/1000)
            why=[f"{f['relacoes']} relações únicas registradas; {f['respostas_com_abordagem']}/{f['contatados']} com resposta após abordagem."]
            if b['contatos_pareados']:why.append(f"Registros operacionais: {b['respostas_pareadas']}/{b['contatos_pareados']} respostas/contatos no mesmo registro.")
            if custo is not None:why.append(f'Custo por conversão de mídia em registros pareados: R$ {custo/100:.2f}; não é previsão.')
            if alvo:why.append(f'{alvo} classificações registradas em perfis-alvo (uma relação pode ter mais de um tipo).')
            if estrutura:why.append(f'{estrutura} classificações de fábrica/distribuidor mapeadas; capacidade não presumida.')
            if interest:why.append(f"{f['interesses_confirmados']} interesses confirmados e {f['classificacoes_interesse']} relações com classificação de interesse pela IA.")
            sufficient=(not incompleto and f['contatados']>=20 and f['respostas_com_abordagem']>=5 and f['relacoes_verificadas']>=10)
            if decisao=='midia':sufficient=sufficient and b['indicadores']['custo_por_conversao_midia_centavos'] is not None
            if decisao in ('producao_distribuicao','eventos'):sufficient=False # V1 sem validação de viabilidade/custos desses projetos.
            candidates.append({'territorio_id':b['id'],'territorio':b['territorio'],'score':round(score,3),
                'classificacao':'evidência suficiente' if sufficient else 'sinal inicial','por_que':why,
                'evidencias':[{'fonte':e['fonte'],'id':e['id']} for e in b['evidencias'][:30]]})
        candidates.sort(key=lambda c:(-c['score'],c['territorio']))
        result[decisao]={'classificacao':candidates[0]['classificacao'] if candidates else 'dados insuficientes',
            'territorio':candidates[0]['territorio'] if candidates else None,'territorio_id':candidates[0]['territorio_id'] if candidates else None,
            'por_que':candidates[0]['por_que'] if candidates else ['Não há evidência territorial suficiente para indicar uma prioridade.'],
            'candidatos':candidates[:5],'dados_faltantes':faltas[decisao],
            'natureza':'sinal calculado; interpretação IA ainda não solicitada'}
    return result
