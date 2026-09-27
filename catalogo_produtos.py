"""Catálogo de produtos da Maranhão: cadastro, publicação e vitrine.

A bebida (Maranhão Cordial) continua com seu próprio checkout e suas
próprias regras comerciais em compreaqui.html/c6_pix.py -- este módulo
NUNCA cria um checkout novo. O que ele faz é dar à administradora um
lugar para cadastrar, editar, publicar e despublicar produtos (a bebida
e os que vierem depois) sem programar, com o resultado aparecendo
automaticamente na página inicial e no catálogo.

Reaproveita mi_artefatos_blobs (migration 019) para os uploads de
imagem/vídeo -- mesmo BYTEA em Postgres já comprovado em produção,
nenhum storage externo novo. `url_externa` é a alternativa para mídia
que já é um arquivo publicado no site (ex.: a foto real da bebida em
img/hero/), sem duplicar bytes.

Modalidades de compra, por produto:
  - comprar_site: só quando já existe uma URL funcional de compra
    (url_compra obrigatório). Nunca aponta para um checkout que não
    existe.
  - orcamento: leva à solicitação de orçamento já existente
    (/cadastro-profissional), reaproveitada via query string -- nenhum
    formulário novo.
  - em_breve: informativo, sem nenhum caminho de pagamento.
"""
import re
import unicodedata
from datetime import datetime, timezone
from uuid import UUID, uuid4

from flask import jsonify, make_response, request, send_from_directory
from psycopg2.extras import RealDictCursor

CATEGORIA_PADRAO_MAXLEN = 60
NOME_MAXLEN = 160
DESCRICAO_CURTA_MAXLEN = 240
DESCRICAO_COMPLETA_MAXLEN = 4000
TEXTO_CURTO_MAXLEN = 120

PADRAO_SLUG = re.compile(r'[a-z][a-z0-9-]{1,78}[a-z0-9]')

MODALIDADES = ('comprar_site', 'orcamento', 'em_breve')
STATUS_VALIDOS = ('rascunho', 'publicado', 'em_breve')
STATUS_PUBLICOS = ('publicado', 'em_breve')
TIPOS_MIDIA = ('imagem', 'video')

MIME_IMAGEM = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
MIME_VIDEO = {'video/mp4': '.mp4'}
LIMITE_IMAGEM_BYTES = 8 * 1024 * 1024
LIMITE_VIDEO_BYTES = 40 * 1024 * 1024

CAMPOS_EDITAVEIS = (
    'nome', 'categoria', 'descricao_curta', 'descricao_completa', 'preco_centavos',
    'unidade_venda', 'quantidade_minima', 'multiplo_compra', 'modalidade_compra',
    'url_compra', 'disponibilidade', 'status', 'destaque_home', 'ordem_exibicao',
    'volume', 'peso', 'composicao', 'cuidados',
)
CAMPOS_NAO_EDITAVEIS = ('id', 'slug', 'criado_em', 'atualizado_em')


class DadosInvalidos(ValueError):
    """Entrada recusada. `campo` diz qual, sem ecoar o valor recebido."""

    def __init__(self, campo, mensagem=None):
        super().__init__(campo)
        self.campo = campo
        self.mensagem = mensagem


def _agora():
    return datetime.now(timezone.utc)


def slug_de(nome):
    sem_acento = ''.join(c for c in unicodedata.normalize('NFD', nome.lower()) if not unicodedata.combining(c))
    base = re.sub(r'[^a-z0-9]+', '-', sem_acento).strip('-')
    if not base or not base[0].isalpha():
        base = 'produto-' + base
    return base[:80].rstrip('-') or 'produto'


def _texto(valor, campo, *, minimo=1, maximo=200, obrigatorio=True, permitir_vazio=False):
    if valor is None:
        if obrigatorio and not permitir_vazio:
            raise DadosInvalidos(campo)
        return None if obrigatorio is False else ''
    if not isinstance(valor, str):
        raise DadosInvalidos(campo)
    limpo = valor.strip()
    if not limpo:
        if permitir_vazio:
            return ''
        if obrigatorio:
            raise DadosInvalidos(campo)
        return None
    if not (minimo <= len(limpo) <= maximo):
        raise DadosInvalidos(campo)
    return limpo


