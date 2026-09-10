import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from uuid import uuid4
from inteligencia_territorial import agregar
from territorio_api import validar_registro, registrar_fato, registrar_rotas, contexto_ia, validar_interpretacao, interpretar

class TerritorioAPITest(unittest.TestCase):
    def body(self,**kw):return dict(chave=str(uuid4()),tipo_registro='circulacao',origem='registro operacional',responsavel='Direção',**kw)
    def test_unknown_and_zero_are_distinct(self):
        _,d,_=validar_registro(self.body(metricas={'conversoes':0}))
        self.assertIsNone(d['cidade']);self.assertIsNone(d['ocorrido_em']);self.assertIsNone(d['quantidade'])
        self.assertEqual(d['metricas'],{'conversoes':0})
    def test_rejects_execution_unknown_fields_and_invalid_counts(self):
        for extra in ({'enviar':True},{'uf':'XX'},{'quantidade':1},{'quantidade':float('nan')},
                      {'metricas':{'respostas':3,'contatos_realizados':2}}, {'metricas':{'cliques':True}},
                      {'metricas':{'custo_centavos':-1}},{'ocorrido_em':'amanhã'}):
            with self.subTest(extra=extra),self.assertRaises((ValueError,TypeError)):validar_registro(self.body(**extra))
    def test_idempotency_and_conflict(self):
        body=self.body();_,_,digest=validar_registro(body)
        for first,stored,status in (({'id':'same'},digest,201),(None,digest,200),(None,'different',409)):
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
            cur.fetchone.side_effect=[first,{'id':'same','payload_hash':stored}]
            response,code=registrar_fato(lambda:conn,body)
            self.assertEqual(code,status)
            self.assertIn('ON CONFLICT(chave) DO NOTHING',cur.execute.call_args_list[0].args[0])
            self.assertEqual(cur.execute.call_count,2);conn.close.assert_called_once()
    def test_auth_all_routes_before_database(self):
        app=Flask(__name__);factory=MagicMock(side_effect=AssertionError('no DB'))
        registrar_rotas(app,factory,lambda:False)
        client=app.test_client()
        for method,path in ((client.get,''),(client.post,'/registros'),(client.post,'/interpretar')):
            self.assertEqual(method('/api/admin/inteligencia-territorial'+path).status_code,401)
        factory.assert_not_called()
    def test_read_never_calls_ai(self):
        app=Flask(__name__);registrar_rotas(app,lambda:None,lambda:True)
        with patch('territorio_api.carregar',return_value=agregar({})),patch('territorio_api.consultar_leitura',return_value=None),patch('territorio_api.chamar_ia',side_effect=AssertionError('no IA')) as ai:
            self.assertEqual(app.test_client().get('/api/admin/inteligencia-territorial').status_code,200);ai.assert_not_called()
    def report(self):
        return agregar({'profissionais_rede':[{'id':'person','nome':'Private Name','email':'secret@actual.com','cidade':'São Paulo','estado':'SP','cargo_funcao':'bartender'}]})
    def abstain(self):return {k:{'territorio_id':None,'motivos':['insuficiencia']} for k in ('midia','prospeccao','producao_distribuicao','eventos')}
    def test_ai_receives_aggregates_only(self):
        context=str(contexto_ia(self.report()))
        for private in ('Private Name','secret@actual.com','person'):self.assertNotIn(private,context)
    def test_ai_cannot_invent_territory_evidence_or_confidence(self):
        report=self.report();raw=self.abstain();ident=report['decisoes']['prospeccao']['territorio_id']
        for choice in ({'territorio_id':'invented','motivos':['perfis']},
                       {'territorio_id':ident,'motivos':['conversao']},
                       {'territorio_id':ident,'motivos':['perfis'],'classificacao':'evidência suficiente'}):
            raw['prospeccao']=choice
            with self.assertRaises(ValueError):validar_interpretacao(report,raw)
        raw['prospeccao']={'territorio_id':ident,'motivos':['perfis']}
        result=validar_interpretacao(report,raw)
        self.assertEqual(result['prospeccao']['classificacao'],'sinal inicial')
        self.assertTrue(result['prospeccao']['evidencias'])
    def test_same_snapshot_uses_cache_without_ai(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[(True,),({'decisoes':{}},)]
        generate=MagicMock(side_effect=AssertionError('no paid call'))
        result,status=interpretar(lambda:conn,self.report(),generate)
        self.assertEqual(status,200);self.assertTrue(result['cache']);generate.assert_not_called()
    def test_concurrent_interpretation_does_not_call_ai(self):
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
        generate=MagicMock()
        self.assertEqual(interpretar(lambda:conn,self.report(),generate)[1],409);generate.assert_not_called()

if __name__=='__main__':unittest.main()
