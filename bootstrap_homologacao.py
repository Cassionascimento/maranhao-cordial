"""Wrapper fail-closed para bootstrap de homologação -- importa `main.py`
SOMENTE quando há certeza de que o banco alvo é isolado de produção.

Este script NÃO cria banco, NÃO aplica migration, NÃO configura Render,
NÃO inicia servidor (nunca chama `app.run()`/`socketio.run()`), NÃO inicia
job (nunca importa `mi_conselho_job`), e NÃO altera `main.py` nem nenhum
outro arquivo -- só valida o ambiente e, se tudo passar, seta
`DATABASE_URL` internamente (só nesta execução do processo, nunca no
ambiente real do usuário) e importa `main.py`, deixando o bootstrap de
schema já existente rodar (auditado antes desta implementação: só
`CREATE TABLE`/registro de rota dormente, nenhuma chamada externa).

Fail-closed em cada etapa: qualquer validação que falhar aborta
imediatamente, com uma mensagem curta e genérica -- nunca usuário, senha
ou a URL completa -- e nunca prossegue parcialmente.
"""
import os
import sys
from urllib.parse import urlsplit

VAR_HOMOLOG = 'DATABASE_URL_HOMOLOG'
VAR_PRODUCAO = 'DATABASE_URL'
VAR_CONFIRMACAO = 'HOMOLOGACAO_CONFIRMAR'
VALOR_CONFIRMACAO_ESPERADO = 'EU_CONFIRM0_BANCO_ISOLADO'

MARCADORES_PRODUCAO = ('prod', 'production')
MARCADORES_SEGUROS = ('homolog', 'staging')

ESQUEMAS_POSTGRES_VALIDOS = ('postgres', 'postgresql', 'postgresql+psycopg2')


class BootstrapRecusado(RuntimeError):
    """Levantada sempre que uma validação fail-closed falha. A mensagem
    (o `str()` da exceção) é sempre um código curto -- nunca contém
    usuário, senha, host ou a URL completa."""


def _nome_banco(url):
    """Extrai e valida o nome do banco de uma URL de conexão Postgres.
    Nunca inclui a URL/credenciais na mensagem de erro."""
    if not isinstance(url, str) or not url.strip():
        raise BootstrapRecusado('database_url_homolog_ausente')
    partes = urlsplit(url.strip())
    if partes.scheme.lower() not in ESQUEMAS_POSTGRES_VALIDOS:
        raise BootstrapRecusado('url_invalida_esquema_nao_postgres')
    if not partes.hostname:
        raise BootstrapRecusado('url_invalida_sem_host')
    nome = (partes.path or '').lstrip('/').split('/')[0]
    if not nome:
        raise BootstrapRecusado('nome_de_banco_nao_identificavel')
    return nome


def _validar_identidade_homologacao(nome_banco):
    """Não confia só na env var: exige marcador positivo de homologação
    no PRÓPRIO nome do banco, e recusa sempre se houver marcador de
    produção -- mesmo que um marcador seguro também apareça."""
    nome_lower = nome_banco.lower()
    if any(marcador in nome_lower for marcador in MARCADORES_PRODUCAO):
        raise BootstrapRecusado('nome_de_banco_parece_producao')
    if not any(marcador in nome_lower for marcador in MARCADORES_SEGUROS):
        raise BootstrapRecusado('nome_de_banco_sem_marcador_de_homologacao')


def _validar_ambiente():
    """Todas as recusas fail-closed, nesta ordem. Devolve a URL de
    homologação já validada -- só depois de passar por tudo."""
    if os.getenv(VAR_PRODUCAO):
        raise BootstrapRecusado('database_url_de_producao_definida')

    url_homolog = os.getenv(VAR_HOMOLOG)
    if not url_homolog or not url_homolog.strip():
        raise BootstrapRecusado('database_url_homolog_ausente')

    nome_banco = _nome_banco(url_homolog)
    _validar_identidade_homologacao(nome_banco)

    if os.getenv(VAR_CONFIRMACAO) != VALOR_CONFIRMACAO_ESPERADO:
        raise BootstrapRecusado('confirmacao_ausente_ou_incorreta')

    return url_homolog


def _importar_main():
    import main  # noqa: F401 -- só dispara o bootstrap de schema já existente, auditado


def executar(importador=None):
    """`importador` é injetável só para teste -- os testes NUNCA importam
    `main.py` de verdade. Em execução real, usa `_importar_main`."""
    importador = importador or _importar_main
    url_homolog = _validar_ambiente()
    os.environ[VAR_PRODUCAO] = url_homolog
    importador()
    return {'success': True}


if __name__ == '__main__':
    try:
        executar()
        print('Homologação: bootstrap concluído.')
    except BootstrapRecusado as recusa:
        print(f'Homologação recusada: {recusa}')
        sys.exit(1)
    except Exception as erro:
        print(f'Homologação abortada: {type(erro).__name__}')
        sys.exit(1)
