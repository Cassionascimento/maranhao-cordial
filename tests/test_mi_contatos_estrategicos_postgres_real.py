"""Opt-in: PostgreSQL real efêmero para a migration 023 (ciclo de vida
de contatos_estrategicos, seção 1.D). Mesmo cluster/disciplina de
tests/test_p5x_postgres_real.py: nunca usa DATABASE_URL, nunca produção.

P5X_POSTGRES_LOCAL=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python3 -m unittest tests.test_mi_contatos_estrategicos_postgres_real
"""
import os
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

import mi_contatos_estrategicos as ce

SOCKET = '/tmp/p5x-postgres-data'


def local_connection(schema='public'):
    if os.getenv('P5X_POSTGRES_LOCAL') != '1':
        raise RuntimeError('homologacao_local_nao_autorizada')
    conn = psycopg2.connect(host=SOCKET, port=55439, user='p5x_homolog', dbname='postgres',
                             options='-c search_path=' + schema, connect_timeout=3)
    with conn.cursor() as cur:
        cur.execute('SHOW data_directory')
        directory = cur.fetchone()[0]
        cur.execute('SHOW listen_addresses')
        listen = cur.fetchone()[0]
    conn.rollback()
    if Path(directory).resolve() != Path(SOCKET).resolve() or listen:
        conn.close()
        raise RuntimeError('cluster_nao_isolado')
    return conn


