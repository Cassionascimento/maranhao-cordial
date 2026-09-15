"""Banco de fatos confirmados do Conselho -- mi_conselho_fatos.py. Mesma
disciplina de mi_conselho.py/mi_sinais.py: idempotência por chave,
append-only (uma correção é sempre um novo registrar_fato, nunca um
UPDATE), e aqui especificamente: validade temporal nunca deixa um dado
velho ser lido como se fosse a leitura de hoje."""
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import MagicMock

import mi_conselho_fatos as f


class ValidarFato(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), topico='preco_extrato_gengibre', valor='120.50',
                       origem_tipo='FORNECEDOR'), **kw}

    def test_fato_minimo_valido(self):
        _, dados = f.validar_fato(self.body())
        self.assertEqual(dados['topico'], 'preco_extrato_gengibre')
        self.assertEqual(dados['origem_tipo'], 'FORNECEDOR')

    def test_topico_invalido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            f.validar_fato(self.body(topico='Preço com espaço'))

    def test_origem_tipo_fora_do_vocabulario_e_rejeitada(self):
        with self.assertRaises(ValueError):
            f.validar_fato(self.body(origem_tipo='CHUTE'))

    def test_valor_vazio_e_rejeitado(self):
        with self.assertRaises(ValueError):
            f.validar_fato(self.body(valor='   '))

    def test_confianca_fora_do_vocabulario_e_rejeitada(self):
        with self.assertRaises(ValueError):
            f.validar_fato(self.body(confianca='altissima'))

    def test_agente_registrante_invalido_e_rejeitado(self):
        with self.assertRaises(ValueError):
            f.validar_fato(self.body(agente_registrante='Fulano de Tal'))

    def test_sem_valido_ate_aplica_ttl_padrao_da_categoria(self):
        _, dados = f.validar_fato(self.body(topico='preco_extrato_gengibre'))
        self.assertEqual(dados['valido_ate'] - dados['obtido_em'], timedelta(days=3))

    def test_topico_sem_categoria_conhecida_usa_ttl_fallback(self):
        _, dados = f.validar_fato(self.body(topico='observacao_geral'))
        self.assertEqual(dados['valido_ate'] - dados['obtido_em'], timedelta(days=30))

    def test_valido_ate_explicito_e_respeitado(self):
        obtido = datetime.now(timezone.utc)
        limite = obtido + timedelta(hours=2)
        _, dados = f.validar_fato(self.body(obtido_em=obtido.isoformat(), valido_ate=limite.isoformat()))
        self.assertEqual(dados['valido_ate'], limite)


class StatusFato(unittest.TestCase):
    def test_fato_atual_dentro_da_validade_e_com_boa_fonte(self):
        agora = datetime.now(timezone.utc)
        fato = {'origem_tipo': 'FONTE_INTERNA', 'confianca': 'alta', 'valido_ate': agora + timedelta(days=1)}
        self.assertEqual(f.status_fato(fato, agora), 'ATUAL')

    def test_fato_com_valido_ate_no_passado_fica_desatualizado(self):
        agora = datetime.now(timezone.utc)
        fato = {'origem_tipo': 'FONTE_INTERNA', 'confianca': 'alta', 'valido_ate': agora - timedelta(days=1)}
        self.assertEqual(f.status_fato(fato, agora), 'DESATUALIZADO')

    def test_estimativa_ainda_dentro_da_validade_fica_incerta_nunca_atual(self):
        agora = datetime.now(timezone.utc)
        fato = {'origem_tipo': 'ESTIMATIVA', 'confianca': 'media', 'valido_ate': agora + timedelta(days=10)}
        self.assertEqual(f.status_fato(fato, agora), 'INCERTO')

    def test_confianca_baixa_fica_incerta_mesmo_com_fonte_interna(self):
        agora = datetime.now(timezone.utc)
        fato = {'origem_tipo': 'FONTE_INTERNA', 'confianca': 'baixa', 'valido_ate': agora + timedelta(days=10)}
        self.assertEqual(f.status_fato(fato, agora), 'INCERTO')

    def test_desatualizado_tem_prioridade_sobre_incerto(self):
        agora = datetime.now(timezone.utc)
        fato = {'origem_tipo': 'ESTIMATIVA', 'confianca': 'baixa', 'valido_ate': agora - timedelta(days=1)}
        self.assertEqual(f.status_fato(fato, agora), 'DESATUALIZADO')

    def test_sem_valido_ate_nunca_expira_mas_ainda_pode_ficar_incerto(self):
        agora = datetime.now(timezone.utc)
        self.assertEqual(f.status_fato({'origem_tipo': 'FONTE_INTERNA', 'confianca': 'alta', 'valido_ate': None}, agora), 'ATUAL')
        self.assertEqual(f.status_fato({'origem_tipo': 'ESTIMATIVA', 'confianca': None, 'valido_ate': None}, agora), 'INCERTO')


class RegistrarFato(unittest.TestCase):
    def body(self, **kw):
        return {**dict(chave=str(uuid4()), topico='moq_fornecedor_x', valor='500', unidade='kg',
                       origem_tipo='FORNECEDOR'), **kw}

    def test_criacao_grava_uma_unica_vez(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{'id': 'novo'}, {'id': 'novo'}]
        resposta, status = f.registrar_fato(lambda: conn, body)
        self.assertTrue(resposta['success'])
        self.assertTrue(resposta['criado'])
        self.assertEqual(status, 201)

    def test_chave_repetida_nao_cria_de_novo(self):
        body = self.body()
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 'existente'}]
        resposta, status = f.registrar_fato(lambda: conn, body)
        self.assertFalse(resposta['criado'])
        self.assertEqual(status, 200)


class FatoAtualEHistorico(unittest.TestCase):
    def _linha(self, obtido_em, **kw):
        base = dict(topico='preco_extrato_gengibre', valor='100', unidade='kg', origem_tipo='FORNECEDOR',
                    fonte_detalhe=None, confianca='alta', agente_registrante='standard', registro_id=None,
                    obtido_em=obtido_em, valido_ate=obtido_em + timedelta(days=3))
        base.update(kw)
        return base

    def test_fato_atual_e_a_leitura_mais_recente(self):
        agora = datetime.now(timezone.utc)
        cur = MagicMock()
        cur.fetchone.return_value = self._linha(agora, valor='130')
        resultado = f.fato_atual(cur, 'preco_extrato_gengibre', agora)
        self.assertEqual(resultado['valor'], '130')
        self.assertTrue(resultado['fato_mais_recente_do_topico'])
        self.assertEqual(resultado['status'], 'ATUAL')

    def test_ausencia_de_fato_devolve_none_nunca_suposicao(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        self.assertIsNone(f.fato_atual(cur, 'topico_nunca_confirmado'))

    def test_historico_marca_status_por_linha_sem_promover_antiga_a_atual(self):
        agora = datetime.now(timezone.utc)
        recente = self._linha(agora, valor='130')
        antiga = self._linha(agora - timedelta(days=10), valor='100', valido_ate=agora - timedelta(days=7))
        cur = MagicMock()
        cur.fetchall.return_value = [recente, antiga]
        historico = f.historico_fato(cur, 'preco_extrato_gengibre', agora=agora)
        self.assertEqual(historico[0]['status'], 'ATUAL')
        self.assertTrue(historico[0]['fato_mais_recente_do_topico'])
        self.assertEqual(historico[1]['status'], 'DESATUALIZADO')
        self.assertFalse(historico[1]['fato_mais_recente_do_topico'])


if __name__ == '__main__':
    unittest.main()
