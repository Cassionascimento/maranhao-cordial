"""QR v1 do Maranhão Intelligence: codigo_publico -> unidade -> mi_evento(scan).

codigo_publico só identifica a unidade; nunca é tratado como prova de
autenticidade. A resposta pública nunca inclui id interno, sku ou lote —
por isso nem lê esses dados prontos para expor. Nenhuma PII (IP, e-mail,
telefone, user-agent) é aceita ou armazenada aqui: a função nem tem
parâmetro para isso.

chave_requisicao é só para idempotência técnica (o mesmo request
reenviado pelo chamador, ex. retry de rede); na ausência dela, cada
chamada é um scan novo e legítimo — não há dedução por janela de tempo
nem qualquer heurística por hora/dia.

Inexistência, revogação e formato inválido do código recebem exatamente
a mesma resposta pública genérica, de propósito: não dar pista de qual
foi o motivo da falha para quem está tentando adivinhar códigos.
"""
from uuid import UUID, uuid4
from mi_unidades import normalizar_codigo_publico, buscar_unidade_por_codigo
from mi_eventos import registrar_evento_mi

ERRO_PUBLICO = {'success': False, 'error': 'codigo_invalido'}


def registrar_scan_qr(factory, codigo_publico, chave_requisicao=None):
    try:
        codigo = normalizar_codigo_publico(codigo_publico)
    except ValueError:
        return dict(ERRO_PUBLICO), 404

    if chave_requisicao is None:
        chave = str(uuid4())
    elif isinstance(chave_requisicao, str):
        chave = str(UUID(chave_requisicao))
    else:
        raise ValueError('chave_requisicao_invalida')

    unidade = buscar_unidade_por_codigo(factory, codigo)
    if not unidade or unidade['estado'] == 'revogada':
        return dict(ERRO_PUBLICO), 404

    try:
        _, status = registrar_evento_mi(factory, {
            'chave': chave,
            'tipo_evento': 'scan',
            'canal': 'qr',
            'unidade_id': str(unidade['id']),
        })
    except ValueError:
        return dict(ERRO_PUBLICO), 404

    if status >= 400:
        return dict(ERRO_PUBLICO), 404

    return {'success': True}, status
