import copy
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import whatsapp_aprovacoes as a
import whatsapp_meta as w


class Banco:
    def __init__(self):
        self.fila = dict(id='f', interacao_id='i', canal='whatsapp', destinatario_id='5598999999999',
                         resposta_sugerida='Olá', status='aguardando_aprovacao')
        self.origem = dict(canal='whatsapp', sender_id='5598999999999', recipient_id='123', message_id='wamid.in')
        self.pausado = False; self.timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        self.auditoria = []
    def __call__(self): return Conexao(self)


class Conexao:
    def __init__(self, b): self.b=b
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self, **kwargs): return Cursor(self.b)
    def close(self): pass


class Cursor:
    def __init__(self, b): self.b=b; self.result=None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()):
        if sql.startswith('SELECT * FROM fila'): self.result=copy.deepcopy(self.b.fila)
        elif sql.startswith('SELECT pausado'): self.result={'pausado': self.b.pausado}
        elif sql.startswith('SELECT * FROM interacoes'): self.result=self.b.origem
        elif sql.startswith('SELECT dados FROM whatsapp'): self.result={'dados': {'metadados': {'timestamp': self.b.timestamp}}}
        elif 'whatsapp_digest_aprovado=%s' in sql:
            self.b.fila.update(status=args[0], resposta_sugerida=args[1], whatsapp_digest_aprovado=args[2])
        elif "SET status='enviando'" in sql: self.b.fila['status']='enviando'
        elif 'whatsapp_message_id=%s' in sql: self.b.fila.update(status=args[0], whatsapp_message_id=args[1])
        elif sql.startswith('INSERT INTO whatsapp_auditoria'): self.b.auditoria.append(args[1])
        else: raise AssertionError(sql)
    def fetchone(self): return self.result


class Aprovacoes(unittest.TestCase):
    def setUp(self):
        self.b = Banco()
        # Estado futuro validado apenas no cenário unitário; rede é sempre simulada.
        gate=patch('whatsapp_omnichannel.status_conector',return_value={'envio_liberado':True})
        gate.start();self.addCleanup(gate.stop)
        patcher=patch.dict(os.environ, {'WHATSAPP_ACCESS_TOKEN':'fake-secret', 'WHATSAPP_PHONE_NUMBER_ID':'123',
                                      'EMAIL_ENVIOS_PAUSADOS':'false', 'WHATSAPP_ENVIOS_PAUSADOS':'false'})
        patcher.start(); self.addCleanup(patcher.stop)
        rede=patch('requests.sessions.Session.request', side_effect=AssertionError('rede proibida'))
        rede.start(); self.addCleanup(rede.stop)

    def aprovar(self): self.assertTrue(a.decidir(self.b, 'f', True)['success'])

    def test_aprovar_nao_envia_e_vincula_texto_editado(self):
        with patch('requests.post') as send:
            self.assertTrue(a.decidir(self.b, 'f', True, 'Texto aprovado')['success'])
            send.assert_not_called()
        self.assertEqual(a.digest(self.b.fila), self.b.fila['whatsapp_digest_aprovado'])

    def test_sem_aprovacao_rejeitada_ou_conteudo_alterado_bloqueia(self):
        for estado in ('aguardando_aprovacao','rejeitada','enviada','enviando','incerta'):
            self.b.fila['status']=estado
            with patch('requests.post') as send:
                self.assertFalse(a.executar(self.b,'f')['success']); send.assert_not_called()
        self.b.fila['status']='aguardando_aprovacao'; self.aprovar()
        self.b.fila['resposta_sugerida']='alterada'
        with patch('requests.post') as send:
            self.assertFalse(a.executar(self.b,'f')['success']); send.assert_not_called()

    def test_envio_aprovado_uma_vez_e_auditoria(self):
        self.aprovar()
        response=Mock(status_code=200); response.json.return_value={'messages':[{'id':'wamid.out'}]}
        def resposta(*args, **kwargs):
            self.assertEqual(self.b.fila['status'],'enviando')
            return response
        with patch('requests.post', side_effect=resposta) as send:
            self.assertTrue(a.executar(self.b,'f')['success'])
            self.assertFalse(a.executar(self.b,'f')['success'])
            send.assert_called_once()
        self.assertEqual(self.b.fila['whatsapp_message_id'],'wamid.out')
        self.assertEqual(self.b.auditoria,['aprovada','enviando','enviada'])

    def test_pausa_janela_e_origem_revalidadas(self):
        self.aprovar()
        self.b.pausado=True
        with patch('requests.post') as send:
            self.assertTrue(a.executar(self.b,'f')['bloqueado'])
            self.b.pausado=False; self.b.timestamp='1'
            self.assertTrue(a.executar(self.b,'f')['bloqueado'])
            self.b.timestamp=str(int(datetime.now(timezone.utc).timestamp()))
            self.b.origem['sender_id']='outro'
            self.assertTrue(a.executar(self.b,'f')['bloqueado']); send.assert_not_called()

    def test_timeout_e_sucesso_sem_id_sao_incertos_sem_retry(self):
        for result in (TimeoutError('fake-secret'), Mock(status_code=200)):
            self.b=Banco(); self.aprovar()
            if isinstance(result,Mock): result.json.return_value={}
            with patch('requests.post', side_effect=result if isinstance(result,Exception) else None,
                       return_value=result) as send:
                out=a.executar(self.b,'f')
                self.assertEqual(out['status'],'incerta')
                self.assertNotIn('fake-secret',str(out))
                self.assertFalse(a.executar(self.b,'f')['success']); send.assert_called_once()

    def test_contexto_uso_unico_conteudo_exato(self):
        ctx={'destinatario':'5598999999999','texto':'Olá','phone_number_id':'123',
             'consumida':False,'revalidar':Mock()}
        token=a._contexto.set(ctx)
        try:
            with self.assertRaises(PermissionError): a.autorizar_transporte('outro','Olá')
            self.assertEqual(a.autorizar_transporte('5598999999999','Olá'),'123')
            with self.assertRaises(PermissionError): a.autorizar_transporte('5598999999999','Olá')
        finally: a._contexto.reset(token)

    def test_entrada_bloqueia_mesmo_com_aprovacao(self):
        from entrada_segura import interpretar_sem_saida
        self.aprovar()
        with patch('requests.post') as send:
            out=interpretar_sem_saida(lambda _: a.executar(self.b,'f'),{})
            self.assertTrue(out['bloqueado']); send.assert_not_called()


if __name__ == '__main__': unittest.main()
