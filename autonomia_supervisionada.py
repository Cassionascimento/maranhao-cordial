"""Política fechada v1. Sem transporte no import; pausas P0 são soberanas.

A autorização automática vale apenas para modelos exatos e evidência relida do
banco. Texto livre da IA continua na fila humana. Reservas nunca são repetidas.
"""
import os
import re
import unicodedata
from datetime import timedelta
from email.utils import parseaddr
from html import escape
from psycopg2.extras import RealDictCursor, Json
import acoes_comerciais as acoes
from email_seguranca import verificar_travas_envio, bloquear_envios_no_contexto

VERSAO = 'supervisionada-v1'
LOCK = 5702001  # compartilha serialização com primeiro contato e resposta humana
MODELOS = {
    'primeiro_contato': ('Maranhão Cordial', 'Olá. Gostaríamos de apresentar a Maranhão Cordial. Há interesse em receber informações institucionais?'),
    'resposta': ('Re: Maranhão Cordial', 'Olá. Agradecemos seu contato com a Maranhão Cordial. Registramos sua mensagem para acompanhamento.'),
    'followup': ('Re: Maranhão Cordial', 'Olá. Retomamos nosso contato anterior. Há interesse em continuar a conversa com a Maranhão Cordial?'),
}


def sensivel(texto):
    normal = ''.join(c for c in unicodedata.normalize('NFKD', str(texto)) if not unicodedata.combining(c)).lower()
    return bool(re.search(r'pre[cç]o|desconto|contrat|cobran|pagamento|pix|estrateg|exclusiv|margem|orcamento|valor|negoci|invest|financeir|fiscal|juridic|nao.{0,25}interess|remov|descadastr|unsubscribe|pare de|nao.{0,20}contat', normal))


def elegivel(tipo, item, agora, entrada=None):
    if tipo not in MODELOS or not item or item.get('campanha_status') not in ('ativa','pesquisando','contatando','negociando'):
        return False
    if item.get('status') in ('descartado','pronto_para_fechamento','promissor','estrategico'):
        return False
    if not item.get('email') or not item.get('fonte_url') or not item.get('evidencia'):
        return False
    if sensivel(' '.join(str(item.get(k) or '') for k in ('objetivo','contexto','regras_adicionais','classificacao','motivo'))):
        return False
    if tipo == 'primeiro_contato':
        return item.get('permitir_primeiro_contato') is True and item.get('status') == 'qualificado' and (item.get('score') or 0) >= 55
    if not item.get('permitir_followup') or not item.get('ultimo_contato_em'):
        return False
    if tipo == 'resposta':
        return bool(entrada and entrada.get('processado_ia') is True and entrada.get('tipo_interacao') == 'email'
                    and entrada.get('canal') == 'gmail' and entrada.get('texto') and entrada.get('classificacao')
                    and not sensivel(str(entrada['texto'])+' '+str(entrada['classificacao']))
                    and parseaddr(entrada.get('sender_id',''))[1].lower() == item['email'].strip().lower())
    return bool(item.get('status') == 'contatado' and not item.get('ultima_resposta_em')
                and item.get('proximo_followup_em') and item['proximo_followup_em'] <= agora
                and agora - item['ultimo_contato_em'] >= timedelta(days=3))


def consultar(cur, sql, args=()):
    cur.execute(sql,args)
    return cur.fetchone()


def carregar(cur, ident):
    return consultar(cur, '''SELECT p.*,c.status campanha_status,c.permitir_primeiro_contato,
        c.permitir_followup,c.objetivo,c.contexto,c.regras_adicionais
        FROM prospectos_fase57 p JOIN campanhas_prospeccao_fase57 c ON c.id=p.campanha_id
        WHERE p.id=%s''',(ident,))


def entrada_recente(cur, email):
    # Remetentes com display name também são tratados pelo parseaddr abaixo.
    cur.execute("""SELECT * FROM interacoes_omnichannel WHERE canal='gmail' AND tipo_interacao='email'
        AND lower(sender_id) LIKE %s ORDER BY criado_em DESC LIMIT 100""",('%'+email.lower()+'%',))
    return next((r for r in cur.fetchall() if parseaddr(r.get('sender_id',''))[1].lower()==email.lower()), None)


