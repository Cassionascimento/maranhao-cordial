"""Rotas C6 sem importar main, abrir banco ou transporte durante importação.

Integração: C6Routes(get_db_connection, lambda: PRECO_UNITARIO).
Use os métodos como wrappers das quatro rotas existentes OU registrar_rotas_c6
num app sem essas rotas. Nunca registre ambas as alternativas.

webhook_verifier(request) deve retornar literalmente True após autenticação
homologada da entrada. Nenhum header/protocolo bancário é presumido aqui.
webhook_homologado=True sem verifier continua bloqueado. mTLS de saída não
autentica a entrada. Não usar finalizar_pedido_pago com cache legado obsoleto:
a transição financeira/logística já é persistida sob lock SQL.
"""
from decimal import Decimal
from urllib.parse import urlsplit

from flask import jsonify, request

from c6_pix import (C6Client, C6Error, iniciar_checkout, concluir_checkout,
                    extrair_txids, reconciliar_persistente, validar_txid)


STATUS = {'ATIVA', 'CONCLUIDA', 'REMOVIDA_PELO_USUARIO_RECEBEDOR', 'REMOVIDA_PELO_PSP'}


def erro(message, status):
    return jsonify(success=False, error=message), status


def resposta_publica(data, txid, code, amount):
    """Allowlist: nunca expõe devedor, chave, token, raw ou resposta inteira."""
    if not isinstance(data, dict) or data.get('txid') != txid or data.get('status') not in STATUS:
        raise C6Error('Resposta de cobrança inconsistente.')
    result = dict(success=True, order_code=code, c6_txid=txid,
                  amount=f'{Decimal(amount) / 100:.2f}', status=data['status'])
    location = data.get('location')
    if isinstance(location, str) and len(location) <= 2048:
        try:
            url = urlsplit(location)
            if url.scheme == 'https' and url.hostname and not (url.username or url.password or url.fragment):
                result['location'] = location
        except ValueError:
            pass
    return result


