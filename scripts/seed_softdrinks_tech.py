"""Central Empresarial -- seção 4 da ordem (caso canônico Softdrinks
Tech). Cria (uma única vez, idempotente) a operação viva com SOMENTE os
fatos já confirmados pela direção: título e datas. Todo o resto
(local/staff/bartender/roupas/atividades/custos/KPIs) nasce vazio ou
AGUARDANDO DADOS -- nunca é inventado aqui.

Uso (rodado manualmente por um humano, nunca por este agente, contra o
banco que a pessoa escolher explicitamente via DATABASE_URL):

    DATABASE_URL=postgres://... python3 scripts/seed_softdrinks_tech.py

Não faz nada em produção por conta própria: precisa de DATABASE_URL
explícita no ambiente de quem executa. Reaproveita mi_operacoes.
criar_operacao -- nenhuma tabela/rota nova.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TITULO = 'Softdrinks Tech'
DATA_INICIO = '2026-10-15'
DATA_FIM = '2026-10-16'


def _factory():
    import psycopg2
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL não configurada -- defina explicitamente antes de rodar este script.')
    return lambda: psycopg2.connect(database_url, sslmode=os.getenv('DB_SSLMODE', 'require'))


def semear(factory, criado_por='seed_softdrinks_tech'):
    from mi_operacoes import listar_operacoes, criar_operacao

    existentes = listar_operacoes(factory, desde=DATA_INICIO, ate=DATA_FIM)
    ja_existe = next((o for o in existentes if o['titulo'] == TITULO), None)
    if ja_existe:
        return {'success': True, 'criado': False, 'operacao': ja_existe}

    resultado = criar_operacao(
        factory, titulo=TITULO, data_inicio=DATA_INICIO, data_fim=DATA_FIM, criado_por=criado_por,
        descricao='Caso canônico da Central Empresarial -- Operações Vivas. '
                  'Local, equipe, roupas, atividades, custos e indicadores começam '
                  'como AGUARDANDO DADOS até que a direção confirme cada fato.',
        local=None, prioridade='normal', responsavel=None,
    )
    return {'success': resultado['success'], 'criado': True, 'operacao': resultado.get('operacao')}


if __name__ == '__main__':
    resultado = semear(_factory())
    if not resultado['success']:
        print('Falha ao semear a operação Softdrinks Tech:', resultado)
        sys.exit(1)
    acao = 'criada agora' if resultado['criado'] else 'já existia (nenhuma duplicata gerada)'
    print(f"Operação 'Softdrinks Tech' {acao}: id={resultado['operacao']['id']}")
