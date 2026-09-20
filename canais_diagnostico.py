"""Diagnóstico REAL de cada canal externo — um contrato só para todos.

Por que este módulo existe: `canais_status.py` responde a partir da presença
de variáveis de ambiente. Presença de credencial não é conexão. Um token
pode estar expirado, o app pode não ter a permissão, o webhook pode não
estar assinado e o número pode estar offline — e o painel dizia
"pendente" ou "conectado" do mesmo jeito.

Aqui cada canal é PERGUNTADO à API oficial dele, somente leitura, e a
resposta vira um estado com motivo. Regras invioláveis:

- nenhum segredo sai daqui: nem token, nem client secret, nem corpo de
  resposta cru. Só booleanos, datas, listas de permissão e códigos de erro
  da própria plataforma;
- nenhuma chamada de escrita, publicação ou envio;
- falha de rede/credencial nunca vira "conectado" nem derruba os outros
  canais: vira estado próprio com o código técnico;
- o que a API oficial não fornece é declarado como não disponível, jamais
  simulado.

`http` é injetado para permitir teste sem rede.
"""
import os
from datetime import datetime, timezone

GRAPH = 'https://graph.facebook.com/v23.0'
TIMEOUT = 12

# Estados possíveis. "pendente" genérico foi aposentado de propósito: quando
# dá para dizer o motivo, o motivo é o estado.
ESTADOS = (
    'conectado',
    'conectado_parcial',
    'aguardando_autorizacao',
    'aguardando_aprovacao_externa',
    'token_expirado',
    'bloqueado',
    'erro',
    'nao_configurado',
    'nao_priorizado',
)

# Capacidades que cada canal PODE ter. Serve para o painel não oferecer um
# botão que a API oficial não suporta.
CAPACIDADES = ('leitura', 'escrita', 'webhook')


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _base(canal, *, grupo='social'):
    """Contrato único. Todo campo desconhecido nasce None — nunca 0, nunca
    string vazia, nunca um valor otimista."""
    return {
        'canal': canal,
        'grupo': grupo,
        'estado': 'nao_configurado',
        'conta': None,
        'tipo_conta': None,
        'leitura_disponivel': False,
        'escrita_disponivel': False,
        'aprovacao_exigida': True,
        'webhook_ativo': None,
        'token_expira_em': None,
        'permissoes_concedidas': None,
        'permissoes_ausentes': None,
        'ultima_sincronizacao': None,
        'ultima_tentativa': None,
        'ultima_mensagem_recebida': None,
        'ultimo_erro': None,
        'codigo_erro': None,
        'exige_reconexao': False,
        'exige_acao_admin': False,
        'aguardando_plataforma': False,
        'verificacao_remota': False,
        'proximo_passo': None,
        'motivo_nao_priorizado': None,
    }


def _erro_tecnico(excecao):
    """Só o NOME da exceção. Mensagem de requests pode carregar URL com
    token em query string."""
    return type(excecao).__name__


def _get(http, url, *, params=None, headers=None):
    """Leitura tolerante: devolve (corpo, codigo_http, erro_tecnico)."""
    try:
        resposta = http.get(url, params=params or {}, headers=headers or {},
                            timeout=TIMEOUT, allow_redirects=False)
    except Exception as erro:
        return None, None, _erro_tecnico(erro)
    try:
        corpo = resposta.json()
    except Exception:
        corpo = None
    return corpo, resposta.status_code, None


def _erro_graph(corpo):
    """Código de erro da Meta — número, não texto do usuário."""
    if not isinstance(corpo, dict):
        return None
    erro = corpo.get('error')
    if not isinstance(erro, dict):
        return None
    return erro.get('code')


# =====================================================
# META — token compartilhado por WhatsApp e Instagram
# =====================================================

