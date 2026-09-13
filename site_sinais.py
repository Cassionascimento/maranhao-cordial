"""Sinais de comportamento do site público (ETAPA 5.4).

Os sinais que já existem de fato -- interesse em degustação (formulário de
/api/degustacao) e interesse profissional/B2B (formulário de
/api/profissional/cadastro) -- são emitidos diretamente em main.py, logo
após cada cadastro ser salvo, reaproveitando mi_sinais.emitir(). Nenhum
código deste arquivo participa desses dois fluxos.

Este módulo é a infraestrutura para sinais PASSIVOS de navegação (página/
produto visitado, CTA clicado, origem/campanha, retorno ao site, intenção de
contato sem formulário) -- pronta e testada, mas **não ligada a nenhuma
página do site nesta etapa**: o site não tem hoje nenhum mecanismo de
consentimento (banner de cookies/preferências) que justifique capturar
comportamento de navegação, mesmo anônimo. Ativar isso sem esse mecanismo
contrariaria "respeitar consentimento", pedido explicitamente nesta etapa.
Quando esse mecanismo existir, basta a página chamar
POST /api/site/sinal com {tipo, consentimento: true, ...}.

Nunca aceita e-mail, telefone, nome, IP ou qualquer identificador real.
'visitante_anonimo', quando enviado, deve ser um token opaco gerado no
navegador (ex.: crypto.randomUUID() salvo em localStorage) -- reconhece
"esta sessão já visitou antes", nunca "quem é esta pessoa". Sem consentimento
explícito (`consentimento: true`), nada é gravado: falha fechada.
"""
import re
from mi_sinais import emitir

TIPOS_SINAL = (
    'pagina_visitada', 'produto_visitado', 'cta_clicado',
    'interesse_degustacao', 'interesse_profissional_b2b',
    'retorno_visitante', 'intencao_contato',
)
# Naturezas por tipo: cliques/visitas expressam interesse, ainda não um fato
# comercial confirmado; os dois tipos com formulário real (degustação/B2B)
# são emitidos por main.py como 'fato', não por aqui.
NATUREZA_POR_TIPO = {
    'pagina_visitada': 'fato', 'retorno_visitante': 'fato',
    'produto_visitado': 'interesse_observado', 'cta_clicado': 'interesse_observado',
    'intencao_contato': 'interesse_observado',
    'interesse_degustacao': 'fato', 'interesse_profissional_b2b': 'fato',
}
PRODUTOS = ('guarana', 'acai', 'bacuri')
PADRAO_CURTO = re.compile(r'[a-z][a-z0-9_-]{0,63}')
PADRAO_ANONIMO = re.compile(r'[a-z0-9-]{8,64}')


def validar_sinal_site(body):
    if not isinstance(body, dict):
        raise ValueError('corpo_invalido')
    if body.get('consentimento') is not True:
        raise ValueError('consentimento_obrigatorio')
    tipo = body.get('tipo')
    if tipo not in TIPOS_SINAL:
        raise ValueError('tipo_invalido')
    produto = body.get('produto')
    if produto is not None and produto not in PRODUTOS:
        raise ValueError('produto_invalido')
    for campo in ('origem', 'cta'):
        valor = body.get(campo)
        if valor is not None and (not isinstance(valor, str) or not PADRAO_CURTO.fullmatch(valor)):
            raise ValueError(campo + '_invalido')
    anonimo = body.get('visitante_anonimo')
    if anonimo is not None and (not isinstance(anonimo, str) or not PADRAO_ANONIMO.fullmatch(anonimo)):
        raise ValueError('visitante_anonimo_invalido')
    return {'tipo': tipo, 'produto': produto, 'origem': body.get('origem'), 'cta': body.get('cta'),
            'anonimo': anonimo}


def registrar_sinal_site(factory, body):
    dados = validar_sinal_site(body)
    payload = {k: dados[k] for k in ('produto', 'cta') if dados[k]}
    return emitir(
        factory, natureza=NATUREZA_POR_TIPO[dados['tipo']], origem='site', tipo_evento=dados['tipo'],
        canal=dados['origem'] or 'site', discriminador=dados['anonimo'], payload=payload,
    )


def registrar_rotas_site_sinais(app, factory):
    from flask import request, jsonify

    @app.route('/api/site/sinal', methods=['POST'])
    def site_sinal():
        dados = request.get_json(silent=True) or {}
        try:
            validar_sinal_site(dados)
        except ValueError:
            return jsonify(success=False, error='Sinal inválido.'), 400
        registrar_sinal_site(factory, dados)
        return jsonify(success=True), 202
