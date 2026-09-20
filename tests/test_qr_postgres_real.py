"""QR Codes rastreáveis contra PostgreSQL real e isolado.

Roda no cluster efêmero do CI (job "Regressões PostgreSQL real") e localmente
com P5X_POSTGRES_LOCAL=1. Sem cluster, todos os testes são pulados — e o job
do CI FALHA se algum for pulado, então isto não vira verde por omissão.

Cada teste tem um schema próprio, com as migrations REAIS aplicadas (sinais
007-013, identidades 027, QR 029). Nada de rede, nada de transporte.
"""
import os
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from flask import Flask, request
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from tests.test_p5x_postgres_real import local_connection
import qr_rastreavel as qr

TELEFONE = '(98) 99000-0000'
TELEFONE_E164 = '5598990000000'

SEGREDOS_QUE_NAO_PODEM_VAZAR = ('sku', 'lote_id', 'unidade_id', 'destino_url_interno')


def corpo_avaliacao(**extra):
    base = {
        'chave': str(uuid4()), 'perfil': 'consumidor', 'aplicacao': 'mocktail', 'nota': 9,
        'sensorial': {'guarana': 'ideal', 'docura': 'alto', 'acidez': 'ideal',
                      'gengibre': 'alto', 'textura': 'ideal'},
        'intencao_compra': 'provavelmente', 'faixa_preco': '59_69',
        'formas_uso': ['drinks_sem_alcool', 'com_agua_com_gas'], 'comentario': 'Muito bom.',
    }
    base.update(extra)
    return base


def corpo_contato(**extra):
    base = {'chave': str(uuid4()), 'nome': 'Marina Costa', 'whatsapp': TELEFONE,
            'email': 'marina@bar.com', 'empresa': 'Bar Central', 'cidade': 'São Luís', 'uf': 'MA',
            'interesse': 'amostra', 'perfil': 'bar_restaurante',
            'consentimento_contato': True, 'consentimento_marketing': False}
    base.update(extra)
    return base


@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL') == '1', 'requer PostgreSQL temporário local')
class QRPostgres(unittest.TestCase):
    def setUp(self):
        self.schema = 'qr_regressao_' + uuid4().hex
        self.connections = []
        conn = local_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        conn.close()
        self.run_sql('''CREATE TABLE leads_crm(id UUID PRIMARY KEY,nome VARCHAR(180),empresa VARCHAR(220),
            tipo_lead VARCHAR(30) NOT NULL,origem VARCHAR(80) NOT NULL,canal VARCHAR(80),cidade VARCHAR(120),
            estado VARCHAR(80),contato VARCHAR(220),interesse TEXT,telefone VARCHAR(80),email VARCHAR(220),
            categoria_contato TEXT,observacoes TEXT,arquivado BOOLEAN DEFAULT FALSE,
            contato_interno BOOLEAN DEFAULT FALSE,cadastro_teste BOOLEAN DEFAULT FALSE,
            atualizado_em TIMESTAMPTZ DEFAULT NOW())''')
        for numero in list(range(7, 14)) + [27, 29]:
            self.run_sql(next(Path('migrations').glob(f'{numero:03d}_*.sql')).read_text())
        rede = patch('requests.sessions.Session.request', side_effect=AssertionError('transporte proibido'))
        rede.start()
        self.addCleanup(rede.stop)
        self.addCleanup(self.derrubar_schema)

    def derrubar_schema(self):
        for c in self.connections:
            try:
                c.close()
            except Exception:
                pass
        conn = local_connection()
        with conn:
            with conn.cursor() as cur:
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
                    cur.execute(query, args)
                    return cur.fetchall() if cur.description else []
        finally:
            conn.close()

    def codigo(self, slug):
        return self.run_sql('SELECT codigo_publico FROM qr_codigos WHERE slug=%s', (slug,))[0]['codigo_publico']

    def sinais(self, tipo=None):
        consulta = "SELECT tipo_evento, origem_id, payload, territorio_uf FROM mi_sinais WHERE origem='qr'"
        if tipo:
            return self.run_sql(consulta + ' AND tipo_evento=%s', (tipo,))
        return self.run_sql(consulta)

    def contar(self, tabela):
        return self.run_sql('SELECT count(*) AS n FROM ' + tabela)[0]['n']

    def app(self, pasta='.'):
        app = Flask(__name__)
        qr.registrar_rotas_qr(app, self.factory, lambda: request.headers.get('X-Admin-Key') == 'teste', pasta)
        return app.test_client()


class Codigos(QRPostgres):
    def test_os_quatro_qrs_iniciais_existem_com_codigo_opaco(self):
        linhas = self.run_sql('SELECT slug, codigo_publico, finalidade FROM qr_codigos ORDER BY slug')
        self.assertEqual({l['slug'] for l in linhas},
                         {'softdrinks_tech_2026', 'produto_embalagem', 'material_comercial', 'divulgacao_digital'})
        for l in linhas:
            self.assertRegex(l['codigo_publico'], r'^[a-hj-km-np-z2-9]{10}$')
            # Opaco: nada do slug nem da finalidade aparece no código.
            self.assertNotIn(l['slug'][:4], l['codigo_publico'])
        self.assertEqual(len({l['codigo_publico'] for l in linhas}), 4)

    def test_finalidades_iniciais(self):
        mapa = {l['slug']: l['finalidade'] for l in self.run_sql('SELECT slug, finalidade FROM qr_codigos')}
        self.assertEqual(mapa, {'softdrinks_tech_2026': 'avaliacao_feira', 'produto_embalagem': 'avaliacao_produto',
                                'material_comercial': 'comercial', 'divulgacao_digital': 'divulgacao'})

    def test_reaplicar_a_migration_nao_troca_codigo_em_uso(self):
        antes = self.codigo('softdrinks_tech_2026')
        self.run_sql(Path('migrations/029_qr_rastreaveis.sql').read_text())
        self.assertEqual(self.codigo('softdrinks_tech_2026'), antes)
        self.assertEqual(self.contar('qr_codigos'), 4)

    def test_normalizacao_aceita_maiuscula_e_espaco_e_recusa_o_resto(self):
        c = self.codigo('produto_embalagem')
        self.assertEqual(qr.normalizar_codigo('  ' + c.upper() + ' '), c)
        for ruim in ('', 'curto', c + 'x', c.replace(c[0], '0', 1), None, 123, 'p8qp3av4g!'):
            with self.assertRaises(ValueError):
                qr.normalizar_codigo(ruim)


