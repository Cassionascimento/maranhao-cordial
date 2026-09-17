"""P5.X — parte de M6: interface abstrata de geração de imagem. Nenhum
teste aqui faz chamada de rede real -- MockImageProvider e um cliente
OpenAI mockado cobrem o contrato inteiro."""
import base64
import unittest
from unittest.mock import MagicMock, patch

import mi_image_provider as provider


class ImageProviderNaoConfigurado(unittest.TestCase):
    def test_nunca_finge_disponibilidade(self):
        p = provider.ImageProviderNaoConfigurado()
        self.assertFalse(p.disponivel())

    def test_gerar_editar_variacao_levantam_erro_explicito(self):
        p = provider.ImageProviderNaoConfigurado()
        for metodo, args in (('gerar', ('prompt',)), ('editar', (b'x', 'instrucao')), ('variacao', (b'x',))):
            with self.assertRaises(provider.ErroImageProviderNaoConfigurado):
                getattr(p, metodo)(*args)


class MockImageProviderTeste(unittest.TestCase):
    def test_nunca_faz_chamada_de_rede_sempre_devolve_png_valido(self):
        mock = provider.MockImageProvider()
        imagens = mock.gerar('rótulo do Bacuri')
        self.assertEqual(len(imagens), 1)
        self.assertTrue(imagens[0].startswith(b'\x89PNG'))

    def test_registra_as_chamadas_recebidas(self):
        mock = provider.MockImageProvider()
        mock.gerar('prompt A')
        mock.editar(b'base', 'mais sofisticado')
        self.assertEqual(mock.chamadas[0][:2], ('gerar', 'prompt A'))
        self.assertEqual(mock.chamadas[1][:2], ('editar', 'mais sofisticado'))

    def test_disponivel_sempre_true(self):
        self.assertTrue(provider.MockImageProvider().disponivel())


class OpenAIImageProviderTeste(unittest.TestCase):
    def _cliente_mock(self, b64='iVBORw0KGgo='):
        cliente = MagicMock()
        item = MagicMock(b64_json=b64)
        cliente.images.generate.return_value = MagicMock(data=[item])
        cliente.images.edit.return_value = MagicMock(data=[item])
        return cliente

    def test_gerar_usa_o_cliente_injetado_nunca_credencial_hardcoded(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        imagens = p.gerar('rótulo do Bacuri')
        self.assertEqual(imagens[0], base64.b64decode('iVBORw0KGgo='))
        kwargs = cliente.images.generate.call_args.kwargs
        self.assertEqual(kwargs['prompt'], 'rótulo do Bacuri')
        self.assertNotIn('api_key', kwargs)

    def test_editar_usa_o_cliente_injetado(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        p.editar(b'imagem-base', 'mais sofisticado')
        cliente.images.edit.assert_called_once()

    def test_variacao_nao_suportada_e_explicita_nunca_falha_silenciosamente(self):
        p = provider.OpenAIImageProvider(cliente=self._cliente_mock())
        with self.assertRaises(NotImplementedError):
            p.variacao(b'x')

    def test_disponivel_com_cliente_injetado_e_true_mesmo_sem_env(self):
        with patch.dict('os.environ', {}, clear=True):
            p = provider.OpenAIImageProvider(cliente=self._cliente_mock())
            self.assertTrue(p.disponivel())

    def test_sem_cliente_injetado_e_sem_env_e_indisponivel(self):
        with patch.dict('os.environ', {}, clear=True):
            p = provider.OpenAIImageProvider()
            self.assertFalse(p.disponivel())


class CriarProviderPadrao(unittest.TestCase):
    def test_sem_openai_api_key_devolve_nao_configurado(self):
        with patch.dict('os.environ', {}, clear=True):
            p = provider.criar_provider_padrao()
            self.assertIsInstance(p, provider.ImageProviderNaoConfigurado)

    def test_com_openai_api_key_devolve_provider_openai_disponivel(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-teste'}, clear=True):
            p = provider.criar_provider_padrao()
            self.assertIsInstance(p, provider.OpenAIImageProvider)
            self.assertTrue(p.disponivel())

    def test_provider_desconhecido_via_env_nunca_finge_suporte(self):
        with patch.dict('os.environ', {'IMAGE_PROVIDER': 'fornecedor-inexistente'}, clear=True):
            p = provider.criar_provider_padrao()
            self.assertIsInstance(p, provider.ImageProviderNaoConfigurado)


if __name__ == '__main__':
    unittest.main()