class C6Routes:
    def __init__(self, connection_factory, preco_unitario, *, client_factory=C6Client,
                 webhook_verifier=None, webhook_homologado=False):
        self.db = connection_factory
        self.preco = preco_unitario
        self.client_factory = client_factory
        self.webhook_verifier = webhook_verifier
        self.webhook_homologado = webhook_homologado

    def status_c6(self):
        try:
            status = self.client_factory().config.status()
            status['webhook_ready'] = self.webhook_homologado is True and callable(self.webhook_verifier)
            return jsonify(status), 200
        except Exception:
            return erro('C6 indisponível.', 503)

    def criar_checkout_c6(self):
        # Gate create=True ANTES de ler request/preço/banco ou mutar estado.
        try:
            client = self.client_factory()
            client.config.validate(create=True)
        except Exception:
            return erro('C6 indisponível.', 503)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return erro('Dados inválidos.', 400)
        try:
            raw = data.get('quantidade', 1)
            if isinstance(raw, bool) or not isinstance(raw, (int, str)):
                raise ValueError
            quantity = int(raw)
            if quantity < 1:
                raise ValueError
            fields = {}
            for field in ('endereco', 'cliente_email', 'cliente_nome', 'cliente_whatsapp'):
                value = data.get(field, '')
                if not isinstance(value, str):
                    raise ValueError
                fields[field] = value.strip()
            fields['cliente_email'] = fields['cliente_email'].lower()
            if not fields['endereco'] or not fields['cliente_email']:
                raise ValueError
        except (ValueError, TypeError):
            return erro('Quantidade, endereço ou e-mail inválido.', 400)
        try:
            # Mesmo preço em centavos do checkout legado; entrada não define valor.
            amount = self.preco() * quantity
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise ValueError
            pedido = dict(fields, quantity=quantity, address=fields['endereco'], amount=amount)
            reservation = iniciar_checkout(self.db, request.headers.get('Idempotency-Key'), pedido, pedido)
        except C6Error:
            return erro('Idempotency-Key inválido ou usado com dados diferentes.', 409)
        except Exception:
            return erro('Não foi possível persistir o pedido.', 503)
        code, txid = reservation['code'], reservation['txid']
        if not reservation['new']:
            # Nenhum segundo PUT após falha ambígua, concorrência ou reinício.
            if reservation.get('response'):
                try:
                    cached = reservation['response']
                    return jsonify(resposta_publica(dict(cached, txid=txid), txid, code, amount)), 200
                except Exception:
                    return erro('Resposta persistida inválida.', 503)
            return jsonify(success=True, pending=True, order_code=code, c6_txid=txid), 202
        payload = dict(calendario={'expiracao': 3600},
                       valor={'original': f'{Decimal(amount) / 100:.2f}', 'modalidadeAlteracao': 0},
                       chave=client.config.pix_key,
                       solicitacaoPagador=f'Maranhão Cordial - {code}',
                       infoAdicionais=[{'nome': 'pedido', 'valor': code},
                                       {'nome': 'quantidade', 'valor': str(quantity)}])
        try:
            data = client.criar(txid, payload)
            public = resposta_publica(data, txid, code, amount)
            reconciliar_persistente(txid, data, self.db)
            concluir_checkout(self.db, code, public)
            return jsonify(public), 201
        except Exception:
            return erro('Cobrança pendente de confirmação. Reutilize o mesmo Idempotency-Key.', 503)

    def _pedido(self, txid):
        validar_txid(txid)
        conn = self.db()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT codigo,valor_centavos FROM pedidos WHERE c6_txid=%s AND payment_origin=%s',
                                (txid, 'c6'))
                    rows = cur.fetchall()
                    return rows[0] if len(rows) == 1 else None
        finally:
            conn.close()

    def _consultar(self, txid, pedido):
        data = self.client_factory().consultar(txid)
        public = resposta_publica(data, txid, pedido[0], pedido[1])
        result = reconciliar_persistente(txid, data, self.db)
        if not result.get('found'):
            raise C6Error('Pedido não encontrado.')
        public['paid'] = result['paid']
        return public

    def consultar_cobranca_c6(self, txid):
        try:
            validar_txid(txid)
        except C6Error:
            return erro('TXID inválido.', 400)
        try:
            pedido = self._pedido(txid)
            if pedido is None:
                return erro('Pedido não encontrado.', 404)
            return jsonify(self._consultar(txid, pedido)), 200
        except Exception:
            return erro('Consulta C6 indisponível.', 503)

    def webhook_c6(self):
        if self.webhook_homologado is not True or not callable(self.webhook_verifier):
            return erro('Autenticação de entrada C6 não homologada.', 503)
        try:
            if self.webhook_verifier(request) is not True:
                return erro('Não autorizado.', 401)
        except Exception:
            return erro('Não autorizado.', 401)
        try:
            txids = extrair_txids(request.get_json(silent=True))
            if not txids:
                return erro('Webhook sem TXID.', 400)
        except C6Error:
            return erro('Webhook inválido.', 400)
        try:
            for txid in txids:
                pedido = self._pedido(txid)
                if pedido is not None:
                    self._consultar(txid, pedido)
            return jsonify(success=True), 200
        except Exception:
            # Banco pode repetir o lote: transições/auditoria são idempotentes.
            return erro('Confirmação C6 indisponível.', 503)


def registrar_rotas_c6(app, connection_factory, preco_unitario, **kwargs):
    routes = C6Routes(connection_factory, preco_unitario, **kwargs)
    specs = [('/api/c6/status', 'status_c6', ['GET']),
             ('/api/c6/pix/checkout', 'criar_checkout_c6', ['POST']),
             ('/api/c6/pix/<txid>', 'consultar_cobranca_c6', ['GET']),
             ('/webhooks/c6', 'webhook_c6', ['POST'])]
    existing = {rule.rule for rule in app.url_map.iter_rules()}
    if any(path in existing or name in app.view_functions for path, name, _ in specs):
        raise ValueError('Remova wrappers C6 existentes antes de registrar as rotas.')
    for path, name, methods in specs:
        app.add_url_rule(path, name, getattr(routes, name), methods=methods)
    return routes
