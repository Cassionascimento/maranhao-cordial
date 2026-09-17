"""Opt-in: PostgreSQL real efêmero, nunca usa DATABASE_URL.
P5X_POSTGRES_LOCAL=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python3 -m unittest tests.test_p5x_postgres_real
Socket e data_directory devem corresponder ao cluster temporário autorizado.
Schemas de teste exclusivos permanecem apenas nesse cluster descartável.
"""
import io
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from pptx import Presentation
import mi_artefatos as a
import mi_brand_context as brand
import mi_regulatorio_produto as reg
import mi_conselho as conselho
import mi_secretario_executivo as secretario
import mi_presentation_engine as deck
import mi_chart_engine as chart
import mi_pirret_criativo as pirret
import mi_label_studio as label
import mi_social_studio as social
from mi_image_provider import MockImageProvider
from tests.test_mi_pirret_criativo import _cliente_mock

SOCKET='/tmp/p5x-postgres-data'
MIGRATIONS=('016_mi_conselho.sql','017_mi_conselho_registros_payload_hash.sql',
            '019_mi_artefatos.sql','020_mi_brand_context.sql','021_mi_regulatorio_produto.sql')

def local_connection(schema='public'):
    if os.getenv('P5X_POSTGRES_LOCAL')!='1':raise RuntimeError('homologacao_local_nao_autorizada')
    conn=psycopg2.connect(host=SOCKET,port=55439,user='p5x_homolog',dbname='postgres',
                         options='-c search_path='+schema,connect_timeout=3)
    with conn.cursor() as cur:
        cur.execute('SHOW data_directory'); directory=cur.fetchone()[0]
        cur.execute('SHOW listen_addresses'); listen=cur.fetchone()[0]
    conn.rollback()
    if Path(directory).resolve()!=Path(SOCKET).resolve() or listen:
        conn.close();raise RuntimeError('cluster_nao_isolado')
    return conn

