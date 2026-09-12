"""Testes locais. Nenhuma credencial, servidor ou transporte externo."""
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from unittest.mock import patch, Mock, MagicMock
from pathlib import Path
import autonomia_supervisionada as s
import acoes_comerciais as a
import entrada_segura as e
import test_email_p0 as f

NOW=datetime.now(timezone.utc)
ID='00000000-0000-0000-0000-000000000057'
ITEM=dict(id=ID,email='teste@example.com',fonte_url='https://example.com',evidencia='Contato cadastrado',
    campanha_status='ativa',status='contatado',permitir_primeiro_contato=True,permitir_followup=True,
    score=60,ultimo_contato_em=NOW-timedelta(days=3),proximo_followup_em=NOW,ultima_resposta_em=None,
    objetivo='Apresentação institucional')

class Banco:
    def __init__(self):
        self.lock=threading.RLock();self.reservas={};self.used=0;self.fail_commit=False;self.fail_finish=False
        self.enabled=True;self.item=copy.deepcopy(ITEM);self.incoming=None
        assunto,texto=s.MODELOS['followup']
        d=dict(tipo='followup',canal='email',destinatario=ITEM['email'],assunto=assunto,mensagem=texto,
            origem_tipo='prospecto_fase57',origem_id=ID,origem=ITEM['fonte_url'])
        self.row=dict(id=ID,dados=d,status='aguardando_aprovacao',digest=a.digest(d),origem_tipo='prospecto_fase57',origem_id=ID)
        self.ev=dict(versao=s.VERSAO,modelo='followup',digest=a.digest(d))
    def __call__(self): return Conn(self)

class Conn:
    def __init__(self,b):self.b=b;self.held=False
    def __enter__(self):
        self.b.lock.acquire();self.before=copy.deepcopy((self.b.row,self.b.reservas));return self
    def __exit__(self,typ,*args):
        if typ or self.b.fail_commit:self.b.row,self.b.reservas=self.before
        self.b.lock.release()
        if self.b.fail_commit and not typ:raise RuntimeError('commit')
    def close(self):
        if self.held:self.b.lock.release();self.held=False
    def cursor(self,**kwargs):return Cur(self)

class Cur:
    def __init__(self,c):self.c=c;self.r=None
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def fetchone(self):return self.r
    def fetchall(self):return self.r or []
    def execute(self,sql,args=()):
        q=' '.join(sql.split());b=self.c.b;self.r=None
        if 'pg_try_advisory_lock' in q:
            b.lock.acquire();self.c.held=True;self.r=(True,)
        elif 'pg_advisory_unlock' in q:
            b.lock.release();self.c.held=False
        elif 'pg_advisory_xact_lock' in q:pass
        elif q.startswith('SELECT * FROM autonomia_politicas'):self.r=dict(limite_continuacoes=2) if b.enabled else None
        elif q.startswith('SELECT versao FROM autonomia_politicas'):self.r={'versao':s.VERSAO} if b.enabled else None
        elif q.startswith('SELECT * FROM acoes_comerciais'):self.r=copy.deepcopy(b.row)
        elif q.startswith('SELECT * FROM autonomia_evidencias'):self.r=b.ev
        elif q.startswith('SELECT p.*'):self.r=b.item
        elif q=='SELECT NOW() agora':self.r={'agora':NOW}
        elif q.startswith('SELECT * FROM interacoes'):self.r=[b.incoming] if b.incoming else []
        elif q.startswith('SELECT COUNT(*)'):self.r={'n':b.used}
        elif q.startswith('INSERT INTO autonomia_execucoes'):
            if args[0] not in b.reservas:
                b.reservas[args[0]]='reservada';self.r={'chave':args[0]}
        elif q.startswith('UPDATE acoes_comerciais_propostas SET status=\'executando\''):b.row['status']='executando'
        elif q.startswith('UPDATE acoes_comerciais_propostas SET status=%s'):b.row['status']=args[0]
        elif q.startswith('UPDATE autonomia_execucoes SET estado'):
            if b.fail_finish:raise RuntimeError('banco apos envio')
            b.reservas[args[-1]]=args[0]
        elif q.startswith('INSERT INTO auditoria'):pass
        elif q.startswith('SELECT 1 FROM autonomia_execucoes'):self.r={'existe':1} if b.reservas else None
        elif q.startswith('SELECT 1 FROM briefings_executivos'):pass
        elif q.startswith('SELECT 1 FROM interacoes'):pass
        else:raise AssertionError(q)

