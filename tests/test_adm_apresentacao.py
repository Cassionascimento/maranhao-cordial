"""Apresentação executiva: agregada, sem dado pessoal e protegida no servidor."""
import json
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

import adm_apresentacao
from adm_apresentacao import (
    _etapa_alcancada,
    _oportunidade_anonima,
    montar_apresentacao,
    registrar_rotas_adm_apresentacao,
)

def conexao(
    por_estagio=(('novo', 4), ('qualificacao', 3), ('negociacao', 2), ('cliente', 5)),
    pracas=7,
    pedidos_por_status=(('pago', 6), ('pendente', 2)),
    receita=123400,
    propostas=(('aguardando_aprovacao', 3), ('aprovada', 1), ('enviada', 2)),
):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [
        [{'estagio': e, 'total': t} for e, t in por_estagio],
        [{'status': s, 'total': t} for s, t in pedidos_por_status],
        [{'status': s, 'total': t} for s, t in propostas],
    ]
    cur.fetchone.side_effect = [{'total': pracas}, {'total': receita}]
    return conn


LEITURA = {
    'ia_trabalhando': True,
    'hoje': {'concluido': [{}, {}], 'planejado': [{}], 'precisa_de_mim': [{}]},
    'comercial': {
        'oportunidades': [
            {'tipo_decisao': 'oportunidade_parada', 'prioridade': 'normal',
             'proxima_acao': 'enviar_followup', 'exige_aprovacao': True,
             'inferencia': 'Bar do Zé parou de responder — Maria, (98) 99999-9999'},
            {'tipo_decisao': 'oportunidade_parada', 'prioridade': 'urgente',
             'proxima_acao': 'avaliar_reengajamento', 'exige_aprovacao': True,
             'motivo': 'Hotel Rio Anil, contato joao@exemplo.com'},
        ],
    },
    'conselho': {'trabalhando': 2, 'conflitos': [{}], 'vetos': [], 'resultados_recentes': [{}]},
}

CANAIS = [
    {'canal': 'Gmail', 'estado': 'conectado', 'leitura_disponivel': True,
     'escrita_disponivel': True, 'aprovacao_exigida': True},
    {'canal': 'WhatsApp', 'estado': 'pendente', 'leitura_disponivel': True,
     'escrita_disponivel': False, 'aprovacao_exigida': True},
]


def montar(conn=None, leitura=LEITURA, canais=CANAIS):
    conn = conn or conexao()
    with patch('mi_diretor.leitura_diretor', return_value=leitura), \
         patch('canais_status.status_todos_os_canais', return_value=canais):
        return montar_apresentacao(lambda: conn)


class Agregacao(unittest.TestCase):
    def test_situacao_agrega_estagios_abertos_sem_clientes(self):
        dados = montar()
        # 4 + 3 + 2 abertos; os 5 clientes ficam num campo próprio.
        self.assertEqual(dados['situacao']['contatos_em_relacionamento'], 9)
        self.assertEqual(dados['situacao']['clientes'], 5)

    def test_receita_confirmada_vem_so_de_pedidos_pagos(self):
        dados = montar()
        self.assertEqual(dados['situacao']['receita_confirmada_centavos'], 123400)
        self.assertEqual(dados['situacao']['pedidos_pagos'], 6)
        self.assertEqual(dados['situacao']['pedidos_registrados'], 8)

    def test_proposta_nunca_entra_como_receita(self):
        dados = montar()
        receita = dados['situacao']['receita_confirmada_centavos']
        propostas = dados['controle_humano']['propostas']
        self.assertEqual(receita, 123400)
        self.assertEqual(propostas, 6)
        self.assertNotIn('receita', dados['controle_humano'])

    def test_controle_humano_declara_que_nao_ha_envio_automatico(self):
        dados = montar()
        self.assertIs(dados['controle_humano']['envio_automatico'], False)
        self.assertIs(dados['controle_humano']['aprovacao_exigida'], True)
        self.assertEqual(dados['controle_humano']['aguardando_aprovacao'], 3)
        self.assertEqual(dados['controle_humano']['executadas'], 2)

    def test_usa_transacao_somente_leitura(self):
        conn = conexao()
        montar(conn)
        conn.set_session.assert_any_call(readonly=True, isolation_level='REPEATABLE READ')

    def test_nenhuma_consulta_escreve(self):
        conn = conexao()
        montar(conn)
        cur = conn.cursor.return_value.__enter__.return_value
        for chamada in cur.execute.call_args_list:
            sql = chamada.args[0].upper()
            for proibido in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER'):
                self.assertNotIn(proibido, sql)


