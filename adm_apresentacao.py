"""Apresentação executiva — leitura agregada e sem dados pessoais.

Para que serve: permitir mostrar a plataforma a alguém de fora (um
investidor, por exemplo) em menos de um minuto, usando OS MESMOS dados do
sistema — nunca números de demonstração.

Duas garantias, ambas no servidor (esconder botão no navegador não é
proteção):

1. A rota vive sob ``/api/admin/``. Além da checagem explícita de
   ``autorizado()`` aqui, o ``before_request`` de main.py já barra todo
   ``/api/admin/*`` sem chave administrativa válida.

2. O corpo devolvido é montado campo a campo, só com escalares e
   enumerações fechadas. Nome, e-mail, telefone, endereço, identificador
   de contato e texto livre (``inferencia``/``motivo``, que pode citar uma
   empresa) NUNCA entram aqui. Nada de ``SELECT *``.

Este módulo não escreve, não envia, não executa e não cria link público.
Ele apenas lê o que já existe. Onde não há medição, devolve ``None`` — a
interface mostra a etapa real alcançada em vez de inventar um resultado.
"""
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor


# Enumerações fechadas: só estes valores podem sair daqui em campos de
# texto. Qualquer coisa fora da lista vira "outro".
PRIORIDADES = ('urgente', 'alta', 'normal', 'baixa')
ACOES_CONHECIDAS = (
    'pesquisar', 'classificar', 'analisar', 'planejar', 'sugerir_conteudo',
    'enviar_followup', 'avaliar_reengajamento', 'revisar_bloqueio',
    'decidir_proposta', 'priorizar_atendimento', 'informar_diretor',
)
ESTAGIOS_ABERTOS = ('novo', 'qualificacao', 'degustacao', 'proposta', 'negociacao')


def _enum(valor, permitidos):
    return valor if valor in permitidos else 'outro'


