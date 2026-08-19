from flask import Flask, send_from_directory, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import os
import json
import io
import uuid
import re
import unicodedata
import requests
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from pypdf import PdfReader

# =====================================================
# CONFIGURAÇÃO
# =====================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

CONTEXTO_MARANHAO = """
Maranhão Cordial é um concentrado premium não alcoólico de guaraná e gengibre,
apresentado em garrafa de 200 mL.

É utilizado em pequenas doses para preparo de bebidas e outras aplicações
gastronômicas.

Pode ser combinado com água com gás, água tônica, vodka, cachaça, café e
outras preparações.

O produto foi desenvolvido com foco em padronização, praticidade de bancada
e experiência sensorial.

A Maranhão Cordial atende consumidores pelo site oficial
maranhaocordial.com.br e possui atendimento profissional B2B para bares,
restaurantes, hotéis, bartenders, mixologistas e distribuidores.

A empresa não possui lojas físicas próprias.

Quando não houver informação oficial suficiente para responder uma pergunta,
não invente. Informe que o atendimento pode orientar o cliente.
"""


# =====================================================
# IA — RESPOSTAS RÁPIDAS E INTELIGÊNCIA EMPRESARIAL
# =====================================================

RESPOSTAS_RAPIDAS_MARANHAO = {
    "o_que_e": (
        "Maranhão Cordial é um concentrado premium não alcoólico "
        "de guaraná e gengibre, desenvolvido para preparar e "
        "padronizar bebidas em pequenas doses."
    ),

    "o_que_faz": (
        "Maranhão Cordial concentra sabor, aroma e acidez em uma "
        "pequena dose, facilitando o preparo e a padronização de bebidas."
    ),

    "para_que_serve": (
        "Maranhão Cordial é usado no preparo de bebidas e aplicações "
        "gastronômicas, com foco em praticidade, padronização e experiência sensorial."
    ),

    "como_usar": (
        "Use em pequenas doses e ajuste conforme a preparação. "
        "Pode ser combinado com água com gás, tônica, café e diferentes destilados."
    ),

    "onde_comprar": (
        "A compra oficial pode ser realizada em maranhaocordial.com.br. "
        "A Maranhão Cordial não possui lojas físicas próprias."
    )
}


USOS_PUBLICOS_VALIDADOS = """
USOS E COMBINAÇÕES QUE PODEM SER INFORMADOS PUBLICAMENTE:

- preparo de bebidas em pequenas doses;
- água com gás;
- água tônica;
- vodka;
- cachaça;
- café;
- coquetéis e bebidas não alcoólicas quando derivados dessas combinações.

REGRAS OBRIGATÓRIAS:

Não apresente como uso validado nenhuma aplicação específica fora desta lista.

Não sugira espontaneamente:
molhos,
marinadas,
sobremesas,
minibar,
drinks prontos,
receitas culinárias,
redução de custos,
redução de erros,
ganhos de produtividade,
ou qualquer outro benefício não documentado.

A expressão "aplicações gastronômicas" é genérica e NÃO autoriza
a criação de exemplos específicos.

Se perguntarem sobre uma aplicação que não esteja nesta lista,
responda que ela pode ser estudada ou validada tecnicamente,
mas não a apresente como uso confirmado.
"""


def normalizar_texto_publico(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return texto.lower()


def limpar_resposta_publica(texto):
    texto = str(texto or "").strip()

    # Corrige espaços depois de pontuação
    texto = re.sub(r",(?=\S)", ", ", texto)
    texto = re.sub(r"\.(?=\S)", ". ", texto)
    texto = re.sub(r";(?=\S)", "; ", texto)

    # Remove excesso de espaços e quebras
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)

    return texto.strip()


def validar_resposta_publica(mensagem, resposta):
    texto = normalizar_texto_publico(resposta)
    pergunta = normalizar_texto_publico(mensagem)

    termos_bloqueados = [
        "molho",
        "marinada",
        "sobremesa",
        "minibar",
        "pronto para servir",
        "prontos para servir",
        "pronta para servir",
        "prontas para servir",
        "reduz erros",
        "reducao de erros",
        "reduz custos",
        "reducao de custos",
        "ganho de produtividade",
        "ganhos de produtividade",
        "receita para",
        "receitas para",
        "aplicacoes na cozinha",
        "aplicacao na cozinha",
        "rapidez e consistencia",
        "reduzindo tempo",
        "reduzindo erros"
    ]

    if not any(
        termo in texto
        for termo in termos_bloqueados
    ):
        return resposta.strip()

    print(
        "RESPOSTA IA BLOQUEADA POR VALIDACAO:",
        resposta
    )

    if "restaurante" in pergunta:
        return (
            "O Maranhão Cordial pode ampliar a carta de bebidas "
            "com preparações em pequenas doses e combinações com "
            "água com gás, água tônica, vodka, cachaça e café. "
            "Outras aplicações gastronômicas precisam ser "
            "avaliadas e validadas antes de serem recomendadas."
        )

    if "hotel" in pergunta:
        return (
            "O Maranhão Cordial pode integrar a carta de bebidas "
            "do hotel em preparações com água com gás, tônica, "
            "vodka, cachaça e café. Outras aplicações podem ser "
            "avaliadas conforme a proposta do estabelecimento."
        )

    if "bar" in pergunta:
        return (
            "O Maranhão Cordial pode ser utilizado em pequenas "
            "doses no preparo de bebidas com água com gás, tônica, "
            "vodka e cachaça. Aplicações adicionais devem ser "
            "avaliadas antes de serem apresentadas como uso validado."
        )

    return (
        "Maranhão Cordial é um concentrado premium não alcoólico "
        "de guaraná e gengibre para preparo de bebidas em pequenas "
        "doses. Para usos não previstos na base oficial, a aplicação "
        "precisa ser avaliada antes de ser recomendada."
    )


HIERARQUIA_DECISAO_EMPRESARIAL = """
MODELO DE RACIOCÍNIO DA DIREÇÃO — MARANHÃO CORDIAL

A análise empresarial deve sempre distinguir três horizontes:

1. ESTRATÉGICO — LONGO PRAZO
Pergunta central: para onde a Maranhão Cordial está indo?

O nível estratégico protege:
- posicionamento premium;
- construção da marca como assinatura brasileira;
- transformação do produto em elemento de identidade e criação;
- fortalecimento de vantagem competitiva;
- construção de mercado B2B;
- expansão coerente sem banalização ou massificação da marca;
- coerência entre origem brasileira, linguagem contemporânea e projeção internacional.

A estratégia NÃO deve ser alterada automaticamente por sinais pontuais,
pedidos isolados ou conveniências operacionais de curto prazo.

2. TÁTICO — MÉDIO PRAZO
Pergunta central: quais projetos aproximam a empresa da estratégia?

O nível tático pode envolver:
- desenvolvimento e qualificação de canais B2B;
- relacionamento com bartenders, mixologistas, restaurantes e hotéis;
- eventos e degustações;
- desenvolvimento comercial;
- materiais profissionais;
- parcerias;
- experimentação de mercado;
- validação de produto;
- distribuição;
- marketing;
- construção da experiência Maranhão;
- uso de ativos culturais e musicais quando coerente com a marca.

Toda iniciativa tática deve estar ligada a uma finalidade estratégica clara.

3. OPERACIONAL — CURTO PRAZO
Pergunta central: o que precisa ser executado agora?

O nível operacional envolve, por exemplo:
- responder contatos;
- acompanhar pedidos;
- organizar leads;
- preparar follow-ups;
- verificar pendências;
- falar com fornecedores ou fabricantes;
- organizar documentação;
- acompanhar degustações;
- registrar informações;
- resolver tarefas rotineiras.

Toda recomendação operacional deve, quando possível,
estar ligada a uma prioridade tática e estratégica.

REGRA DE HIERARQUIA:

ESTRATÉGIA → TÁTICA → OPERAÇÃO.

O operacional não deve comandar automaticamente a estratégia.

Se surgir uma oportunidade de curto prazo que conflite com o posicionamento,
a IA deve apontar o conflito antes de recomendar sua execução.

Ao responder perguntas como:
"O que devo priorizar hoje?",
"Qual oportunidade devo perseguir?",
"O que faço agora?",
a IA deve considerar:

1. qual objetivo estratégico está em jogo;
2. qual frente tática está mais relevante ou bloqueada;
3. qual ação operacional gera maior avanço agora.

REGRAS DE QUALIDADE DA DECISÃO:

- Separar fatos observados de hipóteses.
- Separar metas oficiais de metas sugeridas.
- Nunca apresentar número inventado como meta oficial.
- Quando sugerir número, prazo, quantidade ou KPI sem histórico,
  rotular explicitamente como "sugestão" ou "hipótese".
- Não transformar interesse comercial em capacidade técnica comprovada.
- Não transformar hipótese de mercado em fato.
- Não transformar aplicação possível em uso técnico validado.
- Respeitar sempre validações regulatórias, técnicas e do responsável técnico.
"""


CONTEXTO_EMPRESARIAL_INTERNO = """
INFORMAÇÕES INTERNAS PARA RACIOCÍNIO EMPRESARIAL.

A Maranhão Cordial busca desenvolver mercado B2B com bares,
restaurantes, hotéis, bartenders, mixologistas, eventos,
distribuidores e operações de hospitalidade.

O produto pode ser analisado comercialmente como ingrediente,
ferramenta de padronização de serviço e elemento de experiência
de marca e identidade cultural.

A marca possui o projeto musical GINGA — Five Moments.

O álbum possui cinco faixas:
Black Ginga;
Rhythm of That Look;
Quimbara Cumba;
Maranhão en el Alma;
Maranhão Cordial.

O projeto musical pode ser considerado como ativo de experiência
de marca na identificação de oportunidades envolvendo hotelaria,
bares, gastronomia, turismo, eventos, ambientação e ativações culturais.

A IA pode utilizar informações empresariais internas para analisar
oportunidades, qualificar leads e apoiar prospecção.

Informações classificadas como internas não devem ser reveladas
automaticamente ao consumidor final.

Nunca revele segredos, credenciais, chaves de API, dados bancários,
dados pessoais, fórmulas confidenciais, custos internos ou informações
estratégicas protegidas.
"""