class SemDadoPessoal(unittest.TestCase):
    def test_oportunidade_nao_carrega_texto_livre(self):
        oportunidade = _oportunidade_anonima(LEITURA)
        # A urgente é escolhida, mas nem 'motivo' nem 'inferencia' saem.
        self.assertEqual(oportunidade['prioridade'], 'urgente')
        self.assertNotIn('motivo', oportunidade)
        self.assertNotIn('inferencia', oportunidade)

    def test_json_inteiro_nao_contem_nome_email_nem_telefone(self):
        corpo = json.dumps(montar(), ensure_ascii=False).lower()
        self.assertNotIn('bar do zé', corpo)
        self.assertNotIn('joao@exemplo.com', corpo)
        self.assertNotIn('99999', corpo)
        self.assertNotIn('maria', corpo)

    def test_todo_texto_do_payload_vem_de_enumeracao_fechada(self):
        """Invariante mais forte que procurar palavra proibida: nenhum texto
        do payload pode ter origem numa linha do banco. Todo valor de texto
        tem de ser um número, um booleano, uma data ou uma string que já
        existe no próprio módulo."""
        permitidos = set(adm_apresentacao.PRIORIDADES)
        permitidos |= set(adm_apresentacao.ACOES_CONHECIDAS)
        permitidos |= set(adm_apresentacao.ESTAGIOS_ABERTOS)
        permitidos |= {'outro', 'oportunidade_parada', 'Maranhão Cordial',
                       'Cordiais brasileiros sem álcool'}
        permitidos |= {'Gmail', 'WhatsApp', 'conectado', 'pendente', 'bloqueado'}
        permitidos |= {'acao_executada', 'acao_aprovada', 'acao_aguardando_aprovacao',
                       'acao_proposta', 'relacionamento_em_andamento',
                       'operacao_preparada', 'fila_nao_lida'}

        dados = montar()
        permitidos |= set(dados['limites'])
        permitidos.add(dados['gerado_em'])

        def folhas(no):
            if isinstance(no, dict):
                for chave, valor in no.items():
                    assert not isinstance(chave, str) or '@' not in chave
                    yield from folhas(valor)
            elif isinstance(no, list):
                for item in no:
                    yield from folhas(item)
            else:
                yield no

        for folha in folhas(dados):
            if isinstance(folha, str):
                self.assertIn(folha, permitidos, f'texto de origem desconhecida: {folha!r}')
            else:
                self.assertIsInstance(folha, (int, float, bool, type(None)))

    def test_valor_fora_da_enumeracao_vira_outro(self):
        leitura = {'comercial': {'oportunidades': [
            {'tipo_decisao': 'oportunidade_parada', 'prioridade': 'alta',
             'proxima_acao': 'ligar_para_joao_11988887777', 'exige_aprovacao': True},
        ]}}
        self.assertEqual(_oportunidade_anonima(leitura)['proxima_acao'], 'outro')


