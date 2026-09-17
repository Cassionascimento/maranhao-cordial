"""Opt-in: PostgreSQL real efêmero para a migration 022 (mi_operacoes.py,
Central Empresarial -- Operações Vivas). Mesmo cluster/disciplina de
tests/test_p5x_postgres_real.py: nunca usa DATABASE_URL, nunca produção.

P5X_POSTGRES_LOCAL=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python3 -m unittest tests.test_mi_operacoes_postgres_real
"""
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

import mi_artefatos as art
import mi_operacoes as op

SOCKET = '/tmp/p5x-postgres-data'
MIGRATIONS = ('016_mi_conselho.sql', '017_mi_conselho_registros_payload_hash.sql',
              '019_mi_artefatos.sql', '022_mi_operacoes.sql', '024_mi_operacao_compartilhamentos.sql')


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


def resposta_openai(**campos):
    import json
    base = {
        'dados_utilizados': 'contexto real da operação', 'conclusao': 'priorizar staff bilíngue',
        'confianca': 'media', 'riscos': 'clima chuvoso no dia 16', 'divergencias': '',
        'acao_sugerida': 'confirmar bartender até sexta', 'necessidade_diretor': False,
        'motivo_diretor': '', 'veto': False, 'veto_motivo': None,
    }
    base.update(campos)
    return MagicMock(output_text=json.dumps(base), status='completed', incomplete_details=None)


def cliente_mock(**campos):
    cliente = MagicMock()
    cliente.responses.create.return_value = resposta_openai(**campos)
    return cliente


