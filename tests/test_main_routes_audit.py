"""Auditoria estrutural de main.py: previne exatamente a classe de bug que
causou o 404 relatado (rota registrada em algum módulo mi_*.py mas cujo
`registrar_rotas*` nunca é chamado -- ou chamado, mas com uma URL diferente
da que o frontend usa).

1. Toda função `registrar_rotas*` importada em main.py precisa ser
   efetivamente CHAMADA (mesma falha histórica de mi_conselho_fatos, que
   ficou com rotas mortas por uma rodada inteira).
2. Toda URL literal chamada por maranhao-intelligence.js precisa bater com
   alguma regra real do Flask, montada executando os MESMOS registradores
   que main.py executa -- nunca reimplementando a lógica de rota."""
import ast
import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask

MAIN_SRC = Path('main.py').read_text()
JS_SRC = Path('maranhao-backend/maranhao-intelligence.js').read_text()

IMPORT_RE = re.compile(
    r'^from (?P<modulo>\S+) import (?P<nome>registrar_rotas\w*)(?: as (?P<alias>\w+))?\s*$',
    re.MULTILINE,
)


def _registradores_importados():
    """(modulo, nome_real, nome_local) para cada `registrar_rotas*` importado em main.py."""
    resultado = []
    for m in IMPORT_RE.finditer(MAIN_SRC):
        nome_local = m.group('alias') or m.group('nome')
        resultado.append((m.group('modulo'), m.group('nome'), nome_local))
    return resultado


class TodoRegistradorEhChamado(unittest.TestCase):
    def test_todo_registrar_rotas_importado_e_realmente_invocado(self):
        registradores = _registradores_importados()
        self.assertGreater(len(registradores), 15, 'esperava dezenas de registradores em main.py')
        nao_chamados = []
        for modulo, _nome, alias in registradores:
            padrao_chamada = re.compile(re.escape(alias) + r'\s*\(\s*app\s*,')
            if not padrao_chamada.search(MAIN_SRC):
                nao_chamados.append(f'{modulo}.{alias}')
        self.assertEqual(nao_chamados, [], f'registrado mas NUNCA chamado (rota morta): {nao_chamados}')

    def test_todos_os_modulos_p0_p5_estao_na_lista_de_registradores(self):
        modulos = {m for m, _, _ in _registradores_importados()}
        esperados = {
            'mi_skus', 'mi_lotes', 'mi_unidades', 'mi_estabelecimentos',
            'mi_relacionamento_360', 'mi_inteligencia_relacionamento',
            'mi_outcome_relacionamento', 'mi_territorio_inteligencia',
            'mi_forecast_readiness', 'mi_intelligence_api',
        }
        faltando = esperados - modulos
        self.assertEqual(faltando, set(), f'módulo P0-P5 sem registrador algum em main.py: {faltando}')


def _app_com_todos_os_registradores():
    """Monta um Flask app executando os MESMOS registradores que main.py
    executa (mesma função, mesmo import) -- nunca reimplementa rota.

    Nem todo `registrar_rotas*` tem a mesma assinatura (ex.: o de
    acoes_comerciais é `registrar_rotas(app, namespace)`, não
    `(app, factory, autorizado)`) -- por isso o número de argumentos
    passados é decidido por introspecção, igual o Python faria."""
    app = Flask(__name__)
    factory = MagicMock()
    autorizado = lambda: True
    args_possiveis = [app, factory, autorizado, '.']  # 4º: pasta do frontend (registrar_rotas_qr)
    for modulo, nome, alias in _registradores_importados():
        mod = __import__(modulo, fromlist=[nome])
        registrador = getattr(mod, nome)
        n_params = len(inspect.signature(registrador).parameters)
        registrador(*args_possiveis[:n_params])
    return app


def _urls_chamadas_pelo_frontend():
    """Extrai toda URL literal/templada passada para get() em
    maranhao-intelligence.js (aspas simples ou template literal com
    backtick), normalizando `${...}` para um segmento dinâmico fixo ('X') --
    o bastante para bater com qualquer <param> do Flask na mesma posição."""
    chamadas = re.findall(r"get\('([^']+)'\)", JS_SRC) + re.findall(r'get\(`([^`]+)`\)', JS_SRC)
    normalizadas = []
    for url in chamadas:
        sem_query = url.split('?')[0]
        sem_template = re.sub(r'\$\{[^}]+\}', 'X', sem_query)
        normalizadas.append(sem_template)
    return sorted(set(normalizadas))


class UrlsDoFrontendBatemComRotasReais(unittest.TestCase):
    def test_toda_url_chamada_pelo_painel_tem_rota_registrada(self):
        # Distingue 404 de ROTEAMENTO (nenhuma regra do Flask bateu -- o bug
        # relatado) de um 404 de NEGÓCIO (a rota existe, rodou, e respondeu
        # 'não encontrado' em JSON -- ex.: relacionamento inexistente). Só o
        # primeiro é falha desta auditoria; o Flask nunca devolve JSON no
        # 404 de roteamento (é a página de erro padrão do werkzeug).
        app = _app_com_todos_os_registradores()
        cliente = app.test_client()
        urls = _urls_chamadas_pelo_frontend()
        self.assertGreater(len(urls), 2, 'não encontrei nenhuma chamada get(...) no JS -- regex desatualizada?')
        sem_rota = []
        for url in urls:
            resp = cliente.get(url, headers={'X-Admin-Key': 'x'})
            if resp.status_code == 404 and resp.get_json() is None:
                sem_rota.append(url)
        self.assertEqual(sem_rota, [], f'URL chamada pelo painel sem nenhuma rota Flask correspondente: {sem_rota}')

    def test_lista_de_urls_extraidas_bate_com_o_esperado(self):
        # Trava de regressão: se alguém adicionar/remover uma chamada get()
        # no JS, este teste força atualizar a lista abaixo conscientemente.
        urls = _urls_chamadas_pelo_frontend()
        esperadas = {
            '/api/admin/mi/overview', '/api/admin/mi/fila-decisao', '/api/admin/mi/painel',
            '/api/admin/mi/relacionamento/X/contrato',
        }
        self.assertEqual(set(urls), esperadas)


if __name__ == '__main__':
    unittest.main()