def resposta_rapida_maranhao(mensagem):
    texto = mensagem.strip().lower()

    regras = [
        (
            [
                "o que é o maranhão cordial",
                "o que e o maranhao cordial"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["o_que_e"]
        ),
        (
            [
                "o que esse produto faz",
                "o que o produto faz",
                "o que faz esse produto"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["o_que_faz"]
        ),
        (
            ["para que serve"],
            RESPOSTAS_RAPIDAS_MARANHAO["para_que_serve"]
        ),
        (
            ["como usar", "como usa"],
            RESPOSTAS_RAPIDAS_MARANHAO["como_usar"]
        ),
        (
            [
                "onde comprar",
                "onde eu compro",
                "como comprar",
                "tem loja física",
                "tem loja fisica"
            ],
            RESPOSTAS_RAPIDAS_MARANHAO["onde_comprar"]
        )
    ]

    for frases, resposta in regras:
        if any(frase in texto for frase in frases):
            return resposta

    return None


ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# =====================================================
# BANCO DE DADOS — LEADS B2B E DEGUSTAÇÃO
# =====================================================

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada. Adicione a Internal Database URL "
            "do PostgreSQL nas variáveis de ambiente do serviço."
        )

    return psycopg2.connect(
        DATABASE_URL,
        sslmode=os.getenv("DB_SSLMODE", "require")
    )


def inicializar_banco():
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                # ==========================================
                # LEADS B2B
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cadastros_profissionais (
                        id UUID PRIMARY KEY,
                        empresa VARCHAR(180) NOT NULL,
                        cnpj VARCHAR(30) NOT NULL,
                        segmento VARCHAR(80) NOT NULL,
                        responsavel VARCHAR(180) NOT NULL,
                        whatsapp VARCHAR(40) NOT NULL,
                        email VARCHAR(180) NOT NULL,
                        cidade VARCHAR(180) NOT NULL,
                        interesse VARCHAR(80) NOT NULL,
                        mensagem TEXT,
                        consentimento BOOLEAN NOT NULL DEFAULT FALSE,
                        status VARCHAR(40) NOT NULL DEFAULT 'novo_lead',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # SOLICITAÇÕES DE DEGUSTAÇÃO
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS solicitacoes_degustacao (
                        id UUID PRIMARY KEY,
                        empresa VARCHAR(180) NOT NULL,
                        cnpj VARCHAR(30),
                        segmento VARCHAR(80) NOT NULL,
                        cidade VARCHAR(180) NOT NULL,
                        responsavel VARCHAR(180) NOT NULL,
                        whatsapp VARCHAR(40) NOT NULL,
                        email VARCHAR(180) NOT NULL,
                        mensagem TEXT,
                        status VARCHAR(40) NOT NULL DEFAULT 'nova_solicitacao',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # DOCUMENTOS EMPRESARIAIS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documentos_empresariais (
                        id UUID PRIMARY KEY,
                        nome VARCHAR(255) NOT NULL,
                        nome_original VARCHAR(255) NOT NULL,
                        categoria VARCHAR(80) NOT NULL,
                        descricao TEXT,
                        versao VARCHAR(60),
                        data_documento DATE,
                        nivel_acesso VARCHAR(40) NOT NULL DEFAULT 'direcao',
                        usar_na_ia BOOLEAN NOT NULL DEFAULT FALSE,
                        mime_type VARCHAR(120),
                        tamanho_bytes BIGINT,
                        conteudo BYTEA NOT NULL,
                        texto_extraido TEXT,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)


                cur.execute("""
                    ALTER TABLE documentos_empresariais
                    ADD COLUMN IF NOT EXISTS texto_extraido TEXT
                """)

                cur.execute("""
                    ALTER TABLE documentos_empresariais
                    ADD COLUMN IF NOT EXISTS status_documento VARCHAR(30)
                    NOT NULL DEFAULT 'vigente'
                """)

                cur.execute("""
                    ALTER TABLE documentos_empresariais
                    ADD COLUMN IF NOT EXISTS substitui_documento_id UUID
                """)

                # ==========================================
                # DECISÕES EMPRESARIAIS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS decisoes_empresariais (
                        id UUID PRIMARY KEY,
                        titulo VARCHAR(220) NOT NULL,
                        descricao TEXT NOT NULL,
                        area VARCHAR(80) NOT NULL,
                        horizonte VARCHAR(30) NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'ativa',
                        responsavel VARCHAR(180),
                        data_decisao DATE NOT NULL DEFAULT CURRENT_DATE,
                        documento_id UUID,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # ACOES EMPRESARIAIS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS acoes_empresariais (
                        id UUID PRIMARY KEY,
                        titulo VARCHAR(220) NOT NULL,
                        descricao TEXT NOT NULL,
                        area VARCHAR(80) NOT NULL,
                        prioridade VARCHAR(30) NOT NULL DEFAULT 'media',
                        status VARCHAR(30) NOT NULL DEFAULT 'pendente',
                        responsavel VARCHAR(180),
                        data_limite DATE,
                        decisao_id UUID,
                        resultado TEXT,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # AUDITORIA CENTRAL
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS auditoria_eventos (
                        id UUID PRIMARY KEY,
                        categoria VARCHAR(60) NOT NULL,
                        acao VARCHAR(120) NOT NULL,

                        ator_tipo VARCHAR(40) NOT NULL,
                        ator_id VARCHAR(180),

                        origem VARCHAR(80),

                        entidade_tipo VARCHAR(80),
                        entidade_id VARCHAR(180),

                        status VARCHAR(40) NOT NULL DEFAULT 'registrado',

                        requer_aprovacao BOOLEAN NOT NULL DEFAULT FALSE,
                        aprovado_por VARCHAR(180),

                        correlation_id VARCHAR(180),

                        dados_entrada TEXT,
                        dados_saida TEXT,
                        erro TEXT,

                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_auditoria_eventos_criado_em
                    ON auditoria_eventos (criado_em DESC)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_auditoria_eventos_categoria
                    ON auditoria_eventos (categoria)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_auditoria_eventos_entidade
                    ON auditoria_eventos (
                        entidade_tipo,
                        entidade_id
                    )
                """)

                # ==========================================
                # CRM / FUNIL DE LEADS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads_crm (
                        id UUID PRIMARY KEY,
                        nome VARCHAR(180),
                        empresa VARCHAR(220),
                        tipo_lead VARCHAR(30) NOT NULL,
                        origem VARCHAR(80) NOT NULL,
                        canal VARCHAR(80),
                        cidade VARCHAR(120),
                        estado VARCHAR(80),
                        contato VARCHAR(220),
                        interesse TEXT,
                        estagio VARCHAR(40) NOT NULL DEFAULT 'novo',
                        valor_potencial_centavos BIGINT,
                        cac_centavos BIGINT,
                        receita_acumulada_centavos BIGINT NOT NULL DEFAULT 0,
                        responsavel VARCHAR(180),
                        proximo_followup TIMESTAMPTZ,
                        observacoes TEXT,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # ==========================================
                # PEDIDOS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS atendimentos_sac (
                        id UUID PRIMARY KEY,
                        atendimento_id VARCHAR(40) UNIQUE NOT NULL,
                        mensagem TEXT NOT NULL,
                        resposta TEXT,
                        origem VARCHAR(40),
                        tipo VARCHAR(40),
                        codigo_pedido VARCHAR(40),
                        cliente_email VARCHAR(180),
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pedidos (
                        id UUID PRIMARY KEY,

                        codigo VARCHAR(40)
                            UNIQUE NOT NULL,

                        cliente_nome VARCHAR(180),
                        cliente_email VARCHAR(180),
                        cliente_whatsapp VARCHAR(40),
                        cpf_cnpj VARCHAR(30),

                        endereco TEXT NOT NULL,

                        quantidade INTEGER NOT NULL,

                        valor_centavos INTEGER NOT NULL,

                        status VARCHAR(50)
                            NOT NULL
                            DEFAULT 'aguardando_pagamento',

                        payment_origin VARCHAR(30),

                        c6_txid VARCHAR(120),
                        c6_status VARCHAR(50),

                        pagarme_id VARCHAR(160),

                        transportadora VARCHAR(160),

                        status_entrega VARCHAR(60)
                            NOT NULL
                            DEFAULT 'aguardando_pagamento',

                        tracking_code VARCHAR(180),
                        tracking_url TEXT,

                        criado_em TIMESTAMPTZ
                            NOT NULL
                            DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL
                            DEFAULT NOW()
                    )
                """)

    finally:
        conn.close()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_FOLDER = os.path.join(
    BASE_DIR,
    "maranhao-backend"
)

print("=" * 60)
print("BASE_DIR:", BASE_DIR)
print("FRONTEND_FOLDER:", FRONTEND_FOLDER)
print("PASTA EXISTE?", os.path.isdir(FRONTEND_FOLDER))
print("INDEX EXISTE?",
      os.path.isfile(os.path.join(FRONTEND_FOLDER, "index.html")))
print("=" * 60)

app = Flask(
    __name__,
    static_folder=FRONTEND_FOLDER
)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    "krikati_ancestral_secret"
)

# =====================================================
# CORS — SAC MARANHÃO CORDIAL
# =====================================================

ORIGENS_PERMITIDAS_SAC = {
    "https://maranhaocordial.com.br",
    "https://www.maranhaocordial.com.br",
}


@app.after_request
def adicionar_cors_sac(response):

    if (
        request.path.startswith("/api/sac")
        or request.path.startswith("/api/admin")
    ):

        origem = request.headers.get("Origin")

        if origem in ORIGENS_PERMITIDAS_SAC:

            response.headers[
                "Access-Control-Allow-Origin"
            ] = origem

            response.headers[
                "Vary"
            ] = "Origin"

            response.headers[
                "Access-Control-Allow-Headers"
            ] = "Content-Type, X-Admin-Key"

            response.headers[
                "Access-Control-Allow-Methods"
            ] = "GET, POST, OPTIONS"

    return response


socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)

# =====================================================
# PAGAR.ME
# =====================================================

PAGARME_SECRET_KEY = os.getenv(
    "PAGARME_SECRET_KEY"
)

PAGARME_BASE_URL = os.getenv(
    "PAGARME_BASE_URL",
    "https://sdx-api.pagar.me/core/v5"
)

# Maranhão
PRECO_UNITARIO = 5990  # R$ 59,90 em centavos


# =====================================================
# C6 BANK — CONFIGURAÇÃO DA API
# =====================================================
#
# O C6 libera os endpoints/credenciais definitivos após
# cadastro, sandbox e homologação. Por isso, nada aqui
# inventa URLs bancárias: tudo entra pelo .env.
#

C6_CLIENT_ID = os.getenv("C6_CLIENT_ID")
C6_CLIENT_SECRET = os.getenv("C6_CLIENT_SECRET")
C6_TOKEN_URL = os.getenv("C6_TOKEN_URL")
C6_PIX_CREATE_URL = os.getenv("C6_PIX_CREATE_URL")
C6_PIX_QUERY_URL_TEMPLATE = os.getenv("C6_PIX_QUERY_URL_TEMPLATE")
C6_SCOPE = os.getenv("C6_SCOPE", "")

# Alguns produtos bancários usam certificado cliente (mTLS).
# Se o C6 exigir, coloque os caminhos dos arquivos no Render.
C6_CERT_PATH = os.getenv("C6_CERT_PATH")
C6_KEY_PATH = os.getenv("C6_KEY_PATH")

# Modo de autenticação configurável, conforme documentação
# que o C6 fornecer à sua empresa: basic ou body.
C6_AUTH_MODE = os.getenv("C6_AUTH_MODE", "basic").lower()

# O webhook só libera pedido automaticamente se o evento
# recebido puder ser confirmado consultando a própria API C6.
# Assim, não confiamos cegamente em um POST externo.
C6_PAID_STATUS_VALUES = {
    x.strip().upper()
    for x in os.getenv("C6_PAID_STATUS_VALUES", "").split(",")
    if x.strip()
}

# Nome do campo de status na resposta de consulta do C6.
# Ex.: status, situacao etc. Ajustar após receber a documentação.
C6_STATUS_FIELD = os.getenv("C6_STATUS_FIELD", "status")


# =====================================================
# LOGÍSTICA — CONFIGURAÇÃO FUTURA
# =====================================================
# A empresa de entrega ainda será contratada.
# Este token é opcional e servirá para proteger um webhook
# genérico até adaptarmos ao contrato/API da transportadora.

LOGISTICA_WEBHOOK_TOKEN = os.getenv("LOGISTICA_WEBHOOK_TOKEN")


# =====================================================
# BANCO TEMPORÁRIO DE PEDIDOS
# =====================================================
#
# IMPORTANTE:
# Isso é apenas para teste.
# Na produção, devemos usar seu banco de dados.
#

PEDIDOS = {}

def salvar_pedido_postgres(pedido):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO pedidos (
                        id,
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        cpf_cnpj,
                        endereco,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_txid,
                        c6_status,
                        pagarme_id,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        tracking_url
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (codigo)
                    DO UPDATE SET
                        cliente_nome = EXCLUDED.cliente_nome,
                        cliente_email = EXCLUDED.cliente_email,
                        cliente_whatsapp = EXCLUDED.cliente_whatsapp,
                        cpf_cnpj = EXCLUDED.cpf_cnpj,
                        endereco = EXCLUDED.endereco,
                        quantidade = EXCLUDED.quantidade,
                        valor_centavos = EXCLUDED.valor_centavos,
                        status = EXCLUDED.status,
                        payment_origin = EXCLUDED.payment_origin,
                        c6_txid = EXCLUDED.c6_txid,
                        c6_status = EXCLUDED.c6_status,
                        pagarme_id = EXCLUDED.pagarme_id,
                        transportadora = EXCLUDED.transportadora,
                        status_entrega = EXCLUDED.status_entrega,
                        tracking_code = EXCLUDED.tracking_code,
                        tracking_url = EXCLUDED.tracking_url,
                        atualizado_em = NOW()
                """, (
                    str(uuid.uuid4()),
                    pedido.get("code"),
                    pedido.get("cliente_nome"),
                    pedido.get("cliente_email"),
                    pedido.get("cliente_whatsapp"),
                    pedido.get("cpf_cnpj"),
                    pedido.get("address"),
                    pedido.get("quantity"),
                    pedido.get("amount"),
                    pedido.get("status"),
                    pedido.get("payment_origin"),
                    pedido.get("c6_txid"),
                    pedido.get("c6_status"),
                    pedido.get("pagarme_id"),
                    pedido.get("delivery", {}).get("provider"),
                    pedido.get("delivery", {}).get("status"),
                    pedido.get("delivery", {}).get("tracking_code"),
                    pedido.get("delivery", {}).get("tracking_url")
                ))

    finally:
        conn.close()


def registrar_auditoria(
    categoria,
    acao,
    ator_tipo="sistema",
    ator_id=None,
    origem=None,
    entidade_tipo=None,
    entidade_id=None,
    status="registrado",
    requer_aprovacao=False,
    aprovado_por=None,
    correlation_id=None,
    dados_entrada=None,
    dados_saida=None,
    erro=None
):
    """
    Registra eventos relevantes da operação empresarial.

    A auditoria nunca deve interromper a operação principal.
    Se houver erro ao registrar o evento, retorna None.
    """

    evento_id = str(uuid.uuid4())

    def serializar(valor):
        if valor is None:
            return None

        try:
            return json.dumps(
                valor,
                ensure_ascii=False,
                default=str
            )
        except Exception:
            return str(valor)

    try:
        conn = get_db_connection()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO auditoria_eventos (
                            id,
                            categoria,
                            acao,
                            ator_tipo,
                            ator_id,
                            origem,
                            entidade_tipo,
                            entidade_id,
                            status,
                            requer_aprovacao,
                            aprovado_por,
                            correlation_id,
                            dados_entrada,
                            dados_saida,
                            erro
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                    """, (
                        evento_id,
                        str(categoria),
                        str(acao),
                        str(ator_tipo),
                        str(ator_id) if ator_id else None,
                        str(origem) if origem else None,
                        str(entidade_tipo) if entidade_tipo else None,
                        str(entidade_id) if entidade_id else None,
                        str(status),
                        bool(requer_aprovacao),
                        str(aprovado_por) if aprovado_por else None,
                        str(correlation_id) if correlation_id else None,
                        serializar(dados_entrada),
                        serializar(dados_saida),
                        str(erro) if erro else None
                    ))

            return evento_id

        finally:
            conn.close()

    except Exception as erro_auditoria:
        print(
            "ERRO AUDITORIA CENTRAL:",
            erro_auditoria
        )

        return None


def salvar_atendimento_sac(
    atendimento_id,
    mensagem,
    resposta,
    origem,
    tipo,
    codigo_pedido=None,
    cliente_email=None
):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO atendimentos_sac (
                        id,
                        atendimento_id,
                        mensagem,
                        resposta,
                        origem,
                        tipo,
                        codigo_pedido,
                        cliente_email
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (atendimento_id)
                    DO UPDATE SET
                        mensagem = EXCLUDED.mensagem,
                        resposta = EXCLUDED.resposta,
                        origem = EXCLUDED.origem,
                        tipo = EXCLUDED.tipo,
                        codigo_pedido = EXCLUDED.codigo_pedido,
                        cliente_email = EXCLUDED.cliente_email
                """, (
                    str(uuid.uuid4()),
                    atendimento_id,
                    mensagem,
                    resposta,
                    origem,
                    tipo,
                    codigo_pedido,
                    cliente_email
                ))

    finally:
        conn.close()


# =====================================================
# PÁGINA INICIAL
# =====================================================

@app.route("/")
@app.route("/index")
@app.route("/index.html")
def index():
    return send_from_directory(
        FRONTEND_FOLDER,
        "index.html"
    )


# =====================================================
# PÁGINAS
# =====================================================

def renderizar_html(nome_arquivo):

    caminho = os.path.join(
        FRONTEND_FOLDER,
        nome_arquivo
    )

    if os.path.isfile(caminho):
        return send_from_directory(
            FRONTEND_FOLDER,
            nome_arquivo
        )

    nome_maiusculo = nome_arquivo.replace(
        ".html",
        ".HTML"
    )

    caminho_maiusculo = os.path.join(
        FRONTEND_FOLDER,
        nome_maiusculo
    )

    if os.path.isfile(caminho_maiusculo):
        return send_from_directory(
            FRONTEND_FOLDER,
            nome_maiusculo
        )

    return (
        f"Erro: O arquivo '{nome_arquivo}' "
        "não foi encontrado.",
        404
    )


@app.route("/experience")
def experience():
    return renderizar_html("experience.html")


@app.route("/raizes")
def raizes():
    return renderizar_html("raizes.html")


@app.route("/deposito")
@app.route("/deposito.html")
def deposito():
    return renderizar_html("deposito.html")


@app.route("/entrega")
@app.route("/entrega.html")
def entrega():
    return renderizar_html("entrega.html")


@app.route("/compreaqui")
@app.route("/compreaqui.html")
def compreaqui():
    return renderizar_html("compreaqui.html")


@app.route("/checkout.html")
def checkout():
    return renderizar_html("checkout.html")

@app.route("/home.html")
def home():
    return renderizar_html("home.html")

@app.route("/profissional")
def profissional():
    return renderizar_html("profissional.html")

@app.route("/cadastro-profissional")
def cadastro_profissional():
    return renderizar_html("cadastro-profissional.html")

@app.route("/degustacao")
@app.route("/degustacao.html")
def degustacao():
    return renderizar_html("degustacao.html")

@app.route(
    "/api/profissional/cadastro",
    methods=["POST"]
)
def cadastrar_empresa():
    dados = request.get_json(silent=True) or {}

    obrigatorios = [
        "empresa", "cnpj", "segmento", "responsavel",
        "whatsapp", "email", "cidade", "interesse"
    ]

    faltando = [
        campo for campo in obrigatorios
        if not str(dados.get(campo, "")).strip()
    ]

    if faltando:
        return jsonify({
            "success": False,
            "error": "Preencha todos os campos obrigatórios.",
            "fields": faltando
        }), 400

    if dados.get("consentimento") is not True:
        return jsonify({
            "success": False,
            "error": "É necessário autorizar o contato comercial."
        }), 400

    cadastro_id = str(uuid.uuid4())

    try:
        conn = get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO cadastros_profissionais (
                            id, empresa, cnpj, segmento, responsavel,
                            whatsapp, email, cidade, interesse, mensagem,
                            consentimento, status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s
                        )
                    """, (
                        cadastro_id,
                        str(dados["empresa"]).strip(),
                        str(dados["cnpj"]).strip(),
                        str(dados["segmento"]).strip(),
                        str(dados["responsavel"]).strip(),
                        str(dados["whatsapp"]).strip(),
                        str(dados["email"]).strip().lower(),
                        str(dados["cidade"]).strip(),
                        str(dados["interesse"]).strip(),
                        str(dados.get("mensagem", "")).strip() or None,
                        True,
                        "novo_lead"
                    ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Cadastro profissional recebido.",
            "empresa_id": str(cadastro_id)
        }), 201

    except Exception as erro:
        print("ERRO SALVAR CADASTRO PROFISSIONAL:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível salvar o cadastro agora."
        }), 500


