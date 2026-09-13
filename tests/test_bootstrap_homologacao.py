"""Wrapper fail-closed de homologação -- bootstrap_homologacao.py.
Nenhum teste aqui importa main.py de verdade nem conecta em banco real."""
import contextlib
import io
import os
import unittest

import bootstrap_homologacao as b

_CHAVES = (b.VAR_HOMOLOG, b.VAR_PRODUCAO, b.VAR_CONFIRMACAO)
SENHA_MARCADA = 'SENHA_SECRETA_DE_TESTE_9x7'
URL_SEGURA = f'postgres://user:{SENHA_MARCADA}@algum-host/maranhao_cordial_homolog'


@contextlib.contextmanager
def ambiente(**variaveis):
    anteriores = {k: os.environ.get(k) for k in _CHAVES}
    for k in _CHAVES:
        os.environ.pop(k, None)
    os.environ.update(variaveis)
    try:
        yield
    finally:
        for k in _CHAVES:
            os.environ.pop(k, None)
        for k, v in anteriores.items():
            if v is not None:
                os.environ[k] = v


class ImportadorFalso:
    """Nunca importa main.py -- só registra que foi chamado."""
    def __init__(self):
        self.chamado = 0

    def __call__(self):
        self.chamado += 1


class ValidacaoAmbiente(unittest.TestCase):
    def test_sem_database_url_homolog_aborta(self):
        with ambiente(HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'database_url_homolog_ausente')

    def test_database_url_normal_presente_aborta(self):
        with ambiente(DATABASE_URL='postgres://x/producao_de_verdade',
                       DATABASE_URL_HOMOLOG=URL_SEGURA,
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            importador = ImportadorFalso()
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=importador)
            self.assertEqual(str(ctx.exception), 'database_url_de_producao_definida')
        self.assertEqual(importador.chamado, 0)

    def test_url_sem_esquema_postgres_e_invalida(self):
        with ambiente(DATABASE_URL_HOMOLOG='nao-e-uma-url-de-verdade',
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'url_invalida_esquema_nao_postgres')

    def test_url_sem_host_e_invalida(self):
        with ambiente(DATABASE_URL_HOMOLOG='postgres:///maranhao_cordial_homolog',
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'url_invalida_sem_host')

    def test_url_sem_nome_de_banco_e_recusada(self):
        with ambiente(DATABASE_URL_HOMOLOG='postgres://user:pass@host/',
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'nome_de_banco_nao_identificavel')

    def test_banco_sem_marcador_homolog_ou_staging_e_recusado(self):
        for nome in ('maranhao_cordial', 'postgres'):
            with self.subTest(nome=nome):
                with ambiente(DATABASE_URL_HOMOLOG=f'postgres://user:pass@host/{nome}',
                               HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
                    with self.assertRaises(b.BootstrapRecusado) as ctx:
                        b.executar(importador=ImportadorFalso())
                self.assertEqual(str(ctx.exception), 'nome_de_banco_sem_marcador_de_homologacao')

    def test_banco_contendo_prod_ou_production_e_sempre_recusado(self):
        for nome in ('production', 'prod', 'maranhao_prod', 'maranhao_cordial_production'):
            with self.subTest(nome=nome):
                with ambiente(DATABASE_URL_HOMOLOG=f'postgres://user:pass@host/{nome}',
                               HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
                    with self.assertRaises(b.BootstrapRecusado) as ctx:
                        b.executar(importador=ImportadorFalso())
                self.assertEqual(str(ctx.exception), 'nome_de_banco_parece_producao')

    def test_banco_com_homolog_e_prod_juntos_e_recusado_sempre(self):
        # "recusar sempre" quando aparece marcador de produção -- mesmo
        # que um marcador seguro também esteja presente no nome.
        with ambiente(DATABASE_URL_HOMOLOG='postgres://user:pass@host/homolog_production',
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'nome_de_banco_parece_producao')

    def test_banco_com_marcador_staging_e_aceito(self):
        with ambiente(DATABASE_URL_HOMOLOG='postgres://user:pass@host/maranhao-cordial-staging',
                       HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            importador = ImportadorFalso()
            b.executar(importador=importador)
        self.assertEqual(importador.chamado, 1)

    def test_confirmacao_ausente_aborta(self):
        with ambiente(DATABASE_URL_HOMOLOG=URL_SEGURA):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertEqual(str(ctx.exception), 'confirmacao_ausente_ou_incorreta')

    def test_confirmacao_errada_aborta(self):
        for valor_errado in ('sim', 'EU_CONFIRMO_BANCO_ISOLADO', 'eu_confirm0_banco_isolado', ''):
            with self.subTest(valor=valor_errado):
                with ambiente(DATABASE_URL_HOMOLOG=URL_SEGURA, HOMOLOGACAO_CONFIRMAR=valor_errado):
                    with self.assertRaises(b.BootstrapRecusado) as ctx:
                        b.executar(importador=ImportadorFalso())
                self.assertEqual(str(ctx.exception), 'confirmacao_ausente_ou_incorreta')

    def test_url_segura_e_confirmacao_correta_chega_ao_import_mockado(self):
        with ambiente(DATABASE_URL_HOMOLOG=URL_SEGURA, HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            importador = ImportadorFalso()
            resultado = b.executar(importador=importador)
        self.assertTrue(resultado['success'])
        self.assertEqual(importador.chamado, 1)

    def test_apos_sucesso_database_url_e_setada_com_o_valor_de_homologacao(self):
        with ambiente(DATABASE_URL_HOMOLOG=URL_SEGURA, HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            b.executar(importador=ImportadorFalso())
            self.assertEqual(os.environ.get('DATABASE_URL'), URL_SEGURA)


class NuncaVazaSegredo(unittest.TestCase):
    def _stdout_capturado(self, **variaveis):
        saida = io.StringIO()
        with ambiente(**variaveis):
            with contextlib.redirect_stdout(saida):
                try:
                    b.executar(importador=ImportadorFalso())
                except b.BootstrapRecusado:
                    pass
        return saida.getvalue()

    def test_falha_por_ausencia_nunca_imprime_nada_com_a_senha(self):
        saida = self._stdout_capturado(HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO)
        self.assertNotIn(SENHA_MARCADA, saida)

    def test_falha_por_producao_nunca_imprime_nada_com_a_senha(self):
        saida = self._stdout_capturado(
            DATABASE_URL=f'postgres://x:{SENHA_MARCADA}@host/producao',
            DATABASE_URL_HOMOLOG=URL_SEGURA, HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO,
        )
        self.assertNotIn(SENHA_MARCADA, saida)

    def test_sucesso_nunca_imprime_a_senha_nem_a_url_completa(self):
        saida = io.StringIO()
        with ambiente(DATABASE_URL_HOMOLOG=URL_SEGURA, HOMOLOGACAO_CONFIRMAR=b.VALOR_CONFIRMACAO_ESPERADO):
            with contextlib.redirect_stdout(saida):
                b.executar(importador=ImportadorFalso())
        self.assertNotIn(SENHA_MARCADA, saida.getvalue())
        self.assertNotIn(URL_SEGURA, saida.getvalue())

    def test_excecao_nunca_expoe_a_url_no_str(self):
        # A mensagem da exceção em si (não só o stdout) precisa ser segura,
        # já que ela pode ser logada por quem chama.
        with ambiente(DATABASE_URL_HOMOLOG=f'postgres://user:{SENHA_MARCADA}@host/producao'):
            with self.assertRaises(b.BootstrapRecusado) as ctx:
                b.executar(importador=ImportadorFalso())
        self.assertNotIn(SENHA_MARCADA, str(ctx.exception))


class ScriptCLI(unittest.TestCase):
    def test_falha_fail_closed_encerra_com_codigo_diferente_de_zero(self):
        import subprocess
        import sys as sistema
        env = {k: v for k, v in os.environ.items() if k not in _CHAVES}
        resultado = subprocess.run(
            [sistema.executable, 'bootstrap_homologacao.py'],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=env, capture_output=True, text=True, timeout=15,
        )
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('recusada', resultado.stdout.lower())


class SemEfeitosExternos(unittest.TestCase):
    def test_nenhum_import_de_topo_de_modulo_traz_transporte_main_ou_job(self):
        # Só os imports DIRETOS do módulo (não os de dentro de função) --
        # 'import main' dentro de _importar_main() é esperado e correto,
        # coberto por outro teste; aqui o que importa é o nível do módulo.
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(b))
        modulos_de_topo = set()
        for no in arvore.body:
            if isinstance(no, ast.Import):
                modulos_de_topo.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos_de_topo.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'anthropic', 'openai', 'psycopg2',
                          'main', 'mi_conselho_job', 'whatsapp_meta', 'whatsapp_omnichannel',
                          'gmail_legado', 'flask_socketio'):
            self.assertNotIn(proibido, modulos_de_topo)

    def test_codigo_fonte_nunca_chama_app_run_socketio_run_ou_o_job(self):
        # A prosa do docstring cita "app.run()"/"socketio.run()" só para
        # explicar o que NUNCA é chamado -- removida antes da busca.
        import ast
        import inspect
        codigo = inspect.getsource(b)
        docstring = ast.get_docstring(ast.parse(codigo))
        corpo = codigo.replace(docstring, '', 1) if docstring else codigo
        for proibido in ('app.run(', 'socketio.run(', 'mi_conselho_job', 'processar_e_registrar',
                          'CONSELHO_JOB_HABILITADO'):
            self.assertNotIn(proibido, corpo)

    def test_main_so_e_importado_dentro_da_funcao_dedicada_isolada(self):
        import inspect
        codigo = inspect.getsource(b)
        # 'import main' só pode aparecer uma vez, dentro de _importar_main.
        self.assertEqual(codigo.count('import main'), 1)
        self.assertIn('def _importar_main():\n    import main', codigo)


if __name__ == '__main__':
    unittest.main()
