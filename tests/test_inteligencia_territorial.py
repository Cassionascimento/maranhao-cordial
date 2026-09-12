import unittest
from unittest.mock import MagicMock,patch
from inteligencia_territorial import agregar,localizacao,carregar


def rel(ident,city='São Paulo',uf='SP',**kw):
    return dict(id=ident,nome='Relação '+ident,cidade=city,estado=uf,cargo='bartender',**kw)


class Territorial(unittest.TestCase):
    def group(self,r,city):return next(t for t in r['niveis']['cidade'] if t['territorio']==city)

    def test_localizacao_literal_sem_inferencia(self):
        self.assertEqual(localizacao({'cidade':'Maragogi - AL'})['uf'],'AL')
        self.assertEqual(localizacao({'cidade':'São Paulo/SP'})['cidade'],'São Paulo')
        self.assertIsNone(localizacao({'cidade':'São Paulo'})['uf'])
        self.assertIsNone(localizacao({'cidade':'SP'})['cidade'])
        self.assertTrue(localizacao({'cidade':'Salvador - BA','estado':'SP'})['conflito'])

    def test_desconhecidos_nao_viram_recomendacao(self):
        r=agregar({'leads_crm':[rel('a',None,None)]})
        self.assertEqual(r['cobertura']['relacoes_sem_cidade_uf'],1)
        self.assertTrue(all(d['classificacao']=='dados insuficientes' for d in r['decisoes'].values()))

    def test_vinte_dez_supera_cem_cinco(self):
        rows=[rel('a'+str(i),'Campinas',ultimo_contato_em='2026-01-01',ultima_resposta_em='2026-01-02' if i<10 else None) for i in range(20)]
        rows += [rel('b'+str(i),'São Paulo',ultimo_contato_em='2026-01-01',ultima_resposta_em='2026-01-02' if i<5 else None) for i in range(100)]
        r=agregar({'prospectos_fase57':rows})
        self.assertEqual(r['decisoes']['midia']['territorio'],'Campinas / SP')
        self.assertEqual(self.group(r,'Campinas / SP')['indicadores']['taxa_resposta'],.5)

    def test_mesmo_email_vinculo_e_acentos_nao_inflam_relacoes(self):
        r=agregar({'leads_crm':[rel('a',email='pessoa@real.com')],
                   'profissionais_rede':[rel('b','Sao Paulo',email='PESSOA@real.com',lead_id='a')]})
        self.assertEqual(r['cobertura']['relacoes_unicas'],1)
        self.assertEqual(self.group(r,'Sao Paulo / SP')['fatos']['relacoes'],1)

    def test_conflito_geografico_nao_escolhe_local(self):
        r=agregar({'leads_crm':[rel('a',email='p@real.com')],
                   'profissionais_rede':[rel('b','Salvador','BA',email='p@real.com')]})
        self.assertEqual(r['cobertura']['relacoes_sem_cidade_uf'],1)
        self.assertIsNone(r['decisoes']['prospeccao']['territorio'])

    def test_nao_conta_teste_interno_arquivado(self):
        r=agregar({'leads_crm':[rel('a',cadastro_teste=True),rel('b',contato_interno=True),rel('c',arquivado=True)]})
        self.assertEqual(r['cobertura']['relacoes_unicas'],0)
        self.assertEqual(r['cobertura']['registros_excluidos'],3)

    def test_entrada_espontanea_e_automatica_nao_inflam_taxa(self):
        rows=[rel('a',email='p@real.com')]
        interactions=[dict(id='i',lead_id='a',tipo_interacao='email',classificacao='atendimento',criado_em='2026-01-02')]
        r=agregar({'leads_crm':rows,'interacoes_omnichannel':interactions})
        self.assertIsNone(self.group(r,'São Paulo / SP')['indicadores']['taxa_resposta'])
        interactions += [dict(id='o',lead_id='a',tipo_interacao='saida_ia',criado_em='2026-01-03'),dict(id='b',lead_id='a',tipo_interacao='email',classificacao='comunicacao_automatica',criado_em='2026-01-04')]
        r=agregar({'leads_crm':rows,'interacoes_omnichannel':interactions})
        self.assertEqual(self.group(r,'São Paulo / SP')['indicadores']['taxa_resposta'],0)

    def test_pagamento_nao_inventa_circulacao_e_teste_nao_converte(self):
        data={'leads_crm':[rel('a',email='p@real.com')],'pedidos':[dict(id='p',cliente_email='p@real.com',status='teste')]}
        self.assertEqual(self.group(agregar(data),'São Paulo / SP')['fatos']['relacoes_com_conversao'],0)
        data['pedidos'][0]['status']='pago'
        f=self.group(agregar(data),'São Paulo / SP')['fatos']
        self.assertEqual(f['relacoes_com_conversao'],1)
        self.assertEqual(f['circulacoes_registradas'],0)

    def test_custo_ausente_desconhecido_e_cac_nao_e_midia(self):
        r=agregar({'leads_crm':[rel('a',cac_centavos=10000)]})
        self.assertIsNone(self.group(r,'São Paulo / SP')['indicadores']['custo_por_conversao_midia_centavos'])

    def test_registros_pareados_sem_somar_unidades_distintas_ou_planos(self):
        common=dict(cidade='São Paulo',uf='SP',status='realizada',origem='direcao',responsavel='direcao')
        records=[dict(common,id='a',tipo_registro='circulacao',quantidade=2,unidade='garrafas'),
            dict(common,id='b',tipo_registro='circulacao',quantidade=1,unidade='litros'),
            dict(common,id='c',tipo_registro='circulacao',quantidade=500,unidade='garrafas',status='planejada'),
            dict(common,id='d',tipo_registro='midia',metricas={'custo_centavos':10000,'conversoes':2}),
            dict(common,id='e',tipo_registro='midia',metricas={'custo_centavos':90000})]
        b=self.group(agregar({'territorio_registros':records}),'São Paulo / SP')
        self.assertEqual(b['circulacao'],{'garrafas':2,'litros':1})
        self.assertEqual(b['indicadores']['custo_por_conversao_midia_centavos'],5000)

    def test_regiao_e_agrupamento_da_uf_e_bairro_desconhecido(self):
        r=agregar({'leads_crm':[rel('a')]})
        self.assertEqual(r['niveis']['regiao'][0]['territorio'],'Sudeste')
        self.assertFalse(r['niveis']['bairro'][0]['localizacao_completa'])

    def test_uf_default_fase56_nao_e_fato(self):
        r=agregar({'prospectos_fabrica_fase56':[rel('a')]})
        self.assertFalse(r['niveis']['uf'][0]['localizacao_completa'])

    def test_relacao_aditiva_conta_e_referencia_nao_duplica(self):
        data={'leads_crm':[rel('a')],'territorio_registros':[dict(id='t',tipo_registro='relacao',contato_id='a',cidade='São Paulo',uf='SP',estabelecimento='Bar') ]}
        self.assertEqual(agregar(data)['cobertura']['relacoes_unicas'],1)

    def test_hash_estavel_e_alteracao_rastreavel(self):
        data={'leads_crm':[rel('a')]}
        self.assertEqual(agregar(data)['dados_hash'],agregar(data)['dados_hash'])
        first=agregar(data)['dados_hash'];data['leads_crm'].append(rel('b'))
        self.assertNotEqual(first,agregar(data)['dados_hash'])

    def test_snapshot_digital_global_nao_inventa_audiencia_territorial(self):
        r=agregar({'leads_crm':[rel('a')], 'snapshot_ga4':[dict(id=1,payload_json='{"usuarios_ativos":"200","sessoes":"350"}')]})
        self.assertEqual(r['presenca_digital']['snapshot_existente']['metricas_globais']['usuarios_ativos'],200)
        self.assertNotIn('usuarios_ativos',self.group(r,'São Paulo / SP')['fatos'])

    def test_potencial_evento_nao_inventa_oportunidade_identificada(self):
        r=agregar({'leads_crm':[rel('a',potencial_eventos=True)]})
        b=self.group(r,'São Paulo / SP')
        self.assertEqual(b['fatos']['relacoes_com_eventos'],0)
        self.assertEqual(b['fatos']['sinais_potencial_eventos'],1)
        self.assertEqual(r['decisoes']['eventos']['classificacao'],'dados insuficientes')
        self.assertTrue(any('não comprova evento' in s for s in b['sinais']))

    def test_circulacao_e_custo_sinteticos_nao_entram_nos_fatos(self):
        common=dict(cidade='São Paulo',uf='SP',origem='homologacao protegida',status='realizado')
        r=agregar({'territorio_registros':[
            dict(common,id='a',tipo_registro='circulacao',quantidade=50,unidade='garrafas'),
            dict(common,id='b',tipo_registro='midia',metricas={'custo_centavos':100,'conversoes':2})]})
        self.assertEqual(r['niveis']['cidade'],[])
        self.assertEqual(r['cobertura']['registros_excluidos'],2)

    def test_dados_financeiros_e_fisicos_ausentes_permanecem_desconhecidos(self):
        r=agregar({'leads_crm':[rel('a',recebeu_amostra=True,compra_confirmada=True)]})
        b=self.group(r,'São Paulo / SP')
        self.assertEqual(b['fatos']['relacoes_com_amostra_registrada'],1)
        self.assertEqual(b['fatos']['relacoes_com_conversao'],1)
        self.assertEqual(b['circulacao'],{})
        self.assertEqual(b['metricas'],{})
        self.assertIsNone(b['indicadores']['custo_por_conversao_midia_centavos'])


