"""Cenários offline: banco transacional de ações, transportes/rede proibidos."""
import copy
import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from flask import Flask, request, jsonify
import acoes_comerciais as a
import entrada_segura as entrada
import fase57_prospeccao_universal as fase
import email_seguranca as p0
import test_email_p0 as f

DADOS = dict(destinatario='contato@empresa.com.br', empresa='Empresa', canal='email', objetivo='Parceria',
    origem='https://empresa.com.br/contato', evidencia='Email publicado no site', motivo='Empresa compatível',
    mensagem='Olá, proposta para avaliação.', assunto='Maranhão Cordial', tipo='primeiro_contato',
    origem_tipo='prospecto_fase57', origem_id='00000000-0000-0000-0000-000000000057')

class Banco:
    def __init__(self, estado='aprovada'):
        self.lock=threading.RLock()
        self.row=dict(id='1', origem_tipo=DADOS['origem_tipo'], origem_id=DADOS['origem_id'], dados=copy.deepcopy(DADOS),digest=a.digest(DADOS),
                      digest_aprovado=a.digest(DADOS), status=estado)
        self.eventos=[]
    def __call__(self): return Conn(self)

class Conn:
    def __init__(self,b): self.b=b
    def __enter__(self): self.b.lock.acquire(); return self
    def __exit__(self,*args): self.b.lock.release()
    def cursor(self,**kwargs): return Cur(self.b)
    def close(self): pass

class Cur:
    def __init__(self,b): self.b=b; self.result=None
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,args=()):
        self.result=None
        if sql.startswith('SELECT *'): self.result=copy.deepcopy(self.b.row)
        elif sql in a.ORIGENS.values(): self.result={'id':args[0]}
        elif "SET status='executando'" in sql: self.b.row['status']='executando'
        elif 'decidido_em=NOW()' in sql:
            if self.b.row['status']=='aguardando_aprovacao' and self.b.row['digest']==args[-1]:
                self.b.row.update(status=args[0],digest_aprovado=args[2]);self.result=('1',)
        elif 'SET status=%s,resultado' in sql: self.b.row.update(status=args[0],resultado=args[1].adapted)
        elif 'INSERT INTO auditoria' in sql: self.b.eventos.append(args)
        else: raise AssertionError(sql)
    def fetchone(self): return self.result

