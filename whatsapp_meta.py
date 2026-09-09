"""WhatsApp: eventos normalizados e transporte fechado até aprovação integrada.

Sem chamadas externas, leitura de credenciais ou efeitos no import.
"""
import os
import re
import requests

MEDIA = {'image', 'audio', 'video', 'document', 'sticker'}
STATUSES = {'sent', 'delivered', 'read', 'failed'}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def normalizar_eventos(payload):
    """Preserva IDs e metadados de mídia; não baixa anexos nem interpreta binários."""
    eventos = []
    for entry in _list(_dict(payload).get('entry')):
        for change in _list(_dict(entry).get('changes')):
            if _dict(change).get('field') != 'messages':
                continue
            value = _dict(change.get('value'))
            phone = str(_dict(value.get('metadata')).get('phone_number_id') or '')
            if not phone:
                raise ValueError('whatsapp_phone_number_id_ausente_no_evento')
            contatos = {_dict(c).get('wa_id'): _dict(_dict(c).get('profile')).get('name')
                        for c in _list(value.get('contacts'))}
            for raw in _list(value.get('messages')):
                msg = _dict(raw)
                mid, sender = msg.get('id'), msg.get('from')
                if not isinstance(mid, str) or not mid or not isinstance(sender, str) or not sender.isdigit():
                    raise ValueError('whatsapp_identidade_ausente_ou_invalida')
                tipo = msg.get('type') or 'unknown'
                body = _dict(msg.get(tipo))
                texto = body.get('body') if tipo == 'text' else None
                if tipo == 'button':
                    texto = body.get('text')
                elif tipo == 'interactive':
                    resposta = _dict(body.get('button_reply') or body.get('list_reply'))
                    texto = resposta.get('title')
                elif tipo in MEDIA:
                    texto = body.get('caption')
                if not isinstance(texto, str) or not texto.strip():
                    texto = '[Mensagem WhatsApp: ' + str(tipo) + ']'
                metadata = {'tipo': tipo, 'timestamp': msg.get('timestamp'),
                            'nome': contatos.get(sender), 'context': _dict(msg.get('context'))}
                if tipo in MEDIA:
                    metadata['anexo'] = {k: body[k] for k in ('id', 'mime_type', 'sha256', 'filename', 'caption', 'voice') if k in body}
                elif tipo in {'location', 'contacts', 'interactive', 'button', 'reaction'}:
                    metadata['conteudo'] = msg.get(tipo)
                eventos.append({'chave': 'mensagem:' + phone + ':' + mid,
                                'tipo_evento': 'mensagem', 'message_id': mid,
                                'sender_id': sender, 'recipient_id': phone,
                                'texto': texto.strip(), 'metadados': metadata})
            for raw in _list(value.get('statuses')):
                status = _dict(raw)
                mid, estado = status.get('id'), status.get('status')
                if not isinstance(mid, str) or not mid or estado not in STATUSES:
                    raise ValueError('whatsapp_status_invalido')
                metadata = {k: status[k] for k in ('timestamp', 'recipient_id', 'conversation', 'pricing') if k in status}
                # Persistência de códigos somente: mensagens externas podem conter dados sensíveis.
                metadata['erros'] = [{'code': _dict(e).get('code')} for e in _list(status.get('errors'))]
                eventos.append({'chave': 'status:' + phone + ':' + mid + ':' + estado,
                                'tipo_evento': 'status', 'message_id': mid,
                                'recipient_id': phone, 'status': estado, 'metadados': metadata})
    # Redelivery e repetições dentro de um lote possuem a mesma identidade.
    return list({e['chave']: e for e in eventos}.values())


