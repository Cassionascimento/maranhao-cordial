"""Propostas imutáveis; decisões humanas e execução de primeiro contato sem retry."""
import hashlib
import json
import re
from contextvars import ContextVar
from uuid import UUID
from psycopg2.extras import RealDictCursor, Json
from mi_sinais import emitir

_aprovacao = ContextVar("acao_comercial_aprovada", default=None)

# Registro fechado; futuros fluxos adicionam um resolvedor, sem alterar o schema.
# Nenhum nome de tabela recebido de request é interpolado no SQL.
ORIGENS = {
    'prospecto_fase56': 'SELECT id FROM prospectos_fabrica_fase56 WHERE id=%s FOR KEY SHARE',
    'prospecto_fase57': 'SELECT id FROM prospectos_fase57 WHERE id=%s FOR KEY SHARE',
}


def validar_origem(cur, tipo, identificador):
    if tipo not in ORIGENS:
        raise ValueError('origem_nao_suportada')
    ident = str(UUID(str(identificador)))
    cur.execute(ORIGENS[tipo], (ident,))
    if not cur.fetchone():
        raise ValueError('origem_nao_encontrada')
    return ident


def digest(dados):
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def validar_dados(d):
    for campo in ("destinatario", "empresa", "canal", "objetivo", "origem", "evidencia", "motivo", "mensagem", "assunto"):
        if not str(d.get(campo) or "").strip():
            raise ValueError("proposta_incompleta:" + campo)
    if d['canal'] != 'email' or not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", d['destinatario']):
        raise ValueError('destinatario_invalido')
    if any(c in d['assunto'] for c in ('\r','\n')):
        raise ValueError('assunto_invalido')


def propor(factory, dados, origem_tipo, origem_id):
    validar_dados(dados)
    email = dados['destinatario'].strip().lower()
    tipo = dados.get('tipo')
    if tipo == 'primeiro_contato':
        chave = 'primeiro_contato:' + email
    elif tipo == 'followup':
        chave = 'followup:' + email
    elif tipo == 'resposta':
        chave = 'resposta:' + email + ':' + str(UUID(str(dados.get('origem_mensagem'))))
    else:
        raise ValueError('tipo_acao_nao_suportado')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                ident = validar_origem(cur, origem_tipo, origem_id)
                dados = dict(dados, destinatario=email, origem_tipo=origem_tipo, origem_id=ident)
                cur.execute("""INSERT INTO acoes_comerciais_propostas(chave,origem_tipo,origem_id,dados,digest)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT(chave) DO NOTHING RETURNING id""",
                    (chave, origem_tipo, ident, Json(dados), digest(dados)))
                nova = cur.fetchone()
                if nova:
                    cur.execute("INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,'proposta','ia')", (nova['id'],))
                cur.execute("SELECT id,status,digest,origem_tipo,origem_id FROM acoes_comerciais_propostas WHERE chave=%s", (chave,))
                row = dict(cur.fetchone())
    finally:
        conn.close()
    if nova:
        # Proposta da IA pendente de decisão humana: recomendação, nunca fato confirmado.
        emitir(factory, natureza='recomendacao', origem='acoes_comerciais', tipo_evento='acao_proposta',
               origem_id=str(row['id']), canal=dados.get('canal'),
               payload={'tipo': dados.get('tipo'), 'origem_tipo': origem_tipo})
    return dict(success=True, proposta_criada=bool(nova), enviado=False, acao=row)