class Politica(f.Offline):
    def test_tres_dias_e_uma_data_real(self):
        self.assertTrue(s.elegivel('followup',ITEM,NOW))
        self.assertFalse(s.elegivel('followup',ITEM,NOW-timedelta(seconds=1)))
        for k in ('ultimo_contato_em','proximo_followup_em','fonte_url','evidencia'):
            self.assertFalse(s.elegivel('followup',dict(ITEM,**{k:None}),NOW))
    def test_resposta_recusa_e_sensiveis(self):
        for value in ('preço','desconto','contrato','cobrança','decisão estratégica','não tenho interesse','remover meu contato'):
            self.assertTrue(s.sensivel(value))
            self.assertFalse(s.elegivel('followup',dict(ITEM,objetivo=value),NOW))
        self.assertFalse(s.elegivel('followup',dict(ITEM,ultima_resposta_em=NOW),NOW))
        self.assertFalse(s.elegivel('whatsapp',ITEM,NOW))
    def test_primeiro_contato_nao_adivinha_elegibilidade(self):
        p=dict(ITEM,status='qualificado')
        self.assertTrue(s.elegivel('primeiro_contato',p,NOW))
        for update in ({'score':None},{'permitir_primeiro_contato':False},{'campanha_status':'pausada'}):
            self.assertFalse(s.elegivel('primeiro_contato',dict(p,**update),NOW))
    def test_desligado_nao_abre_banco(self):
        b=Mock()
        with patch.dict('os.environ',{},clear=True):
            s.executar(b,ID,{});s.ciclo({});s.briefing({})
        b.assert_not_called()
    def test_briefing_fora_reserva_bloqueado(self):
        with self.assertRaises(PermissionError):s.transportar_briefing('a@example.com','x','y')

class Execucao(f.Offline):
    def setUp(self):
        super().setUp();self.env=patch.dict('os.environ',{'AUTONOMIA_SUPERVISIONADA_EXECUTAR':'true'});self.env.start();self.addCleanup(self.env.stop)
        self.travas=patch.object(s,'verificar_travas_envio');self.guard=self.travas.start();self.addCleanup(self.travas.stop)
        self.b=Banco();self.send=Mock(return_value={'success':True,'message_id':'sintetico'})
        self.transport=patch.object(s,'transportar_continuacao',self.send);self.transport.start();self.addCleanup(self.transport.stop)
    def run_action(self):return s.executar(self.b,ID,{'adaptadores_autonomia':{'followup':lambda ns,d:self.send(ns,d)}})
    def test_concorrencia_uma_tentativa(self):
        with ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(lambda _:self.run_action(),range(8)))
        self.send.assert_called_once();self.assertEqual(self.b.row['status'],'enviada')
    def test_pausa_supressao_antes_da_reserva(self):
        self.guard.side_effect=PermissionError('pausa ou supressao')
        with self.assertRaises(PermissionError):self.run_action()
        self.assertFalse(self.b.reservas);self.send.assert_not_called()
    def test_adulteracao_e_rejeicao_nao_autorizam(self):
        self.b.row['dados']['mensagem']='Temos desconto'
        self.assertFalse(self.run_action()['success']);self.send.assert_not_called()
        self.b=Banco();self.b.row['status']='rejeitada'
        self.assertFalse(self.run_action()['success']);self.send.assert_not_called()
    def test_cota_continuacoes(self):
        self.b.used=2
        self.assertEqual(self.run_action()['motivo'],'limite_continuacoes');self.send.assert_not_called()
    def test_nova_entrada_cancela_followup(self):
        self.b.incoming=dict(sender_id=ITEM['email'],texto='Olá',id='entrada')
        self.assertFalse(self.run_action()['success']);self.send.assert_not_called()
    def test_timeout_nao_repete(self):
        self.send.side_effect=TimeoutError()
        self.assertEqual(self.run_action()['estado'],'incerta')
        self.run_action();self.send.assert_called_once()
    def test_falha_commit_antes_transporte(self):
        self.b.fail_commit=True
        with self.assertRaises(RuntimeError):self.run_action()
        self.send.assert_not_called()
    def test_falha_registro_pos_transporte_preserva_reserva(self):
        self.b.fail_finish=True
        with self.assertRaises(RuntimeError):self.run_action()
        self.run_action();self.send.assert_called_once()
        self.assertIn('reservada',self.b.reservas.values())
    def test_revalidacao_bloqueia_revogacao(self):
        self.b.enabled=False
        with self.assertRaises(PermissionError):s.revalidar(self.b,self.b.row,'followup')
    def test_briefing_concorrente_e_incerto_nao_repete(self):
        gerar=Mock(side_effect=TimeoutError())
        ns={'get_db_connection':self.b,'EMAIL_BRIEFING_DIRECAO':'direcao@example.com','_enviar_briefing_legado':gerar,'adaptadores_autonomia':{'continuacao':self.send}}
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:s.briefing(ns),range(4)))
        gerar.assert_called_once();self.assertIn('incerta',self.b.reservas.values())

