"""Reautorização do Instagram/Meta pelo ADM — começo ao fim, no backend.

O que este módulo NÃO faz, de propósito: nenhum segredo passa pelo
navegador. A tela só recebe a URL do diálogo da Meta; o código de
autorização é trocado por token aqui, o token é gravado cifrado
(canais_credenciais) e nunca volta para o cliente — nem em JSON, nem em
URL, nem em log.

Preserva o que existe: a Página e a conta profissional já vinculadas são
descobertas, não criadas. O fluxo nunca cria conta nova nem troca a
Página por outra sem que o ativo apareça na lista autorizada.
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

CANAL = 'Instagram'
GRAPH = 'https://graph.facebook.com/v23.0'
DIALOGO = 'https://www.facebook.com/v23.0/dialog/oauth'
TIMEOUT = 15

# Leitura da conta profissional. `instagram_manage_messages` fica fora:
# depende de App Review e pedi-la aqui faria o diálogo falhar para quem
# ainda não tem a aprovação.
ESCOPOS_LEITURA = ('instagram_basic', 'pages_show_list', 'pages_read_engagement')
NOME_TOKEN = 'INSTAGRAM_ACCESS_TOKEN'


def config(env=None):
    env = os.environ if env is None else env
    return {
        'app_id': env.get('META_APP_ID') or env.get('FACEBOOK_APP_ID') or env.get('INSTAGRAM_APP_ID'),
        'app_secret': env.get('META_APP_SECRET'),
    }


def faltantes(env=None):
    """Nomes de variáveis que impedem o fluxo — nunca os valores."""
    cfg = config(env)
    ausentes = []
    if not cfg['app_id']:
        ausentes.append('META_APP_ID')
    if not cfg['app_secret']:
        ausentes.append('META_APP_SECRET')
    return ausentes


def montar_url_autorizacao(*, redirect_uri, state, escopos=ESCOPOS_LEITURA, env=None):
    cfg = config(env)
    if not cfg['app_id']:
        raise ValueError('META_APP_ID ausente')
    return DIALOGO + '?' + urlencode({
        'client_id': cfg['app_id'],
        'redirect_uri': redirect_uri,
        'state': state,
        'response_type': 'code',
        'scope': ','.join(escopos),
        # Força a tela de permissões: reautorização precisa poder recuperar
        # um escopo que foi removido antes.
        'auth_type': 'rerequest',
    })


def _json(resposta):
    try:
        return resposta.json()
    except Exception:
        return {}


def _erro_meta(corpo):
    erro = (corpo or {}).get('error') if isinstance(corpo, dict) else None
    if not isinstance(erro, dict):
        return None
    return erro.get('code')


def trocar_codigo(http, *, codigo, redirect_uri, env=None):
    """Código -> token curto -> token de longa duração.

    Devolve `{'token', 'expira_em'}`. Qualquer falha vira ValueError com um
    motivo curto: nem o código, nem o corpo da resposta, nem a URL entram
    na mensagem.
    """
    cfg = config(env)
    if not cfg['app_id'] or not cfg['app_secret']:
        raise ValueError('configuracao_meta_incompleta')
    try:
        curto = http.get(GRAPH + '/oauth/access_token', params={
            'client_id': cfg['app_id'], 'client_secret': cfg['app_secret'],
            'redirect_uri': redirect_uri, 'code': codigo,
        }, timeout=TIMEOUT, allow_redirects=False)
    except Exception:
        raise ValueError('meta_indisponivel')
    corpo = _json(curto)
    if curto.status_code != 200 or not corpo.get('access_token'):
        raise ValueError('troca_de_codigo_recusada:' + str(_erro_meta(corpo) or curto.status_code))

    try:
        longo = http.get(GRAPH + '/oauth/access_token', params={
            'grant_type': 'fb_exchange_token', 'client_id': cfg['app_id'],
            'client_secret': cfg['app_secret'], 'fb_exchange_token': corpo['access_token'],
        }, timeout=TIMEOUT, allow_redirects=False)
    except Exception:
        raise ValueError('meta_indisponivel')
    corpo_longo = _json(longo)
    token = corpo_longo.get('access_token') if longo.status_code == 200 else None
    # Sem o token longo, o curto ainda serve: melhor uma credencial de vida
    # curta, com validade declarada, do que nenhuma.
    efetivo = token or corpo['access_token']
    segundos = corpo_longo.get('expires_in') if token else corpo.get('expires_in')
    expira_em = None
    if isinstance(segundos, int) and segundos > 0:
        expira_em = datetime.now(timezone.utc) + timedelta(seconds=segundos)
    return {'token': efetivo, 'expira_em': expira_em, 'longa_duracao': bool(token)}


def descobrir_ativos(http, token):
    """Página autorizada e conta profissional do Instagram vinculada a ela.

    Nada é criado: se a lista não trouxer Página com conta vinculada, o
    fluxo devolve o motivo em vez de inventar um ativo.
    """
    try:
        resposta = http.get(GRAPH + '/me/accounts', params={
            'fields': 'name,id,access_token,instagram_business_account{id,username,name}',
        }, headers={'Authorization': 'Bearer ' + token}, timeout=TIMEOUT, allow_redirects=False)
    except Exception:
        raise ValueError('meta_indisponivel')
    corpo = _json(resposta)
    if resposta.status_code != 200:
        raise ValueError('listagem_de_paginas_recusada:' + str(_erro_meta(corpo) or resposta.status_code))
    for pagina in (corpo.get('data') or []):
        conta = (pagina or {}).get('instagram_business_account') or {}
        if conta.get('id'):
            return {
                'pagina_id': pagina.get('id'), 'pagina_nome': pagina.get('name'),
                'instagram_id': conta['id'], 'instagram_usuario': conta.get('username'),
                # Token de Página: é ele que autentica leitura da conta
                # profissional. Volta daqui e é gravado cifrado.
                'token_pagina': pagina.get('access_token'),
            }
    raise ValueError('nenhuma_pagina_com_instagram_vinculado')


def confirmar_leitura(http, *, token, instagram_id):
    """Consulta autenticada real. Sem ela, nada é marcado como conectado."""
    try:
        resposta = http.get(GRAPH + '/' + str(instagram_id),
                            params={'fields': 'username,name,followers_count'},
                            headers={'Authorization': 'Bearer ' + token},
                            timeout=TIMEOUT, allow_redirects=False)
    except Exception:
        raise ValueError('meta_indisponivel')
    corpo = _json(resposta)
    if resposta.status_code != 200:
        raise ValueError('consulta_autenticada_recusada:' + str(_erro_meta(corpo) or resposta.status_code))
    return {'username': corpo.get('username'), 'nome': corpo.get('name'),
            'seguidores': corpo.get('followers_count')}


def concluir(http, factory, *, codigo, redirect_uri, ator=None, env=None):
    """Troca, descobre, valida e grava — nesta ordem, tudo no servidor.

    Só grava depois que uma leitura autenticada real deu certo. Devolve o
    resumo que o painel pode mostrar; o token não está nele.
    """
    import canais_credenciais as cc

    trocado = trocar_codigo(http, codigo=codigo, redirect_uri=redirect_uri, env=env)
    ativos = descobrir_ativos(http, trocado['token'])
    token_efetivo = ativos.get('token_pagina') or trocado['token']
    perfil = confirmar_leitura(http, token=token_efetivo, instagram_id=ativos['instagram_id'])

    metadados = {
        'conta': ('@' + perfil['username']) if perfil.get('username') else None,
        'instagram_id': ativos['instagram_id'],
        'pagina': ativos.get('pagina_nome'),
        'escopos': list(ESCOPOS_LEITURA),
        'longa_duracao': trocado['longa_duracao'],
        'verificado_em': datetime.now(timezone.utc).isoformat(),
    }
    cc.salvar(factory, canal=CANAL, nome=NOME_TOKEN, segredo=token_efetivo,
              metadados=metadados, expira_em=trocado['expira_em'], ator=ator, env=env)
    cc.salvar(factory, canal=CANAL, nome='INSTAGRAM_ACCOUNT_ID',
              segredo=str(ativos['instagram_id']), metadados={'origem': 'oauth'},
              ator=ator, env=env)
    return {'conta': metadados['conta'], 'pagina': metadados['pagina'],
            'longa_duracao': trocado['longa_duracao'],
            'expira_em': trocado['expira_em'].isoformat() if trocado['expira_em'] else None}
