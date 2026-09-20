"""Guarda de credenciais de canal: cifrada, durável e nunca legível no painel.

A aplicação não consegue escrever variáveis de ambiente no Render. Sem um
lugar durável, uma reautorização feita pelo ADM se perderia no próximo
deploy. Este módulo dá esse lugar — com três regras que não se negociam:

1. **Nada em texto puro.** O segredo entra e sai por Fernet (AES-128-CBC +
   HMAC-SHA256). A chave vive fora do banco.
2. **O painel nunca decifra.** `metadados` carrega o que a tela precisa
   (conta, escopos, validade); só quem vai chamar a API pede o segredo.
3. **Sem chave, não grava.** Se não houver material de chave configurado,
   `salvar` recusa em vez de degradar para texto puro — perder uma
   autorização é melhor que vazá-la.

Precedência da leitura: variável de ambiente primeiro, banco depois. Assim
uma credencial já configurada no Render continua mandando, e o banco só
entra onde o ambiente não tem resposta.
"""
import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from psycopg2.extras import Json, RealDictCursor

JANELA_ESTADO_MINUTOS = 10


class ChaveIndisponivel(RuntimeError):
    """Sem material de chave: gravar em texto puro não é alternativa."""


class EstadoOAuthInvalido(ValueError):
    """State desconhecido, expirado ou já consumido."""


def _material_de_chave(env=None):
    """CANAIS_CRYPTO_KEY é o caminho correto.

    FLASK_SECRET_KEY serve de origem derivada para não exigir configuração
    nova no primeiro uso — mas só quando está REALMENTE no ambiente. O
    padrão da aplicação é `secrets.token_hex(32)` gerado a cada boot; se
    derivássemos daquilo, todo deploy tornaria ilegível o que foi gravado
    antes.
    """
    env = os.environ if env is None else env
    direta = env.get('CANAIS_CRYPTO_KEY')
    if direta:
        return ('CANAIS_CRYPTO_KEY', direta)
    derivada = env.get('FLASK_SECRET_KEY')
    if derivada:
        return ('FLASK_SECRET_KEY', derivada)
    return (None, None)


def _fernet(env=None):
    from cryptography.fernet import Fernet
    origem, material = _material_de_chave(env)
    if not material:
        raise ChaveIndisponivel(
            'Defina CANAIS_CRYPTO_KEY para guardar credenciais de canal com segurança.')
    # HKDF simples com rótulo fixo: a mesma variável pode servir a outros
    # usos sem compartilhar a chave efetiva.
    bruto = hashlib.pbkdf2_hmac('sha256', material.encode(), b'maranhao-cordial:canais:v1', 200_000)
    return Fernet(base64.urlsafe_b64encode(bruto))


def chave_configurada(env=None):
    """Para o painel dizer o motivo antes de a pessoa tentar autorizar."""
    origem, _ = _material_de_chave(env)
    return origem


def _hash(valor):
    return hashlib.sha256(str(valor).encode()).hexdigest()


# =====================================================
# ESTADO OAUTH (CSRF + callback idempotente)
# =====================================================

def criar_estado(factory, *, canal, navegador, redirect_uri):
    """Gera o `state` e guarda só o hash dele.

    O valor devolvido vai para a URL de autorização; o banco nunca o vê em
    claro, então um vazamento de banco não permite forjar um callback.
    """
    state = secrets.token_urlsafe(32)
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO oauth_estados_canal(state_hash,canal,navegador_hash,redirect_uri) '
                    'VALUES(%s,%s,%s,%s)',
                    (_hash(state), canal, _hash(navegador or ''), redirect_uri))
    finally:
        conn.close()
    return state


def consumir_estado(factory, *, canal, state, navegador):
    """Valida e queima o state. Uso único, janela de 10 minutos.

    Um callback repetido (usuário recarrega a aba, a plataforma reenvia)
    encontra o estado já consumido e recebe `EstadoOAuthInvalido` com
    `ja_consumido=True` — quem chama trata como idempotente em vez de
    refazer a troca de código.
    """
    if not state or not canal:
        raise EstadoOAuthInvalido('estado_ausente')
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    'SELECT canal,navegador_hash,redirect_uri,consumido_em,criado_em,resultado '
                    'FROM oauth_estados_canal WHERE state_hash=%s FOR UPDATE', (_hash(state),))
                linha = cur.fetchone()
                if not linha:
                    raise EstadoOAuthInvalido('estado_desconhecido')
                if linha['canal'] != canal:
                    raise EstadoOAuthInvalido('estado_de_outro_canal')
                if linha['consumido_em'] is not None:
                    erro = EstadoOAuthInvalido('estado_ja_consumido')
                    erro.ja_consumido = True
                    erro.resultado = linha['resultado']
                    raise erro
                limite = datetime.now(timezone.utc) - timedelta(minutes=JANELA_ESTADO_MINUTOS)
                if linha['criado_em'] and linha['criado_em'] < limite:
                    raise EstadoOAuthInvalido('estado_expirado')
                if linha['navegador_hash'] != _hash(navegador or ''):
                    raise EstadoOAuthInvalido('navegador_diferente')
                cur.execute('UPDATE oauth_estados_canal SET consumido_em=NOW() WHERE state_hash=%s',
                            (_hash(state),))
                return {'redirect_uri': linha['redirect_uri']}
    finally:
        conn.close()