@app.route(
    "/api/degustacao",
    methods=["POST"]
)
def cadastrar_degustacao():
    dados = request.get_json(silent=True) or {}

    obrigatorios = [
        "empresa", "segmento", "cidade", "responsavel",
        "whatsapp", "email"
    ]

    faltando = [
        campo for campo in obrigatorios
        if not str(dados.get(campo, "")).strip()
    ]

    if faltando:
        return jsonify({
            "success": False,
            "error": "Preencha todos os campos obrigatórios.",
            "fields": faltando
        }), 400

    degustacao_id = str(uuid.uuid4())

    try:
        conn = get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO solicitacoes_degustacao (
                            id, empresa, cnpj, segmento, cidade,
                            responsavel, whatsapp, email, mensagem, status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                    """, (
                        degustacao_id,
                        str(dados["empresa"]).strip(),
                        str(dados.get("cnpj", "")).strip() or None,
                        str(dados["segmento"]).strip(),
                        str(dados["cidade"]).strip(),
                        str(dados["responsavel"]).strip(),
                        str(dados["whatsapp"]).strip(),
                        str(dados["email"]).strip().lower(),
                        str(dados.get("mensagem", "")).strip() or None,
                        "nova_solicitacao"
                    ))
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Solicitação de degustação recebida.",
            "degustacao_id": degustacao_id
        }), 201

    except Exception as erro:
        print("ERRO SALVAR DEGUSTAÇÃO:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível salvar a solicitação agora."
        }), 500


# =====================================================
# SAC MARANHÃO CORDIAL — ETAPA 1 DO BACKEND
# =====================================================
#
# Esta rota recebe mensagens do widget de atendimento.
# Neste primeiro momento ela apenas valida a mensagem
# e confirma que frontend e backend estão se comunicando.
# IA, histórico, CRM e automações serão ligados nas
# próximas etapas sem alterar esta URL pública.
#

@app.route(
    "/api/sac",
    methods=["POST"]
)
def sac_maranhao():
    dados = request.get_json(silent=True) or {}

    mensagem = str(dados.get("mensagem", "")).strip()
    origem = str(dados.get("origem", "site")).strip()
    tipo = str(dados.get("tipo", "geral")).strip()

    if not mensagem:
        return jsonify({
            "success": False,
            "error": "Mensagem obrigatória."
        }), 400

    # -------------------------------------------------
    # RESPOSTA INSTANTÂNEA PARA DÚVIDAS SIMPLES
    # -------------------------------------------------

    resposta_rapida = resposta_rapida_maranhao(
        mensagem
    )

    if resposta_rapida:

        atendimento_id = (
            "SAC-"
            + uuid.uuid4().hex[:12].upper()
        )

        try:
            salvar_atendimento_sac(
                atendimento_id=atendimento_id,
                mensagem=mensagem,
                resposta=resposta_rapida,
                origem=origem,
                tipo=tipo,
                codigo_pedido=None,
                cliente_email=None
            )
        except Exception as erro:
            print(
                "ERRO SALVAR SAC RÁPIDO:",
                erro
            )

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": resposta_rapida,
            "origem": origem,
            "tipo": tipo,
            "modo": "resposta_rapida"
        }), 200



    # -------------------------------------------------
    # IDENTIFICA NÚMERO DO PEDIDO NA MENSAGEM
    # -------------------------------------------------

    pedido_encontrado = None

    match_pedido = re.search(
        r"MAR-[A-Z0-9-]+",
        mensagem.upper()
    )

    print(
    "DEBUG PEDIDO SAC:",
    match_pedido.group(0) if match_pedido else "NENHUM"
    )

    if match_pedido:
        codigo_pedido = match_pedido.group(0)

        try:
            pedido_encontrado = buscar_pedido_postgres(
                codigo_pedido
            )

        except Exception as erro:
            print(
                "ERRO SAC CONSULTAR PEDIDO:",
                erro
            )

    # -------------------------------------------------
    # IDENTIFICADOR DO ATENDIMENTO
    # -------------------------------------------------

    atendimento_id = "SAC-" + uuid.uuid4().hex[:12].upper()

    print("=" * 60)
    print("SAC MARANHÃO CORDIAL")
    print("ATENDIMENTO:", atendimento_id)
    print("ORIGEM:", origem)
    print("TIPO:", tipo)
    print("MENSAGEM:", mensagem)
    print("=" * 60)

    # -------------------------------------------------
    # RESPOSTA RÁPIDA PARA PEDIDO ENCONTRADO
    # -------------------------------------------------

    if match_pedido and pedido_encontrado:

        # -----------------------------------------
        # VALIDA E-MAIL DO CLIENTE
        # -----------------------------------------

        email_informado = re.search(
            r"[\w\.-]+@[\w\.-]+\.\w+",
            mensagem.lower()
        )

        if not email_informado:
            return jsonify({
                "success": True,
                "atendimento_id": atendimento_id,
                "resposta": (
                    "Encontrei esse número de pedido. "
                    "Informe o e-mail utilizado na compra para continuar."
                ),
                "origem": origem,
                "tipo": tipo,
                "aguardando_email": True
            }), 200

        email_cliente = (
            pedido_encontrado.get("cliente_email")
            or ""
        ).strip().lower()

        if email_informado.group(0) != email_cliente:
            return jsonify({
                "success": True,
                "atendimento_id": atendimento_id,
                "resposta": (
                    "O e-mail informado não corresponde a esse pedido. "
                    "Confira os dados e tente novamente."
                ),
                "origem": origem,
                "tipo": tipo
            }), 200

        # -----------------------------------------
        # E-MAIL CONFIRMADO → EXIBE STATUS
        # -----------------------------------------

        status_pedido = str(
            pedido_encontrado.get("status")
            or "sem_status"
        ).replace("_", " ")

        status_entrega = str(
            pedido_encontrado.get("status_entrega")
            or ""
        ).replace("_", " ")

        codigo_rastreio = (
            pedido_encontrado.get("tracking_code")
        )

        partes = [
            f"Encontrei o pedido {codigo_pedido}.",
            f"Status: {status_pedido}."
        ]

        if status_entrega:
            partes.append(
                f"Entrega: {status_entrega}."
            )

        if codigo_rastreio:
            partes.append(
                f"Rastreio: {codigo_rastreio}."
            )

        texto_resposta = " ".join(partes)

        try:
            salvar_atendimento_sac(
                atendimento_id=atendimento_id,
                mensagem=mensagem,
                resposta=texto_resposta,
                origem=origem,
                tipo=tipo,
                codigo_pedido=codigo_pedido,
                cliente_email=email_cliente
            )
        except Exception as erro:
            print("ERRO SALVAR SAC:", erro)

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": texto_resposta,
            "origem": origem,
            "tipo": tipo,
            "pedido": codigo_pedido
        }), 200


    # -------------------------------------------------
    # PEDIDO INFORMADO, MAS NÃO ENCONTRADO
    # -------------------------------------------------

    if match_pedido and not pedido_encontrado:

        return jsonify({
            "success": True,
            "atendimento_id": atendimento_id,
            "resposta": (
                f"Não encontrei o pedido {codigo_pedido}. "
                "Confira o número e tente novamente."
            ),
            "origem": origem,
            "tipo": tipo
        }), 200

    if not openai_client:
        texto_resposta = (
            "Recebemos sua mensagem. "
            "O atendimento inteligente está temporariamente indisponível."
        )
    else:
        try:
            resposta_ia = openai_client.responses.create(
                model="gpt-5-mini",
                instructions=(
                    "Você é o atendimento digital oficial do Maranhão Cordial. "
                    + CONTEXTO_MARANHAO
                    + USOS_PUBLICOS_VALIDADOS
                    + " Responda em português do Brasil com no máximo 2 frases curtas. "
                    "Seja cordial, elegante e objetivo. "
                    "Nunca invente política, prazo, preço, troca, reembolso, envio ou cancelamento. "
                    "Nunca peça CPF, cartão, senha, dados bancários ou documentos pessoais. "
                    "Se houver problema com compra feita no site oficial, peça apenas o número do pedido. "
                    "O Maranhão Cordial não possui lojas físicas. "
                    "Se a compra foi feita fora do site maranhaocordial.com.br, informe que qualquer reclamação "
                    "ou solução deve ser tratada diretamente com o distribuidor ou estabelecimento onde a compra foi feita. "
                    "Faça no máximo uma pergunta por resposta. "
                    "Evite repetir a mesma estrutura, abertura ou conclusão em respostas semelhantes. "
                    "Varie naturalmente o vocabulário sem alterar os fatos oficiais da marca. "
                    "Escolha o foco da resposta de acordo com a necessidade demonstrada pelo cliente. "
                    "Quando pertinente, varie entre eficiência operacional, padronização, experiência do cliente, "
                    "aplicações gastronômicas, hospitalidade, coquetelaria, minibar, eventos, identidade cultural "
                    "e experiência de marca. "
                    "Não tente mencionar todos esses aspectos na mesma resposta. "
                    "Não use sempre expressões como 'agrega valor', 'experiência sensorial' ou 'padronização'. "
                    "Não termine todas as respostas oferecendo atendimento B2B. "
                    "Só faça convite comercial ou próxima pergunta quando isso realmente ajudar a avançar a conversa. "
                    "Quando o cliente já tiver informado seu segmento, adapte a resposta especificamente àquele segmento. "
                    "Escolha um argumento principal por resposta e desenvolva prioritariamente esse eixo. "
                    "Evite respostas que apenas enumerem características do produto. "
                    "Não repita mecanicamente expressões como 'padronização', 'praticidade de bancada' e 'experiência sensorial'. "
                    "Use esses conceitos somente quando forem realmente relevantes para a pergunta. "
                    "Para hotéis, varie o raciocínio conforme o contexto entre bar, minibar, eventos, café da manhã, "
                    "experiência do hóspede, carta de bebidas, operação, gastronomia e identidade cultural. "
                    "Para bares e restaurantes, considere naturalmente operação, velocidade de serviço, consistência, "
                    "criação de bebidas, diferenciação de cardápio e aplicações gastronômicas. "
                    "Não invente usos, benefícios, números, preços, condições comerciais ou capacidades que não estejam nas informações oficiais. "
                    "Não prometa proposta, amostra, desconto ou condição comercial sem que isso esteja autorizado nas informações disponíveis. "
                    "Finalize sempre com uma frase completa e pontuação adequada. "
                    "Diferencie rigorosamente fatos oficiais de possibilidades comerciais. "
                    "Só afirme como fato aquilo que estiver explicitamente presente no CONTEXTO_MARANHAO. "
                    "Não invente aplicações gastronômicas específicas, receitas, molhos, marinadas, sobremesas, "
                    "drinks prontos, minibar, redução de erros, redução de custos ou ganhos operacionais não comprovados. "
                    "Se identificar uma aplicação possível que não esteja validada oficialmente, use linguagem condicional, "
                    "como 'pode ser estudado', 'pode ser avaliado' ou 'é uma possibilidade a ser desenvolvida'. "
                    "Não prometa fichas técnicas, receitas, amostras, propostas ou materiais que o sistema não tenha confirmação de que existem. "
                    "Quando houver dúvida, seja preciso e conservador em vez de completar a informação por inferência."
                ),
                input=mensagem,
                reasoning={
                    "effort": "low"
                },
                max_output_tokens=800
            )

            texto_resposta = (resposta_ia.output_text or "").strip()

            if not texto_resposta:
                resposta_retry = openai_client.responses.create(
                    model="gpt-5-mini",
                    instructions=(
                        "Responda diretamente à pergunta do cliente em português do Brasil. "
                        "Use 1 ou 2 frases curtas. "
                        "Não faça introdução genérica. "
                        "Não diga 'Como posso ajudar com seu pedido?'. "
                        + CONTEXTO_MARANHAO
                        + CONTEXTO_EMPRESARIAL_INTERNO
                    ),
                    input=mensagem,
                    reasoning={
                        "effort": "low"
                    },
                    max_output_tokens=500
                )

                texto_resposta = (
                    resposta_retry.output_text or ""
                ).strip()

            if not texto_resposta:
                texto_resposta = (
                    "Posso explicar melhor essa aplicação do Maranhão Cordial. "
                    "Tente reformular a pergunta em uma frase curta."
                )

            texto_resposta = validar_resposta_publica(
                mensagem,
                texto_resposta
            )

            texto_resposta = limpar_resposta_publica(
                texto_resposta
            )

        except Exception as erro:
            print("ERRO IA SAC MARANHÃO:", erro)
            texto_resposta = (
                "Recebemos sua mensagem. "
                "O atendimento inteligente está temporariamente indisponível."
            )

    try:
        salvar_atendimento_sac(
            atendimento_id=atendimento_id,
            mensagem=mensagem,
            resposta=texto_resposta,
            origem=origem,
            tipo=tipo,
            codigo_pedido=(
                codigo_pedido
                if match_pedido
                else None
            ),
            cliente_email=None
        )
    except Exception as erro:
        print("ERRO SALVAR SAC:", erro)

    return jsonify({
        "success": True,
        "atendimento_id": atendimento_id,
        "resposta": texto_resposta,
        "origem": origem,
        "tipo": tipo,
        "validator_version": "v1-rigido"
    }), 200


@app.route("/admin")
@app.route("/admin.html")
def admin():
    return renderizar_html("admin.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204




# =====================================================
# FUNÇÕES COMUNS — PAGAMENTO / C6 / LOGÍSTICA
# =====================================================

def finalizar_pedido_pago(codigo, origem_pagamento):
    """
    Centraliza a liberação operacional do pedido.
    Pagar.me e C6 chamam exatamente a mesma função.
    """

    pedido = PEDIDOS.get(codigo)

    if not pedido:
        return False

    # Idempotência: webhook repetido não dispara tudo de novo.
    if pedido.get("status") == "pago":
        return True

    pedido["status"] = "pago"
    pedido["payment_origin"] = origem_pagamento

    pedido.setdefault("delivery", {})
    pedido["delivery"]["status"] = "aguardando_despacho"

    try:
        salvar_pedido_postgres(pedido)
    except Exception as erro:
        print("ERRO PERSISTIR PEDIDO PAGO:", erro)

    emit(
        "to_admin",
        pedido,
        broadcast=True
    )

    print(
        f"✓ PEDIDO PAGO — {codigo} — origem: {origem_pagamento}"
    )

    return True

# =====================================================
# C6 BANK — SANDBOX
# =====================================================

C6_CLIENT_ID = os.getenv("C6_CLIENT_ID")
C6_CLIENT_SECRET = os.getenv("C6_CLIENT_SECRET")
C6_PIX_KEY = os.getenv("C6_PIX_KEY")

C6_AUTH_URL = os.getenv(
    "C6_AUTH_URL",
    "https://baas-api-sandbox.c6bank.info/v1/auth/"
)

C6_PIX_BASE_URL = os.getenv(
    "C6_PIX_BASE_URL",
    "https://baas-api-sandbox.c6bank.info/v2/pix"
)
C6_CERT_PATH = os.getenv(
    "C6_CERT_PATH",
    "/etc/secrets/C6_sandbox.crt"
)

C6_KEY_PATH = os.getenv(
    "C6_KEY_PATH",
    "/etc/secrets/C6_sandbox.key"
)


# =====================================================
# C6 — CERTIFICADO mTLS
# =====================================================

def c6_cert():

    if not C6_CERT_PATH or not C6_KEY_PATH:
        raise RuntimeError(
            "Certificado C6 não configurado."
        )

    return (
        C6_CERT_PATH,
        C6_KEY_PATH
    )


# =====================================================
# C6 — AUTENTICAÇÃO
# =====================================================

def get_c6_access_token():

    faltando = []

    if not C6_CLIENT_ID:
        faltando.append("C6_CLIENT_ID")

    if not C6_CLIENT_SECRET:
        faltando.append("C6_CLIENT_SECRET")

    if not C6_PIX_KEY:
        faltando.append("C6_PIX_KEY")

    if faltando:
        raise RuntimeError(
            "C6 não configurado: "
            + ", ".join(faltando)
        )

    resposta = requests.post(
        C6_AUTH_URL,

        data={
            "client_id":
                C6_CLIENT_ID,

            "client_secret":
                C6_CLIENT_SECRET,

            "grant_type":
                "client_credentials"
        },

        cert=c6_cert(),

        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },

        timeout=30
    )

    if not resposta.ok:

        print(
            "ERRO AUTENTICAÇÃO C6:",
            resposta.status_code,
            resposta.text
        )

        resposta.raise_for_status()

    dados = resposta.json()

    access_token = dados.get(
        "access_token"
    )

    if not access_token:
        raise RuntimeError(
            "C6 não retornou access_token."
        )

    return access_token


# =====================================================
# C6 — HEADERS
# =====================================================

def c6_headers():

    return {

        "Authorization":
            f"Bearer {get_c6_access_token()}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",

        "User-Agent":
            "maranhao-cordial/1.0"
    }


# =====================================================
# C6 — CONSULTAR COBRANÇA PIX
# =====================================================

def consultar_pix_c6(txid):

    if not txid:
        raise RuntimeError(
            "TXID obrigatório."
        )

    url = (
        f"{C6_PIX_BASE_URL}"
        f"/cob/{txid}"
    )

    resposta = requests.get(
        url,

        headers=c6_headers(),

        cert=c6_cert(),

        timeout=30
    )

    if not resposta.ok:

        print(
            "ERRO CONSULTA PIX C6:",
            resposta.status_code,
            resposta.text
        )

        resposta.raise_for_status()

    return resposta.json()


# =====================================================
# C6 — STATUS DA INTEGRAÇÃO
# =====================================================

@app.route(
    "/api/c6/status",
    methods=["GET"]
)
def status_c6():

    return jsonify({

        "integration":
            "C6 Bank",

        "environment":
            "sandbox",

        "credentials_configured":
            bool(
                C6_CLIENT_ID
                and C6_CLIENT_SECRET
            ),

        "pix_key_configured":
            bool(C6_PIX_KEY),

        "mtls_configured":
            bool(
                C6_CERT_PATH
                and C6_KEY_PATH
            ),

        "auth_url":
            C6_AUTH_URL,

        "pix_base_url":
            C6_PIX_BASE_URL,

        "ready":
            bool(
                C6_CLIENT_ID
                and C6_CLIENT_SECRET
                and C6_PIX_KEY
                and C6_CERT_PATH
                and C6_KEY_PATH
            )
    })


# =====================================================
# C6 BANK — CRIAR COBRANÇA PIX
# =====================================================

@app.route(
    "/api/c6/pix/checkout",
    methods=["POST"]
)
def criar_checkout_c6():

    dados = request.get_json(
        silent=True
    ) or {}

    # ---------------------------------------------
    # QUANTIDADE
    # ---------------------------------------------

    try:

        quantidade = int(
            dados.get(
                "quantidade",
                1
            )
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "error":
                "Quantidade inválida."
        }), 400


    if quantidade < 1:

        return jsonify({
            "error":
                "Quantidade inválida."
        }), 400


    # ---------------------------------------------
    # ENDEREÇO
    # ---------------------------------------------

    endereco = str(
        dados.get(
            "endereco",
            ""
        )
    ).strip()


    if not endereco:

        return jsonify({
            "error":
                "Endereço obrigatório."
        }), 400


    # ---------------------------------------------
    # E-MAIL DO CLIENTE
    # ---------------------------------------------

    cliente_email = str(
        dados.get(
            "cliente_email",
            ""
        )
    ).strip().lower()

    if not cliente_email:

        return jsonify({
            "error":
                "E-mail obrigatório."
        }), 400

    # ---------------------------------------------
    # DADOS DO CLIENTE
    # ---------------------------------------------

    cliente_nome = str(
        dados.get(
            "cliente_nome",
            ""
        )
    ).strip()

    cliente_whatsapp = str(
        dados.get(
            "cliente_whatsapp",
            ""
        )
    ).strip()

    
    # ---------------------------------------------
    # CRIA PEDIDO
    # ---------------------------------------------

    codigo = (
        "MAR-"
        + uuid.uuid4().hex[:10].upper()
    )


    # PRECO_UNITARIO está em centavos
    valor_total_centavos = (
        PRECO_UNITARIO
        * quantidade
    )


    # API PIX C6 recebe valor em reais:
    # exemplo: "59.90"
    valor_total_reais = (
        f"{valor_total_centavos / 100:.2f}"
    )


    pedido = {

        "code":
            codigo,

        "quantity":
            quantidade,

        "address":
            endereco,

         "cliente_nome":
            cliente_nome,

        "cliente_email":
            cliente_email,

        "cliente_whatsapp":
            cliente_whatsapp, 

        "amount":
            valor_total_centavos,

        "status":
            "aguardando_pagamento",

        "payment_origin":
            "c6",

        "c6_txid":
            None,

        "c6_location":
            None,

        "c6_status":
            None,

        "pagarme_id":
            None,


        # -----------------------------------------
        # FISCAL
        # -----------------------------------------

        "fiscal": {

            "status":
                "aguardando_definicao_fiscal",

            "icms_st": {

                "aplicavel":
                    None,

                "responsavel":
                    None,

                "recolhido_na_origem":
                    None
            }
        },


        # -----------------------------------------
        # LOGÍSTICA
        # -----------------------------------------

        "delivery": {

            "provider":
                None,

            "status":
                "aguardando_pagamento",

            "tracking_code":
                None,

            "tracking_url":
                None
        }
    }


    PEDIDOS[codigo] = pedido
    salvar_pedido_postgres(pedido)


    # ---------------------------------------------
    # PAYLOAD PIX C6
    # ---------------------------------------------

    payload = {

        "calendario": {

            # 1 hora
            "expiracao":
                3600
        },

        "valor": {

            "original":
                valor_total_reais,

            "modalidadeAlteracao":
                0
        },

        "chave":
            C6_PIX_KEY,

        "solicitacaoPagador":
            f"Maranhão Cordial - {codigo}",


        # Informações úteis para correlação
        "infoAdicionais": [

            {
                "nome":
                    "pedido",

                "valor":
                    codigo
            },

            {
                "nome":
                    "quantidade",

                "valor":
                    str(quantidade)
            }
        ]
    }


    # ---------------------------------------------
    # ENVIA AO C6
    # ---------------------------------------------

    try:

        txid = uuid.uuid4().hex

        resposta = requests.put(

            f"{C6_PIX_BASE_URL}/cob/{txid}",

            json=payload,

            headers=c6_headers(),

            cert=c6_cert(),

            timeout=30
        )


        try:

            dados_c6 = (
                resposta.json()
            )

        except ValueError:

            dados_c6 = {
                "raw":
                    resposta.text
            }


        if resposta.status_code != 201:

            PEDIDOS[codigo][
                "status"
            ] = "erro_pagamento"


            print(
                "ERRO CRIAR PIX C6:",
                resposta.status_code,
                dados_c6
            )


            return jsonify({

                "success":
                    False,

                "error":
                    "C6 recusou a criação da cobrança PIX.",

                "details":
                    dados_c6

            }), resposta.status_code


        # -----------------------------------------
        # COBRANÇA CRIADA
        # -----------------------------------------

        txid = dados_c6.get(
            "txid"
        )

        location = dados_c6.get(
            "location"
        )

        status = dados_c6.get(
            "status"
        )


        PEDIDOS[codigo][
            "c6_txid"
        ] = txid


        PEDIDOS[codigo][
            "c6_location"
        ] = location


        PEDIDOS[codigo][
            "c6_status"
        ] = status

        salvar_pedido_postgres(PEDIDOS[codigo])

        print("=" * 60)

        print(
            f"✓ PIX C6 CRIADO — {codigo}"
        )

        print(
            "TXID:",
            txid
        )

        print(
            "STATUS:",
            status
        )

        print("=" * 60)


        return jsonify({

            "success":
                True,

            "order_code":
                codigo,

            "amount":
                valor_total_reais,

            "c6_txid":
                txid,

            "status":
                status,

            "location":
                location

        }), 201


    except requests.RequestException as erro:

        PEDIDOS[codigo][
            "status"
        ] = "erro_comunicacao_c6"


        print(
            "ERRO DE COMUNICAÇÃO C6:",
            erro
        )


        return jsonify({

            "success":
                False,

            "error":
                "Não foi possível comunicar com o C6 Bank."

        }), 502


    except Exception as erro:

        PEDIDOS[codigo][
            "status"
        ] = "erro_interno_c6"


        print(
            "ERRO INTERNO C6:",
            erro
        )


        return jsonify({

            "success":
                False,

            "error":
                "Erro interno na integração C6."

        }), 500


# =====================================================
# C6 — CONSULTAR PEDIDO PIX
# =====================================================

@app.route(
    "/api/c6/pix/<txid>",
    methods=["GET"]
)
def consultar_cobranca_c6(txid):

    try:

        dados_c6 = (
            consultar_pix_c6(
                txid
            )
        )


        # -----------------------------------------
        # LOCALIZA PEDIDO PELO TXID
        # -----------------------------------------

        codigo_encontrado = None

        for codigo, pedido in PEDIDOS.items():

            if (
                pedido.get("c6_txid")
                == txid
            ):

                codigo_encontrado = (
                    codigo
                )

                break


        status = str(
            dados_c6.get(
                "status",
                ""
            )
        ).upper()


        # -----------------------------------------
        # ATUALIZA PEDIDO
        # -----------------------------------------

        if codigo_encontrado:

            pedido = PEDIDOS[
                codigo_encontrado
            ]

            pedido[
                "c6_status"
            ] = status


            # Cobrança PIX concluída = paga
            if status == "CONCLUIDA":

                finalizar_pedido_pago(
                    codigo_encontrado,
                    "c6"
                )


        return jsonify({

            "success":
                True,

            "order_code":
                codigo_encontrado,

            "status":
                status,

            "c6":
                dados_c6

        })


    except requests.HTTPError as erro:

        return jsonify({

            "success":
                False,

            "error":
                "C6 recusou a consulta.",

            "details":
                str(erro)

        }), 502


    except Exception as erro:

        print(
            "ERRO CONSULTA C6:",
            erro
        )

        return jsonify({

            "success":
                False,

            "error":
                "Não foi possível consultar a cobrança."

        }), 500


# =====================================================
# C6 — WEBHOOK PIX
# =====================================================

@app.route(
    "/webhooks/c6",
    methods=["POST"]
)
def webhook_c6():

    evento = request.get_json(
        silent=True
    ) or {}


    print("=" * 60)
    print("WEBHOOK C6 PIX")
    print(evento)
    print("=" * 60)


    # O webhook PIX pode trazer txid diretamente.
    txid = evento.get(
        "txid"
    )


    # Alguns formatos podem encapsular
    # os PIX recebidos em uma lista.
    if not txid:

        pix_lista = evento.get(
            "pix"
        )

        if (
            isinstance(
                pix_lista,
                list
            )
            and pix_lista
        ):

            txid = (
                pix_lista[0]
                .get("txid")
            )


    if not txid:

        print(
            "Webhook C6 sem TXID."
        )

        return "", 200


    # ---------------------------------------------
    # LOCALIZA PEDIDO
    # ---------------------------------------------

    codigo = None

    for cod, pedido in PEDIDOS.items():

        if (
            pedido.get("c6_txid")
            == txid
        ):

            codigo = cod
            break


    if not codigo:

        print(
            "Webhook C6 sem pedido correlacionado.",
            txid
        )

        return "", 200


    # ---------------------------------------------
    # CONFIRMA DIRETAMENTE NO C6
    # ---------------------------------------------

    try:

        consulta = consultar_pix_c6(
            txid
        )

        status = str(
            consulta.get(
                "status",
                ""
            )
        ).upper()


        PEDIDOS[codigo][
            "c6_status"
        ] = status


        PEDIDOS[codigo][
            "c6_last_query"
        ] = consulta


        # Só libera operação após
        # confirmação direta no banco.
        if status == "CONCLUIDA":

            finalizar_pedido_pago(
                codigo,
                "c6"
            )


    except Exception as erro:

        print(
            "Falha ao confirmar PIX no C6:",
            erro
        )


    return "", 200
# =====================================================
# LOGÍSTICA — WEBHOOK GENÉRICO (FUTURA TRANSPORTADORA)
# =====================================================

@app.route("/webhooks/logistica", methods=["POST"])
def webhook_logistica():

    if LOGISTICA_WEBHOOK_TOKEN:
        esperado = f"Bearer {LOGISTICA_WEBHOOK_TOKEN}"
        if request.headers.get("Authorization") != esperado:
            return jsonify({"error": "Não autorizado."}), 401

    evento = request.get_json(silent=True) or {}
    codigo = evento.get("order_code") or evento.get("code")

    if not codigo or codigo not in PEDIDOS:
        return jsonify({"error": "Pedido não encontrado."}), 404

    pedido = PEDIDOS[codigo]
    pedido.setdefault("delivery", {})

    for campo in ("provider", "status", "tracking_code"):
        if campo in evento:
            pedido["delivery"][campo] = evento[campo]

    emit("to_admin", pedido, broadcast=True)

    return jsonify({"received": True}), 200


# =====================================================
# PAGAR.ME — CRIAR CHECKOUT
# =====================================================

@app.route("/api/pagarme/checkout", methods=["POST"])
def criar_checkout():

    if not PAGARME_SECRET_KEY:
        return jsonify({
            "error": "PAGARME_SECRET_KEY não configurada."
        }), 500

    dados = request.get_json(
        silent=True
    ) or {}

    quantidade = int(
        dados.get("quantidade", 1)
    )

    endereco = str(
        dados.get("endereco", "")
    ).strip()

    if quantidade < 1:
        return jsonify({
            "error": "Quantidade inválida."
        }), 400

    if not endereco:
        return jsonify({
            "error": "Endereço obrigatório."
        }), 400

    # -------------------------------------------------
    # CRIA PEDIDO INTERNO
    # -------------------------------------------------

    codigo = (
        "MAR-"
        + uuid.uuid4().hex[:10].upper()
    )

    valor_total = (
        PRECO_UNITARIO * quantidade
    )

    pedido = {

        "code": codigo,

        "quantity": quantidade,

        "address": endereco,

        "amount": valor_total,

        "status": "aguardando_pagamento",

        "payment_origin": "pagarme",

        "pagarme_id": None,

        "c6_txid": None,

        "fiscal": {
            "status": "aguardando_definicao_fiscal",
            "icms_st": {
                "aplicavel": None,
                "responsavel": None,
                "recolhido_na_origem": None
            }
        },

        "delivery": {
            "provider": None,
            "status": "aguardando_pagamento",
            "tracking_code": None,
            "tracking_url": None
        }

    }

    PEDIDOS[codigo] = pedido
    salvar_pedido_postgres(pedido)


    # -------------------------------------------------
    # CRIA CHECKOUT PAGAR.ME
    # -------------------------------------------------

    payload = {

        "is_building": False,

        "name": f"Maranhão - {codigo}",

        "order_code": codigo,

        "type": "order",

        "max_paid_sessions": 1,

        "payment_settings": {

            "accepted_payment_methods": [
                "credit_card",
                "pix"
            ],

            "credit_card_settings": {

                "operation_type":
                    "auth_and_capture",

                "installments_setup": {

                    "interest_type":
                        "simple"

                }

            }

        },

        "cart_settings": {

            "items": [

                {

                    "amount":
                        PRECO_UNITARIO,

                    "name":
                        "Maranhão Cordial",

                    "description":
                        "Concentrado premium de guaraná",

                    "default_quantity":
                        quantidade

                }

            ]

        }

    }


    # -------------------------------------------------
    # ENVIA PARA PAGAR.ME
    # -------------------------------------------------

    try:

        resposta = requests.post(

            f"{PAGARME_BASE_URL}/paymentlinks",

            auth=(
                PAGARME_SECRET_KEY,
                ""
            ),

            headers={
                "User-Agent":
                    "maranhao-cordial/1.0",
                "Content-Type":
                    "application/json"
            },

            json=payload,

            timeout=20

        )


        dados_pagarme = resposta.json()


        if not resposta.ok:

            print(
                "ERRO PAGAR.ME:",
                dados_pagarme
            )

            PEDIDOS[codigo]["status"] = \
                "erro_pagamento"

            return jsonify({

                "error":
                    "Erro ao criar pagamento.",

                "details":
                    dados_pagarme

            }), 400


        # -------------------------------------------------
        # SALVA ID DO PAGAR.ME
        # -------------------------------------------------

        PEDIDOS[codigo][
            "pagarme_id"
        ] = dados_pagarme.get("id")

        salvar_pedido_postgres(PEDIDOS[codigo])

        checkout_url = \
            dados_pagarme.get("url")


        return jsonify({

            "success": True,

            "order_code":
                codigo,

            "checkout_url":
                checkout_url

        })


    except Exception as erro:

        print(
            "ERRO DE COMUNICAÇÃO:",
            erro
        )

        return jsonify({

            "error":
                "Não foi possível comunicar com o Pagar.me."

        }), 500


# =====================================================
# WEBHOOK PAGAR.ME
# =====================================================

@app.route(
    "/webhooks/pagarme",
    methods=["POST"]
)
def webhook_pagarme():

    evento = request.get_json(
        silent=True
    ) or {}

    print("=" * 60)
    print("WEBHOOK PAGAR.ME")
    print(evento)
    print("=" * 60)


    tipo = evento.get("type")

    dados = evento.get(
        "data",
        {}
    )


    # =================================================
    # PAGAMENTO APROVADO
    # =================================================

    if tipo == "order.paid":

        codigo = dados.get(
            "code"
        )

        if codigo in PEDIDOS:
            finalizar_pedido_pago(codigo, "pagarme")


    # =================================================
    # PAGAMENTO RECUSADO
    # =================================================

    elif tipo == "order.payment_failed":

        codigo = dados.get(
            "code"
        )

        if codigo in PEDIDOS:

            PEDIDOS[codigo][
                "status"
            ] = "pagamento_recusado"

            print(
                f"✕ PEDIDO {codigo} "
                "PAGAMENTO RECUSADO"
            )


    return "", 200


# =====================================================
# LISTAGEM DE PEDIDOS — POSTGRESQL
# =====================================================

def listar_pedidos_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_status,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        criado_em,
                        atualizado_em
                    FROM pedidos
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "codigo": linha[0],
                        "cliente_nome": linha[1],
                        "cliente_email": linha[2],
                        "cliente_whatsapp": linha[3],
                        "quantidade": linha[4],
                        "valor_centavos": linha[5],
                        "status": linha[6],
                        "payment_origin": linha[7],
                        "c6_status": linha[8],
                        "transportadora": linha[9],
                        "status_entrega": linha[10],
                        "tracking_code": linha[11],
                        "criado_em": linha[12].isoformat() if linha[12] else None,
                        "atualizado_em": linha[13].isoformat() if linha[13] else None
                    }
                    for linha in linhas
                ]

    finally:
        conn.close()


def listar_atendimentos_sac_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        atendimento_id,
                        mensagem,
                        resposta,
                        origem,
                        tipo,
                        codigo_pedido,
                        cliente_email,
                        criado_em
                    FROM atendimentos_sac
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "atendimento_id": linha[0],
                        "mensagem": linha[1],
                        "resposta": linha[2],
                        "origem": linha[3],
                        "tipo": linha[4],
                        "codigo_pedido": linha[5],
                        "cliente_email": linha[6],
                        "criado_em": linha[7].isoformat() if linha[7] else None
                    }
                    for linha in linhas
                ]
    finally:
        conn.close()


@app.route(
    "/api/admin/atendimentos",
    methods=["GET"]
)
def admin_listar_atendimentos():

    chave_recebida = request.headers.get("X-Admin-Key")

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        atendimentos = listar_atendimentos_sac_postgres()

        return jsonify({
            "success": True,
            "total": len(atendimentos),
            "atendimentos": atendimentos
        }), 200

    except Exception as erro:
        print("ERRO ADMIN LISTAR ATENDIMENTOS:", erro)

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os atendimentos."
        }), 500


def listar_b2b_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        empresa,
                        cnpj,
                        segmento,
                        responsavel,
                        whatsapp,
                        email,
                        cidade,
                        interesse,
                        mensagem,
                        status,
                        criado_em
                    FROM cadastros_profissionais
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "empresa": linha[0],
                        "cnpj": linha[1],
                        "segmento": linha[2],
                        "responsavel": linha[3],
                        "whatsapp": linha[4],
                        "email": linha[5],
                        "cidade": linha[6],
                        "interesse": linha[7],
                        "mensagem": linha[8],
                        "status": linha[9],
                        "criado_em": linha[10].isoformat() if linha[10] else None
                    }
                    for linha in linhas
                ]
    finally:
        conn.close()


@app.route(
    "/api/admin/b2b",
    methods=["GET"]
)
def admin_listar_b2b():

    chave_recebida = request.headers.get("X-Admin-Key")

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        cadastros = listar_b2b_postgres()

        return jsonify({
            "success": True,
            "total": len(cadastros),
            "cadastros": cadastros
        }), 200

    except Exception as erro:
        print("ERRO ADMIN LISTAR B2B:", erro)

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os cadastros B2B."
        }), 500


def listar_degustacoes_postgres(limite=100):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        empresa,
                        cnpj,
                        segmento,
                        cidade,
                        responsavel,
                        whatsapp,
                        email,
                        mensagem,
                        status,
                        criado_em
                    FROM solicitacoes_degustacao
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (limite,))

                linhas = cur.fetchall()

                return [
                    {
                        "empresa": linha[0],
                        "cnpj": linha[1],
                        "segmento": linha[2],
                        "cidade": linha[3],
                        "responsavel": linha[4],
                        "whatsapp": linha[5],
                        "email": linha[6],
                        "mensagem": linha[7],
                        "status": linha[8],
                        "criado_em": linha[9].isoformat()
                            if linha[9]
                            else None
                    }
                    for linha in linhas
                ]

    finally:
        conn.close()


@app.route(
    "/api/admin/degustacoes",
    methods=["GET"]
)
def admin_listar_degustacoes():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        degustacoes = listar_degustacoes_postgres()

        return jsonify({
            "success": True,
            "total": len(degustacoes),
            "degustacoes": degustacoes
        }), 200

    except Exception as erro:
        print(
            "ERRO ADMIN LISTAR DEGUSTAÇÕES:",
            erro
        )

        return jsonify({
            "success": False,
            "error": "Não foi possível listar as degustações."
        }), 500




# =====================================================
# DOCUMENTOS EMPRESARIAIS — ADMIN
# =====================================================

def extrair_texto_documento(conteudo, mime_type, nome_arquivo):
    mime_type = str(mime_type or "").lower()
    nome_arquivo = str(nome_arquivo or "").lower()

    if (
        mime_type == "application/pdf"
        or nome_arquivo.endswith(".pdf")
    ):
        try:
            leitor = PdfReader(io.BytesIO(conteudo))

            partes = []

            for pagina in leitor.pages:
                texto_pagina = (
                    pagina.extract_text()
                    or ""
                ).strip()

                if texto_pagina:
                    partes.append(texto_pagina)

            return "\n\n".join(partes).strip()

        except Exception as erro:
            print(
                "ERRO EXTRAIR TEXTO PDF:",
                erro
            )
            return ""

    if (
        mime_type.startswith("text/")
        or nome_arquivo.endswith(".txt")
        or nome_arquivo.endswith(".md")
    ):
        try:
            return conteudo.decode(
                "utf-8",
                errors="replace"
            ).strip()
        except Exception:
            return ""

    return ""


CATEGORIAS_DOCUMENTOS = {
    "societario",
    "produto",
    "regulatorio",
    "comercial",
    "financeiro",
    "estrategia",
    "eventos_parcerias",
    "investidores",
    "outros"
}

NIVEIS_ACESSO_DOCUMENTOS = {
    "direcao",
    "socios",
    "investidor"
}


def validar_admin_request():
    chave = request.headers.get("X-Admin-Key")

    return bool(
        ADMIN_API_KEY
        and chave == ADMIN_API_KEY
    )


@app.route(
    "/api/admin/documentos",
    methods=["GET"]
)
def admin_listar_documentos():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        nome,
                        nome_original,
                        categoria,
                        descricao,
                        versao,
                        data_documento,
                        nivel_acesso,
                        usar_na_ia,
                        status_documento,
                        substitui_documento_id,
                        mime_type,
                        tamanho_bytes,
                        criado_em,
                        atualizado_em
                    FROM documentos_empresariais
                    ORDER BY criado_em DESC
                """)

                documentos = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(documentos),
            "documentos": documentos
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/documentos/upload",
    methods=["POST"]
)
def admin_upload_documento():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    arquivo = request.files.get("arquivo")

    if not arquivo or not arquivo.filename:
        return jsonify({
            "success": False,
            "error": "Arquivo obrigatório."
        }), 400

    nome = str(
        request.form.get("nome", "")
    ).strip() or arquivo.filename

    categoria = str(
        request.form.get("categoria", "outros")
    ).strip()

    descricao = str(
        request.form.get("descricao", "")
    ).strip()

    versao = str(
        request.form.get("versao", "")
    ).strip() or None

    data_documento = str(
        request.form.get("data_documento", "")
    ).strip() or None

    nivel_acesso = str(
        request.form.get("nivel_acesso", "direcao")
    ).strip()

    status_documento = str(
        request.form.get("status_documento", "vigente")
    ).strip()

    substitui_documento_id = str(
        request.form.get("substitui_documento_id", "")
    ).strip() or None

    usar_na_ia = str(
        request.form.get("usar_na_ia", "false")
    ).lower() in {
        "1",
        "true",
        "sim",
        "on"
    }

    if categoria not in CATEGORIAS_DOCUMENTOS:
        return jsonify({
            "success": False,
            "error": "Categoria inválida."
        }), 400

    if nivel_acesso not in NIVEIS_ACESSO_DOCUMENTOS:
        return jsonify({
            "success": False,
            "error": "Nível de acesso inválido."
        }), 400

    if status_documento not in {
        "vigente",
        "rascunho",
        "historico"
    }:
        return jsonify({
            "success": False,
            "error": "Status documental inválido."
        }), 400

    conteudo = arquivo.read()

    texto_extraido = extrair_texto_documento(
        conteudo,
        arquivo.mimetype,
        arquivo.filename
    )

    # V1: limite de 15 MB por documento
    limite = 15 * 1024 * 1024

    if len(conteudo) > limite:
        return jsonify({
            "success": False,
            "error": "Arquivo excede o limite de 15 MB."
        }), 413

    documento_id = str(uuid.uuid4())

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                if substitui_documento_id:
                    cur.execute("""
                        UPDATE documentos_empresariais
                        SET
                            status_documento = 'historico',
                            atualizado_em = NOW()
                        WHERE id = %s
                    """, (
                        substitui_documento_id,
                    ))

                cur.execute("""
                    INSERT INTO documentos_empresariais (
                        id,
                        nome,
                        nome_original,
                        categoria,
                        descricao,
                        versao,
                        data_documento,
                        nivel_acesso,
                        usar_na_ia,
                        status_documento,
                        substitui_documento_id,
                        mime_type,
                        tamanho_bytes,
                        conteudo,
                        texto_extraido
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    documento_id,
                    nome,
                    arquivo.filename,
                    categoria,
                    descricao,
                    versao,
                    data_documento,
                    nivel_acesso,
                    usar_na_ia,
                    status_documento,
                    substitui_documento_id,
                    arquivo.mimetype,
                    len(conteudo),
                    psycopg2.Binary(conteudo),
                    texto_extraido
                ))

        return jsonify({
            "success": True,
            "documento_id": documento_id,
            "nome": nome
        }), 201

    finally:
        conn.close()




@app.route(
    "/api/admin/documentos/<documento_id>/status",
    methods=["PATCH"]
)
def admin_alterar_status_documento(documento_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    status_documento = str(
        dados.get(
            "status_documento",
            ""
        )
    ).strip()

    if status_documento not in {
        "vigente",
        "rascunho",
        "historico"
    }:
        return jsonify({
            "success": False,
            "error": "Status documental inválido."
        }), 400

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    UPDATE documentos_empresariais
                    SET
                        status_documento = %s,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING id
                """, (
                    status_documento,
                    documento_id
                ))

                atualizado = cur.fetchone()

        if not atualizado:
            return jsonify({
                "success": False,
                "error": "Documento não encontrado."
            }), 404

        return jsonify({
            "success": True,
            "documento_id": documento_id,
            "status_documento": status_documento
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/documentos/reprocessar",
    methods=["POST"]
)
def admin_reprocessar_documentos():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    documento_id = str(
        dados.get(
            "documento_id",
            ""
        )
    ).strip()

    somente_sem_texto = bool(
        dados.get(
            "somente_sem_texto",
            True
        )
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                if documento_id:

                    cur.execute("""
                        SELECT
                            id,
                            nome,
                            nome_original,
                            mime_type,
                            conteudo,
                            texto_extraido
                        FROM documentos_empresariais
                        WHERE id = %s
                    """, (
                        documento_id,
                    ))

                    documentos = cur.fetchall()

                else:

                    if somente_sem_texto:

                        cur.execute("""
                            SELECT
                                id,
                                nome,
                                nome_original,
                                mime_type,
                                conteudo,
                                texto_extraido
                            FROM documentos_empresariais
                            WHERE
                                texto_extraido IS NULL
                                OR TRIM(texto_extraido) = ''
                            ORDER BY criado_em ASC
                        """)

                    else:

                        cur.execute("""
                            SELECT
                                id,
                                nome,
                                nome_original,
                                mime_type,
                                conteudo,
                                texto_extraido
                            FROM documentos_empresariais
                            ORDER BY criado_em ASC
                        """)

                    documentos = cur.fetchall()

                processados = []
                falhas = []

                for documento in documentos:

                    try:

                        conteudo = bytes(
                            documento["conteudo"]
                        )

                        texto_extraido = (
                            extrair_texto_documento(
                                conteudo,
                                documento["mime_type"],
                                documento["nome_original"]
                            )
                        )

                        cur.execute("""
                            UPDATE documentos_empresariais
                            SET
                                texto_extraido = %s,
                                atualizado_em = NOW()
                            WHERE id = %s
                        """, (
                            texto_extraido,
                            documento["id"]
                        ))

                        processados.append({
                            "id":
                                str(documento["id"]),

                            "nome":
                                documento["nome"],

                            "caracteres_extraidos":
                                len(
                                    texto_extraido
                                    or ""
                                ),

                            "texto_extraido":
                                bool(
                                    texto_extraido
                                    and texto_extraido.strip()
                                )
                        })

                    except Exception as erro_documento:

                        print(
                            "ERRO REPROCESSAR DOCUMENTO:",
                            documento["id"],
                            erro_documento
                        )

                        falhas.append({
                            "id":
                                str(documento["id"]),

                            "nome":
                                documento["nome"],

                            "erro":
                                str(
                                    erro_documento
                                )
                        })

        return jsonify({
            "success": True,
            "total_encontrados":
                len(documentos),

            "total_processados":
                len(processados),

            "total_falhas":
                len(falhas),

            "processados":
                processados,

            "falhas":
                falhas
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/documentos/<documento_id>/download",
    methods=["GET"]
)
def admin_download_documento(documento_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        nome_original,
                        mime_type,
                        conteudo
                    FROM documentos_empresariais
                    WHERE id = %s
                """, (
                    documento_id,
                ))

                documento = cur.fetchone()

        if not documento:
            return jsonify({
                "success": False,
                "error": "Documento não encontrado."
            }), 404

        return send_file(
            io.BytesIO(
                bytes(documento["conteudo"])
            ),
            mimetype=(
                documento["mime_type"]
                or "application/octet-stream"
            ),
            as_attachment=True,
            download_name=documento["nome_original"]
        )

    finally:
        conn.close()



# =====================================================
# DECISÕES EMPRESARIAIS — ADMIN
# =====================================================

HORIZONTES_DECISOES = {
    "estrategico",
    "tatico",
    "operacional"
}

STATUS_DECISOES = {
    "ativa",
    "concluida",
    "cancelada",
    "substituida"
}


@app.route(
    "/api/admin/decisoes",
    methods=["GET"]
)
def admin_listar_decisoes():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        titulo,
                        descricao,
                        area,
                        horizonte,
                        status,
                        responsavel,
                        data_decisao,
                        documento_id,
                        criado_em,
                        atualizado_em
                    FROM decisoes_empresariais
                    ORDER BY
                        data_decisao DESC,
                        criado_em DESC
                """)

                decisoes = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(decisoes),
            "decisoes": decisoes
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/decisoes",
    methods=["POST"]
)
def admin_criar_decisao():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    titulo = str(
        dados.get("titulo", "")
    ).strip()

    descricao = str(
        dados.get("descricao", "")
    ).strip()

    area = str(
        dados.get("area", "")
    ).strip()

    horizonte = str(
        dados.get("horizonte", "")
    ).strip()

    status = str(
        dados.get("status", "ativa")
    ).strip()

    responsavel = str(
        dados.get("responsavel", "")
    ).strip() or None

    data_decisao = str(
        dados.get("data_decisao", "")
    ).strip() or None

    documento_id = str(
        dados.get("documento_id", "")
    ).strip() or None

    if not titulo:
        return jsonify({
            "success": False,
            "error": "Título obrigatório."
        }), 400

    if not descricao:
        return jsonify({
            "success": False,
            "error": "Descrição obrigatória."
        }), 400

    if not area:
        return jsonify({
            "success": False,
            "error": "Área obrigatória."
        }), 400

    if horizonte not in HORIZONTES_DECISOES:
        return jsonify({
            "success": False,
            "error": "Horizonte inválido."
        }), 400

    if status not in STATUS_DECISOES:
        return jsonify({
            "success": False,
            "error": "Status inválido."
        }), 400

    decisao_id = str(uuid.uuid4())

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO decisoes_empresariais (
                        id,
                        titulo,
                        descricao,
                        area,
                        horizonte,
                        status,
                        responsavel,
                        data_decisao,
                        documento_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        COALESCE(%s::date, CURRENT_DATE),
                        %s
                    )
                """, (
                    decisao_id,
                    titulo,
                    descricao,
                    area,
                    horizonte,
                    status,
                    responsavel,
                    data_decisao,
                    documento_id
                ))

        return jsonify({
            "success": True,
            "decisao_id": decisao_id,
            "titulo": titulo
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/decisoes/<decisao_id>",
    methods=["PATCH"]
)
def admin_atualizar_decisao(decisao_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos = []
    valores = []

    if "titulo" in dados:
        titulo = str(
            dados.get("titulo", "")
        ).strip()

        if not titulo:
            return jsonify({
                "success": False,
                "error": "Título inválido."
            }), 400

        campos.append("titulo = %s")
        valores.append(titulo)

    if "descricao" in dados:
        descricao = str(
            dados.get("descricao", "")
        ).strip()

        if not descricao:
            return jsonify({
                "success": False,
                "error": "Descrição inválida."
            }), 400

        campos.append("descricao = %s")
        valores.append(descricao)

    if "area" in dados:
        area = str(
            dados.get("area", "")
        ).strip()

        if not area:
            return jsonify({
                "success": False,
                "error": "Área inválida."
            }), 400

        campos.append("area = %s")
        valores.append(area)

    if "horizonte" in dados:
        horizonte = str(
            dados.get("horizonte", "")
        ).strip()

        if horizonte not in HORIZONTES_DECISOES:
            return jsonify({
                "success": False,
                "error": "Horizonte inválido."
            }), 400

        campos.append("horizonte = %s")
        valores.append(horizonte)

    if "status" in dados:
        status = str(
            dados.get("status", "")
        ).strip()

        if status not in STATUS_DECISOES:
            return jsonify({
                "success": False,
                "error": "Status inválido."
            }), 400

        campos.append("status = %s")
        valores.append(status)

    if "responsavel" in dados:
        responsavel = str(
            dados.get("responsavel", "")
        ).strip() or None

        campos.append("responsavel = %s")
        valores.append(responsavel)

    if "data_decisao" in dados:
        data_decisao = str(
            dados.get("data_decisao", "")
        ).strip()

        if not data_decisao:
            return jsonify({
                "success": False,
                "error": "Data inválida."
            }), 400

        campos.append("data_decisao = %s")
        valores.append(data_decisao)

    if "documento_id" in dados:
        documento_id = str(
            dados.get("documento_id", "")
        ).strip() or None

        campos.append("documento_id = %s")
        valores.append(documento_id)

    if not campos:
        return jsonify({
            "success": False,
            "error": "Nenhuma alteração informada."
        }), 400

    campos.append("atualizado_em = NOW()")

    valores.append(decisao_id)

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                query = (
                    "UPDATE decisoes_empresariais SET "
                    + ", ".join(campos)
                    + " WHERE id = %s "
                    + "RETURNING id"
                )

                cur.execute(
                    query,
                    tuple(valores)
                )

                atualizado = cur.fetchone()

        if not atualizado:
            return jsonify({
                "success": False,
                "error": "Decisão não encontrada."
            }), 404

        return jsonify({
            "success": True,
            "decisao_id": decisao_id
        }), 200

    finally:
        conn.close()


# =====================================================
# IA EMPRESARIAL — MARANHÃO CORDIAL
# =====================================================


def carregar_documentos_para_ia(limite_documentos=20, limite_caracteres=50000):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        nome,
                        categoria,
                        descricao,
                        versao,
                        data_documento,
                        nivel_acesso,
                        texto_extraido,
                        atualizado_em
                    FROM documentos_empresariais
                    WHERE
                        usar_na_ia = TRUE
                        AND status_documento = 'vigente'
                        AND texto_extraido IS NOT NULL
                        AND TRIM(texto_extraido) <> ''
                    ORDER BY
                        atualizado_em DESC,
                        criado_em DESC
                    LIMIT %s
                """, (
                    limite_documentos,
                ))

                documentos = cur.fetchall()

        partes = []
        total_caracteres = 0
        usados = []

        for documento in documentos:

            texto_documento = (
                documento["texto_extraido"]
                or ""
            ).strip()

            if not texto_documento:
                continue

            cabecalho = (
                "\n\n=== DOCUMENTO EMPRESARIAL ===\n"
                f"Nome: {documento['nome']}\n"
                f"Categoria: {documento['categoria']}\n"
                f"Versão: {documento['versao'] or 'não informada'}\n"
                f"Data: {documento['data_documento'] or 'não informada'}\n"
                f"Nível de acesso: {documento['nivel_acesso']}\n"
                f"Descrição: {documento['descricao'] or 'não informada'}\n"
                "Conteúdo:\n"
            )

            restante = (
                limite_caracteres
                - total_caracteres
                - len(cabecalho)
            )

            if restante <= 0:
                break

            trecho = texto_documento[:restante]

            partes.append(
                cabecalho + trecho
            )

            total_caracteres += (
                len(cabecalho)
                + len(trecho)
            )

            usados.append({
                "id": str(documento["id"]),
                "nome": documento["nome"],
                "categoria": documento["categoria"],
                "versao": documento["versao"]
            })

            if total_caracteres >= limite_caracteres:
                break

        contexto = "".join(partes)

        if contexto:
            contexto = (
                "\n\nBASE DOCUMENTAL EMPRESARIAL AUTORIZADA:\n"
                "Use os documentos abaixo como fonte interna. "
                "Não trate hipótese, proposta ou documento de desenvolvimento "
                "como fato definitivo. Respeite categoria, versão, descrição "
                "e eventuais ressalvas presentes no próprio documento."
                + contexto
            )

        return {
            "contexto": contexto,
            "documentos_usados": usados,
            "total_documentos": len(usados),
            "total_caracteres": total_caracteres
        }

    finally:
        conn.close()




@app.route(
    "/api/admin/acoes",
    methods=["GET"]
)
def admin_listar_acoes():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,
                        responsavel,
                        data_limite,
                        decisao_id,
                        resultado,
                        criado_em,
                        atualizado_em
                    FROM acoes_empresariais
                    ORDER BY
                        CASE prioridade
                            WHEN 'critica' THEN 1
                            WHEN 'alta' THEN 2
                            WHEN 'media' THEN 3
                            WHEN 'baixa' THEN 4
                            ELSE 5
                        END,
                        criado_em DESC
                """)

                acoes = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(acoes),
            "acoes": acoes
        })

    finally:
        conn.close()


@app.route(
    "/api/admin/acoes",
    methods=["POST"]
)
def admin_criar_acao():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    titulo = str(
        dados.get("titulo", "")
    ).strip()

    descricao = str(
        dados.get("descricao", "")
    ).strip()

    area = str(
        dados.get("area", "")
    ).strip().lower()

    prioridade = str(
        dados.get("prioridade", "media")
    ).strip().lower()

    status = str(
        dados.get("status", "pendente")
    ).strip().lower()

    responsavel = str(
        dados.get("responsavel", "")
    ).strip() or None

    data_limite = (
        dados.get("data_limite")
        or None
    )

    decisao_id = (
        dados.get("decisao_id")
        or None
    )

    resultado = str(
        dados.get("resultado", "")
    ).strip() or None

    if not titulo:
        return jsonify({
            "success": False,
            "error": "Título obrigatório."
        }), 400

    if not descricao:
        return jsonify({
            "success": False,
            "error": "Descrição obrigatória."
        }), 400

    if not area:
        return jsonify({
            "success": False,
            "error": "Área obrigatória."
        }), 400

    if prioridade not in {
        "baixa",
        "media",
        "alta",
        "critica"
    }:
        return jsonify({
            "success": False,
            "error": "Prioridade inválida."
        }), 400

    if status not in {
        "pendente",
        "em_andamento",
        "concluida",
        "cancelada"
    }:
        return jsonify({
            "success": False,
            "error": "Status inválido."
        }), 400

    acao_id = str(uuid.uuid4())

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO acoes_empresariais (
                        id,
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,
                        responsavel,
                        data_limite,
                        decisao_id,
                        resultado
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    RETURNING
                        id,
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,
                        responsavel,
                        data_limite,
                        decisao_id,
                        resultado,
                        criado_em,
                        atualizado_em
                """, (
                    acao_id,
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    status,
                    responsavel,
                    data_limite,
                    decisao_id,
                    resultado
                ))

                acao = cur.fetchone()

        return jsonify({
            "success": True,
            "acao": acao
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/acoes/<acao_id>",
    methods=["PATCH"]
)
def admin_atualizar_acao(acao_id):

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos_permitidos = {
        "titulo",
        "descricao",
        "area",
        "prioridade",
        "status",
        "responsavel",
        "data_limite",
        "decisao_id",
        "resultado"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo == "prioridade":
            valor = str(valor).strip().lower()

            if valor not in {
                "baixa",
                "media",
                "alta",
                "critica"
            }:
                return jsonify({
                    "success": False,
                    "error": "Prioridade inválida."
                }), 400

        if campo == "status":
            valor = str(valor).strip().lower()

            if valor not in {
                "pendente",
                "em_andamento",
                "concluida",
                "cancelada"
            }:
                return jsonify({
                    "success": False,
                    "error": "Status inválido."
                }), 400

        if campo in {
            "responsavel",
            "data_limite",
            "decisao_id",
            "resultado"
        } and valor == "":
            valor = None

        atualizacoes.append(
            f"{campo} = %s"
        )
        valores.append(valor)

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error": "Nenhum campo válido informado."
        }), 400

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(acao_id)

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE acoes_empresariais
                    SET {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING
                        id,
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,
                        responsavel,
                        data_limite,
                        decisao_id,
                        resultado,
                        criado_em,
                        atualizado_em
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                acao = cur.fetchone()

                if not acao:
                    return jsonify({
                        "success": False,
                        "error": "Ação não encontrada."
                    }), 404

        return jsonify({
            "success": True,
            "acao": acao
        })

    finally:
        conn.close()





@app.route(
    "/api/admin/crm/leads",
    methods=["GET"]
)
def admin_listar_leads_crm():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        nome,
                        empresa,
                        tipo_lead,
                        origem,
                        canal,
                        cidade,
                        estado,
                        contato,
                        interesse,
                        estagio,
                        valor_potencial_centavos,
                        cac_centavos,
                        receita_acumulada_centavos,
                        responsavel,
                        proximo_followup,
                        observacoes,
                        criado_em,
                        atualizado_em
                    FROM leads_crm
                    ORDER BY
                        atualizado_em DESC,
                        criado_em DESC
                """)

                leads = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(leads),
            "leads": leads
        })

    finally:
        conn.close()


@app.route(
    "/api/admin/crm/leads",
    methods=["POST"]
)
def admin_criar_lead_crm():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    nome = str(
        dados.get("nome", "")
    ).strip() or None

    empresa = str(
        dados.get("empresa", "")
    ).strip() or None

    tipo_lead = str(
        dados.get("tipo_lead", "")
    ).strip().lower()

    origem = str(
        dados.get("origem", "")
    ).strip().lower()

    canal = str(
        dados.get("canal", "")
    ).strip().lower() or None

    cidade = str(
        dados.get("cidade", "")
    ).strip() or None

    estado = str(
        dados.get("estado", "")
    ).strip() or None

    contato = str(
        dados.get("contato", "")
    ).strip() or None

    interesse = str(
        dados.get("interesse", "")
    ).strip() or None

    estagio = str(
        dados.get("estagio", "novo")
    ).strip().lower()

    valor_potencial_centavos = (
        dados.get("valor_potencial_centavos")
    )

    cac_centavos = (
        dados.get("cac_centavos")
    )

    receita_acumulada_centavos = (
        dados.get(
            "receita_acumulada_centavos",
            0
        )
        or 0
    )

    responsavel = str(
        dados.get("responsavel", "")
    ).strip() or None

    proximo_followup = (
        dados.get("proximo_followup")
        or None
    )

    observacoes = str(
        dados.get("observacoes", "")
    ).strip() or None

    tipos_validos = {
        "b2b",
        "b2c",
        "parceiro",
        "influenciador",
        "fornecedor",
        "outro"
    }

    estagios_validos = {
        "novo",
        "qualificacao",
        "degustacao",
        "proposta",
        "negociacao",
        "cliente",
        "perdido"
    }

    if tipo_lead not in tipos_validos:
        return jsonify({
            "success": False,
            "error": "Tipo de lead inválido."
        }), 400

    if not origem:
        return jsonify({
            "success": False,
            "error": "Origem obrigatória."
        }), 400

    if estagio not in estagios_validos:
        return jsonify({
            "success": False,
            "error": "Estágio inválido."
        }), 400

    lead_id = str(uuid.uuid4())

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO leads_crm (
                        id,
                        nome,
                        empresa,
                        tipo_lead,
                        origem,
                        canal,
                        cidade,
                        estado,
                        contato,
                        interesse,
                        estagio,
                        valor_potencial_centavos,
                        cac_centavos,
                        receita_acumulada_centavos,
                        responsavel,
                        proximo_followup,
                        observacoes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s
                    )
                    RETURNING *
                """, (
                    lead_id,
                    nome,
                    empresa,
                    tipo_lead,
                    origem,
                    canal,
                    cidade,
                    estado,
                    contato,
                    interesse,
                    estagio,
                    valor_potencial_centavos,
                    cac_centavos,
                    receita_acumulada_centavos,
                    responsavel,
                    proximo_followup,
                    observacoes
                ))

                lead = cur.fetchone()

        return jsonify({
            "success": True,
            "lead": lead
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/crm/leads/<lead_id>",
    methods=["PATCH"]
)
def admin_atualizar_lead_crm(lead_id):

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos_permitidos = {
        "nome",
        "empresa",
        "tipo_lead",
        "origem",
        "canal",
        "cidade",
        "estado",
        "contato",
        "interesse",
        "estagio",
        "valor_potencial_centavos",
        "cac_centavos",
        "receita_acumulada_centavos",
        "responsavel",
        "proximo_followup",
        "observacoes"
    }

    estagios_validos = {
        "novo",
        "qualificacao",
        "degustacao",
        "proposta",
        "negociacao",
        "cliente",
        "perdido"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo == "estagio":
            valor = str(valor).strip().lower()

            if valor not in estagios_validos:
                return jsonify({
                    "success": False,
                    "error": "Estágio inválido."
                }), 400

        if campo in {
            "nome",
            "empresa",
            "canal",
            "cidade",
            "estado",
            "contato",
            "interesse",
            "responsavel",
            "proximo_followup",
            "observacoes"
        } and valor == "":
            valor = None

        atualizacoes.append(
            f"{campo} = %s"
        )
        valores.append(valor)

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error": "Nenhum campo válido informado."
        }), 400

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(lead_id)

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE leads_crm
                    SET {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING *
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                lead = cur.fetchone()

                if not lead:
                    return jsonify({
                        "success": False,
                        "error": "Lead não encontrado."
                    }), 404

        return jsonify({
            "success": True,
            "lead": lead
        })

    finally:
        conn.close()




def carregar_leads_crm_para_ia(limite=50):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        nome,
                        empresa,
                        tipo_lead,
                        origem,
                        canal,
                        cidade,
                        estado,
                        interesse,
                        estagio,
                        valor_potencial_centavos,
                        cac_centavos,
                        receita_acumulada_centavos,
                        responsavel,
                        proximo_followup,
                        atualizado_em
                    FROM leads_crm
                    ORDER BY
                        CASE estagio
                            WHEN 'negociacao' THEN 1
                            WHEN 'proposta' THEN 2
                            WHEN 'degustacao' THEN 3
                            WHEN 'qualificacao' THEN 4
                            WHEN 'novo' THEN 5
                            WHEN 'cliente' THEN 6
                            WHEN 'perdido' THEN 7
                            ELSE 8
                        END,
                        atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                leads = cur.fetchall()

        linhas = []

        for lead in leads:

            valor_potencial = (
                (lead["valor_potencial_centavos"] or 0)
                / 100
            )

            cac = (
                (lead["cac_centavos"] or 0)
                / 100
            )

            receita = (
                (lead["receita_acumulada_centavos"] or 0)
                / 100
            )

            linhas.append(
                (
                    f"- {lead['nome'] or 'Sem nome'}"
                    f" | Empresa: {lead['empresa'] or 'não informada'}"
                    f" | Tipo: {lead['tipo_lead']}"
                    f" | Origem: {lead['origem']}"
                    f" | Canal: {lead['canal'] or 'não informado'}"
                    f" | Estágio: {lead['estagio']}"
                    f" | Valor potencial: R$ {valor_potencial:.2f}"
                    f" | CAC: R$ {cac:.2f}"
                    f" | Receita acumulada: R$ {receita:.2f}"
                    f" | Interesse: {lead['interesse'] or 'não informado'}"
                    f" | Responsável: {lead['responsavel'] or 'não definido'}"
                    f" | Próximo follow-up: "
                    f"{lead['proximo_followup'] or 'não definido'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\nCRM / FUNIL DE LEADS\n"
                "Use estes dados para analisar qualidade do pipeline, "
                "origem dos leads, estágio, CAC, valor potencial, "
                "receita acumulada e necessidade de follow-up. "
                "Não trate valor potencial como receita realizada.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "leads": leads,
            "contexto": contexto
        }

    finally:
        conn.close()


def carregar_acoes_para_ia(limite=30):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,
                        responsavel,
                        data_limite,
                        decisao_id,
                        resultado,
                        criado_em,
                        atualizado_em
                    FROM acoes_empresariais
                    WHERE status <> 'cancelada'
                    ORDER BY
                        CASE prioridade
                            WHEN 'critica' THEN 1
                            WHEN 'alta' THEN 2
                            WHEN 'media' THEN 3
                            WHEN 'baixa' THEN 4
                            ELSE 5
                        END,
                        COALESCE(
                            data_limite,
                            CURRENT_DATE + INTERVAL '100 years'
                        ),
                        criado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                acoes = cur.fetchall()

        linhas = []

        for acao in acoes:

            linhas.append(
                (
                    f"- [{acao['status']}] "
                    f"{acao['titulo']} | "
                    f"Área: {acao['area']} | "
                    f"Prioridade: {acao['prioridade']} | "
                    f"Responsável: "
                    f"{acao['responsavel'] or 'não definido'} | "
                    f"Data limite: "
                    f"{acao['data_limite'] or 'não definida'} | "
                    f"Descrição: {acao['descricao']} | "
                    f"Resultado: "
                    f"{acao['resultado'] or 'ainda não registrado'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "AÇÕES EMPRESARIAIS ATUAIS\n"
                "Considere estas ações como memória operacional "
                "da empresa. Não trate ação pendente ou em andamento "
                "como concluída. Quando houver resultado registrado, "
                "use-o como aprendizado operacional.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "acoes": acoes,
            "contexto": contexto
        }

    finally:
        conn.close()


def carregar_decisoes_para_ia(limite=30):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        id,
                        titulo,
                        descricao,
                        area,
                        horizonte,
                        status,
                        responsavel,
                        data_decisao,
                        documento_id,
                        atualizado_em
                    FROM decisoes_empresariais
                    WHERE status = 'ativa'
                    ORDER BY
                        data_decisao DESC,
                        atualizado_em DESC
                    LIMIT %s
                """, (limite,))

                decisoes = cur.fetchall()

        partes = []
        usadas = []

        for decisao in decisoes:

            partes.append(
                "\n=== DECISÃO EMPRESARIAL ATIVA ===\n"
                f"Título: {decisao['titulo']}\n"
                f"Área: {decisao['area']}\n"
                f"Horizonte: {decisao['horizonte']}\n"
                f"Data: {decisao['data_decisao']}\n"
                f"Responsável: {decisao['responsavel'] or 'não informado'}\n"
                f"Descrição: {decisao['descricao']}\n"
            )

            usadas.append({
                "id": str(decisao["id"]),
                "titulo": decisao["titulo"],
                "area": decisao["area"],
                "horizonte": decisao["horizonte"]
            })

        contexto = ""

        if partes:
            contexto = (
                "\n\nMEMÓRIA DE DECISÕES EMPRESARIAIS ATIVAS:\n"
                "As decisões abaixo são escolhas internas já tomadas. "
                "Considere-as como orientação institucional enquanto "
                "permanecerem ativas. Se uma recomendação entrar em "
                "conflito com uma decisão ativa, indique o conflito.\n"
                + "".join(partes)
            )

        return {
            "contexto": contexto,
            "total_decisoes": len(usadas),
            "decisoes_usadas": usadas
        }

    finally:
        conn.close()


def obter_resumo_empresarial_postgres():
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM pedidos
                """)
                total_pedidos = cur.fetchone()[0]

                cur.execute("""
                    SELECT COALESCE(
                        SUM(valor_centavos),
                        0
                    )
                    FROM pedidos
                """)
                valor_pedidos_centavos = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM cadastros_profissionais
                """)
                total_b2b = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM solicitacoes_degustacao
                """)
                total_degustacoes = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM atendimentos_sac
                """)
                total_atendimentos = cur.fetchone()[0]

                cur.execute("""
                    SELECT
                        codigo,
                        cliente_nome,
                        status,
                        status_entrega,
                        valor_centavos,
                        criado_em
                    FROM pedidos
                    ORDER BY criado_em DESC
                    LIMIT 10
                """)
                pedidos_recentes = cur.fetchall()

                cur.execute("""
                    SELECT
                        empresa,
                        segmento,
                        cidade,
                        interesse,
                        status,
                        criado_em
                    FROM cadastros_profissionais
                    ORDER BY criado_em DESC
                    LIMIT 10
                """)
                leads_recentes = cur.fetchall()

                cur.execute("""
                    SELECT
                        atendimento_id,
                        mensagem,
                        tipo,
                        criado_em
                    FROM atendimentos_sac
                    ORDER BY criado_em DESC
                    LIMIT 10
                """)
                atendimentos_recentes = cur.fetchall()

        return {
            "total_pedidos":
                total_pedidos,

            "valor_pedidos_centavos":
                int(valor_pedidos_centavos or 0),

            "total_b2b":
                total_b2b,

            "total_degustacoes":
                total_degustacoes,

            "total_atendimentos":
                total_atendimentos,

            "pedidos_recentes": [
                {
                    "codigo": linha[0],
                    "cliente_nome": linha[1],
                    "status": linha[2],
                    "status_entrega": linha[3],
                    "valor_centavos": linha[4],
                    "criado_em":
                        linha[5].isoformat()
                        if linha[5]
                        else None
                }
                for linha in pedidos_recentes
            ],

            "leads_recentes": [
                {
                    "empresa": linha[0],
                    "segmento": linha[1],
                    "cidade": linha[2],
                    "interesse": linha[3],
                    "status": linha[4],
                    "criado_em":
                        linha[5].isoformat()
                        if linha[5]
                        else None
                }
                for linha in leads_recentes
            ],

            "atendimentos_recentes": [
                {
                    "atendimento_id": linha[0],
                    "mensagem": linha[1],
                    "tipo": linha[2],
                    "criado_em":
                        linha[3].isoformat()
                        if linha[3]
                        else None
                }
                for linha in atendimentos_recentes
            ]
        }

    finally:
        conn.close()


@app.route(
    "/api/admin/ia-empresarial",
    methods=["POST"]
)
def ia_empresarial():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    pergunta = str(
        dados.get(
            "pergunta",
            ""
        )
    ).strip()

    if not pergunta:
        return jsonify({
            "success": False,
            "error": "Pergunta obrigatória."
        }), 400

    if not openai_client:
        return jsonify({
            "success": False,
            "error":
                "IA empresarial indisponível."
        }), 503

    try:
        resumo = (
            obter_resumo_empresarial_postgres()
        )

        documentos_ia = (
            carregar_documentos_para_ia()
        )

        contexto_documental = (
            documentos_ia["contexto"]
            or ""
        )

        decisoes_ia = (
            carregar_decisoes_para_ia()
        )

        contexto_decisoes = (
            decisoes_ia["contexto"]
            or ""
        )

        acoes_ia = (
            carregar_acoes_para_ia()
        )

        contexto_acoes = (
            acoes_ia["contexto"]
            or ""
        )

        crm_ia = (
            carregar_leads_crm_para_ia()
        )

        contexto_crm = (
            crm_ia["contexto"]
            or ""
        )

        contexto_operacional = (
            "\n\nDADOS ATUAIS DO SISTEMA:\n"
            + str(resumo)
        )

        resposta = openai_client.responses.create(
            model="gpt-5-mini",

            text={
                "format": {
                    "type": "json_schema",
                    "name": "analise_empresarial",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "resposta": {
                                "type": "string"
                            },
                            "acoes_sugeridas": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "titulo": {
                                            "type": "string"
                                        },
                                        "descricao": {
                                            "type": "string"
                                        },
                                        "area": {
                                            "type": "string",
                                            "enum": [
                                                "comercial",
                                                "financeiro",
                                                "operacional",
                                                "produto",
                                                "regulatorio",
                                                "marketing",
                                                "tecnologia",
                                                "estrategia"
                                            ]
                                        },
                                        "prioridade": {
                                            "type": "string",
                                            "enum": [
                                                "baixa",
                                                "media",
                                                "alta",
                                                "critica"
                                            ]
                                        },
                                        "justificativa": {
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "titulo",
                                        "descricao",
                                        "area",
                                        "prioridade",
                                        "justificativa"
                                    ],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": [
                            "resposta",
                            "acoes_sugeridas"
                        ],
                        "additionalProperties": False
                    }
                }
            },

            instructions=(
                "Você é a inteligência empresarial privada "
                "da Maranhão Cordial. "

                "Seu usuário é a direção da empresa, não o consumidor final. "

                + CONTEXTO_MARANHAO
                + CONTEXTO_EMPRESARIAL_INTERNO
                + HIERARQUIA_DECISAO_EMPRESARIAL
                + contexto_documental
                + contexto_decisoes
                + contexto_acoes
                + contexto_crm
                + contexto_operacional +

                "\nAnalise negócios com rigor. "
                "Separe fatos, hipóteses, riscos e oportunidades. "
                "Use os dados atuais do sistema quando forem relevantes. "
                "Não invente números ou fatos ausentes. "
                "Quando faltar informação, diga exatamente o que falta. "

                "Todo número, prazo, meta, percentual, preço, volume ou KPI "
                "que não esteja presente nos dados atuais do sistema, "
                "nos documentos internos vigentes ou nas decisões empresariais "
                "ativas deve ser explicitamente identificado como SUGESTÃO, "
                "ESTIMATIVA ou HIPÓTESE. "
                "Nunca apresente números sugeridos como fatos, metas aprovadas "
                "ou decisões já tomadas pela empresa. "

                "Você pode recomendar prioridades comerciais, "
                "identificar padrões, analisar leads, sugerir próximos passos, "
                "examinar oportunidades B2B e interpretar sinais do negócio. "

                "Você NÃO possui autorização para assumir compromissos, "
                "alterar preços, aceitar contratos, conceder descontos, "
                "enviar mensagens, fazer pagamentos ou executar negociações "
                "sem ferramenta e autorização específicas. "

                "Responda de forma executiva, clara e objetiva. "
                "Quando útil, apresente uma recomendação concreta."
            ),

            input=pergunta,

            reasoning={
                "effort": "low"
            },

            max_output_tokens=1600
        )

        texto_bruto = (
            resposta.output_text
            or ""
        ).strip()

        texto = ""
        acoes_sugeridas = []

        if texto_bruto:
            try:
                dados_ia = json.loads(
                    texto_bruto
                )

                texto = str(
                    dados_ia.get(
                        "resposta",
                        ""
                    )
                ).strip()

                acoes_sugeridas = (
                    dados_ia.get(
                        "acoes_sugeridas",
                        []
                    )
                    or []
                )

            except Exception as erro_json:
                print(
                    "AVISO JSON IA EMPRESARIAL:",
                    erro_json
                )

                texto = texto_bruto
                acoes_sugeridas = []

        if not texto:
            resposta_retry = openai_client.responses.create(
                model="gpt-5-mini",

                instructions=(
                    "Você é a inteligência empresarial privada da Maranhão Cordial. "
                    "Faça uma análise executiva direta. "
                    "Use somente fatos presentes no contexto e nos dados fornecidos. "
                    "Não invente números. "
                    "Indique exatamente três prioridades empresariais, "
                    "explicando brevemente por que cada uma é importante. "
                    + CONTEXTO_MARANHAO
                    + CONTEXTO_EMPRESARIAL_INTERNO
                    + HIERARQUIA_DECISAO_EMPRESARIAL
                    + contexto_documental
                    + contexto_decisoes
                    + contexto_acoes
                    + contexto_crm
                    + contexto_operacional
                ),

                input=pergunta,

                reasoning={
                    "effort": "low"
                },

                max_output_tokens=1600
            )

            texto = (
                resposta_retry.output_text
                or ""
            ).strip()

            acoes_sugeridas = []

        if not texto:
            texto = (
                "Os dados foram consultados, mas a análise não pôde ser "
                "gerada nesta tentativa. Tente novamente."
            )

            acoes_sugeridas = []

        registrar_auditoria(
            categoria="ia",
            acao="analise_empresarial",
            ator_tipo="ia",
            ator_id="maranhao-empresarial-v1",
            origem="admin",
            entidade_tipo="empresa",
            entidade_id="maranhao-cordial",
            status="concluido",
            dados_entrada={
                "pergunta": pergunta
            },
            dados_saida={
                "acoes_sugeridas":
                    acoes_sugeridas,
                "documentos_consultados":
                    documentos_ia["total_documentos"],
                "decisoes_consultadas":
                    decisoes_ia["total_decisoes"],
                "acoes_consultadas":
                    len(acoes_ia["acoes"]),
                "leads_crm_consultados":
                    len(crm_ia["leads"])
            }
        )

        return jsonify({
            "success": True,
            "agent":
                "maranhao-empresarial-v1",
            "resposta":
                texto,
            "dados_consultados": {
                "pedidos":
                    resumo["total_pedidos"],
                "b2b":
                    resumo["total_b2b"],
                "degustacoes":
                    resumo["total_degustacoes"],
                "atendimentos":
                    resumo["total_atendimentos"],
                "documentos":
                    documentos_ia["total_documentos"],
                "decisoes":
                    decisoes_ia["total_decisoes"],
                "acoes":
                    len(acoes_ia["acoes"]),
                "leads_crm":
                    len(crm_ia["leads"])
            },
            "documentos_usados":
                documentos_ia["documentos_usados"],
            "decisoes_usadas":
                decisoes_ia["decisoes_usadas"],
            "acoes_usadas":
                [
                    {
                        "id": str(acao["id"]),
                        "titulo": acao["titulo"],
                        "area": acao["area"],
                        "prioridade": acao["prioridade"],
                        "status": acao["status"]
                    }
                    for acao in acoes_ia["acoes"]
                ],
            "acoes_sugeridas":
                acoes_sugeridas
        }), 200

    except Exception as erro:

        print(
            "ERRO IA EMPRESARIAL:",
            erro
        )

        return jsonify({
            "success": False,
            "error":
                "Não foi possível executar "
                "a análise empresarial."
        }), 500


# =====================================================
# ADMIN — LISTAR PEDIDOS
# =====================================================

@app.route(
    "/api/admin/pedidos",
    methods=["GET"]
)
def admin_listar_pedidos():

    chave_recebida = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave_recebida != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        pedidos = listar_pedidos_postgres()

        return jsonify({
            "success": True,
            "total": len(pedidos),
            "pedidos": pedidos
        }), 200

    except Exception as erro:
        print(
            "ERRO ADMIN LISTAR PEDIDOS:",
            erro
        )

        return jsonify({
            "success": False,
            "error": "Não foi possível listar os pedidos."
        }), 500


# =====================================================
# CONSULTAR PEDIDO
# =====================================================

@app.route(
    "/api/pedido/<codigo>",
    methods=["GET"]
)
def consultar_pedido(codigo):

    try:
        pedido = buscar_pedido_postgres(
            codigo.strip()
        )

    except Exception as erro:
        print(
            "ERRO CONSULTAR PEDIDO:",
            erro
        )
        pedido = None

    if not pedido:
        pedido = PEDIDOS.get(
            codigo
        )

    if not pedido:
        return jsonify({
            "error": "Pedido não encontrado."
        }), 404

    return jsonify(
        pedido
    )


# =====================================================
# WEBSOCKET
# =====================================================

@socketio.on(
    "new_ancestral_order"
)
def handle_new_order(payload):

    print(
        "Evento recebido:",
        payload
    )

    # ATENÇÃO:
    # Não liberamos produção/entrega
    # aqui.
    #
    # O pedido só deve ser liberado
    # após o webhook order.paid.


# =====================================================
# ROTA DE ARQUIVOS
# =====================================================

@app.route("/api/openai/status", methods=["GET"])
def openai_status():
    return jsonify({
        "openai_configured": bool(OPENAI_API_KEY)
    })

@app.route("/api/openai/teste", methods=["GET"])
def openai_teste():

    try:

        resposta = openai_client.responses.create(
            model="gpt-5-mini",
            input="Responda apenas: Maranhão IA funcionando."
        )

        return jsonify({
            "success": True,
            "resposta": resposta.output_text
        }), 200

    except Exception as erro:

        print(
            "ERRO TESTE OPENAI:",
            erro
        )

        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500

def buscar_pedido_postgres(codigo):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        codigo,
                        cliente_nome,
                        cliente_email,
                        cliente_whatsapp,
                        cpf_cnpj,
                        endereco,
                        quantidade,
                        valor_centavos,
                        status,
                        payment_origin,
                        c6_txid,
                        c6_status,
                        pagarme_id,
                        transportadora,
                        status_entrega,
                        tracking_code,
                        tracking_url,
                        criado_em,
                        atualizado_em
                    FROM pedidos
                    WHERE codigo = %s
                    LIMIT 1
                """, (codigo,))

                linha = cur.fetchone()

                if not linha:
                    return None

                return {
                    "codigo": linha[0],
                    "cliente_nome": linha[1],
                    "cliente_email": linha[2],
                    "cliente_whatsapp": linha[3],
                    "cpf_cnpj": linha[4],
                    "endereco": linha[5],
                    "quantidade": linha[6],
                    "valor_centavos": linha[7],
                    "status": linha[8],
                    "payment_origin": linha[9],
                    "c6_txid": linha[10],
                    "c6_status": linha[11],
                    "pagarme_id": linha[12],
                    "transportadora": linha[13],
                    "status_entrega": linha[14],
                    "tracking_code": linha[15],
                    "tracking_url": linha[16],
                    "criado_em": linha[17].isoformat() if linha[17] else None,
                    "atualizado_em": linha[18].isoformat() if linha[18] else None
                }
    finally:
        conn.close()


