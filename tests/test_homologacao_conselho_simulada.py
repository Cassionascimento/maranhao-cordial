"""Homologação SIMULADA do Conselho autônomo (modo observador).

Não existe banco de homologação nem OPENAI_API_KEY configurados nesta
sessão (confirmado antes de escrever este arquivo -- sem DATABASE_URL,
sem .env, nenhuma referência a staging no repositório). Por isso este
arquivo NÃO é uma homologação real -- é uma simulação: um Postgres falso
mínimo (só o suficiente para as consultas que o código realmente emite,
nada de motor SQL genérico) e um cliente OpenAI falso (respostas
determinísticas por agente), amarrando o código REAL (mi_conselho_gatilho
-- estendido NESTA etapa para reconhecer sinais comerciais reais além de
produção -- mi_conselho_orquestrador, mi_conselho_executor e mi_conselho,
estes três inalterados) numa única rodada de ponta a ponta.

O que isto prova: que a fiação entre os módulos está correta (detector
lê -> classifica -> executa -> consolida -> registra), com sinais reais
de produção, comercial e ruído ao mesmo tempo, sem nenhuma chamada de
rede real, sem nenhum banco real e sem nenhuma ação externa.

O que isto NÃO prova: nada sobre o comportamento do Postgres real (locks,
constraints, performance) nem sobre a qualidade real de um modelo OpenAI
de verdade -- essas exigem o banco de homologação e a chave que não
existem aqui.
"""
import json
import unittest
from types import SimpleNamespace

import mi_conselho_executor as executor
import mi_conselho_gatilho as gatilho
from mi_conselho_orquestrador import contem_credencial


# =====================================================
# Postgres falso -- só os padrões de SQL que o código realmente emite.
# Qualquer consulta não reconhecida levanta erro (nunca falha em silêncio).
# =====================================================

class FakeDB:
    def __init__(self):
        self.sinais = []
        self.auditoria = []
        self.registros = {}


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self._resultado = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        s = ' '.join(sql.split())
        params = params or ()

        if s.startswith('SET LOCAL'):
            self._resultado = []
            return

        if s.startswith('SELECT s.id, s.origem, s.tipo_evento'):
            origens, eventos, limite = params
            avaliados = {a['sinal_id'] for a in self.db.auditoria if a['evento'] in eventos}
            linhas = [r for r in self.db.sinais if r['origem'] in origens and r['id'] not in avaliados]
            linhas.sort(key=lambda r: r['criado_em'])
            self._resultado = [dict(r) for r in linhas[:limite]]
            return

        if s.startswith('SELECT payload FROM mi_sinais WHERE'):
            tipo_evento, chave1, chave2, antes_de = params
            candidatos = [r for r in self.db.sinais
                          if r['origem'] == 'producao' and r['tipo_evento'] == tipo_evento
                          and (r.get('sku') == chave1 or r.get('lote_id') == chave2)
                          and r['criado_em'] < antes_de]
            candidatos.sort(key=lambda r: r['criado_em'], reverse=True)
            self._resultado = [{'payload': candidatos[0]['payload']}] if candidatos else []
            return

        if s.startswith('INSERT INTO mi_sinais_auditoria'):
            sinal_id, evento, ator = params
            self.db.auditoria.append({'sinal_id': sinal_id, 'evento': evento, 'ator': ator})
            self._resultado = []
            return

        if s.startswith('INSERT INTO mi_conselho_registros'):
            novo_id, chave, digest = params[0], params[1], params[2]
            if chave in self.db.registros:
                self._resultado = []  # ON CONFLICT(chave) DO NOTHING -- já existe
            else:
                self.db.registros[chave] = {'id': novo_id, 'payload_hash': digest}
                self._resultado = [{'id': novo_id}]
            return

        if s.startswith('SELECT id, payload_hash FROM mi_conselho_registros WHERE chave'):
            row = self.db.registros.get(params[0])
            self._resultado = [{'id': row['id'], 'payload_hash': row['payload_hash']}] if row else []
            return

        raise AssertionError(f'SQL não simulado nesta homologação: {s[:150]}')

    def fetchone(self):
        return self._resultado[0] if self._resultado else None

    def fetchall(self):
        return list(self._resultado)