class Publico(QRPostgres):
    def test_configuracao_publica_nao_vaza_dado_interno(self):
        c = self.codigo('softdrinks_tech_2026')
        r = self.app().get('/api/qr/' + c)
        self.assertEqual(r.status_code, 200)
        corpo = r.get_data(as_text=True)
        for proibido in ('"id"', 'lote_id', 'unidade_id', '"sku"', 'codigo_publico', 'criado_em'):
            self.assertNotIn(proibido, corpo)
        dados = r.get_json()
        self.assertEqual(dados['qr']['finalidade'], 'avaliacao_feira')
        self.assertEqual(dados['qr']['chamada'], 'Provou? Conte o que achou.')
        self.assertTrue(dados['qr']['tem_avaliacao'])
        self.assertEqual(dados['consentimento']['versao'], qr.CONSENTIMENTO_VERSAO)

    def test_codigo_em_maiuscula_funciona(self):
        self.assertEqual(self.app().get('/api/qr/' + self.codigo('produto_embalagem').upper()).status_code, 200)

    def test_inexistente_pausado_e_revogado_respondem_exatamente_igual(self):
        cliente = self.app()
        inexistente = cliente.get('/api/qr/aaaaaaaaaa')
        c_pausado, c_revogado = self.codigo('produto_embalagem'), self.codigo('material_comercial')
        self.run_sql("UPDATE qr_codigos SET estado='pausado' WHERE codigo_publico=%s", (c_pausado,))
        self.run_sql("UPDATE qr_codigos SET estado='revogado' WHERE codigo_publico=%s", (c_revogado,))
        for c in (c_pausado, c_revogado, 'aaaaaaaaaa', 'formato-ruim'):
            r = cliente.get('/api/qr/' + c)
            self.assertEqual(r.status_code, 404, c)
            self.assertEqual(r.get_json(), inexistente.get_json(), 'a resposta não pode revelar o motivo')

    def test_pagina_e_identica_para_qualquer_codigo_e_nao_indexa(self):
        pasta = Path('/tmp') / ('qrpag_' + uuid4().hex)
        pasta.mkdir()
        (pasta / 'qr.html').write_text('<!doctype html><title>qr</title>')
        self.addCleanup(lambda: [p.unlink() for p in pasta.iterdir()] and pasta.rmdir())
        cliente = self.app(str(pasta))
        valido = cliente.get('/q/' + self.codigo('softdrinks_tech_2026'))
        invalido = cliente.get('/q/qualquercoisa')
        self.assertEqual(valido.status_code, invalido.status_code)
        self.assertEqual(valido.get_data(), invalido.get_data(), 'a página não pode ser um oráculo de códigos')
        self.assertIn('noindex', valido.headers['X-Robots-Tag'])
        valido.close(), invalido.close()

    def test_scan_grava_evento_e_sinal_e_e_idempotente_por_chave(self):
        c, chave = self.codigo('softdrinks_tech_2026'), str(uuid4())
        cliente = self.app()
        r1 = cliente.post(f'/api/qr/{c}/scan', json={'chave': chave})
        r2 = cliente.post(f'/api/qr/{c}/scan', json={'chave': chave})
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertFalse(r1.get_json()['duplicado'])
        self.assertTrue(r2.get_json()['duplicado'])
        self.assertEqual(self.contar('qr_eventos'), 1)
        self.assertEqual(len(self.sinais('qr_scan')), 1)
        cliente.post(f'/api/qr/{c}/scan', json={'chave': str(uuid4())})
        self.assertEqual(self.contar('qr_eventos'), 2, 'outra sessão é outro scan legítimo')

    def test_scan_de_codigo_invalido_nao_grava_nada(self):
        r = self.app().post('/api/qr/zzzzzzzzzz/scan', json={'chave': str(uuid4())})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.contar('qr_eventos'), 0)

    def test_sinal_do_scan_carrega_o_qr_e_nenhum_dado_pessoal(self):
        c = self.codigo('softdrinks_tech_2026')
        self.app().post(f'/api/qr/{c}/scan', json={'chave': str(uuid4())},
                        headers={'User-Agent': 'iPhone-Safari', 'X-Forwarded-For': '203.0.113.9'})
        sinal = self.sinais('qr_scan')[0]
        self.assertEqual(sinal['origem_id'], 'softdrinks_tech_2026')
        texto = str(sinal)
        for pessoal in ('203.0.113.9', 'iPhone', 'Safari'):
            self.assertNotIn(pessoal, texto)
        self.assertNotIn(pessoal := '203.0.113.9', str(self.run_sql('SELECT * FROM qr_eventos')))


