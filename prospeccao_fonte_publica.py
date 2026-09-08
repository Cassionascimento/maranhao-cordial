"""Verificação conservadora da associação empresarial, antes de reservar cota."""
import html
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urljoin

import certifi
import urllib3


def pagina_publica(url):
    """HTTPS público, IP fixado por conexão, sem cookies/credenciais/retries."""
    for _ in range(3):
        u = urlsplit(url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
            raise ValueError('fonte_invalida')
        hosts = {r[4][0] for r in socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)}
        if not hosts or any(not ipaddress.ip_address(ip).is_global for ip in hosts):
            raise ValueError('fonte_nao_publica')
        with urllib3.HTTPSConnectionPool(
            sorted(hosts)[0], port=443, server_hostname=u.hostname,
            assert_hostname=u.hostname, cert_reqs='CERT_REQUIRED',
            ca_certs=certifi.where(), timeout=urllib3.Timeout(connect=5, read=10),
        ) as pool:
            r = pool.urlopen('GET', u.path or '/', headers={'Host': u.hostname},
                             retries=False, redirect=False, preload_content=False)
            try:
                if r.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, r.headers.get('Location', ''))
                    continue
                if r.status != 200 or 'text/html' not in r.headers.get('Content-Type', ''):
                    raise ValueError('fonte_indisponivel')
                body = r.read(524289)
                if len(body) > 524288:
                    raise ValueError('fonte_excede_limite')
                return url, body.decode('utf-8', errors='replace')
            finally:
                r.close()
    raise ValueError('redirecionamentos_excedidos')


def validar_associacao(email, fonte_url, fetch=pagina_publica):
    """Sem evidência suficiente é exclusão normal; nunca autoriza envio."""
    email = str(email or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9._+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', email):
        return False, 'sem_email_comercial_valido'
    dominio = email.split('@')[1]
    if dominio in ('site.com.br', 'example.com', 'exemplo.com.br', 'email.com'):
        return False, 'endereco_de_exemplo'
    try:
        url, texto = fetch(fonte_url)
        host = (urlsplit(url).hostname or '').lower().removeprefix('www.')
        if host != dominio and not host.endswith('.' + dominio):
            return False, 'associacao_dominio_nao_confirmada'
        # Não considerar dados em scripts ou comentários como contato publicado.
        texto = re.sub(r'<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>', '', texto,
                       flags=re.I | re.S)
        enderecos = set(re.findall(r'[a-z0-9._+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', html.unescape(texto).lower()))
        if email not in enderecos:
            return False, 'email_nao_publicado_na_fonte'
        return True, url
    except Exception:
        return False, 'fonte_nao_verificavel_nesta_rodada'
