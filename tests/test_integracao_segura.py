from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import whatsapp_omnichannel as w
import autonomia_supervisionada as a
import gmail_legado

class Integracao(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.config={k:'sintetico' for k in ('WHATSAPP_ACCESS_TOKEN','WHATSAPP_PHONE_NUMBER_ID',
            'WHATSAPP_BUSINESS_ACCOUNT_ID','META_APP_SECRET','META_WEBHOOK_VERIFY_TOKEN')}
        self.ev=dict(empresa_id='empresa-a',conector_id='wa-a',phone_number_id='sintetico',waba_id='sintetico',
            verificado_em=(self.now-timedelta(minutes=1)).isoformat(),valido_ate=(self.now+timedelta(minutes=5)).isoformat())
        for k in ('numero_online','token_valido','app_vinculado','webhook_validado','messages_assinado',
                  'messaging_autorizado','management_autorizado'):self.ev[k]=True
    def estado(self,ev=None):
        return w.status_conector(self.config,evidencia=self.ev if ev is None else ev,
            empresa_id='empresa-a',conector_id='wa-a',agora=self.now)
    def test_prontidao_nunca_libera_transporte(self):
        self.assertEqual(w.avaliar_prontidao({})['estado'],'disconnected')
        self.assertEqual(w.avaliar_prontidao(self.config)['estado'],'configurado')
        self.assertEqual(self.estado()['prontidao']['estado'],'conectado')
        self.ev['homologacao']=dict(real=True,entrada_id='e',interacao_id='i',lead_id='l',proposta_id='p',aprovacao_id='a',auditoria_id='u')
        self.assertEqual(self.estado()['prontidao']['estado'],'homologado')
        self.assertFalse(self.estado()['envio_liberado'])
    def test_outro_tenant_ou_canal_nao_herda_evidencia(self):
        for key in ('empresa_id','conector_id','phone_number_id','waba_id'):
            ev=dict(self.ev,**{key:'outro'})
            self.assertEqual(self.estado(ev)['prontidao']['estado'],'configurado')
    def test_evidencia_expirada_futura_invalida(self):
        for ev in (dict(self.ev,valido_ate=self.now.isoformat()),dict(self.ev,verificado_em=(self.now+timedelta(hours=1)).isoformat()),dict(self.ev,valido_ate='invalida')):
            self.assertEqual(self.estado(ev)['prontidao']['estado'],'configurado')
    def test_simulacao_nao_e_homologacao_real(self):
        self.ev['homologacao']={'real':False,'entrada_id':'sintetica'}
        self.assertEqual(self.estado()['prontidao']['estado'],'conectado')
    def test_meta_pendente_ou_config_ausente_fecha(self):
        self.ev['messaging_autorizado']=False
        self.assertEqual(self.estado()['prontidao']['estado'],'configurado')
        self.config.pop('WHATSAPP_ACCESS_TOKEN')
        self.assertEqual(self.estado()['prontidao']['estado'],'disconnected')
    def test_sem_segredos_na_resposta(self):
        self.assertNotIn('sintetico',str(self.estado()))
    def test_gmail_legado_fechado(self):
        with self.assertRaises(PermissionError):gmail_legado.gmail_enviar_email('a@example.com','x','y')
    def test_env_flag_sozinha_nao_instala_transportes(self):
        db=Mock()
        with patch.dict('os.environ',{'AUTONOMIA_SUPERVISIONADA_EXECUTAR':'true'}):
            self.assertEqual(a.executar(db,'id',{})['motivo'],'integracao_sem_transporte')
            self.assertEqual(a.briefing({})['motivo'],'integracao_sem_transporte')
        db.assert_not_called()
    def test_migrations_locais_nao_copiadas(self):
        self.assertFalse(Path('migrations/007_tiktok_shop.sql').exists())
        self.assertFalse(Path('migrations/008_autonomia_supervisionada.sql').exists())
        self.assertTrue(Path('migrations/012_mi_eventos_unidade.sql').exists())

if __name__=='__main__':unittest.main()