class Avaliacao(QRPostgres):
    def test_avaliacao_anonima_completa_grava_sinais_e_nao_cria_lead(self):
        c = self.codigo('softdrinks_tech_2026')
        corpo = corpo_avaliacao()
        r = self.app().post(f'/api/qr/{c}/avaliacao', json=corpo)
        self.assertEqual((r.status_code, r.get_json()['duplicada']), (201, False))
        linha = self.run_sql('SELECT * FROM qr_avaliacoes')[0]
        self.assertEqual((linha['nota'], linha['perfil'], linha['docura']), (9, 'consumidor', 'alto'))
        self.assertEqual(sorted(linha['formas_uso']), ['com_agua_com_gas', 'drinks_sem_alcool'])
        tipos = sorted(s['tipo_evento'] for s in self.sinais())
        self.assertEqual(tipos, ['avaliacao_concluida', 'avaliacao_iniciada', 'intencao_compra', 'preco_aceito'])
        # O ponto central: anônima não vira contato.
        self.assertEqual(self.contar('leads_crm'), 0)
        self.assertEqual(self.contar('qr_contatos'), 0)
        self.assertEqual(self.contar('crm_identidades_canal'), 0)

    def test_aceita_59_e_derivado_no_servidor_e_nao_pode_ser_forjado(self):
        c = self.codigo('softdrinks_tech_2026')
        cliente = self.app()
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(faixa_preco='50_58', aceita_59=True))
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(faixa_preco='59_69', aceita_59=False))
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(faixa_preco='70_ou_mais'))
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(faixa_preco='ate_39'))
        resultado = {l['faixa_preco']: l['aceita_59'] for l in self.run_sql('SELECT faixa_preco, aceita_59 FROM qr_avaliacoes')}
        self.assertEqual(resultado, {'50_58': False, '59_69': True, '70_ou_mais': True, 'ate_39': False})
        self.assertEqual(len(self.sinais('preco_aceito')), 2)

    def test_intencao_negativa_nao_emite_intencao_de_compra(self):
        c = self.codigo('softdrinks_tech_2026')
        cliente = self.app()
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(intencao_compra='talvez'))
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(intencao_compra='nao'))
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(intencao_compra='certamente'))
        self.assertEqual(len(self.sinais('intencao_compra')), 1)

    def test_reenvio_com_a_mesma_chave_nao_duplica_avaliacao_nem_sinal(self):
        c, corpo = self.codigo('softdrinks_tech_2026'), corpo_avaliacao()
        cliente = self.app()
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo)
        r = cliente.post(f'/api/qr/{c}/avaliacao', json=corpo)
        self.assertEqual((r.status_code, r.get_json()['duplicada']), (200, True))
        self.assertEqual(self.contar('qr_avaliacoes'), 1)
        self.assertEqual(len(self.sinais('avaliacao_concluida')), 1)

    def test_concluida_implica_iniciada_e_o_funil_nunca_passa_de_100_por_cento(self):
        c = self.codigo('softdrinks_tech_2026')
        self.app().post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao())
        eventos = self.run_sql("SELECT tipo FROM qr_eventos")
        self.assertEqual([e['tipo'] for e in eventos], ['avaliacao_iniciada'])

    def test_inicio_explicito_seguido_de_conclusao_conta_uma_iniciada_so(self):
        c, corpo = self.codigo('softdrinks_tech_2026'), corpo_avaliacao()
        cliente = self.app()
        cliente.post(f'/api/qr/{c}/inicio', json={'chave': corpo['chave']})
        cliente.post(f'/api/qr/{c}/avaliacao', json=corpo)
        self.assertEqual(self.contar('qr_eventos'), 1)
        self.assertEqual(len(self.sinais('avaliacao_iniciada')), 1)

    def test_entradas_invalidas_sao_recusadas_e_nada_e_gravado(self):
        c = self.codigo('softdrinks_tech_2026')
        ruins = {
            'nota': corpo_avaliacao(nota=11), 'nota_negativa': corpo_avaliacao(nota=-1),
            'nota_texto': corpo_avaliacao(nota='9'), 'nota_bool': corpo_avaliacao(nota=True),
            'perfil': corpo_avaliacao(perfil='hacker'), 'faixa_preco': corpo_avaliacao(faixa_preco='59'),
            'intencao': corpo_avaliacao(intencao_compra='sim'), 'chave': corpo_avaliacao(chave='nao-e-uuid'),
            'formas_vazias': corpo_avaliacao(formas_uso=[]), 'forma_invalida': corpo_avaliacao(formas_uso=['x']),
            'sensorial_ausente': {k: v for k, v in corpo_avaliacao().items() if k != 'sensorial'},
            'comentario_longo': corpo_avaliacao(comentario='x' * 501),
        }
        cliente = self.app()
        for rotulo, corpo in ruins.items():
            r = cliente.post(f'/api/qr/{c}/avaliacao', json=corpo)
            self.assertEqual(r.status_code, 400, rotulo)
            self.assertEqual(r.get_json()['error'], 'dados_invalidos', rotulo)
        sensorial_ruim = corpo_avaliacao()
        sensorial_ruim['sensorial']['acidez'] = 'medio'
        r = cliente.post(f'/api/qr/{c}/avaliacao', json=sensorial_ruim)
        self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'acidez'))
        self.assertEqual(self.contar('qr_avaliacoes'), 0)

    def test_qr_comercial_e_digital_nao_recebem_avaliacao(self):
        cliente = self.app()
        for slug in ('material_comercial', 'divulgacao_digital'):
            r = cliente.post(f'/api/qr/{self.codigo(slug)}/avaliacao', json=corpo_avaliacao())
            self.assertEqual(r.status_code, 404, slug)
        self.assertEqual(self.contar('qr_avaliacoes'), 0)

    def test_comentario_com_html_e_guardado_como_texto_sem_alteracao(self):
        c = self.codigo('softdrinks_tech_2026')
        self.app().post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(comentario='<img src=x onerror=alert(1)>'))
        self.assertEqual(self.run_sql('SELECT comentario FROM qr_avaliacoes')[0]['comentario'],
                         '<img src=x onerror=alert(1)>')

    def test_comentario_nunca_entra_nos_sinais(self):
        c = self.codigo('softdrinks_tech_2026')
        self.app().post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(comentario='segredo-do-comentario'))
        self.assertNotIn('segredo-do-comentario', str(self.sinais()))


