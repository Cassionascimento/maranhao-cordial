"""Agendamento cloud da rodada verificada; reutiliza o motor comercial homologado."""
import json
import os
import time
from datetime import datetime, date
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI

from email_seguranca import definir_pausa
from gmail_sync_job import executar_job as sincronizar
from fase56_fabrica_piloto import obter_gmail_service_fase56
from fase57_prospeccao_universal import (
    enviar_primeiro_contato_fase57, executar_pesquisa_publica_fase57,
    garantir_pesquisa_se_faltar_fase57,
)
from prospeccao_controle import status, elegivel_sql
from prospeccao_fonte_publica import validar_associacao

FECHAMENTO = 'prospeccao_render: intervalo seguro entre rodadas'
INCIDENTE = 'prospeccao_render: incidente; requer intervenção'
CONTA = 'contato@maranhaocordial.com.br'
RUN_LOCK = 5702002


def conectar():
    return psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require', connect_timeout=10)


def dependencias(factory):
    for key in ('DATABASE_URL', 'ADMIN_API_KEY', 'OPENAI_API_KEY'):
        if not os.getenv(key):
            raise RuntimeError('dependencia_ausente:' + key)
    if os.getenv('EMAIL_ENVIOS_PAUSADOS') != 'true' or os.getenv('EMAIL_APENAS_PROSPECCAO_CONTROLADA') != 'true':
        raise RuntimeError('travas_de_entrada_incorretas')
    contador = status(factory)
    gmail = obter_gmail_service_fase56({'get_db_connection': factory})
    if gmail.users().getProfile(userId='me').execute(num_retries=0).get('emailAddress', '').lower() != CONTA:
        raise RuntimeError('conta_gmail_incorreta')
    OpenAI(max_retries=0, timeout=20).models.retrieve(os.getenv('OPENAI_MODEL_PROSPECCAO', 'gpt-5-mini'))
    return gmail, contador


def permite_janela(agora):
    inicio = date.fromisoformat(os.environ['PROSPECCAO_RENDER_INICIO'])
    return agora.date() >= inicio and agora.weekday() < 5 and agora.hour == 10