class FalhaIsolada(unittest.TestCase):
    def test_conselho_indisponivel_nao_derruba_a_apresentacao(self):
        conn = conexao()
        with patch('mi_diretor.leitura_diretor', side_effect=RuntimeError('sem tabela')), \
             patch('canais_status.status_todos_os_canais', return_value=CANAIS):
            dados = montar_apresentacao(lambda: conn)
        self.assertIsNone(dados['oportunidade'])
        self.assertIsNone(dados['trabalho_da_tecnologia'])
        self.assertIsNotNone(dados['situacao'])

    def test_fila_de_aprovacoes_ausente_vira_none_e_nunca_zero(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [
            [{'estagio': 'novo', 'total': 1}],
            [{'status': 'pago', 'total': 1}],
            Exception('tabela inexistente'),
        ]
        cur.fetchone.side_effect = [{'total': 1}, {'total': 100}]

        def execute(sql, *args, **kwargs):
            if 'acoes_comerciais_propostas' in sql:
                raise RuntimeError('relation does not exist')
        cur.execute.side_effect = execute

        with patch('mi_diretor.leitura_diretor', return_value=LEITURA), \
             patch('canais_status.status_todos_os_canais', return_value=CANAIS):
            dados = montar_apresentacao(lambda: conn)
        self.assertIsNone(dados['controle_humano'])
        self.assertEqual(dados['resultado']['etapa_alcancada'], 'fila_nao_lida')

    def test_capacidades_indisponiveis_nao_derrubam(self):
        conn = conexao()
        with patch('mi_diretor.leitura_diretor', return_value=LEITURA), \
             patch('canais_status.status_todos_os_canais', side_effect=RuntimeError):
            dados = montar_apresentacao(lambda: conn)
        self.assertIsNone(dados['capacidades'])


class EtapaReal(unittest.TestCase):
    def test_sem_resultado_mostra_a_etapa_mais_avancada_de_verdade(self):
        base = {'propostas': 2, 'aguardando_aprovacao': 2, 'aprovadas': 0,
                'rejeitadas': 0, 'executadas': 0, 'sem_confirmacao': 0}
        self.assertEqual(_etapa_alcancada(base, None), 'acao_aguardando_aprovacao')
        self.assertEqual(_etapa_alcancada(dict(base, aprovadas=1), None), 'acao_aprovada')
        self.assertEqual(_etapa_alcancada(dict(base, executadas=1), None), 'acao_executada')

    def test_sem_nenhuma_proposta_declara_operacao_preparada(self):
        vazio = {'propostas': 0, 'aguardando_aprovacao': 0, 'aprovadas': 0,
                 'rejeitadas': 0, 'executadas': 0, 'sem_confirmacao': 0}
        self.assertEqual(_etapa_alcancada(vazio, None), 'operacao_preparada')
        self.assertEqual(
            _etapa_alcancada(vazio, {'contatos_em_relacionamento': 3}),
            'relacionamento_em_andamento',
        )

    def test_limites_sempre_acompanham_a_leitura(self):
        limites = ' '.join(montar()['limites']).lower()
        self.assertIn('pagamento confirmado', limites)
        self.assertIn('não são receita', limites)


class Autorizacao(unittest.TestCase):
    def _app(self, autorizado):
        app = Flask(__name__)
        registrar_rotas_adm_apresentacao(app, lambda: conexao(), lambda: autorizado)
        return app.test_client()

    def test_sem_chave_administrativa_responde_401_e_nao_le_dados(self):
        with patch.object(adm_apresentacao, 'montar_apresentacao') as montador:
            resposta = self._app(False).get('/api/admin/apresentacao')
        self.assertEqual(resposta.status_code, 401)
        montador.assert_not_called()

    def test_rota_fica_sob_api_admin_para_herdar_a_protecao_global(self):
        app = Flask(__name__)
        registrar_rotas_adm_apresentacao(app, lambda: conexao(), lambda: True)
        caminhos = [str(r) for r in app.url_map.iter_rules()]
        self.assertTrue(any(c.startswith('/api/admin/') for c in caminhos))

    def test_com_chave_valida_devolve_a_leitura(self):
        with patch('mi_diretor.leitura_diretor', return_value=LEITURA), \
             patch('canais_status.status_todos_os_canais', return_value=CANAIS):
            resposta = self._app(True).get('/api/admin/apresentacao')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()['success'])

    def test_nenhuma_fonte_lida_responde_503_sem_vazar_detalhe(self):
        # Degradar bloco a bloco é o esperado; devolver uma tela toda vazia
        # como se fosse o estado real do negócio, não.
        app = Flask(__name__)
        registrar_rotas_adm_apresentacao(app, lambda: 1 / 0, lambda: True)
        resposta = app.test_client().get('/api/admin/apresentacao')
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn('ZeroDivision', resposta.get_data(as_text=True))

    def test_uma_fonte_fora_do_ar_ainda_devolve_o_resto(self):
        with patch('mi_diretor.leitura_diretor', side_effect=RuntimeError), \
             patch('canais_status.status_todos_os_canais', return_value=CANAIS):
            resposta = self._app(True).get('/api/admin/apresentacao')
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.get_json()['apresentacao']
        self.assertIsNone(corpo['trabalho_da_tecnologia'])
        self.assertIsNotNone(corpo['situacao'])

    def test_nao_existe_rota_publica_de_apresentacao(self):
        app = Flask(__name__)
        registrar_rotas_adm_apresentacao(app, lambda: conexao(), lambda: True)
        for regra in app.url_map.iter_rules():
            if regra.endpoint == 'static':
                continue
            self.assertTrue(str(regra).startswith('/api/admin/'), str(regra))


if __name__ == '__main__':
    unittest.main()
