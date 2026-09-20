"""QR Codes rastreáveis: código -> origem -> avaliação -> Maranhão Intelligence -> contato opcional.

Não reconstrói CRM, painel nem Intelligence: usa o que já existe.

- **Sinais**: cada fato relevante vai para o barramento de mi_sinais via
  emitir(), depois do commit, sem nunca derrubar o fluxo da pessoa.
- **CRM**: contato entra em leads_crm, deduplicado por telefone/e-mail com
  crm_identidade (a mesma regra do WhatsApp: ambiguidade não é adivinhada).
- **Funil e conteúdo** ficam em tabelas próprias (migration 029), lidas pelo
  painel. Elas existem porque emitir() é observabilidade best-effort: um número
  que vai para investidor não pode depender de uma escrita que pode falhar
  em silêncio.

Regras que este módulo não abre mão:

1. O código impresso nunca muda; muda o destino.
2. Avaliação anônima não cria lead e não guarda IP, user-agent nem
   identificador de aparelho.
3. Consentimento de contato e de marketing são dois campos, com a versão do
   texto que a pessoa viu.
4. O painel só devolve o que existe. Sem dado, o valor é None — nunca zero
   travestido de medição — e todo agregado informa o tamanho da amostra.
5. Resposta pública para código inexistente, pausado ou revogado é a mesma:
   não dar pista a quem tenta adivinhar códigos.
"""
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg2.extras import Json, RealDictCursor

import crm_identidade as ci
from mi_sinais import emitir

BASE_PUBLICA = 'https://maranhaocordial.com.br'

# ---------------------------------------------------------------- códigos

# 31 símbolos, sem 0/o, 1/l/i: legível em papel e digitável sem ambiguidade.
ALFABETO = 'abcdefghjkmnpqrstuvwxyz23456789'
TAMANHO_CODIGO = 10
PADRAO_CODIGO = re.compile(r'[' + ALFABETO + r']{%d}' % TAMANHO_CODIGO)
PADRAO_SLUG = re.compile(r'[a-z][a-z0-9_]{2,63}')

FINALIDADES = ('avaliacao_feira', 'avaliacao_produto', 'comercial', 'divulgacao')
FINALIDADES_COM_AVALIACAO = ('avaliacao_feira', 'avaliacao_produto')
ESTADOS = ('ativo', 'pausado', 'revogado')
DESTINOS = ('pagina', 'redirecionar')

ERRO_PUBLICO = {'success': False, 'error': 'codigo_invalido'}

# ---------------------------------------------------------------- vocabulário

PERFIS = ('consumidor', 'bartender', 'bar_restaurante', 'distribuidor',
          'imprensa_influenciador', 'outro')
PERFIS_B2B = ('bartender', 'bar_restaurante', 'distribuidor')

APLICACOES = ('agua_com_gas', 'mocktail', 'drink_alcoolico', 'puro_com_gelo', 'cozinha', 'outra')
NIVEIS = ('baixo', 'ideal', 'alto')
ATRIBUTOS_SENSORIAIS = ('guarana', 'docura', 'acidez', 'gengibre', 'textura')
INTENCOES = ('certamente', 'provavelmente', 'talvez', 'nao')
INTENCOES_POSITIVAS = ('certamente', 'provavelmente')
FORMAS_USO = ('com_agua_com_gas', 'drinks_sem_alcool', 'drinks_com_alcool', 'cozinha', 'presente', 'outra')

# Teto que a pessoa pagaria por 200 mL, com os limites de cada faixa.
# `aceita_59` é DERIVADO daqui, no servidor: se o teto começa em R$59 ou mais,
# R$59 está dentro do que a pessoa aceita pagar. O navegador nunca informa o
# derivado — só a faixa — para o número não poder ser forjado.
FAIXAS_PRECO = {
    'ate_39': (0, 39),
    '40_49': (40, 49),
    '50_58': (50, 58),
    '59_69': (59, 69),
    '70_ou_mais': (70, None),
}
PRECO_REFERENCIA = 59


def aceita_preco_referencia(faixa):
    return FAIXAS_PRECO[faixa][0] >= PRECO_REFERENCIA


INTERESSES = ('comprar', 'servir', 'amostra', 'proposta', 'revenda', 'distribuicao', 'parceria')
INTERESSES_B2B = ('servir', 'proposta', 'revenda', 'distribuicao', 'parceria')
# Oportunidade = interesse comercial além do consumo. "Comprar" é contado à
# parte: é intenção de compra com contato, não oportunidade B2B.
INTERESSES_OPORTUNIDADE = ('servir', 'amostra', 'proposta', 'revenda', 'distribuicao', 'parceria')
ROTULO_INTERESSE = {
    'comprar': 'Comprar', 'servir': 'Servir', 'amostra': 'Amostra', 'proposta': 'Proposta',
    'revenda': 'Revenda', 'distribuicao': 'Distribuição', 'parceria': 'Parceria',
}

UFS = ('AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB',
       'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO')

# Textos que a pessoa vê. Ficam AQUI (e chegam à página pela configuração)
# para a versão gravada no banco ser sempre a do texto realmente exibido.
CONSENTIMENTO_VERSAO = 'qr-2026-09-v1'
TEXTO_CONSENTIMENTO_CONTATO = ('Autorizo a Maranhão Cordial a entrar em contato comigo '
                               'sobre este pedido, pelos dados que informei.')
TEXTO_CONSENTIMENTO_MARKETING = ('Quero receber novidades, lançamentos e ofertas da '
                                 'Maranhão Cordial. Posso cancelar quando quiser.')

# Abaixo disto, qualquer percentual é ruído. O painel mostra o número, mas
# avisa — e o texto não afirma tendência.
AMOSTRA_MINIMA = 30

# Teto por código, por minuto: barra enchente de requisições sem atrapalhar
# uma feira movimentada (um estande real fica muito abaixo disto).
LIMITE_POR_MINUTO = {'qr_scan': 600, 'avaliacao_iniciada': 300, 'avaliacao': 120, 'contato': 60}
LIMITE_CORPO_BYTES = 16384


class DadosInvalidos(ValueError):
    """Entrada recusada. `campo` diz qual, sem ecoar o valor recebido."""

    def __init__(self, campo):
        super().__init__(campo)
        self.campo = campo