def _texto_opcional(valor, campo, maximo=200):
    if valor is None:
        return None
    return _texto(valor, campo, minimo=1, maximo=maximo, obrigatorio=False)


def _inteiro_positivo(valor, campo, padrao):
    if valor is None:
        return padrao
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise DadosInvalidos(campo)
    if valor < 1:
        raise DadosInvalidos(campo)
    return valor


def _preco_centavos(valor, campo='preco_centavos'):
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise DadosInvalidos(campo)
    if valor < 0:
        raise DadosInvalidos(campo)
    return valor


def _inteiro(valor, campo, padrao):
    if valor is None:
        return padrao
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise DadosInvalidos(campo)
    return valor


def _bool(valor, campo, padrao=False):
    if valor is None:
        return padrao
    if not isinstance(valor, bool):
        raise DadosInvalidos(campo)
    return valor


def validar_url_compra(valor):
    if not isinstance(valor, str) or not valor.strip():
        raise DadosInvalidos('url_compra')
    limpo = valor.strip()
    if limpo.startswith('/'):
        return limpo[:400]
    partes = re.match(r'^https://[^\s<>"\']+$', limpo)
    if not partes or '@' in limpo.split('//', 1)[1].split('/', 1)[0]:
        raise DadosInvalidos('url_compra')
    return limpo[:400]


def validar_criacao(corpo):
    if not isinstance(corpo, dict):
        raise DadosInvalidos('corpo')
    nome = _texto(corpo.get('nome'), 'nome', minimo=2, maximo=NOME_MAXLEN)
    slug = corpo.get('slug') or slug_de(nome)
    if not isinstance(slug, str) or not PADRAO_SLUG.fullmatch(slug):
        raise DadosInvalidos('slug')
    status = corpo.get('status', 'rascunho')
    if status not in STATUS_VALIDOS:
        raise DadosInvalidos('status')
    modalidade = corpo.get('modalidade_compra')
    if modalidade not in MODALIDADES:
        raise DadosInvalidos('modalidade_compra')
    url_compra = None
    if modalidade == 'comprar_site':
        url_compra = validar_url_compra(corpo.get('url_compra'))
    elif corpo.get('url_compra'):
        url_compra = validar_url_compra(corpo.get('url_compra'))
    return {
        'slug': slug,
        'nome': nome,
        'categoria': _texto(corpo.get('categoria'), 'categoria', minimo=2, maximo=CATEGORIA_PADRAO_MAXLEN),
        'descricao_curta': _texto(corpo.get('descricao_curta'), 'descricao_curta', minimo=3, maximo=DESCRICAO_CURTA_MAXLEN),
        'descricao_completa': _texto_opcional(corpo.get('descricao_completa'), 'descricao_completa', DESCRICAO_COMPLETA_MAXLEN),
        'preco_centavos': _preco_centavos(corpo.get('preco_centavos')),
        'unidade_venda': _texto(corpo.get('unidade_venda'), 'unidade_venda', minimo=1, maximo=60, obrigatorio=False) or 'unidade',
        'quantidade_minima': _inteiro_positivo(corpo.get('quantidade_minima'), 'quantidade_minima', 1),
        'multiplo_compra': _inteiro_positivo(corpo.get('multiplo_compra'), 'multiplo_compra', 1),
        'modalidade_compra': modalidade,
        'url_compra': url_compra,
        'disponibilidade': _texto_opcional(corpo.get('disponibilidade'), 'disponibilidade', TEXTO_CURTO_MAXLEN),
        'status': status,
        'destaque_home': _bool(corpo.get('destaque_home'), 'destaque_home', False),
        'ordem_exibicao': _inteiro(corpo.get('ordem_exibicao'), 'ordem_exibicao', 0),
        'volume': _texto_opcional(corpo.get('volume'), 'volume', TEXTO_CURTO_MAXLEN),
        'peso': _texto_opcional(corpo.get('peso'), 'peso', TEXTO_CURTO_MAXLEN),
        'composicao': _texto_opcional(corpo.get('composicao'), 'composicao', 400),
        'cuidados': _texto_opcional(corpo.get('cuidados'), 'cuidados', 400),
    }