def receber_eventos(factory, payload, registrar, processar, sugerir):
    """Inbox durável serializa a entrada e permite retry após falha de interpretação.

    A migration 002_whatsapp_eventos.sql é pré-requisito explícito. Uma exceção
    deve resultar em HTTP 503 para a Meta repetir o evento. CRM e proposta usam
    suas identidades persistentes; nenhuma autorização/transporte é invocada.
    """
    from psycopg2.extras import Json
    from entrada_segura import interpretar_sem_saida
    eventos = normalizar_eventos(payload)
    if not eventos:
        return {'success': True, 'processados': 0, 'enviado': False}
    total = 0
    conn = factory()
    try:
        for evento in eventos:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (evento['chave'],))
                    cur.execute('SELECT concluido FROM whatsapp_eventos WHERE chave=%s', (evento['chave'],))
                    row = cur.fetchone()
                    if row and row[0]:
                        continue
                    cur.execute('''INSERT INTO whatsapp_eventos(chave,message_id,tipo_evento,dados)
                        VALUES(%s,%s,%s,%s) ON CONFLICT(chave) DO NOTHING''',
                        (evento['chave'], evento['message_id'], evento['tipo_evento'], Json(evento)))
                    if evento['tipo_evento'] == 'mensagem':
                        registro = registrar(canal='whatsapp', sender_id=evento['sender_id'],
                                             recipient_id=evento['recipient_id'], message_id=evento['message_id'],
                                             texto=evento['texto'], plataforma='meta', tipo_interacao='mensagem')
                        interacao = registro.get('interacao')
                        if not registro.get('success') or not interacao:
                            raise RuntimeError('whatsapp_registro_nao_confirmado')
                        resultado = interpretar_sem_saida(processar, interacao)
                        if not resultado or resultado.get('success') is False:
                            raise RuntimeError('whatsapp_crm_nao_confirmado')
                        proposta = interpretar_sem_saida(lambda item: sugerir(item, resultado), interacao)
                        if not proposta or proposta.get('success') is False:
                            raise RuntimeError('whatsapp_proposta_nao_confirmada')
                    cur.execute('UPDATE whatsapp_eventos SET concluido=TRUE,concluido_em=NOW() WHERE chave=%s', (evento['chave'],))
                    total += 1
        return {'success': True, 'processados': total, 'enviado': False}
    finally:
        conn.close()


def enviar_texto(destinatario, conteudo):
    """Transporte de uso único, vinculado ao conteúdo aprovado pelo executor."""
    from whatsapp_aprovacoes import autorizar_transporte
    try:
        phone = autorizar_transporte(destinatario, conteudo)
    except PermissionError as erro:
        return {'success': False, 'bloqueado': True, 'erro': str(erro)}
    if (not re.fullmatch(r'[0-9]{7,15}', destinatario or '')
            or not isinstance(conteudo, str) or not conteudo.strip() or len(conteudo) > 4096
            or not re.fullmatch(r'[0-9]+', phone or '')):
        return {'success': False, 'erro': 'whatsapp_payload_invalido'}
    token = os.getenv('WHATSAPP_ACCESS_TOKEN')
    if not token:
        return {'success': False, 'erro': 'whatsapp_token_ausente'}
    try:
        resposta = requests.post('https://graph.facebook.com/v23.0/' + phone + '/messages',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            json={'messaging_product': 'whatsapp', 'recipient_type': 'individual',
                  'to': destinatario, 'type': 'text', 'text': {'preview_url': False, 'body': conteudo}},
            timeout=20, allow_redirects=False)
        try:
            dados = resposta.json()
        except Exception:
            dados = {}
        messages = _list(_dict(dados).get('messages'))
        mid = _dict(messages[0]).get('id') if messages else None
        if 200 <= resposta.status_code < 300 and isinstance(mid, str) and mid:
            return {'success': True, 'message_id': mid, 'status_code': resposta.status_code,
                    'meta': {'messages': [{'id': mid}]}}
        # 5xx e 2xx sem ID não comprovam ausência de envio; jamais retry automático.
        return {'success': False, 'incerto': resposta.status_code >= 500 or 200 <= resposta.status_code < 300,
                'status_code': resposta.status_code, 'erro': 'whatsapp_meta_nao_confirmou_envio',
                'codigo_meta': _dict(_dict(dados).get('error')).get('code')}
    except Exception:
        # Nunca persistir URL, token, corpo HTTP ou exception repr de requests.
        return {'success': False, 'incerto': True, 'erro': 'whatsapp_transporte_incerto'}