def _debug_token(http, token, app_secret):
    """Permissões e expiração reais do token, sem revelá-lo.

    debug_token exige um app token (app_id|app_secret). Sem app_secret não
    dá para perguntar — e nesse caso dizemos que não sabemos, em vez de
    supor que está tudo certo.
    """
    if not token or not app_secret:
        return None
    corpo, codigo, erro = _get(http, GRAPH + '/debug_token',
                               params={'input_token': token, 'access_token': app_secret})
    if erro or codigo != 200 or not isinstance(corpo, dict):
        return {'erro': erro, 'codigo_http': codigo, 'codigo_meta': _erro_graph(corpo)}
    dados = corpo.get('data') or {}
    expira = dados.get('expires_at')
    return {
        'valido': bool(dados.get('is_valid')),
        'expira_em': (datetime.fromtimestamp(expira, timezone.utc).isoformat()
                      if isinstance(expira, int) and expira > 0 else None),
        'permissoes': sorted(dados.get('scopes') or []) or None,
        'tipo': dados.get('type'),
    }


def diagnosticar_whatsapp(http, env=None):
    """Pergunta à Meta o que ela sabe sobre este número e esta WABA.

    Três fatos independentes, cada um com seu próprio motivo de falha:
    1. o número existe e está verificado (GET /{phone_number_id});
    2. o app está assinado no webhook da WABA (GET /{waba_id}/subscribed_apps);
    3. o token tem as permissões de mensageria (debug_token).
    """
    env = os.environ if env is None else env
    dado = _base('WhatsApp', grupo='mensageria')
    dado['ultima_tentativa'] = _agora()

    token = env.get('WHATSAPP_ACCESS_TOKEN')
    phone_id = env.get('WHATSAPP_PHONE_NUMBER_ID')
    waba_id = env.get('WHATSAPP_BUSINESS_ACCOUNT_ID')
    app_secret = env.get('META_APP_SECRET')
    verify_token = env.get('META_WEBHOOK_VERIFY_TOKEN')

    faltando = [nome for nome, valor in (
        ('WHATSAPP_ACCESS_TOKEN', token), ('WHATSAPP_PHONE_NUMBER_ID', phone_id),
        ('META_APP_SECRET', app_secret), ('META_WEBHOOK_VERIFY_TOKEN', verify_token),
    ) if not valor]
    if faltando:
        dado['estado'] = 'nao_configurado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = ('Definir no Render: ' + ', '.join(faltando)
                                 + '. Sem isso o webhook não valida assinatura e o envio fica bloqueado.')
        return dado

    dado['verificacao_remota'] = True
    cabecalho = {'Authorization': 'Bearer ' + token}

    numero, codigo, erro = _get(
        http, GRAPH + '/' + str(phone_id),
        params={'fields': 'verified_name,display_phone_number,code_verification_status,quality_rating,platform_type'},
        headers=cabecalho)
    if erro:
        dado['estado'] = 'erro'
        dado['ultimo_erro'] = 'nao_foi_possivel_falar_com_a_meta'
        dado['codigo_erro'] = erro
        dado['proximo_passo'] = 'Repetir o diagnóstico. Se persistir, verificar saída de rede do serviço.'
        return dado
    if codigo != 200:
        codigo_meta = _erro_graph(numero)
        dado['estado'] = 'token_expirado' if codigo_meta in (190, 463) else 'bloqueado'
        dado['ultimo_erro'] = 'meta_recusou_a_consulta_do_numero'
        dado['codigo_erro'] = 'http_' + str(codigo) + (('/meta_' + str(codigo_meta)) if codigo_meta else '')
        dado['exige_reconexao'] = dado['estado'] == 'token_expirado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = ('Gerar novo token do sistema no Business Manager e atualizar '
                                 'WHATSAPP_ACCESS_TOKEN.' if dado['estado'] == 'token_expirado'
                                 else 'Conferir se o Phone Number ID pertence ao app e se o ativo foi concedido a ele.')
        return dado

    numero = numero or {}
    dado['conta'] = numero.get('display_phone_number')
    dado['tipo_conta'] = numero.get('platform_type') or 'WhatsApp Business Platform'
    verificado = numero.get('code_verification_status') == 'VERIFIED'

    permissoes = _debug_token(http, token, app_secret)
    necessarias = {'whatsapp_business_messaging', 'whatsapp_business_management'}
    if permissoes and permissoes.get('permissoes') is not None:
        concedidas = set(permissoes['permissoes'])
        dado['permissoes_concedidas'] = sorted(concedidas)
        dado['permissoes_ausentes'] = sorted(necessarias - concedidas) or []
        dado['token_expira_em'] = permissoes.get('expira_em')
        if permissoes.get('valido') is False:
            dado['estado'] = 'token_expirado'
            dado['exige_reconexao'] = True
            dado['exige_acao_admin'] = True
            dado['proximo_passo'] = 'Token recusado pela Meta. Gerar novo token do sistema e atualizar WHATSAPP_ACCESS_TOKEN.'
            return dado

    if waba_id:
        assinados, codigo_webhook, erro_webhook = _get(
            http, GRAPH + '/' + str(waba_id) + '/subscribed_apps', headers=cabecalho)
        if erro_webhook or codigo_webhook != 200:
            dado['webhook_ativo'] = None
            dado['codigo_erro'] = dado['codigo_erro'] or ('http_' + str(codigo_webhook) if codigo_webhook else erro_webhook)
        else:
            dado['webhook_ativo'] = bool((assinados or {}).get('data'))
    else:
        dado['proximo_passo'] = 'Definir WHATSAPP_BUSINESS_ACCOUNT_ID para conferir a assinatura do webhook.'

    dado['leitura_disponivel'] = True
    faltam = dado['permissoes_ausentes']
    if faltam:
        dado['estado'] = 'aguardando_aprovacao_externa'
        dado['aguardando_plataforma'] = True
        dado['proximo_passo'] = ('Aguardando aprovação da Meta para: ' + ', '.join(faltam)
                                 + '. A infraestrutura de recebimento já está pronta.')
    elif not verificado:
        dado['estado'] = 'conectado_parcial'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Concluir a verificação do número comercial no WhatsApp Manager.'
    elif dado['webhook_ativo'] is False:
        dado['estado'] = 'conectado_parcial'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Assinar o campo "messages" do webhook da WABA para este app.'
    else:
        dado['estado'] = 'conectado'
        dado['escrita_disponivel'] = True
        dado['proximo_passo'] = None
    return dado


