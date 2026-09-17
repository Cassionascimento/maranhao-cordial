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
        import io
        resposta = self._cliente().images.edit(
            model=MODELO_IMAGEM_PADRAO, image=io.BytesIO(imagem_base), prompt=instrucao, size=tamanho,
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
