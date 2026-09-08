"""Exceção explícita e durável para uma mensagem; nunca altera as pausas P0.

Nenhum adaptador normal consulta esta autorização. Consumo anterior ao Gmail,
sem retry: falha/timeout após consumo exige reconciliação, nunca reenvio.
"""
import base64
import hashlib
import html
import os
import uuid
from email import policy
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.utils import formatdate, formataddr

from email_seguranca import EnvioBloqueado, enderecos


def schema(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_autorizacoes_unicas_p0 (
            id UUID PRIMARY KEY,
            destinatario TEXT NOT NULL,
            raw TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            texto TEXT NOT NULL,
            motivo TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'autorizado'
                CHECK (estado IN ('autorizado','consumido','enviado','incerto')),
            criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expira_em TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '10 minutes',
            consumido_em TIMESTAMPTZ,
            gmail_id TEXT,
            thread_id TEXT,
            crm_id UUID,
            erro_tipo TEXT
        )
    """)


def _travas(cur, destinatario):
    if os.getenv('EMAIL_ENVIOS_PAUSADOS') != 'true':
        raise EnvioBloqueado('Supervisionado exige pausa por ambiente ativa')
    cur.execute('SELECT pausado FROM email_controle_p0 WHERE id=1')
    row = cur.fetchone()
    if not row or row[0] is not True:
        raise EnvioBloqueado('Supervisionado exige pausa persistente ativa')
    cur.execute('SELECT email FROM email_supressoes_p0 WHERE email=%s', (destinatario,))
    if cur.fetchone():
        raise EnvioBloqueado('Destinatário suprimido; autorização não sobrepõe supressão')


def _auditar(cur, tipo, ident, destinatario, motivo):
    cur.execute("""INSERT INTO email_eventos_seguranca_p0
        (tipo,destinatario,mensagem_origem,motivo) VALUES (%s,%s,%s,%s)""",
        (tipo, destinatario, str(ident), motivo))


def preparar(dados):
    from fase56_fabrica_piloto import EMAIL_INSTITUCIONAL, LOGO_EMAIL, _assinatura_html
    campos = {'destinatario', 'assunto', 'texto', 'motivo'}
    if not isinstance(dados, dict) or set(dados) != campos:
        raise ValueError('Informe somente destinatario, assunto, texto e motivo')
    if any(not isinstance(dados[k], str) or not dados[k].strip() for k in campos):
        raise ValueError('Campos obrigatórios devem ser texto não vazio')
    alvo = dados['destinatario'].strip().lower()
    if enderecos(alvo) != [alvo]:
        raise ValueError('Exige exatamente um endereço simples; sem nomes, Cc ou Bcc')
    if len(alvo) > 254 or len(dados['assunto']) > 200 or any(c in dados['assunto'] for c in '\r\n'):
        raise ValueError('Destinatário ou assunto inválido')
    if len(dados['texto']) > 10000 or len(dados['motivo']) > 2000:
        raise ValueError('Conteúdo excede o limite supervisionado')
    ident = str(uuid.uuid4())
    texto = dados['texto'].strip() + '\n\nMaranhão Cordial\nCássio Nascimento · Direção\n' + EMAIL_INSTITUCIONAL + '\nmaranhaocordial.com.br'
    msg = MIMEMultipart('related')
    msg['From'] = formataddr(('Maranhão Cordial', EMAIL_INSTITUCIONAL))
    msg['To'] = alvo
    msg['Subject'] = dados['assunto']
    msg['Date'] = formatdate(localtime=False)
    msg['Message-ID'] = f'<supervisionado-{ident}@maranhaocordial.com.br>'
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(texto, 'plain', 'utf-8'))
    alt.attach(MIMEText('<div>' + html.escape(dados['texto']).replace('\n', '<br>') + '</div>' + _assinatura_html(), 'html', 'utf-8'))
    msg.attach(alt)
    if os.path.isfile(LOGO_EMAIL):
        with open(LOGO_EMAIL, 'rb') as f:
            logo = MIMEImage(f.read(), _subtype='jpeg')
        logo.add_header('Content-ID', '<logo_maranhao_cordial>')
        logo.add_header('Content-Disposition', 'inline', filename='maranhao-cordial-logo.jpg')
        msg.attach(logo)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return ident, alvo, raw, digest, texto, dados['motivo']


def autorizar(conn_factory, dados):
    registro = preparar(dados)
    ident, alvo, raw, digest, texto, motivo = registro
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                schema(cur)
                _travas(cur, alvo)
                cur.execute("""INSERT INTO email_autorizacoes_unicas_p0
                    (id,destinatario,raw,sha256,texto,motivo) VALUES (%s,%s,%s,%s,%s,%s)""", registro)
                _auditar(cur, 'supervisionado_autorizado', ident, alvo, motivo)
    finally:
        conn.close()
    return {'success': True, 'autorizacao_id': ident, 'destinatario': alvo, 'sha256': digest, 'validade_segundos': 600}


def consumir(conn_factory, ident):
    from fase56_fabrica_piloto import EMAIL_INSTITUCIONAL
    ident = str(uuid.UUID(ident))
    conn = conn_factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT destinatario,raw,sha256,texto FROM email_autorizacoes_unicas_p0
                    WHERE id=%s AND estado='autorizado' AND expira_em>NOW() FOR UPDATE""", (ident,))
                row = cur.fetchone()
                if not row:
                    raise EnvioBloqueado('Autorização ausente, expirada ou já consumida')
                alvo, raw, digest, texto = row
                _travas(cur, alvo)
                if hashlib.sha256(raw.encode()).hexdigest() != digest:
                    raise EnvioBloqueado('Conteúdo da autorização alterado')
                msg = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
                if (msg.get_all('To') != [alvo] or msg.get_all('Cc') or msg.get_all('Bcc')
                        or msg.get_all('Resent-To') or msg.get_all('Resent-Cc') or msg.get_all('Resent-Bcc')
                        or enderecos(str(msg['From'])) != [EMAIL_INSTITUCIONAL]
                        or str(msg['Message-ID']) != f'<supervisionado-{ident}@maranhaocordial.com.br>'):
                    raise EnvioBloqueado('Envelope da autorização inválido')
                cur.execute("""UPDATE email_autorizacoes_unicas_p0
                    SET estado='consumido',consumido_em=NOW() WHERE id=%s""", (ident,))
                _auditar(cur, 'supervisionado_consumido', ident, alvo, 'Consumo irreversível antes do Gmail; sem retry')
        # O commit precisa ter sucesso antes de devolver qualquer capacidade de envio.
        return ident, alvo, raw, texto
    finally:
        conn.close()