def validar_atualizacao(corpo, estado_atual):
    """`estado_atual` (dict já validado do registro) é usado para checar a
    consistência de modalidade_compra/url_compra quando só um dos dois
    campos vem no PATCH."""
    if not isinstance(corpo, dict):
        raise DadosInvalidos('corpo')
    for campo in corpo:
        if campo in CAMPOS_NAO_EDITAVEIS:
            raise DadosInvalidos('campo_nao_editavel')
        if campo not in CAMPOS_EDITAVEIS:
            raise DadosInvalidos('campo_desconhecido')

    saida = {}
    if 'nome' in corpo:
        saida['nome'] = _texto(corpo['nome'], 'nome', minimo=2, maximo=NOME_MAXLEN)
    if 'categoria' in corpo:
        saida['categoria'] = _texto(corpo['categoria'], 'categoria', minimo=2, maximo=CATEGORIA_PADRAO_MAXLEN)
    if 'descricao_curta' in corpo:
        saida['descricao_curta'] = _texto(corpo['descricao_curta'], 'descricao_curta', minimo=3, maximo=DESCRICAO_CURTA_MAXLEN)
    if 'descricao_completa' in corpo:
        saida['descricao_completa'] = _texto_opcional(corpo['descricao_completa'], 'descricao_completa', DESCRICAO_COMPLETA_MAXLEN)
    if 'preco_centavos' in corpo:
        saida['preco_centavos'] = _preco_centavos(corpo['preco_centavos'])
    if 'unidade_venda' in corpo:
        saida['unidade_venda'] = _texto(corpo['unidade_venda'], 'unidade_venda', minimo=1, maximo=60)
    if 'quantidade_minima' in corpo:
        saida['quantidade_minima'] = _inteiro_positivo(corpo['quantidade_minima'], 'quantidade_minima', 1)
    if 'multiplo_compra' in corpo:
        saida['multiplo_compra'] = _inteiro_positivo(corpo['multiplo_compra'], 'multiplo_compra', 1)
    if 'destaque_home' in corpo:
        saida['destaque_home'] = _bool(corpo['destaque_home'], 'destaque_home')
    if 'ordem_exibicao' in corpo:
        saida['ordem_exibicao'] = _inteiro(corpo['ordem_exibicao'], 'ordem_exibicao', 0)
    if 'status' in corpo:
        if corpo['status'] not in STATUS_VALIDOS:
            raise DadosInvalidos('status')
        saida['status'] = corpo['status']
    for campo, maximo in (('disponibilidade', TEXTO_CURTO_MAXLEN), ('volume', TEXTO_CURTO_MAXLEN),
                          ('peso', TEXTO_CURTO_MAXLEN), ('composicao', 400), ('cuidados', 400)):
        if campo in corpo:
            saida[campo] = _texto_opcional(corpo[campo], campo, maximo)

    modalidade_final = corpo.get('modalidade_compra', estado_atual['modalidade_compra'])
    if 'modalidade_compra' in corpo:
        if modalidade_final not in MODALIDADES:
            raise DadosInvalidos('modalidade_compra')
        saida['modalidade_compra'] = modalidade_final
    url_compra_final = estado_atual.get('url_compra')
    if 'url_compra' in corpo:
        bruto = corpo['url_compra']
        url_compra_final = validar_url_compra(bruto) if bruto else None
        saida['url_compra'] = url_compra_final
    if modalidade_final == 'comprar_site' and not url_compra_final:
        raise DadosInvalidos('url_compra')
    return saida


# ------------------------------------------------------------------ domínio

_COLUNAS_PRODUTO = (
    'id, slug, nome, categoria, descricao_curta, descricao_completa, preco_centavos, '
    'unidade_venda, quantidade_minima, multiplo_compra, modalidade_compra, url_compra, '
    'disponibilidade, status, destaque_home, ordem_exibicao, volume, peso, composicao, '
    'cuidados, criado_em, atualizado_em'
)