def diagnosticar_instagram(http, env=None):
    """Instagram profissional via Graph. Confirma conta e permissões; nunca
    publica nem lê conteúdo de terceiros."""
    env = os.environ if env is None else env
    dado = _base('Instagram')
    dado['ultima_tentativa'] = _agora()

    token = env.get('INSTAGRAM_ACCESS_TOKEN') or env.get('META_INSTAGRAM_ACCESS_TOKEN') or env.get('META_ACCESS_TOKEN')
    conta_id = (env.get('INSTAGRAM_ACCOUNT_ID') or env.get('META_INSTAGRAM_ACCOUNT_ID')
                or env.get('INSTAGRAM_USER_ID') or env.get('INSTAGRAM_ID'))
    if not token or not conta_id:
        dado['estado'] = 'nao_configurado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = ('Definir INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_ACCOUNT_ID '
                                 '(conta profissional vinculada a uma Página).')
        return dado

    dado['verificacao_remota'] = True
    corpo, codigo, erro = _get(http, GRAPH + '/' + str(conta_id),
                               params={'fields': 'username,name,followers_count'},
                               headers={'Authorization': 'Bearer ' + token})
    if erro:
        dado['estado'] = 'erro'
        dado['ultimo_erro'] = 'nao_foi_possivel_falar_com_a_meta'
        dado['codigo_erro'] = erro
        return dado
    if codigo != 200:
        codigo_meta = _erro_graph(corpo)
        dado['estado'] = 'token_expirado' if codigo_meta in (190, 463) else 'bloqueado'
        dado['ultimo_erro'] = 'meta_recusou_a_consulta_da_conta'
        dado['codigo_erro'] = 'http_' + str(codigo) + (('/meta_' + str(codigo_meta)) if codigo_meta else '')
        dado['exige_reconexao'] = dado['estado'] == 'token_expirado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Renovar o token da Página e atualizar INSTAGRAM_ACCESS_TOKEN.'
        return dado

    corpo = corpo or {}
    dado['conta'] = ('@' + corpo['username']) if corpo.get('username') else None
    dado['tipo_conta'] = 'Conta profissional'
    dado['leitura_disponivel'] = True

    permissoes = _debug_token(http, token, env.get('META_APP_SECRET'))
    if permissoes and permissoes.get('permissoes') is not None:
        concedidas = set(permissoes['permissoes'])
        necessarias = {'instagram_basic'}
        dado['permissoes_concedidas'] = sorted(concedidas)
        dado['permissoes_ausentes'] = sorted(necessarias - concedidas) or []
        dado['token_expira_em'] = permissoes.get('expira_em')
        # Escrita só quando a permissão existe de fato. instagram_manage_messages
        # depende de App Review; sem ela, o painel não oferece resposta.
        dado['escrita_disponivel'] = 'instagram_manage_messages' in concedidas

    dado['estado'] = 'conectado' if dado['leitura_disponivel'] else 'conectado_parcial'
    if not dado['escrita_disponivel']:
        dado['estado'] = 'conectado_parcial'
        dado['proximo_passo'] = ('Leitura ativa. Resposta a mensagens exige a permissão '
                                 'instagram_manage_messages aprovada no App Review da Meta.')
    return dado


