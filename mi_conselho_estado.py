"""Pacote de estado da demanda -- o snapshot que falta ser MONTADO antes de
qualquer deliberação do Conselho de Agentes.

Motivação real: `mi_conselho_executor.executar_especialista` sempre foi
capaz de receber um `snapshot` (mi_conselho_orquestrador.formatar_
contexto_factual já existe para isso desde a integração original), mas
`processar_e_registrar` nunca montava um -- cada especialista automático
respondia só com a frase curta da demanda, sem enxergar o que já estava em
andamento/concluído, sem bloqueios, sem prazos. Este módulo fecha essa
lacuna com UMA função, reaproveitando o que já existe:

- mi_diretor.leitura_diretor -- estado atual, ações de hoje/aguardando/
  concluídas/bloqueadas, resumo do Conselho (já agrega mi_decisao +
  mi_publico + mi_conselho, nenhuma consulta de negócio nova aqui);
- mi_conselho_orquestrador.classificar_especialistas -- agentes
  pertinentes (já validado, não duplicado);
- mi_conselho_fatos -- fatos confirmados com proveniência/validade,
  buscados por palavra-chave da própria demanda (mesmo estilo de
  correspondência por palavra-chave já usado em `_REGRAS_CLASSIFICACAO`).

`dados_ausentes` começa vazio de propósito: identificar lacuna é
julgamento de especialista (a própria Iris), não algo que este módulo
mecânico deveria inventar antes de qualquer agente falar. Quem preenche
esse campo de verdade é `mi_conselho_executor._consolidar`, a partir do
campo `lacunas` que cada parecer devolve.

Este módulo TOMA `factory()` (é leitura de banco, como mi_decisao.py/
mi_diretor.py) -- diferente de mi_conselho_orquestrador.py, que nunca pode
receber factory/credencial (monta só o texto do prompt). A fronteira entre
os dois continua a mesma: aqui só se lê e organiza; quem decide o que
recomendar continua sendo o LLM (mi_conselho_executor) ou o humano
(/conclave).
"""
import re
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

from mi_diretor import leitura_diretor
from mi_conselho_orquestrador import classificar_especialistas
from mi_conselho_fatos import fatos_atuais_por_prefixo

_PRIORIDADE_ORDEM = {'urgente': 0, 'alta': 1, 'normal': 2, 'baixa': 3}
_PALAVRA_CHAVE = re.compile(r'[a-zà-ú0-9_]{4,}', re.I)
_PALAVRAS_IGNORADAS = {
    'para', 'sobre', 'como', 'esse', 'essa', 'este', 'esta', 'pelo', 'pela',
    'quando', 'onde', 'porque', 'ainda', 'sendo', 'foram', 'temos', 'sem',
}


def _prioridade(atividade):
    return _PRIORIDADE_ORDEM.get(atividade.get('prioridade'), 9)


def _termos_da_demanda(demanda, limite=6):
    """Mesmo espírito de `_REGRAS_CLASSIFICACAO` (mi_conselho_orquestrador):
    correspondência determinística por palavra-chave, não busca semântica.
    Serve só para achar fatos confirmados potencialmente relevantes -- não
    decide nada sozinho, é só o que alimenta `evidencias`."""
    termos = []
    for match in _PALAVRA_CHAVE.finditer(demanda.lower()):
        termo = match.group(0)
        if termo in _PALAVRAS_IGNORADAS or termo in termos:
            continue
        termos.append(termo)
        if len(termos) >= limite:
            break
    return termos


def _dedup_por_chave(*listas):
    vistos, resultado = set(), []
    for lista in listas:
        for item in lista:
            chave = item.get('chave')
            if chave in vistos:
                continue
            vistos.add(chave)
            resultado.append(item)
    return resultado


def _fatos_relacionados(factory, demanda, limite_por_termo=5, limite_total=20):
    termos = _termos_da_demanda(demanda)
    if not termos:
        return []
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            vistos, achados = set(), []
            for termo in termos:
                try:
                    for fato in fatos_atuais_por_prefixo(cur, termo, limite=limite_por_termo):
                        if fato['topico'] in vistos:
                            continue
                        vistos.add(fato['topico'])
                        achados.append(fato)
                except Exception:
                    # Consulta best-effort por palavra-chave -- uma falha
                    # pontual (ex.: caractere inesperado) nunca derruba o
                    # resto do pacote de estado.
                    conn.rollback()
                    continue
                if len(achados) >= limite_total:
                    break
            return achados[:limite_total]
    finally:
        conn.close()