class MuitasRequisicoes(RuntimeError):
    pass


# ---------------------------------------------------------------- utilidades

def gerar_codigo():
    return ''.join(secrets.choice(ALFABETO) for _ in range(TAMANHO_CODIGO))


def normalizar_codigo(codigo):
    if not isinstance(codigo, str):
        raise ValueError('codigo_invalido')
    limpo = codigo.strip().lower()
    if not PADRAO_CODIGO.fullmatch(limpo):
        raise ValueError('codigo_invalido')
    return limpo


def url_do_codigo(codigo_publico, base=BASE_PUBLICA):
    return base.rstrip('/') + '/q/' + codigo_publico


def _uuid(valor, campo):
    try:
        return str(UUID(str(valor)))
    except (ValueError, AttributeError, TypeError):
        raise DadosInvalidos(campo)


def _texto(valor, campo, *, minimo=0, maximo=200, obrigatorio=False):
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obrigatorio:
            raise DadosInvalidos(campo)
        return None
    if not isinstance(valor, str):
        raise DadosInvalidos(campo)
    # Remove caracteres de controle (exceto quebra de linha e tab) antes de medir.
    limpo = ''.join(c for c in valor if c in '\n\t' or ord(c) >= 32).strip()
    if len(limpo) < minimo or len(limpo) > maximo:
        raise DadosInvalidos(campo)
    return limpo


def _escolha(valor, campo, permitidos):
    if valor not in permitidos:
        raise DadosInvalidos(campo)
    return valor


def _agora():
    return datetime.now(timezone.utc)


def _pct(parte, total):
    return None if not total else round(100.0 * parte / total, 1)


def _com_amostra(dado, n):
    dado['n'] = n
    dado['amostra_pequena'] = n < AMOSTRA_MINIMA
    return dado


def validar_url_destino(url):
    """Só https, com host, sem credenciais embutidas. Quem define o destino
    é o administrador, mas um destino errado vira um redirecionamento público:
    melhor recusar aqui do que descobrir na feira."""
    if not isinstance(url, str) or not url.strip() or len(url) > 500:
        raise DadosInvalidos('destino_url')
    partes = urlsplit(url.strip())
    if partes.scheme != 'https' or not partes.hostname or partes.username or partes.password:
        raise DadosInvalidos('destino_url')
    return url.strip()


# ---------------------------------------------------------------- leitura de código

_COLUNAS_QR = ('id, codigo_publico, slug, nome, chamada, finalidade, origem, campanha, canal, posicao, '
               'sku, lote_id, unidade_id, destino_tipo, destino_url, estado, criado_em, atualizado_em')


def _qr_ativo(cur, codigo):
    """Código ativo ou None. Inexistente, pausado e revogado são
    indistinguíveis para quem chama."""
    cur.execute('SELECT ' + _COLUNAS_QR + ' FROM qr_codigos WHERE codigo_publico=%s AND estado=%s',
                (codigo, 'ativo'))
    return cur.fetchone()


def config_publica(qr):
    """O que a página precisa. Nenhum id interno, SKU, lote ou unidade."""
    opcoes = {
        'perfis': list(PERFIS), 'aplicacoes': list(APLICACOES), 'niveis': list(NIVEIS),
        'atributos': list(ATRIBUTOS_SENSORIAIS), 'intencoes': list(INTENCOES),
        'faixas_preco': list(FAIXAS_PRECO), 'formas_uso': list(FORMAS_USO),
        'interesses': list(INTERESSES), 'ufs': list(UFS),
    }
    return {
        'success': True,
        'qr': {
            'finalidade': qr['finalidade'], 'chamada': qr['chamada'], 'nome': qr['nome'],
            'destino_tipo': qr['destino_tipo'],
            'destino_url': qr['destino_url'] if qr['destino_tipo'] == 'redirecionar' else None,
            'tem_avaliacao': qr['finalidade'] in FINALIDADES_COM_AVALIACAO,
        },
        'opcoes': opcoes,
        'consentimento': {'versao': CONSENTIMENTO_VERSAO, 'contato': TEXTO_CONSENTIMENTO_CONTATO,
                          'marketing': TEXTO_CONSENTIMENTO_MARKETING},
    }


def _limite_excedido(cur, tabela, qr_id, tipo, chave_limite):
    """Conta as últimas linhas do próprio código. É um teto grosso, de propósito."""
    janela = _agora() - timedelta(seconds=60)
    if tabela == 'qr_eventos':
        cur.execute('SELECT count(*) AS n FROM qr_eventos WHERE qr_id=%s AND tipo=%s AND criado_em>=%s',
                    (qr_id, tipo, janela))
    else:
        cur.execute('SELECT count(*) AS n FROM ' + tabela + ' WHERE qr_id=%s AND criado_em>=%s',
                    (qr_id, janela))
    return cur.fetchone()['n'] >= LIMITE_POR_MINUTO[chave_limite]


def _emitir(factory, qr, tipo, discriminador, payload=None, origem_id=None, uf=None, cidade=None):
    """Sinal no barramento. Nunca propaga: emitir() já engole a falha, e aqui
    só montamos os campos. Sem PII: identifica o QR e o fato, não a pessoa."""
    campos = dict(natureza='fato', origem='qr', tipo_evento=tipo, canal=qr['canal'],
                  origem_id=origem_id or qr['slug'], discriminador=str(discriminador),
                  payload=payload or {})
    if qr.get('sku'):
        campos['sku'] = qr['sku']
    if qr.get('unidade_id'):
        campos['unidade_id'] = str(qr['unidade_id'])
    if qr.get('lote_id'):
        campos['lote_id'] = str(qr['lote_id'])
    if uf:
        campos['territorio_uf'] = uf
    if cidade:
        campos['territorio_cidade'] = cidade
    return emitir(factory, **campos)


def _payload_base(qr):
    return {'finalidade': qr['finalidade'], 'campanha': qr['campanha'], 'posicao': qr['posicao']}


# ---------------------------------------------------------------- scan e início