# =====================================================
# LINKEDIN — perfil pessoal ≠ página empresarial
# =====================================================

def diagnosticar_linkedin(http, env=None):
    """Distingue o que o sistema está de fato autorizado a fazer.

    Um token de membro (`openid profile`) autentica a PESSOA. Publicar como
    a empresa exige `w_organization_social` e que a pessoa seja
    administradora da Página. São coisas diferentes, e o painel precisa
    dizer qual delas existe.
    """
    env = os.environ if env is None else env
    dado = _base('LinkedIn')
    dado['ultima_tentativa'] = _agora()

    token = env.get('LINKEDIN_ACCESS_TOKEN')
    client_id = env.get('LINKEDIN_CLIENT_ID')
    org_urn = env.get('LINKEDIN_ORGANIZATION_URN') or env.get('LINKEDIN_ORGANIZATION_ID')

    if not client_id:
        dado['estado'] = 'nao_configurado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Criar o app no LinkedIn Developer Portal e definir LINKEDIN_CLIENT_ID/SECRET.'
        return dado
    if not token:
        dado['estado'] = 'aguardando_autorizacao'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Autorizar o app em Canais → LinkedIn → Conectar (OAuth abre em nova aba).'
        return dado

    dado['verificacao_remota'] = True
    cabecalho = {'Authorization': 'Bearer ' + token, 'LinkedIn-Version': '202401',
                 'X-Restli-Protocol-Version': '2.0.0'}

    perfil, codigo, erro = _get(http, 'https://api.linkedin.com/v2/userinfo', headers=cabecalho)
    if erro:
        dado['estado'] = 'erro'
        dado['ultimo_erro'] = 'nao_foi_possivel_falar_com_o_linkedin'
        dado['codigo_erro'] = erro
        return dado
    if codigo in (401, 403):
        dado['estado'] = 'token_expirado'
        dado['exige_reconexao'] = True
        dado['exige_acao_admin'] = True
        dado['codigo_erro'] = 'http_' + str(codigo)
        dado['proximo_passo'] = 'Reautorizar o LinkedIn: o token expirou ou foi revogado.'
        return dado
    if codigo != 200:
        dado['estado'] = 'erro'
        dado['codigo_erro'] = 'http_' + str(codigo)
        dado['ultimo_erro'] = 'linkedin_recusou_a_consulta_de_perfil'
        return dado

    perfil = perfil or {}
    dado['leitura_disponivel'] = True
    dado['token_expira_em'] = env.get('LINKEDIN_TOKEN_EXPIRES_AT') or None

    # Páginas que ESTA pessoa administra. É a prova de que existe presença
    # empresarial acessível ao sistema -- não basta ter um perfil.
    organizacoes, codigo_org, _erro_org = _get(
        http, 'https://api.linkedin.com/v2/organizationAcls',
        params={'q': 'roleAssignee', 'role': 'ADMINISTRATOR', 'projection': '(elements*(organization~(localizedName)))'},
        headers=cabecalho)
    paginas = []
    if codigo_org == 200 and isinstance(organizacoes, dict):
        for item in organizacoes.get('elements') or []:
            alvo = (item or {}).get('organization~') or {}
            nome = alvo.get('localizedName')
            if nome:
                paginas.append(nome)

    if paginas:
        dado['conta'] = paginas[0]
        dado['tipo_conta'] = 'Página empresarial'
        dado['permissoes_concedidas'] = ['r_organization_social'] if codigo_org == 200 else None
        if org_urn:
            dado['escrita_disponivel'] = True
            dado['estado'] = 'conectado'
        else:
            dado['estado'] = 'conectado_parcial'
            dado['exige_acao_admin'] = True
            dado['proximo_passo'] = ('Definir LINKEDIN_ORGANIZATION_URN com a Página "'
                                     + paginas[0] + '" para habilitar publicação com aprovação humana.')
    else:
        # Autenticou a pessoa, não a empresa. Este é o estado real descrito
        # na ordem: "iniciado como perfil pessoal".
        dado['conta'] = perfil.get('name') or perfil.get('given_name')
        dado['tipo_conta'] = 'Perfil pessoal'
        dado['estado'] = 'conectado_parcial'
        dado['permissoes_ausentes'] = ['r_organization_social', 'w_organization_social']
        dado['exige_acao_admin'] = True
        dado['aguardando_plataforma'] = codigo_org == 403
        dado['proximo_passo'] = ('O sistema está ligado ao perfil pessoal. Criar/confirmar a Página '
                                 '"Maranhão Cordial", tornar este perfil administrador dela e solicitar o produto '
                                 'Community Management API no Developer Portal.')
    return dado


