"""Origem heterogênea e deduplicação, sem PostgreSQL real ou transporte."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import Mock, patch

import acoes_comerciais as a
import fase56_fabrica_piloto as f56
import fase57_prospeccao_universal as f57
from test_acoes_comerciais import Banco, DADOS

ID56 = '00000000-0000-0000-0000-000000000056'
ID57 = DADOS['origem_id']
ENTRADA = '00000000-0000-0000-0000-000000000099'


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.origens = {'prospecto_fase56': {ID56}, 'prospecto_fase57': {ID57}}
        self.propostas = {}
        self.eventos = []
        self.prospectos = {ID57: dict(email=DADOS['destinatario'], fonte_url=DADOS['origem'],
            status='qualificado', score=90, evidencia='Fonte pública', campanha_status='ativa',
            permitir_primeiro_contato=True)}
        self.supressoes, self.historico, self.reservas = set(), set(), set()

    def __call__(self):
        return Connection(self)


class Connection:
    def __init__(self, db): self.db = db
    def __enter__(self): self.db.lock.acquire(); return self
    def __exit__(self, *args): self.db.lock.release()
    def close(self): pass
    def cursor(self, **kwargs): return Cursor(self.db)


class Cursor:
    def __init__(self, db): self.db = db; self.row = None
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def fetchone(self): return self.row
    def execute(self, sql, args=()):
        self.row = None
        if sql in a.ORIGENS.values():
            tipo = next(t for t, query in a.ORIGENS.items() if query == sql)
            if args[0] in self.db.origens[tipo]: self.row = {'id': args[0]}
        elif sql.startswith('SELECT p.id FROM prospectos_fase57 p'):
            ident, email, fonte, campanhas = args
            p = self.db.prospectos.get(ident)
            if (p and ident in self.db.origens['prospecto_fase57']
                    and p['email'].strip().lower() == email and p['fonte_url'] == fonte
                    and p['status'] == 'qualificado' and p['score'] >= 55 and p['evidencia']
                    and p['campanha_status'] in campanhas and p['permitir_primeiro_contato']
                    and email not in self.db.supressoes | self.db.historico | self.db.reservas):
                self.row = (ident,)
        elif sql.startswith('INSERT INTO acoes_comerciais_propostas'):
            chave, tipo, ident, dados, digest = args
            if chave not in self.db.propostas:
                row = dict(id=str(len(self.db.propostas)+1), status='aguardando_aprovacao',
                           origem_tipo=tipo, origem_id=ident, dados=copy.deepcopy(dados.adapted), digest=digest)
                self.db.propostas[chave] = row
                self.row = {'id': row['id']}
        elif sql.startswith('SELECT id,status,digest'):
            registro = self.db.propostas[args[0]]
            self.row = {k:registro[k] for k in ('id','status','digest','origem_tipo','origem_id')}
        elif sql.startswith('INSERT INTO auditoria_acoes_comerciais'):
            self.db.eventos.append(args)
        else:
            raise AssertionError(sql)


class Origens(TestCase):
    def test_fase56_e_fase57_persistem_referencia_e_digest(self):
        db = Store()
        for tipo, ident, email in (('prospecto_fase56', ID56, 'piloto@empresa.com.br'),
                                   ('prospecto_fase57', ID57, 'vendas@empresa.com.br')):
            original = dict(DADOS, destinatario=email)
            r = a.propor(db, original, tipo, ident)
            self.assertTrue(r['proposta_criada'])
            self.assertFalse(r['enviado'])
            row = db.propostas['primeiro_contato:'+email]
            self.assertEqual((row['origem_tipo'],row['origem_id']), (tipo,ident))
            self.assertEqual((row['dados']['origem_tipo'],row['dados']['origem_id']), (tipo,ident))
            self.assertEqual(row['digest'], a.digest(row['dados']))
            self.assertEqual(original['origem_tipo'], DADOS['origem_tipo'])  # sem mutação do chamador

    def test_id_existente_na_outra_tabela_nao_e_origem_valida(self):
        db = Store()
        with self.assertRaisesRegex(ValueError,'origem_nao_encontrada'):
            a.propor(db,DADOS,'prospecto_fase56',ID57)
        self.assertEqual(db.propostas,{})

    def test_tipo_desconhecido_ou_id_invalido_falha_fechado(self):
        for tipo, ident in (('tabela; DELETE','x'), ('prospecto_fase57','invalido')):
            db=Store()
            with self.assertRaises(ValueError): a.propor(db,DADOS,tipo,ident)
            self.assertEqual(db.propostas,{})

    def test_repeticao_e_concorrencia_entre_fases_nao_duplicam(self):
        db=Store()
        def criar(i):
            return a.propor(db,DADOS,'prospecto_fase56' if i%2 else 'prospecto_fase57',ID56 if i%2 else ID57)
        with ThreadPoolExecutor(max_workers=8) as pool:
            resultados=list(pool.map(criar,range(20)))
        self.assertEqual(sum(r['proposta_criada'] for r in resultados),1)
        self.assertEqual(len(db.propostas),1)
        self.assertEqual(len(db.eventos),1)
        original=copy.deepcopy(db.propostas)
        criar(0)
        self.assertEqual(db.propostas,original)

    def test_resposta_preserva_prospecto_e_interacao_separados(self):
        db=Store()
        r=a.propor(db,dict(DADOS,tipo='resposta',origem_mensagem=ENTRADA),'prospecto_fase56',ID56)
        self.assertEqual(r['acao']['origem_id'],ID56)
        self.assertEqual(db.propostas['resposta:'+DADOS['destinatario']+':'+ENTRADA]['dados']['origem_mensagem'],ENTRADA)
        repetida=a.propor(db,dict(DADOS,tipo='resposta',origem_mensagem=ENTRADA),'prospecto_fase57',ID57)
        self.assertFalse(repetida['proposta_criada'])

    def test_criador_fase56_nao_envia_e_usa_origem_correta(self):
        db=Store()
        conn=Mock()
        cur=Mock(fetchone=Mock(return_value=dict(id=ID56,nome='Fábrica',email='piloto@empresa.com.br')))
        conn.cursor.return_value.__enter__=Mock(return_value=cur)
        conn.cursor.return_value.__exit__=Mock(return_value=False)
        propor_real=a.propor
        with patch.object(f56,'_conn',return_value=conn), patch.object(a,'propor',side_effect=lambda _,d,t,i: propor_real(db,d,t,i)), patch.object(f56,'enviar_email_institucional_fase56') as enviar:
            r=f56.enviar_primeiro_contato_fase56({},ID56)
        enviar.assert_not_called()
        self.assertEqual((r['acao']['origem_tipo'],r['acao']['origem_id']),('prospecto_fase56',ID56))

    def test_criador_fase57_preserva_rota_de_origem(self):
        db=Store()
        item=dict(id=ID57,email=DADOS['destinatario'],empresa='Empresa',objetivo='Parceria',
                  fonte_url=DADOS['origem'],evidencia='Fonte',campanha_id=ID57)
        with patch.object(f57,'_conn',side_effect=lambda _:db()):
            r=f57.propor_mensagem_fase57({},item,'Mensagem','Assunto')
        self.assertEqual((r['acao']['origem_tipo'],r['acao']['origem_id']),('prospecto_fase57',ID57))

    def test_executor_fase57_recebe_id_correto(self):
        db=Banco(); send=Mock(return_value={'success':True,'message_id':'mock'})
        a.executar(db,'1',send)
        send.assert_called_once_with(ID57)

    def test_criador_fase57_exige_origem_e_elegibilidade_atuais(self):
        for bloqueio in ('supressoes', 'historico', 'reservas', 'campanha', 'score', 'origem'):
            with self.subTest(bloqueio=bloqueio):
                db = Store()
                if bloqueio in ('supressoes', 'historico', 'reservas'):
                    getattr(db, bloqueio).add(DADOS['destinatario'])
                elif bloqueio == 'campanha':
                    db.prospectos[ID57]['permitir_primeiro_contato'] = False
                elif bloqueio == 'score':
                    db.prospectos[ID57]['score'] = 54
                else:
                    db.origens['prospecto_fase57'].clear()
                item = dict(id=ID57, email=DADOS['destinatario'], fonte_url=DADOS['origem'])
                with patch.object(f57, '_conn', side_effect=lambda _: db()):
                    resultado = f57.propor_mensagem_fase57({}, item, 'Mensagem', 'Assunto')
                self.assertFalse(resultado['apto_para_contato'])
                self.assertEqual(db.propostas, {})
                self.assertEqual(db.eventos, [])

    def test_mesmo_uuid_em_tabelas_distintas_preserva_tipo(self):
        db=Store();db.origens['prospecto_fase56'].add(ID57)
        p56=a.propor(db,dict(DADOS,destinatario='piloto@empresa.com.br'),'prospecto_fase56',ID57)
        p57=a.propor(db,DADOS,'prospecto_fase57',ID57)
        self.assertEqual(p56['acao']['origem_id'],p57['acao']['origem_id'])
        self.assertNotEqual(p56['acao']['origem_tipo'],p57['acao']['origem_tipo'])

    def test_aprovacao_nao_autoriza_troca_de_origem(self):
        for field, value in (('origem_tipo','prospecto_fase56'),('origem_id',ID56)):
            db=Banco();db.row[field]=value;send=Mock()
            self.assertEqual(a.executar(db,'1',send)['motivo'],'origem_nao_aprovada')
            send.assert_not_called()
            db=Banco();db.row['dados'][field]=value
            self.assertEqual(a.executar(db,'1',send)['motivo'],'conteudo_nao_aprovado')
            send.assert_not_called()

    def test_fase56_nunca_usa_executor_de_primeiro_contato_fase57(self):
        db=Banco()
        db.row.update(origem_tipo='prospecto_fase56',origem_id=ID56)
        db.row['dados'].update(origem_tipo='prospecto_fase56',origem_id=ID56)
        db.row.update(digest=a.digest(db.row['dados']),digest_aprovado=a.digest(db.row['dados']))
        send=Mock()
        self.assertEqual(a.executar(db,'1',send)['motivo'],'executor_da_origem_nao_habilitado')
        send.assert_not_called()


class PropostaSinaisMI(TestCase):
    """ETAPA 4.9: propor() -> mi_sinais (recomendação, não fato confirmado)."""

    def test_proposta_criada_emite_recomendacao_apos_commit(self):
        db = Store()
        with patch('acoes_comerciais.emitir') as emitir:
            r = a.propor(db, dict(DADOS), 'prospecto_fase57', ID57)
        self.assertTrue(r['proposta_criada'])
        emitir.assert_called_once_with(db, natureza='recomendacao', origem='acoes_comerciais',
            tipo_evento='acao_proposta', origem_id=r['acao']['id'], canal='email',
            payload={'tipo': 'primeiro_contato', 'origem_tipo': 'prospecto_fase57'})

    def test_proposta_duplicada_nao_reemite(self):
        db = Store()
        with patch('acoes_comerciais.emitir') as emitir:
            a.propor(db, dict(DADOS), 'prospecto_fase57', ID57)
            a.propor(db, dict(DADOS), 'prospecto_fase57', ID57)
        emitir.assert_called_once()

    def test_origem_invalida_nao_emite_nada(self):
        db = Store()
        with patch('acoes_comerciais.emitir') as emitir:
            with self.assertRaises(ValueError):
                a.propor(db, DADOS, 'prospecto_fase56', ID57)
        emitir.assert_not_called()