def _registrar_evento(factory, codigo, chave, tipo):
    """qr_scan e avaliacao_iniciada: uma linha por (código, tipo, chave)."""
    try:
        codigo = normalizar_codigo(codigo)
        chave = _uuid(chave, 'chave')
    except (ValueError, DadosInvalidos):
        return dict(ERRO_PUBLICO), 404
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                qr = _qr_ativo(cur, codigo)
                if not qr:
                    return dict(ERRO_PUBLICO), 404
                if _limite_excedido(cur, 'qr_eventos', qr['id'], tipo, tipo):
                    return {'success': False, 'error': 'muitas_tentativas'}, 429
                cur.execute('INSERT INTO qr_eventos(qr_id,tipo,chave) VALUES(%s,%s,%s) '
                            'ON CONFLICT (qr_id,tipo,chave) DO NOTHING RETURNING id', (qr['id'], tipo, chave))
                novo = cur.fetchone()
    finally:
        conn.close()
    if novo:
        _emitir(factory, qr, tipo, chave, _payload_base(qr))
    return {'success': True, 'duplicado': not novo}, 200


def registrar_scan(factory, codigo, chave):
    return _registrar_evento(factory, codigo, chave, 'qr_scan')


def registrar_inicio(factory, codigo, chave):
    return _registrar_evento(factory, codigo, chave, 'avaliacao_iniciada')


# ---------------------------------------------------------------- avaliação

def validar_avaliacao(corpo):
    if not isinstance(corpo, dict):
        raise DadosInvalidos('corpo')
    nota = corpo.get('nota')
    if isinstance(nota, bool) or not isinstance(nota, int) or not 0 <= nota <= 10:
        raise DadosInvalidos('nota')
    sensorial = corpo.get('sensorial')
    if not isinstance(sensorial, dict):
        raise DadosInvalidos('sensorial')
    dados = {
        'chave': _uuid(corpo.get('chave'), 'chave'),
        'perfil': _escolha(corpo.get('perfil'), 'perfil', PERFIS),
        'aplicacao': _escolha(corpo.get('aplicacao'), 'aplicacao', APLICACOES),
        'nota': nota,
        'intencao_compra': _escolha(corpo.get('intencao_compra'), 'intencao_compra', INTENCOES),
        'faixa_preco': _escolha(corpo.get('faixa_preco'), 'faixa_preco', tuple(FAIXAS_PRECO)),
        'comentario': _texto(corpo.get('comentario'), 'comentario', maximo=500),
    }
    for atributo in ATRIBUTOS_SENSORIAIS:
        dados[atributo] = _escolha(sensorial.get(atributo), atributo, NIVEIS)
    formas = corpo.get('formas_uso')
    if not isinstance(formas, list) or not 1 <= len(formas) <= len(FORMAS_USO):
        raise DadosInvalidos('formas_uso')
    for forma in formas:
        _escolha(forma, 'formas_uso', FORMAS_USO)
    dados['formas_uso'] = sorted(set(formas))
    dados['aceita_59'] = aceita_preco_referencia(dados['faixa_preco'])
    return dados


