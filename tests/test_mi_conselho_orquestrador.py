import unittest

import mi_conselho_orquestrador as o
from mi_conselho import AGENTES


class CarregarPersona(unittest.TestCase):
    def test_carrega_o_corpo_de_cada_um_dos_8_agentes_sem_frontmatter(self):
        for agente in AGENTES:
            corpo = o.carregar_persona(agente)
            self.assertTrue(corpo.strip())
            self.assertFalse(corpo.startswith('---'))
            self.assertNotIn('\nname: ' + agente, corpo)

    def test_corpo_referencia_o_nome_do_agente(self):
        self.assertIn('Iris', o.carregar_persona('iris'))
        self.assertIn('Dicio', o.carregar_persona('dicio'))

    def test_agente_desconhecido_levanta_erro(self):
        with self.assertRaises(ValueError):
            o.carregar_persona('fulano')

    def test_nunca_copia_a_persona_para_outro_lugar_le_sempre_do_md_original(self):
        # Corrigir o .md e reler deve refletir a mudança -- prova de que
        # não existe uma cópia duplicada em cache/constante no orquestrador.
        import pathlib
        caminho = pathlib.Path(o._DIR_AGENTES) / 'iris.md'
        original = caminho.read_text(encoding='utf-8')
        try:
            caminho.write_text(original + '\nMARCA_DE_TESTE_UNICA', encoding='utf-8')
            self.assertIn('MARCA_DE_TESTE_UNICA', o.carregar_persona('iris'))
        finally:
            caminho.write_text(original, encoding='utf-8')