# =====================================================
# CANAIS SEM PRIORIDADE COMERCIAL IMEDIATA
# =====================================================

def _nao_priorizado(canal, motivo, proximo_passo, env, chave_token):
    """Nem tudo precisa estar "pendente" para sempre. Quando a integração
    não tem uso comercial agora, o painel diz isso e para de cobrar."""
    dado = _base(canal)
    dado['estado'] = 'nao_priorizado'
    dado['motivo_nao_priorizado'] = motivo
    dado['proximo_passo'] = proximo_passo
    dado['aprovacao_exigida'] = True
    if env.get(chave_token):
        dado['tipo_conta'] = 'Credencial presente; verificação remota não solicitada'
    return dado


def diagnosticar_pinterest(http, env=None):
    env = os.environ if env is None else env
    return _nao_priorizado(
        'Pinterest',
        'Sem uso comercial imediato definido para a operação atual.',
        'Reavaliar quando houver catálogo visual publicado. A integração técnica permanece disponível em Canais.',
        env, 'PINTEREST_ACCESS_TOKEN')


def diagnosticar_x(http, env=None):
    env = os.environ if env is None else env
    return _nao_priorizado(
        'X',
        'A API oficial exige plano pago para escrita; nenhum plano foi contratado.',
        'Reavaliar caso a publicação em X entre no plano de comunicação. Nenhum custo foi assumido.',
        env, 'X_ACCESS_TOKEN')


# =====================================================
# TIKTOK — social e loja são canais diferentes
# =====================================================

def diagnosticar_tiktok_social(http, env=None):
    """Login Kit + Display API: perfil e vídeos. Não vê pedido nem cliente."""
    env = os.environ if env is None else env
    dado = _base('TikTok Social')
    dado['ultima_tentativa'] = _agora()
    if not env.get('TIKTOK_CLIENT_KEY'):
        dado['estado'] = 'nao_configurado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Definir TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET do app no TikTok for Developers.'
        return dado
    dado['estado'] = 'aguardando_autorizacao'
    dado['tipo_conta'] = 'Conta de conteúdo (Login Kit)'
    dado['leitura_disponivel'] = False
    dado['exige_acao_admin'] = True
    dado['proximo_passo'] = ('Autorizar em /api/tiktok/login. Esta integração lê perfil e vídeos; '
                             'pedidos e clientes só existem no TikTok Shop.')
    return dado


