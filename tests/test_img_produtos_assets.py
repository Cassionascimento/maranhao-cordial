"""Ativos de imagem do catálogo em maranhao-backend/img/produtos/.

Não é lógica de negócio -- é só garantir que um arquivo entregue para
upload pelo painel (Comercial → Catálogo → mídia) existe de verdade, é
uma imagem íntegra e tem um enquadramento adequado a cartão de vitrine
(quadrado). Qual imagem é a "capa" de um produto continua decidido
inteiramente pelo banco via o painel -- nada aqui fixa isso no código
(ver catalogo_produtos.py, sem nenhuma referência a este arquivo)."""
import unittest
from pathlib import Path

from PIL import Image

PASTA = Path(__file__).resolve().parents[1] / 'maranhao-backend' / 'img' / 'produtos'


class ImagemGuaranaGengibre(unittest.TestCase):
    ARQUIVO = PASTA / 'maranhao-cordial-guarana-gengibre.webp'

    def test_arquivo_existe_e_abre_como_imagem_valida(self):
        self.assertTrue(self.ARQUIVO.is_file(), self.ARQUIVO)
        with Image.open(self.ARQUIVO) as im:
            im.verify()

    def test_e_quadrada_boa_para_cartao_de_vitrine(self):
        with Image.open(self.ARQUIVO) as im:
            largura, altura = im.size
        self.assertEqual(largura, altura)
        self.assertGreaterEqual(largura, 600)

    def test_recorte_real_da_foto_das_tres_garrafas_nao_e_novo_bitmap_gerado(self):
        # A garantia que importa aqui não é de negócio, é de honestidade: o
        # arquivo é um recorte de uma foto real já usada no site (não uma
        # imagem inventada). Comparamos os bytes de pixel do recorte com a
        # região equivalente da foto original -- salvo em WebP sem perdas,
        # têm de ser idênticos byte a byte (.tobytes(), não getdata(): a
        # mesma comparação por milhares de tuplas Python é ordens de
        # grandeza mais lenta).
        origem = PASTA.parent / 'hero' / 'tres-cordiais.webp'
        with Image.open(origem) as original, Image.open(self.ARQUIVO) as recorte:
            esperado = original.crop((30, 0, 690, original.height))
            w, h = esperado.size
            lado = h
            fundo = Image.new('RGB', (lado, lado), (0, 0, 0))
            fundo.paste(esperado, ((lado - w) // 2, 0))
            self.assertEqual(fundo.tobytes(), recorte.convert('RGB').tobytes())

    def test_nenhum_codigo_fixa_esta_imagem_como_capa(self):
        # A troca de imagem principal é feita pelo painel (upload + "usar
        # como capa"), nunca por um caminho de arquivo hardcoded.
        raiz = PASTA.parents[2]
        for arquivo in ('catalogo_produtos.py', 'migrations/030_catalogo_produtos.sql'):
            texto = (raiz / arquivo).read_text(encoding='utf-8')
            self.assertNotIn('guarana-gengibre', texto, arquivo)


if __name__ == '__main__':
    unittest.main()
