import ast,hashlib,hmac,json,os,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from flask import Flask,jsonify,request
from whatsapp_sqlite import Banco
import whatsapp_omnichannel as w
import whatsapp_aprovacoes as a
from test_whatsapp_meta import payload

class Integracao(unittest.TestCase):
    def setUp(self):
        self.db=Banco();self.addCleanup(self.db.close)
        for p in (patch.dict(os.environ,{'WHATSAPP_PHONE_NUMBER_ID':'123','WHATSAPP_ACCESS_TOKEN':'fake','META_APP_SECRET':'fake','EMAIL_ENVIOS_PAUSADOS':'true'}),
                  patch('requests.sessions.Session.request',side_effect=AssertionError('rede real proibida'))):
            p.start();self.addCleanup(p.stop)
        self.data=payload([{'id':'wamid.simulado','from':'5598999999999','type':'text','text':{'body':'Gostaria de conhecer uma degustação.'}}])
        self.data['object']='whatsapp_business_account'
        self.data['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']='123'
        self.ia=Mock(return_value={'classificacao':'degustacao','interesse':'degustação','resposta_sugerida':'Olá! Obrigado pelo interesse. Podemos conversar sobre a degustação?'} )
    def receive(self):return w.receber(self.db,self.data,gerar=self.ia)
    def test_payload_crm_interacao_ia_fila_auditoria_aprovacao_sem_envio(self):
        self.assertTrue(self.receive()['success'])
        leads=self.db.rows('leads_crm');inter=self.db.rows('interacoes_omnichannel');fila=self.db.rows('fila_respostas_omnichannel')
        self.assertEqual(len(leads),1);self.assertEqual(inter[0]['lead_id'],leads[0]['id'])
        self.assertEqual(inter[0]['classificacao'],'degustacao');self.assertTrue(inter[0]['processado_ia'])
        self.assertEqual(fila[0]['status'],'aguardando_aprovacao');self.assertEqual(fila[0]['modo_autonomia'],'manual')
        self.assertTrue(a.decidir(self.db,fila[0]['id'],True,'Resposta editada')['success'])
        self.assertTrue(a.executar(self.db,fila[0]['id'])['bloqueado'])
        self.assertEqual(self.db.rows('fila_respostas_omnichannel')[0]['status'],'aprovada')
        self.assertEqual([r['evento'] for r in self.db.rows('whatsapp_auditoria')],['proposta_criada','aprovada','bloqueada'])
        self.assertEqual([r['etapa'] for r in self.db.rows('whatsapp_entrada_auditoria')],['recebido','interacao_registrada','contato_vinculado','classificado','proposta_vinculada','concluido'])
    def test_redelivery_nao_repete_ia_fila_crm_auditoria(self):
        self.receive();before={t:len(self.db.rows(t)) for t in ('leads_crm','interacoes_omnichannel','fila_respostas_omnichannel','whatsapp_entrada_auditoria')}
        self.assertEqual(self.receive()['duplicados'],1);self.ia.assert_called_once()
        self.assertEqual(before,{t:len(self.db.rows(t)) for t in before})
    def test_falha_ia_preserva_entrada_e_retomada(self):
        self.ia.side_effect=RuntimeError('segredo não persistir')
        with self.assertRaises(RuntimeError):self.receive()
        self.assertEqual(len(self.db.rows('interacoes_omnichannel')),1)
        self.assertFalse(self.db.rows('interacoes_omnichannel')[0]['processado_ia'])
        self.assertEqual(self.db.rows('whatsapp_processamentos')[0]['estado'],'falhou')
        self.assertNotIn('segredo',str(self.db.rows('whatsapp_entrada_auditoria')))
        self.ia.side_effect=None;self.receive()
        self.assertEqual(len(self.db.rows('leads_crm')),1);self.assertEqual(len(self.db.rows('fila_respostas_omnichannel')),1)
    def test_falha_fila_reutiliza_checkpoint_ia(self):
        with patch.object(w.Repositorio,'concluir',side_effect=RuntimeError('falha na fila')):
            with self.assertRaises(RuntimeError):self.receive()
        self.receive();self.ia.assert_called_once();self.assertEqual(len(self.db.rows('fila_respostas_omnichannel')),1)
    def test_telefone_formatado_usa_contato_central_sem_inferir_ddd(self):
        conn=self.db();self.addCleanup(conn.close)
        with conn:
            conn.db.execute("INSERT INTO leads_crm(id,nome,tipo_lead,origem,telefone) VALUES('existing','Pessoa','outro','cadastro','+55 (98) 99999-9999')")
        self.receive();self.assertEqual(len(self.db.rows('leads_crm')),1)
        self.assertEqual(self.db.rows('interacoes_omnichannel')[0]['lead_id'],'existing')
    def test_ambiguidade_preserva_entrada_sem_associar_nem_chamar_ia(self):
        conn=self.db();self.addCleanup(conn.close)
        with conn:
            for ident in ('a','b'):conn.db.execute("INSERT INTO leads_crm(id,tipo_lead,origem,telefone) VALUES(?,'outro','cadastro','5598999999999')",(ident,))
        with self.assertRaises(RuntimeError):self.receive()
        self.ia.assert_not_called();self.assertIsNone(self.db.rows('interacoes_omnichannel')[0]['lead_id'])
        self.assertEqual(self.db.rows('whatsapp_processamentos')[0]['estado'],'pendente_identidade')
    def test_status_nao_cria_contato_proposta_ou_classificacao(self):
        value=self.data['entry'][0]['changes'][0]['value'];value['messages']=[];value['statuses']=[{'id':'wamid.out','status':'read'}]
        self.receive();self.ia.assert_not_called()
        self.assertEqual(self.db.rows('leads_crm'),[]);self.assertEqual(self.db.rows('fila_respostas_omnichannel'),[])
    def test_midia_nao_baixada_e_classificacao_falha_fechado(self):
        msg=self.data['entry'][0]['changes'][0]['value']['messages'][0];msg.update(type='audio',audio={'id':'media-sintetica'})
        self.ia.return_value={'classificacao':'inventada','interesse':None,'resposta_sugerida':'x'}
        with self.assertRaises(RuntimeError):self.receive()
        self.assertEqual(self.db.rows('interacoes_omnichannel')[0]['texto'],'[Mensagem WhatsApp: audio]')
        self.assertFalse(self.db.rows('interacoes_omnichannel')[0]['processado_ia'])
    def test_phone_alheio_rejeitado_antes_de_persistir(self):
        self.data['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']='456'
        with self.assertRaises(ValueError):self.receive()
        self.assertEqual(self.db.rows('whatsapp_eventos'),[])
    def test_payload_conflitante_nao_sobrescreve_entrada(self):
        self.receive();self.data['entry'][0]['changes'][0]['value']['messages'][0]['text']['body']='alterado'
        with self.assertRaises(ValueError):self.receive()
        self.assertNotEqual(self.db.rows('interacoes_omnichannel')[0]['texto'],'alterado')
    def test_conector_nunca_libera_com_apenas_credenciais(self):
        self.assertEqual(w.status_conector({})['estado'],'disconnected')
        self.assertEqual(w.status_conector()['estado'],'aguardando_meta');self.assertFalse(w.status_conector()['envio_liberado'])
        self.assertNotIn('fake',str(w.status_conector()))
    def test_webhook_real_assinado_e_painel_autenticado(self):
        app=Flask(__name__);tree=ast.parse(Path('main.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='webhook_meta']
        ns=dict(app=app,os=os,request=request,jsonify=jsonify,get_db_connection=self.db,META_WEBHOOK_VERIFY_TOKEN='verify')
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),ns)
        w.registrar_rotas(app,self.db,lambda:request.headers.get('X-Admin-Key')=='admin-test')
        http=app.test_client();body=json.dumps(self.data).encode();signature='sha256='+hmac.new(b'fake',body,hashlib.sha256).hexdigest()
        real=w.receber
        with patch.object(w,'receber',side_effect=lambda factory,data:real(factory,data,gerar=self.ia)):
            self.assertEqual(http.post('/webhooks/meta',data=body,content_type='application/json').status_code,403)
            r=http.post('/webhooks/meta',data=body,content_type='application/json',headers={'X-Hub-Signature-256':signature})
            self.assertEqual(r.status_code,200);self.assertFalse(r.json['enviado'])
        self.assertEqual(http.get('/api/admin/omnichannel/whatsapp').status_code,401)
        r=http.get('/api/admin/omnichannel/whatsapp',headers={'X-Admin-Key':'admin-test'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['conector']['estado'],'aguardando_meta')
        self.assertEqual(r.json['entradas'][0]['resposta_status'],'aguardando_aprovacao')
        self.assertEqual(http.get('/webhooks/meta?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=challenge').data,b'challenge')

    def test_metadados_originais_preservados_na_retomada(self):
        with patch.object(w.Repositorio,'vincular',side_effect=RuntimeError('falha temporaria')):
            with self.assertRaises(RuntimeError):self.receive()
        self.data['entry'][0]['changes'][0]['value']['contacts'][0]['profile']['name']='Nome alterado na reentrega'
        self.receive()
        self.assertEqual(self.db.rows('leads_crm')[0]['nome'],'Contato teste')

    def test_ids_conflitantes_no_mesmo_lote_rejeitados_antes_do_banco(self):
        msg=self.data['entry'][0]['changes'][0]['value']['messages'][0]
        self.data['entry'][0]['changes'][0]['value']['messages'].append(dict(msg,text={'body':'outro conteúdo'}))
        with self.assertRaises(ValueError):self.receive()
        self.assertEqual(self.db.rows('whatsapp_eventos'),[])

    def test_lock_ocupado_nao_grava_nem_chama_ia(self):
        from unittest.mock import MagicMock
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(False,)
        with self.assertRaises(RuntimeError):w.receber(lambda:conn,self.data,gerar=self.ia)
        self.ia.assert_not_called();conn.close.assert_called_once()
        self.assertEqual(cur.execute.call_count,1)

    def test_auditoria_de_aprovacao_disponivel_no_painel(self):
        self.receive();fila=self.db.rows('fila_respostas_omnichannel')[0]
        a.decidir(self.db,fila['id'],True)
        self.assertIn('aprovada',[row['etapa'] for row in w.painel(self.db)['auditoria_respostas']])

    def test_adaptador_ia_sem_ferramentas_ou_transporte(self):
        event=w.normalizar_eventos(self.data)[0]
        with patch('openai.OpenAI') as client:
            client.return_value.responses.create.return_value.output_text=json.dumps(self.ia.return_value)
            result=w.interpretar_mensagem(event)
            self.assertEqual(result['classificacao'],'degustacao')
            kwargs=client.return_value.responses.create.call_args.kwargs
            self.assertNotIn('tools',kwargs)
            self.assertNotIn(event['sender_id'],kwargs['input'])
            self.assertIn('revisão humana',kwargs['instructions'])

    def test_aguardando_meta_bloqueia_aprovada_mesmo_sem_pausas(self):
        self.receive();fila=self.db.rows('fila_respostas_omnichannel')[0]
        a.decidir(self.db,fila['id'],True)
        with patch.dict(os.environ,{'EMAIL_ENVIOS_PAUSADOS':'false','WHATSAPP_ENVIOS_PAUSADOS':'false'}):
            result=a.executar(self.db,fila['id'])
        self.assertTrue(result['bloqueado']);self.assertEqual(result['erro'],'whatsapp_aguardando_meta')
        self.assertEqual(self.db.rows('fila_respostas_omnichannel')[0]['status'],'aprovada')

if __name__=='__main__':unittest.main()