def preparar(factory, limite=10):
    """Somente candidatos existentes; nenhuma pesquisa nem alteração de campanha."""
    conn=factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM prospectos_fase57 WHERE status IN ('qualificado','contatado','negociando') ORDER BY atualizado_em LIMIT %s",(min(max(limite,1),20),))
            ids=[r['id'] for r in cur.fetchall()]
        feitos=[]
        for ident in ids:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                item=carregar(cur,ident)
                agora=consultar(cur,'SELECT NOW() agora')['agora']
                entrada=entrada_recente(cur,item['email']) if item and item.get('email') else None
                tipo='primeiro_contato' if item and item['status']=='qualificado' else ('resposta' if entrada else 'followup')
                if not elegivel(tipo,item,agora,entrada):
                    continue
                assunto,texto=MODELOS[tipo]
                dados=dict(tipo=tipo, destinatario=item['email'].strip().lower(),empresa=item.get('empresa') or item.get('nome') or item['email'],
                    canal='email',objetivo=item['objetivo'],origem=item['fonte_url'],evidencia=item['evidencia'],
                    motivo='Modelo fechado da política '+VERSAO,mensagem=texto,assunto=assunto)
                if entrada: dados['origem_mensagem']=str(entrada['id'])
            r=acoes.propor(factory,dados,'prospecto_fase57',str(ident))
            # Nunca altera proposta anterior, inclusive texto livre ou decisão humana.
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    row=consultar(cur,'SELECT * FROM acoes_comerciais_propostas WHERE id=%s',(r['acao']['id'],))
                    if row['dados'].get('mensagem')==texto and row['dados'].get('assunto')==assunto:
                        cur.execute('''INSERT INTO autonomia_evidencias(acao_id,versao,modelo,digest)
                            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(row['id'],VERSAO,tipo,row['digest']))
                        feitos.append(str(row['id']))
        return feitos
    finally: conn.close()


def executar(factory, ident, namespace):
    """Reserva commitada antes do adaptador normal, jamais simula decisão humana."""
    if os.getenv('AUTONOMIA_SUPERVISIONADA_EXECUTAR')!='true':
        return {'success':False,'motivo':'execucao_desabilitada'}
    adaptadores = namespace.get('adaptadores_autonomia')
    if not adaptadores:
        return {'success':False,'motivo':'integracao_sem_transporte'}
    conn=factory(); token=None
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)',(LOCK,))
            if not cur.fetchone()[0]: return {'success':False,'motivo':'ocupado'}
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                politica=consultar(cur,'SELECT * FROM autonomia_politicas WHERE versao=%s AND habilitada',(VERSAO,))
                row=consultar(cur,'SELECT * FROM acoes_comerciais_propostas WHERE id=%s FOR UPDATE',(ident,))
                if not politica or not row or row['status']!='aguardando_aprovacao': return {'success':False,'motivo':'nao_elegivel'}
                d=dict(row['dados']); tipo=d.get('tipo')
                ev=consultar(cur,'SELECT * FROM autonomia_evidencias WHERE acao_id=%s',(ident,))
                if (tipo not in MODELOS or not ev or ev['versao']!=VERSAO or ev['modelo']!=tipo or ev['digest']!=row['digest']
                    or acoes.digest(d)!=row['digest'] or (d.get('assunto'),d.get('mensagem'))!=MODELOS[tipo]
                    or d.get('canal')!='email' or row['origem_tipo']!='prospecto_fase57'
                    or d.get('origem_id')!=row['origem_id'] or d.get('origem_tipo')!=row['origem_tipo']):
                    return {'success':False,'motivo':'conteudo_requer_humano'}
                item=carregar(cur,row['origem_id']); agora=consultar(cur,'SELECT NOW() agora')['agora']
                entrada=entrada_recente(cur,d['destinatario'])
                if (not elegivel(tipo,item,agora,entrada) or item['email'].strip().lower()!=d['destinatario']
                    or item['fonte_url']!=d['origem'] or (tipo=='followup' and entrada)
                    or (tipo=='resposta' and str(entrada['id'])!=d.get('origem_mensagem'))):
                    return {'success':False,'motivo':'contexto_alterado'}
                verificar_travas_envio(factory,d['destinatario'])
                if tipo!='primeiro_contato':
                    usados=consultar(cur,"""SELECT COUNT(*) n FROM autonomia_execucoes WHERE tipo IN ('resposta','followup')
                        AND (criado_em AT TIME ZONE 'America/Sao_Paulo')::date=(NOW() AT TIME ZONE 'America/Sao_Paulo')::date""")['n']
                    if usados>=politica['limite_continuacoes']: return {'success':False,'motivo':'limite_continuacoes'}
                chave=(tipo+':'+d['destinatario']) if tipo=='followup' else 'acao:'+str(ident)
                cur.execute("""INSERT INTO autonomia_execucoes(chave,versao,tipo,acao_id,destinatario,digest,estado)
                    VALUES(%s,%s,%s,%s,%s,%s,'reservada') ON CONFLICT DO NOTHING RETURNING chave""",
                    (chave,VERSAO,tipo,ident,d['destinatario'],row['digest']))
                if not cur.fetchone(): return {'success':False,'motivo':'ja_reservada'}
                cur.execute("UPDATE acoes_comerciais_propostas SET status='executando',executor=%s,atualizado_em=NOW() WHERE id=%s",(VERSAO,ident))
                cur.execute("INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,'autorizada_por_politica',%s)",(ident,VERSAO))
        d['_validar_politica']=lambda: revalidar(factory,row,tipo)
        token=acoes._aprovacao.set(d)
        # A conexão de reserva não pode reter o lock compartilhado durante um
        # adaptador que adquire o mesmo lock em outra conexão.
        with conn.cursor() as cur: cur.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
        try:
            resultado=adaptadores[tipo](namespace, d)
            estado='enviada' if resultado.get('success') and resultado.get('message_id') else 'incerta'
        except Exception as erro:
            resultado={'erro_tipo':type(erro).__name__}; estado='incerta'
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE autonomia_execucoes SET estado=%s,resultado=%s,concluido_em=NOW() WHERE chave=%s',(estado,Json(resultado),chave))
                cur.execute('UPDATE acoes_comerciais_propostas SET status=%s,resultado=%s,atualizado_em=NOW() WHERE id=%s',(estado,Json(resultado),ident))
                cur.execute('INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,%s,%s)',(ident,estado,VERSAO))
        return {'success':estado=='enviada','estado':estado}
    finally:
        if token is not None: acoes._aprovacao.reset(token)
        conn.close()


def transportar_continuacao(namespace,d):
    adaptador = namespace.get('adaptadores_autonomia', {}).get('continuacao')
    if adaptador is None:
        raise PermissionError('integracao_sem_transporte')
    d['_continuacao_politica']=VERSAO
    try:
        return adaptador(namespace,d)
    finally: d.pop('_continuacao_politica',None)


def briefing(namespace):
    """Reutiliza gerador e renderização legados; transporte reservado e rastreável."""
    if os.getenv('AUTONOMIA_SUPERVISIONADA_EXECUTAR')!='true':
        return {'success':False,'motivo':'execucao_desabilitada'}
    if not namespace.get('adaptadores_autonomia'):
        return {'success':False,'motivo':'integracao_sem_transporte'}
    factory=namespace['get_db_connection']; alvo=namespace.get('EMAIL_BRIEFING_DIRECAO')
    if not alvo: return {'success':False,'motivo':'destinatario_nao_configurado'}
    verificar_travas_envio(factory,alvo)
    conn=factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT pg_advisory_xact_lock(%s)',(5702009,))
                if not consultar(cur,'SELECT versao FROM autonomia_politicas WHERE versao=%s AND habilitada',(VERSAO,)):
                    return {'success':False,'motivo':'politica_inativa'}
                if consultar(cur,"SELECT 1 FROM autonomia_execucoes WHERE tipo='briefing' AND (estado<>'enviada' OR concluido_em>NOW()-INTERVAL '3 days') LIMIT 1"):
                    return {'success':True,'enviado':False,'motivo':'reservado_ou_periodo_nao_vencido'}
                if consultar(cur,"SELECT 1 FROM briefings_executivos_ia WHERE status='enviado' AND enviado_em>NOW()-INTERVAL '3 days' LIMIT 1"):
                    return {'success':True,'enviado':False,'motivo':'periodo_nao_vencido'}
                import uuid
                chave='briefing:'+str(uuid.uuid4())
                cur.execute("""INSERT INTO autonomia_execucoes(chave,versao,tipo,destinatario,digest,estado)
                    VALUES(%s,%s,'briefing',%s,'pendente','reservada')""",(chave,VERSAO,alvo))
        token=_briefing_reserva.set((namespace,chave,alvo))
        try:
            resultado=namespace['_enviar_briefing_legado'](forcar=False, transporte=transportar_briefing)
            estado='enviada' if resultado.get('success') and resultado.get('gmail',{}).get('gmail_id') else 'incerta'
        except Exception as erro:
            resultado={'erro_tipo':type(erro).__name__}; estado='incerta'
        finally: _briefing_reserva.reset(token)
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE autonomia_execucoes SET estado=%s,resultado=%s,concluido_em=NOW() WHERE chave=%s',(estado,Json(resultado),chave))
        return resultado
    finally: conn.close()

from contextvars import ContextVar
_briefing_reserva=ContextVar('briefing_reserva',default=None)


def transportar_briefing(alvo,assunto,corpo):
    reserva=_briefing_reserva.get()
    if not reserva or reserva[2]!=alvo: raise PermissionError('briefing_sem_reserva')
    namespace,chave,_=reserva
    _briefing_reserva.set(None)  # consumível uma única vez
    d=dict(destinatario=alvo,assunto=assunto,mensagem=corpo,_continuacao_politica=VERSAO)
    conn=namespace['get_db_connection']()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE autonomia_execucoes SET digest=%s WHERE chave=%s',(acoes.digest(d),chave))
    finally: conn.close()
    token=acoes._aprovacao.set(d)
    try:
        r=transportar_continuacao(namespace,d)
        return dict(r,gmail_id=r.get('message_id'))
    finally: acoes._aprovacao.reset(token)


def ciclo(namespace):
    if os.getenv('AUTONOMIA_SUPERVISIONADA_EXECUTAR')!='true':
        return {'success':True,'modo':'bloqueado_sem_ativacao'}
    from entrada_segura import recuperar_pendentes
    factory=namespace['get_db_connection']
    recuperadas=recuperar_pendentes(factory,namespace['processar_interacao_omnichannel_crm'])
    if any(not r.get('success') for r in recuperadas): return {'success':False,'motivo':'entrada_pendente'}
    conn=factory()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM interacoes_omnichannel WHERE canal='gmail' AND tipo_interacao='email' AND NOT COALESCE(processado_ia,FALSE) LIMIT 1")
            if cur.fetchone(): return {'success':False,'motivo':'entrada_pendente'}
    finally: conn.close()
    ids=preparar(factory)
    resultados=[]
    for ident in ids:
        r=executar(factory,ident,namespace); resultados.append(r)
        if r.get('estado')=='incerta': break
    return {'success':True,'acoes':resultados,'briefing':briefing(namespace)}


def registrar_rotas(app,namespace):
    from flask import jsonify
    @app.get('/api/admin/autonomia-supervisionada')
    def status():
        if not namespace['validar_admin_request'](): return jsonify(success=False),401
        conn=namespace['get_db_connection']()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                politica=consultar(cur,'SELECT versao,habilitada,limite_continuacoes FROM autonomia_politicas WHERE versao=%s',(VERSAO,))
                cur.execute('SELECT tipo,estado,COUNT(*) quantidade FROM autonomia_execucoes GROUP BY tipo,estado')
                registros=[dict(r) for r in cur.fetchall()]
                proximo=consultar(cur,"SELECT MAX(enviado_em)+INTERVAL '3 days' proximo FROM briefings_executivos_ia WHERE status='enviado'")
                pausa=consultar(cur,'SELECT pausado FROM email_controle_p0 WHERE id=1')
            return jsonify(success=True,politica=dict(politica) if politica else None,registros=registros,
                proximo_briefing=proximo['proximo'].isoformat() if proximo and proximo['proximo'] else None,
                execucao_habilitada=False,
                pausado=bool(not pausa or pausa['pausado'] or os.getenv('EMAIL_ENVIOS_PAUSADOS','false').lower() not in ('false','0','no')),
                whatsapp='bloqueado_meta')
        except Exception: return jsonify(success=False,motivo='sem_dados'),503
        finally: conn.close()


def revalidar(factory,row,tipo):
    """Última checagem no adaptador imediatamente antes de consumir transporte."""
    conn=factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if os.getenv('AUTONOMIA_SUPERVISIONADA_EXECUTAR')!='true' or not consultar(cur,
                    'SELECT versao FROM autonomia_politicas WHERE versao=%s AND habilitada',(VERSAO,)):
                raise PermissionError('politica_desabilitada')
            d=row['dados']; item=carregar(cur,row['origem_id'])
            entrada=entrada_recente(cur,d['destinatario'])
            agora=consultar(cur,'SELECT NOW() agora')['agora']
            if not elegivel(tipo,item,agora,entrada) or (tipo=='followup' and entrada):
                raise PermissionError('contexto_alterado_antes_transporte')
            if tipo=='resposta' and str(entrada['id'])!=d.get('origem_mensagem'):
                raise PermissionError('nova_entrada')
            if consultar(cur,"SELECT 1 FROM interacoes_omnichannel WHERE canal='gmail' AND tipo_interacao='email' AND NOT COALESCE(processado_ia,FALSE) LIMIT 1"):
                raise PermissionError('entrada_pendente')
        verificar_travas_envio(factory,d['destinatario'])
    finally: conn.close()