def decidir(factory, identificador, esperado, aprovar, ator='direcao'):
    conn = factory()
    status = 'aprovada' if aprovar else 'rejeitada'
    sucesso = False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE acoes_comerciais_propostas SET status=%s,decidido_em=NOW(),
                    decidido_por=%s,digest_aprovado=%s,atualizado_em=NOW()
                    WHERE id=%s AND status='aguardando_aprovacao' AND digest=%s RETURNING id""",
                    (status, ator, esperado if aprovar else None, identificador, esperado))
                if cur.fetchone():
                    sucesso = True
                    cur.execute("INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,%s,%s)", (identificador,status,ator))
    finally:
        conn.close()
    if not sucesso:
        return {'success': False, 'motivo': 'estado_ou_conteudo_alterado'}
    # Decisão humana de fato tomada: ação, não mais recomendação pendente.
    emitir(factory, natureza='acao', origem='acoes_comerciais', tipo_evento='acao_' + status,
           origem_id=str(identificador), payload={'ator': ator})
    return {'success': True, 'status': status, 'enviado': False}


def conteudo_aprovado(destinatario=None):
    d = _aprovacao.get()
    if not d or (destinatario and destinatario.strip().lower() != d['destinatario']):
        raise PermissionError('aprovacao_humana_obrigatoria')
    return d


def autorizar_transporte(destinatario, assunto, texto, cc=None):
    d = conteudo_aprovado(destinatario)
    if cc or d.get('_consumida') or assunto != d['assunto'] or texto != d['mensagem']:
        raise PermissionError('transporte_fora_da_aprovacao')
    if d.get('_validar_politica'):
        d['_validar_politica']()
    d['_consumida'] = True


def executar(factory, identificador, executor, resposta_executor=None):
    # A reivindicação é persistida ANTES de qualquer tentativa. Crash não libera retry.
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM acoes_comerciais_propostas WHERE id=%s FOR UPDATE", (identificador,))
                row = cur.fetchone()
                if not row or row['status'] != 'aprovada':
                    return {'success': False, 'motivo': 'acao_nao_aprovada'}
                d = dict(row['dados'])
                validar_dados(d)
                if digest(d) != row['digest'] or row['digest_aprovado'] != row['digest']:
                    return {'success': False, 'motivo': 'conteudo_nao_aprovado'}
                if (row['origem_tipo'],row['origem_id']) != (d.get('origem_tipo'),d.get('origem_id')):
                    return {'success': False, 'motivo': 'origem_nao_aprovada'}
                # Não encaminha IDs da Fase 5.6 ao executor exclusivo da Fase 5.7.
                # Propostas do piloto são preservadas; nenhum novo transporte é habilitado.
                if d.get('tipo') == 'primeiro_contato' and row['origem_tipo'] != 'prospecto_fase57':
                    return {'success': False, 'motivo': 'executor_da_origem_nao_habilitado'}
                validar_origem(cur,row['origem_tipo'],row['origem_id'])
                # Respostas permanecem preparáveis, mas não usam reserva de primeiro contato.
                if d.get('tipo') not in ('primeiro_contato','resposta') or (d.get('tipo') == 'resposta' and resposta_executor is None):
                    return {'success': False, 'motivo': 'execucao_deste_tipo_nao_habilitada'}
                cur.execute("UPDATE acoes_comerciais_propostas SET status='executando',executor='executor_aprovado',atualizado_em=NOW() WHERE id=%s", (identificador,))
                cur.execute("INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,'executando','executor_aprovado')", (identificador,))
    finally:
        conn.close()
    token = _aprovacao.set(d)
    try:
        resultado = resposta_executor(d) if d['tipo'] == 'resposta' else executor(row['origem_id'])
        status = 'enviada' if resultado.get('success') and resultado.get('message_id') else ('incerta' if d.get('_consumida') else 'bloqueada')
    except Exception as erro:
        resultado = {'success': False, 'erro_tipo': type(erro).__name__}
        status = 'incerta'  # conservador mesmo em falha anterior ao transporte
    finally:
        _aprovacao.reset(token)
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE acoes_comerciais_propostas SET status=%s,resultado=%s,atualizado_em=NOW() WHERE id=%s AND status='executando'", (status,Json(resultado),identificador))
                cur.execute("INSERT INTO auditoria_acoes_comerciais(acao_id,evento,ator) VALUES(%s,%s,'executor_aprovado')", (identificador,status))
    finally:
        conn.close()
    # Desfecho observável da execução -- resultado, não a ação em si.
    tipo_sinal = 'acao_bloqueada' if status == 'bloqueada' else 'acao_executada'
    emitir(factory, natureza='resultado', origem='acoes_comerciais', tipo_evento=tipo_sinal,
           origem_id=str(identificador), resultado=status, payload={'tipo': d.get('tipo')})
    return {'success': status == 'enviada', 'status': status, 'resultado': resultado}


def registrar_rotas(app, namespace):
    from flask import request, jsonify
    factory = lambda: namespace['get_db_connection']()

    @app.before_request
    def proteger_rotas_acoes_comerciais():
        if request.path.startswith(('/api/admin/acoes-comerciais', '/api/admin/gmail/reconciliar')) and request.method != 'OPTIONS':
            if not namespace['validar_admin_request']():
                return jsonify(success=False, motivo='nao_autorizado'),401

    @app.route('/api/admin/gmail/reconciliar/<uuid:identificador>', methods=['POST'])
    def reconciliar_gmail_seguro(identificador):
        from entrada_segura import reconciliar_interacao
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM interacoes_omnichannel WHERE id=%s AND canal='gmail' AND tipo_interacao='email'", (str(identificador),))
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return jsonify(success=False, motivo='entrada_nao_encontrada'),404
        r = reconciliar_interacao(factory,namespace['processar_interacao_omnichannel_crm'],dict(row))
        return jsonify(r),200 if r.get('success') else 409


    @app.route('/api/admin/acoes-comerciais', methods=['GET'])
    def listar_acoes_comerciais():
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM acoes_comerciais_propostas ORDER BY (status='aguardando_aprovacao') DESC, criado_em DESC LIMIT 100")
                return jsonify(success=True, acoes=[dict(r) for r in cur.fetchall()])
        finally:
            conn.close()

    @app.route('/api/admin/acoes-comerciais/<uuid:identificador>/decisao', methods=['POST'])
    def decidir_acao_comercial(identificador):
        d = request.get_json(silent=True)
        if not isinstance(d,dict) or d.get('decisao') not in ('aprovar','rejeitar') or not isinstance(d.get('digest'),str):
            return jsonify(success=False, motivo='decisao_invalida'),400
        r = decidir(factory,str(identificador),d['digest'],d['decisao']=='aprovar')
        return jsonify(r),200 if r['success'] else 409

    @app.route('/api/admin/acoes-comerciais/<uuid:identificador>/executar', methods=['POST'])
    def executar_acao_comercial(identificador):
        from fase57_prospeccao_universal import executar_primeiro_contato_aprovado
        r = executar(factory,str(identificador),lambda pid: executar_primeiro_contato_aprovado(namespace,pid),lambda d: executar_resposta_aprovada(namespace,d))
        return jsonify(r),200 if r['success'] else 409


def executar_resposta_aprovada(namespace, dados):
    """Resposta a entrada identificada: histórico obrigatório, lock e sem nova quota."""
    from email_seguranca import verificar_travas_envio
    from fase56_fabrica_piloto import obter_gmail_service_fase56, enviar_email_institucional_fase56, _assinatura_html
    from email.utils import parseaddr
    from html import escape
    factory = namespace['get_db_connection']
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', (5702001,))
            if not cur.fetchone()[0]:
                return {'success': False, 'motivo': 'rodada_em_andamento'}
            cur.execute("SELECT 1 FROM prospeccao_historico_contatados WHERE email=%s LIMIT 1", (dados['destinatario'],))
            if not cur.fetchone():
                raise PermissionError('resposta_nao_pode_iniciar_contato')
            cur.execute("SELECT message_id,sender_id FROM interacoes_omnichannel WHERE id=%s AND canal='gmail' AND tipo_interacao='email'", (dados['origem_mensagem'],))
            row = cur.fetchone()
            if not row or parseaddr(row[1])[1].lower() != dados['destinatario']:
                raise PermissionError('entrada_incompativel')
        verificar_travas_envio(factory,dados['destinatario'])
        service = obter_gmail_service_fase56(namespace)
        msg = service.users().messages().get(userId='me',id=row[0],format='metadata').execute(num_retries=0)
        headers = {h['name'].lower():h['value'] for h in msg.get('payload',{}).get('headers',[])}
        rfc = headers.get('message-id','')
        if not msg.get('threadId') or not rfc or any(c in rfc for c in ('\r','\n')) or parseaddr(headers.get('from',''))[1].lower() != dados['destinatario']:
            raise PermissionError('thread_nao_confirmada')
        dados['_resposta_validada'] = True
        html = '<div>'+''.join('<p>'+escape(x)+'</p>' for x in dados['mensagem'].splitlines())+_assinatura_html()+'</div>'
        return enviar_email_institucional_fase56(namespace,dados['destinatario'],dados['assunto'],html,dados['mensagem'],reply_message_id=msg['threadId'],reply_rfc_message_id=rfc)
    finally:
        dados.pop('_resposta_validada',None)
        conn.close()
