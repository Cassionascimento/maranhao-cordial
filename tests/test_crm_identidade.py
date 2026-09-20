"""Identidade única do contato entre canais, contra SQL real e isolado.

O que precisa ficar provado: o sistema reconhece o mesmo contato vindo de
canais diferentes, NÃO inventa fusão quando há ambiguidade, e nunca apaga
um cadastro ao fundir.
"""
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crm_identidade as ci
from crm_identidade import IdentidadePendente

ESQUEMA = '''
CREATE TABLE leads_crm(
  id TEXT PRIMARY KEY, nome TEXT, empresa TEXT, tipo_lead TEXT NOT NULL,
  origem TEXT NOT NULL, canal TEXT, telefone TEXT, email TEXT, contato TEXT,
  categoria_contato TEXT, arquivado BOOLEAN DEFAULT FALSE,
  contato_interno BOOLEAN DEFAULT FALSE, cadastro_teste BOOLEAN DEFAULT FALSE,
  fundido_em_lead_id TEXT, fundido_em TEXT, fundido_por TEXT);
CREATE TABLE interacoes_omnichannel(
  id TEXT PRIMARY KEY, canal TEXT, plataforma TEXT, sender_id TEXT, recipient_id TEXT,
  message_id TEXT UNIQUE, texto TEXT, tipo_interacao TEXT, classificacao TEXT,
  interesse TEXT, lead_id TEXT REFERENCES leads_crm(id), processado_ia BOOLEAN DEFAULT FALSE,
  arquivado BOOLEAN DEFAULT FALSE, criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
  atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP);
'''


class _Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        sql = sql.replace('%s', '?')
        sql = re.sub(r'::text', '', sql)
        sql = sql.replace("contato ~ ", "contato REGEXP ")
        sql = sql.replace('array_agg(id ORDER BY id)', 'group_concat(id)')
        self.cur = self.db.execute(sql, list(args))

    def fetchone(self):
        linha = self.cur.fetchone()
        return dict(linha) if linha else None

    def fetchall(self):
        return [dict(l) for l in self.cur.fetchall()]


