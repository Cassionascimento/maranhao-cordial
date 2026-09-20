"""Os QRs impressos precisam ser lidos. Um decodificador independente
(zxing-cpp) lê SVG, PNG e PDF de cada QR — e o PNG também degradado como um
celular de feira degrada: reduzido, desfocado, girado, cinza, sem contraste,
JPEG. Isto NÃO substitui a leitura em iPhone/Android físicos e em papel
impresso, que continua sendo verificação manual declarada."""
import io
import re
import unittest
import zlib

from PIL import Image, ImageDraw, ImageFilter

import qr_arte

try:
    import zxingcpp
except ImportError:  # o CI instala requirements-test.txt; sem ele, falha em vez de pular
    zxingcpp = None

CODIGOS = {
    'p8qp3av4g5': 'Provou? Conte o que achou.',
    'wrn2hkps5b': 'Conte sua experiência com Maranhão.',
    '272j7fy6my': 'Quer comprar, servir ou representar Maranhão?',
    'gcy3t5drzj': 'Conheça o universo Maranhão Cordial.',
}


def ler(imagem):
    return [b.text for b in zxingcpp.read_barcodes(imagem)]


def esperado(codigo):
    return 'https://maranhaocordial.com.br/q/' + codigo


def png_para_imagem(dados):
    return Image.open(io.BytesIO(dados)).convert('RGB')