def _midias_do_produto(cur, produto_id):
    cur.execute(
        'SELECT id, tipo, blob_id, url_externa, alt_text, capa, ordem FROM catalogo_produto_midias '
        'WHERE produto_id=%s ORDER BY capa DESC, ordem, criado_em', (str(produto_id),))
    saida = []
    for m in cur.fetchall():
        url = m['url_externa'] or ('/api/catalogo/midia/' + str(m['blob_id']))
        saida.append({'id': str(m['id']), 'tipo': m['tipo'], 'url': url, 'alt_text': m['alt_text'],
                      'capa': m['capa'], 'ordem': m['ordem']})
    return saida


def _serializar(produto, midias=None, admin=False):
    saida = {
        'slug': produto['slug'], 'nome': produto['nome'], 'categoria': produto['categoria'],
        'descricao_curta': produto['descricao_curta'], 'preco_centavos': produto['preco_centavos'],
        'unidade_venda': produto['unidade_venda'], 'quantidade_minima': produto['quantidade_minima'],
        'multiplo_compra': produto['multiplo_compra'], 'modalidade_compra': produto['modalidade_compra'],
        'url_compra': produto['url_compra'] if produto['modalidade_compra'] == 'comprar_site' else None,
        'disponibilidade': produto['disponibilidade'], 'status': produto['status'],
        'destaque_home': produto['destaque_home'], 'ordem_exibicao': produto['ordem_exibicao'],
        'volume': produto['volume'], 'peso': produto['peso'], 'composicao': produto['composicao'],
        'cuidados': produto['cuidados'], 'descricao_completa': produto['descricao_completa'],
        'midias': midias or [],
    }
    if admin:
        saida['id'] = str(produto['id'])
        saida['criado_em'] = produto['criado_em'].isoformat()
        saida['atualizado_em'] = produto['atualizado_em'].isoformat()
    return saida


def listar_publicos(factory):
    conn = factory()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                'SELECT ' + _COLUNAS_PRODUTO + ' FROM catalogo_produtos WHERE status = ANY(%s) '
                'ORDER BY destaque_home DESC, ordem_exibicao, nome', (list(STATUS_PUBLICOS),))
            produtos = cur.fetchall()
            saida = []
            for p in produtos:
                midias = _midias_do_produto(cur, p['id'])
                item = _serializar(p, midias)
                del item['descricao_completa']  # lista fica leve; detalhe vem no GET por slug
                saida.append(item)
            return saida
    finally:
        conn.close()


def buscar_publico(factory, slug):
    conn = factory()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT ' + _COLUNAS_PRODUTO + ' FROM catalogo_produtos WHERE slug=%s AND status = ANY(%s)',
                        (slug, list(STATUS_PUBLICOS)))
            p = cur.fetchone()
            if not p:
                return None
            return _serializar(p, _midias_do_produto(cur, p['id']))
    finally:
        conn.close()


def buscar_midia_publica(factory, blob_id):
    """`blob_id` é o id que a própria URL pública carrega (ver
    `_midias_do_produto`: a URL é montada com blob_id, não com o id da
    linha de catalogo_produto_midias)."""
    try:
        UUID(str(blob_id))
    except (ValueError, AttributeError):
        return None
    conn = factory()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                'SELECT b.conteudo, b.mime_type FROM mi_artefatos_blobs b '
                'JOIN catalogo_produto_midias m ON m.blob_id = b.id '
                'JOIN catalogo_produtos p ON p.id = m.produto_id '
                "WHERE b.id=%s AND p.status <> 'rascunho'", (str(blob_id),))
            row = cur.fetchone()
            if not row:
                return None
            return bytes(row['conteudo']), row['mime_type']
    finally:
        conn.close()


def listar_admin(factory):
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT ' + _COLUNAS_PRODUTO + ' FROM catalogo_produtos ORDER BY ordem_exibicao, nome')
            saida = []
            for p in cur.fetchall():
                saida.append(_serializar(p, _midias_do_produto(cur, p['id']), admin=True))
            return saida
    finally:
        conn.close()


def buscar_admin(cur, produto_id):
    cur.execute('SELECT ' + _COLUNAS_PRODUTO + ' FROM catalogo_produtos WHERE id=%s', (str(produto_id),))
    return cur.fetchone()