class Banco:
    """SQL de verdade, dialeto adaptado. Não valida o catálogo PostgreSQL."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'crm.db')
        conn = sqlite3.connect(self.path)
        conn.executescript(ESQUEMA)
        # Migration 027 carregada do arquivo real; só as partes que o SQLite
        # entende (ALTER ... IF NOT EXISTS já está no esquema acima).
        bruto = Path('migrations/027_crm_identidades_canal.sql').read_text()
        # Comentários vêm colados no primeiro comando; sem removê-los, o
        # CREATE TABLE inicial passaria despercebido.
        bruto = '\n'.join(l for l in bruto.splitlines() if not l.strip().startswith('--'))
        for comando in bruto.split(';'):
            limpo = comando.strip()
            if not limpo.upper().startswith('CREATE'):
                continue
            conn.executescript(
                limpo.replace('BIGSERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
                     .replace('DEFAULT NOW()', 'DEFAULT CURRENT_TIMESTAMP')
                     .replace('UUID', 'TEXT').replace(' ON DELETE CASCADE', '') + ';')
        conn.close()

    def conectar(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.create_function('regexp_replace', 4, lambda t, p, r, f: re.sub(p, r, t or ''))
        db.create_function('regexp', 2, lambda p, t: bool(re.search(p, t or '')))
        db.create_function('NOW', 0, lambda: '2026-09-19 00:00:00')
        return db

    def cursor(self):
        self.db = self.conectar()
        return _Cursor(self.db)

    def rows(self, tabela):
        db = self.conectar()
        try:
            return [dict(l) for l in db.execute('SELECT * FROM ' + tabela)]
        finally:
            db.close()

    def close(self):
        self.temp.cleanup()


class _Base(unittest.TestCase):
    def setUp(self):
        self.banco = Banco()
        self.addCleanup(self.banco.close)
        self.cur = self.banco.cursor()
        self.addCleanup(lambda: self.banco.db.close())

    def lead(self, **campos):
        ident = campos.pop('id', str(uuid4()))
        colunas = {'id': ident, 'tipo_lead': 'outro', 'origem': 'site'}
        colunas.update(campos)
        nomes = ','.join(colunas)
        marcas = ','.join('?' * len(colunas))
        self.banco.db.execute(f'INSERT INTO leads_crm({nomes}) VALUES({marcas})', list(colunas.values()))
        self.banco.db.commit()
        return ident


class Normalizacao(unittest.TestCase):
    def test_telefone_vira_so_digitos(self):
        self.assertEqual(ci.normalizar('+55 (98) 99000-0000', 'telefone'), '5598990000000')
        self.assertEqual(ci.normalizar('5598990000000', 'telefone'), '5598990000000')

    def test_telefone_curto_demais_nao_identifica_ninguem(self):
        self.assertIsNone(ci.normalizar('99000', 'telefone'))
        self.assertIsNone(ci.normalizar('1234567890123456', 'telefone'))

    def test_email_vira_minusculo_e_precisa_ser_valido(self):
        self.assertEqual(ci.normalizar('  Contato@Bar.COM ', 'email'), 'contato@bar.com')
        self.assertIsNone(ci.normalizar('contato', 'email'))
        self.assertIsNone(ci.normalizar('contato@bar', 'email'))

    def test_vazio_e_nao_texto_nunca_casam(self):
        for valor in ('', '   ', None, 123, []):
            self.assertIsNone(ci.normalizar(valor, 'telefone'))
            self.assertIsNone(ci.normalizar(valor, 'email'))


class Resolucao(_Base):
    def test_encontra_pelo_telefone_nativo_em_formato_diferente(self):
        ident = self.lead(nome='Bar Central', telefone='+55 (98) 99000-0000')
        achado = ci.resolver(self.cur, canal='whatsapp', identificador='5598990000000', tipo='telefone')
        self.assertEqual(achado, ident)

    def test_encontra_pelo_email_ignorando_caixa(self):
        ident = self.lead(nome='Hotel', email='Reservas@Hotel.com')
        self.assertEqual(ci.resolver(self.cur, canal='gmail', identificador='reservas@hotel.com', tipo='email'), ident)

    def test_sem_correspondencia_devolve_none_sem_criar_nada(self):
        self.assertIsNone(ci.resolver(self.cur, canal='whatsapp', identificador='5511000000000', tipo='telefone'))
        self.assertEqual(self.banco.rows('leads_crm'), [])

    def test_dois_candidatos_param_para_revisao_humana(self):
        self.lead(nome='A', telefone='5598990000000')
        self.lead(nome='B', telefone='+55 98 99000-0000')
        with self.assertRaises(IdentidadePendente):
            ci.resolver(self.cur, canal='whatsapp', identificador='5598990000000', tipo='telefone')

    def test_contato_arquivado_ou_de_teste_exige_revisao(self):
        for campo in ('arquivado', 'contato_interno', 'cadastro_teste'):
            with self.subTest(campo=campo):
                banco = Banco()
                self.addCleanup(banco.close)
                cur = banco.cursor()
                banco.db.execute(
                    f'INSERT INTO leads_crm(id,tipo_lead,origem,telefone,{campo}) VALUES(?,?,?,?,?)',
                    (str(uuid4()), 'outro', 'site', '5598990000000', True))
                banco.db.commit()
                with self.assertRaises(IdentidadePendente):
                    ci.resolver(cur, canal='whatsapp', identificador='5598990000000', tipo='telefone')
                banco.db.close()

    def test_contato_ja_fundido_nao_e_mais_candidato(self):
        destino = self.lead(nome='Destino', telefone='5598990000000')
        self.lead(nome='Antigo', telefone='5598990000000', fundido_em_lead_id=destino)
        self.assertEqual(ci.resolver(self.cur, canal='whatsapp', identificador='5598990000000', tipo='telefone'), destino)


class Vinculo(_Base):
    def test_vinculo_e_idempotente(self):
        ident = self.lead(nome='Bar')
        primeiro = ci.vincular(self.cur, lead_id=ident, canal='whatsapp', identificador='5598990000000', tipo='telefone')
        segundo = ci.vincular(self.cur, lead_id=ident, canal='whatsapp', identificador='5598990000000', tipo='telefone')
        self.banco.db.commit()
        self.assertEqual(primeiro, segundo)
        self.assertEqual(len(self.banco.rows('crm_identidades_canal')), 1)

    def test_identidade_encontrada_pelo_vinculo_dispensa_busca_nativa(self):
        ident = self.lead(nome='Bar')
        ci.vincular(self.cur, lead_id=ident, canal='instagram', identificador='bar_central', tipo='usuario')
        self.banco.db.commit()
        self.assertEqual(ci.resolver(self.cur, canal='instagram', identificador='bar_central', tipo='usuario'), ident)

    def test_mesmo_identificador_em_canais_diferentes_nao_colide(self):
        ident = self.lead(nome='Bar')
        ci.vincular(self.cur, lead_id=ident, canal='whatsapp', identificador='5598990000000', tipo='telefone')
        ci.vincular(self.cur, lead_id=ident, canal='instagram', identificador='5598990000000', tipo='telefone')
        self.banco.db.commit()
        self.assertEqual(len(self.banco.rows('crm_identidades_canal')), 2)

    def test_identificador_disputado_por_dois_contatos_para_a_operacao(self):
        um = self.lead(nome='A')
        outro = self.lead(nome='B')
        ci.vincular(self.cur, lead_id=um, canal='whatsapp', identificador='5598990000000', tipo='telefone')
        self.banco.db.commit()
        with self.assertRaises(IdentidadePendente):
            ci.vincular(self.cur, lead_id=outro, canal='whatsapp', identificador='5598990000000', tipo='telefone')


class Fusao(_Base):
    def _par(self):
        destino = self.lead(nome='Bar Central', telefone='5598990000000')
        absorvido = self.lead(nome='Bar Central (site)', email='bar@central.com')
        ci.vincular(self.cur, lead_id=absorvido, canal='gmail', identificador='bar@central.com', tipo='email')
        self.banco.db.execute(
            'INSERT INTO interacoes_omnichannel(id,canal,message_id,texto,lead_id) VALUES(?,?,?,?,?)',
            (str(uuid4()), 'gmail', 'msg-1', 'Olá', absorvido))
        self.banco.db.commit()
        return destino, absorvido

    def test_fusao_move_historico_e_identidades_sem_apagar_o_cadastro(self):
        destino, absorvido = self._par()
        resultado = ci.fundir(self.cur, destino=destino, absorvido=absorvido,
                              motivo='mesma empresa, dois cadastros', ator='direcao')
        self.banco.db.commit()
        self.assertEqual(resultado['identidades_movidas'], 1)
        self.assertEqual(resultado['interacoes_movidas'], 1)
        self.assertEqual(self.banco.rows('interacoes_omnichannel')[0]['lead_id'], destino)
        # O cadastro absorvido continua existindo, marcado.
        absorvidos = [l for l in self.banco.rows('leads_crm') if l['id'] == absorvido]
        self.assertEqual(len(absorvidos), 1)
        self.assertEqual(absorvidos[0]['fundido_em_lead_id'], destino)

    def test_fusao_e_auditada(self):
        destino, absorvido = self._par()
        ci.fundir(self.cur, destino=destino, absorvido=absorvido, motivo='duplicata confirmada', ator='direcao')
        self.banco.db.commit()
        auditoria = self.banco.rows('crm_fusao_auditoria')
        self.assertEqual(len(auditoria), 1)
        self.assertEqual(auditoria[0]['motivo'], 'duplicata confirmada')
        self.assertEqual(auditoria[0]['ator'], 'direcao')

    def test_fusao_exige_motivo_e_recusa_o_mesmo_contato(self):
        destino, absorvido = self._par()
        for kwargs in ({'motivo': '', 'absorvido': absorvido}, {'motivo': 'x', 'absorvido': destino}):
            with self.assertRaises(ValueError):
                ci.fundir(self.cur, destino=destino, ator='direcao', **kwargs)

    def test_contato_ja_fundido_nao_funde_de_novo(self):
        destino, absorvido = self._par()
        ci.fundir(self.cur, destino=destino, absorvido=absorvido, motivo='primeira', ator='direcao')
        self.banco.db.commit()
        with self.assertRaises(ValueError):
            ci.fundir(self.cur, destino=destino, absorvido=absorvido, motivo='segunda', ator='direcao')

    def test_fusao_nunca_acontece_por_inferencia(self):
        """candidatos_de_fusao aponta; quem funde é a rota explícita."""
        fonte = Path('crm_identidade.py').read_text()
        trecho = fonte[fonte.index('def candidatos_de_fusao'):fonte.index('def fundir')]
        self.assertNotIn('UPDATE', trecho.upper())
        self.assertNotIn('INSERT', trecho.upper())
        self.assertNotIn('DELETE', trecho.upper())


class Historico(_Base):
    def test_linha_do_tempo_preserva_canal_e_tipo_de_cada_evento(self):
        ident = self.lead(nome='Bar')
        for canal, tipo, mid in (('whatsapp', 'mensagem', 'w-1'), ('gmail', 'email', 'g-1'),
                                 ('instagram', 'comentario', 'i-1')):
            self.banco.db.execute(
                'INSERT INTO interacoes_omnichannel(id,canal,tipo_interacao,message_id,texto,lead_id) '
                'VALUES(?,?,?,?,?,?)', (str(uuid4()), canal, tipo, mid, 'texto', ident))
        self.banco.db.commit()
        linha = ci.historico(self.cur, ident)
        self.assertEqual(len(linha), 3)
        self.assertEqual({e['canal'] for e in linha}, {'whatsapp', 'gmail', 'instagram'})
        self.assertEqual({e['tipo'] for e in linha}, {'mensagem', 'email', 'comentario'})

    def test_interacao_arquivada_fica_fora_da_linha_do_tempo(self):
        ident = self.lead(nome='Bar')
        self.banco.db.execute(
            'INSERT INTO interacoes_omnichannel(id,canal,message_id,texto,lead_id,arquivado) '
            'VALUES(?,?,?,?,?,?)', (str(uuid4()), 'whatsapp', 'w-9', 'oi', ident, True))
        self.banco.db.commit()
        self.assertEqual(ci.historico(self.cur, ident), [])


if __name__ == '__main__':
    unittest.main()
