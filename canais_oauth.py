"""Rotas de autorização dos canais — iniciar no ADM, voltar para o cartão.

Duas rotas por canal, com proteções diferentes de propósito:

- `/api/admin/<canal>/connect` exige chave administrativa e devolve apenas
  a URL do diálogo da plataforma. Nenhum segredo sai daqui.
- `/api/<canal>/callback` é aberta pelo navegador depois do consentimento,
  então NÃO pode exigir cabeçalho administrativo — quem a protege é o
  `state` de uso único, preso ao navegador que iniciou o fluxo. Por isso
  ela vive fora de `/api/admin/`, igual ao callback do Gmail e do TikTok
  que já existiam.

O callback nunca ecoa código, token ou corpo de resposta. O redirecionamento
de volta carrega só canal e desfecho.
"""
import os
import secrets

# Página do ADM e a vista de Canais do shell novo.
RETORNO_ADM = '/admin.html'

# Desfechos que o ADM sabe traduzir. Qualquer outro vira 'erro'.
DESFECHOS = ('ok', 'cancelado', 'estado_invalido', 'repetido', 'erro', 'indisponivel')


def _identidade_navegador(session):
    """Marca opaca do navegador que iniciou o fluxo.

    Prende o callback à mesma sessão: um `state` vazado não completa a
    autorização em outro navegador.
    """
    marca = session.get('canais_oauth_navegador')
    if not marca:
        marca = secrets.token_urlsafe(24)
        session['canais_oauth_navegador'] = marca
    return marca


def _retorno(canal, desfecho, detalhe=None):
    from urllib.parse import urlencode
    if desfecho not in DESFECHOS:
        desfecho = 'erro'
    parametros = {'canal': canal, 'oauth': desfecho}
    if detalhe:
        # Motivo curto e sem dado sensível; serve para a pessoa entender.
        parametros['motivo'] = str(detalhe)[:120]
    return RETORNO_ADM + '?' + urlencode(parametros)


def registrar_rotas_canais_oauth(app, factory, autorizado):
    from flask import jsonify, redirect, request, session

    import canais_credenciais as cc
    import meta_oauth

    def _redirect_uri(caminho):
        """URL absoluta desta aplicação. A Meta exige correspondência exata
        entre o que foi usado no diálogo e o que vai na troca do código."""
        base = os.getenv('PUBLIC_BASE_URL') or request.url_root.rstrip('/')
        return base.rstrip('/') + caminho

    # -------------------------------------------------
    # INSTAGRAM / META
    # -------------------------------------------------

    @app.route('/api/admin/instagram/connect', methods=['GET'])
    def instagram_connect():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        ausentes = meta_oauth.faltantes()
        if ausentes:
            return jsonify(success=False, configuracao_ausente=ausentes,
                           error='Configuração da Meta incompleta: ' + ', '.join(ausentes)), 409
        if not cc.chave_configurada():
            return jsonify(success=False, configuracao_ausente=['CANAIS_CRYPTO_KEY'],
                           error='Sem chave de cifragem não é possível guardar a credencial.'), 409
        redirect_uri = _redirect_uri('/api/instagram/callback')
        try:
            state = cc.criar_estado(factory, canal=meta_oauth.CANAL,
                                    navegador=_identidade_navegador(session),
                                    redirect_uri=redirect_uri)
        except Exception:
            app.logger.exception('Falha ao criar estado OAuth do Instagram')
            return jsonify(success=False, error='Não foi possível iniciar a autorização.'), 503
        return jsonify(success=True,
                       url=meta_oauth.montar_url_autorizacao(redirect_uri=redirect_uri, state=state),
                       escopos=list(meta_oauth.ESCOPOS_LEITURA))

    @app.route('/api/instagram/callback', methods=['GET'])
    def instagram_callback():
        """Protegida pelo state, não por cabeçalho: quem chega aqui é o
        navegador da pessoa, vindo da Meta."""
        import requests

        canal = meta_oauth.CANAL
        state = request.args.get('state')
        if request.args.get('error'):
            # Consentimento negado é desfecho normal, não falha do sistema.
            return redirect(_retorno(canal, 'cancelado'))
        codigo = request.args.get('code')
        if not codigo or not state:
            return redirect(_retorno(canal, 'estado_invalido'))
        try:
            estado = cc.consumir_estado(factory, canal=canal, state=state,
                                        navegador=_identidade_navegador(session))
        except cc.EstadoOAuthInvalido as erro:
            # Callback repetido: a primeira passagem já decidiu. Não troca o
            # código de novo (a Meta o invalidaria) nem sobrescreve nada.
            if getattr(erro, 'ja_consumido', False):
                return redirect(_retorno(canal, 'repetido', getattr(erro, 'resultado', None)))
            return redirect(_retorno(canal, 'estado_invalido', str(erro)))
        except Exception:
            app.logger.exception('Falha ao validar estado OAuth do Instagram')
            return redirect(_retorno(canal, 'indisponivel'))

        try:
            resumo = meta_oauth.concluir(requests, factory, codigo=codigo,
                                         redirect_uri=estado['redirect_uri'], ator='oauth_adm')
        except ValueError as erro:
            # str(ValueError) aqui é um motivo curto montado por meta_oauth;
            # nunca carrega código, token ou corpo de resposta.
            motivo = str(erro)
            cc.registrar_resultado(factory, state=state, resultado='erro:' + motivo)
            app.logger.warning('Instagram OAuth não concluiu: %s', motivo)
            return redirect(_retorno(canal, 'erro', motivo))
        except Exception:
            app.logger.exception('Falha inesperada no callback do Instagram')
            cc.registrar_resultado(factory, state=state, resultado='indisponivel')
            return redirect(_retorno(canal, 'indisponivel'))

        cc.registrar_resultado(factory, state=state, resultado='ok')
        app.logger.info('Instagram reautorizado: conta=%s pagina=%s',
                        resumo.get('conta'), resumo.get('pagina'))
        return redirect(_retorno(canal, 'ok'))

    @app.route('/api/admin/instagram/desconectar', methods=['POST'])
    def instagram_desconectar():
        """Remove só o que ESTE fluxo gravou. Credencial vinda de variável
        de ambiente não é tocada — quem a definiu foi o painel do Render."""
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        conn = factory()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM credenciais_canal WHERE canal=%s', (meta_oauth.CANAL,))
                    removidas = cur.rowcount
            return jsonify(success=True, removidas=removidas,
                           aviso=('Credenciais definidas por variável de ambiente permanecem; '
                                  'remova-as no painel do Render se for a intenção.'))
        except Exception:
            app.logger.exception('Falha ao desconectar Instagram')
            return jsonify(success=False, error='Não foi possível desconectar.'), 503
        finally:
            conn.close()