class Contato(QRPostgres):
    def enviar(self, corpo, slug='softdrinks_tech_2026'):
        return self.app().post(f'/api/qr/{self.codigo(slug)}/contato', json=corpo)

    def test_contato_cria_lead_vincula_avaliacao_e_registra_consentimentos_separados(self):
        c = self.codigo('softdrinks_tech_2026')
        av = corpo_avaliacao()
        self.app().post(f'/api/qr/{c}/avaliacao', json=av)
        r = self.enviar(corpo_contato(avaliacao_chave=av['chave'], consentimento_marketing=True))
        self.assertEqual((r.status_code, r.get_json()['duplicado']), (201, False))
        lead = self.run_sql('SELECT * FROM leads_crm')[0]
        self.assertEqual((lead['nome'], lead['empresa'], lead['cidade'], lead['estado']),
                         ('Marina Costa', 'Bar Central', 'São Luís', 'MA'))
        self.assertEqual((lead['telefone'], lead['email']), (TELEFONE_E164, 'marina@bar.com'))
        self.assertEqual((lead['origem'], lead['canal'], lead['tipo_lead']), ('evento', 'qr:softdrinks_tech_2026', 'b2b'))
        ct = self.run_sql('SELECT * FROM qr_contatos')[0]
        self.assertEqual(str(ct['lead_id']), str(lead['id']))
        self.assertIsNotNone(ct['avaliacao_id'])
        self.assertTrue(ct['consentimento_contato'])
        self.assertTrue(ct['consentimento_marketing'])
        self.assertEqual(ct['texto_consentimento_versao'], qr.CONSENTIMENTO_VERSAO)
        self.assertEqual(self.contar('crm_identidades_canal'), 2)

    def test_marketing_e_contato_sao_independentes(self):
        self.enviar(corpo_contato(consentimento_marketing=False))
        ct = self.run_sql('SELECT consentimento_contato, consentimento_marketing FROM qr_contatos')[0]
        self.assertEqual((ct['consentimento_contato'], ct['consentimento_marketing']), (True, False))

    def test_sem_consentimento_de_contato_nada_e_guardado(self):
        for valor in (False, None, 'true', 1):
            r = self.enviar(corpo_contato(consentimento_contato=valor))
            self.assertEqual((r.status_code, r.get_json()['campo']), (400, 'consentimento_contato'), valor)
        self.assertEqual(self.contar('leads_crm'), 0)
        self.assertEqual(self.contar('qr_contatos'), 0)

    def test_exige_ao_menos_um_meio_de_contato_valido(self):
        r = self.enviar(corpo_contato(whatsapp='', email=''))
        self.assertEqual(r.get_json()['campo'], 'contato')
        self.assertEqual(self.enviar(corpo_contato(whatsapp='123')).get_json()['campo'], 'whatsapp')
        self.assertEqual(self.enviar(corpo_contato(email='sem-arroba')).get_json()['campo'], 'email')
        self.assertEqual(self.enviar(corpo_contato(uf='XX')).get_json()['campo'], 'uf')
        self.assertEqual(self.enviar(corpo_contato(interesse='vender')).get_json()['campo'], 'interesse')
        self.assertEqual(self.contar('leads_crm'), 0)

    def test_so_whatsapp_ou_so_email_bastam(self):
        self.assertEqual(self.enviar(corpo_contato(email='')).status_code, 201)
        self.assertEqual(self.enviar(corpo_contato(whatsapp='', email='outra@pessoa.com', nome='Outra Pessoa')).status_code, 201)
        self.assertEqual(self.contar('leads_crm'), 2)

    def test_mesmo_telefone_em_formatos_diferentes_e_um_lead_so(self):
        for formato in ('(98) 99000-0000', '+55 98 99000-0000', '98990000000', '55 98 9 9000 0000'):
            self.enviar(corpo_contato(whatsapp=formato, email='', nome='Marina Costa'))
        self.assertEqual(self.contar('leads_crm'), 1)
        self.assertEqual(self.contar('qr_contatos'), 4)
        leads_dos_contatos = {str(l['lead_id']) for l in self.run_sql('SELECT lead_id FROM qr_contatos')}
        self.assertEqual(len(leads_dos_contatos), 1)

    def test_lead_antigo_com_telefone_sem_ddi_e_reaproveitado(self):
        self.run_sql("INSERT INTO leads_crm(id,nome,tipo_lead,origem,telefone) VALUES(%s,'Antigo','b2b','site','98990000000')",
                     (str(uuid4()),))
        self.enviar(corpo_contato(email=''))
        self.assertEqual(self.contar('leads_crm'), 1)
        ct = self.run_sql('SELECT lead_ja_existia, identidade_pendente FROM qr_contatos')[0]
        self.assertEqual((ct['lead_ja_existia'], ct['identidade_pendente']), (True, False))

    def test_email_em_maiuscula_reencontra_o_mesmo_lead(self):
        self.enviar(corpo_contato(whatsapp='', email='Marina@Bar.com'))
        self.enviar(corpo_contato(whatsapp='', email='marina@BAR.COM'))
        self.assertEqual(self.contar('leads_crm'), 1)

    def test_telefone_e_email_do_mesmo_envio_reencontram_o_lead_por_qualquer_um(self):
        self.enviar(corpo_contato())
        self.enviar(corpo_contato(whatsapp='', email='marina@bar.com'))
        self.enviar(corpo_contato(email=''))
        self.assertEqual(self.contar('leads_crm'), 1)
        self.assertEqual(self.run_sql('SELECT count(*) AS n FROM qr_contatos WHERE lead_ja_existia')[0]['n'], 2)

    def test_telefone_e_email_de_leads_diferentes_nao_sao_fundidos_em_silencio(self):
        self.enviar(corpo_contato(email='', nome='Um'))
        self.enviar(corpo_contato(whatsapp='', email='marina@bar.com', nome='Outro'))
        self.enviar(corpo_contato(nome='Terceiro'))
        self.assertEqual(self.contar('leads_crm'), 3)
        self.assertTrue(self.run_sql('SELECT identidade_pendente FROM qr_contatos ORDER BY criado_em DESC LIMIT 1')[0]['identidade_pendente'])

    def test_dois_cadastros_com_o_mesmo_telefone_nao_sao_adivinhados(self):
        for nome in ('A', 'B'):
            self.run_sql("INSERT INTO leads_crm(id,nome,tipo_lead,origem,telefone) VALUES(%s,%s,'b2b','site',%s)",
                         (str(uuid4()), nome, TELEFONE_E164))
        r = self.enviar(corpo_contato(email=''))
        self.assertEqual(r.status_code, 201, 'a pessoa não é punida pela duplicata da base')
        ct = self.run_sql('SELECT identidade_pendente, lead_ja_existia FROM qr_contatos')[0]
        self.assertEqual((ct['identidade_pendente'], ct['lead_ja_existia']), (True, False))
        self.assertEqual(self.contar('leads_crm'), 3)
        # Sem fusão silenciosa: a duplicata aparece para decisão humana.
        import crm_identidade as ci
        conn = self.factory()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            self.assertTrue(ci.candidatos_de_fusao(cur))
        conn.rollback()

    def test_lead_arquivado_nao_recebe_vinculo_automatico(self):
        self.run_sql("INSERT INTO leads_crm(id,nome,tipo_lead,origem,telefone,arquivado) VALUES(%s,'Velho','b2b','site',%s,TRUE)",
                     (str(uuid4()), TELEFONE_E164))
        self.enviar(corpo_contato(email=''))
        self.assertTrue(self.run_sql('SELECT identidade_pendente FROM qr_contatos')[0]['identidade_pendente'])

    def test_reenvio_com_a_mesma_chave_e_idempotente(self):
        corpo = corpo_contato()
        self.enviar(corpo)
        r = self.enviar(corpo)
        self.assertEqual((r.status_code, r.get_json()['duplicado']), (200, True))
        self.assertEqual(self.contar('leads_crm'), 1)
        self.assertEqual(self.contar('qr_contatos'), 1)
        self.assertEqual(len(self.sinais('contato_fornecido')), 1)

    def test_submissoes_simultaneas_do_mesmo_telefone_criam_um_lead_so(self):
        c = self.codigo('softdrinks_tech_2026')

        def enviar(_):
            return self.app().post(f'/api/qr/{c}/contato', json=corpo_contato(email='')).status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            estados = list(pool.map(enviar, range(6)))
        self.assertTrue(all(s == 201 for s in estados), estados)
        self.assertEqual(self.contar('leads_crm'), 1)
        self.assertEqual(self.contar('qr_contatos'), 6)

    def test_sinais_de_contato_interesse_e_lead_b2b_sem_dado_pessoal(self):
        self.enviar(corpo_contato(interesse='distribuicao', nome='Nome Muito Pessoal', empresa='Empresa Secreta Ltda'))
        tipos = sorted(s['tipo_evento'] for s in self.sinais())
        self.assertEqual(tipos, ['contato_fornecido', 'interesse_distribuicao', 'lead_b2b'])
        tudo = str(self.sinais())
        for pessoal in ('Nome Muito Pessoal', 'Empresa Secreta', 'marina@bar.com', '99000', TELEFONE_E164):
            self.assertNotIn(pessoal, tudo)
        self.assertEqual({s['territorio_uf'] for s in self.sinais()}, {'MA'})

    def test_consumidor_comum_nao_vira_lead_b2b(self):
        self.enviar(corpo_contato(perfil='consumidor', interesse='comprar', empresa=''))
        self.assertEqual(self.run_sql('SELECT tipo_lead FROM leads_crm')[0]['tipo_lead'], 'b2c')
        self.assertEqual(self.sinais('lead_b2b'), [])

    def test_todos_os_interesses_geram_o_seu_sinal(self):
        for interesse in qr.INTERESSES:
            self.enviar(corpo_contato(interesse=interesse, whatsapp='', email=f'{interesse}@teste.com'))
        emitidos = {s['tipo_evento'] for s in self.sinais()}
        for interesse in qr.INTERESSES:
            self.assertIn('interesse_' + interesse, emitidos)

    def test_qr_comercial_aceita_contato_sem_avaliacao(self):
        r = self.enviar(corpo_contato(interesse='revenda'), slug='material_comercial')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.contar('qr_avaliacoes'), 0)
        self.assertEqual(self.run_sql('SELECT origem FROM leads_crm')[0]['origem'], 'outro')


