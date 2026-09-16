"""Next Best Action -- mi_next_best_action.py. Motor de regras puro (sem
LLM, sem rede): cada sugestão precisa ser rastreável a evidência real, nunca
mais de 3, nunca duplica ação já proposta/ativa, nunca executa nada."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import mi_next_best_action as nba


def _lead(**campos):
    base = {'id': 'lead1', 'nome': 'Fulano', 'email': 'fulano@x.com', 'estagio': 'novo', 'status': 'ativo',
            'atualizado_em': datetime.now(timezone.utc) - timedelta(days=30)}
    base.update(campos)
    return base


class SugestoesLead(unittest.TestCase):
    def test_lead_ativo_sem_interacao_sugere_primeiro_contato(self):
        sugestoes = nba.sugestoes_lead(_lead(), [], [])
        self.assertEqual([s['tipo'] for s in sugestoes], ['primeiro_contato'])
        self.assertEqual(sugestoes[0]['confianca'], 'media')
        self.assertIn('0 linhas em interacoes_omnichannel', sugestoes[0]['evidencia'][0])

    def test_lead_inativo_nao_sugere_primeiro_contato(self):
        sugestoes = nba.sugestoes_lead(_lead(status='arquivado'), [], [])
        self.assertEqual(sugestoes, [])

    def test_interacao_de_interesse_alto_sem_acao_depois_sugere_follow_up(self):
        interacao = {'canal': 'whatsapp', 'interesse': 'alto', 'classificacao': None,
                     'criado_em': datetime.now(timezone.utc) - timedelta(days=1)}
        sugestoes = nba.sugestoes_lead(_lead(), [interacao], [])
        tipos = [s['tipo'] for s in sugestoes]
        self.assertIn('follow_up_interesse_alto', tipos)
        self.assertEqual(sugestoes[tipos.index('follow_up_interesse_alto')]['confianca'], 'alta')

    def test_interesse_alto_com_acao_ja_registrada_depois_nao_sugere_follow_up(self):
        criado = datetime.now(timezone.utc) - timedelta(days=2)
        interacao = {'canal': 'whatsapp', 'interesse': 'alto', 'classificacao': None, 'criado_em': criado}
        acao = {'id': 'a1', 'status': 'enviada', 'tipo': 'resposta', 'criado_em': criado + timedelta(hours=1)}
        sugestoes = nba.sugestoes_lead(_lead(), [interacao], [acao])
        self.assertNotIn('follow_up_interesse_alto', [s['tipo'] for s in sugestoes])

    def test_estagio_avancado_parado_ha_mais_de_7_dias_sugere_retomar_contato(self):
        lead = _lead(estagio='negociacao', atualizado_em=datetime.now(timezone.utc) - timedelta(days=10))
        sugestoes = nba.sugestoes_lead(lead, [], [])
        tipos = [s['tipo'] for s in sugestoes]
        self.assertIn('retomar_contato_estagio_parado', tipos)

    def test_estagio_avancado_recente_nao_sugere_retomar_contato(self):
        lead = _lead(estagio='negociacao', atualizado_em=datetime.now(timezone.utc) - timedelta(days=1))
        sugestoes = nba.sugestoes_lead(lead, [], [])
        self.assertNotIn('retomar_contato_estagio_parado', [s['tipo'] for s in sugestoes])

    def test_acao_pendente_de_aprovacao_sugere_aprovar_e_nao_duplica_primeiro_contato(self):
        acao = {'id': 'a1', 'status': 'aguardando_aprovacao', 'tipo': 'primeiro_contato',
                'criado_em': datetime.now(timezone.utc)}
        sugestoes = nba.sugestoes_lead(_lead(), [], [acao])
        tipos = [s['tipo'] for s in sugestoes]
        self.assertIn('aprovar_acao_pendente', tipos)
        self.assertNotIn('primeiro_contato', tipos)

    def test_acao_ja_enviada_nao_duplica_primeiro_contato(self):
        acao = {'id': 'a1', 'status': 'enviada', 'tipo': 'primeiro_contato', 'criado_em': datetime.now(timezone.utc)}
        sugestoes = nba.sugestoes_lead(_lead(), [], [acao])
        self.assertNotIn('primeiro_contato', [s['tipo'] for s in sugestoes])

    def test_nunca_mais_de_tres_sugestoes(self):
        acao_pendente = {'id': 'a1', 'status': 'aguardando_aprovacao', 'tipo': 'resposta',
                          'criado_em': datetime.now(timezone.utc)}
        interacao = {'canal': 'whatsapp', 'interesse': 'alto', 'classificacao': None,
                     'criado_em': datetime.now(timezone.utc) - timedelta(days=1)}
        lead = _lead(estagio='negociacao', atualizado_em=datetime.now(timezone.utc) - timedelta(days=30))
        sugestoes = nba.sugestoes_lead(lead, [interacao], [acao_pendente])
        self.assertLessEqual(len(sugestoes), nba.MAX_SUGESTOES)

    def test_toda_sugestao_carrega_motivo_evidencia_confianca_responsavel(self):
        sugestoes = nba.sugestoes_lead(_lead(), [], [])
        for s in sugestoes:
            self.assertTrue(s['motivo'])
            self.assertTrue(s['evidencia'])
            self.assertIn(s['confianca'], ('alta', 'media', 'baixa'))
            self.assertTrue(s['responsavel'])

    def test_sem_factory_nunca_consulta_travas_de_envio(self):
        with patch('email_seguranca.verificar_travas_envio') as verificar:
            nba.sugestoes_lead(_lead(), [], [], factory=None)
            verificar.assert_not_called()

    def test_bloqueio_de_envio_e_refletido_na_sugestao_sem_suprimi_la(self):
        from email_seguranca import EnvioBloqueado
        with patch('email_seguranca.verificar_travas_envio', side_effect=EnvioBloqueado('envios_pausados')):
            sugestoes = nba.sugestoes_lead(_lead(), [], [], factory=MagicMock())
        self.assertTrue(sugestoes)
        self.assertEqual(sugestoes[0]['bloqueio'], 'envios_pausados')


class RegistrarRotasNextBestAction(unittest.TestCase):
    def test_rota_exige_autorizacao(self):
        from flask import Flask
        app = Flask(__name__)
        nba.registrar_rotas_next_best_action(app, MagicMock(), lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.get('/api/admin/mi/next-best-action/lead1').status_code, 401)


if __name__ == '__main__':
    unittest.main()