class ClassificarEspecialistas(unittest.TestCase):
    def test_demanda_vazia_levanta_erro(self):
        with self.assertRaises(ValueError):
            o.classificar_especialistas('')
        with self.assertRaises(ValueError):
            o.classificar_especialistas('   ')

    def test_marketing_convoca_pirret(self):
        r = o.classificar_especialistas('Precisamos avaliar uma nova campanha de marketing.')
        self.assertIn('pirret', r['selecionados'])
        self.assertNotIn('zilda', r['selecionados'])
        self.assertIn('zilda', r['excluidos'])

    def test_vendas_convoca_leonard(self):
        r = o.classificar_especialistas('Avaliar essa oportunidade de venda com o cliente novo.')
        self.assertIn('leonard', r['selecionados'])

    def test_preco_margem_convoca_standard_e_leonard_e_iris(self):
        r = o.classificar_especialistas('Analisar desconto e margem dessa venda para o cliente.')
        self.assertIn('standard', r['selecionados'])
        self.assertIn('leonard', r['selecionados'])
        self.assertIn('iris', r['selecionados'])  # >1 especialista de conteúdo -> Iris entra

    def test_produto_formula_com_risco_regulatorio_convoca_marie_e_dicio(self):
        r = o.classificar_especialistas('Mudar a fórmula do produto -- risco regulatório da ANVISA?')
        self.assertIn('marie', r['selecionados'])
        self.assertIn('dicio', r['selecionados'])

    def test_produto_formula_com_impacto_de_producao_convoca_marie_e_rua(self):
        r = o.classificar_especialistas('Mudar a embalagem do produto -- isso afeta a capacidade de produção?')
        self.assertIn('marie', r['selecionados'])
        self.assertIn('rua', r['selecionados'])

    def test_rh_desligamento_convoca_zilda_e_dicio(self):
        r = o.classificar_especialistas('Avaliar desligamento de um colaborador.')
        self.assertIn('zilda', r['selecionados'])
        self.assertIn('dicio', r['selecionados'])

    def test_logistica_convoca_somente_rua(self):
        r = o.classificar_especialistas('Qual a capacidade de entrega e prazo do próximo lote?')
        self.assertEqual(r['selecionados'], ['rua'])

    def test_contrato_convoca_somente_dicio(self):
        r = o.classificar_especialistas('Revisar o contrato antes de assinar.')
        self.assertEqual(r['selecionados'], ['dicio'])

    def test_agente_sem_relacao_fica_de_fora_com_motivo_explicado(self):
        r = o.classificar_especialistas('Revisar o contrato antes de assinar.')
        self.assertIn('pirret', r['excluidos'])
        self.assertTrue(r['excluidos']['pirret'])

    def test_conclave_completo_true_convoca_os_8(self):
        r = o.classificar_especialistas('Qualquer demanda simples.', conclave_completo=True)
        self.assertEqual(r['selecionados'], sorted(AGENTES))
        self.assertTrue(r['conclave_completo'])

    def test_demanda_multidisciplinar_o_bastante_aciona_conclave_completo_automatico(self):
        r = o.classificar_especialistas(
            'Piloto novo: envolve marketing, vendas, preço, fórmula do produto, capacidade de produção, '
            'contrato jurídico e dado de mercado.'
        )
        self.assertEqual(r['selecionados'], sorted(AGENTES))
        self.assertTrue(r['conclave_completo'])

    def test_toda_demanda_simples_nao_vira_conclave_completo(self):
        r = o.classificar_especialistas('Qual a capacidade de entrega e prazo do próximo lote?')
        self.assertFalse(r['conclave_completo'])

    def test_demanda_real_softdrinks_tech_convoca_exatamente_iris_dicio_leonard_marie_rua_standard(self):
        # Repete, palavra por palavra, a demanda usada no Conclave real
        # rodado nesta sessão -- antes deste ajuste, o classificador só
        # pegava iris/rua/standard (viabilidade técnica, risco regulatório
        # e potencial comercial não tinham cobertura de palavra-chave).
        demanda = (
            'Avaliar se devemos avançar com o piloto e produção inicial do Maranhão Cordial '
            'para a Softdrinks Tech, considerando custo, capacidade de produção, viabilidade '
            'técnica, risco regulatório, potencial comercial e necessidade real de mercado.'
        )
        r = o.classificar_especialistas(demanda)
        self.assertEqual(r['selecionados'], sorted(['iris', 'dicio', 'leonard', 'marie', 'rua', 'standard']))
        self.assertNotIn('pirret', r['selecionados'])
        self.assertNotIn('zilda', r['selecionados'])
        self.assertIn('pirret', r['excluidos'])
        self.assertIn('zilda', r['excluidos'])
        # 6 especialistas é seleção pontual, não alta multidisciplinaridade.
        self.assertFalse(r['conclave_completo'])

    def test_demandas_isoladas_simples_nao_convocam_em_excesso(self):
        casos = {
            'Qual o retorno esperado desse investimento?': ['standard'],
            'Precisamos revisar o posicionamento da marca no conteúdo das redes.': ['pirret'],
            'Qual a tendência de comportamento dos consumidores neste mercado?': ['iris'],
            'O estoque do lote 45 está baixo, qual o prazo de reposição?': ['rua'],
            'Revisar o contrato antes de assinar.': ['dicio'],
        }
        for demanda, esperado in casos.items():
            with self.subTest(demanda=demanda):
                r = o.classificar_especialistas(demanda)
                self.assertEqual(r['selecionados'], esperado)
                self.assertFalse(r['conclave_completo'])

    def test_pessoa_isolada_em_atendimento_cx_nao_chama_mais_zilda(self):
        # Corrigido: "pessoa" sozinha não é mais gatilho de Zilda. Esta
        # frase (o exemplo literal do pedido de correção) não toca nenhuma
        # das 8 especialidades -- por isso levanta o erro de "nenhum
        # especialista identificado", e não porque Zilda foi convocada.
        with self.assertRaises(ValueError) as ctx:
            o.classificar_especialistas('Precisamos melhorar o atendimento a cada pessoa que visita a loja.')
        self.assertEqual(str(ctx.exception), 'nenhum_especialista_identificado')

    def test_pessoa_isolada_em_atendimento_cx_nao_chama_zilda_mesmo_com_outro_agente_selecionado(self):
        # Mesmo quando a frase tem contexto suficiente para convocar outro
        # especialista de verdade (aqui, Leonard via "funil"), a palavra
        # solta "pessoa" continua não trazendo Zilda para a mesa.
        r = o.classificar_especialistas('Qual o funil de atendimento para cada pessoa que entra na loja?')
        self.assertIn('leonard', r['selecionados'])
        self.assertNotIn('zilda', r['selecionados'])

    def test_contexto_real_de_rh_continua_chamando_zilda(self):
        casos = [
            'Precisamos revisar a remuneração e o plano de carreira dos funcionários.',
            'Avaliar desligamento de um colaborador.',
            'Vamos melhorar a gestão de pessoas na fábrica.',
        ]
        for demanda in casos:
            with self.subTest(demanda=demanda):
                r = o.classificar_especialistas(demanda)
                self.assertIn('zilda', r['selecionados'])

    def test_produto_isolado_em_pergunta_de_vendas_nao_chama_mais_marie(self):
        # Corrigido: "produto" sozinho não é mais gatilho de Marie. A
        # pergunta é de desempenho de vendas (Leonard), não de fórmula/
        # embalagem/viabilidade técnica.
        r = o.classificar_especialistas('Qual o produto mais vendido este mês?')
        self.assertNotIn('marie', r['selecionados'])
        self.assertIn('leonard', r['selecionados'])

    def test_contexto_tecnico_real_continua_chamando_marie(self):
        casos = [
            'Precisamos revisar o desenvolvimento de produto e o ingrediente novo da fórmula.',
            'Qual o claim técnico que podemos usar na rotulagem?',
            'A embalagem atual tem problema de estabilidade no transporte.',
        ]
        for demanda in casos:
            with self.subTest(demanda=demanda):
                r = o.classificar_especialistas(demanda)
                self.assertIn('marie', r['selecionados'])