def rasterizar_svg(texto):
    """Desenha só o que o leitor precisa (fundo, bloco creme, módulos) a partir
    do próprio SVG — o que valida a geometria do arquivo, não a do PNG."""
    imagem = Image.new('RGB', (qr_arte.LARGURA, qr_arte.ALTURA), qr_arte.PRETO)
    desenho = ImageDraw.Draw(imagem)
    for x, y, w, h, cor in re.findall(r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="(#[0-9a-f]{6})"/>', texto):
        desenho.rectangle([int(x), int(y), int(x) + int(w) - 1, int(y) + int(h) - 1], fill=cor)
    caminho = re.search(r'<path d="([^"]+)" fill="(#[0-9a-f]{6})"/>', texto)
    for x, y, w, h in re.findall(r'M(\d+) (\d+)h(\d+)v(\d+)h-\d+z', caminho.group(1)):
        desenho.rectangle([int(x), int(y), int(x) + int(w) - 1, int(y) + int(h) - 1], fill=caminho.group(2))
    return imagem


def rasterizar_pdf(dados):
    """Reconstrói a página: a imagem de fundo (Flate) e os retângulos vetoriais."""
    fundo = None
    for m in re.finditer(rb'/Width (\d+) /Height (\d+) /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length (\d+) >>\nstream\n', dados):
        w, h, n = int(m.group(1)), int(m.group(2)), int(m.group(3))
        bruto = zlib.decompress(dados[m.end():m.end() + n])
        fundo = Image.frombytes('RGB', (w, h), bruto)
    assert fundo is not None, 'imagem de fundo não encontrada no PDF'
    pontos = 72.0 / qr_arte.DPI
    fim = dados.rfind(b'endstream', 0, dados.find(b'6 0 obj'))
    inicio = dados.rfind(b'stream\n', 0, fim) + len(b'stream\n')
    conteudo = zlib.decompress(dados[inicio:fim].rstrip(b'\n')).decode('ascii')
    desenho = ImageDraw.Draw(fundo)
    for x, y, w, h in re.findall(r'([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re f', conteudo):
        x, y, w, h = (float(v) / pontos for v in (x, y, w, h))
        topo = qr_arte.ALTURA - y - h
        desenho.rectangle([round(x), round(topo), round(x + w) - 1, round(topo + h) - 1], fill=qr_arte.PRETO)
    return fundo


@unittest.skipIf(zxingcpp is None, 'zxing-cpp ausente: pip install -r requirements-test.txt')
class LeituraDosQRs(unittest.TestCase):
    def test_os_tres_formatos_de_cada_qr_decodificam_para_a_url_certa(self):
        for codigo, chamada in CODIGOS.items():
            with self.subTest(codigo=codigo):
                svg = qr_arte.gerar('svg', chamada, codigo).decode()
                png = qr_arte.gerar('png', chamada, codigo)
                pdf = qr_arte.gerar('pdf', chamada, codigo)
                self.assertEqual(ler(png_para_imagem(png)), [esperado(codigo)], 'png')
                self.assertEqual(ler(rasterizar_svg(svg)), [esperado(codigo)], 'svg')
                self.assertEqual(ler(rasterizar_pdf(pdf)), [esperado(codigo)], 'pdf')

    def test_nao_ha_leitura_cruzada_o_codigo_de_um_nao_decodifica_como_outro(self):
        lidos = {c: ler(png_para_imagem(qr_arte.gerar('png', t, c)))[0] for c, t in CODIGOS.items()}
        self.assertEqual(len(set(lidos.values())), 4)

    def degradar(self, codigo, chamada):
        original = png_para_imagem(qr_arte.gerar('png', chamada, codigo))
        cinza = original.convert('L').convert('RGB')
        sem_contraste = Image.eval(original, lambda v: 100 + v * 60 // 255)
        jpeg = io.BytesIO()
        original.resize((520, 736), Image.BILINEAR).save(jpeg, 'JPEG', quality=35)
        return {
            'reduzido_25%': original.resize((310, 437), Image.BILINEAR),
            'reduzido_pequeno': original.resize((372, 524), Image.BILINEAR),
            'desfocado': original.filter(ImageFilter.GaussianBlur(3)),
            'girado_10': original.rotate(10, expand=True, fillcolor=qr_arte.PRETO, resample=Image.BICUBIC),
            'girado_45': original.rotate(45, expand=True, fillcolor=qr_arte.PRETO, resample=Image.BICUBIC),
            'cinza': cinza,
            'baixo_contraste': sem_contraste,
            'jpeg_35': Image.open(io.BytesIO(jpeg.getvalue())).convert('RGB'),
            'reduzido_e_desfocado': original.resize((400, 566), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2)),
        }

    def test_qr_de_feira_le_com_degradacao_de_celular(self):
        for codigo, chamada in CODIGOS.items():
            for nome, imagem in self.degradar(codigo, chamada).items():
                with self.subTest(codigo=codigo, degradacao=nome):
                    self.assertEqual(ler(imagem), [esperado(codigo)])

    def test_quadro_impresso_pequeno_em_papel_a6_a_150dpi_ainda_le(self):
        # Meio-termo real: A6 a 150 dpi.
        for codigo, chamada in CODIGOS.items():
            imagem = png_para_imagem(qr_arte.gerar('png', chamada, codigo)).resize((620, 874), Image.LANCZOS)
            self.assertEqual(ler(imagem), [esperado(codigo)], codigo)


class Estrutura(unittest.TestCase):
    def test_nivel_de_correcao_e_zona_de_silencio(self):
        self.assertEqual(qr_arte.NIVEL_CORRECAO, 'q')
        self.assertGreaterEqual(qr_arte.ZONA_SILENCIO, 4, 'ISO/IEC 18004 exige 4 módulos')

    def test_modulo_tem_tamanho_inteiro_em_pixels_e_bloco_cabe_no_cartao(self):
        for codigo in CODIGOS:
            n = len(qr_arte._matriz(qr_arte.url_do_codigo(codigo)))
            g = qr_arte._geometria(n)
            self.assertGreaterEqual(g['escala'], 8, 'módulo pequeno demais para impressão')
            self.assertLessEqual(g['lado'], qr_arte.LADO_BLOCO)
            self.assertGreater(g['x0'], 160)
            self.assertLess(g['x0'] + g['lado'], qr_arte.LARGURA - 160)

    def test_url_carrega_so_o_codigo_opaco(self):
        self.assertEqual(qr_arte.url_do_codigo('p8qp3av4g5'), 'https://maranhaocordial.com.br/q/p8qp3av4g5')
        self.assertEqual(qr_arte.url_do_codigo('p8qp3av4g5', 'https://x.com/'), 'https://x.com/q/p8qp3av4g5')

    def test_pdf_e_valido_e_tem_uma_pagina(self):
        from pypdf import PdfReader
        leitor = PdfReader(io.BytesIO(qr_arte.gerar('pdf', 'Provou? Conte o que achou.', 'p8qp3av4g5')))
        self.assertEqual(len(leitor.pages), 1)

    def test_svg_e_xml_valido_e_traz_a_chamada_e_a_url(self):
        from xml.etree import ElementTree
        texto = qr_arte.gerar('svg', 'Quer comprar, servir ou representar Maranhão?', '272j7fy6my').decode()
        ElementTree.fromstring(texto)
        self.assertIn('maranhaocordial.com.br/q/272j7fy6my', texto)
        self.assertIn('Aponte a câmera do celular', texto)

    def test_chamada_com_caractere_xml_e_escapada(self):
        texto = qr_arte.gerar('svg', 'A & B <c>', 'p8qp3av4g5').decode()
        from xml.etree import ElementTree
        ElementTree.fromstring(texto)

    def test_formato_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            qr_arte.gerar('gif', 'x', 'p8qp3av4g5')

    def test_geracao_e_deterministica(self):
        a = qr_arte.gerar('svg', 'Provou? Conte o que achou.', 'p8qp3av4g5')
        self.assertEqual(a, qr_arte.gerar('svg', 'Provou? Conte o que achou.', 'p8qp3av4g5'))


@unittest.skipIf(zxingcpp is None, 'zxing-cpp ausente')
class ArtesEntregues(unittest.TestCase):
    """O que está em artes/qr é o que vai para a gráfica: tem de bater com a
    migration (fonte dos códigos) e ler para a URL certa."""

    def test_artes_entregues_leem_e_o_svg_e_o_da_geracao_atual(self):
        from scripts.gerar_qr_artes import qrs_iniciais, RAIZ
        qrs = qrs_iniciais()
        self.assertEqual(len(qrs), 4)
        for codigo, slug, chamada in qrs:
            base = RAIZ / 'artes' / 'qr' / f'qr_{slug}'
            self.assertEqual(ler(Image.open(base.with_suffix('.png'))), [esperado(codigo)], slug)
            self.assertEqual(base.with_suffix('.svg').read_bytes(), qr_arte.gerar('svg', chamada, codigo), slug)
            self.assertEqual(ler(rasterizar_pdf(base.with_suffix('.pdf').read_bytes())), [esperado(codigo)], slug)


if __name__ == '__main__':
    unittest.main()