def pausa_rotineira(cur):
    cur.execute('SELECT pausado FROM email_controle_p0 WHERE id=1')
    if cur.fetchone()[0] is not True:
        raise RuntimeError('pausa_inicial_inesperada')
    cur.execute("SELECT motivo FROM email_eventos_seguranca_p0 WHERE tipo IN ('pausa','retomada') ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row or row[0] != FECHAMENTO:
        raise RuntimeError('pausa_de_emergencia_nao_pode_ser_retirada_pelo_cron')
    cur.execute("SELECT 1 FROM prospeccao_reservas WHERE estado<>'enviado' LIMIT 1")
    if cur.fetchone():
        raise RuntimeError('reserva_pendente_requer_reconciliacao')


def candidatos(factory, vistos):
    db = factory()
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT p.* FROM prospectos_fase57 p
                JOIN campanhas_prospeccao_fase57 c ON c.id=p.campanha_id
                WHERE c.status IN ('ativa','pesquisando','contatando','negociando')
                  AND c.permitir_primeiro_contato AND """ + elegivel_sql() + """
                  AND NOT (p.id::text = ANY(%s))
                ORDER BY p.score DESC,p.criado_em LIMIT 12""", (list(vistos),))
            return [dict(r) for r in cur.fetchall()]
    finally:
        db.close()


def evento(factory, tipo, item, motivo):
    db = factory()
    try:
        with db:
            with db.cursor() as cur:
                cur.execute('''INSERT INTO email_eventos_seguranca_p0
                    (tipo,destinatario,mensagem_origem,motivo) VALUES(%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING''', (tipo, item['email'], str(item['id']), motivo[:2000]))
    finally:
        db.close()


def verificar_resultado(factory, gmail, item, resultado, inicio):
    import base64
    from email.utils import getaddresses, parseaddr
    mid = resultado['message_id']
    gm = gmail.users().messages().get(userId='me', id=mid, format='full').execute(num_retries=0)
    h = {x['name'].lower(): x['value'] for x in gm['payload']['headers']}
    if ('SENT' not in gm.get('labelIds', []) or gm['threadId'] != resultado['thread_id']
            or parseaddr(h.get('from', ''))[1].lower() != CONTA
            or [e.lower() for _, e in getaddresses([h.get('to', '')])] != [item['email'].strip().lower()]
            or h.get('cc') or h.get('bcc')):
        raise RuntimeError('verificacao_gmail_falhou')
    def textos_html(parte):
        if parte.get('mimeType') == 'text/html':
            yield base64.urlsafe_b64decode(parte.get('body', {}).get('data', '')).decode('utf-8', errors='replace')
        for filha in parte.get('parts', []):
            yield from textos_html(filha)
    if 'maranhaocordial.com.br' not in ''.join(textos_html(gm['payload'])):
        raise RuntimeError('assinatura_nao_confirmada')
    db = factory()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT estado,gmail_id FROM prospeccao_reservas WHERE prospecto_id=%s', (str(item['id']),))
            if cur.fetchone() != ('enviado', mid):
                raise RuntimeError('reserva_nao_concluida')
            cur.execute('SELECT count(*) FROM interacoes_omnichannel WHERE message_id=%s AND recipient_id=%s', (mid, item['email']))
            if cur.fetchone()[0] < 1:
                raise RuntimeError('crm_nao_confirmado')
    finally:
        db.close()
    evento(factory, 'prospeccao_render_verificada', item,
           json.dumps({'gmail_id': mid, 'thread_id': gm['threadId'], 'rfc_message_id': h.get('message-id'), 'entrega_confirmada': False}))


def executar(factory=conectar, agora=None):
    modo = os.getenv('PROSPECCAO_RENDER_MODO', 'seguro')
    if modo not in ('seguro', 'ativo'):
        raise RuntimeError('modo_invalido')
    gmail, contador = dependencias(factory)
    if modo == 'seguro':
        return {'success': True, 'modo': 'seguro', 'dependencias': 'PASS', 'envios': 0, 'contador': contador}
    agora = agora or datetime.now(ZoneInfo('America/Sao_Paulo'))
    if not permite_janela(agora):
        return {'success': True, 'motivo': 'fora_da_janela', 'envios': 0}
    controle = factory()
    levantou = False
    incidente = False
    inicio = int(time.time())
    vistos, enviados, pesquisas, excluidos = set(), [], [], 0
    try:
        with controle.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', (RUN_LOCK,))
            if not cur.fetchone()[0]:
                return {'success': True, 'motivo': 'rodada_em_andamento', 'envios': 0}
            pausa_rotineira(cur)
        if contador['bloqueado']:
            return {'success': True, 'motivo': 'cota_diaria', 'envios': 0, 'contador': contador}
        sincronizar()
        ns = {'get_db_connection': factory}
        for ciclo in range(4):
            for item in candidatos(factory, vistos):
                if len(vistos) >= 12 or status(factory)['bloqueado']:
                    break
                vistos.add(str(item['id']))
                valido, evidencia = validar_associacao(item['email'], item['fonte_url'])
                if not valido:
                    excluidos += 1
                    evento(factory, 'prospeccao_render_excluida', item, evidencia)
                    continue
                evento(factory, 'prospeccao_render_fonte_confirmada', item, evidencia)
                # A pausa de emergência nunca é limpa apenas por chegar novo horário.
                with controle.cursor() as cur:
                    pausa_rotineira(cur)
                levantou = True
                definir_pausa(factory, False, 'prospeccao_render: destinatário verificado; reserva obrigatória')
                os.environ['EMAIL_ENVIOS_PAUSADOS'] = 'false'
                try:
                    r = enviar_primeiro_contato_fase57(ns, str(item['id']))
                    if r.get('enviado') is not True:
                        raise RuntimeError('envio_nao_confirmado')
                finally:
                    os.environ['EMAIL_ENVIOS_PAUSADOS'] = 'true'
                verificar_resultado(factory, gmail, item, r, inicio)
                enviados.append(r['message_id'])
                sent = gmail.users().messages().list(userId='me', q='in:sent after:'+str(inicio), maxResults=100).execute(num_retries=0)
                if sent.get('nextPageToken') or {m['id'] for m in sent.get('messages', [])} != set(enviados):
                    raise RuntimeError('envio_inesperado')
                definir_pausa(factory, True, FECHAMENTO)
                levantou = False
            if status(factory)['bloqueado'] or len(vistos) >= 12 or ciclo == 3:
                break
            db = factory()
            try:
                with db.cursor() as cur:
                    cur.execute("SELECT id FROM campanhas_prospeccao_fase57 WHERE status='ativa' AND permitir_primeiro_contato ORDER BY criado_em")
                    campanhas = [str(r[0]) for r in cur.fetchall()]
            finally:
                db.close()
            for campanha in campanhas:
                garantir_pesquisa_se_faltar_fase57(ns, campanha)
            pesquisa = executar_pesquisa_publica_fase57(ns, limite=4)
            pesquisas.append(pesquisa)
            if not pesquisa.get('success'):
                raise RuntimeError('pesquisa_falhou')
            if not pesquisa.get('executada'):
                break
        return {'success': True, 'envios': len(enviados), 'excluidos': excluidos,
                'pesquisas': len(pesquisas), 'avaliados': len(vistos), 'contador': status(factory)}
    except Exception:
        incidente = True
        raise
    finally:
        os.environ['EMAIL_ENVIOS_PAUSADOS'] = 'true'
        if levantou or incidente:
            definir_pausa(factory, True, INCIDENTE)
        controle.close()


if __name__ == '__main__':
    try:
        print(json.dumps(executar(), default=str))
    except Exception as erro:
        print(json.dumps({'success': False, 'erro_tipo': type(erro).__name__, 'envios_nao_repetir': True}))
        raise SystemExit(1)
