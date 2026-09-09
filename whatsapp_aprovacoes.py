"""Aprovação humana de respostas WhatsApp na fila Admin existente.

Somente respostas livres a mensagens recebidas nas últimas 24h. Não implementa
prospecção WhatsApp nem transforma mensagens livres em templates automaticamente.
"""
import hashlib
import json
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor, Json

_contexto = ContextVar('whatsapp_aprovacao', default=None)


def digest(fila):
    dados = {k: str(fila.get(k) or '') for k in ('id', 'interacao_id', 'canal', 'destinatario_id', 'resposta_sugerida')}
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def autorizar_transporte(destinatario, texto):
    ctx = _contexto.get()
    if not ctx or ctx['consumida'] or ctx['destinatario'] != destinatario or ctx['texto'] != texto:
        raise PermissionError('whatsapp_aprovacao_humana_obrigatoria')
    # Revalida pausas e janela novamente imediatamente antes do transporte.
    ctx['revalidar']()
    ctx['consumida'] = True
    return ctx['phone_number_id']


def _auditar(cur, resposta_id, evento, dados=None):
    cur.execute('INSERT INTO whatsapp_auditoria(resposta_id,evento,dados) VALUES(%s,%s,%s)',
                (resposta_id, evento, Json(dados or {})))


def decidir(factory, resposta_id, aprovar, texto=None):
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM fila_respostas_omnichannel WHERE id=%s FOR UPDATE', (resposta_id,))
                fila = cur.fetchone()
                if not fila or fila['canal'] != 'whatsapp' or fila['status'] != 'aguardando_aprovacao':
                    return {'success': False, 'erro': 'whatsapp_estado_invalido'}
                fila = dict(fila)
                if texto is not None:
                    if not isinstance(texto, str) or not texto.strip() or len(texto) > 4096:
                        return {'success': False, 'erro': 'whatsapp_texto_invalido'}
                    fila['resposta_sugerida'] = texto.strip()
                estado = 'aprovada' if aprovar else 'rejeitada'
                cur.execute('''UPDATE fila_respostas_omnichannel SET status=%s,resposta_sugerida=%s,
                    whatsapp_digest_aprovado=%s,aprovado_por='direcao',aprovado_em=NOW(),atualizado_em=NOW()
                    WHERE id=%s''', (estado, fila['resposta_sugerida'], digest(fila) if aprovar else None, resposta_id))
                _auditar(cur, resposta_id, estado)
                return {'success': True, 'status': estado, 'enviado': False}
    finally:
        conn.close()


def revalidar(factory, fila):
    from email_seguranca import _bloqueio_contexto
    if _bloqueio_contexto.get():
        raise PermissionError('whatsapp_entrada_sem_transporte')
    for nome in ('EMAIL_ENVIOS_PAUSADOS', 'WHATSAPP_ENVIOS_PAUSADOS'):
        if os.getenv(nome, 'false').lower() not in ('false', '0', 'no'):
            raise PermissionError('whatsapp_envios_pausados')
    if not os.getenv('WHATSAPP_ACCESS_TOKEN') or not os.getenv('WHATSAPP_PHONE_NUMBER_ID'):
        raise PermissionError('whatsapp_configuracao_meta_ausente')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Preserva a pausa empresarial P0; ausência de estado falha fechado.
                cur.execute('SELECT pausado FROM email_controle_p0 WHERE id=1')
                pausa = cur.fetchone()
                if not pausa or pausa['pausado']:
                    raise PermissionError('whatsapp_pausa_empresarial')
                cur.execute('SELECT * FROM interacoes_omnichannel WHERE id=%s', (fila['interacao_id'],))
                origem = cur.fetchone()
                if (not origem or origem['canal'] != 'whatsapp' or origem.get('arquivado')
                        or origem['sender_id'] != fila['destinatario_id']):
                    raise PermissionError('whatsapp_origem_invalida')
                phone = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
                if origem['recipient_id'] != phone:
                    raise PermissionError('whatsapp_numero_alterado')
                cur.execute('''SELECT dados FROM whatsapp_eventos WHERE message_id=%s
                    AND tipo_evento='mensagem' AND concluido=TRUE''', (origem['message_id'],))
                evento = cur.fetchone()
                try:
                    raw_timestamp = evento['dados']['metadados']['timestamp']
                    instante = datetime.fromtimestamp(int(raw_timestamp), timezone.utc)
                    idade = (datetime.now(timezone.utc) - instante).total_seconds()
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    raise PermissionError('whatsapp_janela_nao_comprovada') from None
                if not 0 <= idade < 24 * 3600:
                    raise PermissionError('whatsapp_janela_expirada_requer_template')
                return phone
    finally:
        conn.close()