def registrar_avaliacao(factory, codigo, corpo):
    try:
        codigo = normalizar_codigo(codigo)
    except ValueError:
        return dict(ERRO_PUBLICO), 404
    try:
        dados = validar_avaliacao(corpo)
    except DadosInvalidos as erro:
        return {'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}, 400

    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                qr = _qr_ativo(cur, codigo)
                if not qr or qr['finalidade'] not in FINALIDADES_COM_AVALIACAO:
                    return dict(ERRO_PUBLICO), 404
                if _limite_excedido(cur, 'qr_avaliacoes', qr['id'], None, 'avaliacao'):
                    return {'success': False, 'error': 'muitas_tentativas'}, 429
                cur.execute(
                    'INSERT INTO qr_avaliacoes(id,qr_id,chave,perfil,aplicacao,nota,guarana,docura,acidez,'
                    'gengibre,textura,intencao_compra,faixa_preco,aceita_59,formas_uso,comentario) '
                    'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                    'ON CONFLICT (qr_id,chave) DO NOTHING RETURNING id',
                    (str(uuid4()), qr['id'], dados['chave'], dados['perfil'], dados['aplicacao'],
                     dados['nota'], dados['guarana'], dados['docura'], dados['acidez'],
                     dados['gengibre'], dados['textura'], dados['intencao_compra'],
                     dados['faixa_preco'], dados['aceita_59'], dados['formas_uso'], dados['comentario']))
                nova = cur.fetchone()
                # Uma avaliação concluída implica uma iniciada: sem isto, quem
                # concluiu sem passar pelo evento de início (rede ruim) faria a
                # conversão passar de 100%.
                cur.execute('INSERT INTO qr_eventos(qr_id,tipo,chave) VALUES(%s,%s,%s) '
                            'ON CONFLICT (qr_id,tipo,chave) DO NOTHING RETURNING id',
                            (qr['id'], 'avaliacao_iniciada', dados['chave']))
                inicio_novo = cur.fetchone()
    finally:
        conn.close()

    if not nova:
        return {'success': True, 'duplicada': True}, 200

    chave = dados['chave']
    base = _payload_base(qr)
    if inicio_novo:
        _emitir(factory, qr, 'avaliacao_iniciada', chave, base)
    _emitir(factory, qr, 'avaliacao_concluida', chave,
            dict(base, nota=dados['nota'], perfil=dados['perfil']))
    if dados['intencao_compra'] in INTENCOES_POSITIVAS:
        _emitir(factory, qr, 'intencao_compra', chave, dict(base, nivel=dados['intencao_compra']))
    if dados['aceita_59']:
        _emitir(factory, qr, 'preco_aceito', chave, dict(base, faixa=dados['faixa_preco']))
    return {'success': True, 'duplicada': False}, 201


# ---------------------------------------------------------------- contato

def normalizar_telefone(valor):
    """Só dígitos; 10-11 dígitos sem DDI viram +55 (Brasil), que é o formato
    que o WhatsApp entrega. Devolve (canônico, variantes_de_busca)."""
    if not isinstance(valor, str):
        return None, []
    digitos = re.sub(r'\D', '', valor)
    if len(digitos) in (10, 11):
        canonico = '55' + digitos
    elif 12 <= len(digitos) <= 15:
        canonico = digitos
    else:
        return None, []
    variantes = [canonico]
    # Cadastros antigos guardam o telefone sem o 55; procurar pelos dois evita
    # criar duplicata de quem já existe.
    if canonico.startswith('55') and len(canonico) in (12, 13):
        variantes.append(canonico[2:])
    return canonico, variantes


def validar_contato(corpo):
    if not isinstance(corpo, dict):
        raise DadosInvalidos('corpo')
    if corpo.get('consentimento_contato') is not True:
        raise DadosInvalidos('consentimento_contato')
    marketing = corpo.get('consentimento_marketing', False)
    if not isinstance(marketing, bool):
        raise DadosInvalidos('consentimento_marketing')

    whatsapp_bruto = _texto(corpo.get('whatsapp'), 'whatsapp', maximo=40)
    email_bruto = _texto(corpo.get('email'), 'email', maximo=220)
    if not whatsapp_bruto and not email_bruto:
        raise DadosInvalidos('contato')
    whatsapp, variantes = (None, [])
    if whatsapp_bruto:
        whatsapp, variantes = normalizar_telefone(whatsapp_bruto)
        if not whatsapp:
            raise DadosInvalidos('whatsapp')
    email = None
    if email_bruto:
        email = ci.normalizar(email_bruto, 'email')
        if not email:
            raise DadosInvalidos('email')

    uf = corpo.get('uf')
    if uf not in (None, ''):
        uf = _escolha(str(uf).upper(), 'uf', UFS)
    else:
        uf = None
    perfil = corpo.get('perfil')
    return {
        'chave': _uuid(corpo.get('chave'), 'chave'),
        'avaliacao_chave': _uuid(corpo['avaliacao_chave'], 'avaliacao_chave') if corpo.get('avaliacao_chave') else None,
        'nome': _texto(corpo.get('nome'), 'nome', minimo=2, maximo=120, obrigatorio=True),
        'whatsapp': whatsapp, 'variantes_telefone': variantes, 'email': email,
        'empresa': _texto(corpo.get('empresa'), 'empresa', maximo=160),
        'cidade': _texto(corpo.get('cidade'), 'cidade', maximo=100),
        'uf': uf,
        'interesse': _escolha(corpo.get('interesse'), 'interesse', INTERESSES),
        'perfil': _escolha(perfil, 'perfil', PERFIS) if perfil else None,
        'consentimento_marketing': marketing,
    }


def _resolver_lead(cur, dados):
    """(lead_id | None, pendente). Nunca escolhe entre dois candidatos."""
    achados, pendente = set(), False
    consultas = [(v, 'telefone') for v in dados['variantes_telefone']]
    if dados['email']:
        consultas.append((dados['email'], 'email'))
    for valor, tipo in consultas:
        try:
            lead = ci.resolver(cur, canal='qr', identificador=valor, tipo=tipo)
        except ci.IdentidadePendente:
            pendente = True
            continue
        if lead:
            achados.add(lead)
    if len(achados) > 1:
        return None, True
    return (next(iter(achados)) if achados else None), pendente


def _criar_lead(cur, qr, dados):
    lead_id = str(uuid4())
    b2b = dados['perfil'] in PERFIS_B2B or dados['interesse'] in INTERESSES_B2B
    contato = dados['whatsapp'] or dados['email']
    cur.execute(
        'INSERT INTO leads_crm(id,nome,empresa,tipo_lead,origem,canal,cidade,estado,contato,interesse,'
        'telefone,email,categoria_contato,observacoes) '
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'lead',%s)",
        (lead_id, dados['nome'][:180], (dados['empresa'] or None), 'b2b' if b2b else 'b2c',
         'evento' if qr['finalidade'] == 'avaliacao_feira' else 'outro',
         ('qr:' + qr['slug'])[:80], (dados['cidade'] or None), dados['uf'], contato[:220],
         ROTULO_INTERESSE[dados['interesse']], dados['whatsapp'], dados['email'],
         'Origem: QR %s (%s).' % (qr['slug'], qr['finalidade'])))
    return lead_id, b2b


def registrar_contato(factory, codigo, corpo):
    try:
        codigo = normalizar_codigo(codigo)
    except ValueError:
        return dict(ERRO_PUBLICO), 404
    try:
        dados = validar_contato(corpo)
    except DadosInvalidos as erro:
        return {'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}, 400

    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                qr = _qr_ativo(cur, codigo)
                if not qr:
                    return dict(ERRO_PUBLICO), 404
                if _limite_excedido(cur, 'qr_contatos', qr['id'], None, 'contato'):
                    return {'success': False, 'error': 'muitas_tentativas'}, 429
                cur.execute('SELECT id FROM qr_contatos WHERE qr_id=%s AND chave=%s',
                            (qr['id'], dados['chave']))
                if cur.fetchone():
                    return {'success': True, 'duplicado': True}, 200

                # Serializa por identificador: duas submissões simultâneas do
                # mesmo telefone não podem criar dois cadastros.
                for identificador in dados['variantes_telefone'][:1] + ([dados['email']] if dados['email'] else []):
                    cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('qr-contato:' + identificador,))

                lead_id, pendente = _resolver_lead(cur, dados)
                ja_existia = bool(lead_id)
                b2b = dados['perfil'] in PERFIS_B2B or dados['interesse'] in INTERESSES_B2B
                if not lead_id:
                    lead_id, b2b = _criar_lead(cur, qr, dados)
                else:
                    cur.execute('UPDATE leads_crm SET atualizado_em=NOW() WHERE id=%s', (lead_id,))

                # Vínculo de identidade; disputa por identificador vira revisão
                # humana, nunca sobrescrita.
                for valor, tipo in ([(dados['whatsapp'], 'telefone')] if dados['whatsapp'] else []) + \
                                   ([(dados['email'], 'email')] if dados['email'] else []):
                    cur.execute('SAVEPOINT vinculo_qr')
                    try:
                        ci.vincular(cur, lead_id=lead_id, canal='qr', identificador=valor, tipo=tipo)
                    except ci.IdentidadePendente:
                        cur.execute('ROLLBACK TO SAVEPOINT vinculo_qr')
                        pendente = True
                    cur.execute('RELEASE SAVEPOINT vinculo_qr')

                avaliacao_id = None
                if dados['avaliacao_chave']:
                    cur.execute('SELECT id FROM qr_avaliacoes WHERE qr_id=%s AND chave=%s',
                                (qr['id'], dados['avaliacao_chave']))
                    linha = cur.fetchone()
                    avaliacao_id = linha['id'] if linha else None

                cur.execute(
                    'INSERT INTO qr_contatos(id,qr_id,chave,avaliacao_id,lead_id,interesse,perfil,'
                    'consentimento_contato,consentimento_marketing,texto_consentimento_versao,'
                    'identidade_pendente,lead_ja_existia) VALUES(%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s)',
                    (str(uuid4()), qr['id'], dados['chave'], avaliacao_id, lead_id, dados['interesse'],
                     dados['perfil'], dados['consentimento_marketing'], CONSENTIMENTO_VERSAO,
                     pendente, ja_existia))
    finally:
        conn.close()

    base = _payload_base(qr)
    canais = [c for c, v in (('whatsapp', dados['whatsapp']), ('email', dados['email'])) if v]
    _emitir(factory, qr, 'contato_fornecido', dados['chave'],
            dict(base, canais=canais, marketing=dados['consentimento_marketing'],
                 interesse=dados['interesse']),
            origem_id=str(lead_id), uf=dados['uf'], cidade=dados['cidade'])
    _emitir(factory, qr, 'interesse_' + dados['interesse'], dados['chave'],
            dict(base, perfil=dados['perfil']), origem_id=str(lead_id), uf=dados['uf'])
    if b2b:
        _emitir(factory, qr, 'lead_b2b', dados['chave'],
                dict(base, interesse=dados['interesse'], perfil=dados['perfil']),
                origem_id=str(lead_id), uf=dados['uf'], cidade=dados['cidade'])
    return {'success': True, 'duplicado': False}, 201