def criar_produto(factory, corpo):
    dados = validar_criacao(corpo)
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT 1 FROM catalogo_produtos WHERE slug=%s', (dados['slug'],))
                if cur.fetchone():
                    return {'success': False, 'error': 'slug_em_uso'}, 409
                novo_id = str(uuid4())
                colunas = list(dados.keys())
                cur.execute(
                    'INSERT INTO catalogo_produtos (id, ' + ', '.join(colunas) + ') VALUES (%s, ' +
                    ', '.join(['%s'] * len(colunas)) + ') RETURNING ' + _COLUNAS_PRODUTO,
                    [novo_id] + [dados[c] for c in colunas])
                produto = cur.fetchone()
        return {'success': True, 'produto': _serializar(produto, [], admin=True)}, 201
    finally:
        conn.close()


def atualizar_produto(factory, produto_id, corpo):
    try:
        UUID(str(produto_id))
    except (ValueError, AttributeError):
        return {'success': False, 'error': 'produto_nao_encontrado'}, 404
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                atual = buscar_admin(cur, produto_id)
                if not atual:
                    return {'success': False, 'error': 'produto_nao_encontrado'}, 404
                dados = validar_atualizacao(corpo, atual)
                if not dados:
                    return {'success': True, 'produto': _serializar(atual, _midias_do_produto(cur, atual['id']), admin=True)}, 200
                sets = ', '.join(f'{c}=%s' for c in dados) + ', atualizado_em=NOW()'
                cur.execute('UPDATE catalogo_produtos SET ' + sets + ' WHERE id=%s RETURNING ' + _COLUNAS_PRODUTO,
                            list(dados.values()) + [str(produto_id)])
                produto = cur.fetchone()
                midias = _midias_do_produto(cur, produto['id'])
        return {'success': True, 'produto': _serializar(produto, midias, admin=True)}, 200
    finally:
        conn.close()


def listar_categorias(factory):
    conn = factory()
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute('SELECT DISTINCT categoria FROM catalogo_produtos ORDER BY categoria')
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _mime_valido(tipo, mimetype):
    tabela = MIME_IMAGEM if tipo == 'imagem' else MIME_VIDEO
    return mimetype in tabela


def adicionar_midia(factory, produto_id, arquivo, tipo, alt_text, capa, ordem):
    if tipo not in TIPOS_MIDIA:
        raise DadosInvalidos('tipo')
    if arquivo is None:
        raise DadosInvalidos('arquivo')
    mimetype = (arquivo.mimetype or '').lower()
    if not _mime_valido(tipo, mimetype):
        raise DadosInvalidos('arquivo_formato')
    conteudo = arquivo.read()
    limite = LIMITE_IMAGEM_BYTES if tipo == 'imagem' else LIMITE_VIDEO_BYTES
    if not conteudo or len(conteudo) > limite:
        raise DadosInvalidos('arquivo_tamanho')
    alt_text = _texto(alt_text, 'alt_text', minimo=1, maximo=240, obrigatorio=(tipo == 'imagem'), permitir_vazio=(tipo == 'video')) or ''

    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT id FROM catalogo_produtos WHERE id=%s', (str(produto_id),))
                if not cur.fetchone():
                    return {'success': False, 'error': 'produto_nao_encontrado'}, 404
                from psycopg2 import Binary
                blob_id = str(uuid4())
                cur.execute('INSERT INTO mi_artefatos_blobs (id, conteudo, mime_type, tamanho_bytes) VALUES (%s,%s,%s,%s)',
                            (blob_id, Binary(conteudo), mimetype, len(conteudo)))
                if capa:
                    cur.execute('UPDATE catalogo_produto_midias SET capa=FALSE WHERE produto_id=%s', (str(produto_id),))
                midia_id = str(uuid4())
                cur.execute(
                    'INSERT INTO catalogo_produto_midias (id, produto_id, tipo, blob_id, alt_text, capa, ordem) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (midia_id, str(produto_id), tipo, blob_id, alt_text, capa, ordem))
                cur.execute('UPDATE catalogo_produtos SET atualizado_em=NOW() WHERE id=%s', (str(produto_id),))
        return {'success': True, 'midia': {'id': midia_id, 'tipo': tipo, 'url': '/api/catalogo/midia/' + blob_id,
                                            'alt_text': alt_text, 'capa': capa, 'ordem': ordem}}, 201
    finally:
        conn.close()


def remover_midia(factory, produto_id, midia_id):
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT blob_id FROM catalogo_produto_midias WHERE id=%s AND produto_id=%s',
                            (str(midia_id), str(produto_id)))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'error': 'midia_nao_encontrada'}, 404
                cur.execute('DELETE FROM catalogo_produto_midias WHERE id=%s', (str(midia_id),))
                if row['blob_id']:
                    cur.execute('DELETE FROM mi_artefatos_blobs WHERE id=%s', (row['blob_id'],))
        return {'success': True}, 200
    finally:
        conn.close()