class FakeConn:
    def __init__(self, db):
        self.db = db

    def set_session(self, **_kw):
        pass

    def cursor(self, cursor_factory=None):
        return FakeCursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


# =====================================================
# Cliente OpenAI falso -- resposta determinística por persona, com dois
# desvios propositais (veto do Dicio, escalonamento da Rua) e uma falha
# proposital (Standard) para provar que o pipeline se comporta com
# segurança nesses três casos sem nenhuma chamada de rede real.
# =====================================================

NOMES_NA_PERSONA = {'Iris': 'iris', 'Leonard': 'leonard', 'Marie': 'marie', 'Rua': 'rua',
                     'Standard': 'standard', 'Dicio': 'dicio', 'Pirret': 'pirret', 'Zilda': 'zilda'}


def _agente_do_prompt(texto):
    for nome, codigo in NOMES_NA_PERSONA.items():
        if f'Você é **{nome}**' in texto:
            return codigo
    return None


def _parecer_padrao(agente):
    return {
        'dados_utilizados': f'sinal de produção analisado por {agente}',
        'conclusao': 'dentro do padrão esperado', 'confianca': 'media',
        'riscos': 'nenhum risco imediato identificado', 'divergencias': '',
        'acao_sugerida': 'acompanhar próxima leitura', 'necessidade_diretor': False,
        'motivo_diretor': '', 'veto': False, 'veto_motivo': None,
    }


class FakeRespostas:
    def __init__(self, contador):
        self.contador = contador

    def create(self, model, input, max_output_tokens, store, reasoning, text):
        self.contador['chamadas'] += 1
        self.contador['tokens_solicitados'] += max_output_tokens
        self.contador['prompts'].append(input)
        agente = _agente_do_prompt(input)
        self.contador['agentes_chamados'].append(agente)

        if agente == 'standard' and 'Custo de matéria-prima: 13.0' in input:
            self.contador['falhas_simuladas'] += 1
            raise TimeoutError('falha de LLM simulada -- prova que o pipeline não trava nem libera ação')

        parecer = _parecer_padrao(agente)
        if agente == 'dicio':
            parecer.update(conclusao='cor fora do padrão sem causa raiz documentada',
                            veto=True, veto_motivo='não conformidade sem plano de contenção',
                            necessidade_diretor=True, motivo_diretor='veto jurídico/regulatório')
        elif agente == 'rua' and 'Capacidade: 1100' in input:
            parecer.update(conclusao='aumento de capacidade exige turno extra não orçado',
                            necessidade_diretor=True, motivo_diretor='investimento em turno extra')
        return SimpleNamespace(output_text=json.dumps(parecer), status='completed', incomplete_details=None)


class FakeOpenAI:
    def __init__(self, contador):
        self.responses = FakeRespostas(contador)


def _sinal(id_, tipo_evento, criado_em, origem='producao', sku=None, lote_id=None,
           origem_id=None, payload=None, resultado=None):
    return {'id': id_, 'origem': origem, 'tipo_evento': tipo_evento, 'sku': sku,
            'lote_id': lote_id, 'origem_id': origem_id, 'payload': payload or {},
            'criado_em': criado_em, 'resultado': resultado}