def executar(factory, resposta_id):
    from whatsapp_meta import enviar_texto
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM fila_respostas_omnichannel WHERE id=%s FOR UPDATE', (resposta_id,))
                row = cur.fetchone()
                if not row or row['canal'] != 'whatsapp' or row['status'] != 'aprovada':
                    return {'success': False, 'erro': 'whatsapp_nao_aprovada_ou_ja_executada'}
                fila = dict(row)
                if not fila.get('whatsapp_digest_aprovado') or digest(fila) != fila['whatsapp_digest_aprovado']:
                    return {'success': False, 'erro': 'whatsapp_conteudo_nao_aprovado'}
                try:
                    phone = revalidar(factory, fila)
                except PermissionError as erro:
                    _auditar(cur, resposta_id, 'bloqueada', {'motivo': str(erro)})
                    return {'success': False, 'erro': str(erro), 'bloqueado': True}
                cur.execute("UPDATE fila_respostas_omnichannel SET status='enviando',atualizado_em=NOW() WHERE id=%s", (resposta_id,))
                _auditar(cur, resposta_id, 'enviando')
    finally:
        conn.close()
    # Reivindicação confirmada antes da rede: crash/timeout nunca libera retry.
    token = _contexto.set({'destinatario': fila['destinatario_id'], 'texto': fila['resposta_sugerida'],
                          'phone_number_id': phone, 'consumida': False,
                          'revalidar': lambda: revalidar(factory, fila)})
    try:
        resultado = enviar_texto(fila['destinatario_id'], fila['resposta_sugerida'])
    except Exception:
        resultado = {'success': False, 'incerto': True, 'erro': 'whatsapp_resultado_incerto'}
    finally:
        _contexto.reset(token)
    estado = 'enviada' if resultado.get('success') else ('incerta' if resultado.get('incerto') else 'bloqueada')
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute('''UPDATE fila_respostas_omnichannel SET status=%s,whatsapp_message_id=%s,
                    erro_envio=%s,enviado_em=CASE WHEN %s='enviada' THEN NOW() ELSE enviado_em END,
                    atualizado_em=NOW() WHERE id=%s''',
                    (estado, resultado.get('message_id'), resultado.get('erro'), estado, resposta_id))
                _auditar(cur, resposta_id, estado, resultado)
    finally:
        conn.close()
    return dict(resultado, status=estado)


def listar_status(factory, resposta_id):
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('''SELECT f.id,f.status,f.whatsapp_message_id,e.dados AS evento
                    FROM fila_respostas_omnichannel f LEFT JOIN whatsapp_eventos e
                    ON e.message_id=f.whatsapp_message_id AND e.tipo_evento='status'
                    WHERE f.id=%s AND f.canal='whatsapp' ORDER BY e.recebido_em''', (resposta_id,))
                eventos = [dict(row) for row in cur.fetchall()]
                cur.execute('SELECT evento,dados,criado_em FROM whatsapp_auditoria WHERE resposta_id=%s ORDER BY id', (resposta_id,))
                auditoria = [dict(row) for row in cur.fetchall()]
                return {'success': True, 'eventos': eventos, 'auditoria': auditoria}
    finally:
        conn.close()


def canal_resposta(factory, resposta_id):
    """Roteamento compatível das rotas antigas antes de reservar a execução."""
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute('SELECT canal FROM fila_respostas_omnichannel WHERE id=%s', (resposta_id,))
                row = cur.fetchone()
                return row[0] if row else None
    finally:
        conn.close()


def registrar_rotas(app, factory, validar_admin):
    from flask import jsonify

    @app.get('/api/admin/omnichannel/respostas/<uuid:resposta_id>/whatsapp-status')
    def admin_whatsapp_status(resposta_id):
        if not validar_admin():
            return jsonify(success=False, error='Não autorizado'), 401
        return jsonify(listar_status(factory, str(resposta_id)))