class Acoes(f.Offline):
    def test_sem_aprovacao_e_rejeitada_nao_executam(self):
        for estado in ('aguardando_aprovacao','rejeitada','executando','incerta','enviada','bloqueada'):
            envio=Mock()
            self.assertFalse(a.executar(Banco(estado),'1',envio)['success'])
            envio.assert_not_called()

    def test_decisao_nao_envia_e_exige_digest_atual(self):
        b=Banco('aguardando_aprovacao')
        self.assertFalse(a.decidir(b,'1','alterado',True)['success'])
        self.assertTrue(a.decidir(b,'1',b.row['digest'],True)['success'])
        self.assertEqual(b.row['status'],'aprovada')
        self.assertFalse(a.decidir(b,'1',b.row['digest'],False)['success'])

    def test_conteudo_adulterado_bloqueado(self):
        b=Banco();b.row['dados']['mensagem']='outra'
        send=Mock(); self.assertFalse(a.executar(b,'1',send)['success']);send.assert_not_called()

    def test_aprovada_contexto_exato_e_consumo_unico(self):
        b=Banco()
        def send(_):
            self.assertEqual(b.row['status'],'executando')
            with self.assertRaises(PermissionError): a.autorizar_transporte('outro@empresa.com.br',DADOS['assunto'],DADOS['mensagem'])
            with self.assertRaises(PermissionError): a.autorizar_transporte(DADOS['destinatario'],'outro',DADOS['mensagem'])
            a.autorizar_transporte(DADOS['destinatario'],DADOS['assunto'],DADOS['mensagem'])
            with self.assertRaises(PermissionError): a.autorizar_transporte(DADOS['destinatario'],DADOS['assunto'],DADOS['mensagem'])
            return {'success':True,'message_id':'gmail-mock'}
        self.assertTrue(a.executar(b,'1',send)['success'])
        with self.assertRaises(PermissionError): a.conteudo_aprovado()

    def test_concorrencia_uma_execucao(self):
        b=Banco();send=Mock(return_value={'success':True,'message_id':'gmail-mock'})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: a.executar(b,'1',send),range(12)))
        send.assert_called_once()

    def test_incerto_nunca_reenvia(self):
        b=Banco();send=Mock(side_effect=TimeoutError)
        self.assertEqual(a.executar(b,'1',send)['status'],'incerta')
        self.assertFalse(a.executar(b,'1',send)['success']);send.assert_called_once()

    def test_pesquisa_prepara_sem_reserva_ou_envio(self):
        item=dict(DADOS,id='p1',email=DADOS['destinatario'],fonte_url=DADOS['origem'])
        with patch.object(fase,'_campanha_e_prospecto',return_value=item),patch('prospeccao_fonte_publica.validar_associacao',return_value=(True,'fonte')),patch.object(fase,'gerar_primeiro_contato_fase57',return_value='Olá.'),patch.object(fase,'validar_mensagem_fase57'),patch.object(fase,'propor_mensagem_fase57',return_value={'success':True,'enviado':False}) as proposta,patch.object(fase,'_transportar_primeiro_contato_aprovado') as envio:
            self.assertFalse(fase.enviar_primeiro_contato_fase57({},'p1')['enviado'])
        proposta.assert_called_once();envio.assert_not_called()

    def test_sem_email_e_sem_fonte_nao_reservam(self):
        for item in ({'id':'p'}, {'id':'p','email':'a@empresa.com.br','fonte_url':'https://empresa.com.br'}):
            with patch.object(fase,'_campanha_e_prospecto',return_value=item),patch('prospeccao_fonte_publica.validar_associacao',return_value=(False,'fonte')),patch.object(fase,'propor_mensagem_fase57') as proposta:
                self.assertFalse(fase.enviar_primeiro_contato_fase57({},'p')['enviado'])
                proposta.assert_not_called()

    def test_sync_interpretacao_sem_transporte_mesmo_sem_pausas(self):
        def processar(_):
            with self.assertRaises(p0.EnvioBloqueado): p0.verificar_envio(self.banco,'a@empresa.com.br')
            return {'success':True}
        self.assertTrue(entrada.interpretar_sem_saida(processar,{'id':'entrada'})['success'])

    def test_executor_sem_aprovacao_nao_chega_a_reserva(self):
        with patch.object(fase,'_transportar_primeiro_contato_aprovado') as envio:
            with self.assertRaises(PermissionError): fase.executar_primeiro_contato_aprovado({},'p')
            envio.assert_not_called()

    def test_rotas_exigem_chave_e_decisao_valida(self):
        app=Flask('acoes-test')
        a.registrar_rotas(app,dict(get_db_connection=Banco(),validar_admin_request=lambda: request.headers.get('X-Admin-Key')=='teste'))
        client=app.test_client()
        self.assertEqual(client.get('/api/admin/acoes-comerciais').status_code,401)
        self.assertEqual(client.post('/api/admin/acoes-comerciais/00000000-0000-0000-0000-000000000001/decisao',headers={'X-Admin-Key':'invalida'},json={}).status_code,401)
        self.assertEqual(client.post('/api/admin/acoes-comerciais/00000000-0000-0000-0000-000000000001/decisao',headers={'X-Admin-Key':'teste'},json={}).status_code,400)