class Protecoes(QRPostgres):
    def test_isca_preenchida_e_descartada_sem_avisar_o_robo(self):
        c = self.codigo('softdrinks_tech_2026')
        r = self.app().post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao(website='http://spam'))
        self.assertEqual((r.status_code, r.get_json()), (200, {'success': True}))
        self.assertEqual(self.contar('qr_avaliacoes'), 0)

    def test_corpo_gigante_e_corpo_que_nao_e_objeto_sao_recusados(self):
        c = self.codigo('softdrinks_tech_2026')
        cliente = self.app()
        self.assertEqual(cliente.post(f'/api/qr/{c}/scan', data='x' * (qr.LIMITE_CORPO_BYTES + 10),
                                      content_type='application/json').status_code, 400)
        self.assertEqual(cliente.post(f'/api/qr/{c}/scan', json=[1, 2]).status_code, 400)
        self.assertEqual(cliente.post(f'/api/qr/{c}/scan', data='nao-json',
                                      content_type='application/json').status_code, 400)

    def test_teto_por_minuto_barra_enchente(self):
        c = self.codigo('softdrinks_tech_2026')
        cliente = self.app()
        with patch.dict(qr.LIMITE_POR_MINUTO, {'avaliacao': 3}):
            estados = [cliente.post(f'/api/qr/{c}/avaliacao', json=corpo_avaliacao()).status_code for _ in range(5)]
        self.assertEqual(estados, [201, 201, 201, 429, 429])
        self.assertEqual(self.contar('qr_avaliacoes'), 3)

    def test_rotas_de_administracao_exigem_chave(self):
        cliente = self.app()
        for metodo, url in (('get', '/api/admin/qr/codigos'), ('post', '/api/admin/qr/codigos'),
                            ('get', '/api/admin/qr/painel'), ('patch', f'/api/admin/qr/codigos/{uuid4()}'),
                            ('get', f'/api/admin/qr/codigos/{uuid4()}/arquivo')):
            self.assertEqual(getattr(cliente, metodo)(url).status_code, 401, url)

    def test_rota_publica_de_contato_nao_e_admin_e_nao_devolve_dados_do_lead(self):
        r = self.app().post(f'/api/qr/{self.codigo("softdrinks_tech_2026")}/contato', json=corpo_contato())
        self.assertEqual(r.get_json(), {'success': True, 'duplicado': False})