def registrar_resultado(factory, *, state, resultado):
    """Marca o desfecho, para um callback repetido saber o que já houve."""
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute('UPDATE oauth_estados_canal SET resultado=%s WHERE state_hash=%s',
                            (str(resultado)[:80], _hash(state)))
    finally:
        conn.close()


# =====================================================
# CREDENCIAIS
# =====================================================

def salvar(factory, *, canal, nome, segredo, metadados=None, expira_em=None, ator=None, env=None):
    """Grava cifrado. Sem chave, recusa — nunca degrada para texto puro."""
    if not isinstance(segredo, str) or not segredo.strip():
        raise ValueError('segredo_vazio')
    cifrado = _fernet(env).encrypt(segredo.encode())
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO credenciais_canal(canal,nome,segredo_cifrado,metadados,expira_em,atualizado_por)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (canal,nome) DO UPDATE SET
                        segredo_cifrado=EXCLUDED.segredo_cifrado,
                        metadados=EXCLUDED.metadados,
                        expira_em=EXCLUDED.expira_em,
                        atualizado_por=EXCLUDED.atualizado_por,
                        atualizado_em=NOW()
                """, (canal, nome, cifrado, Json(metadados or {}), expira_em,
                      str(ator or 'oauth')[:220]))
    finally:
        conn.close()
    return True


def ler(factory, *, canal, nome, env=None):
    """Segredo em claro, só para quem vai chamar a API do canal.

    Variável de ambiente tem precedência: uma credencial já configurada no
    Render continua mandando, e o banco só responde onde o ambiente cala.
    """
    env = os.environ if env is None else env
    do_ambiente = env.get(nome)
    if do_ambiente:
        return do_ambiente
    conn = factory()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT segredo_cifrado FROM credenciais_canal WHERE canal=%s AND nome=%s',
                        (canal, nome))
            linha = cur.fetchone()
            if not linha:
                return None
            try:
                return _fernet(env).decrypt(bytes(linha[0])).decode()
            except ChaveIndisponivel:
                raise
            except Exception:
                # Chave trocada ou envelope corrompido: tratar como ausente é
                # melhor que devolver lixo para a API do canal.
                return None
    finally:
        conn.close()


def descrever(factory, *, canal, env=None):
    """O que o painel pode mostrar: metadados, validade e origem.

    Nunca decifra. Existe para o cartão dizer "conta conectada" e "expira
    em" sem que o segredo saia do banco.
    """
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT nome,metadados,expira_em,atualizado_em,atualizado_por '
                        'FROM credenciais_canal WHERE canal=%s ORDER BY nome', (canal,))
            return [{'nome': l['nome'], 'metadados': l['metadados'] or {},
                     'expira_em': l['expira_em'].isoformat() if l['expira_em'] else None,
                     'atualizado_em': l['atualizado_em'].isoformat() if l['atualizado_em'] else None,
                     'atualizado_por': l['atualizado_por']}
                    for l in (cur.fetchall() or [])]
    finally:
        conn.close()


def ambiente_com_banco(factory, canal, nomes, env=None):
    """Env sobreposto pelas credenciais guardadas.

    Serve ao diagnóstico: ele continua lendo `env`, sem saber que parte da
    resposta veio do banco. Falha de leitura nunca derruba o diagnóstico.
    """
    env = os.environ if env is None else env
    combinado = dict(env)
    for nome in nomes:
        if combinado.get(nome):
            continue
        try:
            valor = ler(factory, canal=canal, nome=nome, env={})
        except Exception:
            valor = None
        if valor:
            combinado[nome] = valor
    return combinado


def limpar_estados_antigos(factory, horas=24):
    """Higiene: estado velho não serve para nada e não deve acumular."""
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM oauth_estados_canal WHERE criado_em < NOW() - make_interval(hours => %s)",
                            (int(horas),))
                return cur.rowcount
    finally:
        conn.close()