class SinaisMI(f.Offline):
    """ETAPA 4.9: acoes_comerciais -> mi_sinais, sem tocar no comportamento existente.

    propor() é coberto em test_origem_comercial.py (usa Store, que reconhece o
    INSERT em acoes_comerciais_propostas; o Banco daqui não reconhece)."""

    def test_aprovacao_emite_acao_aprovada(self):
        b = Banco('aguardando_aprovacao')
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.decidir(b, '1', b.row['digest'], True)
        self.assertTrue(r['success'])
        emitir.assert_called_once_with(b, natureza='acao', origem='acoes_comerciais',
            tipo_evento='acao_aprovada', origem_id='1', payload={'ator': 'direcao'})

    def test_rejeicao_emite_acao_rejeitada(self):
        b = Banco('aguardando_aprovacao')
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.decidir(b, '1', b.row['digest'], False)
        self.assertTrue(r['success'])
        emitir.assert_called_once_with(b, natureza='acao', origem='acoes_comerciais',
            tipo_evento='acao_rejeitada', origem_id='1', payload={'ator': 'direcao'})

    def test_decisao_recusada_nao_emite_nada(self):
        b = Banco('aguardando_aprovacao')
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.decidir(b, '1', 'digest-errado', True)
        self.assertFalse(r['success'])
        emitir.assert_not_called()

    def test_execucao_enviada_emite_resultado_executada(self):
        b = Banco()
        send = Mock(return_value={'success': True, 'message_id': 'gmail-mock'})
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.executar(b, '1', send)
        self.assertEqual(r['status'], 'enviada')
        emitir.assert_called_once_with(b, natureza='resultado', origem='acoes_comerciais',
            tipo_evento='acao_executada', origem_id='1', resultado='enviada', payload={'tipo': 'primeiro_contato'})

    def test_execucao_incerta_emite_resultado_executada_com_resultado_incerta(self):
        b = Banco()
        send = Mock(side_effect=TimeoutError)
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.executar(b, '1', send)
        self.assertEqual(r['status'], 'incerta')
        emitir.assert_called_once_with(b, natureza='resultado', origem='acoes_comerciais',
            tipo_evento='acao_executada', origem_id='1', resultado='incerta', payload={'tipo': 'primeiro_contato'})

    def test_execucao_sem_aprovacao_nao_emite_nada(self):
        b = Banco('rejeitada')
        with patch('acoes_comerciais.emitir') as emitir:
            a.executar(b, '1', Mock())
        emitir.assert_not_called()

    def test_falha_real_do_registro_de_sinal_nao_derruba_decisao(self):
        """emitir() de verdade (nao mockado): SQL de mi_sinais nao reconhecido
        pelo Banco fake levanta AssertionError, mas isso nunca deveria escapar
        -- e de fato nao escapa, porque emitir() intercepta tudo."""
        b = Banco('aguardando_aprovacao')
        r = a.decidir(b, '1', b.row['digest'], True)
        self.assertTrue(r['success'])


class Meta(f.Offline):
    def test_hmac_corpo_original_e_ausencia(self):
        raw=b'{"object":"instagram"}'
        sig='sha256='+hmac.new(b'sintetico',raw,hashlib.sha256).hexdigest()
        self.assertTrue(entrada.assinatura_meta_valida(raw,sig,'sintetico'))
        for corpo, assinatura, segredo in ((raw+b' ',sig,'sintetico'),(raw,None,'sintetico'),(raw,sig,''),(raw,'sha256=errado','sintetico')):
            self.assertFalse(entrada.assinatura_meta_valida(corpo,assinatura,segredo))

    def test_webhook_rejeita_antes_de_processar_preserva_get(self):
        import os
        app=Flask('meta-test');ns=dict(request=request,jsonify=jsonify,os=os,META_WEBHOOK_VERIFY_TOKEN='verificacao')
        f.carregar_funcoes('main.py',['webhook_meta'],ns)
        app.add_url_rule('/webhooks/meta',view_func=ns['webhook_meta'],methods=['GET','POST'])
        c=app.test_client()
        with patch.dict(os.environ,META_APP_SECRET='sintetico'):
            self.assertEqual(c.post('/webhooks/meta',json={'object':'instagram'}).status_code,403)
            self.assertEqual(c.get('/webhooks/meta?hub.mode=subscribe&hub.verify_token=verificacao&hub.challenge=123').data,b'123')
        with patch.dict(os.environ,META_APP_SECRET=''):
            self.assertEqual(c.post('/webhooks/meta',json={}).status_code,503)