def _objetivos_estrategicos_ativos(factory, limite=20):
    """Best-effort: a tabela `objetivos_estrategicos` (ORQUESTRADOR
    EMPRESARIAL, main.py) só existe depois que
    `garantir_tabelas_orquestrador_empresarial()` rodou -- nem todo
    ambiente terá isso. Ausência da tabela nunca derruba o pacote de
    estado; só devolve lista vazia."""
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='10s'")
            try:
                cur.execute(
                    "SELECT id, titulo, descricao, area, prioridade, criado_em "
                    "FROM objetivos_estrategicos WHERE status='ativo' "
                    "ORDER BY CASE prioridade WHEN 'critica' THEN 1 WHEN 'alta' THEN 2 "
                    "WHEN 'media' THEN 3 ELSE 4 END, criado_em DESC LIMIT %s",
                    (limite,),
                )
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                conn.rollback()
                return []
    finally:
        conn.close()


def montar_pacote_estado(factory, demanda, classificacao=None, agora=None):
    """Ponto único desta etapa: devolve exatamente os 11 campos pedidos
    para toda deliberação (demanda, estado_atual, acoes_concluidas,
    acoes_em_andamento, evidencias, dados_ausentes, bloqueios,
    dependencias, prazos, restricoes, agentes_pertinentes). Cada campo
    reaproveita uma leitura já existente -- nenhuma tabela nova é
    consultada além de mi_conselho_fatos (nova nesta etapa) e
    objetivos_estrategicos (já existente, só não lida por este caminho
    ainda)."""
    if not isinstance(demanda, str) or not demanda.strip():
        raise ValueError('demanda_obrigatoria')
    agora = agora or datetime.now(timezone.utc)

    leitura = leitura_diretor(factory, agora)
    hoje = leitura['hoje']

    acoes_em_andamento = sorted(
        _dedup_por_chave(hoje.get('planejado', []), hoje.get('aguardando', [])),
        key=_prioridade,
    )
    bloqueios = _dedup_por_chave(hoje.get('bloqueado', []), hoje.get('precisa_de_mim', []))
    acoes_concluidas = hoje.get('concluido', [])

    prazos = sorted(
        (
            {'descricao': a.get('motivo') or a.get('proxima_acao'), 'executar_em': a.get('executar_em')}
            for a in acoes_em_andamento if a.get('executar_em')
        ),
        key=lambda p: p['executar_em'],
    )

    objetivos = _objetivos_estrategicos_ativos(factory)
    termos = set(_termos_da_demanda(demanda))
    dependencias = [
        o for o in objetivos
        if termos & set(_termos_da_demanda((o.get('titulo') or '') + ' ' + (o.get('descricao') or '')))
    ] or objetivos[:5]  # sem correspondência direta: os objetivos mais prioritários ainda dão contexto útil

    if classificacao is None:
        classificacao = classificar_especialistas(demanda)

    return {
        'demanda': demanda.strip(),
        'estado_atual': {
            'ia_trabalhando': leitura.get('ia_trabalhando'),
            'calendario': leitura.get('calendario'),
            'conselho': {
                'trabalhando': leitura['conselho'].get('trabalhando'),
                'sem_demanda': leitura['conselho'].get('sem_demanda'),
                'vetos_abertos': len(leitura['conselho'].get('vetos') or []),
                'aguardando_diretor': len(leitura['conselho'].get('aguardando_diretor') or []),
            },
            'chamar_diretor': leitura.get('chamar_diretor'),
        },
        'acoes_concluidas': acoes_concluidas,
        'acoes_em_andamento': acoes_em_andamento,
        'evidencias': _fatos_relacionados(factory, demanda),
        # Preenchido depois que os especialistas (sobretudo Iris) respondem
        # -- ver mi_conselho_executor._consolidar. Fica vazio aqui de
        # propósito: identificar lacuna é julgamento de especialista, não
        # algo que este montador mecânico deveria supor antes da rodada.
        'dados_ausentes': [],
        'bloqueios': bloqueios,
        'dependencias': dependencias,
        'prazos': prazos,
        'restricoes': [
            'Nenhum agente executa sozinho ação irreversível, gasto real, publicação ou envio externo.',
            'Objetivos estratégicos ativos só mudam por comando explícito da direção (main.py, ORQUESTRADOR EMPRESARIAL).',
        ],
        'agentes_pertinentes': classificacao,
    }
