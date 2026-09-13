"""ETAPA 5.4: formulários reais do site (/api/degustacao,
/api/profissional/cadastro) -> mi_sinais. Funções extraídas de main.py via
AST (mesmo padrão de test_crm_pedidos_sinais_mi.py), sem importar main.py
inteiro. emitir() é chamado via import local, por isso os testes
interceptam mi_sinais.emitir diretamente."""
import re
import unittest
import uuid
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify, request
import test_email_p0 as f


class Degustacao(unittest.TestCase):
    def _app(self, conn):
        ns = dict(request=request, jsonify=jsonify, uuid=uuid, get_db_connection=lambda: conn)
        f.carregar_funcoes('main.py', ['cadastrar_degustacao'], ns)
        app = Flask('site-test')
        app.add_url_rule('/api/degustacao', view_func=ns['cadastrar_degustacao'], methods=['POST'])
        return app.test_client()

    def _conn(self):
        return MagicMock()

    def _payload(self, **kw):
        return {**dict(empresa='Bar do Zé', segmento='bar', cidade='São Luís/MA', responsavel='Zé',
                       whatsapp='98999999999', email='ze@bar.com.br'), **kw}

    def test_solicitacao_valida_emite_fato_de_interesse_em_degustacao(self):
        conn = self._conn()
        client = self._app(conn)
        with patch('uuid.uuid4', return_value=uuid.UUID('00000000-0000-0000-0000-000000000001')), \
             patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/degustacao', json=self._payload())
        self.assertEqual(resposta.status_code, 201)
        emitir.assert_called_once()
        kwargs = emitir.call_args.kwargs
        self.assertEqual(kwargs['natureza'], 'fato')
        self.assertEqual(kwargs['origem'], 'site')
        self.assertEqual(kwargs['tipo_evento'], 'interesse_degustacao')
        self.assertEqual(kwargs['origem_id'], '00000000-0000-0000-0000-000000000001')
        self.assertEqual(kwargs['canal'], 'site')

    def test_payload_do_sinal_nunca_carrega_pii(self):
        conn = self._conn()
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.post('/api/degustacao', json=self._payload())
        kwargs = emitir.call_args.kwargs
        texto = str(kwargs)
        for pii in ('Zé', 'ze@bar.com.br', '98999999999'):
            self.assertNotIn(pii, texto)

    def test_campos_obrigatorios_ausentes_nao_emite_nada(self):
        conn = self._conn()
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/degustacao', json={'empresa': 'Bar do Zé'})
        self.assertEqual(resposta.status_code, 400)
        emitir.assert_not_called()


class ProfissionalCadastro(unittest.TestCase):
    def _app(self, conn, resposta_rede=None):
        ns = dict(request=request, jsonify=jsonify, uuid=uuid, re=re, get_db_connection=lambda: conn,
                  parceiro_cadastrar_profissional=lambda dados: resposta_rede or (jsonify(profissional_id='p1'), 201))
        f.carregar_funcoes('main.py', ['cadastrar_empresa'], ns)
        app = Flask('site-test')
        app.add_url_rule('/api/profissional/cadastro', view_func=ns['cadastrar_empresa'], methods=['POST'])
        return app.test_client()

    def _payload(self, **kw):
        return {**dict(segmento='distribuidor', responsavel='Maria', whatsapp='98988888888',
                       email='maria@empresa.com.br', cidade='São Luís/MA', interesse='revenda',
                       consentimento=True), **kw}

    def test_cadastro_valido_emite_fato_com_territorio(self):
        conn = MagicMock()
        client = self._app(conn)
        with patch('uuid.uuid4', return_value=uuid.UUID('00000000-0000-0000-0000-000000000002')), \
             patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/profissional/cadastro', json=self._payload())
        self.assertEqual(resposta.status_code, 201)
        kwargs = emitir.call_args.kwargs
        self.assertEqual(kwargs['natureza'], 'fato')
        self.assertEqual(kwargs['tipo_evento'], 'interesse_profissional_b2b')
        self.assertEqual(kwargs['territorio_uf'], 'MA')
        self.assertEqual(kwargs['territorio_cidade'], 'São Luís')

    def test_cidade_sem_uf_reconhecivel_nao_forca_territorio(self):
        conn = MagicMock()
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.post('/api/profissional/cadastro', json=self._payload(cidade='São Luís'))
        self.assertIsNone(emitir.call_args.kwargs['territorio_uf'])

    def test_payload_nunca_carrega_pii_nem_texto_livre_do_usuario(self):
        conn = MagicMock()
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            client.post('/api/profissional/cadastro', json=self._payload(interesse='quero muita revenda urgente'))
        kwargs = emitir.call_args.kwargs
        texto = str(kwargs)
        for sensivel in ('Maria', 'maria@empresa.com.br', '98988888888', 'quero muita revenda urgente'):
            self.assertNotIn(sensivel, texto)

    def test_sem_consentimento_nao_emite_nada(self):
        conn = MagicMock()
        client = self._app(conn)
        with patch('mi_sinais.emitir') as emitir:
            resposta = client.post('/api/profissional/cadastro', json=self._payload(consentimento=False))
        self.assertEqual(resposta.status_code, 400)
        emitir.assert_not_called()

    def test_falha_real_do_registro_de_sinal_nao_impede_o_cadastro(self):
        """emitir() de verdade: MagicMock nao reconhece o SQL, mas o cadastro
        (já commitado antes) nunca deveria falhar por causa disso."""
        conn = MagicMock()
        client = self._app(conn)
        resposta = client.post('/api/profissional/cadastro', json=self._payload())
        self.assertEqual(resposta.status_code, 201)


if __name__ == '__main__':
    unittest.main()