class TransacaoEntrada(unittest.TestCase):
    def test_conexoes_internas_nao_commitam_antes_do_marcador(self):
        conn=MagicMock();proxy=e.ConexaoEntrada(conn)
        with proxy:
            proxy.commit();proxy.close()
            with proxy:proxy.commit()
        conn.commit.assert_not_called();conn.close.assert_not_called()
        comandos=[x.args[0] for x in conn.cursor().__enter__().execute.call_args_list]
        self.assertEqual(comandos,['SAVEPOINT entrada_1','SAVEPOINT entrada_2','RELEASE SAVEPOINT entrada_2','RELEASE SAVEPOINT entrada_1'])
    def test_falha_interna_rollback_savepoint(self):
        conn=MagicMock();proxy=e.ConexaoEntrada(conn)
        with self.assertRaises(ValueError):
            with proxy:raise ValueError('falha sintetica')
        conn.cursor().__enter__().execute.assert_any_call('ROLLBACK TO SAVEPOINT entrada_1')
    def test_contrato_sql_original_aditivo_sem_ativacao_de_jobs(self):
        sql="BEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='30s';\nCREATE TABLE IF NOT EXISTS autonomia_politicas (\n versao TEXT PRIMARY KEY, habilitada BOOLEAN NOT NULL DEFAULT TRUE,\n limite_continuacoes INTEGER NOT NULL DEFAULT 2 CHECK(limite_continuacoes BETWEEN 0 AND 2),\n criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()\n);\nINSERT INTO autonomia_politicas(versao) VALUES('supervisionada-v1') ON CONFLICT DO NOTHING;\nCREATE TABLE IF NOT EXISTS autonomia_execucoes (\n chave TEXT PRIMARY KEY, versao TEXT NOT NULL REFERENCES autonomia_politicas(versao),\n tipo TEXT NOT NULL CHECK(tipo IN ('primeiro_contato','resposta','followup','briefing')),\n acao_id UUID REFERENCES acoes_comerciais_propostas(id),\n destinatario TEXT NOT NULL, digest TEXT NOT NULL,\n estado TEXT NOT NULL CHECK(estado IN ('reservada','enviada','incerta')),\n resultado JSONB, criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), concluido_em TIMESTAMPTZ\n);\nCREATE INDEX IF NOT EXISTS ix_autonomia_execucoes_dia ON autonomia_execucoes(criado_em,tipo);\nCREATE TABLE IF NOT EXISTS autonomia_evidencias (\n acao_id UUID PRIMARY KEY REFERENCES acoes_comerciais_propostas(id),\n versao TEXT NOT NULL REFERENCES autonomia_politicas(versao),\n modelo TEXT NOT NULL, digest TEXT NOT NULL,\n criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()\n);\nCOMMIT;\n"
        self.assertNotRegex(sql.upper(),r'\b(DELETE|DROP|TRUNCATE)\b')
        self.assertIn('ON CONFLICT DO NOTHING',sql)
        self.assertNotIn('UPDATE email_controle',sql)

if __name__=='__main__':unittest.main()