def diagnosticar_tiktok_shop(http, env=None):
    """TikTok Shop Partner API — canal comercial, não rede social.

    Só entra em operação com app aprovado no TikTok Shop Partner Center e
    autorização da loja. Nada aqui tenta imitar a API por navegador ou
    raspagem: sem credencial, o estado é "não configurado" com o passo
    exato.
    """
    env = os.environ if env is None else env
    dado = _base('TikTok Shop', grupo='comercial')
    dado['ultima_tentativa'] = _agora()
    dado['aprovacao_exigida'] = True

    chave = env.get('TIKTOK_SHOP_APP_KEY')
    segredo = env.get('TIKTOK_SHOP_APP_SECRET')
    token_loja = env.get('TIKTOK_SHOP_ACCESS_TOKEN')

    if not chave or not segredo:
        dado['estado'] = 'nao_configurado'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = ('Criar o app em partner.tiktokshop.com (Partner Center) e definir '
                                 'TIKTOK_SHOP_APP_KEY e TIKTOK_SHOP_APP_SECRET. '
                                 'Exige conta de parceiro aprovada — etapa de validação empresarial.')
        return dado
    if not token_loja:
        dado['estado'] = 'aguardando_autorizacao'
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = ('Autorizar a loja no Seller Center e guardar o token em '
                                 'TIKTOK_SHOP_ACCESS_TOKEN.')
        return dado

    dado['verificacao_remota'] = True
    corpo, codigo, erro = _get(http, 'https://open-api.tiktokglobalshop.com/authorization/202309/shops',
                               headers={'x-tts-access-token': token_loja})
    if erro:
        dado['estado'] = 'erro'
        dado['ultimo_erro'] = 'nao_foi_possivel_falar_com_o_tiktok_shop'
        dado['codigo_erro'] = erro
        return dado
    if codigo != 200:
        dado['estado'] = 'token_expirado' if codigo in (401, 403) else 'erro'
        dado['codigo_erro'] = 'http_' + str(codigo)
        dado['exige_reconexao'] = codigo in (401, 403)
        dado['exige_acao_admin'] = True
        dado['proximo_passo'] = 'Reautorizar a loja no Seller Center.'
        return dado
    lojas = ((corpo or {}).get('data') or {}).get('shops') or []
    dado['conta'] = (lojas[0] or {}).get('name') if lojas else None
    dado['tipo_conta'] = 'Loja TikTok Shop'
    dado['leitura_disponivel'] = bool(lojas)
    dado['estado'] = 'conectado' if lojas else 'conectado_parcial'
    if not lojas:
        dado['proximo_passo'] = 'O token não devolveu nenhuma loja autorizada. Refazer a autorização no Seller Center.'
    return dado


REGISTRO = {
    'WhatsApp': diagnosticar_whatsapp,
    'Instagram': diagnosticar_instagram,
    'LinkedIn': diagnosticar_linkedin,
    'TikTok Shop': diagnosticar_tiktok_shop,
    'TikTok Social': diagnosticar_tiktok_social,
    'Pinterest': diagnosticar_pinterest,
    'X': diagnosticar_x,
}


def diagnosticar(canal, http=None, env=None):
    """Um canal. Exceção inesperada vira estado de erro com o nome da
    exceção — nunca derruba o painel inteiro."""
    funcao = REGISTRO.get(canal)
    if not funcao:
        dado = _base(canal)
        dado['estado'] = 'nao_configurado'
        dado['proximo_passo'] = 'Canal sem diagnóstico implementado.'
        return dado
    if http is None:
        import requests as http
    try:
        return funcao(http, env)
    except Exception as erro:
        dado = _base(canal)
        dado['estado'] = 'erro'
        dado['ultima_tentativa'] = _agora()
        dado['ultimo_erro'] = 'falha_inesperada_no_diagnostico'
        dado['codigo_erro'] = _erro_tecnico(erro)
        return dado
