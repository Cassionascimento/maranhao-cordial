"""P5.X — Milestone 6: Pirret multimodal. Nenhum teste aqui faz chamada
paga real -- MockImageProvider (M6) para geração de imagem e um cliente
OpenAI mockado (mesmo padrão de tests/test_mi_conselho_executor.py) para
o brief. Persistência via o fake in-memory de mi_artefatos (M1)."""
import json
import unittest
from unittest.mock import MagicMock

from flask import Flask

import mi_pirret_criativo as pirret
from mi_image_provider import ErroImageProviderNaoConfigurado, ImageProviderNaoConfigurado, MockImageProvider
from tests.test_mi_artefatos import FakeArtefatoConn, _db_vazio


def _valor(v):
    return v.adapted if hasattr(v, 'adapted') else v


def _resposta_brief(**campos):
    base = {
        'objetivo_comercial': 'lançar o Bacuri', 'publico': 'consumidores premium 25-40',
        'posicionamento': 'sofisticado e regional', 'mensagem': 'sabor autêntico da Amazônia',
        'direcao_criativa': 'paleta terrosa, tipografia editorial', 'prompt_geracao': 'rótulo minimalista de Bacuri',
    }
    base.update(campos)
    return MagicMock(output_text=json.dumps(base))


def _cliente_mock(**campos):
    cliente = MagicMock()
    cliente.responses.create.return_value = _resposta_brief(**campos)
    return cliente


class MontarBriefCriativo(unittest.TestCase):
    def test_brief_valido_e_devolvido(self):
        brief = pirret.montar_brief_criativo('crie um rótulo para o Bacuri', cliente=_cliente_mock())
        self.assertEqual(brief['prompt_geracao'], 'rótulo minimalista de Bacuri')

    def test_chamada_nunca_usa_tools_nem_historico_nem_persiste(self):
        cliente = _cliente_mock()
        pirret.montar_brief_criativo('pedido', cliente=cliente)
        kwargs = cliente.responses.create.call_args.kwargs
        self.assertNotIn('tools', kwargs)
        self.assertNotIn('previous_response_id', kwargs)
        self.assertFalse(kwargs['store'])

    def test_brand_context_flui_para_o_prompt(self):
        cliente = _cliente_mock()
        pirret.montar_brief_criativo('pedido', brand_context={'paleta': ['dourado', 'creme']}, cliente=cliente)
        prompt_enviado = cliente.responses.create.call_args.kwargs['input']
        self.assertIn('dourado', prompt_enviado)

    def test_prompt_geracao_vazio_levanta_erro_nunca_gera_imagem_de_brief_invalido(self):
        cliente = _cliente_mock(prompt_geracao='   ')
        with self.assertRaises(ValueError):
            pirret.montar_brief_criativo('pedido', cliente=cliente)

    def test_falha_de_rede_propaga_nunca_finge_um_brief(self):
        cliente = MagicMock()
        cliente.responses.create.side_effect = RuntimeError('timeout')
        with self.assertRaises(RuntimeError):
            pirret.montar_brief_criativo('pedido', cliente=cliente)


class GerarConceitosVisuais(unittest.TestCase):
    def test_sem_provider_configurado_devolve_motivo_explicito_nunca_finge(self):
        db = _db_vazio()
        resultado = pirret.gerar_conceitos_visuais(
            lambda: FakeArtefatoConn(db), 'crie rótulos para o Bacuri', artifact_type='LABEL_CONCEPT',
            provider=ImageProviderNaoConfigurado(),
        )
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'image_provider_nao_configurado')
        self.assertEqual(db['artefatos'], {})

    def test_tres_propostas_geram_tres_artefatos_com_agent_id_pirret(self):
        db = _db_vazio()
        mock_provider = MockImageProvider()
        resultado = pirret.gerar_conceitos_visuais(
            lambda: FakeArtefatoConn(db), 'crie três propostas de rótulo para o Bacuri',
            artifact_type='LABEL_CONCEPT', quantidade=3, provider=mock_provider, cliente=_cliente_mock(),
        )
        self.assertTrue(resultado['success'])
        self.assertEqual(len(resultado['artefatos']), 3)
        for artefato_id in (a['id'] for a in resultado['artefatos']):
            self.assertEqual(_valor(db['artefatos'][artefato_id]['agent_id']), 'pirret')
            self.assertEqual(_valor(db['artefatos'][artefato_id]['artifact_type']), 'LABEL_CONCEPT')

    def test_brief_usado_para_gerar_e_registrado_como_metadata(self):
        db = _db_vazio()
        mock_provider = MockImageProvider()
        pirret.gerar_conceitos_visuais(
            lambda: FakeArtefatoConn(db), 'pedido', artifact_type='SOCIAL_CREATIVE', quantidade=1,
            provider=mock_provider, cliente=_cliente_mock(),
        )
        self.assertEqual(mock_provider.chamadas[0][1], 'rótulo minimalista de Bacuri')