class OrdenarExecucao(unittest.TestCase):
    def test_iris_roda_primeiro_quando_convocada(self):
        self.assertEqual(o.ordenar_execucao(['standard', 'iris', 'leonard']), ['iris', 'leonard', 'standard'])

    def test_sem_iris_mantem_ordem_alfabetica(self):
        self.assertEqual(o.ordenar_execucao(['standard', 'leonard']), ['leonard', 'standard'])


class FormatarContextoFactual(unittest.TestCase):
    def test_sem_snapshot_devolve_marcador_de_dado_indisponivel(self):
        self.assertEqual(o.formatar_contexto_factual(None), o.MARCADOR_SEM_DADO)
        self.assertEqual(o.formatar_contexto_factual({}), o.MARCADOR_SEM_DADO)
        self.assertIn('INDISPONIVEL', o.MARCADOR_SEM_DADO)

    def test_com_snapshot_normal_devolve_json_embutido(self):
        texto = o.formatar_contexto_factual({'trabalhando': 3, 'sem_demanda': 5})
        self.assertIn('"trabalhando": 3', texto)
        self.assertIn('somente leitura', texto)

    def test_snapshot_com_chave_sensivel_e_recusado(self):
        with self.assertRaises(ValueError):
            o.formatar_contexto_factual({'database_url': 'postgres://x'})
        with self.assertRaises(ValueError):
            o.formatar_contexto_factual({'config': {'factory': 'algo'}})

    def test_snapshot_com_valor_parecido_com_credencial_e_recusado(self):
        with self.assertRaises(ValueError):
            o.formatar_contexto_factual({'nota': 'postgres://user:pass@host/db'})
        with self.assertRaises(ValueError):
            o.formatar_contexto_factual({'nota': 'Bearer abcdefgh123456'})

    def test_snapshot_aninhado_em_lista_tambem_e_verificado(self):
        with self.assertRaises(ValueError):
            o.formatar_contexto_factual({'itens': [{'token': 'sk-abcdefghij1234567890'}]})