def mi_evento(**kw):
    return {**dict(id=1,tipo_evento='scan',canal='qr',sku=None,ocorrido_em=None,
                   cidade=None,uf=None,bairro=None),**kw}


class MiEventosTerritorio(unittest.TestCase):
    def group(self,r,city):return next(t for t in r['niveis']['cidade'] if t['territorio']==city)

    def test_evento_com_localizacao_contribui_no_territorio_correto(self):
        r=agregar({'mi_eventos':[mi_evento(cidade='Salvador',uf='BA')]})
        b=self.group(r,'Salvador / BA')
        self.assertEqual(b['fatos_mi']['scan'],1)
        self.assertTrue(b['localizacao_completa'])

    def test_evento_sem_localizacao_fica_desconhecido_sem_inventar(self):
        r=agregar({'mi_eventos':[mi_evento()]})
        b=next(x for x in r['niveis']['cidade'] if not x['localizacao_completa'])
        self.assertEqual(b['territorio'],'Localização desconhecida')
        self.assertEqual(b['fatos_mi']['scan'],1)

    def test_mi_eventos_nao_altera_relacoes_ou_identidade_crm(self):
        r=agregar({'leads_crm':[rel('a','Salvador','BA',email='a@real.com')],
                   'mi_eventos':[mi_evento(cidade='Salvador',uf='BA',tipo_evento='venda')]})
        self.assertEqual(r['cobertura']['relacoes_unicas'],1)
        b=self.group(r,'Salvador / BA')
        self.assertEqual(b['fatos']['relacoes'],1)
        self.assertEqual(b['fatos_mi']['venda'],1)

    def test_nao_inventa_equivalencia_com_contadores_antigos(self):
        r=agregar({'mi_eventos':[mi_evento(cidade='Salvador',uf='BA',tipo_evento='venda'),
                                  mi_evento(cidade='Salvador',uf='BA',tipo_evento='ativacao')]})
        b=self.group(r,'Salvador / BA')
        self.assertEqual(b['fatos']['eventos_registrados'],0)
        self.assertEqual(b['fatos']['relacoes_com_conversao'],0)
        self.assertEqual(b['circulacao'],{})
        self.assertEqual(b['metricas'],{})


class CarregarComMiEventos(unittest.TestCase):
    def test_le_mi_eventos_no_mesmo_cursor_e_aplica_limite_5000(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[]
        linhas=[mi_evento(id=i) for i in range(5001)]
        with patch('mi_eventos.consumo_territorial',return_value=linhas) as mocked:
            report=carregar(lambda:conn)
        mocked.assert_called_once_with(cur)
        self.assertIn('mi_eventos',report['cobertura']['fontes_limitadas'])
        self.assertEqual(cur.execute.call_count,15)  # 13 fontes + statement_timeout + snapshot_ga4, sem regressão

    def test_sem_mi_eventos_nao_marca_fonte_limitada(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[]
        with patch('mi_eventos.consumo_territorial',return_value=[]):
            report=carregar(lambda:conn)
        self.assertNotIn('mi_eventos',report['cobertura']['fontes_limitadas'])


if __name__=='__main__':unittest.main()
