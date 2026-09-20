"""Regressões PostgreSQL 18 isolado. Nunca usa DATABASE_URL nem transporte.
P5X_POSTGRES_LOCAL=1 PYTHONPATH=tests:. python3 -m pytest tests/test_whatsapp_postgres_real.py
"""
import os
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock, patch
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from flask import Flask,request
from tests.test_p5x_postgres_real import local_connection
from tests.test_whatsapp_ponta_a_ponta import payload,mensagem,TELEFONE,PHONE_ID,IA_COMERCIAL
import whatsapp_omnichannel as w

@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL')=='1','requer PostgreSQL temporário local')
class WhatsAppPostgres(unittest.TestCase):
    def setUp(self):
        self.schema='wa_regressao_'+uuid4().hex
        self.connections=[]
        conn=local_connection()
        with conn:
            with conn.cursor() as cur:cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        conn.close()
        self.run_sql('''CREATE TABLE leads_crm(id UUID PRIMARY KEY,nome TEXT,tipo_lead TEXT,origem TEXT,canal TEXT,telefone TEXT,contato TEXT,categoria_contato TEXT,arquivado BOOLEAN DEFAULT FALSE,contato_interno BOOLEAN DEFAULT FALSE,cadastro_teste BOOLEAN DEFAULT FALSE);
        CREATE TABLE interacoes_omnichannel(id UUID PRIMARY KEY,canal TEXT,plataforma TEXT,sender_id TEXT,recipient_id TEXT,message_id TEXT UNIQUE,texto TEXT,tipo_interacao TEXT,classificacao TEXT,interesse TEXT,lead_id UUID REFERENCES leads_crm(id),processado_ia BOOLEAN DEFAULT FALSE,atualizado_em TIMESTAMPTZ DEFAULT NOW());
        CREATE TABLE fila_respostas_omnichannel(id UUID PRIMARY KEY,interacao_id UUID REFERENCES interacoes_omnichannel(id),canal TEXT,destinatario_id TEXT,resposta_sugerida TEXT,status TEXT,modo_autonomia TEXT,criado_em TIMESTAMPTZ DEFAULT NOW());''')
        self.apply(2,6)
        self.ia=Mock(return_value=IA_COMERCIAL)
        self.env=patch.dict(os.environ,{'WHATSAPP_PHONE_NUMBER_ID':PHONE_ID});self.env.start();self.addCleanup(self.env.stop)
        network=patch('requests.sessions.Session.request',side_effect=AssertionError('transporte proibido'));network.start();self.addCleanup(network.stop)
    def factory(self):
        conn=local_connection(self.schema);self.connections.append(conn);return conn
    def run_sql(self,query,args=()):
        conn=self.factory()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query,args)
                    rows=cur.fetchall() if cur.description else []
            self.assertEqual(conn.get_transaction_status(),TRANSACTION_STATUS_IDLE)
            return rows
        finally:conn.close()
    def apply(self,*numbers):
        for n in numbers:self.run_sql(next(Path('migrations').glob(f'{n:03d}_*.sql')).read_text())
    def receive(self,p=None):return w.receber(self.factory,p or payload(mensagens=mensagem()),gerar=self.ia)
    def status(self):return payload(statuses=[{'id':'wamid.saida','status':'delivered'}])
    def test_sem_027_preserva_vinculo_auditoria_proposta_e_transacao_utilizavel(self):
        self.assertIsNone(self.run_sql("SELECT to_regclass('crm_identidades_canal') AS tabela")[0]['tabela'])
        self.assertEqual(self.receive()['processados'],1)
        row=self.run_sql('SELECT i.lead_id,l.id FROM interacoes_omnichannel i JOIN leads_crm l ON l.id=i.lead_id')[0]
        self.assertEqual(row['lead_id'],row['id'])
        self.assertEqual(self.run_sql('SELECT status FROM fila_respostas_omnichannel')[0]['status'],'aguardando_aprovacao')
        etapas=[r['etapa'] for r in self.run_sql('SELECT etapa FROM whatsapp_entrada_auditoria')]
        for etapa in ('recebido','identidade_nao_registrada','contato_vinculado','concluido'):self.assertIn(etapa,etapas)
        self.assertTrue(self.run_sql('SELECT concluido FROM whatsapp_eventos')[0]['concluido'])
        self.assertEqual(self.receive()['duplicados'],1);self.ia.assert_called_once()
        self.assertTrue(all(c.closed for c in self.connections))
    def test_conflito_real_nao_e_mascarado_como_migration_ausente(self):
        self.apply(27)
        origem,outro=str(uuid4()),str(uuid4())
        self.run_sql('INSERT INTO leads_crm(id,telefone) VALUES(%s,%s),(%s,NULL)',(origem,TELEFONE,outro))
        self.run_sql("INSERT INTO crm_identidades_canal(id,lead_id,canal,identificador_externo,tipo) VALUES(%s,%s,'whatsapp',%s,'telefone')",(str(uuid4()),outro,TELEFONE))
        with self.assertRaises(RuntimeError):self.receive()
        self.ia.assert_not_called()
        self.assertIsNone(self.run_sql('SELECT lead_id FROM interacoes_omnichannel')[0]['lead_id'])
        self.assertEqual(self.run_sql('SELECT estado FROM whatsapp_processamentos')[0]['estado'],'pendente_identidade')
        self.assertEqual(self.run_sql("SELECT count(*) AS n FROM whatsapp_entrada_auditoria WHERE etapa='identidade_nao_registrada'")[0]['n'],0)
    def test_status_sem_026_tem_ack_duravel_e_recupera_apos_migration(self):
        self.assertEqual(self.receive(self.status())['pendentes'],1)
        for _ in range(3):self.assertEqual(self.receive(self.status())['pendentes'],1)
        self.assertFalse(self.run_sql('SELECT concluido FROM whatsapp_eventos')[0]['concluido'])
        self.assertEqual(self.run_sql('SELECT tentativas FROM whatsapp_processamentos')[0]['tentativas'],1)
        self.apply(26)
        self.assertEqual(w.reprocessar_status(self.factory)['processados'],1)
        self.assertEqual(self.run_sql('SELECT estado FROM whatsapp_status_mensagem')[0]['estado'],'delivered')
        self.assertTrue(self.run_sql('SELECT concluido FROM whatsapp_eventos')[0]['concluido'])
        self.assertEqual(w.reprocessar_status(self.factory)['processados'],0);self.ia.assert_not_called()
    def test_limite_de_tentativas_fica_visivel_sem_laco(self):
        self.receive(self.status())
        for _ in range(10):w.reprocessar_status(self.factory)
        row=self.run_sql('SELECT estado,tentativas FROM whatsapp_processamentos')[0]
        self.assertEqual(row['estado'],'status_revisao');self.assertEqual(row['tentativas'],5)
        self.assertFalse(self.run_sql('SELECT concluido FROM whatsapp_eventos')[0]['concluido'])
    def test_falha_ao_persistir_pendencia_nao_confirma_evento(self):
        with patch.object(w.Repositorio,'status_nao_registrado',side_effect=RuntimeError('auditoria indisponível')):
            with self.assertRaises(RuntimeError):self.receive(self.status())
        self.assertFalse(self.run_sql('SELECT concluido FROM whatsapp_eventos')[0]['concluido'])
    def test_migrations_025_027_idempotentes_e_catalogo(self):
        self.apply(25,26,27);self.apply(25,26,27)
        names={r['tablename'] for r in self.run_sql('SELECT tablename FROM pg_tables WHERE schemaname=%s',(self.schema,))}
        self.assertTrue({'canais_diagnostico_historico','whatsapp_status_mensagem','crm_identidades_canal','crm_fusao_auditoria'}<=names)
        indexes={r['indexname'] for r in self.run_sql('SELECT indexname FROM pg_indexes WHERE schemaname=%s',(self.schema,))}
        self.assertTrue({'crm_identidades_canal_unica','leads_crm_fundido_idx','whatsapp_status_mensagem_falhas_idx','canais_diagnostico_historico_canal_idx'}<=indexes)
        columns={r['column_name'] for r in self.run_sql("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='leads_crm'",(self.schema,))}
        self.assertTrue({'fundido_em_lead_id','fundido_em','fundido_por'}<=columns)
    def test_recuperacao_exige_auth_e_limite_sem_ia_ou_envio(self):
        app=Flask(__name__);w.registrar_rotas(app,self.factory,lambda:request.headers.get('X-Admin-Key')=='teste')
        client=app.test_client();url='/api/admin/omnichannel/whatsapp/reprocessar-status'
        self.assertEqual(client.post(url).status_code,401)
        self.assertEqual(client.post(url,headers={'X-Admin-Key':'teste'},json={'limite':51}).status_code,400)
        self.assertEqual(client.post(url,headers={'X-Admin-Key':'teste'},json={'limite':1}).status_code,200)
        self.ia.assert_not_called()
    def test_recupera_conclusao_legada_apos_falha_de_status(self):
        self.receive(self.status())
        self.run_sql('UPDATE whatsapp_eventos SET concluido=TRUE,concluido_em=NOW()')
        self.run_sql("UPDATE whatsapp_processamentos SET estado='concluido'")
        self.apply(26)
        self.assertEqual(w.reprocessar_status(self.factory)['processados'],1)
        self.assertEqual(w.reprocessar_status(self.factory)['processados'],0)
        self.assertEqual(self.run_sql("SELECT count(*) AS n FROM whatsapp_entrada_auditoria WHERE etapa='status_reaberto'")[0]['n'],1)
    def test_erro_sql_distinto_nao_e_tolerado(self):
        self.apply(27)
        self.run_sql('ALTER TABLE crm_identidades_canal RENAME COLUMN identificador_externo TO coluna_incompativel')
        with self.assertRaises(RuntimeError):self.receive()
        self.ia.assert_not_called()
        self.assertIsNone(self.run_sql('SELECT lead_id FROM interacoes_omnichannel')[0]['lead_id'])
        self.assertEqual(self.run_sql('SELECT erro_tipo FROM whatsapp_processamentos')[0]['erro_tipo'],'UndefinedColumn')
    def test_status_fora_de_ordem_e_concorrente_preserva_read(self):
        from concurrent.futures import ThreadPoolExecutor
        self.apply(26)
        def delivery(status):return self.receive(payload(statuses=[{'id':'wamid.concurrent','status':status}]))
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(delivery,['sent','read','delivered']))
        self.assertTrue(all(r['success'] for r in results))
        self.assertEqual(self.run_sql('SELECT estado FROM whatsapp_status_mensagem')[0]['estado'],'read')
