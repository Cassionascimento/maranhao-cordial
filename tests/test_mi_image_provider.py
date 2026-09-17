"""P5.X — parte de M6: interface abstrata de geração de imagem. Nenhum
teste aqui faz chamada de rede real -- MockImageProvider e um cliente
OpenAI mockado cobrem o contrato inteiro."""
import base64
import unittest
from unittest.mock import MagicMock, patch

import mi_image_provider as provider

PNG_VALIDO = provider._PNG_1X1_BRANCO
JPEG_VALIDO = b'\xff\xd8\xff\xe0' + b'\x00' * 20
WEBP_VALIDO = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 8
BYTES_INVALIDOS = b'isto nao e uma imagem, so texto de padding qualquer'
SVG_COMO_ARTEFATO = b'<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"></svg>'


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
        p.editar(PNG_VALIDO, 'mais sofisticado')
        cliente.images.edit.assert_called_once()
        kwargs = cliente.images.edit.call_args.kwargs
        nome, conteudo, mime = kwargs['image']
        self.assertEqual(mime, 'image/png')
        self.assertTrue(nome.endswith('.png'))
        self.assertEqual(conteudo, PNG_VALIDO)

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


class DetectarMimeImagem(unittest.TestCase):
    def test_png_valido(self):
        self.assertEqual(provider.detectar_mime_imagem(PNG_VALIDO), 'image/png')

    def test_jpeg_valido(self):
        self.assertEqual(provider.detectar_mime_imagem(JPEG_VALIDO), 'image/jpeg')

    def test_webp_valido(self):
        self.assertEqual(provider.detectar_mime_imagem(WEBP_VALIDO), 'image/webp')

    def test_bytes_invalidos_devolve_none(self):
        self.assertIsNone(provider.detectar_mime_imagem(BYTES_INVALIDOS))

    def test_svg_nunca_e_reconhecido_como_editavel(self):
        # Causa raiz real encontrada em produção: um gráfico SVG tem
        # mime_type='image/svg+xml' armazenado (passa em filtros genéricos
        # 'image/*'), mas não é um formato que a edição de imagem aceita.
        self.assertIsNone(provider.detectar_mime_imagem(SVG_COMO_ARTEFATO))

    def test_none_ou_tipo_errado_nunca_lanca_excecao(self):
        self.assertIsNone(provider.detectar_mime_imagem(None))
        self.assertIsNone(provider.detectar_mime_imagem('string, nao bytes'))
        self.assertIsNone(provider.detectar_mime_imagem(b'curto'))

    def test_mime_extensao_fornecida_pelo_cliente_nunca_e_usada(self):
        # Bytes de PNG "disfarçados" de outro tipo continuam detectados
        # pelo conteúdo real, nunca por um rótulo externo -- não há
        # parâmetro de mime/extensão na função para confiar cegamente.
        self.assertEqual(provider.detectar_mime_imagem(PNG_VALIDO), 'image/png')


class OpenAIImageProviderEditarFormatos(unittest.TestCase):
    def _cliente_mock(self):
        cliente = MagicMock()
        item = MagicMock(b64_json='iVBORw0KGgo=')
        cliente.images.edit.return_value = MagicMock(data=[item])
        return cliente

    def test_editar_com_jpeg_envia_arquivo_nomeado_com_mime_correto(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        p.editar(JPEG_VALIDO, 'instrucao')
        _, conteudo, mime = cliente.images.edit.call_args.kwargs['image']
        self.assertEqual(mime, 'image/jpeg')
        self.assertEqual(conteudo, JPEG_VALIDO)

    def test_editar_com_webp_envia_arquivo_nomeado_com_mime_correto(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        p.editar(WEBP_VALIDO, 'instrucao')
        _, conteudo, mime = cliente.images.edit.call_args.kwargs['image']
        self.assertEqual(mime, 'image/webp')

    def test_editar_com_bytes_invalidos_falha_local_nunca_chama_o_provider(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        with self.assertRaises(provider.ErroImagemNaoSuportada):
            p.editar(BYTES_INVALIDOS, 'instrucao')
        cliente.images.edit.assert_not_called()

    def test_editar_com_svg_falha_local_nunca_chama_o_provider(self):
        cliente = self._cliente_mock()
        p = provider.OpenAIImageProvider(cliente=cliente)
        with self.assertRaises(provider.ErroImagemNaoSuportada):
            p.editar(SVG_COMO_ARTEFATO, 'instrucao')
        cliente.images.edit.assert_not_called()

    def test_erro_conhecido_do_provider_e_um_tipo_distinguivel(self):
        # openai.APIStatusError real (ex.: 400 unsupported_file_mimetype)
        # precisa continuar propagando intacto quando o provider de fato
        # recusa -- quem trata isso com segurança é a rota (mi_social_studio).
        import openai
        cliente = MagicMock()
        resposta_falsa = MagicMock(status_code=400, headers={})
        cliente.images.edit.side_effect = openai.BadRequestError(
            'unsupported_file_mimetype', response=resposta_falsa, body={'code': 'unsupported_file_mimetype'})
        p = provider.OpenAIImageProvider(cliente=cliente)
        with self.assertRaises(openai.APIStatusError):
            p.editar(PNG_VALIDO, 'instrucao')


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
