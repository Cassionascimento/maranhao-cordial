"""Catálogo de produtos contra PostgreSQL real e isolado.

Roda no cluster efêmero do CI (job "Regressões PostgreSQL real") e localmente
com P5X_POSTGRES_LOCAL=1. Sem cluster, todos os testes são pulados — e o job
do CI FALHA se algum for pulado, então isto não vira verde por omissão.

Cada teste tem um schema próprio, com a migration 019 (mi_artefatos_blobs,
reaproveitada para uploads) e a 030 (catálogo) REAIS aplicadas.
"""
import io
import os
import unittest
from pathlib import Path
from uuid import uuid4

from flask import Flask, request
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from tests.test_p5x_postgres_real import local_connection
import catalogo_produtos as cat

PNG_1PX = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108020000009077'
    '53de0000000c4944415478da6360606000000005000101a5f645400000000049454e44ae426082')


def corpo_produto(**extra):
    base = {'nome': 'Sabonete de Bacuri', 'categoria': 'Higiene', 'descricao_curta': 'Sabonete artesanal de bacuri.',
            'modalidade_compra': 'orcamento'}
    base.update(extra)
    return base


@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL') == '1', 'requer PostgreSQL temporário local')
class CatalogoPostgres(unittest.TestCase):
    def setUp(self):
        self.schema = 'catalogo_regressao_' + uuid4().hex
        self.connections = []
        conn = local_connection()
        with conn, conn.cursor():
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        conn.close()
        for numero in (19, 30):
            self.run_sql(next(Path('migrations').glob(f'{numero:03d}_*.sql')).read_text())
        self.addCleanup(self.derrubar_schema)

    def derrubar_schema(self):
        for c in self.connections:
            try:
                c.close()
            except Exception:
                pass
        conn = local_connection()
        with conn, conn.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(self.schema)))
        conn.close()

    def factory(self):
        conn = local_connection(self.schema)
        self.connections.append(conn)
        return conn

    def run_sql(self, query, args=()):
        conn = self.factory()
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Sem args, NÃO passar params: um "%" literal no SQL (ex.: "0,0% álcool"
                    # no seed da migration 030) faria o psycopg2 tentar interpretá-lo como
                    # placeholder assim que qualquer tupla de params é passada, mesmo vazia.
                    if args:
                        cur.execute(query, args)
                    else:
                        cur.execute(query)
                    return cur.fetchall() if cur.description else []
        finally:
            conn.close()

    def contar(self, tabela):
        return self.run_sql('SELECT count(*) AS n FROM ' + tabela)[0]['n']

    def app(self, pasta='.'):
        app = Flask(__name__)
        app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024
        cat.registrar_rotas_catalogo(app, self.factory, lambda: request.headers.get('X-Admin-Key') == 'teste', pasta)
        return app.test_client()

    H = {'X-Admin-Key': 'teste'}


class Seed(CatalogoPostgres):
    def test_maranhao_cordial_semeado_publicado_e_em_destaque(self):
        p = self.run_sql("SELECT * FROM catalogo_produtos WHERE slug='maranhao-cordial'")[0]
        self.assertEqual(p['status'], 'publicado')
        self.assertTrue(p['destaque_home'])
        self.assertEqual(p['modalidade_compra'], 'comprar_site')
        self.assertEqual(p['url_compra'], '/compreaqui.html#checkoutCard')
        self.assertEqual(p['preco_centavos'], 5990)
        self.assertNotIn('premium', p['descricao_curta'].lower())
        self.assertNotIn('premium', (p['descricao_completa'] or '').lower())
        midia = self.run_sql("SELECT * FROM catalogo_produto_midias WHERE produto_id=%s", (p['id'],))
        self.assertEqual(len(midia), 1)
        self.assertEqual(midia[0]['url_externa'], '/img/hero/tres-cordiais.webp')
        self.assertTrue(midia[0]['capa'])

    def test_reaplicar_a_migration_nao_duplica_produto_nem_midia(self):
        self.run_sql(Path('migrations/030_catalogo_produtos.sql').read_text())
        self.assertEqual(self.contar('catalogo_produtos'), 1)
        self.assertEqual(self.contar('catalogo_produto_midias'), 1)

    def test_produto_despublicado_nao_e_revivido_ao_reaplicar(self):
        self.run_sql("UPDATE catalogo_produtos SET status='rascunho' WHERE slug='maranhao-cordial'")
        self.run_sql(Path('migrations/030_catalogo_produtos.sql').read_text())
        self.assertEqual(self.run_sql("SELECT status FROM catalogo_produtos WHERE slug='maranhao-cordial'")[0]['status'], 'rascunho')


class Publico(CatalogoPostgres):
    def test_lista_publica_traz_o_produto_semeado_sem_descricao_completa(self):
        r = self.app().get('/api/catalogo/produtos')
        self.assertEqual(r.status_code, 200)
        produtos = r.get_json()['produtos']
        self.assertEqual(len(produtos), 1)
        self.assertEqual(produtos[0]['slug'], 'maranhao-cordial')
        self.assertNotIn('descricao_completa', produtos[0])
        self.assertNotIn('id', produtos[0], 'lista pública não expõe id interno')
        self.assertEqual(produtos[0]['midias'][0]['url'], '/img/hero/tres-cordiais.webp')

    def test_rascunho_nunca_aparece_na_lista_nem_na_busca_publica(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H)
        produtos = self.app().get('/api/catalogo/produtos').get_json()['produtos']
        self.assertEqual([p['slug'] for p in produtos], ['maranhao-cordial'])
        self.assertEqual(self.app().get('/api/catalogo/produtos/sabonete-de-bacuri').status_code, 404)

    def test_em_breve_aparece_na_lista_publica(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(modalidade_compra='em_breve', status='em_breve'), headers=self.H)
        produtos = self.app().get('/api/catalogo/produtos').get_json()['produtos']
        self.assertEqual(sorted(p['slug'] for p in produtos), ['maranhao-cordial', 'sabonete-de-bacuri'])

    def test_busca_por_slug_traz_a_descricao_completa(self):
        r = self.app().get('/api/catalogo/produtos/maranhao-cordial')
        self.assertEqual(r.status_code, 200)
        self.assertIn('descricao_completa', r.get_json()['produto'])

    def test_url_compra_so_aparece_quando_a_modalidade_e_comprar_site(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(
            modalidade_compra='comprar_site', url_compra='/compreaqui.html#sabonete', status='publicado'), headers=self.H)
        p = self.app().get('/api/catalogo/produtos/sabonete-de-bacuri').get_json()['produto']
        self.assertEqual(p['url_compra'], '/compreaqui.html#sabonete')
        r2 = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(
            nome='Vela de Cheiro', modalidade_compra='orcamento', status='publicado'), headers=self.H)
        self.assertIsNone(self.app().get('/api/catalogo/produtos/vela-de-cheiro').get_json()['produto']['url_compra'])

    def test_pagina_do_produto_serve_o_mesmo_arquivo_para_qualquer_slug(self):
        pasta = Path('/tmp') / ('produtopag_' + uuid4().hex)
        pasta.mkdir()
        (pasta / 'produto.html').write_text('<!doctype html><title>produto</title>')
        self.addCleanup(lambda: [p.unlink() for p in pasta.iterdir()] and pasta.rmdir())
        cliente = self.app(str(pasta))
        r1 = cliente.get('/produto/maranhao-cordial')
        r2 = cliente.get('/produto/isso-nao-existe')
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        r1.close(); r2.close()

    def test_produto_inexistente_e_404_generico(self):
        r = self.app().get('/api/catalogo/produtos/isso-nao-existe')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['error'], 'produto_nao_encontrado')


