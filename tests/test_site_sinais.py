"""ETAPA 5.4: site_sinais.py -- sinais passivos do site (infraestrutura
pronta, não ligada a nenhuma página ainda -- falta mecanismo de
consentimento). Sem consentimento explícito, nada é validado nem gravado."""
import unittest
from unittest.mock import MagicMock, patch
from flask import Flask
import site_sinais as s


class ValidarSinalSite(unittest.TestCase):
    def body(self, **kw):
        return {**dict(tipo='produto_visitado', consentimento=True), **kw}

    def test_sinal_minimo_valido(self):
        dados = s.validar_sinal_site(self.body())
        self.assertEqual(dados['tipo'], 'produto_visitado')

    def test_sem_consentimento_e_rejeitado(self):
        for valor in (False, None, 'sim', 1):
            with self.assertRaises(ValueError):
                s.validar_sinal_site(self.body(consentimento=valor))

    def test_tipo_desconhecido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(tipo='rastrear_tudo'))

    def test_produto_fora_do_enum_e_rejeitado(self):
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(produto='cerveja'))

    def test_produtos_validos_sao_aceitos(self):
        for produto in s.PRODUTOS:
            dados = s.validar_sinal_site(self.body(produto=produto))
            self.assertEqual(dados['produto'], produto)

    def test_origem_e_cta_com_caracteres_invalidos_sao_rejeitados(self):
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(origem='<script>'))
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(cta='ó tem acento'))

    def test_visitante_anonimo_mal_formado_e_rejeitado(self):
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(visitante_anonimo='curto'))
        with self.assertRaises(ValueError):
            s.validar_sinal_site(self.body(visitante_anonimo='tem@caractere'))

    def test_visitante_anonimo_valido_e_aceito(self):
        token = 'a' * 32
        dados = s.validar_sinal_site(self.body(visitante_anonimo=token))
        self.assertEqual(dados['anonimo'], token)

    def test_nunca_aceita_email_telefone_ou_nome(self):
        """Não há campo para PII no contrato -- só o que está em TIPOS_SINAL/
        PRODUTOS/origem/cta/visitante_anonimo é lido; qualquer outro campo é
        simplesmente ignorado (nunca persistido)."""
        dados = s.validar_sinal_site(self.body(email='a@b.com', nome='Fulano', telefone='123'))
        self.assertNotIn('email', dados)
        self.assertNotIn('nome', dados)
        self.assertNotIn('telefone', dados)


class RegistrarSinalSite(unittest.TestCase):
    def test_produto_visitado_e_interesse_observado(self):
        with patch.object(s, 'emitir') as emitir:
            s.registrar_sinal_site(MagicMock(), {'tipo': 'produto_visitado', 'produto': 'guarana', 'consentimento': True})
        emitir.assert_called_once()
        kwargs = emitir.call_args.kwargs
        self.assertEqual(kwargs['natureza'], 'interesse_observado')
        self.assertEqual(kwargs['origem'], 'site')
        self.assertEqual(kwargs['tipo_evento'], 'produto_visitado')
        self.assertEqual(kwargs['payload'], {'produto': 'guarana'})

    def test_retorno_visitante_e_fato(self):
        with patch.object(s, 'emitir') as emitir:
            s.registrar_sinal_site(MagicMock(), {'tipo': 'retorno_visitante', 'consentimento': True,
                                                   'visitante_anonimo': 'a'*32})
        self.assertEqual(emitir.call_args.kwargs['natureza'], 'fato')
        self.assertEqual(emitir.call_args.kwargs['discriminador'], 'a'*32)

    def test_payload_nunca_carrega_visitante_anonimo(self):
        """discriminador serve só para a chave de idempotência (mi_decisao.
        chave_atividade não é usado aqui, mas o mesmo princípio de nunca
        vazar o token pro payload se aplica)."""
        with patch.object(s, 'emitir') as emitir:
            s.registrar_sinal_site(MagicMock(), {'tipo': 'pagina_visitada', 'consentimento': True,
                                                   'visitante_anonimo': 'a'*32})
        self.assertNotIn('visitante_anonimo', emitir.call_args.kwargs['payload'])

    def test_sem_consentimento_nao_chama_emitir(self):
        with patch.object(s, 'emitir') as emitir:
            with self.assertRaises(ValueError):
                s.registrar_sinal_site(MagicMock(), {'tipo': 'pagina_visitada'})
        emitir.assert_not_called()


class RotaSiteSinal(unittest.TestCase):
    def _app(self):
        app = Flask(__name__)
        s.registrar_rotas_site_sinais(app, lambda: MagicMock())
        return app.test_client()

    def test_sinal_valido_retorna_202(self):
        client = self._app()
        with patch.object(s, 'emitir') as emitir:
            resposta = client.post('/api/site/sinal', json={'tipo': 'produto_visitado', 'produto': 'acai',
                                                              'consentimento': True})
        self.assertEqual(resposta.status_code, 202)
        emitir.assert_called_once()

    def test_sem_consentimento_retorna_400_sem_gravar(self):
        client = self._app()
        with patch.object(s, 'emitir') as emitir:
            resposta = client.post('/api/site/sinal', json={'tipo': 'produto_visitado'})
        self.assertEqual(resposta.status_code, 400)
        emitir.assert_not_called()

    def test_corpo_vazio_retorna_400(self):
        client = self._app()
        resposta = client.post('/api/site/sinal', json={})
        self.assertEqual(resposta.status_code, 400)


class SemEfeitosExternos(unittest.TestCase):
    def test_modulo_nao_importa_nenhum_transporte(self):
        import ast
        import inspect
        arvore = ast.parse(inspect.getsource(s))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name.split('.')[0] for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split('.')[0])
        for proibido in ('requests', 'smtplib', 'socket', 'gmail_legado', 'whatsapp_meta',
                          'whatsapp_omnichannel', 'openai'):
            self.assertNotIn(proibido, modulos)


if __name__ == '__main__':
    unittest.main()
