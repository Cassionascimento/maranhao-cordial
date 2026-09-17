"""M8: pipeline real, persistência fake e providers explicitamente simulados."""
import unittest
from unittest.mock import patch
from flask import Flask
import mi_label_studio as label
import mi_social_studio as social
import mi_regulatorio_produto as reg
import mi_artefatos as artifacts
import mi_pirret_criativo as pirret
from mi_image_provider import MockImageProvider
from tests.test_mi_artefatos import _db_vazio, _factory
from tests.test_mi_pirret_criativo import _cliente_mock

class Studios(unittest.TestCase):
    def setUp(self):
        self.db=_db_vazio(); self.factory=_factory(self.db); self.provider=MockImageProvider()
        self.context=patch('mi_brand_context.montar_brand_context_completo',return_value={'versao':1,'referencias_aprovadas':[]})
        self.context.start(); self.addCleanup(self.context.stop)

    def conceito(self):
        result=label.gerar_conceito_rotulo(self.factory,'Conceito de teste','SKU-TEST',quantidade=1,
            provider=self.provider,cliente=_cliente_mock())
        self.assertTrue(result['success'])
        return result['artefatos'][0]['id']

    def test_rotulo_nasce_bloqueado_com_sku_e_contexto(self):
        ident=self.conceito(); row=self.db['artefatos'][ident]
        self.assertEqual(row['status'],'gerado')
        self.assertEqual(row['metadata']['regulatory_status'],'NAO_VALIDADO')
        self.assertEqual(row['metadata']['sku'],'SKU-TEST')
        self.assertEqual(row['metadata']['brand_context']['versao'],1)

    def test_regulatorio_nao_aceita_sku_alheio_ou_sem_aprovacao(self):
        ident=self.conceito()
        with patch.object(label,'dados_regulatorios_atuais',return_value={'versao':1,'campos':{'volume':'declarado'}}):
            self.assertEqual(label.validar_regulatoriamente(self.factory,ident,'OUTRO','humano')['motivo'],'artefato_sku_incompativel')
            self.assertEqual(label.validar_regulatoriamente(self.factory,ident,'SKU-TEST','humano')['motivo'],'aprovacao_criativa_pendente')

    def test_revisao_auditada_nao_autoriza_producao_e_nova_versao_perde_validacao(self):
        ident=self.conceito(); artifacts.aprovar_artefato(self.factory,ident,'humano')
        with patch.object(label,'dados_regulatorios_atuais',return_value={'versao':1,'campos':{'volume':'declarado'}}):
            self.assertTrue(label.validar_regulatoriamente(self.factory,ident,'SKU-TEST','humano')['success'])
        self.assertIn('NÃO AUTORIZA',self.db['artefatos'][ident]['metadata']['production_status'])
        self.assertIn('metadata_atualizada',self.db['auditoria'][-1]['motivo'])
        novo=pirret.refinar_conceito_visual(self.factory,ident,'Nova composição',provider=self.provider)
        self.assertEqual(self.db['artefatos'][novo['id']]['metadata']['regulatory_status'],'NAO_VALIDADO')
        self.assertEqual(novo['version'],2)

    def test_social_exige_aprovacao_e_gera_formatos_sem_publicar(self):
        ident=self.conceito()
        self.assertFalse(social.gerar_campanha_a_partir_de_artefato(self.factory,ident,['feed'],provider=self.provider)['success'])
        artifacts.aprovar_artefato(self.factory,ident,'humano')
        result=social.gerar_campanha_a_partir_de_artefato(self.factory,ident,['feed','story','mockup','feed'],provider=self.provider)
        self.assertEqual(len(result['pecas']),3)
        for p in result['pecas']:
            row=self.db['artefatos'][p['id']]
            self.assertEqual(row['parent_artifact_id'],ident); self.assertEqual(row['status'],'gerado')

    def test_limites_e_provider_vazio(self):
        with self.assertRaises(ValueError):
            label.gerar_conceito_rotulo(self.factory,'teste','SKU',quantidade=100,provider=self.provider,cliente=_cliente_mock())
        self.provider.gerar=lambda *a:[]
        self.assertFalse(label.gerar_conceito_rotulo(self.factory,'teste','SKU',provider=self.provider,cliente=_cliente_mock())['success'])

    def test_rotas_sem_autorizacao_nao_abrem_banco(self):
        app=Flask(__name__)
        def proibido(): raise AssertionError('banco não deveria abrir')
        for mod in (label,social,reg):mod.registrar_rotas(app,proibido,lambda:False)
        client=app.test_client()
        for rule in app.url_map.iter_rules():
            if not rule.rule.startswith('/api/admin/mi/'):continue
            url=rule.rule.replace('<sku>','SKU').replace('<artefato_id>','id').replace('<artefato_base_id>','id')
            for method in rule.methods-{'HEAD','OPTIONS'}:
                self.assertEqual(client.open(url,method=method,json={}).status_code,401)
