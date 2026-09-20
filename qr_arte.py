"""Arte dos QR Codes rastreáveis: SVG, PNG e PDF a partir do MESMO desenho.

Regras que definem o desenho, na ordem em que importam:

1. **Ler vem antes de enfeitar.** O QR é escuro (#0b0a08) sobre um bloco
   creme (#f4ece1), com zona de silêncio de 4 módulos — o mínimo da norma.
   Um QR invertido (claro sobre escuro) fica bonito num cartão preto, mas
   leitores de iPhone e Android tratam inversão de forma irregular. O visual
   escuro e dourado da marca vive em volta do bloco, não dentro dele.
2. **Correção de erro nível Q (25%).** A URL é curta, então o QR fica com
   poucos módulos (versão 3-4) e cada módulo sai grande no papel — mais
   robusto a dobra, mancha e impressão ruim do que um nível H denso.
3. **Um só desenho.** SVG, PNG e PDF partem da mesma matriz e das mesmas
   medidas, para o arquivo impresso e o arquivo de tela nunca divergirem.
4. **No PDF, o QR é vetorial.** O fundo e o texto são um raster sem perdas
   (Flate, nunca JPEG — JPEG suja a borda do módulo e derruba a leitura);
   os módulos são retângulos vetoriais por cima, nítidos em qualquer escala.

A geração não depende de fonte da marca instalada: usa Georgia/DejaVu se
existirem e cai no padrão do Pillow. O SVG carrega a pilha de fontes da
marca e cai em Georgia.
"""
import io
import textwrap
import zlib
from html import escape

import segno

BASE_PUBLICA = 'https://maranhaocordial.com.br'

# Medidas do cartão (A6 a 300 dpi): 105 x 148 mm.
LARGURA = 1240
ALTURA = 1748
DPI = 300

PRETO = (11, 10, 8)
CREME = (244, 236, 225)
OURO = (212, 175, 55)
CREME_SUAVE = (201, 192, 179)
# 45% ouro sobre preto: equivale ao opacity=.45 da moldura interna no SVG.
OURO_DISCRETO = tuple(round(o * 0.45 + p * 0.55) for o, p in zip(OURO, PRETO))

ZONA_SILENCIO = 4  # módulos, mínimo da norma ISO/IEC 18004
NIVEL_CORRECAO = 'q'
LADO_BLOCO = 860  # px, bloco creme com a zona de silêncio dentro

PILHA_SVG = "'Cormorant Garamond', Georgia, 'Times New Roman', serif"
PILHA_SVG_SANS = "Inter, Arial, Helvetica, sans-serif"

FORMATOS = ('svg', 'png', 'pdf')
TIPOS_MIME = {'svg': 'image/svg+xml', 'png': 'image/png', 'pdf': 'application/pdf'}


def url_do_codigo(codigo_publico, base=BASE_PUBLICA):
    return base.rstrip('/') + '/q/' + codigo_publico


def _matriz(url):
    """Matriz de módulos (lista de listas de 0/1)."""
    codigo = segno.make(url, error=NIVEL_CORRECAO, boost_error=False, micro=False)
    return [[1 if celula else 0 for celula in linha] for linha in codigo.matrix]


