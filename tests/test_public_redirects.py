"""Homepage simplificada: /raizes e /experience (com ou sem .html) devem
redirecionar para a home, nunca mais servir as páginas antigas -- mas os
arquivos raizes.html/experience.html continuam no projeto (reversível,
não apagados). Extrai as funções via AST, sem importar main.py inteiro."""
import ast
import re
import unittest
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
MAIN_TEXTO = (ROOT / "main.py").read_text()


def carregar_funcoes(nomes, namespace):
    arvore = ast.parse(MAIN_TEXTO)
    nos = []
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in nomes:
            no.decorator_list = []
            nos.append(no)
    assert len(nos) == len(nomes), nomes
    exec(compile(ast.Module(body=nos, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


class RedirectsHomepageSimplificada(unittest.TestCase):
    def setUp(self):
        namespace = {"redirect": __import__("flask").redirect}
        carregar_funcoes(["experience", "raizes"], namespace)
        self.app = Flask(__name__)
        self.app.add_url_rule("/experience", "experience", namespace["experience"])
        self.app.add_url_rule("/experience.html", "experience_html", namespace["experience"])
        self.app.add_url_rule("/raizes", "raizes", namespace["raizes"])
        self.app.add_url_rule("/raizes.html", "raizes_html", namespace["raizes"])
        self.client = self.app.test_client()

    def test_experience_redireciona_para_home(self):
        resposta = self.client.get("/experience")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.headers["Location"], "/")

    def test_experience_html_redireciona_para_home(self):
        resposta = self.client.get("/experience.html")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.headers["Location"], "/")

    def test_raizes_redireciona_para_home(self):
        resposta = self.client.get("/raizes")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.headers["Location"], "/")

    def test_raizes_html_redireciona_para_home(self):
        resposta = self.client.get("/raizes.html")
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta.headers["Location"], "/")

    def test_redirect_e_302_temporario_nao_301_permanente(self):
        # Reversibilidade: um 301 seria fixado em cache por navegadores/
        # motores de busca por muito mais tempo -- 302 mantém a decisão
        # fácil de desfazer.
        for caminho in ("/experience", "/experience.html", "/raizes", "/raizes.html"):
            with self.subTest(caminho=caminho):
                resposta = self.client.get(caminho)
                self.assertEqual(resposta.status_code, 302)

    def test_arquivos_html_antigos_nao_foram_apagados(self):
        self.assertTrue((ROOT / "maranhao-backend" / "raizes.html").is_file())
        self.assertTrue((ROOT / "maranhao-backend" / "experience.html").is_file())

    def test_rotas_declaradas_em_main_py_cobrem_com_e_sem_html(self):
        # Confirma que as rotas realmente registradas em main.py (não só as
        # que este teste registrou manualmente) cobrem as 4 variantes.
        bloco = re.search(
            r'@app\.route\("/experience"\)\s*'
            r'@app\.route\("/experience\.html"\)\s*'
            r'def experience\(\):',
            MAIN_TEXTO,
        )
        self.assertIsNotNone(bloco, "rotas de /experience e /experience.html ausentes em main.py")
        bloco = re.search(
            r'@app\.route\("/raizes"\)\s*'
            r'@app\.route\("/raizes\.html"\)\s*'
            r'def raizes\(\):',
            MAIN_TEXTO,
        )
        self.assertIsNotNone(bloco, "rotas de /raizes e /raizes.html ausentes em main.py")


if __name__ == "__main__":
    unittest.main()
