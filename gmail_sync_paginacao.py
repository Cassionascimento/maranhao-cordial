"""Seleção Gmail limitada, retomável e sem transporte de saída.

Requer migration 004. O cursor só avança após confirmação do importador;
falha/crash repete a página, com deduplicação e reconciliação já existentes.
"""
from contextlib import contextmanager
import re
import requests

LOCK = 5702003
MAX_MENSAGENS = 20
MAX_PAGINAS = 5
MAX_PENDENTES = 5
URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages'


class Lote:
    def __init__(self, conn):
        self.conn = conn
        self.mensagens = []
        self.page_token = None
        self.paginas = 0
        self.ocupado = False

    def confirmar(self):
        if self.ocupado:
            return
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute('UPDATE gmail_sync_cursor SET page_token=%s,atualizado_em=NOW() WHERE id=1',
                            (self.page_token,))


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('Gmail ID inválido')
    return value


@contextmanager
def selecionar_lote(factory, access_token, limite=20, http=requests):
    limite = max(1, min(int(limite), MAX_MENSAGENS))
    conn = factory()
    lote = Lote(conn)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,))
            lote.ocupado = not cur.fetchone()[0]
            if not lote.ocupado:
                cur.execute('SELECT page_token FROM gmail_sync_cursor WHERE id=1')
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError('Cursor Gmail não instalado')
                lote.page_token = row[0]
                # Retoma inclusive entrada antiga fora da inbox/página atual.
                # Técnicas não são candidatas à interpretação comercial.
                cur.execute('''SELECT i.message_id FROM interacoes_omnichannel i
                    LEFT JOIN gmail_processamentos_seguros g ON g.interacao_id=i.id
                    WHERE i.canal='gmail' AND i.tipo_interacao='email'
                      AND i.processado_ia=FALSE AND i.message_id IS NOT NULL
                    ORDER BY COALESCE(g.atualizado_em,i.criado_em),i.id LIMIT %s''',
                            (min(MAX_PENDENTES, limite),))
                lote.mensagens = [{'id': _id(row[0])} for row in cur.fetchall()]
        conn.commit()
        if lote.ocupado:
            yield lote
            return
        vistos = {item['id'] for item in lote.mensagens}
        tokens = set()
        reiniciado = False
        while len(lote.mensagens) < limite and lote.paginas < MAX_PAGINAS:
            token = lote.page_token
            params = {'maxResults': limite - len(lote.mensagens), 'q': 'in:inbox'}
            if token:
                params['pageToken'] = token
            resposta = http.get(URL, headers={'Authorization': 'Bearer ' + access_token},
                                params=params, timeout=30, allow_redirects=False)
            lote.paginas += 1
            # Token expirado não aprisiona a varredura. No máximo um reinício.
            if resposta.status_code == 400 and token and not reiniciado:
                lote.page_token = None
                reiniciado = True
                tokens.clear()
                continue
            resposta.raise_for_status()
            data = resposta.json()
            items = data.get('messages', []) if isinstance(data, dict) else None
            if not isinstance(items, list) or len(items) > params['maxResults']:
                raise ValueError('Página Gmail inválida')
            ids = [_id(item.get('id') if isinstance(item, dict) else None) for item in items]
            with conn.cursor() as cur:
                cur.execute('''SELECT message_id FROM interacoes_omnichannel
                    WHERE canal='gmail' AND processado_ia=TRUE AND message_id=ANY(%s)''', (ids,))
                concluidos = {row[0] for row in cur.fetchall()}
            for mid in ids:
                if mid not in vistos and mid not in concluidos:
                    lote.mensagens.append({'id': mid})
                    vistos.add(mid)
            proximo = data.get('nextPageToken')
            if proximo is not None and (not isinstance(proximo, str) or not proximo or len(proximo) > 8192):
                raise ValueError('Cursor Gmail inválido')
            if proximo and (proximo == token or proximo in tokens):
                raise ValueError('Cursor Gmail repetido')
            if token:
                tokens.add(token)
            lote.page_token = proximo
            if not proximo:
                break
        yield lote
    finally:
        # Libera o lock de sessão em sucesso, falha e crash da conexão.
        conn.close()