@app.route("/api/pedidos/teste-postgres", methods=["POST"])
def teste_pedido_postgres():
    codigo = "MAR-TESTE-" + uuid.uuid4().hex[:8].upper()

    pedido_teste = {
        "code": codigo,
        "cliente_nome": "Cliente Teste",
        "cliente_email": "teste@maranhaocordial.com.br",
        "cliente_whatsapp": None,
        "cpf_cnpj": None,
        "address": "Endereço de teste",
        "quantity": 1,
        "amount": 5990,
        "status": "teste",
        "payment_origin": "teste",
        "c6_txid": None,
        "c6_status": None,
        "pagarme_id": None,
        "delivery": {
            "provider": None,
            "status": "teste",
            "tracking_code": None,
            "tracking_url": None
        }
    }

    try:
        salvar_pedido_postgres(pedido_teste)
        return jsonify({
            "success": True,
            "codigo": codigo,
            "mensagem": "Pedido de teste salvo no PostgreSQL."
        }), 201
    except Exception as erro:
        print("ERRO TESTE POSTGRES PEDIDO:", erro)
        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


@app.route(
    "/api/pedidos/<codigo>",
    methods=["GET"]
)
def consultar_pedido_postgres(codigo):
    try:
        pedido = buscar_pedido_postgres(codigo.strip())

        if not pedido:
            return jsonify({
                "success": False,
                "error": "Pedido não encontrado."
            }), 404

        return jsonify({
            "success": True,
            "pedido": pedido
        }), 200

    except Exception as erro:
        print("ERRO CONSULTAR PEDIDO POSTGRES:", erro)
        return jsonify({
            "success": False,
            "error": "Não foi possível consultar o pedido agora."
        }), 500


@app.route(
    "/<path:filename>"
)
def arquivos(filename):

    return send_from_directory(
        FRONTEND_FOLDER,
        filename
    )


# =====================================================
# ROTAS
# =====================================================

print(
    "\nROTAS REGISTRADAS:\n"
)

for regra in app.url_map.iter_rules():

    print(regra)


# =====================================================
# INICIALIZAÇÃO
# =====================================================


# Cria as tabelas automaticamente quando o serviço inicia.
if DATABASE_URL:
    try:
        inicializar_banco()
        print("✓ BANCO DE LEADS INICIALIZADO")
    except Exception as erro:
        print("ERRO AO INICIALIZAR BANCO DE LEADS:", erro)
else:
    print("AVISO: DATABASE_URL não configurada; formulários B2B não persistirão dados.")


if __name__ == "__main__":

    porta = int(
        os.environ.get(
            "PORT",
            3000
        )
    )

    socketio.run(

        app,

        host="0.0.0.0",

        port=porta,

        debug=True

    )