@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL')=='1','requer cluster PostgreSQL local isolado')
class PostgresReal(unittest.TestCase):
    def setUp(self):
        self.schema='p5x_homolog_'+uuid4().hex
        conn=local_connection()
        with conn:
            with conn.cursor() as cur:cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        conn.close()
        self.factory=lambda:local_connection(self.schema)
        self.apply()
    def apply(self):
        conn=self.factory()
        with conn:
            with conn.cursor() as cur:
                for name in MIGRATIONS:cur.execute(Path('migrations',name).read_text())
        conn.close()
    def rows(self,query,args=()):
        conn=self.factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query,args);return cur.fetchall()
        finally:conn.close()
    def create(self,**extra):
        return a.registrar_artefato(self.factory,artifact_type='IMAGE',conteudo=b'test-only',mime_type='image/png',
            metadata={'confidence':'SYNTHETIC_TEST'},**extra)
    def test_migrations_reaplicadas_preservam_dados_indices_constraints(self):
        artifact=self.create();self.apply()
        self.assertEqual(len(self.rows('SELECT * FROM mi_artefatos')),1)
        self.assertEqual(len(self.rows('SELECT * FROM mi_artefatos_blobs')),1)
        indices=self.rows('SELECT indexname FROM pg_indexes WHERE schemaname=%s',(self.schema,))
        self.assertGreaterEqual(len(indices),13)
        conn=self.factory()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with conn:
                with conn.cursor() as cur:cur.execute("UPDATE mi_artefatos SET status='aprovado' WHERE id=%s",(artifact['id'],))
        conn.close()
        self.assertEqual(self.rows('SELECT status FROM mi_artefatos')[0]['status'],'gerado')
    def test_banco_vazio_parcial_e_artefato_inexistente(self):
        conn=self.factory()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertEqual(a.listar_artefatos(cur),[])
            self.assertIsNone(brand.brand_context_atual(cur))
        conn.close()
        self.assertFalse(a.aprovar_artefato(self.factory,str(uuid4()),'teste')['success'])
        self.assertFalse(a.atualizar_metadata_artefato(self.factory,str(uuid4()),{'x':1})['success'])
        brand.registrar_versao_brand_context(self.factory,{'paleta':['teste']},'teste')
        self.assertEqual(len(self.rows('SELECT * FROM mi_brand_context')),1)
    def test_falha_transacional_nao_deixa_blob_orfao(self):
        conn=self.factory()
        with conn:
            with conn.cursor() as cur:cur.execute("ALTER TABLE mi_artefatos ADD CONSTRAINT simular_falha CHECK (artifact_type <> 'IMAGE')")
        conn.close()
        with self.assertRaises(psycopg2.errors.CheckViolation):self.create()
        self.assertEqual(self.rows('SELECT * FROM mi_artefatos_blobs'),[])
    def test_aprovacao_concorrente_uma_unica_auditoria(self):
        artifact=self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:a.aprovar_artefato(self.factory,artifact['id'],'teste humano'),range(2)))
        self.assertEqual(sum(r['success'] for r in results),1)
        self.assertEqual(len(self.rows('SELECT * FROM mi_artefatos_auditoria')),1)
    def test_metadata_idempotente_e_nova_versao_preserva_anterior(self):
        artifact=self.create()
        for _ in range(2):a.atualizar_metadata_artefato(self.factory,artifact['id'],{'observacao':'teste'},ator='teste')
        self.assertEqual(len(self.rows('SELECT * FROM mi_artefatos_auditoria')),1)
        a.rejeitar_artefato(self.factory,artifact['id'],'teste','não usar')
        novo=self.create(parent_artifact_id=artifact['id'])
        self.assertEqual(novo['version'],2)
        self.assertEqual(self.rows('SELECT status FROM mi_artefatos WHERE id=%s',(artifact['id'],))[0]['status'],'rejeitado')
    def test_permissoes_readonly_e_rollback_ddl(self):
        conn=self.factory();conn.set_session(readonly=True)
        with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):
            with conn:
                with conn.cursor() as cur:cur.execute("INSERT INTO mi_brand_context(id,versao,criado_por) VALUES(%s,1,'teste')",(str(uuid4()),))
        conn.close()
        conn=self.factory()
        with conn.cursor() as cur:cur.execute('CREATE TABLE rollback_probe (id int)')
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('rollback_probe')");self.assertIsNone(cur.fetchone()[0])
        conn.close()
    def test_conselho_pptx_chart_studios_end_to_end_real_sql(self):
        record,status=conselho.registrar_registro(self.factory,{'chave':str(uuid4()),'tipo':'reuniao',
            'demanda':'SYNTHETIC_TEST — validar pipeline, não operação empresarial',
            'participantes':['iris','pirret'],'conclusao':'AGUARDANDO DADOS comerciais',
            'dados_apresentados':{},'recomendacoes':[]})
        self.assertEqual(status,201)
        conn=self.factory()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:row=conselho.buscar_registro(cur,record['id'])
        conn.close()
        with patch.object(secretario,'OpenAI',side_effect=RuntimeError('sem credencial')):
            ata=secretario.montar_ata_executiva(row)
        pres=deck.gerar_e_registrar_apresentacao(self.factory,ata,graficos=[chart.NOT_ENOUGH_DATA])
        conn=self.factory()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            blob=a.PostgresBlobStorage(cur).ler(pres['storage_uri'])
        conn.close()
        self.assertLessEqual(len(Presentation(io.BytesIO(blob)).slides),6)
        brand.registrar_versao_brand_context(self.factory,{'paleta':['#000000'],'restricoes':['SYNTHETIC_TEST']},'teste')
        provider=MockImageProvider()
        concepts=label.gerar_conceito_rotulo(self.factory,'SYNTHETIC_TEST','TEST',quantidade=1,provider=provider,cliente=_cliente_mock())
        ident=concepts['artefatos'][0]['id'];a.aprovar_artefato(self.factory,ident,'teste humano')
        result=social.gerar_campanha_a_partir_de_artefato(self.factory,ident,list(social.FORMATOS_SOCIAL),provider=provider)
        self.assertEqual(len(result['pecas']),7)
        newer=pirret.refinar_conceito_visual(self.factory,ident,'SYNTHETIC_TEST',provider=provider)
        self.assertEqual(newer['version'],2)
        self.assertEqual(len(self.rows('SELECT * FROM mi_artefatos')),10)

    def test_brand_e_regulatorio_concorrentes_preservam_versoes(self):
        conn=self.factory()
        with conn:
            with conn.cursor() as cur:
                cur.execute("CREATE FUNCTION slow_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.1); RETURN NEW; END $$")
                for table in ('mi_brand_context','mi_regulatorio_produto'):
                    cur.execute(sql.SQL('CREATE TRIGGER homolog_delay BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION slow_insert()').format(sql.Identifier(table)))
        conn.close()
        for generate,table in ((lambda:brand.registrar_versao_brand_context(self.factory,{},'teste'),'mi_brand_context'),
                               (lambda:reg.registrar_versao_regulatoria(self.factory,'TEST',{},'teste'),'mi_regulatorio_produto')):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:generate(),range(2)))
            self.assertEqual(sorted(r['versao'] for r in results),[1,2],table)

    def test_migration_rollback_e_usuario_sem_permissao(self):
        conn=self.factory();name='p5x_rollback_'+uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
            cur.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(name)))
            for filename in MIGRATIONS[2:]:cur.execute(Path('migrations',filename).read_text())
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(name,));self.assertIsNone(cur.fetchone())
        conn.rollback()
        role='p5x_readonly_'+uuid4().hex
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(role)))
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                    cur.execute("INSERT INTO mi_brand_context(id,versao,criado_por) VALUES(%s,1,'teste')",(str(uuid4()),))
        conn.close()