class Midia(CatalogoPostgres):
    def criar_e_subir(self, **extra_upload):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(status='publicado'),
                                     headers=self.H).get_json()['produto']['id']
        dados = {'tipo': 'imagem', 'alt_text': 'Sabonete artesanal de bacuri sobre pano de linho.'}
        dados.update(extra_upload)
        r = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias', headers=self.H,
                            data=dict(dados, arquivo=(io.BytesIO(PNG_1PX), 'foto.png')),
                            content_type='multipart/form-data')
        return produto_id, r

    def test_upload_de_imagem_fica_disponivel_publicamente_apos_publicar(self):
        produto_id, r = self.criar_e_subir()
        self.assertEqual(r.status_code, 201)
        midia = r.get_json()['midia']
        resposta = self.app().get(midia['url'])
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers['Content-Type'], 'image/png')
        self.assertEqual(resposta.data, PNG_1PX)

    def test_midia_de_produto_em_rascunho_nao_e_servida_publicamente(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias', headers=self.H,
                            data={'tipo': 'imagem', 'alt_text': 'x', 'arquivo': (io.BytesIO(PNG_1PX), 'f.png')},
                            content_type='multipart/form-data')
        midia_id = r.get_json()['midia']['id']
        self.assertEqual(self.app().get('/api/catalogo/midia/' + midia_id).status_code, 404)

    def test_formato_fora_da_lista_branca_e_recusado(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias', headers=self.H,
                            data={'tipo': 'imagem', 'alt_text': 'x', 'arquivo': (io.BytesIO(b'<svg></svg>'), 'f.svg', 'image/svg+xml')},
                            content_type='multipart/form-data')
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'arquivo_formato'))

    def test_imagem_sem_texto_alternativo_e_recusada(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias', headers=self.H,
                            data={'tipo': 'imagem', 'arquivo': (io.BytesIO(PNG_1PX), 'f.png')},
                            content_type='multipart/form-data')
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'alt_text'))

    def test_marcar_nova_capa_tira_a_anterior(self):
        produto_id, r1 = self.criar_e_subir(capa='true')
        self.assertTrue(r1.get_json()['midia']['capa'])
        r2 = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias', headers=self.H,
                             data={'tipo': 'imagem', 'alt_text': 'Segunda foto do sabonete.', 'capa': 'true',
                                   'arquivo': (io.BytesIO(PNG_1PX), 'f2.png')},
                             content_type='multipart/form-data')
        capas = self.run_sql("SELECT capa FROM catalogo_produto_midias WHERE produto_id=%s ORDER BY criado_em", (produto_id,))
        self.assertEqual([c['capa'] for c in capas], [False, True])

    def test_remover_midia_apaga_o_blob(self):
        # A migration já semeia uma mídia (a foto real do Maranhão Cordial,
        # por url_externa -- sem blob). O que este teste verifica é que a
        # mídia CRIADA aqui, e só ela, some ao ser removida.
        antes = self.contar('catalogo_produto_midias')
        produto_id, r = self.criar_e_subir()
        midia_id = r.get_json()['midia']['id']
        self.assertEqual(self.contar('catalogo_produto_midias'), antes + 1)
        self.assertEqual(self.contar('mi_artefatos_blobs'), 1)
        d = self.app().delete(f'/api/admin/catalogo/produtos/{produto_id}/midias/{midia_id}', headers=self.H)
        self.assertEqual(d.status_code, 200)
        self.assertEqual(self.contar('catalogo_produto_midias'), antes)
        self.assertEqual(self.contar('mi_artefatos_blobs'), 0)

    def test_upload_exige_autorizacao(self):
        produto_id = self.run_sql("SELECT id FROM catalogo_produtos WHERE slug='maranhao-cordial'")[0]['id']
        r = self.app().post(f'/api/admin/catalogo/produtos/{produto_id}/midias',
                            data={'tipo': 'imagem', 'alt_text': 'x', 'arquivo': (io.BytesIO(PNG_1PX), 'f.png')},
                            content_type='multipart/form-data')
        self.assertEqual(r.status_code, 401)