def _geometria(n_modulos):
    """Escala inteira: cada módulo ocupa um número exato de pixels, sem
    interpolação — é o que mantém a borda nítida."""
    total = n_modulos + 2 * ZONA_SILENCIO
    escala = max(1, LADO_BLOCO // total)
    lado = total * escala
    x0 = (LARGURA - lado) // 2
    # Bloco mais alto que o centro do cartão: sobra folga entre a URL do rodapé e a
    # moldura dourada, e a chamada respira em cima.
    y0 = 640
    return {'total': total, 'escala': escala, 'lado': lado, 'x0': x0, 'y0': y0,
            'mx': x0 + ZONA_SILENCIO * escala, 'my': y0 + ZONA_SILENCIO * escala}


def _corridas(matriz):
    """Une módulos escuros vizinhos na horizontal: (linha, coluna, largura).
    Reduz milhares de retângulos a algumas centenas, sem mudar o desenho."""
    saida = []
    for r, linha in enumerate(matriz):
        c = 0
        while c < len(linha):
            if linha[c]:
                inicio = c
                while c < len(linha) and linha[c]:
                    c += 1
                saida.append((r, inicio, c - inicio))
            else:
                c += 1
    return saida


def _linhas_da_chamada(chamada):
    return textwrap.wrap(chamada.strip(), width=22) or [chamada.strip()]


def _hex(cor):
    return '#%02x%02x%02x' % cor


# ------------------------------------------------------------------ SVG

def gerar_svg(chamada, codigo_publico, base=BASE_PUBLICA):
    url = url_do_codigo(codigo_publico, base)
    matriz = _matriz(url)
    g = _geometria(len(matriz))
    partes = []
    for r, c, w in _corridas(matriz):
        x, y = g['mx'] + c * g['escala'], g['my'] + r * g['escala']
        partes.append('M%d %dh%dv%dh-%dz' % (x, y, w * g['escala'], g['escala'], w * g['escala']))
    linhas = _linhas_da_chamada(chamada)
    tam = 84 if len(linhas) <= 2 else 70
    y_texto = 400 - (len(linhas) - 1) * (tam // 2)
    texto = ''.join(
        '<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="%d" '
        'font-style="italic" fill="%s">%s</text>'
        % (LARGURA // 2, y_texto + i * int(tam * 1.18), PILHA_SVG, tam, _hex(CREME), escape(l))
        for i, l in enumerate(linhas))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="105mm" height="148mm" '
        'role="img" aria-labelledby="t">\n'
        '<title id="t">QR Code — %s</title>\n'
        '<rect width="%d" height="%d" fill="%s"/>\n'
        '<rect x="60" y="60" width="%d" height="%d" fill="none" stroke="%s" stroke-width="3"/>\n'
        '<rect x="80" y="80" width="%d" height="%d" fill="none" stroke="%s" stroke-width="1" opacity=".45"/>\n'
        '<text x="%d" y="190" text-anchor="middle" font-family="%s" font-size="30" '
        'letter-spacing="9" fill="%s">MARANHÃO CORDIAL</text>\n'
        '%s\n'
        '<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>\n'
        '<path d="%s" fill="%s"/>\n'
        '<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="34" fill="%s">'
        'Aponte a câmera do celular</text>\n'
        '<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="27" '
        'letter-spacing="1" fill="%s">%s</text>\n'
        '</svg>\n'
    ) % (LARGURA, ALTURA, escape(chamada),
         LARGURA, ALTURA, _hex(PRETO),
         LARGURA - 120, ALTURA - 120, _hex(OURO),
         LARGURA - 160, ALTURA - 160, _hex(OURO),
         LARGURA // 2, PILHA_SVG_SANS, _hex(OURO),
         texto,
         g['x0'], g['y0'], g['lado'], g['lado'], _hex(CREME),
         ''.join(partes), _hex(PRETO),
         LARGURA // 2, g['y0'] + g['lado'] + 90, PILHA_SVG_SANS, _hex(CREME_SUAVE),
         LARGURA // 2, g['y0'] + g['lado'] + 150, PILHA_SVG_SANS, _hex(OURO),
         escape(url.replace('https://', '')))


# ------------------------------------------------------------------ PNG / PDF

def _fonte(tamanho, serifada=True, italico=False):
    from PIL import ImageFont
    candidatas = []
    if serifada:
        candidatas += [
            '/System/Library/Fonts/Supplemental/Georgia Italic.ttf' if italico else '/System/Library/Fonts/Supplemental/Georgia.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf' if italico else '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf' if italico else '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf',
        ]
    else:
        candidatas += [
            '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        ]
    for caminho in candidatas:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


def _centralizado(desenho, y, texto, fonte, cor, espaco=0):
    """Texto centrado; `espaco` acrescenta tracking (só para caixa-alta)."""
    if espaco:
        larguras = [desenho.textlength(c, font=fonte) for c in texto]
        total = sum(larguras) + espaco * (len(texto) - 1)
        x = (LARGURA - total) / 2
        for c, w in zip(texto, larguras):
            desenho.text((x, y), c, font=fonte, fill=cor)
            x += w + espaco
        return
    desenho.text((LARGURA / 2, y), texto, font=fonte, fill=cor, anchor='mt')


def _desenhar_base(chamada, codigo_publico, matriz, base, com_modulos):
    from PIL import Image, ImageDraw
    g = _geometria(len(matriz))
    imagem = Image.new('RGB', (LARGURA, ALTURA), PRETO)
    d = ImageDraw.Draw(imagem)
    d.rectangle((60, 60, LARGURA - 60, ALTURA - 60), outline=OURO, width=3)
    # Segunda moldura, mais discreta. O SVG usa opacity .45; no raster a mesma
    # aparência vem de uma mistura ouro/preto já calculada (PIL não tem alfa aqui).
    d.rectangle((80, 80, LARGURA - 80, ALTURA - 80), outline=OURO_DISCRETO, width=1)
    _centralizado(d, 165, 'MARANHÃO CORDIAL', _fonte(30, serifada=False), OURO, espaco=9)
    linhas = _linhas_da_chamada(chamada)
    tam = 84 if len(linhas) <= 2 else 70
    fonte_chamada = _fonte(tam, italico=True)
    y = 400 - (len(linhas) - 1) * (tam // 2) - int(tam * 0.75)
    for linha in linhas:
        _centralizado(d, y, linha, fonte_chamada, CREME)
        y += int(tam * 1.18)
    d.rectangle((g['x0'], g['y0'], g['x0'] + g['lado'] - 1, g['y0'] + g['lado'] - 1), fill=CREME)
    if com_modulos:
        for r, c, w in _corridas(matriz):
            x, yy = g['mx'] + c * g['escala'], g['my'] + r * g['escala']
            d.rectangle((x, yy, x + w * g['escala'] - 1, yy + g['escala'] - 1), fill=PRETO)
    _centralizado(d, g['y0'] + g['lado'] + 60, 'Aponte a câmera do celular', _fonte(34, serifada=False), CREME_SUAVE)
    _centralizado(d, g['y0'] + g['lado'] + 125, url_do_codigo(codigo_publico, base).replace('https://', ''),
                  _fonte(27, serifada=False), OURO, espaco=1)
    return imagem, g


def gerar_png(chamada, codigo_publico, base=BASE_PUBLICA):
    matriz = _matriz(url_do_codigo(codigo_publico, base))
    imagem, _ = _desenhar_base(chamada, codigo_publico, matriz, base, com_modulos=True)
    saida = io.BytesIO()
    imagem.save(saida, format='PNG', dpi=(DPI, DPI), optimize=True)
    return saida.getvalue()


def gerar_pdf(chamada, codigo_publico, base=BASE_PUBLICA):
    """PDF de uma página A6: raster sem perdas por baixo, módulos vetoriais
    por cima. Escrito à mão para não depender de biblioteca e para garantir
    Flate (JPEG derrubaria a leitura)."""
    matriz = _matriz(url_do_codigo(codigo_publico, base))
    imagem, g = _desenhar_base(chamada, codigo_publico, matriz, base, com_modulos=False)
    pontos = 72.0 / DPI
    w_pt, h_pt = LARGURA * pontos, ALTURA * pontos
    bruto = zlib.compress(imagem.tobytes(), 9)

    conteudo = ['q %.4f 0 0 %.4f 0 0 cm /Fundo Do Q' % (w_pt, h_pt),
                '%.3f %.3f %.3f rg' % tuple(c / 255 for c in PRETO)]
    for r, c, w in _corridas(matriz):
        x = (g['mx'] + c * g['escala']) * pontos
        y = (ALTURA - (g['my'] + (r + 1) * g['escala'])) * pontos
        conteudo.append('%.3f %.3f %.3f %.3f re f' % (x, y, w * g['escala'] * pontos, g['escala'] * pontos))
    fluxo = zlib.compress('\n'.join(conteudo).encode('ascii'), 9)

    objetos = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.3f %.3f] /Resources << /XObject << /Fundo 4 0 R >> >> '
         '/Contents 5 0 R >>' % (w_pt, h_pt)).encode(),
        (b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB '
         b'/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n' % (LARGURA, ALTURA, len(bruto)))
        + bruto + b'\nendstream',
        (b'<< /Filter /FlateDecode /Length %d >>\nstream\n' % len(fluxo)) + fluxo + b'\nendstream',
        b'<< /Title (QR Code Maranhao Cordial) /Producer (Maranhao Cordial) >>',
    ]
    saida = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    posicoes = []
    for i, corpo in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b'%d 0 obj\n' % i + corpo + b'\nendobj\n'
    xref = len(saida)
    saida += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objetos) + 1)
    for p in posicoes:
        saida += b'%010d 00000 n \n' % p
    saida += (b'trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n'
              % (len(objetos) + 1, xref))
    return bytes(saida)


def gerar(formato, chamada, codigo_publico, base=BASE_PUBLICA):
    if formato == 'svg':
        return gerar_svg(chamada, codigo_publico, base).encode('utf-8')
    if formato == 'png':
        return gerar_png(chamada, codigo_publico, base)
    if formato == 'pdf':
        return gerar_pdf(chamada, codigo_publico, base)
    raise ValueError('formato_invalido')