class Administracao(QRPostgres):
    H = {'X-Admin-Key': 'teste'}

    def criar(self, **extra):
        corpo = {'nome': 'Feira Nordeste 2026', 'chamada': 'Provou? Conte o que achou.',
                 'finalidade': 'avaliacao_feira', 'origem': 'feira', 'campanha': 'nordeste_2026',
                 'posicao': 'estande_b'}
        corpo.update(extra)
        return self.app().post('/api/admin/qr/codigos', json=corpo, headers=self.H)

    def test_criar_gera_codigo_opaco_unico_e_url_canonica(self):
        r = self.criar()
        self.assertEqual(r.status_code, 201)
        novo = r.get_json()['qr']
        self.assertRegex(novo['codigo_publico'], r'^[a-hj-km-np-z2-9]{10}$')
        self.assertEqual(novo['slug'], 'feira_nordeste_2026')
        self.assertEqual(novo['url'], 'https://maranhaocordial.com.br/q/' + novo['codigo_publico'])
        self.assertEqual(self.contar('qr_codigos'), 5)
        # E já funciona publicamente.
        self.assertEqual(self.app().get('/api/qr/' + novo['codigo_publico']).status_code, 200)

    def test_slug_repetido_e_recusado(self):
        self.criar()
        self.assertEqual(self.criar().status_code, 409)

    def test_validacoes_de_criacao(self):
        for extra, campo in ((dict(finalidade='outra'), 'finalidade'), (dict(chamada='x'), 'chamada'),
                             (dict(nome=''), 'nome'), (dict(slug='Com Espaço'), 'slug'),
                             (dict(destino_tipo='redirecionar'), 'destino_url'),
                             (dict(destino_tipo='redirecionar', destino_url='http://inseguro.com'), 'destino_url'),
                             (dict(destino_tipo='redirecionar', destino_url='javascript:alert(1)'), 'destino_url'),
                             (dict(destino_tipo='redirecionar', destino_url='https://user:pass@x.com'), 'destino_url')):
            r = self.criar(**extra)
            self.assertEqual((r.status_code, r.get_json().get('campo')), (400, campo), extra)

    def test_vinculo_com_sku_inexistente_e_recusado_e_com_sku_real_funciona(self):
        r = self.criar(sku='NAO-EXISTE')
        self.assertEqual((r.status_code, r.get_json()['error']), (400, 'vinculo_invalido'))
        self.run_sql("INSERT INTO mi_skus(id,sku,produto_nome) VALUES(%s,'MC-200ML','Guaraná e Gengibre 200 mL')", (str(uuid4()),))
        r = self.criar(sku='mc-200ml', nome='Embalagem 200 mL')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()['qr']['sku'], 'MC-200ML')

    def test_sinais_de_um_qr_com_sku_carregam_o_sku(self):
        self.run_sql("INSERT INTO mi_skus(id,sku,produto_nome) VALUES(%s,'MC-200ML','Guaraná e Gengibre 200 mL')", (str(uuid4()),))
        novo = self.criar(sku='MC-200ML', nome='Embalagem 200 mL').get_json()['qr']
        self.app().post(f"/api/qr/{novo['codigo_publico']}/scan", json={'chave': str(uuid4())})
        self.assertEqual(self.run_sql("SELECT sku FROM mi_sinais WHERE tipo_evento='qr_scan'")[0]['sku'], 'MC-200ML')

    def test_alterar_o_destino_nao_muda_o_codigo_impresso(self):
        antes = self.codigo('divulgacao_digital')
        qr_id = self.run_sql("SELECT id FROM qr_codigos WHERE slug='divulgacao_digital'")[0]['id']
        r = self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H,
                             json={'destino_tipo': 'redirecionar', 'destino_url': 'https://maranhaocordial.com.br/apresentacao'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.codigo('divulgacao_digital'), antes)
        publico = self.app().get('/api/qr/' + antes).get_json()['qr']
        self.assertEqual((publico['destino_tipo'], publico['destino_url']),
                         ('redirecionar', 'https://maranhaocordial.com.br/apresentacao'))
        # E volta para a página sem reimprimir nada.
        self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={'destino_tipo': 'pagina'})
        self.assertIsNone(self.app().get('/api/qr/' + antes).get_json()['qr']['destino_url'])

    def test_codigo_slug_e_finalidade_nao_sao_editaveis(self):
        qr_id = self.run_sql("SELECT id FROM qr_codigos WHERE slug='divulgacao_digital'")[0]['id']
        for campo in ('codigo_publico', 'slug', 'finalidade', 'id', 'sku'):
            r = self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={campo: 'x'})
            self.assertEqual((r.status_code, r.get_json()['error']), (400, 'campo_nao_editavel'), campo)

    def test_pausar_tira_o_codigo_do_ar_e_reativar_devolve(self):
        c = self.codigo('produto_embalagem')
        qr_id = self.run_sql("SELECT id FROM qr_codigos WHERE slug='produto_embalagem'")[0]['id']
        self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={'estado': 'pausado'})
        self.assertEqual(self.app().get('/api/qr/' + c).status_code, 404)
        self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={'estado': 'ativo'})
        self.assertEqual(self.app().get('/api/qr/' + c).status_code, 200)

    def test_revogado_e_definitivo(self):
        qr_id = self.run_sql("SELECT id FROM qr_codigos WHERE slug='produto_embalagem'")[0]['id']
        self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={'estado': 'revogado'})
        r = self.app().patch(f'/api/admin/qr/codigos/{qr_id}', headers=self.H, json={'estado': 'ativo'})
        self.assertEqual((r.status_code, r.get_json()['error']), (409, 'codigo_revogado_e_imutavel'))

    def test_lista_traz_os_codigos_e_as_urls(self):
        codigos = self.app().get('/api/admin/qr/codigos', headers=self.H).get_json()['codigos']
        self.assertEqual(len(codigos), 4)
        for c in codigos:
            self.assertTrue(c['url'].endswith('/q/' + c['codigo_publico']))

    def test_arquivos_svg_png_e_pdf_sao_gerados_e_o_png_e_o_svg_carregam_o_mesmo_codigo(self):
        qr_id = self.run_sql("SELECT id FROM qr_codigos WHERE slug='softdrinks_tech_2026'")[0]['id']
        esperado = 'https://maranhaocordial.com.br/q/' + self.codigo('softdrinks_tech_2026')
        tipos = {'svg': 'image/svg+xml', 'png': 'image/png', 'pdf': 'application/pdf'}
        for formato, mime in tipos.items():
            r = self.app().get(f'/api/admin/qr/codigos/{qr_id}/arquivo?formato={formato}', headers=self.H)
            self.assertEqual(r.status_code, 200, formato)
            self.assertEqual(r.headers['Content-Type'], mime)
            self.assertIn(f'qr_softdrinks_tech_2026.{formato}', r.headers['Content-Disposition'])
        png = self.app().get(f'/api/admin/qr/codigos/{qr_id}/arquivo?formato=png', headers=self.H).data
        import io
        import zxingcpp
        from PIL import Image
        self.assertEqual([b.text for b in zxingcpp.read_barcodes(Image.open(io.BytesIO(png)))], [esperado])
        self.assertEqual(self.app().get(f'/api/admin/qr/codigos/{qr_id}/arquivo?formato=gif', headers=self.H).status_code, 400)