def executar(namespace, ident):
    from fase56_fabrica_piloto import EMAIL_INSTITUCIONAL, obter_gmail_service_fase56
    factory = namespace['get_db_connection']
    ident, alvo, raw, texto = consumir(factory, ident)
    resultado = {}
    try:
        service = obter_gmail_service_fase56(namespace)
        perfil = service.users().getProfile(userId='me').execute(num_retries=0)
        if (perfil.get('emailAddress') or '').lower() != EMAIL_INSTITUCIONAL:
            raise EnvioBloqueado('Conta Gmail diferente do remetente institucional')
        # Reconfere supressão/pausas após obter credenciais, antes da única submissão.
        conn = factory()
        try:
            with conn.cursor() as cur:
                _travas(cur, alvo)
        finally:
            conn.close()
        resultado = service.users().messages().send(userId='me', body={'raw': raw}).execute(num_retries=0)
        if not resultado.get('id') or not resultado.get('threadId'):
            raise RuntimeError('Resultado Gmail incompleto; não repetir')
        conn = factory()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO interacoes_omnichannel
                        (id,canal,plataforma,sender_id,recipient_id,message_id,texto,
                         tipo_interacao,classificacao,processado_ia,criado_em,atualizado_em)
                        VALUES (gen_random_uuid(),'gmail','gmail',%s,%s,%s,%s,
                        'saida_ia_empresarial','email_supervisionado',TRUE,NOW(),NOW()) RETURNING id""",
                        (EMAIL_INSTITUCIONAL, alvo, resultado['id'], texto))
                    crm_id = str(cur.fetchone()[0])
                    cur.execute("""UPDATE email_autorizacoes_unicas_p0 SET estado='enviado',
                        gmail_id=%s,thread_id=%s,crm_id=%s WHERE id=%s""",
                        (resultado['id'], resultado['threadId'], crm_id, ident))
                    _auditar(cur, 'supervisionado_enviado', ident, alvo, 'Gmail confirmou ID; registrado no CRM')
        finally:
            conn.close()
    except Exception as erro:
        # Nunca devolve a autorização ao estado autorizado, mesmo em falha do banco.
        try:
            conn = factory()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""UPDATE email_autorizacoes_unicas_p0 SET estado='incerto',
                            gmail_id=%s,thread_id=%s,erro_tipo=%s WHERE id=%s""",
                            (resultado.get('id'), resultado.get('threadId'), type(erro).__name__, ident))
                        _auditar(cur, 'supervisionado_incerto', ident, alvo, 'Falha após consumo; reconciliar sem reenvio')
            finally:
                conn.close()
        except Exception:
            pass  # O consumo já foi confirmado; permanece fechado.
        raise RuntimeError('Autorização consumida; resultado incerto. Não repetir envio.') from erro
    return {'success': True, 'autorizacao_id': ident, 'destinatario': alvo,
            'message_id': resultado['id'], 'thread_id': resultado['threadId'], 'crm_id': crm_id}
