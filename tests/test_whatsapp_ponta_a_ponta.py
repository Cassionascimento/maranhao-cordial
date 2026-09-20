"""WhatsApp de ponta a ponta, contra um banco SQL real e isolado.

Percorre o caminho inteiro de uma mensagem: webhook -> inbox durável ->
interação -> contato no CRM -> classificação -> proposta aguardando
aprovação -> decisão humana -> ciclo de entrega (sent/delivered/read/failed).

Nenhuma rede, nenhum modelo, nenhum transporte: a interpretação é injetada
e o envio é explicitamente proibido nos testes. O que se verifica aqui é o
que o sistema GRAVA, não o que a Meta faria.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import whatsapp_omnichannel as wo
from whatsapp_sqlite import Banco

TELEFONE = '5598990000000'
PHONE_ID = '1112223334'


def payload(mensagens=None, statuses=None, nome='Bar Central'):
    valor = {
        'metadata': {'phone_number_id': PHONE_ID},
        'contacts': [{'wa_id': TELEFONE, 'profile': {'name': nome}}],
    }
    if mensagens is not None:
        valor['messages'] = mensagens
    if statuses is not None:
        valor['statuses'] = statuses
    return {'object': 'whatsapp_business_account',
            'entry': [{'changes': [{'field': 'messages', 'value': valor}]}]}


def mensagem(mid='wamid.entrada1', texto='Vocês atendem bares em São Luís?'):
    return [{'id': mid, 'from': TELEFONE, 'type': 'text',
             'timestamp': '1790000000', 'text': {'body': texto}}]


IA_COMERCIAL = {'classificacao': 'interesse_comercial_b2b',
                'interesse': 'atendimento a bares em São Luís',
                'resposta_sugerida': 'Olá! Atendemos bares em São Luís. Posso enviar a apresentação?'}


class _Base(unittest.TestCase):
    def setUp(self):
        self.banco = Banco()
        self.addCleanup(self.banco.close)

    def receber(self, corpo, ia=IA_COMERCIAL):
        return wo.receber(self.banco, corpo, gerar=lambda evento: dict(ia))

    def uma(self, tabela):
        linhas = self.banco.rows(tabela)
        self.assertEqual(len(linhas), 1, f'{tabela}: {linhas}')
        return linhas[0]


class EntradaAteProposta(_Base):
    def test_uma_mensagem_percorre_o_caminho_inteiro(self):
        resultado = self.receber(payload(mensagens=mensagem()))
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['processados'], 1)
        self.assertIs(resultado['enviado'], False)

        interacao = self.uma('interacoes_omnichannel')
        self.assertEqual(interacao['canal'], 'whatsapp')
        self.assertEqual(interacao['sender_id'], TELEFONE)
        self.assertEqual(interacao['classificacao'], 'interesse_comercial_b2b')
        self.assertTrue(interacao['processado_ia'])

        lead = self.uma('leads_crm')
        self.assertEqual(lead['telefone'], TELEFONE)
        self.assertEqual(lead['origem'], 'whatsapp')
        self.assertEqual(lead['nome'], 'Bar Central')
        self.assertEqual(interacao['lead_id'], lead['id'])

        proposta = self.uma('fila_respostas_omnichannel')
        self.assertEqual(proposta['status'], 'aguardando_aprovacao')
        self.assertEqual(proposta['modo_autonomia'], 'manual')
        self.assertIsNone(proposta['enviado_em'])
        self.assertIsNone(proposta['whatsapp_message_id'])

    def test_a_trilha_de_auditoria_cobre_cada_etapa(self):
        self.receber(payload(mensagens=mensagem()))
        etapas = [linha['etapa'] for linha in self.banco.rows('whatsapp_entrada_auditoria')]
        for etapa in ('recebido', 'interacao_registrada', 'contato_vinculado', 'classificado',
                      'proposta_vinculada', 'concluido'):
            self.assertIn(etapa, etapas)

    def test_spam_nao_gera_proposta_de_resposta(self):
        self.receber(payload(mensagens=mensagem(texto='ganhe dinheiro rápido')),
                     ia={'classificacao': 'spam', 'interesse': None, 'resposta_sugerida': None})
        self.assertEqual(self.banco.rows('fila_respostas_omnichannel'), [])
        self.assertEqual(self.uma('interacoes_omnichannel')['classificacao'], 'spam')


class Idempotencia(_Base):
    def test_o_mesmo_evento_reentregue_nao_duplica_nada(self):
        corpo = payload(mensagens=mensagem())
        self.receber(corpo)
        segundo = self.receber(corpo)
        self.assertEqual(segundo['processados'], 0)
        self.assertEqual(segundo['duplicados'], 1)
        self.assertEqual(len(self.banco.rows('interacoes_omnichannel')), 1)
        self.assertEqual(len(self.banco.rows('leads_crm')), 1)
        self.assertEqual(len(self.banco.rows('fila_respostas_omnichannel')), 1)

    def test_duas_mensagens_do_mesmo_numero_nao_criam_dois_contatos(self):
        self.receber(payload(mensagens=mensagem('wamid.a', 'primeira')))
        self.receber(payload(mensagens=mensagem('wamid.b', 'segunda')))
        self.assertEqual(len(self.banco.rows('leads_crm')), 1)
        self.assertEqual(len(self.banco.rows('interacoes_omnichannel')), 2)

    def test_message_id_reaproveitado_com_outro_conteudo_e_recusado(self):
        # A primeira entrega é imutável: uma reentrega com o mesmo id e outro
        # texto é recusada antes de tocar o CRM (ValueError -> 400 na rota,
        # não 503, porque repetir o mesmo evento não resolveria).
        self.receber(payload(mensagens=mensagem('wamid.x', 'original')))
        with self.assertRaises(ValueError):
            self.receber(payload(mensagens=mensagem('wamid.x', 'adulterada')))
        self.assertEqual(self.uma('interacoes_omnichannel')['texto'], 'original')


class CicloDeEntrega(_Base):
    """sent -> delivered -> read, fora de ordem, com reentrega."""

    def _status(self, estado, mid='wamid.saida1', erros=None):
        evento = {'id': mid, 'status': estado, 'timestamp': '1790000001',
                  'recipient_id': TELEFONE}
        if erros:
            evento['errors'] = erros
        return payload(mensagens=[], statuses=[evento])

    def test_estado_avanca_e_fica_registrado(self):
        for estado in ('sent', 'delivered', 'read'):
            self.receber(self._status(estado))
        linha = self.uma('whatsapp_status_mensagem')
        self.assertEqual(linha['estado'], 'read')
        self.assertEqual(linha['message_id'], 'wamid.saida1')

    def test_evento_atrasado_nao_faz_o_estado_retroceder(self):
        self.receber(self._status('read'))
        self.receber(self._status('delivered'))
        self.assertEqual(self.uma('whatsapp_status_mensagem')['estado'], 'read')

    def test_falha_vence_e_guarda_so_o_codigo_da_meta(self):
        self.receber(self._status('failed', erros=[{'code': 131026, 'title': 'contato +55 98 99999-9999 indisponível'}]))
        linha = self.uma('whatsapp_status_mensagem')
        self.assertEqual(linha['estado'], 'failed')
        self.assertEqual(linha['codigo_erro'], 131026)
        # O título da Meta pode conter o telefone do destinatário: não persiste.
        for valor in linha.values():
            self.assertNotIn('99999-9999', str(valor))

    def test_delivered_atrasado_nao_apaga_uma_falha(self):
        self.receber(self._status('failed', erros=[{'code': 131026}]))
        self.receber(self._status('delivered'))
        self.assertEqual(self.uma('whatsapp_status_mensagem')['estado'], 'failed')

    def test_status_repetido_e_idempotente(self):
        for _ in range(3):
            self.receber(self._status('delivered'))
        self.assertEqual(len(self.banco.rows('whatsapp_status_mensagem')), 1)

    def test_status_se_liga_a_proposta_aprovada_pelo_message_id(self):
        self.receber(payload(mensagens=mensagem()))
        proposta = self.uma('fila_respostas_omnichannel')
        conn = self.banco()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('UPDATE fila_respostas_omnichannel SET whatsapp_message_id=%s WHERE id=%s',
                                ('wamid.saida1', proposta['id']))
        finally:
            conn.close()
        self.receber(self._status('delivered'))
        linha = self.uma('whatsapp_status_mensagem')
        self.assertEqual(linha['resposta_id'], proposta['id'])
        eventos = [a['evento'] for a in self.banco.rows('whatsapp_auditoria')]
        self.assertIn('status_recebido', eventos)


class NadaSaiSemDecisaoHumana(_Base):
    def test_o_fluxo_de_entrada_nunca_chama_transporte(self):
        chamadas = []
        original = wo.__dict__.get('enviar_texto')
        self.assertIsNone(original, 'o módulo de entrada não deve importar transporte')
        self.receber(payload(mensagens=mensagem()))
        self.assertEqual(chamadas, [])
        self.assertEqual(self.uma('fila_respostas_omnichannel')['status'], 'aguardando_aprovacao')

    def test_proposta_nasce_sem_marca_de_envio(self):
        self.receber(payload(mensagens=mensagem()))
        proposta = self.uma('fila_respostas_omnichannel')
        self.assertIsNone(proposta['enviado_em'])
        self.assertIsNone(proposta['erro_envio'])
        self.assertIsNone(proposta['aprovado_por'])
        self.assertIsNone(proposta['whatsapp_digest_aprovado'])

    def test_painel_declara_envio_bloqueado_e_mostra_o_ciclo(self):
        self.receber(payload(mensagens=mensagem()))
        self.receber(payload(mensagens=[], statuses=[{'id': 'wamid.saida1', 'status': 'delivered'}]))
        painel = wo.painel(self.banco)
        self.assertIs(painel['conector']['envio_liberado'], False)
        self.assertEqual(painel['status_mensagens'], {'delivered': 1})
        self.assertEqual(len(painel['entregas']), 1)
        self.assertEqual(painel['processamentos']['concluido'], 2)


class IdentidadeAmbigua(_Base):
    def test_dois_contatos_com_o_mesmo_telefone_param_para_revisao(self):
        conn = self.banco()
        try:
            with conn:
                with conn.cursor() as cur:
                    for ident in ('lead-1', 'lead-2'):
                        cur.execute("INSERT INTO leads_crm(id,nome,tipo_lead,origem,canal,telefone) "
                                    "VALUES(%s,%s,'outro','site','site',%s)", (ident, ident, TELEFONE))
        finally:
            conn.close()
        with self.assertRaises(RuntimeError):
            self.receber(payload(mensagens=mensagem()))
        processamento = self.uma('whatsapp_processamentos')
        self.assertEqual(processamento['estado'], 'pendente_identidade')
        # Nenhum contato novo foi inventado para resolver a ambiguidade.
        self.assertEqual(len(self.banco.rows('leads_crm')), 2)


if __name__ == '__main__':
    unittest.main()


class IdentidadeEntreCanais(_Base):
    """A mensagem do WhatsApp passa a deixar rastro de identidade — é o que
    permite reconhecer o mesmo contato depois, vindo por outro canal."""

    def test_o_telefone_vira_identidade_de_canal_do_contato(self):
        self.receber(payload(mensagens=mensagem()))
        identidades = self.banco.rows('crm_identidades_canal')
        self.assertEqual(len(identidades), 1)
        registro = identidades[0]
        self.assertEqual(registro['canal'], 'whatsapp')
        self.assertEqual(registro['identificador_externo'], TELEFONE)
        self.assertEqual(registro['tipo'], 'telefone')
        self.assertTrue(registro['verificado'])
        self.assertEqual(registro['lead_id'], self.uma('leads_crm')['id'])

    def test_duas_mensagens_do_mesmo_numero_nao_duplicam_a_identidade(self):
        self.receber(payload(mensagens=mensagem('wamid.a', 'primeira')))
        self.receber(payload(mensagens=mensagem('wamid.b', 'segunda')))
        self.assertEqual(len(self.banco.rows('crm_identidades_canal')), 1)

    def test_falha_ao_registrar_identidade_nao_derruba_a_entrada(self):
        """Se a migration 027 ainda não rodou em produção, a mensagem
        precisa continuar entrando e virando proposta."""
        conn = self.banco()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('DROP TABLE crm_identidades_canal')
        finally:
            conn.close()
        resultado = self.receber(payload(mensagens=mensagem()))
        self.assertEqual(resultado['processados'], 1)
        self.assertEqual(self.uma('fila_respostas_omnichannel')['status'], 'aguardando_aprovacao')
        etapas = [linha['etapa'] for linha in self.banco.rows('whatsapp_entrada_auditoria')]
        self.assertIn('identidade_nao_registrada', etapas)