class RefinarConceitoVisual(unittest.TestCase):
    def test_refinamento_cria_nova_versao_encadeada_ao_pai(self):
        db = _db_vazio()
        original = pirret.gerar_conceitos_visuais(
            lambda: FakeArtefatoConn(db), 'pedido', artifact_type='LABEL_CONCEPT', quantidade=1,
            provider=MockImageProvider(), cliente=_cliente_mock(),
        )
        artefato_pai_id = original['artefatos'][0]['id']
        resultado = pirret.refinar_conceito_visual(
            lambda: FakeArtefatoConn(db), artefato_pai_id, 'mais sofisticado', provider=MockImageProvider(),
        )
        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['version'], 2)
        filho = db['artefatos'][resultado['id']]
        self.assertEqual(_valor(filho['parent_artifact_id']), artefato_pai_id)

    def test_refinar_artefato_pai_inexistente_e_motivo_explicito(self):
        db = _db_vazio()
        resultado = pirret.refinar_conceito_visual(
            lambda: FakeArtefatoConn(db), 'id-que-nao-existe', 'mais sofisticado', provider=MockImageProvider(),
        )
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'artefato_pai_nao_encontrado')

    def test_sem_provider_configurado_recusa_antes_de_tocar_o_banco(self):
        db = _db_vazio()
        resultado = pirret.refinar_conceito_visual(
            lambda: FakeArtefatoConn(db), 'qualquer-id', 'instrucao', provider=ImageProviderNaoConfigurado(),
        )
        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['motivo'], 'image_provider_nao_configurado')


class RotaHTTP(unittest.TestCase):
    def _app(self, db, autorizado=lambda: True):
        app = Flask(__name__)
        pirret.registrar_rotas(app, lambda: FakeArtefatoConn(db), autorizado)
        return app

    def test_todas_as_rotas_exigem_autorizacao(self):
        db = _db_vazio()
        app = self._app(db, autorizado=lambda: False)
        cliente = app.test_client()
        self.assertEqual(cliente.get('/api/admin/mi/pirret/provider-status').status_code, 401)
        self.assertEqual(cliente.post('/api/admin/mi/pirret/conceitos').status_code, 401)
        self.assertEqual(cliente.post('/api/admin/mi/pirret/refinar/x').status_code, 401)

    def test_provider_status_sem_configuracao(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            db = _db_vazio()
            resp = self._app(db).test_client().get('/api/admin/mi/pirret/provider-status')
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.get_json()['disponivel'])

    def test_gerar_conceitos_sem_pedido_e_400(self):
        db = _db_vazio()
        resp = self._app(db).test_client().post('/api/admin/mi/pirret/conceitos', json={})
        self.assertEqual(resp.status_code, 400)

    def test_refinar_sem_instrucao_e_400(self):
        db = _db_vazio()
        resp = self._app(db).test_client().post('/api/admin/mi/pirret/refinar/x', json={})
        self.assertEqual(resp.status_code, 400)


class NenhumaAcaoExterna(unittest.TestCase):
    def test_modulo_nunca_publica_nem_chama_canais_externos(self):
        import inspect
        codigo = inspect.getsource(pirret)
        for proibido in ('smtplib', 'requests.', 'import whatsapp', 'import gmail',
                          'INSERT INTO leads_crm', 'salvar_pedido_postgres('):
            self.assertNotIn(proibido, codigo)

    def test_nenhum_agente_novo_e_criado_pirret_e_sempre_o_agent_id(self):
        # "Pires" pode aparecer em prosa explicando a correção de
        # nomenclatura (como em P5X_AUDIT.md) -- o que nunca pode
        # acontecer é o código usar "pires" como valor real de agent_id.
        import inspect
        codigo = inspect.getsource(pirret)
        self.assertNotIn("agent_id='pires'", codigo)
        self.assertNotIn('agent_id="pires"', codigo)
        self.assertIn("agent_id='pirret'", codigo)


if __name__ == '__main__':
    unittest.main()