def _contagens_comerciais(factory):
    """Agregados puros: nenhuma linha individual sai desta função."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='15s'")

            cur.execute(
                "SELECT estagio, count(*) AS total FROM leads_crm "
                "WHERE NOT cadastro_teste AND NOT arquivado GROUP BY estagio"
            )
            por_estagio = {linha['estagio']: linha['total'] for linha in cur.fetchall()}

            cur.execute(
                "SELECT count(DISTINCT (cidade, estado)) AS total FROM leads_crm "
                "WHERE NOT cadastro_teste AND NOT arquivado AND cidade IS NOT NULL"
            )
            pracas = cur.fetchone()['total']

            cur.execute("SELECT status, count(*) AS total FROM pedidos GROUP BY status")
            pedidos_por_status = {linha['status']: linha['total'] for linha in cur.fetchall()}

            cur.execute(
                "SELECT COALESCE(sum(valor_centavos),0) AS total FROM pedidos WHERE status='pago'"
            )
            receita_confirmada = cur.fetchone()['total']

        abertos = sum(por_estagio.get(e, 0) for e in ESTAGIOS_ABERTOS)
        return {
            'contatos_em_relacionamento': abertos,
            'contatos_por_estagio': {e: por_estagio.get(e, 0) for e in ESTAGIOS_ABERTOS},
            'clientes': por_estagio.get('cliente', 0),
            'pracas_alcancadas': pracas,
            'pedidos_registrados': sum(pedidos_por_status.values()),
            'pedidos_pagos': pedidos_por_status.get('pago', 0),
            'receita_confirmada_centavos': int(receita_confirmada or 0),
        }
    finally:
        conn.close()


def _contagens_propostas(factory):
    """Fila de ações comerciais: o coração do controle humano.

    A tabela pertence a acoes_comerciais.py (migration própria). Se ela
    ainda não existir no ambiente em uso, isso não é erro de apresentação
    — devolve None e a interface diz que a fila não foi lida.
    """
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            cur.execute(
                "SELECT status, count(*) AS total FROM acoes_comerciais_propostas GROUP BY status"
            )
            por_status = {linha['status']: linha['total'] for linha in cur.fetchall()}
    except Exception:
        return None
    finally:
        conn.close()

    return {
        'propostas': sum(por_status.values()),
        'aguardando_aprovacao': por_status.get('aguardando_aprovacao', 0),
        'aprovadas': por_status.get('aprovada', 0) + por_status.get('executando', 0),
        'rejeitadas': por_status.get('rejeitada', 0),
        'executadas': por_status.get('enviada', 0),
        'sem_confirmacao': por_status.get('bloqueada', 0) + por_status.get('incerta', 0),
    }


def _oportunidade_anonima(leitura):
    """Uma oportunidade real, descrita só por campos de enumeração.

    ``inferencia``/``motivo`` ficam de fora de propósito: é texto livre e
    pode citar o nome de uma empresa ou de uma pessoa.
    """
    if not leitura:
        return None
    oportunidades = (leitura.get('comercial') or {}).get('oportunidades') or []
    if not oportunidades:
        return None
    escolhida = min(
        oportunidades,
        key=lambda o: PRIORIDADES.index(o['prioridade']) if o.get('prioridade') in PRIORIDADES else 99,
    )
    return {
        'tipo': _enum(escolhida.get('tipo_decisao'), ('oportunidade_parada',)),
        'prioridade': _enum(escolhida.get('prioridade'), PRIORIDADES),
        'proxima_acao': _enum(escolhida.get('proxima_acao'), ACOES_CONHECIDAS),
        'exige_aprovacao': bool(escolhida.get('exige_aprovacao', True)),
        'total_abertas': len(oportunidades),
    }


def _capacidades(factory):
    """O que está de fato funcionando hoje, canal a canal.

    Reaproveita canais_status.status_todos_os_canais — a mesma leitura que
    o ADM já mostra, sem nenhuma chamada de rede nova.
    """
    try:
        from canais_status import status_todos_os_canais
        canais = status_todos_os_canais(factory)
    except Exception:
        return None
    return [
        {
            'canal': canal['canal'],
            'estado': canal['estado'],
            'leitura': bool(canal['leitura_disponivel']),
            'escrita': bool(canal['escrita_disponivel']),
            'aprovacao_exigida': bool(canal['aprovacao_exigida']),
        }
        for canal in canais
    ]


def _etapa_alcancada(propostas, comercial):
    """Quando ainda não há resultado comprovado, dizer a etapa REAL.

    Nada de "em breve" nem de projeção: a frase descreve o ponto mais
    avançado que os próprios registros sustentam.
    """
    if propostas is None:
        return 'fila_nao_lida'
    if propostas['executadas'] > 0:
        return 'acao_executada'
    if propostas['aprovadas'] > 0:
        return 'acao_aprovada'
    if propostas['aguardando_aprovacao'] > 0:
        return 'acao_aguardando_aprovacao'
    if propostas['propostas'] > 0:
        return 'acao_proposta'
    if comercial and comercial['contatos_em_relacionamento'] > 0:
        return 'relacionamento_em_andamento'
    return 'operacao_preparada'


def montar_apresentacao(factory, agora=None):
    """Cada bloco é isolado: a falha de um não derruba a apresentação
    inteira — vira ``None`` e a interface explica o que não foi lido."""
    agora = agora or datetime.now(timezone.utc)

    try:
        comercial = _contagens_comerciais(factory)
    except Exception:
        comercial = None

    propostas = None
    try:
        propostas = _contagens_propostas(factory)
    except Exception:
        propostas = None

    leitura = None
    try:
        from mi_diretor import leitura_diretor
        leitura = leitura_diretor(factory)
    except Exception:
        leitura = None

    conselho = (leitura or {}).get('conselho') or {}
    resultados = conselho.get('resultados_recentes') or []

    return {
        'gerado_em': agora.isoformat(),
        'negocio': {
            'marca': 'Maranhão Cordial',
            'categoria': 'Cordiais brasileiros sem álcool',
        },
        'situacao': comercial,
        'oportunidade': _oportunidade_anonima(leitura),
        'trabalho_da_tecnologia': None if leitura is None else {
            'em_atividade': bool(leitura.get('ia_trabalhando')),
            'concluidas_recentes': len((leitura.get('hoje') or {}).get('concluido') or []),
            'planejadas_hoje': len((leitura.get('hoje') or {}).get('planejado') or []),
            'aguardando_decisao_humana': len((leitura.get('hoje') or {}).get('precisa_de_mim') or []),
            'especialistas_ativos': int(conselho.get('trabalhando') or 0),
            'divergencias_registradas': len(conselho.get('conflitos') or []),
            'vetos_registrados': len(conselho.get('vetos') or []),
        },
        'controle_humano': None if propostas is None else dict(
            propostas,
            envio_automatico=False,
            aprovacao_exigida=True,
        ),
        'resultado': {
            'confirmados': len(resultados),
            'etapa_alcancada': _etapa_alcancada(propostas, comercial),
            'sem_confirmacao': None if propostas is None else propostas['sem_confirmacao'],
        },
        'capacidades': _capacidades(factory),
        'limites': [
            'Receita considera apenas pedidos com pagamento confirmado.',
            'Oportunidades e propostas não são receita.',
            'Nenhum número de economia de tempo, retorno ou conversão é estimado: só o que está medido aparece.',
            'Esta visão é somente leitura e não expõe contatos, nomes ou dados pessoais.',
        ],
    }


def nada_foi_lido(dados):
    """True quando nenhuma das fontes respondeu.

    Degradar bloco a bloco é o comportamento desejado (uma fonte fora do ar
    não derruba a leitura inteira). Mas se NADA foi lido não existe
    apresentação: a rota responde 503 em vez de devolver uma tela toda
    vazia como se fosse o estado real do negócio.
    """
    # 'capacidades' fica de fora: ela é lida de variáveis de ambiente e
    # responde mesmo com o banco inteiro fora do ar. Sozinha, não é uma
    # apresentação do negócio.
    return all(
        dados.get(bloco) is None
        for bloco in ('situacao', 'controle_humano', 'trabalho_da_tecnologia')
    )


def registrar_rotas_adm_apresentacao(app, factory, autorizado):
    from flask import jsonify

    @app.route('/api/admin/apresentacao', methods=['GET'])
    def adm_apresentacao():
        # Dupla checagem proposital: a rota não depende só do
        # before_request para existir de forma segura.
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        try:
            dados = montar_apresentacao(factory)
            if nada_foi_lido(dados):
                return jsonify(success=False, error='Apresentação indisponível.'), 503
            return jsonify(success=True, apresentacao=dados)
        except Exception:
            app.logger.exception('Falha ao montar a apresentação executiva')
            return jsonify(success=False, error='Apresentação indisponível.'), 503