# ---------------------------------------------------------------- administração

def _serializar_qr(linha, base=BASE_PUBLICA):
    saida = {k: (str(v) if k in ('id', 'lote_id', 'unidade_id') and v else v) for k, v in linha.items()}
    for k in ('criado_em', 'atualizado_em'):
        if saida.get(k):
            saida[k] = saida[k].isoformat()
    saida['url'] = url_do_codigo(linha['codigo_publico'], base)
    return saida


def listar_codigos(factory):
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT ' + _COLUNAS_QR + ' FROM qr_codigos ORDER BY criado_em, slug')
            return [_serializar_qr(l) for l in cur.fetchall()]
    finally:
        conn.close()


def _slug_de(nome):
    """'Feira São Paulo 2026' -> 'feira_sao_paulo_2026'."""
    sem_acento = ''.join(c for c in unicodedata.normalize('NFD', nome.lower()) if not unicodedata.combining(c))
    base = re.sub(r'[^a-z0-9]+', '_', sem_acento).strip('_')
    if not base or not base[0].isalpha():
        base = 'qr_' + base
    return base[:64]


def validar_criacao(corpo):
    if not isinstance(corpo, dict):
        raise DadosInvalidos('corpo')
    nome = _texto(corpo.get('nome'), 'nome', minimo=3, maximo=200, obrigatorio=True)
    slug = corpo.get('slug') or _slug_de(nome)
    if not isinstance(slug, str) or not PADRAO_SLUG.fullmatch(slug):
        raise DadosInvalidos('slug')
    destino_tipo = corpo.get('destino_tipo', 'pagina')
    _escolha(destino_tipo, 'destino_tipo', DESTINOS)
    destino_url = validar_url_destino(corpo.get('destino_url')) if destino_tipo == 'redirecionar' or corpo.get('destino_url') else None
    if destino_tipo == 'redirecionar' and not destino_url:
        raise DadosInvalidos('destino_url')
    dados = {
        'nome': nome, 'slug': slug,
        'chamada': _texto(corpo.get('chamada'), 'chamada', minimo=3, maximo=80, obrigatorio=True),
        'finalidade': _escolha(corpo.get('finalidade'), 'finalidade', FINALIDADES),
        'origem': _texto(corpo.get('origem'), 'origem', minimo=2, maximo=80, obrigatorio=True),
        'campanha': _texto(corpo.get('campanha'), 'campanha', maximo=120),
        'canal': _texto(corpo.get('canal'), 'canal', maximo=40) or 'qr',
        'posicao': _texto(corpo.get('posicao'), 'posicao', maximo=120),
        'sku': _texto(corpo.get('sku'), 'sku', maximo=60),
        'lote_id': _uuid(corpo['lote_id'], 'lote_id') if corpo.get('lote_id') else None,
        'unidade_id': _uuid(corpo['unidade_id'], 'unidade_id') if corpo.get('unidade_id') else None,
        'destino_tipo': destino_tipo, 'destino_url': destino_url,
    }
    return dados


