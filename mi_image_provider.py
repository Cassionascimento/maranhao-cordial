"""Interface abstrata de geração/edição de imagem (P5.X — parte de M6,
fatiada do que seria M7 pela mesma razão que ArtifactStorage foi fatiada
para dentro de M1: Pirret multimodal não funciona sem ela).

O sistema não depende estruturalmente de um único fornecedor -- um novo
provider só precisa implementar `gerar`/`editar`/`variacao`/`disponivel`.
O provider padrão de produção reaproveita a MESMA credencial OpenAI já
configurada para o Conselho (mi_conselho_executor.py usa `OpenAI()` sem
api_key explícita, lendo `OPENAI_API_KEY` do ambiente -- aqui é
exatamente o mesmo mecanismo, nenhuma segunda credencial). Escolha de
provider é sempre por variável de ambiente (`IMAGE_PROVIDER`), nunca
hardcoded; sem configuração real, `ImageProviderNaoConfigurado` nunca
finge que gerou uma imagem."""
import base64
import os

MODELO_IMAGEM_PADRAO = os.getenv('OPENAI_IMAGE_MODEL', 'gpt-image-1')


class ImageGenerationProvider:
    def gerar(self, prompt, **kwargs):
        raise NotImplementedError

    def editar(self, imagem_base, instrucao, **kwargs):
        raise NotImplementedError

    def variacao(self, imagem_base, **kwargs):
        raise NotImplementedError

    def disponivel(self):
        raise NotImplementedError


class ErroImageProviderNaoConfigurado(RuntimeError):
    pass


class ErroImagemNaoSuportada(ValueError):
    """Levantado quando os bytes recebidos para edição não são um PNG/
    JPEG/WEBP reconhecível -- falha local e explícita, antes de qualquer
    chamada ao provider real. Nunca converte silenciosamente o conteúdo
    para um formato aceito."""


MIME_SUPORTADOS_EDICAO = ('image/png', 'image/jpeg', 'image/webp')
_EXTENSAO_POR_MIME = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}


def detectar_mime_imagem(conteudo):
    """Deriva o mime type real a partir da assinatura dos bytes -- nunca
    confia em `mime_type`/extensão informados pelo cliente ou já
    armazenados em metadata (podem estar errados ou ser de um artefato
    que nunca foi pensado para edição, como um gráfico SVG). Só
    reconhece os três formatos que a edição de imagem realmente aceita;
    qualquer outra coisa (incluindo SVG, PDF, texto) devolve None."""
    if not isinstance(conteudo, (bytes, bytearray)) or len(conteudo) < 12:
        return None
    if conteudo[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if conteudo[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if conteudo[:4] == b'RIFF' and conteudo[8:12] == b'WEBP':
        return 'image/webp'
    return None


class ImageProviderNaoConfigurado(ImageGenerationProvider):
    """Nunca finge geração de imagem sem configuração real (mesma
    disciplina de mi_artefato_storage.StorageNaoConfigurado)."""

    MENSAGEM = 'IMAGE PROVIDER — NOT CONFIGURED'

    def gerar(self, prompt, **kwargs):
        raise ErroImageProviderNaoConfigurado(self.MENSAGEM)

    def editar(self, imagem_base, instrucao, **kwargs):
        raise ErroImageProviderNaoConfigurado(self.MENSAGEM)

    def variacao(self, imagem_base, **kwargs):
        raise ErroImageProviderNaoConfigurado(self.MENSAGEM)

    def disponivel(self):
        return False


def _decodificar_b64(item):
    return base64.b64decode(item.b64_json)


class OpenAIImageProvider(ImageGenerationProvider):
    """Reaproveita openai.OpenAI() já em uso pelo Conselho -- só chama
    `client.images.*` em vez de `client.responses.*`. `cliente` é
    injetável (mesmo padrão de `cliente` em mi_conselho_executor.py) só
    para teste; em produção usa o cliente real, sem chave hardcoded."""

    def __init__(self, cliente=None):
        self._cliente_injetado = cliente

    def _cliente(self):
        if self._cliente_injetado:
            return self._cliente_injetado
        from openai import OpenAI
        return OpenAI()

    def gerar(self, prompt, *, tamanho='1024x1024', n=1):
        resposta = self._cliente().images.generate(model=MODELO_IMAGEM_PADRAO, prompt=prompt, size=tamanho, n=n)
        return [_decodificar_b64(item) for item in resposta.data]

    def editar(self, imagem_base, instrucao, *, tamanho='1024x1024'):
        # A OpenAI recusa a edição (400 unsupported_file_mimetype) quando o
        # arquivo enviado não carrega um mime type reconhecível -- um
        # io.BytesIO puro, sem nome, vira application/octet-stream. Aqui
        # detectamos o formato real pelos BYTES (nunca por extensão/
        # mime_type informado) e só então enviamos um arquivo nomeado com
        # o mime correto; sem isso, falha local antes de gastar a chamada.
        mime = detectar_mime_imagem(imagem_base)
        if mime is None:
            raise ErroImagemNaoSuportada(
                'Conteúdo não reconhecido como PNG/JPEG/WEBP -- edição recusada antes de chamar o provider.'
            )
        nome_arquivo = f'imagem.{_EXTENSAO_POR_MIME[mime]}'
        resposta = self._cliente().images.edit(
            model=MODELO_IMAGEM_PADRAO, image=(nome_arquivo, imagem_base, mime), prompt=instrucao, size=tamanho,
        )
        return [_decodificar_b64(item) for item in resposta.data]

    def variacao(self, imagem_base, **kwargs):
        # gpt-image-1 (modelo padrão atual) não expõe um endpoint de
        # variação dedicado -- falha explícita em vez de fingir suporte.
        raise NotImplementedError('variacao_nao_suportada_pelo_modelo_atual')

    def disponivel(self):
        return bool((self._cliente_injetado is not None) or os.getenv('OPENAI_API_KEY'))


# PNG 1x1 branco válido, gerado uma única vez -- usado só pelo mock
# abaixo, nunca em produção.
_PNG_1X1_BRANCO = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


class MockImageProvider(ImageGenerationProvider):
    sintetico = True
    """Nunca faz chamada de rede nem gera custo -- só para testes/demo
    (M15/M16 exigem isso explicitamente). Registra as chamadas recebidas
    para asserção em teste, sempre devolve o mesmo PNG mínimo válido."""

    def __init__(self):
        self.chamadas = []

    def gerar(self, prompt, **kwargs):
        self.chamadas.append(('gerar', prompt, kwargs))
        return [_PNG_1X1_BRANCO]

    def editar(self, imagem_base, instrucao, **kwargs):
        self.chamadas.append(('editar', instrucao, kwargs))
        return [_PNG_1X1_BRANCO]

    def variacao(self, imagem_base, **kwargs):
        self.chamadas.append(('variacao', kwargs))
        return [_PNG_1X1_BRANCO]

    def disponivel(self):
        return True


def criar_provider_padrao():
    """Único ponto de decisão de qual provider usar -- nunca hardcoded.
    `IMAGE_PROVIDER=openai` (padrão) usa a credencial já configurada; sem
    OPENAI_API_KEY real, cai em ImageProviderNaoConfigurado -- nunca
    finge disponibilidade."""
    nome = (os.getenv('IMAGE_PROVIDER') or 'openai').strip().lower()
    if nome == 'openai':
        provider = OpenAIImageProvider()
        return provider if provider.disponivel() else ImageProviderNaoConfigurado()
    return ImageProviderNaoConfigurado()
