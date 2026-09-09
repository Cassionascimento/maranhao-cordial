"""WhatsApp inteiramente offline: nenhuma credencial ou transporte real."""
import copy
import unittest
from unittest.mock import Mock, patch
import whatsapp_meta as w


def payload(messages=None, statuses=None):
    return {'entry': [{'changes': [{'field': 'messages', 'value': {
        'metadata': {'phone_number_id': 'phone-test'},
        'contacts': [{'wa_id': '5598999999999', 'profile': {'name': 'Contato teste'}}],
        'messages': messages or [], 'statuses': statuses or []}}]}]}


class Banco:
    def __init__(self): self.rows = {}; self.result = None
    def __call__(self): return self
    def __enter__(self): self.snapshot = copy.deepcopy(self.rows); return self
    def __exit__(self, exc, *_):
        if exc: self.rows = self.snapshot
    def cursor(self): return Cursor(self)
    def close(self): pass


class Cursor:
    def __init__(self, banco): self.b = banco
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args):
        if sql.startswith('SELECT pg_advisory'): return
        if sql.startswith('SELECT concluido'):
            self.b.result = (self.b.rows[args[0]],) if args[0] in self.b.rows else None
        elif sql.startswith('INSERT INTO'): self.b.rows.setdefault(args[0], False)
        elif sql.startswith('UPDATE'): self.b.rows[args[0]] = True
        else: raise AssertionError(sql)
    def fetchone(self): return self.b.result


class WhatsApp(unittest.TestCase):
    def setUp(self):
        self.rede = patch('requests.sessions.Session.request', side_effect=AssertionError('rede proibida'))
        self.rede.start(); self.addCleanup(self.rede.stop)
        self.msg = {'id': 'wamid.test', 'from': '5598999999999', 'type': 'text', 'text': {'body': 'Olá'}}

    def test_texto_identidade_e_dedup_lote(self):
        result = w.normalizar_eventos(payload([self.msg, self.msg]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['texto'], 'Olá')
        self.assertEqual(result[0]['metadados']['nome'], 'Contato teste')
        self.assertEqual(result[0]['message_id'], 'wamid.test')

    def test_midia_preserva_metadados_sem_download(self):
        for tipo in w.MEDIA:
            msg = dict(self.msg, type=tipo, **{tipo: {'id': 'media-test', 'mime_type': 'test/type', 'caption': 'Anexo'}})
            event = w.normalizar_eventos(payload([msg]))[0]
            self.assertEqual(event['metadados']['anexo']['id'], 'media-test')
            self.assertEqual(event['texto'], 'Anexo')

    def test_interativo_e_sem_texto(self):
        msg = dict(self.msg, type='interactive', interactive={'button_reply': {'id': 'a', 'title': 'Sim'}})
        self.assertEqual(w.normalizar_eventos(payload([msg]))[0]['texto'], 'Sim')
        msg = dict(self.msg, type='audio', audio={'id': 'a'})
        self.assertEqual(w.normalizar_eventos(payload([msg]))[0]['texto'], '[Mensagem WhatsApp: audio]')

    def test_status_eventos_independentes_e_erro_sem_texto_sensivel(self):
        statuses = [{'id': 'wamid.test', 'status': s, 'errors': [{'code': 131, 'message': 'SEGREDO'}]} for s in w.STATUSES]
        events = w.normalizar_eventos(payload(statuses=statuses + statuses))
        self.assertEqual(len(events), 4)
        self.assertNotIn('SEGREDO', str(events))

    def test_identidade_incompleta_rejeitada(self):
        for key in ('id', 'from'):
            msg = dict(self.msg); msg.pop(key)
            with self.assertRaises(ValueError): w.normalizar_eventos(payload([msg]))
        data = payload([self.msg]); data['entry'][0]['changes'][0]['value']['metadata'] = {}
        with self.assertRaises(ValueError): w.normalizar_eventos(data)

    def test_inbox_crm_proposta_e_retry_idempotente(self):
        banco = Banco(); registrar = Mock(return_value={'success': True, 'interacao': {'id': 'i'}})
        crm = Mock(return_value={'success': True}); proposta = Mock(return_value={'success': True})
        for _ in range(2):
            self.assertTrue(w.receber_eventos(banco, payload([self.msg]), registrar, crm, proposta)['success'])
        registrar.assert_called_once(); crm.assert_called_once(); proposta.assert_called_once()

    def test_falha_proposta_permite_retomada_mesmo_interacao_duplicada(self):
        banco = Banco(); registrar = Mock(return_value={'success': True, 'duplicada': True, 'interacao': {'id': 'i'}})
        crm = Mock(return_value={'success': True}); proposta = Mock(side_effect=[RuntimeError('falha'), {'success': True}])
        with self.assertRaises(RuntimeError): w.receber_eventos(banco, payload([self.msg]), registrar, crm, proposta)
        self.assertFalse(banco.rows)
        self.assertTrue(w.receber_eventos(banco, payload([self.msg]), registrar, crm, proposta)['success'])
        self.assertEqual(proposta.call_count, 2)

    def test_status_nao_chama_ia(self):
        banco = Banco(); registrar = Mock(); crm = Mock(); proposta = Mock()
        w.receber_eventos(banco, payload(statuses=[{'id': 'wamid.test', 'status': 'read'}]), registrar, crm, proposta)
        registrar.assert_not_called(); crm.assert_not_called(); proposta.assert_not_called()

    def test_transporte_direto_bloqueado_inclusive_com_credenciais(self):
        with patch.dict('os.environ', {'WHATSAPP_ACCESS_TOKEN': 'fake', 'WHATSAPP_PHONE_NUMBER_ID': 'fake'}):
            self.assertTrue(w.enviar_texto('5598999999999', 'teste')['bloqueado'])


if __name__ == '__main__': unittest.main()