class Administracao(CatalogoPostgres):
    def test_criar_gera_slug_a_partir_do_nome(self):
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(nome='Vela de Alecrim e Cajá'), headers=self.H)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()['produto']['slug'], 'vela-de-alecrim-e-caja')
        self.assertEqual(r.get_json()['produto']['status'], 'rascunho', 'produto novo nasce em rascunho por padrão')

    def test_slug_repetido_e_recusado(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H)
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['error']), (409, 'slug_em_uso'))

    def test_comprar_site_exige_url_compra(self):
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(modalidade_compra='comprar_site'), headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'url_compra'))

    def test_url_compra_absoluta_precisa_ser_https(self):
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(
            modalidade_compra='comprar_site', url_compra='http://inseguro.com'), headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'url_compra'))
        self.assertEqual(self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(
            modalidade_compra='comprar_site', url_compra='javascript:alert(1)'), headers=self.H).status_code, 400)

    def test_modalidade_invalida_e_recusada(self):
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(modalidade_compra='fiado'), headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'modalidade_compra'))

    def test_campos_obrigatorios(self):
        for campo, corpo in (('nome', corpo_produto(nome='')), ('categoria', corpo_produto(categoria='')),
                             ('descricao_curta', corpo_produto(descricao_curta=''))):
            r = self.app().post('/api/admin/catalogo/produtos', json=corpo, headers=self.H)
            self.assertEqual((r.status_code, r.get_json()['campo']), (400, campo), campo)

    def test_preco_negativo_e_recusado_preco_nulo_e_aceito(self):
        r1 = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(preco_centavos=-1), headers=self.H)
        self.assertEqual((r1.status_code, r1.get_json()['campo']), (400, 'preco_centavos'))
        r2 = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(preco_centavos=None), headers=self.H)
        self.assertEqual(r2.status_code, 201)

    def test_campos_da_bebida_nao_sao_obrigatorios_para_outra_categoria(self):
        r = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H)
        self.assertEqual(r.status_code, 201)
        p = r.get_json()['produto']
        self.assertIsNone(p['volume'])
        self.assertIsNone(p['preco_centavos'])

    def test_publicar_e_despublicar_via_patch(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        self.assertEqual(self.app().get('/api/catalogo/produtos/sabonete-de-bacuri').status_code, 404)
        r = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'status': 'publicado'}, headers=self.H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.app().get('/api/catalogo/produtos/sabonete-de-bacuri').status_code, 200)
        self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'status': 'rascunho'}, headers=self.H)
        self.assertEqual(self.app().get('/api/catalogo/produtos/sabonete-de-bacuri').status_code, 404)

    def test_id_slug_e_criado_em_nao_sao_editaveis(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        for campo in ('id', 'slug', 'criado_em', 'atualizado_em'):
            r = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={campo: 'x'}, headers=self.H)
            self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'campo_nao_editavel'), campo)

    def test_campo_desconhecido_e_recusado(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'preco_secreto': 1}, headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'campo_desconhecido'))

    def test_trocar_para_comprar_site_sem_url_e_recusado_ja_tendo_url_e_aceito(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'modalidade_compra': 'comprar_site'}, headers=self.H)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'url_compra'))
        self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'url_compra': '/compreaqui.html#x'}, headers=self.H)
        r2 = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'modalidade_compra': 'comprar_site'}, headers=self.H)
        self.assertEqual(r2.status_code, 200)

    def test_destaque_e_ordem_sao_editaveis(self):
        produto_id = self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(), headers=self.H).get_json()['produto']['id']
        r = self.app().patch(f'/api/admin/catalogo/produtos/{produto_id}', json={'destaque_home': True, 'ordem_exibicao': 5}, headers=self.H)
        p = r.get_json()['produto']
        self.assertEqual((p['destaque_home'], p['ordem_exibicao']), (True, 5))

    def test_produto_inexistente_no_patch_e_404(self):
        r = self.app().patch(f'/api/admin/catalogo/produtos/{uuid4()}', json={'destaque_home': True}, headers=self.H)
        self.assertEqual(r.status_code, 404)

    def test_lista_admin_traz_rascunhos_e_ordena_pela_vitrine(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(ordem_exibicao=1), headers=self.H)
        produtos = self.app().get('/api/admin/catalogo/produtos', headers=self.H).get_json()['produtos']
        self.assertEqual(len(produtos), 2)
        self.assertTrue(any(p['status'] == 'rascunho' for p in produtos))

    def test_categorias_reflete_o_que_ja_foi_usado(self):
        self.app().post('/api/admin/catalogo/produtos', json=corpo_produto(categoria='Velas'), headers=self.H)
        categorias = self.app().get('/api/admin/catalogo/categorias', headers=self.H).get_json()['categorias']
        self.assertEqual(sorted(categorias), ['Bebidas', 'Velas'])

    def test_rotas_de_administracao_exigem_chave(self):
        cliente = self.app()
        for metodo, url in (('get', '/api/admin/catalogo/produtos'), ('post', '/api/admin/catalogo/produtos'),
                            ('get', '/api/admin/catalogo/categorias'),
                            ('patch', f'/api/admin/catalogo/produtos/{uuid4()}')):
            self.assertEqual(getattr(cliente, metodo)(url).status_code, 401, url)


class Restricoes(CatalogoPostgres):
    def test_restricoes_do_banco_impedem_dado_invalido_mesmo_sem_a_aplicacao(self):
        import psycopg2
        for consulta in (
            "INSERT INTO catalogo_produtos(slug,nome,categoria,descricao_curta,modalidade_compra) "
            "VALUES('x','n','c','d','fiado')",
            "INSERT INTO catalogo_produtos(slug,nome,categoria,descricao_curta,modalidade_compra) "
            "VALUES('y','n','c','d','comprar_site')",
        ):
            with self.assertRaises(psycopg2.errors.CheckViolation):
                self.run_sql(consulta)

    def test_midia_precisa_de_blob_ou_url_externa_nunca_os_dois_nem_nenhum(self):
        import psycopg2
        produto_id = self.run_sql("SELECT id FROM catalogo_produtos LIMIT 1")[0]['id']
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.run_sql("INSERT INTO catalogo_produto_midias(produto_id,tipo) VALUES(%s,'imagem')", (produto_id,))


if __name__ == '__main__':
    unittest.main()