class MontarPrompt(unittest.TestCase):
    def test_prompt_contem_persona_demanda_e_contexto(self):
        contexto = o.formatar_contexto_factual({'trabalhando': 1})
        prompt = o.montar_prompt('iris', 'Avaliar piloto X', contexto)
        self.assertIn('Iris', prompt)
        self.assertIn('Avaliar piloto X', prompt)
        self.assertIn('"trabalhando": 1', prompt)

    def test_sem_snapshot_prompt_traz_marcador_de_dado_indisponivel(self):
        prompt = o.montar_prompt('iris', 'Avaliar piloto X', None)
        self.assertIn('INDISPONIVEL', prompt)

    def test_primeira_rodada_nao_contem_posicao_de_outro_agente(self):
        prompt = o.montar_prompt('rua', 'Avaliar piloto X', None)
        self.assertNotIn('Posicao divergente', prompt)

    def test_segunda_rodada_inclui_posicao_conflitante_para_replica_com_evidencia(self):
        prompt = o.montar_prompt(
            'rua', 'Avaliar piloto X', None,
            posicao_conflitante={'agente': 'Leonard', 'texto': 'quer avançar sem volume definido'},
        )
        self.assertIn('Posicao divergente de Leonard', prompt)
        self.assertIn('quer avançar sem volume definido', prompt)
        self.assertIn('nao concorde por educacao', prompt.lower())

    def test_prompt_inclui_instrucao_de_governanca_sem_execucao_externa(self):
        prompt = o.montar_prompt('dicio', 'Avaliar contrato', None)
        self.assertIn('nao chame nenhuma ferramenta', prompt.lower())
        self.assertIn('chain-of-thought', prompt.lower())

    def test_demanda_vazia_levanta_erro(self):
        with self.assertRaises(ValueError):
            o.montar_prompt('iris', '', None)

    def test_agente_desconhecido_levanta_erro(self):
        with self.assertRaises(ValueError):
            o.montar_prompt('fulano', 'demanda', None)

    def test_nunca_contem_database_url_ou_credencial_mesmo_com_contexto_real(self):
        contexto = o.formatar_contexto_factual({'agentes': ['leonard', 'rua'], 'trabalhando': 2})
        for agente in AGENTES:
            prompt = o.montar_prompt(agente, 'Avaliar piloto X', contexto)
            self.assertFalse(o.contem_credencial(prompt))
            self.assertNotIn('DATABASE_URL', prompt)
            self.assertNotIn('postgres://', prompt)


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte_nem_chama_anthropic(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(o))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'anthropic', 'openai', 'psycopg2',
                          'whatsapp_meta', 'whatsapp_omnichannel', 'gmail_legado'):
            self.assertNotIn(proibido, modulos)

    def test_nenhuma_funcao_roda_em_loop_ou_agenda_sozinha(self):
        import inspect
        codigo = inspect.getsource(o)
        for proibido in ('while True', 'schedule.every', 'BackgroundScheduler', 'threading.Timer'):
            self.assertNotIn(proibido, codigo)

    def test_nenhuma_funcao_recebe_factory_ou_credencial_como_parametro(self):
        # A prosa do módulo cita "factory()" só para explicar o que NUNCA
        # recebe -- o que importa de verdade é a assinatura das funções.
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(o))
        for no in ast.walk(arvore):
            if isinstance(no, ast.FunctionDef):
                nomes = {a.arg for a in no.args.args}
                proibidos = nomes & {'factory', 'conn', 'connection', 'cur', 'cursor',
                                      'database_url', 'credencial', 'credential'}
                self.assertFalse(proibidos, f'{no.name} recebe parâmetro proibido: {proibidos}')
        self.assertNotIn('get_db_connection', inspect.getsource(o))


if __name__ == '__main__':
    unittest.main()