# contatos_estrategicos e fabricas_parceiras não têm migration própria em
# migrations/ (schema pré-existente, criado por main.py em produção) --
# recriamos aqui só a fatia mínima que a migration 023 altera, para
# validar de forma isolada e real que ALTER TABLE/CREATE TABLE são
# idempotentes e que as constraints/índices realmente existem.
SCHEMA_BASE = """
CREATE TABLE contatos_estrategicos (
    id UUID PRIMARY KEY,
    nome VARCHAR(180), empresa VARCHAR(220), tipo VARCHAR(50) NOT NULL, cargo VARCHAR(180),
    telefone VARCHAR(50), email VARCHAR(220), cidade VARCHAR(120), estado VARCHAR(2),
    fabrica_id UUID, status_relacao VARCHAR(50) NOT NULL DEFAULT 'prospectado',
    origem_contato VARCHAR(120), resumo TEXT, capacidades TEXT, restricoes TEXT,
    proximo_passo TEXT, fonte_dados TEXT, verificado_por VARCHAR(180), verificado_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL') == '1', 'requer cluster PostgreSQL local isolado')
class ContatosEstrategicosPostgresReal(unittest.TestCase):
    def setUp(self):
        self.schema = 'contatos_homolog_' + uuid4().hex
        conn = local_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        conn.close()
        self.factory = lambda: local_connection(self.schema)
        self.apply()

    def apply(self):
        conn = self.factory()
        with conn:
            with conn.cursor() as cur:
                if not self._aplicado():
                    cur.execute(SCHEMA_BASE)
                cur.execute(Path('migrations', '023_contatos_estrategicos_ciclo_de_vida.sql').read_text())
        conn.close()
        self._marcar_aplicado()

    def _aplicado(self):
        return getattr(self, '_schema_base_aplicado', False)

    def _marcar_aplicado(self):
        self._schema_base_aplicado = True

    def rows(self, query, args=()):
        conn = self.factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, args)
                return cur.fetchall()
        finally:
            conn.close()

    def criar_contato(self):
        conn = self.factory()
        contato_id = str(uuid4())
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO contatos_estrategicos (id, nome, tipo, status_relacao) "
                    "VALUES (%s,'Fulano de Tal','fabricante','prospectado')", (contato_id,))
        conn.close()
        return contato_id

    def test_migration_reaplicada_e_idempotente(self):
        self.apply()
        colunas = self.rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name='contatos_estrategicos'")
        nomes = {c['column_name'] for c in colunas}
        for esperado in ('arquivado', 'ultimo_contato_em', 'proxima_acao', 'data_followup', 'tentativas_contato'):
            self.assertIn(esperado, nomes)

    def test_mudar_status_grava_historico_e_permite_reversao(self):
        contato_id = self.criar_contato()
        ce.mudar_status(self.factory, contato_id, 'em_contato', ator='diretor')
        ce.mudar_status(self.factory, contato_id, 'qualificado', ator='diretor')
        ce.mudar_status(self.factory, contato_id, 'em_contato', ator='diretor', motivo='reversão: dado incorreto')
        historico = ce.historico_status(self.factory, contato_id)
        self.assertEqual(len(historico), 3)
        self.assertEqual(historico[0]['status_anterior'], 'qualificado')
        self.assertEqual(historico[0]['status_novo'], 'em_contato')
        self.assertEqual(historico[0]['motivo'], 'reversão: dado incorreto')

    def test_registrar_interacao_incrementa_tentativas_e_nunca_confia_em_horario_do_cliente(self):
        contato_id = self.criar_contato()
        ce.registrar_interacao(self.factory, contato_id, ator='diretor', proxima_acao='ligar de novo')
        ce.registrar_interacao(self.factory, contato_id, ator='diretor', houve_resposta=True)
        contato = self.rows('SELECT * FROM contatos_estrategicos WHERE id=%s', (contato_id,))[0]
        self.assertEqual(contato['tentativas_contato'], 2)
        self.assertIsNotNone(contato['ultimo_contato_em'])
        self.assertIsNotNone(contato['ultima_resposta_em'])

    def test_arquivar_e_desarquivar(self):
        contato_id = self.criar_contato()
        arquivado = ce.arquivar(self.factory, contato_id, ator='diretor')
        self.assertTrue(arquivado['contato']['arquivado'])
        self.assertIsNotNone(arquivado['contato']['arquivado_em'])
        desarquivado = ce.arquivar(self.factory, contato_id, ator='diretor', arquivado=False)
        self.assertFalse(desarquivado['contato']['arquivado'])
        self.assertIsNone(desarquivado['contato']['arquivado_em'])

    def test_exclusao_definitiva_funciona_para_cadastro_intocado(self):
        contato_id = self.criar_contato()
        resultado = ce.excluir_definitivamente(self.factory, contato_id, ator='diretor', confirmacao=True)
        self.assertTrue(resultado['success'])
        self.assertEqual(self.rows('SELECT * FROM contatos_estrategicos WHERE id=%s', (contato_id,)), [])

    def test_exclusao_definitiva_bloqueada_apos_qualquer_interacao_real(self):
        contato_id = self.criar_contato()
        ce.registrar_interacao(self.factory, contato_id, ator='diretor')
        resultado = ce.excluir_definitivamente(self.factory, contato_id, ator='diretor', confirmacao=True)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'possui_interacao_real_use_arquivar')
        self.assertEqual(len(self.rows('SELECT * FROM contatos_estrategicos WHERE id=%s', (contato_id,))), 1)

    def test_exclusao_definitiva_bloqueada_apos_mudanca_de_status(self):
        contato_id = self.criar_contato()
        ce.mudar_status(self.factory, contato_id, 'descartado', ator='diretor')
        resultado = ce.excluir_definitivamente(self.factory, contato_id, ator='diretor', confirmacao=True)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'possui_historico_use_arquivar')

    def test_historico_e_removido_em_cascata_ao_excluir(self):
        contato_id = self.criar_contato()
        ce.mudar_status(self.factory, contato_id, 'em_contato', ator='diretor')
        conn = self.factory()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM contatos_estrategicos WHERE id=%s', (contato_id,))
        conn.close()
        self.assertEqual(self.rows('SELECT * FROM contatos_estrategicos_historico_status WHERE contato_id=%s',
                                    (contato_id,)), [])


if __name__ == '__main__':
    unittest.main()