class Painel(QRPostgres):
    H = {'X-Admin-Key': 'teste'}

    def test_sem_dados_nao_inventa_numero(self):
        p = self.app().get('/api/admin/qr/painel', headers=self.H).get_json()
        self.assertEqual(p['avaliacoes']['n'], 0)
        self.assertIsNone(p['avaliacoes']['nota_media'])
        self.assertIsNone(p['avaliacoes']['pct_aceita_59'])
        self.assertIsNone(p['avaliacoes']['pct_intencao_positiva'])
        self.assertIsNone(p['comparacao']['feira']['nota_media'])
        self.assertTrue(p['avaliacoes']['amostra_pequena'])
        self.assertEqual(p['por_perfil'], [])
        self.assertEqual(p['comentarios_recentes'], [])
        for linha in p['por_qr']:
            self.assertEqual((linha['scans'], linha['concluidas']), (0, 0))
            self.assertIsNone(linha['conversao_avaliacao'], 'sem scan não há conversão — não 0%')

    def popular(self):
        feira, produto = self.codigo('softdrinks_tech_2026'), self.codigo('produto_embalagem')
        cliente = self.app()
        for _ in range(4):
            cliente.post(f'/api/qr/{feira}/scan', json={'chave': str(uuid4())})
        cliente.post(f'/api/qr/{produto}/scan', json={'chave': str(uuid4())})
        cliente.post(f'/api/qr/{feira}/avaliacao', json=corpo_avaliacao(nota=10, perfil='consumidor',
                     faixa_preco='59_69', intencao_compra='certamente'))
        cliente.post(f'/api/qr/{feira}/avaliacao', json=corpo_avaliacao(nota=8, perfil='consumidor',
                     faixa_preco='40_49', intencao_compra='nao', comentario='Um pouco doce.'))
        cliente.post(f'/api/qr/{feira}/avaliacao', json=corpo_avaliacao(nota=6, perfil='bartender',
                     faixa_preco='70_ou_mais', intencao_compra='talvez'))
        cliente.post(f'/api/qr/{produto}/avaliacao', json=corpo_avaliacao(nota=4, perfil='consumidor',
                     faixa_preco='ate_39', intencao_compra='nao'))
        cliente.post(f'/api/qr/{feira}/contato', json=corpo_contato(interesse='proposta'))
        cliente.post(f'/api/qr/{feira}/contato', json=corpo_contato(interesse='comprar', whatsapp='', email='c@c.com', perfil='consumidor', nome='Cliente Comum'))
        return cliente

    def painel(self, **q):
        return self.app().get('/api/admin/qr/painel', headers=self.H, query_string=q).get_json()

    def test_funil_por_qr(self):
        self.popular()
        p = self.painel()
        f = next(l for l in p['por_qr'] if l['slug'] == 'softdrinks_tech_2026')
        self.assertEqual((f['scans'], f['iniciadas'], f['concluidas'], f['contatos'], f['leads']), (4, 3, 3, 2, 2))
        self.assertEqual(f['conversao_avaliacao'], 75.0)
        self.assertEqual(f['oportunidades'], 1, 'só a proposta é oportunidade; comprar é contado à parte')
        produto = next(l for l in p['por_qr'] if l['slug'] == 'produto_embalagem')
        self.assertEqual((produto['scans'], produto['concluidas']), (1, 1))

    def test_notas_intencao_e_aceitacao_de_59_com_amostra(self):
        a = self.popular() and self.painel()['avaliacoes']
        self.assertEqual(a['n'], 4)
        self.assertEqual(a['nota_media'], 7.0)
        self.assertEqual(a['pct_intencao_positiva'], 25.0)
        self.assertEqual(a['aceita_59'], 2)
        self.assertEqual(a['pct_aceita_59'], 50.0)
        self.assertTrue(a['amostra_pequena'], '4 avaliações não sustentam percentual — o painel tem de avisar')
        self.assertEqual(a['distribuicao_notas'], {'4': 1, '6': 1, '8': 1, '10': 1})

    def test_percepcao_sensorial_por_atributo_com_amostra(self):
        self.popular()
        s = self.painel()['avaliacoes']['sensorial']
        self.assertEqual(set(s), set(qr.ATRIBUTOS_SENSORIAIS))
        self.assertEqual((s['docura']['alto'], s['docura']['n']), (4, 4))
        self.assertEqual(s['docura']['pct']['alto'], 100.0)
        self.assertEqual(s['guarana']['ideal'], 4)

    def test_comparacao_feira_x_outras_origens(self):
        self.popular()
        c = self.painel()['comparacao']
        self.assertEqual((c['feira']['n'], c['feira']['nota_media']), (3, 8.0))
        self.assertEqual((c['outras_origens']['n'], c['outras_origens']['nota_media']), (1, 4.0))
        self.assertIn('fora da feira', c['descricao_outras_origens'])

    def test_desempenho_por_perfil(self):
        self.popular()
        perfis = {l['perfil']: l for l in self.painel()['por_perfil']}
        self.assertEqual(perfis['consumidor']['n'], 3)
        self.assertEqual(perfis['bartender']['n'], 1)
        self.assertEqual(perfis['bartender']['pct_aceita_59'], 100.0)

    def test_contatos_e_leads_por_interesse(self):
        self.popular()
        c = self.painel()['contatos']
        self.assertEqual(c['total'], 2)
        self.assertEqual(c['por_interesse']['proposta'], {'contatos': 1, 'leads': 1})
        self.assertEqual(c['por_interesse']['comprar'], {'contatos': 1, 'leads': 1})

    def test_comentarios_recentes_sem_dado_de_contato(self):
        self.popular()
        comentarios = self.painel()['comentarios_recentes']
        self.assertTrue(any(c['comentario'] == 'Um pouco doce.' for c in comentarios))
        texto = str(comentarios)
        for pessoal in ('Marina', 'marina@bar.com', '99000'):
            self.assertNotIn(pessoal, texto)

    def test_painel_nunca_expoe_dado_pessoal(self):
        self.popular()
        texto = str(self.painel())
        for pessoal in ('Marina Costa', 'marina@bar.com', TELEFONE_E164, 'Bar Central', 'Cliente Comum', 'c@c.com'):
            self.assertNotIn(pessoal, texto)

    def test_filtro_de_periodo(self):
        self.popular()
        self.run_sql("UPDATE qr_avaliacoes SET criado_em = NOW() - INTERVAL '40 days' WHERE nota IN (10, 8)")
        self.assertEqual(self.painel()['avaliacoes']['n'], 4)
        self.assertEqual(self.painel(dias=7)['avaliacoes']['n'], 2)
        self.assertEqual(self.app().get('/api/admin/qr/painel?dias=abc', headers=self.H).status_code, 400)
        self.assertEqual(self.app().get('/api/admin/qr/painel?dias=0', headers=self.H).status_code, 400)

    def test_aviso_de_amostra_minima_some_com_amostra_suficiente(self):
        feira = self.codigo('softdrinks_tech_2026')
        with patch.dict(qr.LIMITE_POR_MINUTO, {'avaliacao': 10_000}):
            for _ in range(qr.AMOSTRA_MINIMA):
                self.app().post(f'/api/qr/{feira}/avaliacao', json=corpo_avaliacao())
        a = self.painel()['avaliacoes']
        self.assertEqual(a['n'], qr.AMOSTRA_MINIMA)
        self.assertFalse(a['amostra_pequena'])

    def test_sinais_emitidos_batem_com_o_painel(self):
        self.popular()
        self.assertEqual(len(self.sinais('avaliacao_concluida')), self.painel()['avaliacoes']['n'])
        self.assertEqual(len(self.sinais('qr_scan')), sum(l['scans'] for l in self.painel()['por_qr']))