# ------------------------------------------------------------------ rotas

def registrar_rotas_catalogo(app, factory, autorizado, pasta_front):
    def _resposta(resultado):
        corpo, status = resultado
        return jsonify(corpo), status

    def _corpo_json(limite=32768):
        if request.content_length and request.content_length > limite:
            return None
        return request.get_json(silent=True)

    # -------------------------------------------------------------- público

    @app.route('/api/catalogo/produtos', methods=['GET'])
    def catalogo_listar_publico():
        return jsonify({'success': True, 'produtos': listar_publicos(factory)})

    @app.route('/api/catalogo/produtos/<slug>', methods=['GET'])
    def catalogo_buscar_publico(slug):
        produto = buscar_publico(factory, slug.strip().lower()[:100])
        if not produto:
            return jsonify({'success': False, 'error': 'produto_nao_encontrado'}), 404
        return jsonify({'success': True, 'produto': produto})

    @app.route('/api/catalogo/midia/<midia_id>', methods=['GET'])
    def catalogo_midia(midia_id):
        achado = buscar_midia_publica(factory, midia_id)
        if not achado:
            return jsonify({'success': False, 'error': 'midia_nao_encontrada'}), 404
        conteudo, mime_type = achado
        resposta = make_response(conteudo)
        resposta.headers['Content-Type'] = mime_type
        resposta.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resposta

    @app.route('/produto/<slug>', methods=['GET'])
    def catalogo_pagina_produto(slug):
        resposta = make_response(send_from_directory(pasta_front, 'produto.html'))
        resposta.headers['Cache-Control'] = 'no-cache'
        return resposta

    # --------------------------------------------------------------- admin

    @app.route('/api/admin/catalogo/categorias', methods=['GET'])
    def catalogo_admin_categorias():
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        return jsonify({'success': True, 'categorias': listar_categorias(factory)})

    @app.route('/api/admin/catalogo/produtos', methods=['GET'])
    def catalogo_admin_listar():
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        return jsonify({'success': True, 'produtos': listar_admin(factory)})

    @app.route('/api/admin/catalogo/produtos', methods=['POST'])
    def catalogo_admin_criar():
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        try:
            return _resposta(criar_produto(factory, _corpo_json()))
        except DadosInvalidos as erro:
            return jsonify({'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}), 400

    @app.route('/api/admin/catalogo/produtos/<produto_id>', methods=['PATCH'])
    def catalogo_admin_atualizar(produto_id):
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        try:
            return _resposta(atualizar_produto(factory, produto_id, _corpo_json()))
        except DadosInvalidos as erro:
            return jsonify({'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}), 400

    @app.route('/api/admin/catalogo/produtos/<produto_id>/midias', methods=['POST'])
    def catalogo_admin_upload_midia(produto_id):
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        try:
            tipo = (request.form.get('tipo') or 'imagem').strip().lower()
            capa = (request.form.get('capa') or '').strip().lower() == 'true'
            ordem_bruta = request.form.get('ordem', '0')
            ordem = int(ordem_bruta) if str(ordem_bruta).lstrip('-').isdigit() else 0
            return _resposta(adicionar_midia(factory, produto_id, request.files.get('arquivo'), tipo,
                                             request.form.get('alt_text'), capa, ordem))
        except DadosInvalidos as erro:
            return jsonify({'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}), 400

    @app.route('/api/admin/catalogo/produtos/<produto_id>/midias/<midia_id>', methods=['DELETE'])
    def catalogo_admin_remover_midia(produto_id, midia_id):
        if not autorizado():
            return jsonify({'success': False, 'error': 'nao_autorizado'}), 401
        return _resposta(remover_midia(factory, produto_id, midia_id))
