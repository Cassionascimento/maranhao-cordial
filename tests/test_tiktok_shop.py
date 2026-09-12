import copy
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from whatsapp_sqlite import Banco
import tiktok_shop as shop


class Shop(unittest.TestCase):
    def setUp(self):
        self.db = Banco()
        self.addCleanup(self.db.close)
        sql = "-- Espelho de leitura. Aditiva/idempotente; não altera pedidos, estoque ou jobs.\nCREATE TABLE IF NOT EXISTS tiktok_shop_registros (\n    loja TEXT NOT NULL,\n    tipo TEXT NOT NULL CHECK (tipo IN ('catalogo','pedido','cliente')),\n    externo_id TEXT NOT NULL,\n    versao BIGINT NOT NULL CHECK (versao >= 0),\n    dados JSONB NOT NULL,\n    origem TEXT NOT NULL,\n    lead_id UUID REFERENCES leads_crm(id),\n    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n    PRIMARY KEY (loja,tipo,externo_id)\n);\nCREATE TABLE IF NOT EXISTS tiktok_shop_historico (\n    id BIGSERIAL PRIMARY KEY,\n    loja TEXT NOT NULL,\n    tipo TEXT NOT NULL,\n    externo_id TEXT NOT NULL,\n    versao BIGINT NOT NULL,\n    dados JSONB NOT NULL,\n    origem TEXT NOT NULL,\n    lead_id UUID REFERENCES leads_crm(id),\n    registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n    UNIQUE (loja,tipo,externo_id,versao)\n);\nCREATE INDEX IF NOT EXISTS tiktok_shop_crm_idx ON tiktok_shop_registros(lead_id);\n".replace('BIGSERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT').replace('DEFAULT NOW()', 'DEFAULT CURRENT_TIMESTAMP')
        with sqlite3.connect(self.db.path) as conn:
            conn.executescript(sql)
            conn.executescript(sql)
        self.payload = {'loja':'shop-real-id','origem':'exportacao identificada', 'registros':[
            {'tipo':'catalogo','externo_id':'p1','versao':1,'dados':{'titulo':'Produto registrado'}},
            {'tipo':'cliente','externo_id':'c1','versao':1,'dados':{'nome':'Cliente simulado'}},
            {'tipo':'pedido','externo_id':'o1','versao':1,'dados':{'cliente_id':'c1','status':'UNPAID'}}]}
        self.net = patch('requests.sessions.Session.request', side_effect=AssertionError('Transporte proibido'))
        self.net.start(); self.addCleanup(self.net.stop)

    def test_importacao_idempotente_historico_sem_venda_inferida(self):
        self.assertEqual(shop.importar(self.db,self.payload)['importados'],3)
        self.assertEqual(shop.importar(self.db,self.payload)['duplicados'],3)
        view = shop.painel(self.db)
        self.assertEqual(len(view['historico']),3)
        self.assertFalse(view['transporte'])
        self.assertNotIn('estoque',view['fatos'][0]['dados'])
        self.assertEqual(self.db.rows('leads_crm'),[])
        self.assertEqual(self.db.rows('fila_respostas_omnichannel'),[])

    def test_versao_antiga_nao_sobrescreve_e_conflito_reverte_lote(self):
        shop.importar(self.db,self.payload)
        other=copy.deepcopy(self.payload)
        other['registros'][0]['versao']=2
        shop.importar(self.db,other)
        self.assertEqual(shop.importar(self.db,self.payload)['antigos'],1)
        conflict=copy.deepcopy(other)
        conflict['registros'][0]['versao']=3
        conflict['registros'][1]['dados']={'nome':'Alterado sem versão'}
        with self.assertRaises(ValueError):shop.importar(self.db,conflict)
        self.assertEqual(len(self.db.rows('tiktok_shop_historico')),4)

    def test_vinculo_explicito_crm_e_lojas_isoladas(self):
        ident='810172a7-74a3-4127-9601-2af3ea837bd2'
        with sqlite3.connect(self.db.path) as conn:
            conn.execute("INSERT INTO leads_crm(id,nome,tipo_lead,origem) VALUES(?,?,?,?)",(ident,'Teste','outro','teste'))
        self.payload['registros'][1]['lead_id']=ident
        shop.importar(self.db,self.payload)
        self.payload['loja']='outra-loja'
        shop.importar(self.db,self.payload)
        self.assertEqual(len(self.db.rows('tiktok_shop_registros')),6)
        self.assertEqual(len(self.db.rows('leads_crm')),1)

    def test_autenticacao_limites_e_dados_ausentes(self):
        app=Flask(__name__)
        shop.registrar_rotas(app,self.db,lambda:False)
        self.assertEqual(app.test_client().post('/api/admin/tiktok-shop/importar',json=self.payload).status_code,401)
        for bad in (None,{},dict(self.payload,registros=self.payload['registros']*40)):
            with self.assertRaises(ValueError):shop.normalizar(bad)
        self.assertNotIn('total',shop.normalizar(self.payload)[2]['dados'])

    def test_contexto_ia_nao_expoe_pii_e_falha_fechada(self):
        shop.importar(self.db,self.payload)
        context=shop.contexto_ia(self.db)
        self.assertIn('UNPAID',context)
        self.assertNotIn('Cliente simulado',context)
        self.assertIn('não inferir',shop.contexto_ia(lambda: (_ for _ in ()).throw(RuntimeError())))


if __name__=='__main__':unittest.main()