class Migration(QRPostgres):
    def test_catalogo_das_tabelas_e_indices(self):
        tabelas = {l['tablename'] for l in self.run_sql('SELECT tablename FROM pg_tables WHERE schemaname=%s', (self.schema,))}
        self.assertTrue({'qr_codigos', 'qr_eventos', 'qr_avaliacoes', 'qr_contatos'} <= tabelas)
        indices = {l['indexname'] for l in self.run_sql('SELECT indexname FROM pg_indexes WHERE schemaname=%s', (self.schema,))}
        self.assertTrue({'qr_codigos_codigo_publico_unico', 'qr_codigos_slug_unico'} <= indices)

    def test_restricoes_do_banco_impedem_dado_invalido_mesmo_sem_a_aplicacao(self):
        import psycopg2
        qr_id = self.run_sql("SELECT id FROM qr_codigos LIMIT 1")[0]['id']
        for consulta, args in (
            ("INSERT INTO qr_codigos(codigo_publico,slug,nome,chamada,finalidade,origem) VALUES('x','y','n','c','invalida','o')", ()),
            ("INSERT INTO qr_codigos(codigo_publico,slug,nome,chamada,finalidade,origem,destino_tipo) VALUES('x','y','n','c','comercial','o','redirecionar')", ()),
            ("INSERT INTO qr_contatos(id,qr_id,chave,interesse,consentimento_contato,texto_consentimento_versao) VALUES(%s,%s,%s,'comprar',FALSE,'v')",
             (str(uuid4()), str(qr_id), str(uuid4()))),
        ):
            with self.assertRaises(psycopg2.errors.CheckViolation):
                self.run_sql(consulta, args)


if __name__ == '__main__':
    unittest.main()