class HomologacaoSimuladaConselho(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.contador = {'chamadas': 0, 'tokens_solicitados': 0, 'prompts': [],
                          'agentes_chamados': [], 'falhas_simuladas': 0}
        self.cliente = FakeOpenAI(self.contador)
        self.factory = lambda: FakeConn(self.db)

        t0, t1, t2 = '2026-09-13T09:00:00', '2026-09-13T10:00:00', '2026-09-13T11:00:00'

        # B) Produção -- baseline (t0) + leitura com mudança (t1) por série.
        self.db.sinais += [
            _sinal('p1', 'ph_medido', t0, sku='GUA-001', payload={'valor': 3.61}),
            _sinal('p2', 'ph_medido', t1, sku='GUA-001', payload={'valor': 3.92, 'codigo_lote': 'L10'}),
            _sinal('p3', 'brix_medido', t1, sku='GUA-001', payload={'valor': 12.0, 'codigo_lote': 'L10'}),
            _sinal('p4', 'custo_ingrediente', t0, sku='ACA-002', payload={'valor': 10.0}),
            _sinal('p5', 'custo_ingrediente', t1, sku='ACA-002', payload={'valor': 13.0, 'codigo_lote': 'L20'}),
            _sinal('p6', 'perda', t0, sku='ACA-002', payload={'valor': 2.0}),
            _sinal('p7', 'perda', t1, sku='ACA-002', payload={'valor': 6.0, 'codigo_lote': 'L20'}),
            _sinal('p8', 'capacidade', t0, sku='BAC-003', payload={'valor': 800}),
            _sinal('p9', 'capacidade', t1, sku='BAC-003', payload={'valor': 1100, 'codigo_lote': 'L30'}),
            _sinal('p10', 'nao_conformidade', t1, sku='BAC-003', payload={'descricao': 'cor fora do padrão', 'codigo_lote': 'L30'}),
        ]
        # C) Ruído -- abaixo do limiar, tipo não reconhecido, origem alheia,
        # e agora também ruído comercial ROTINEIRO (origem reconhecida,
        # mas o próprio tipo_evento continua sendo filtrado no Python).
        self.db.sinais += [
            _sinal('r1', 'ph_medido', t2, sku='GUA-001', payload={'valor': 3.95}),  # diff vs p2 (3.92) = 0.03 < 0.2
            _sinal('r3', 'temperatura_ambiente', t2, sku='GUA-001', payload={'valor': 25}),
            _sinal('r4', 'pagina_visitada', t2, origem='site', payload={}),
            _sinal('r5', 'lead_criado', t0, origem='crm', origem_id='lead-999'),
            _sinal('r6', 'prospecto_encontrado', t0, origem='prospeccao_fase57', origem_id='prospecto-999'),
            _sinal('r7', 'lead_estagio_mudou', t0, origem='crm', origem_id='lead-888',
                   payload={'estagio_anterior': 'novo', 'estagio_novo': 'contato'}),  # progressão rotineira de funil
        ]
        # A) Comercial -- CORRIGIDO nesta etapa: lead_qualificado, mudança
        # material de estágio e a "oportunidade parada" real (prospecto_
        # priorizado/descartado, já emitidos por fase57 -- oportunidade_
        # parada em si é conceito de mi_decisao.py, não um tipo_evento de
        # mi_sinais, então não é usado aqui) agora são visíveis e avaliados.
        self.db.sinais += [
            _sinal('c1', 'lead_qualificado', t0, origem='crm', origem_id='lead-100'),
            _sinal('c2', 'lead_estagio_mudou', t0, origem='crm', origem_id='lead-200',
                   payload={'estagio_anterior': 'negociacao', 'estagio_novo': 'perdido'}),
            _sinal('c3', 'prospecto_descartado', t0, origem='prospeccao_fase57', origem_id='prospecto-300'),
        ]

    def test_A_sinais_comerciais_agora_sao_visiveis_e_avaliados_pelo_conselho(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        por_id = {r['sinal_id']: r for r in resultados}
        for id_ in ('c1', 'c2', 'c3'):
            self.assertIn(id_, por_id, f'{id_} deveria ter sido avaliado (visível), não ignorado')
            self.assertTrue(por_id[id_]['relevante'], id_)
            self.assertTrue(por_id[id_]['registro'][0]['success'], id_)

    def test_A_leonard_e_convocado_para_lead_qualificado(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        c1 = next(r for r in resultados if r['sinal_id'] == 'c1')
        self.assertIn('leonard', [p['agente'] for p in c1['pareceres']])

    def test_A_standard_e_convocado_para_lead_perdido_impacto_economico(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        c2 = next(r for r in resultados if r['sinal_id'] == 'c2')
        self.assertIn('standard', [p['agente'] for p in c2['pareceres']])

    def test_A_pirret_nunca_e_convocado_para_sinais_comerciais_sem_marketing(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        for id_ in ('c1', 'c2', 'c3'):
            r = next(x for x in resultados if x['sinal_id'] == id_)
            self.assertNotIn('pirret', [p['agente'] for p in r['pareceres']])

    def test_C_ruido_comercial_rotineiro_continua_sem_chegar_ao_llm(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        por_id = {r['sinal_id']: r for r in resultados}
        # r5/r6/r7 SÃO avaliados agora (origem reconhecida), mas o próprio
        # tipo_evento/estágio continua marcado como ruído -- nenhum vira LLM.
        for id_ in ('r5', 'r6', 'r7'):
            self.assertIn(id_, por_id)
            self.assertFalse(por_id[id_]['relevante'], id_)
            self.assertNotIn('demanda', por_id[id_])
            self.assertNotIn('pareceres', por_id[id_])

    def test_B_producao_convoca_especialistas_pertinentes_e_registra(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        por_id = {r['sinal_id']: r for r in resultados}

        self.assertEqual([p['agente'] for p in por_id['p1']['pareceres']], ['marie'])
        self.assertEqual(sorted(p['agente'] for p in por_id['p2']['pareceres']), ['iris', 'marie'])
        self.assertEqual([p['agente'] for p in por_id['p3']['pareceres']], ['marie'])
        self.assertEqual([p['agente'] for p in por_id['p4']['pareceres']], ['standard'])
        self.assertEqual([p['agente'] for p in por_id['p6']['pareceres']], ['standard'])
        self.assertEqual(sorted(p['agente'] for p in por_id['p7']['pareceres']), ['iris', 'standard'])
        self.assertEqual([p['agente'] for p in por_id['p8']['pareceres']], ['rua'])
        self.assertEqual(sorted(p['agente'] for p in por_id['p9']['pareceres']), ['iris', 'rua'])
        self.assertEqual([p['agente'] for p in por_id['p10']['pareceres']], ['dicio'])

        for id_ in ('p1', 'p2', 'p3', 'p4', 'p6', 'p7', 'p8', 'p9', 'p10'):
            self.assertTrue(por_id[id_]['registro'][0]['success'], id_)
            self.assertEqual(por_id[id_]['registro'][1], 201, id_)  # criado agora

    def test_B_dicio_veta_e_forca_diretor(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        p10 = next(r for r in resultados if r['sinal_id'] == 'p10')
        self.assertTrue(p10['pareceres'][0]['veto'])
        self.assertTrue(p10['pareceres'][0]['necessidade_diretor'])

    def test_B_rua_escalona_diretor_sem_veto(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        p9 = next(r for r in resultados if r['sinal_id'] == 'p9')
        parecer_rua = next(p for p in p9['pareceres'] if p['agente'] == 'rua')
        self.assertTrue(parecer_rua['necessidade_diretor'])
        self.assertFalse(parecer_rua['veto'])

    def test_B_falha_de_llm_e_segura_nao_trava_nem_vira_acao(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        p5 = next(r for r in resultados if r['sinal_id'] == 'p5')
        # Iris (chamada primeiro) teve sucesso; Standard falhou -- a falha
        # de um agente não derruba o outro nem impede o registro.
        self.assertEqual(self.contador['falhas_simuladas'], 1)
        self.assertEqual([e['agente'] for e in p5['erros']], ['standard'])
        self.assertEqual([p['agente'] for p in p5['pareceres']], ['iris'])
        self.assertTrue(p5['registro'][0]['success'])
        # A recomendação de Standard nunca foi obtida -- nada foi executado
        # em nome dele; o registro só documenta a falha como pendência.
        registro_id = p5['registro'][0]['id']
        registro_bruto = self.db.registros[str(next(
            k for k, v in self.db.registros.items() if v['id'] == registro_id))]
        self.assertIsNotNone(registro_bruto)

    def test_C_mudanca_abaixo_do_limiar_e_ignorada(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        r1 = next(r for r in resultados if r['sinal_id'] == 'r1')
        self.assertFalse(r1['relevante'])
        self.assertNotIn('demanda', r1)

    def test_C_tipo_evento_desconhecido_e_ignorado(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        r3 = next(r for r in resultados if r['sinal_id'] == 'r3')
        self.assertFalse(r3['relevante'])

    def test_C_sinal_repetido_nao_gera_nova_analise_na_segunda_rodada(self):
        primeira = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        chamadas_apos_primeira = self.contador['chamadas']
        self.assertGreater(chamadas_apos_primeira, 0)
        segunda = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        self.assertEqual(segunda, [])
        self.assertEqual(self.contador['chamadas'], chamadas_apos_primeira, 'segunda rodada não deve chamar LLM')

    def test_seguranca_nenhum_prompt_contem_credencial(self):
        executor.processar_e_registrar(self.factory, cliente=self.cliente)
        for prompt in self.contador['prompts']:
            self.assertFalse(contem_credencial(prompt), prompt[:200])

    def test_seguranca_nenhuma_chamada_usa_tools_ou_historico_compartilhado(self):
        # FakeRespostas.create só aceita os kwargs nomeados abaixo -- se o
        # código real passasse 'tools' ou 'previous_response_id', a
        # chamada já falharia aqui com TypeError (kwarg inesperado).
        executor.processar_e_registrar(self.factory, cliente=self.cliente)
        self.assertGreater(self.contador['chamadas'], 0)

    def test_seguranca_modo_observador_ativo_por_padrao_na_simulacao(self):
        self.assertTrue(executor.modo_observador_ativo())

    def test_custo_contagem_de_chamadas_e_agentes_por_demanda(self):
        resultados = executor.processar_e_registrar(self.factory, cliente=self.cliente)
        relevantes = [r for r in resultados if r['relevante']]
        descartados_antes_do_llm = [r for r in resultados if not r['relevante']]

        # 10 sinais de produção + 3 comerciais relevantes = 13. Nenhum bate
        # o limite de 4 especialistas (máximo usado aqui é 3, em c2/c3).
        self.assertEqual(len(relevantes), 13)
        # r1 (limiar) + r3 (tipo desconhecido) + r5 (lead_criado, ruído) +
        # r6 (prospecto_encontrado, ruído) + r7 (progressão rotineira) = 5.
        self.assertEqual(len(descartados_antes_do_llm), 5)
        # Produção: p1:1 p4:1 p6:1 p8:1 + p2:2 p3:1 p5:2 p7:2 p9:2 p10:1 = 14.
        # Comercial: c1:2 (iris+leonard) c2:3 (iris+leonard+standard)
        # c3:3 (iris+leonard+standard) = 8. Total 22 (uma tentativa falha).
        self.assertEqual(self.contador['chamadas'], 22)
        self.assertEqual(self.contador['falhas_simuladas'], 1)
        self.assertEqual(self.contador['tokens_solicitados'], 22 * executor.MAX_OUTPUT_TOKENS)
        # Nenhuma demanda desta rodada chegou perto do teto de 4 especialistas.
        maior_grupo = max(len(r['pareceres']) + len(r['erros']) for r in relevantes)
        self.assertLessEqual(maior_grupo, executor.MAX_ESPECIALISTAS_POR_DEMANDA)
        self.assertEqual(maior_grupo, 3)


if __name__ == '__main__':
    unittest.main()
