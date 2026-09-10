"""Banco SQL isolado para testar o repositório real, com adaptação explícita de dialeto.
Não valida o catálogo PostgreSQL, suas permissões ou locks concorrentes.
"""
import json,re,sqlite3,tempfile
from pathlib import Path

class Banco:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory();self.path=str(Path(self.temp.name)/'teste.db')
        conn=sqlite3.connect(self.path)
        conn.executescript('''
CREATE TABLE leads_crm(id TEXT PRIMARY KEY,nome TEXT,tipo_lead TEXT NOT NULL,origem TEXT NOT NULL,canal TEXT,telefone TEXT,contato TEXT,categoria_contato TEXT,arquivado BOOLEAN DEFAULT FALSE,contato_interno BOOLEAN DEFAULT FALSE,cadastro_teste BOOLEAN DEFAULT FALSE);
CREATE TABLE interacoes_omnichannel(id TEXT PRIMARY KEY,canal TEXT,plataforma TEXT,sender_id TEXT,recipient_id TEXT,message_id TEXT UNIQUE,texto TEXT,tipo_interacao TEXT,classificacao TEXT,interesse TEXT,lead_id TEXT REFERENCES leads_crm(id),processado_ia BOOLEAN DEFAULT FALSE,arquivado BOOLEAN DEFAULT FALSE,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE fila_respostas_omnichannel(id TEXT PRIMARY KEY,interacao_id TEXT REFERENCES interacoes_omnichannel(id),canal TEXT,destinatario_id TEXT,resposta_sugerida TEXT,status TEXT,modo_autonomia TEXT,whatsapp_digest_aprovado TEXT,whatsapp_message_id TEXT,aprovado_por TEXT,aprovado_em TEXT,enviado_em TEXT,erro_envio TEXT,criado_em TEXT DEFAULT CURRENT_TIMESTAMP,atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE whatsapp_eventos(chave TEXT PRIMARY KEY,message_id TEXT,tipo_evento TEXT,dados TEXT,concluido BOOLEAN DEFAULT FALSE,recebido_em TEXT DEFAULT CURRENT_TIMESTAMP,concluido_em TEXT);
CREATE TABLE whatsapp_auditoria(id INTEGER PRIMARY KEY AUTOINCREMENT,resposta_id TEXT REFERENCES fila_respostas_omnichannel(id),evento TEXT,dados TEXT,criado_em TEXT DEFAULT CURRENT_TIMESTAMP);
''')
        migration=Path('migrations/006_whatsapp_omnichannel.sql').read_text().replace('BIGSERIAL PRIMARY KEY','INTEGER PRIMARY KEY AUTOINCREMENT').replace('DEFAULT NOW()','DEFAULT CURRENT_TIMESTAMP').replace("'{}'::jsonb","'{}'")
        conn.executescript(migration);conn.executescript(migration);conn.close()
    def __call__(self):return Conexao(self.path)
    def rows(self,table):
        conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row
        try:return [dict(r) for r in conn.execute('SELECT * FROM '+table)]
        finally:conn.close()
    def close(self):self.temp.cleanup()

class Conexao:
    def __init__(self,path):
        self.db=sqlite3.connect(path);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.create_function('NOW',0,lambda:'2026-09-10 00:00:00')
        self.db.create_function('regexp_replace',4,lambda text,pattern,replacement,flags:re.sub(pattern,replacement,text or ''))
        self.db.create_function('regexp',2,lambda pattern,text:bool(re.search(pattern,text or '')))
    def __enter__(self):return self
    def __exit__(self,exc,*args):self.db.rollback() if exc else self.db.commit()
    def cursor(self,**kwargs):return Cursor(self.db,bool(kwargs))
    def close(self):self.db.close()
    def rollback(self):self.db.rollback()

class Cursor:
    def __init__(self,db,as_dict):self.db=db;self.as_dict=as_dict;self.special=False
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,args=()):
        self.special=sql.startswith('SELECT pg_')
        if self.special:return
        sql=sql.replace('%s','?').replace(' FOR UPDATE','').replace("contato ~ ","contato REGEXP ")
        args=[json.dumps(v.adapted) if hasattr(v,'adapted') else str(v) if type(v).__name__=='UUID' else v for v in args]
        self.cur=self.db.execute(sql,args)
    def convert(self,row):
        if row is None:return None
        if not self.as_dict:return tuple(json.loads(v) if isinstance(v,str) and v.startswith('{') else v for v in row)
        d=dict(row)
        for k in ('dados','interpretacao'):
            if d.get(k):d[k]=json.loads(d[k])
        return d
    def fetchone(self):return (True,) if self.special else self.convert(self.cur.fetchone())
    def fetchall(self):return [self.convert(r) for r in self.cur.fetchall()]