@unittest.skipUnless(os.getenv('P5X_POSTGRES_LOCAL') == '1', 'requer cluster PostgreSQL local isolado')
class OperacoesVivasPostgresReal(unittest.TestCase):
    def setUp(self):
        self.schema = 'mi_operacoes_homolog_' + uuid4().hex
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
                for name in MIGRATIONS:
                    cur.execute(Path('migrations', name).read_text())
        conn.close()

    def rows(self, query, args=()):
        conn = self.factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, args)
                return cur.fetchall()
        finally:
            conn.close()

    def criar_operacao_softdrinks(self):
        resultado = op.criar_operacao(
            self.factory, titulo='Softdrinks Tech', data_inicio='2026-10-15', data_fim='2026-10-16',
            criado_por='diretor', local='AGUARDANDO DADOS', descricao='SYNTHETIC_TEST — caso canônico')
        self.assertTrue(resultado['success'])
        return resultado['operacao']['id']

    def test_migrations_reaplicadas_preservam_dados_indices_constraints(self):
        operacao_id = self.criar_operacao_softdrinks()
        self.apply()
        self.assertEqual(len(self.rows('SELECT * FROM mi_operacoes')), 1)
        indices = self.rows('SELECT indexname FROM pg_indexes WHERE schemaname=%s', (self.schema,))
        self.assertGreaterEqual(len(indices), 15)
        with self.assertRaises(psycopg2.errors.CheckViolation):
            conn = self.factory()
            with conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE mi_operacoes SET data_fim = data_inicio - 1 WHERE id=%s", (operacao_id,))
            conn.close()

    def test_ciclo_completo_operacao_viva_softdrinks_tech(self):
        operacao_id = self.criar_operacao_softdrinks()

        pessoa = op.adicionar_pessoa(self.factory, operacao_id, funcao='Bartender', ator='diretor',
                                      origem='agente', nome='AGUARDANDO DADOS')
        self.assertEqual(pessoa['pessoa']['estado'], 'sugerido')
        confirmada = op.atualizar_estado_pessoa(self.factory, pessoa['pessoa']['id'], 'confirmado', ator='diretor')
        self.assertEqual(confirmada['pessoa']['estado'], 'confirmado')

        item = op.adicionar_item(self.factory, operacao_id, titulo='Montar bar', ator='diretor',
                                  data_prevista='2026-10-15')
        op.atualizar_item(self.factory, item['item']['id'], {'status': 'concluido'}, ator='diretor')
        itens = op.listar_itens(self.factory, operacao_id)
        self.assertEqual(itens[0]['status'], 'concluido')

        pergunta = op.criar_pergunta_brainstorm(
            self.factory, operacao_id, pergunta='Como reduzir risco de chuva no dia 16?', ator='diretor')
        executado = op.executar_brainstorm(self.factory, pergunta['brainstorm']['id'], ['rua'],
                                            ator='diretor', cliente=cliente_mock())
        self.assertTrue(executado['success'])
        self.assertEqual(executado['brainstorm']['status'], 'respondido')
        self.assertIn('confirmar bartender até sexta', executado['brainstorm']['resposta']['recomendacao'])
        self.assertEqual(len(self.rows('SELECT * FROM mi_conselho_registros')), 1)

        decidido = op.decidir_brainstorm(self.factory, pergunta['brainstorm']['id'], 'transformar_em_tarefa',
                                          ator='diretor')
        self.assertTrue(decidido['success'])
        self.assertEqual(len(op.listar_itens(self.factory, operacao_id)), 2)

        op.upsert_metrica(self.factory, operacao_id, nome='CAC', ator='diretor')
        metricas = op.listar_metricas(self.factory, operacao_id)
        self.assertEqual(metricas[0]['estado_dado'], 'aguardando_dados')
        self.assertIsNone(metricas[0]['valor'])

        op.adicionar_lancamento_financeiro(self.factory, operacao_id, categoria='staff', tipo='orcamento',
                                            valor_centavos=500000, ator='diretor', fonte='planilha aprovada',
                                            estado_dado='confirmado')
        resumo = op.resumo_financeiro(self.factory, operacao_id)
        self.assertEqual(resumo['totais_centavos']['orcamento'], 500000)
        self.assertEqual(resumo['totais_centavos']['realizado'], 0)

        artefato = art.registrar_artefato(self.factory, artifact_type='IMAGE', conteudo=b'teste-visual',
                                           mime_type='image/png', metadata={'confidence': 'SYNTHETIC_TEST'})
        vinculo = op.vincular_artefato(self.factory, operacao_id, artefato['id'], ator='diretor', categoria='visual')
        self.assertTrue(vinculo['success'])
        arquivos = op.listar_arquivos(self.factory, operacao_id)
        self.assertEqual(arquivos[0]['artifact_type'], 'IMAGE')
        duplicado = op.vincular_artefato(self.factory, operacao_id, artefato['id'], ator='diretor')
        self.assertFalse(duplicado['success'])

        auditoria = op.listar_auditoria(self.factory, operacao_id)
        entidades = {linha['entidade'] for linha in auditoria}
        self.assertEqual(entidades, {'operacao', 'pessoa', 'item', 'brainstorm', 'metrica', 'financeiro', 'arquivo'})

        investidor = op.visao_investidor(self.factory, operacao_id)
        bruto = str(investidor)
        self.assertNotIn('telefone', investidor['equipe_resumo'][0] if investidor['equipe_resumo'] else {})
        self.assertNotIn('senha', bruto.lower())
        self.assertNotIn('token', bruto.lower())

    def test_brainstorm_sem_credencial_openai_falha_fechado_nunca_fabrica_parecer(self):
        operacao_id = self.criar_operacao_softdrinks()
        pergunta = op.criar_pergunta_brainstorm(self.factory, operacao_id, pergunta='Teste', ator='diretor')
        cliente_sem_credencial = MagicMock()
        cliente_sem_credencial.responses.create.side_effect = RuntimeError('sem credencial OpenAI configurada')
        resultado = op.executar_brainstorm(self.factory, pergunta['brainstorm']['id'], ['rua'],
                                            ator='diretor', cliente=cliente_sem_credencial)
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'conselho_indisponivel')
        aguardando = op.listar_brainstorm(self.factory, operacao_id)
        self.assertEqual(aguardando[0]['status'], 'aguardando')

    def test_operacao_com_data_fim_antes_do_inicio_e_rejeitada_pelo_banco(self):
        conn = self.factory()
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO mi_operacoes (id, titulo, data_inicio, data_fim, criado_por) "
                        "VALUES (%s,'x','2026-10-16','2026-10-15','teste')", (str(uuid4()),))
        conn.close()

    def test_excluir_operacao_remove_em_cascata_sem_orfaos(self):
        operacao_id = self.criar_operacao_softdrinks()
        op.adicionar_pessoa(self.factory, operacao_id, funcao='Staff', ator='diretor')
        op.adicionar_item(self.factory, operacao_id, titulo='Tarefa', ator='diretor')
        conn = self.factory()
        with conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM mi_operacoes WHERE id=%s', (operacao_id,))
        conn.close()
        self.assertEqual(self.rows('SELECT * FROM mi_operacao_pessoas'), [])
        self.assertEqual(self.rows('SELECT * FROM mi_operacao_itens'), [])

    def test_compartilhamento_investidor_ciclo_completo_criar_acessar_revogar(self):
        operacao_id = self.criar_operacao_softdrinks()
        op.adicionar_pessoa(self.factory, operacao_id, funcao='Bartender', ator='diretor',
                             nome='Fulano', telefone='11999999999')
        criado = op.criar_compartilhamento_investidor(self.factory, operacao_id, ator='diretor')
        self.assertTrue(criado['success'])
        token = criado['compartilhamento']['token']

        visao = op.visao_investidor_por_token(self.factory, token)
        self.assertIsNotNone(visao)
        self.assertEqual(visao['operacao']['titulo'], 'Softdrinks Tech')
        self.assertNotIn('telefone', visao['equipe_resumo'][0])

        compartilhamentos = op.listar_compartilhamentos(self.factory, operacao_id)
        self.assertEqual(compartilhamentos[0]['total_acessos'], 1)
        self.assertIsNotNone(compartilhamentos[0]['ultimo_acesso_em'])

        revogado = op.revogar_compartilhamento_investidor(self.factory, token, ator='diretor')
        self.assertTrue(revogado['success'])
        self.assertIsNone(op.visao_investidor_por_token(self.factory, token))

        auditoria = {a['acao'] for a in op.listar_auditoria(self.factory, operacao_id) if a['entidade'] == 'compartilhamento'}
        self.assertEqual(auditoria, {'criado', 'revogado'})

    def test_token_de_uma_operacao_nao_acessa_outra(self):
        op1 = self.criar_operacao_softdrinks()
        op2 = op.criar_operacao(self.factory, titulo='Outra Operação', data_inicio='2027-01-01',
                                 data_fim='2027-01-02', criado_por='diretor')['operacao']['id']
        criado = op.criar_compartilhamento_investidor(self.factory, op1, ator='diretor')
        visao = op.visao_investidor_por_token(self.factory, criado['compartilhamento']['token'])
        self.assertEqual(visao['operacao']['id'], op1)
        self.assertNotEqual(visao['operacao']['id'], op2)

    def test_token_revogado_nunca_incrementa_acesso(self):
        operacao_id = self.criar_operacao_softdrinks()
        criado = op.criar_compartilhamento_investidor(self.factory, operacao_id, ator='diretor')
        token = criado['compartilhamento']['token']
        op.revogar_compartilhamento_investidor(self.factory, token, ator='diretor')
        self.assertIsNone(op.visao_investidor_por_token(self.factory, token))
        compartilhamentos = op.listar_compartilhamentos(self.factory, operacao_id)
        self.assertEqual(compartilhamentos[0]['total_acessos'], 0)


if __name__ == '__main__':
    unittest.main()