def criar_codigo(factory, corpo):
    """Cria um QR novo. SKU, lote e unidade são conferidos AQUI: um vínculo
    inexistente faria todos os sinais desse QR falharem em silêncio."""
    from mi_skus import sku_existe
    from mi_lotes import lote_existe_por_id
    from mi_unidades import unidade_utilizavel
    try:
        dados = validar_criacao(corpo)
    except DadosInvalidos as erro:
        return {'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}, 400
    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    if dados['sku']:
                        dados['sku'] = sku_existe(cur, dados['sku'])
                    if dados['lote_id']:
                        lote_existe_por_id(cur, dados['lote_id'])
                    if dados['unidade_id']:
                        unidade_utilizavel(cur, dados['unidade_id'])
                except ValueError as erro:
                    return {'success': False, 'error': 'vinculo_invalido', 'campo': str(erro)}, 400
                cur.execute('SELECT 1 FROM qr_codigos WHERE slug=%s', (dados['slug'],))
                if cur.fetchone():
                    return {'success': False, 'error': 'slug_ja_existe'}, 409
                for _ in range(8):
                    codigo = gerar_codigo()
                    cur.execute('SAVEPOINT novo_codigo')
                    try:
                        cur.execute(
                            'INSERT INTO qr_codigos(codigo_publico,slug,nome,chamada,finalidade,origem,campanha,'
                            'canal,posicao,sku,lote_id,unidade_id,destino_tipo,destino_url) '
                            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING ' + _COLUNAS_QR,
                            (codigo, dados['slug'], dados['nome'], dados['chamada'], dados['finalidade'],
                             dados['origem'], dados['campanha'], dados['canal'], dados['posicao'],
                             dados['sku'], dados['lote_id'], dados['unidade_id'],
                             dados['destino_tipo'], dados['destino_url']))
                        criado = cur.fetchone()
                        cur.execute('RELEASE SAVEPOINT novo_codigo')
                        return {'success': True, 'qr': _serializar_qr(criado)}, 201
                    except Exception as erro:
                        if getattr(erro, 'pgcode', None) != '23505':
                            raise
                        # Colisão de código (improvável: ~8e14 combinações): sorteia outro.
                        cur.execute('ROLLBACK TO SAVEPOINT novo_codigo')
                return {'success': False, 'error': 'codigo_indisponivel'}, 503
    finally:
        conn.close()


_ATUALIZAVEIS = ('nome', 'chamada', 'campanha', 'posicao', 'destino_tipo', 'destino_url', 'estado')


def atualizar_codigo(factory, qr_id, corpo):
    """Altera o que pode mudar sem reimprimir. NÃO altera codigo_publico, slug
    nem finalidade: os dois primeiros estão impressos, e mudar a finalidade
    misturaria dois conjuntos de avaliação sob o mesmo código."""
    if not isinstance(corpo, dict):
        return {'success': False, 'error': 'dados_invalidos', 'campo': 'corpo'}, 400
    proibidos = set(corpo) - set(_ATUALIZAVEIS)
    if proibidos:
        return {'success': False, 'error': 'campo_nao_editavel', 'campo': sorted(proibidos)[0]}, 400
    try:
        qr_id = _uuid(qr_id, 'id')
        mudancas = {}
        if 'nome' in corpo:
            mudancas['nome'] = _texto(corpo['nome'], 'nome', minimo=3, maximo=200, obrigatorio=True)
        if 'chamada' in corpo:
            mudancas['chamada'] = _texto(corpo['chamada'], 'chamada', minimo=3, maximo=80, obrigatorio=True)
        for campo in ('campanha', 'posicao'):
            if campo in corpo:
                mudancas[campo] = _texto(corpo[campo], campo, maximo=120)
        if 'estado' in corpo:
            mudancas['estado'] = _escolha(corpo['estado'], 'estado', ESTADOS)
        if 'destino_tipo' in corpo:
            mudancas['destino_tipo'] = _escolha(corpo['destino_tipo'], 'destino_tipo', DESTINOS)
        if 'destino_url' in corpo:
            mudancas['destino_url'] = validar_url_destino(corpo['destino_url']) if corpo['destino_url'] else None
    except DadosInvalidos as erro:
        return {'success': False, 'error': 'dados_invalidos', 'campo': erro.campo}, 400
    if not mudancas:
        return {'success': False, 'error': 'nada_a_alterar'}, 400

    conn = factory()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT ' + _COLUNAS_QR + ' FROM qr_codigos WHERE id=%s FOR UPDATE', (qr_id,))
                atual = cur.fetchone()
                if not atual:
                    return {'success': False, 'error': 'nao_encontrado'}, 404
                if atual['estado'] == 'revogado':
                    return {'success': False, 'error': 'codigo_revogado_e_imutavel'}, 409
                final = dict(atual, **mudancas)
                if final['destino_tipo'] == 'redirecionar' and not final['destino_url']:
                    return {'success': False, 'error': 'dados_invalidos', 'campo': 'destino_url'}, 400
                sets = ', '.join(k + '=%s' for k in mudancas)
                cur.execute('UPDATE qr_codigos SET ' + sets + ', atualizado_em=NOW() WHERE id=%s RETURNING ' + _COLUNAS_QR,
                            list(mudancas.values()) + [qr_id])
                return {'success': True, 'qr': _serializar_qr(cur.fetchone())}, 200
    finally:
        conn.close()


def dados_para_arte(factory, qr_id):
    try:
        qr_id = _uuid(qr_id, 'id')
    except DadosInvalidos:
        return None
    conn = factory()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT slug, chamada, codigo_publico FROM qr_codigos WHERE id=%s', (qr_id,))
            return cur.fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------- painel (Maranhão Intelligence)

def _metricas(cur, filtro, params):
    """Nota, intenção e aceitação de R$59 sobre um recorte de avaliações."""
    cur.execute(
        'SELECT count(*) AS n, avg(a.nota)::float AS nota_media, '
        "count(*) FILTER (WHERE a.intencao_compra IN ('certamente','provavelmente')) AS intencao_positiva, "
        'count(*) FILTER (WHERE a.aceita_59) AS aceita_59 '
        'FROM qr_avaliacoes a JOIN qr_codigos q ON q.id=a.qr_id '
        'WHERE a.criado_em >= %(desde)s ' + filtro, params)
    r = cur.fetchone()
    n = r['n']
    return _com_amostra({
        'nota_media': round(r['nota_media'], 2) if r['nota_media'] is not None else None,
        'intencao_positiva': r['intencao_positiva'], 'pct_intencao_positiva': _pct(r['intencao_positiva'], n),
        'aceita_59': r['aceita_59'], 'pct_aceita_59': _pct(r['aceita_59'], n),
    }, n)


def painel(factory, dias=None):
    """Tudo o que a Intelligence mostra sobre QR, lido do que existe.

    Nada aqui é estimado: sem avaliação, a nota é None e a amostra é 0.
    `dias=None` significa todo o período.
    """
    desde = (_agora() - timedelta(days=dias)) if dias else datetime(1970, 1, 1, tzinfo=timezone.utc)
    params = {'desde': desde}
    conn = factory()
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT q.slug, q.nome, q.finalidade, q.origem, q.canal, q.posicao, q.estado,
                  COALESCE((SELECT count(*) FROM qr_eventos e WHERE e.qr_id=q.id AND e.tipo='qr_scan'
                            AND e.criado_em >= %(desde)s),0) AS scans,
                  COALESCE((SELECT count(*) FROM qr_eventos e WHERE e.qr_id=q.id AND e.tipo='avaliacao_iniciada'
                            AND e.criado_em >= %(desde)s),0) AS iniciadas,
                  COALESCE((SELECT count(*) FROM qr_avaliacoes a WHERE a.qr_id=q.id
                            AND a.criado_em >= %(desde)s),0) AS concluidas,
                  COALESCE((SELECT count(*) FROM qr_contatos c WHERE c.qr_id=q.id
                            AND c.criado_em >= %(desde)s),0) AS contatos,
                  COALESCE((SELECT count(DISTINCT c.lead_id) FROM qr_contatos c WHERE c.qr_id=q.id
                            AND c.lead_id IS NOT NULL AND c.criado_em >= %(desde)s),0) AS leads,
                  COALESCE((SELECT count(DISTINCT c.lead_id) FROM qr_contatos c WHERE c.qr_id=q.id
                            AND c.lead_id IS NOT NULL AND c.interesse = ANY(%(oportunidade)s)
                            AND c.criado_em >= %(desde)s),0) AS oportunidades
                FROM qr_codigos q ORDER BY q.criado_em, q.slug
            """, dict(params, oportunidade=list(INTERESSES_OPORTUNIDADE)))
            por_qr = []
            for l in cur.fetchall():
                l = dict(l)
                l['conversao_avaliacao'] = _pct(l['concluidas'], l['scans'])
                l['conversao_contato'] = _pct(l['contatos'], l['scans'])
                por_qr.append(l)

            por_origem = {}
            for l in por_qr:
                chave = (l['origem'], l['canal'])
                acc = por_origem.setdefault(chave, {'origem': l['origem'], 'canal': l['canal'], 'scans': 0,
                                                    'concluidas': 0, 'contatos': 0, 'leads': 0})
                for campo in ('scans', 'concluidas', 'contatos', 'leads'):
                    acc[campo] += l[campo]
            por_origem = list(por_origem.values())

            geral = _metricas(cur, '', params)
            cur.execute('SELECT a.nota, count(*) AS n FROM qr_avaliacoes a WHERE a.criado_em >= %(desde)s '
                        'GROUP BY a.nota ORDER BY a.nota', params)
            geral['distribuicao_notas'] = {str(l['nota']): l['n'] for l in cur.fetchall()}

            sensorial = {}
            for atributo in ATRIBUTOS_SENSORIAIS:
                cur.execute('SELECT a.' + atributo + ' AS nivel, count(*) AS n FROM qr_avaliacoes a '
                            'WHERE a.criado_em >= %(desde)s GROUP BY 1', params)
                contagem = {l['nivel']: l['n'] for l in cur.fetchall()}
                n = sum(contagem.values())
                sensorial[atributo] = _com_amostra(
                    {nivel: contagem.get(nivel, 0) for nivel in NIVEIS}, n)
                sensorial[atributo]['pct'] = {nivel: _pct(contagem.get(nivel, 0), n) for nivel in NIVEIS}

            cur.execute('SELECT a.intencao_compra AS chave, count(*) AS n FROM qr_avaliacoes a '
                        'WHERE a.criado_em >= %(desde)s GROUP BY 1', params)
            intencao = {l['chave']: l['n'] for l in cur.fetchall()}
            cur.execute('SELECT a.faixa_preco AS chave, count(*) AS n FROM qr_avaliacoes a '
                        'WHERE a.criado_em >= %(desde)s GROUP BY 1', params)
            preco = {l['chave']: l['n'] for l in cur.fetchall()}

            cur.execute('SELECT a.perfil, count(*) AS n, avg(a.nota)::float AS nota_media, '
                        "count(*) FILTER (WHERE a.intencao_compra IN ('certamente','provavelmente')) AS pos, "
                        'count(*) FILTER (WHERE a.aceita_59) AS aceita '
                        'FROM qr_avaliacoes a WHERE a.criado_em >= %(desde)s GROUP BY a.perfil ORDER BY n DESC', params)
            por_perfil = [_com_amostra({
                'perfil': l['perfil'],
                'nota_media': round(l['nota_media'], 2) if l['nota_media'] is not None else None,
                'pct_intencao_positiva': _pct(l['pos'], l['n']), 'pct_aceita_59': _pct(l['aceita'], l['n'])},
                l['n']) for l in cur.fetchall()]

            feira = _metricas(cur, "AND q.finalidade='avaliacao_feira'", params)
            externos = _metricas(cur, "AND q.finalidade<>'avaliacao_feira'", params)

            cur.execute('SELECT c.interesse, count(*) AS contatos, count(DISTINCT c.lead_id) AS leads '
                        'FROM qr_contatos c WHERE c.criado_em >= %(desde)s GROUP BY c.interesse', params)
            por_interesse = {l['interesse']: {'contatos': l['contatos'], 'leads': l['leads']} for l in cur.fetchall()}

            cur.execute("SELECT count(*) FILTER (WHERE identidade_pendente) AS pendentes, "
                        'count(*) FILTER (WHERE lead_ja_existia) AS ja_existiam, '
                        'count(*) FILTER (WHERE consentimento_marketing) AS marketing, count(*) AS total '
                        'FROM qr_contatos WHERE criado_em >= %(desde)s', params)
            c = cur.fetchone()

            cur.execute('SELECT a.comentario, a.nota, a.perfil, q.slug, a.criado_em '
                        'FROM qr_avaliacoes a JOIN qr_codigos q ON q.id=a.qr_id '
                        'WHERE a.comentario IS NOT NULL AND a.criado_em >= %(desde)s '
                        'ORDER BY a.criado_em DESC LIMIT 10', params)
            comentarios = [{'comentario': l['comentario'], 'nota': l['nota'], 'perfil': l['perfil'],
                            'qr': l['slug'], 'quando': l['criado_em'].isoformat()} for l in cur.fetchall()]
    finally:
        conn.close()

    return {
        'success': True,
        'periodo_dias': dias,
        'amostra_minima': AMOSTRA_MINIMA,
        'preco_referencia': PRECO_REFERENCIA,
        'por_qr': por_qr,
        'por_origem': por_origem,
        'avaliacoes': dict(geral, sensorial=sensorial,
                           intencao=_com_amostra({k: intencao.get(k, 0) for k in INTENCOES}, sum(intencao.values())),
                           faixa_preco=_com_amostra({k: preco.get(k, 0) for k in FAIXAS_PRECO}, sum(preco.values()))),
        'por_perfil': por_perfil,
        # "Externos" = tudo que não veio da feira (embalagem/produto, material e
        # digital). Não há base externa importada: só o que foi coletado por
        # QR, dito com esse nome para ninguém ler "mercado" onde é "outras origens".
        'comparacao': {'feira': feira, 'outras_origens': externos,
                       'descricao_outras_origens': 'Avaliações coletadas por QR fora da feira.'},
        'contatos': {'por_interesse': por_interesse, 'total': c['total'],
                     'com_marketing': c['marketing'], 'lead_ja_existia': c['ja_existiam'],
                     'identidade_pendente': c['pendentes']},
        'comentarios_recentes': comentarios,
    }


# ---------------------------------------------------------------- rotas

def registrar_rotas_qr(app, factory, autorizado, pasta_front):
    from flask import jsonify, make_response, request, send_from_directory

    def _corpo():
        if request.content_length and request.content_length > LIMITE_CORPO_BYTES:
            return None
        return request.get_json(silent=True)

    def _resposta(par):
        corpo, status = par
        resposta = jsonify(corpo)
        resposta.status_code = status
        resposta.headers['Cache-Control'] = 'no-store'
        return resposta

    @app.route('/q/<codigo>', methods=['GET'])
    def qr_pagina(codigo):
        # A mesma página serve qualquer código: a validade é decidida pela API,
        # então a página não vira um oráculo de códigos existentes.
        resposta = make_response(send_from_directory(pasta_front, 'qr.html'))
        resposta.headers['Cache-Control'] = 'no-cache'
        resposta.headers['X-Robots-Tag'] = 'noindex, nofollow'
        resposta.headers['Referrer-Policy'] = 'no-referrer'
        return resposta

    @app.route('/api/qr/<codigo>', methods=['GET'])
    def qr_config(codigo):
        try:
            codigo = normalizar_codigo(codigo)
        except ValueError:
            return _resposta((dict(ERRO_PUBLICO), 404))
        conn = factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                qr = _qr_ativo(cur, codigo)
        finally:
            conn.close()
        return _resposta((config_publica(qr), 200) if qr else (dict(ERRO_PUBLICO), 404))

    def _rota_publica(nome, funcao):
        def vista(codigo):
            corpo = _corpo()
            if corpo is None or not isinstance(corpo, dict):
                return _resposta(({'success': False, 'error': 'corpo_invalido'}, 400))
            # Isca: humano não preenche campo escondido. Responde como sucesso e
            # descarta, para o robô não saber que foi identificado.
            if corpo.get('website'):
                return _resposta(({'success': True}, 200))
            try:
                return _resposta(funcao(factory, codigo, corpo))
            except Exception:
                app.logger.exception('Falha em %s', nome)
                return _resposta(({'success': False, 'error': 'indisponivel'}, 503))
        vista.__name__ = 'qr_' + nome
        return vista

    app.add_url_rule('/api/qr/<codigo>/scan', view_func=_rota_publica(
        'scan', lambda f, c, b: registrar_scan(f, c, b.get('chave'))), methods=['POST'])
    app.add_url_rule('/api/qr/<codigo>/inicio', view_func=_rota_publica(
        'inicio', lambda f, c, b: registrar_inicio(f, c, b.get('chave'))), methods=['POST'])
    app.add_url_rule('/api/qr/<codigo>/avaliacao', view_func=_rota_publica(
        'avaliacao', registrar_avaliacao), methods=['POST'])
    app.add_url_rule('/api/qr/<codigo>/contato', view_func=_rota_publica(
        'contato', registrar_contato), methods=['POST'])

    # ------------------------------------------------ administração
    def _admin():
        if not autorizado():
            return jsonify(success=False, error='Não autorizado.'), 401
        return None

    @app.route('/api/admin/qr/codigos', methods=['GET'])
    def qr_admin_listar():
        negado = _admin()
        if negado:
            return negado
        return jsonify(success=True, codigos=listar_codigos(factory))

    @app.route('/api/admin/qr/codigos', methods=['POST'])
    def qr_admin_criar():
        negado = _admin()
        if negado:
            return negado
        return _resposta(criar_codigo(factory, request.get_json(silent=True)))

    @app.route('/api/admin/qr/codigos/<qr_id>', methods=['PATCH'])
    def qr_admin_atualizar(qr_id):
        negado = _admin()
        if negado:
            return negado
        return _resposta(atualizar_codigo(factory, qr_id, request.get_json(silent=True)))

    @app.route('/api/admin/qr/codigos/<qr_id>/arquivo', methods=['GET'])
    def qr_admin_arquivo(qr_id):
        negado = _admin()
        if negado:
            return negado
        import qr_arte
        formato = request.args.get('formato', 'png')
        if formato not in qr_arte.FORMATOS:
            return jsonify(success=False, error='formato_invalido'), 400
        dados = dados_para_arte(factory, qr_id)
        if not dados:
            return jsonify(success=False, error='nao_encontrado'), 404
        conteudo = qr_arte.gerar(formato, dados['chamada'], dados['codigo_publico'])
        resposta = make_response(conteudo)
        resposta.headers['Content-Type'] = qr_arte.TIPOS_MIME[formato]
        resposta.headers['Content-Disposition'] = 'attachment; filename="qr_%s.%s"' % (dados['slug'], formato)
        resposta.headers['Cache-Control'] = 'no-store'
        return resposta

    @app.route('/api/admin/qr/painel', methods=['GET'])
    def qr_admin_painel():
        negado = _admin()
        if negado:
            return negado
        dias = request.args.get('dias')
        try:
            dias = int(dias) if dias else None
            if dias is not None and not 1 <= dias <= 3650:
                raise ValueError
        except ValueError:
            return jsonify(success=False, error='dias_invalido'), 400
        try:
            return jsonify(painel(factory, dias))
        except Exception:
            app.logger.exception('Falha ao montar o painel de QR')
            return jsonify(success=False, error='Painel indisponível.'), 503
