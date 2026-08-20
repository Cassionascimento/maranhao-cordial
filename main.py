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

                        modo_execucao VARCHAR(30)
                            NOT NULL DEFAULT 'requer_aprovacao',

                        estado_execucao VARCHAR(40)
                            NOT NULL DEFAULT 'nao_iniciada',

                        executor VARCHAR(180),

                        tentativas_execucao INTEGER
                            NOT NULL DEFAULT 0,

                        autorizado_por VARCHAR(180),
                        autorizado_em TIMESTAMPTZ,

                        ultimo_erro TEXT,
                        executado_em TIMESTAMPTZ,

                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)

                # Migração segura para bancos já existentes.

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    modo_execucao VARCHAR(30)
                    NOT NULL DEFAULT 'requer_aprovacao'
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    estado_execucao VARCHAR(40)
                    NOT NULL DEFAULT 'nao_iniciada'
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    executor VARCHAR(180)
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    tentativas_execucao INTEGER
                    NOT NULL DEFAULT 0
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    autorizado_por VARCHAR(180)
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    autorizado_em TIMESTAMPTZ
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    ultimo_erro TEXT
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    executado_em TIMESTAMPTZ
                """)


                # Campos estruturados do motor de execução.

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    tipo_execucao VARCHAR(80)
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    payload_execucao TEXT
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
                # MATRIZ DE FABRICAS PARCEIRAS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fabricas_parceiras (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(220) NOT NULL,
                        razao_social VARCHAR(220),
                        cnpj VARCHAR(30),

                        cidade VARCHAR(120),
                        estado VARCHAR(80),
                        regiao VARCHAR(80),

                        contato_nome VARCHAR(180),
                        contato_email VARCHAR(220),
                        contato_whatsapp VARCHAR(40),
                        site TEXT,

                        status_comercial VARCHAR(40)
                            NOT NULL DEFAULT 'prospectada',

                        status_regulatorio VARCHAR(40)
                            NOT NULL DEFAULT 'nao_verificado',

                        mapa_status TEXT,

                        lote_minimo_unidades INTEGER,
                        lote_minimo_litros NUMERIC(12,2),

                        capacidade_maxima_unidades INTEGER,
                        capacidade_maxima_litros NUMERIC(12,2),

                        custo_unitario_centavos BIGINT,
                        custo_litro_centavos BIGINT,

                        prazo_producao_dias INTEGER,

                        embalagem_vidro BOOLEAN,

                        embalagem_pet BOOLEAN,

                        envase_200ml BOOLEAN,

                        rotulagem BOOLEAN,

                        responsabilidade_tecnica BOOLEAN,

                        analises_laboratoriais BOOLEAN,

                        pode_copack BOOLEAN,

                        ncm_informado VARCHAR(20),

                        observacoes TEXT,

                        fonte_dados VARCHAR(180),
                        verificado_por VARCHAR(180),
                        verificado_em TIMESTAMPTZ,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fabricas_parceiras_estado
                    ON fabricas_parceiras (estado)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fabricas_parceiras_status
                    ON fabricas_parceiras (
                        status_comercial,
                        status_regulatorio
                    )
                """)

                # Ajuste seguro para bancos já existentes.
                cur.execute("""
                    ALTER TABLE fabricas_parceiras
                    ALTER COLUMN mapa_status TYPE TEXT
                """)


                # Permite distinguir:
                # TRUE = confirmado sim
                # FALSE = confirmado não
                # NULL = ainda não verificado
                cur.execute("""
                    ALTER TABLE fabricas_parceiras
                    ALTER COLUMN embalagem_vidro DROP NOT NULL,
                    ALTER COLUMN embalagem_vidro DROP DEFAULT,
                    ALTER COLUMN embalagem_pet DROP NOT NULL,
                    ALTER COLUMN embalagem_pet DROP DEFAULT,
                    ALTER COLUMN envase_200ml DROP NOT NULL,
                    ALTER COLUMN envase_200ml DROP DEFAULT,
                    ALTER COLUMN rotulagem DROP NOT NULL,
                    ALTER COLUMN rotulagem DROP DEFAULT,
                    ALTER COLUMN responsabilidade_tecnica DROP NOT NULL,
                    ALTER COLUMN responsabilidade_tecnica DROP DEFAULT,
                    ALTER COLUMN analises_laboratoriais DROP NOT NULL,
                    ALTER COLUMN analises_laboratoriais DROP DEFAULT,
                    ALTER COLUMN pode_copack DROP NOT NULL,
                    ALTER COLUMN pode_copack DROP DEFAULT
                """)

                # ==========================================
                # CENARIOS FISCAIS / CUSTO TRIBUTARIO
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cenarios_fiscais (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(220) NOT NULL,

                        fabrica_id UUID,

                        uf_origem VARCHAR(2) NOT NULL,
                        uf_destino VARCHAR(2) NOT NULL,

                        finalidade VARCHAR(40)
                            NOT NULL DEFAULT 'revenda',

                        tipo_destinatario VARCHAR(40),
                        contribuinte_icms BOOLEAN,

                        ncm VARCHAR(20),

                        cfop VARCHAR(10),
                        csosn VARCHAR(10),

                        icms_st_aplicavel BOOLEAN,
                        icms_st_retido_origem BOOLEAN,
                        antecipacao_aplicavel BOOLEAN,
                        difal_aplicavel BOOLEAN,

                        aliquota_icms_origem NUMERIC(8,4),
                        aliquota_icms_destino NUMERIC(8,4),

                        aliquota_simples NUMERIC(8,4),

                        valor_compra_centavos BIGINT,
                        valor_venda_centavos BIGINT,

                        icms_st_centavos BIGINT,
                        antecipacao_centavos BIGINT,
                        difal_centavos BIGINT,
                        das_estimado_centavos BIGINT,

                        carga_tributaria_total_centavos BIGINT,

                        status_calculo VARCHAR(40)
                            NOT NULL DEFAULT 'aguardando_dados',

                        fonte_regra TEXT,
                        observacoes TEXT,

                        verificado_por VARCHAR(180),
                        verificado_em TIMESTAMPTZ,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_cenario_fabrica
                            FOREIGN KEY (fabrica_id)
                            REFERENCES fabricas_parceiras(id)
                            ON DELETE SET NULL
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_cenarios_fiscais_rota
                    ON cenarios_fiscais (
                        uf_origem,
                        uf_destino
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_cenarios_fiscais_ncm
                    ON cenarios_fiscais (ncm)
                """)

                # ==========================================
                # ROTAS LOGISTICAS / FRETE
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rotas_logisticas (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(220) NOT NULL,

                        fabrica_id UUID,
                        cenario_fiscal_id UUID,

                        transportadora VARCHAR(220),

                        cidade_origem VARCHAR(120),
                        uf_origem VARCHAR(2) NOT NULL,

                        cidade_destino VARCHAR(120),
                        uf_destino VARCHAR(2) NOT NULL,

                        quantidade_unidades INTEGER,
                        peso_total_kg NUMERIC(12,3),
                        volume_total_m3 NUMERIC(12,4),

                        modalidade VARCHAR(80),
                        condicao_frete VARCHAR(20),

                        valor_frete_centavos BIGINT,
                        seguro_centavos BIGINT,
                        pedagio_centavos BIGINT,
                        outras_despesas_centavos BIGINT,

                        prazo_minimo_dias INTEGER,
                        prazo_maximo_dias INTEGER,

                        custo_total_logistico_centavos BIGINT,
                        custo_logistico_unitario_centavos BIGINT,

                        status_cotacao VARCHAR(40)
                            NOT NULL DEFAULT 'aguardando_cotacao',

                        validade_cotacao DATE,

                        fonte_dados TEXT,
                        observacoes TEXT,

                        verificado_por VARCHAR(180),
                        verificado_em TIMESTAMPTZ,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_rota_fabrica
                            FOREIGN KEY (fabrica_id)
                            REFERENCES fabricas_parceiras(id)
                            ON DELETE SET NULL,

                        CONSTRAINT fk_rota_cenario_fiscal
                            FOREIGN KEY (cenario_fiscal_id)
                            REFERENCES cenarios_fiscais(id)
                            ON DELETE SET NULL
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_rotas_logisticas_ufs
                    ON rotas_logisticas (
                        uf_origem,
                        uf_destino
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_rotas_logisticas_fabrica
                    ON rotas_logisticas (fabrica_id)
                """)

                # ==========================================
                # CONTATOS ESTRATEGICOS / REDE EMPRESARIAL
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS contatos_estrategicos (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(180),
                        empresa VARCHAR(220),

                        tipo VARCHAR(50) NOT NULL,
                        cargo VARCHAR(180),

                        telefone VARCHAR(50),
                        email VARCHAR(220),

                        cidade VARCHAR(120),
                        estado VARCHAR(2),

                        fabrica_id UUID,

                        status_relacao VARCHAR(50)
                            NOT NULL DEFAULT 'prospectado',

                        origem_contato VARCHAR(120),

                        resumo TEXT,
                        capacidades TEXT,
                        restricoes TEXT,
                        proximo_passo TEXT,

                        fonte_dados TEXT,

                        verificado_por VARCHAR(180),
                        verificado_em TIMESTAMPTZ,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_contato_fabrica
                            FOREIGN KEY (fabrica_id)
                            REFERENCES fabricas_parceiras(id)
                            ON DELETE SET NULL
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_contatos_estrategicos_tipo
                    ON contatos_estrategicos (tipo)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_contatos_estrategicos_empresa
                    ON contatos_estrategicos (empresa)
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


def avaliar_politica_execucao(
    area,
    titulo="",
    descricao=""
):
    """
    Define o nível de autonomia permitido para uma ação empresarial.

    Retorna:
    - automatico
    - requer_aprovacao
    - somente_humano
    """

    texto = (
        f"{area} {titulo} {descricao}"
    ).lower()

    # -------------------------------------------------
    # VERMELHO — SEM EXECUÇÃO AUTÔNOMA
    # -------------------------------------------------

    termos_somente_humano = (
        "pagamento",
        "pagar",
        "transferência",
        "transferencia",
        "pix",
        "contrato",
        "assinar",
        "assinatura",
        "jurídico",
        "juridico",
        "preço",
        "preco",
        "desconto",
        "negociação",
        "negociacao",
        "empréstimo",
        "emprestimo",
        "investimento",
        "societário",
        "societario",
        "alterar estratégia",
        "alterar estrategia"
    )

    if any(
        termo in texto
        for termo in termos_somente_humano
    ):
        return "somente_humano"

    # -------------------------------------------------
    # AMARELO — EXIGE APROVAÇÃO
    # -------------------------------------------------

    termos_requer_aprovacao = (
        "enviar mensagem",
        "enviar email",
        "enviar e-mail",
        "whatsapp",
        "instagram",
        "facebook",
        "cliente",
        "fornecedor",
        "distribuidor",
        "proposta",
        "follow-up",
        "followup",
        "contato comercial"
    )

    if any(
        termo in texto
        for termo in termos_requer_aprovacao
    ):
        return "requer_aprovacao"

    # -------------------------------------------------
    # VERDE — AUTOMAÇÃO INTERNA DE BAIXO RISCO
    # -------------------------------------------------

    termos_automaticos = (
        "classificar lead",
        "priorizar lead",
        "organizar lead",
        "resumir",
        "analisar",
        "monitorar",
        "atualizar métrica",
        "atualizar metrica",
        "registrar",
        "criar alerta",
        "identificar",
        "comparar"
    )

    if any(
        termo in texto
        for termo in termos_automaticos
    ):
        return "automatico"

    # -------------------------------------------------
    # PADRÃO CONSERVADOR
    # -------------------------------------------------

    return "requer_aprovacao"


def executar_acao_controlada(acao):
    """
    Motor central de execução governada.

    Nenhuma ação é executada apenas porque a IA a sugeriu.
    É necessário:
    1. modo_execucao compatível;
    2. estado_execucao autorizado;
    3. tipo_execucao presente na whitelist.
    """

    if not acao:
        return {
            "success": False,
            "erro": "Ação inexistente."
        }

    modo = str(
        acao.get("modo_execucao")
        or "requer_aprovacao"
    ).strip()

    estado = str(
        acao.get("estado_execucao")
        or "nao_iniciada"
    ).strip()

    tipo = str(
        acao.get("tipo_execucao")
        or ""
    ).strip()

    # Nunca permitir execução autônoma
    # para ações classificadas como humanas.
    if modo == "somente_humano":
        return {
            "success": False,
            "erro":
                "Ação reservada à execução humana."
        }

    if modo == "requer_aprovacao" and estado != "autorizada":
        return {
            "success": False,
            "erro":
                "Ação ainda não autorizada."
        }

    if modo == "automatico" and estado not in {
        "autorizada",
        "nao_iniciada"
    }:
        return {
            "success": False,
            "erro":
                "Estado incompatível com execução automática."
        }

    # ---------------------------------------------
    # EXECUTORES AUTORIZADOS
    # ---------------------------------------------

    executores = {
        "registrar_analise_interna":
            executar_registro_analise_interna,

        "atualizar_lead_crm":
            executar_atualizacao_lead_crm
    }

    executor = executores.get(tipo)

    if not executor:
        return {
            "success": False,
            "erro":
                "Tipo de execução não autorizado."
        }

    return executor(acao)


def executar_atualizacao_lead_crm(acao):
    """
    Executor real e controlado do CRM.

    Pode alterar somente:
    - estagio
    - responsavel
    - proximo_followup
    - observacoes

    Não envia mensagens, não altera preços,
    não faz pagamentos e não negocia com terceiros.
    """

    acao_id = str(
        acao.get("id") or ""
    ).strip()

    if not acao_id:
        return {
            "success": False,
            "erro": "Ação sem ID."
        }

    payload = acao.get(
        "payload_execucao"
    )

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {
                "success": False,
                "erro":
                    "payload_execucao não contém JSON válido."
            }

    if not isinstance(payload, dict):
        return {
            "success": False,
            "erro":
                "payload_execucao deve ser um objeto JSON."
        }

    lead_id = str(
        payload.get("lead_id") or ""
    ).strip()

    if not lead_id:
        return {
            "success": False,
            "erro": "lead_id obrigatório."
        }

    alteracoes = payload.get(
        "alteracoes"
    )

    if not isinstance(alteracoes, dict):
        return {
            "success": False,
            "erro":
                "alteracoes deve ser um objeto JSON."
        }

    campos_permitidos = {
        "estagio",
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
    alteracoes_validas = {}

    for campo, valor in alteracoes.items():

        if campo not in campos_permitidos:
            return {
                "success": False,
                "erro":
                    f"Campo não autorizado: {campo}"
            }

        if campo == "estagio":
            valor = str(
                valor
            ).strip().lower()

            if valor not in estagios_validos:
                return {
                    "success": False,
                    "erro":
                        "Estágio de CRM inválido."
                }

        if campo in {
            "responsavel",
            "proximo_followup",
            "observacoes"
        } and valor == "":
            valor = None

        atualizacoes.append(
            f"{campo} = %s"
        )

        valores.append(
            valor
        )

        alteracoes_validas[
            campo
        ] = valor

    if not atualizacoes:
        return {
            "success": False,
            "erro":
                "Nenhuma alteração de CRM informada."
        }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                valores_lead = list(
                    valores
                )

                valores_lead.append(
                    lead_id
                )

                query = f"""
                    UPDATE leads_crm
                    SET
                        {", ".join(atualizacoes)},
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """

                cur.execute(
                    query,
                    tuple(valores_lead)
                )

                lead = cur.fetchone()

                if not lead:
                    raise ValueError(
                        "Lead não encontrado."
                    )

                resultado_texto = (
                    "CRM atualizado automaticamente: "
                    + ", ".join(
                        alteracoes_validas.keys()
                    )
                )

                cur.execute("""
                    UPDATE acoes_empresariais
                    SET
                        estado_execucao = 'executada',
                        status = 'concluida',
                        executor = 'ia_empresarial',
                        tentativas_execucao =
                            tentativas_execucao + 1,
                        executado_em = NOW(),
                        resultado = %s,
                        ultimo_erro = NULL,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    resultado_texto,
                    acao_id
                ))

                acao_atualizada = (
                    cur.fetchone()
                )

        registrar_auditoria(
            categoria="execucao",
            acao="lead_crm_atualizado",
            ator_tipo="ia",
            ator_id="maranhao-empresarial-v1",
            origem="motor_execucao",
            entidade_tipo="lead_crm",
            entidade_id=lead_id,
            status="executada",
            dados_entrada={
                "acao_id":
                    acao_id,
                "alteracoes":
                    alteracoes_validas
            },
            dados_saida={
                "lead_id":
                    lead_id,
                "estagio":
                    lead.get("estagio"),
                "responsavel":
                    lead.get("responsavel"),
                "proximo_followup":
                    lead.get(
                        "proximo_followup"
                    )
            }
        )

        return {
            "success": True,
            "acao":
                acao_atualizada,
            "lead":
                lead
        }

    except Exception as erro:

        try:
            conn2 = get_db_connection()

            with conn2:
                with conn2.cursor() as cur:
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            estado_execucao = 'falhou',
                            tentativas_execucao =
                                tentativas_execucao + 1,
                            ultimo_erro = %s,
                            atualizado_em = NOW()
                        WHERE id = %s
                    """, (
                        str(erro),
                        acao_id
                    ))

            conn2.close()

        except Exception as erro_registro:
            print(
                "ERRO REGISTRAR FALHA CRM:",
                erro_registro
            )

        registrar_auditoria(
            categoria="execucao",
            acao="atualizacao_lead_crm_falhou",
            ator_tipo="ia",
            ator_id="maranhao-empresarial-v1",
            origem="motor_execucao",
            entidade_tipo="lead_crm",
            entidade_id=lead_id,
            status="falhou",
            erro=str(erro)
        )

        return {
            "success": False,
            "erro": str(erro)
        }

    finally:
        conn.close()


def executar_registro_analise_interna(acao):
    """
    Primeiro executor automático seguro.

    Não envia mensagem, não movimenta dinheiro,
    não altera contrato e não representa a empresa
    perante terceiros.

    Apenas registra a conclusão de uma tarefa
    analítica interna.
    """

    acao_id = str(
        acao.get("id")
        or ""
    )

    if not acao_id:
        return {
            "success": False,
            "erro": "Ação sem ID."
        }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    UPDATE acoes_empresariais
                    SET
                        estado_execucao = 'executada',
                        status = 'concluida',
                        executor = 'ia_empresarial',
                        tentativas_execucao =
                            tentativas_execucao + 1,
                        executado_em = NOW(),
                        resultado = COALESCE(
                            resultado,
                            'Execução interna concluída automaticamente.'
                        ),
                        ultimo_erro = NULL,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    acao_id,
                ))

                atualizada = cur.fetchone()

        registrar_auditoria(
            categoria="execucao",
            acao="acao_executada",
            ator_tipo="ia",
            ator_id="maranhao-empresarial-v1",
            origem="motor_execucao",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status="executada",
            dados_saida={
                "tipo_execucao":
                    acao.get("tipo_execucao"),
                "resultado":
                    atualizada.get("resultado")
                    if atualizada else None
            }
        )

        return {
            "success": True,
            "acao": atualizada
        }

    except Exception as erro:

        try:
            conn2 = get_db_connection()

            with conn2:
                with conn2.cursor() as cur:
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            estado_execucao = 'falhou',
                            tentativas_execucao =
                                tentativas_execucao + 1,
                            ultimo_erro = %s,
                            atualizado_em = NOW()
                        WHERE id = %s
                    """, (
                        str(erro),
                        acao_id
                    ))

            conn2.close()

        except Exception as erro_registro:
            print(
                "ERRO REGISTRAR FALHA EXECUÇÃO:",
                erro_registro
            )

        registrar_auditoria(
            categoria="execucao",
            acao="acao_falhou",
            ator_tipo="ia",
            ator_id="maranhao-empresarial-v1",
            origem="motor_execucao",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status="falhou",
            erro=str(erro)
        )

        return {
            "success": False,
            "erro": str(erro)
        }

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
                        modo_execucao,
                        estado_execucao,
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

    modo_execucao = avaliar_politica_execucao(
        area=area,
        titulo=titulo,
        descricao=descricao
    )

    if modo_execucao == "automatico":
        estado_execucao = "autorizada"

    elif modo_execucao == "requer_aprovacao":
        estado_execucao = "aguardando_aprovacao"

    else:
        estado_execucao = "bloqueada_humano"

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
                        resultado,
                        modo_execucao,
                        estado_execucao
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s
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
                    resultado,
                    modo_execucao,
                    estado_execucao
                ))

                acao = cur.fetchone()

        origem_acao = str(
            dados.get("origem", "manual")
        ).strip() or "manual"

        aprovado_por = str(
            dados.get("aprovado_por", "")
        ).strip() or None

        if origem_acao == "ia_empresarial":
            acao_auditoria = "sugestao_ia_aprovada"
            status_auditoria = "aprovado"
            requer_aprovacao = True
        else:
            acao_auditoria = "acao_empresarial_criada"
            status_auditoria = "criado"
            requer_aprovacao = False

        registrar_auditoria(
            categoria="acao_empresarial",
            acao=acao_auditoria,
            ator_tipo="admin",
            ator_id="admin",
            origem=origem_acao,
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status=status_auditoria,
            requer_aprovacao=requer_aprovacao,
            aprovado_por=aprovado_por,
            dados_entrada={
                "titulo": titulo,
                "area": area,
                "prioridade": prioridade,
                "status": status
            },
            dados_saida={
                "acao_id": acao_id
            }
        )

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
        "resultado",
        "modo_execucao",
        "estado_execucao",
        "tipo_execucao",
        "payload_execucao"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo == "modo_execucao":
            valor = str(valor).strip().lower()

            if valor not in {
                "automatico",
                "requer_aprovacao",
                "somente_humano"
            }:
                return jsonify({
                    "success": False,
                    "error": "Modo de execução inválido."
                }), 400

        if campo == "estado_execucao":
            valor = str(valor).strip().lower()

            if valor not in {
                "nao_iniciada",
                "aguardando_aprovacao",
                "autorizada",
                "executando",
                "executada",
                "falhou",
                "bloqueada_humano"
            }:
                return jsonify({
                    "success": False,
                    "error": "Estado de execução inválido."
                }), 400

        if campo == "tipo_execucao":
            valor = str(valor).strip()

            if valor not in {
                "",
                "registrar_analise_interna",
                "atualizar_lead_crm"
            }:
                return jsonify({
                    "success": False,
                    "error": "Tipo de execução não autorizado."
                }), 400

            if valor == "":
                valor = None

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

        status_novo = str(
            acao.get("status") or ""
        ).strip().lower()

        if status_novo == "concluida":
            acao_auditoria = "acao_concluida"
            status_auditoria = "concluida"

        elif status_novo == "cancelada":
            acao_auditoria = "acao_cancelada"
            status_auditoria = "cancelada"

        else:
            acao_auditoria = "acao_empresarial_atualizada"
            status_auditoria = status_novo or "atualizada"

        campos_alterados = {
            chave: valor
            for chave, valor in dados.items()
            if chave in campos_permitidos
        }

        registrar_auditoria(
            categoria="acao_empresarial",
            acao=acao_auditoria,
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status=status_auditoria,
            dados_entrada={
                "campos_alterados":
                    list(campos_alterados.keys()),
                "prioridade":
                    campos_alterados.get("prioridade"),
                "status":
                    campos_alterados.get("status"),
                "resultado_informado":
                    bool(
                        campos_alterados.get("resultado")
                    )
            },
            dados_saida={
                "status_atual":
                    acao.get("status"),
                "prioridade_atual":
                    acao.get("prioridade"),
                "responsavel":
                    acao.get("responsavel"),
                "tem_resultado":
                    bool(
                        acao.get("resultado")
                    )
            }
        )

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




@app.route(
    "/api/admin/fabricas",
    methods=["GET"]
)
def admin_listar_fabricas():

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
                    SELECT *
                    FROM fabricas_parceiras
                    ORDER BY
                        CASE status_comercial
                            WHEN 'homologada' THEN 1
                            WHEN 'negociacao' THEN 2
                            WHEN 'qualificada' THEN 3
                            WHEN 'prospectada' THEN 4
                            ELSE 5
                        END,
                        atualizado_em DESC
                """)

                fabricas = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(fabricas),
            "fabricas": fabricas
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/fabricas",
    methods=["POST"]
)
def admin_criar_fabrica():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    nome = str(
        dados.get("nome", "")
    ).strip()

    if not nome:
        return jsonify({
            "success": False,
            "error": "Nome da fábrica obrigatório."
        }), 400

    status_comercial = str(
        dados.get(
            "status_comercial",
            "prospectada"
        )
    ).strip().lower()

    status_regulatorio = str(
        dados.get(
            "status_regulatorio",
            "nao_verificado"
        )
    ).strip().lower()

    status_comerciais_validos = {
        "prospectada",
        "qualificada",
        "negociacao",
        "homologada",
        "inativa",
        "descartada"
    }

    status_regulatorios_validos = {
        "nao_verificado",
        "em_analise",
        "regular",
        "pendente",
        "incompativel"
    }

    if status_comercial not in status_comerciais_validos:
        return jsonify({
            "success": False,
            "error": "Status comercial inválido."
        }), 400

    if status_regulatorio not in status_regulatorios_validos:
        return jsonify({
            "success": False,
            "error": "Status regulatório inválido."
        }), 400

    fabrica_id = str(
        uuid.uuid4()
    )

    campos = {
        "razao_social": dados.get("razao_social"),
        "cnpj": dados.get("cnpj"),
        "cidade": dados.get("cidade"),
        "estado": dados.get("estado"),
        "regiao": dados.get("regiao"),
        "contato_nome": dados.get("contato_nome"),
        "contato_email": dados.get("contato_email"),
        "contato_whatsapp": dados.get("contato_whatsapp"),
        "site": dados.get("site"),
        "mapa_status": dados.get("mapa_status"),
        "lote_minimo_unidades": dados.get("lote_minimo_unidades"),
        "lote_minimo_litros": dados.get("lote_minimo_litros"),
        "capacidade_maxima_unidades": dados.get("capacidade_maxima_unidades"),
        "capacidade_maxima_litros": dados.get("capacidade_maxima_litros"),
        "custo_unitario_centavos": dados.get("custo_unitario_centavos"),
        "custo_litro_centavos": dados.get("custo_litro_centavos"),
        "prazo_producao_dias": dados.get("prazo_producao_dias"),
        "embalagem_vidro": dados.get("embalagem_vidro") if "embalagem_vidro" in dados else None,
        "embalagem_pet": dados.get("embalagem_pet") if "embalagem_pet" in dados else None,
        "envase_200ml": dados.get("envase_200ml") if "envase_200ml" in dados else None,
        "rotulagem": dados.get("rotulagem") if "rotulagem" in dados else None,
        "responsabilidade_tecnica": dados.get("responsabilidade_tecnica") if "responsabilidade_tecnica" in dados else None,
        "analises_laboratoriais": dados.get("analises_laboratoriais") if "analises_laboratoriais" in dados else None,
        "pode_copack": dados.get("pode_copack") if "pode_copack" in dados else None,
        "ncm_informado": dados.get("ncm_informado"),
        "observacoes": dados.get("observacoes"),
        "fonte_dados": dados.get("fonte_dados"),
        "verificado_por": dados.get("verificado_por")
    }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO fabricas_parceiras (
                        id,
                        nome,
                        razao_social,
                        cnpj,
                        cidade,
                        estado,
                        regiao,
                        contato_nome,
                        contato_email,
                        contato_whatsapp,
                        site,
                        status_comercial,
                        status_regulatorio,
                        mapa_status,
                        lote_minimo_unidades,
                        lote_minimo_litros,
                        capacidade_maxima_unidades,
                        capacidade_maxima_litros,
                        custo_unitario_centavos,
                        custo_litro_centavos,
                        prazo_producao_dias,
                        embalagem_vidro,
                        embalagem_pet,
                        envase_200ml,
                        rotulagem,
                        responsabilidade_tecnica,
                        analises_laboratoriais,
                        pode_copack,
                        ncm_informado,
                        observacoes,
                        fonte_dados,
                        verificado_por,
                        verificado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        CASE
                            WHEN %s IS NOT NULL
                            THEN NOW()
                            ELSE NULL
                        END
                    )
                    RETURNING *
                """, (
                    fabrica_id,
                    nome,
                    campos["razao_social"],
                    campos["cnpj"],
                    campos["cidade"],
                    campos["estado"],
                    campos["regiao"],
                    campos["contato_nome"],
                    campos["contato_email"],
                    campos["contato_whatsapp"],
                    campos["site"],
                    status_comercial,
                    status_regulatorio,
                    campos["mapa_status"],
                    campos["lote_minimo_unidades"],
                    campos["lote_minimo_litros"],
                    campos["capacidade_maxima_unidades"],
                    campos["capacidade_maxima_litros"],
                    campos["custo_unitario_centavos"],
                    campos["custo_litro_centavos"],
                    campos["prazo_producao_dias"],
                    campos["embalagem_vidro"],
                    campos["embalagem_pet"],
                    campos["envase_200ml"],
                    campos["rotulagem"],
                    campos["responsabilidade_tecnica"],
                    campos["analises_laboratoriais"],
                    campos["pode_copack"],
                    campos["ncm_informado"],
                    campos["observacoes"],
                    campos["fonte_dados"],
                    campos["verificado_por"],
                    campos["verificado_por"]
                ))

                fabrica = cur.fetchone()

        registrar_auditoria(
            categoria="industrial",
            acao="fabrica_cadastrada",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="fabrica_parceira",
            entidade_id=fabrica_id,
            status="criado",
            dados_entrada={
                "nome": nome,
                "estado": campos["estado"],
                "status_comercial": status_comercial,
                "status_regulatorio": status_regulatorio
            }
        )

        return jsonify({
            "success": True,
            "fabrica": fabrica
        }), 201

    except Exception as erro:
        print(
            "ERRO CRIAR FABRICA:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error": "Erro ao cadastrar fábrica."
        }), 500

    finally:
        conn.close()


@app.route(
    "/api/admin/fabricas/<fabrica_id>",
    methods=["PATCH"]
)
def admin_atualizar_fabrica(fabrica_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos_permitidos = {
        "nome",
        "razao_social",
        "cnpj",
        "cidade",
        "estado",
        "regiao",
        "contato_nome",
        "contato_email",
        "contato_whatsapp",
        "site",
        "status_comercial",
        "status_regulatorio",
        "mapa_status",
        "lote_minimo_unidades",
        "lote_minimo_litros",
        "capacidade_maxima_unidades",
        "capacidade_maxima_litros",
        "custo_unitario_centavos",
        "custo_litro_centavos",
        "prazo_producao_dias",
        "embalagem_vidro",
        "embalagem_pet",
        "envase_200ml",
        "rotulagem",
        "responsabilidade_tecnica",
        "analises_laboratoriais",
        "pode_copack",
        "ncm_informado",
        "observacoes",
        "fonte_dados",
        "verificado_por"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo == "status_comercial":
            valor = str(valor).strip().lower()

            if valor not in {
                "prospectada",
                "qualificada",
                "negociacao",
                "homologada",
                "inativa",
                "descartada"
            }:
                return jsonify({
                    "success": False,
                    "error": "Status comercial inválido."
                }), 400

        if campo == "status_regulatorio":
            valor = str(valor).strip().lower()

            if valor not in {
                "nao_verificado",
                "em_analise",
                "regular",
                "pendente",
                "incompativel"
            }:
                return jsonify({
                    "success": False,
                    "error": "Status regulatório inválido."
                }), 400

        atualizacoes.append(
            f"{campo} = %s"
        )

        valores.append(
            valor
        )

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error": "Nenhum campo válido informado."
        }), 400

    if "verificado_por" in dados:
        atualizacoes.append(
            "verificado_em = NOW()"
        )

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(
        fabrica_id
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE fabricas_parceiras
                    SET {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING *
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                fabrica = cur.fetchone()

                if not fabrica:
                    return jsonify({
                        "success": False,
                        "error": "Fábrica não encontrada."
                    }), 404

        registrar_auditoria(
            categoria="industrial",
            acao="fabrica_atualizada",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="fabrica_parceira",
            entidade_id=fabrica_id,
            status="atualizado",
            dados_entrada={
                "campos_alterados":
                    list(dados.keys())
            }
        )

        return jsonify({
            "success": True,
            "fabrica": fabrica
        }), 200

    finally:
        conn.close()


def texto_booleano_verificado(valor):
    if valor is True:
        return "sim"

    if valor is False:
        return "não"

    return "não verificado"


@app.route(
    "/api/admin/cenarios-fiscais",
    methods=["GET"]
)
def admin_listar_cenarios_fiscais():

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
                    SELECT *
                    FROM cenarios_fiscais
                    ORDER BY
                        uf_origem,
                        uf_destino,
                        criado_em DESC
                """)

                cenarios = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(cenarios),
            "cenarios": cenarios
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/cenarios-fiscais",
    methods=["POST"]
)
def admin_criar_cenario_fiscal():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    nome = str(
        dados.get("nome", "")
    ).strip()

    uf_origem = str(
        dados.get("uf_origem", "")
    ).strip().upper()

    uf_destino = str(
        dados.get("uf_destino", "")
    ).strip().upper()

    if not nome:
        return jsonify({
            "success": False,
            "error": "Nome obrigatório."
        }), 400

    if len(uf_origem) != 2 or len(uf_destino) != 2:
        return jsonify({
            "success": False,
            "error": "UF de origem e destino obrigatórias."
        }), 400

    cenario_id = str(uuid.uuid4())

    campos = {
        "fabrica_id": dados.get("fabrica_id"),
        "finalidade": dados.get("finalidade", "revenda"),
        "tipo_destinatario": dados.get("tipo_destinatario"),
        "contribuinte_icms": dados.get("contribuinte_icms"),
        "ncm": dados.get("ncm"),
        "cfop": dados.get("cfop"),
        "csosn": dados.get("csosn"),
        "icms_st_aplicavel": dados.get("icms_st_aplicavel"),
        "icms_st_retido_origem": dados.get("icms_st_retido_origem"),
        "antecipacao_aplicavel": dados.get("antecipacao_aplicavel"),
        "difal_aplicavel": dados.get("difal_aplicavel"),
        "aliquota_icms_origem": dados.get("aliquota_icms_origem"),
        "aliquota_icms_destino": dados.get("aliquota_icms_destino"),
        "aliquota_simples": dados.get("aliquota_simples"),
        "valor_compra_centavos": dados.get("valor_compra_centavos"),
        "valor_venda_centavos": dados.get("valor_venda_centavos"),
        "icms_st_centavos": dados.get("icms_st_centavos"),
        "antecipacao_centavos": dados.get("antecipacao_centavos"),
        "difal_centavos": dados.get("difal_centavos"),
        "das_estimado_centavos": dados.get("das_estimado_centavos"),
        "carga_tributaria_total_centavos":
            dados.get("carga_tributaria_total_centavos"),
        "status_calculo":
            dados.get("status_calculo", "aguardando_dados"),
        "fonte_regra": dados.get("fonte_regra"),
        "observacoes": dados.get("observacoes"),
        "verificado_por": dados.get("verificado_por")
    }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO cenarios_fiscais (
                        id,
                        nome,
                        fabrica_id,
                        uf_origem,
                        uf_destino,
                        finalidade,
                        tipo_destinatario,
                        contribuinte_icms,
                        ncm,
                        cfop,
                        csosn,
                        icms_st_aplicavel,
                        icms_st_retido_origem,
                        antecipacao_aplicavel,
                        difal_aplicavel,
                        aliquota_icms_origem,
                        aliquota_icms_destino,
                        aliquota_simples,
                        valor_compra_centavos,
                        valor_venda_centavos,
                        icms_st_centavos,
                        antecipacao_centavos,
                        difal_centavos,
                        das_estimado_centavos,
                        carga_tributaria_total_centavos,
                        status_calculo,
                        fonte_regra,
                        observacoes,
                        verificado_por,
                        verificado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        CASE
                            WHEN %s IS NOT NULL
                            THEN NOW()
                            ELSE NULL
                        END
                    )
                    RETURNING *
                """, (
                    cenario_id,
                    nome,
                    campos["fabrica_id"],
                    uf_origem,
                    uf_destino,
                    campos["finalidade"],
                    campos["tipo_destinatario"],
                    campos["contribuinte_icms"],
                    campos["ncm"],
                    campos["cfop"],
                    campos["csosn"],
                    campos["icms_st_aplicavel"],
                    campos["icms_st_retido_origem"],
                    campos["antecipacao_aplicavel"],
                    campos["difal_aplicavel"],
                    campos["aliquota_icms_origem"],
                    campos["aliquota_icms_destino"],
                    campos["aliquota_simples"],
                    campos["valor_compra_centavos"],
                    campos["valor_venda_centavos"],
                    campos["icms_st_centavos"],
                    campos["antecipacao_centavos"],
                    campos["difal_centavos"],
                    campos["das_estimado_centavos"],
                    campos["carga_tributaria_total_centavos"],
                    campos["status_calculo"],
                    campos["fonte_regra"],
                    campos["observacoes"],
                    campos["verificado_por"],
                    campos["verificado_por"]
                ))

                cenario = cur.fetchone()

        registrar_auditoria(
            categoria="fiscal",
            acao="cenario_fiscal_criado",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="cenario_fiscal",
            entidade_id=cenario_id,
            status="criado",
            dados_entrada={
                "nome": nome,
                "uf_origem": uf_origem,
                "uf_destino": uf_destino,
                "ncm": campos["ncm"],
                "status_calculo":
                    campos["status_calculo"]
            }
        )

        return jsonify({
            "success": True,
            "cenario": cenario
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/cenarios-fiscais/<cenario_id>",
    methods=["PATCH"]
)
def admin_atualizar_cenario_fiscal(cenario_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos_permitidos = {
        "nome",
        "fabrica_id",
        "uf_origem",
        "uf_destino",
        "finalidade",
        "tipo_destinatario",
        "contribuinte_icms",
        "ncm",
        "cfop",
        "csosn",
        "icms_st_aplicavel",
        "icms_st_retido_origem",
        "antecipacao_aplicavel",
        "difal_aplicavel",
        "aliquota_icms_origem",
        "aliquota_icms_destino",
        "aliquota_simples",
        "valor_compra_centavos",
        "valor_venda_centavos",
        "icms_st_centavos",
        "antecipacao_centavos",
        "difal_centavos",
        "das_estimado_centavos",
        "carga_tributaria_total_centavos",
        "status_calculo",
        "fonte_regra",
        "observacoes",
        "verificado_por"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo in {
            "uf_origem",
            "uf_destino"
        } and valor is not None:
            valor = str(valor).strip().upper()

        atualizacoes.append(
            f"{campo} = %s"
        )
        valores.append(valor)

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error": "Nenhum campo válido informado."
        }), 400

    if "verificado_por" in dados:
        atualizacoes.append(
            "verificado_em = NOW()"
        )

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(
        cenario_id
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE cenarios_fiscais
                    SET {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING *
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                cenario = cur.fetchone()

                if not cenario:
                    return jsonify({
                        "success": False,
                        "error": "Cenário fiscal não encontrado."
                    }), 404

        registrar_auditoria(
            categoria="fiscal",
            acao="cenario_fiscal_atualizado",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="cenario_fiscal",
            entidade_id=cenario_id,
            status="atualizado",
            dados_entrada={
                "campos_alterados":
                    list(dados.keys())
            }
        )

        return jsonify({
            "success": True,
            "cenario": cenario
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/rotas-logisticas",
    methods=["GET"]
)
def admin_listar_rotas_logisticas():

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
                        r.*,
                        f.nome AS fabrica_nome,
                        c.nome AS cenario_fiscal_nome
                    FROM rotas_logisticas r
                    LEFT JOIN fabricas_parceiras f
                        ON f.id = r.fabrica_id
                    LEFT JOIN cenarios_fiscais c
                        ON c.id = r.cenario_fiscal_id
                    ORDER BY
                        CASE r.status_cotacao
                            WHEN 'contratada' THEN 1
                            WHEN 'cotada' THEN 2
                            WHEN 'aguardando_cotacao' THEN 3
                            WHEN 'expirada' THEN 4
                            ELSE 5
                        END,
                        r.atualizado_em DESC
                """)

                rotas = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(rotas),
            "rotas": rotas
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/rotas-logisticas",
    methods=["POST"]
)
def admin_criar_rota_logistica():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    nome = str(
        dados.get("nome", "")
    ).strip()

    uf_origem = str(
        dados.get("uf_origem", "")
    ).strip().upper()

    uf_destino = str(
        dados.get("uf_destino", "")
    ).strip().upper()

    if not nome:
        return jsonify({
            "success": False,
            "error": "Nome da rota obrigatório."
        }), 400

    if len(uf_origem) != 2 or len(uf_destino) != 2:
        return jsonify({
            "success": False,
            "error": "UF de origem e destino obrigatórias."
        }), 400

    status_cotacao = str(
        dados.get(
            "status_cotacao",
            "aguardando_cotacao"
        )
    ).strip().lower()

    if status_cotacao not in {
        "aguardando_cotacao",
        "cotada",
        "contratada",
        "expirada",
        "cancelada"
    }:
        return jsonify({
            "success": False,
            "error": "Status de cotação inválido."
        }), 400

    rota_id = str(
        uuid.uuid4()
    )

    campos = {
        "fabrica_id":
            dados.get("fabrica_id"),

        "cenario_fiscal_id":
            dados.get("cenario_fiscal_id"),

        "transportadora":
            dados.get("transportadora"),

        "cidade_origem":
            dados.get("cidade_origem"),

        "cidade_destino":
            dados.get("cidade_destino"),

        "quantidade_unidades":
            dados.get("quantidade_unidades"),

        "peso_total_kg":
            dados.get("peso_total_kg"),

        "volume_total_m3":
            dados.get("volume_total_m3"),

        "modalidade":
            dados.get("modalidade"),

        "condicao_frete":
            dados.get("condicao_frete"),

        "valor_frete_centavos":
            dados.get("valor_frete_centavos"),

        "seguro_centavos":
            dados.get("seguro_centavos"),

        "pedagio_centavos":
            dados.get("pedagio_centavos"),

        "outras_despesas_centavos":
            dados.get("outras_despesas_centavos"),

        "prazo_minimo_dias":
            dados.get("prazo_minimo_dias"),

        "prazo_maximo_dias":
            dados.get("prazo_maximo_dias"),

        "validade_cotacao":
            dados.get("validade_cotacao"),

        "fonte_dados":
            dados.get("fonte_dados"),

        "observacoes":
            dados.get("observacoes"),

        "verificado_por":
            dados.get("verificado_por")
    }

    componentes = [
        campos["valor_frete_centavos"],
        campos["seguro_centavos"],
        campos["pedagio_centavos"],
        campos["outras_despesas_centavos"]
    ]

    custo_total = None

    if any(
        valor is not None
        for valor in componentes
    ):
        custo_total = sum(
            int(valor or 0)
            for valor in componentes
        )

    custo_unitario = None

    if (
        custo_total is not None
        and campos["quantidade_unidades"]
        and int(campos["quantidade_unidades"]) > 0
    ):
        custo_unitario = round(
            custo_total
            / int(campos["quantidade_unidades"])
        )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO rotas_logisticas (
                        id,
                        nome,
                        fabrica_id,
                        cenario_fiscal_id,
                        transportadora,
                        cidade_origem,
                        uf_origem,
                        cidade_destino,
                        uf_destino,
                        quantidade_unidades,
                        peso_total_kg,
                        volume_total_m3,
                        modalidade,
                        condicao_frete,
                        valor_frete_centavos,
                        seguro_centavos,
                        pedagio_centavos,
                        outras_despesas_centavos,
                        prazo_minimo_dias,
                        prazo_maximo_dias,
                        custo_total_logistico_centavos,
                        custo_logistico_unitario_centavos,
                        status_cotacao,
                        validade_cotacao,
                        fonte_dados,
                        observacoes,
                        verificado_por,
                        verificado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        CASE
                            WHEN %s IS NOT NULL
                            THEN NOW()
                            ELSE NULL
                        END
                    )
                    RETURNING *
                """, (
                    rota_id,
                    nome,
                    campos["fabrica_id"],
                    campos["cenario_fiscal_id"],
                    campos["transportadora"],
                    campos["cidade_origem"],
                    uf_origem,
                    campos["cidade_destino"],
                    uf_destino,
                    campos["quantidade_unidades"],
                    campos["peso_total_kg"],
                    campos["volume_total_m3"],
                    campos["modalidade"],
                    campos["condicao_frete"],
                    campos["valor_frete_centavos"],
                    campos["seguro_centavos"],
                    campos["pedagio_centavos"],
                    campos["outras_despesas_centavos"],
                    campos["prazo_minimo_dias"],
                    campos["prazo_maximo_dias"],
                    custo_total,
                    custo_unitario,
                    status_cotacao,
                    campos["validade_cotacao"],
                    campos["fonte_dados"],
                    campos["observacoes"],
                    campos["verificado_por"],
                    campos["verificado_por"]
                ))

                rota = cur.fetchone()

        registrar_auditoria(
            categoria="logistica",
            acao="rota_logistica_criada",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="rota_logistica",
            entidade_id=rota_id,
            status="criado",
            dados_entrada={
                "nome": nome,
                "uf_origem": uf_origem,
                "uf_destino": uf_destino,
                "transportadora":
                    campos["transportadora"],
                "status_cotacao":
                    status_cotacao
            }
        )

        return jsonify({
            "success": True,
            "rota": rota
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/rotas-logisticas/<rota_id>",
    methods=["DELETE"]
)
def admin_excluir_rota_logistica(rota_id):

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
                    DELETE FROM rotas_logisticas
                    WHERE id = %s
                    RETURNING *
                """, (
                    rota_id,
                ))

                rota = cur.fetchone()

                if not rota:
                    return jsonify({
                        "success": False,
                        "error": "Rota logística não encontrada."
                    }), 404

        registrar_auditoria(
            categoria="logistica",
            acao="rota_logistica_excluida",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="rota_logistica",
            entidade_id=rota_id,
            status="excluido",
            dados_entrada={
                "nome": rota.get("nome"),
                "uf_origem": rota.get("uf_origem"),
                "uf_destino": rota.get("uf_destino")
            }
        )

        return jsonify({
            "success": True,
            "rota_excluida": rota
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/rotas-logisticas/<rota_id>",
    methods=["PATCH"]
)
def admin_atualizar_rota_logistica(rota_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    campos_permitidos = {
        "nome",
        "fabrica_id",
        "cenario_fiscal_id",
        "transportadora",
        "cidade_origem",
        "uf_origem",
        "cidade_destino",
        "uf_destino",
        "quantidade_unidades",
        "peso_total_kg",
        "volume_total_m3",
        "modalidade",
        "condicao_frete",
        "valor_frete_centavos",
        "seguro_centavos",
        "pedagio_centavos",
        "outras_despesas_centavos",
        "prazo_minimo_dias",
        "prazo_maximo_dias",
        "status_cotacao",
        "validade_cotacao",
        "fonte_dados",
        "observacoes",
        "verificado_por"
    }

    atualizacoes = []
    valores = []

    for campo, valor in dados.items():

        if campo not in campos_permitidos:
            continue

        if campo in {
            "uf_origem",
            "uf_destino"
        } and valor is not None:
            valor = str(
                valor
            ).strip().upper()

        if campo == "status_cotacao":
            valor = str(
                valor
            ).strip().lower()

            if valor not in {
                "aguardando_cotacao",
                "cotada",
                "contratada",
                "expirada",
                "cancelada"
            }:
                return jsonify({
                    "success": False,
                    "error": "Status de cotação inválido."
                }), 400

        atualizacoes.append(
            f"{campo} = %s"
        )

        valores.append(
            valor
        )

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error": "Nenhum campo válido informado."
        }), 400

    if "verificado_por" in dados:
        atualizacoes.append(
            "verificado_em = NOW()"
        )

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(
        rota_id
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE rotas_logisticas
                    SET {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING *
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                rota = cur.fetchone()

                if not rota:
                    return jsonify({
                        "success": False,
                        "error": "Rota logística não encontrada."
                    }), 404

        registrar_auditoria(
            categoria="logistica",
            acao="rota_logistica_atualizada",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="rota_logistica",
            entidade_id=rota_id,
            status="atualizado",
            dados_entrada={
                "campos_alterados":
                    list(dados.keys())
            }
        )

        return jsonify({
            "success": True,
            "rota": rota
        }), 200

    finally:
        conn.close()


def carregar_cenarios_fiscais_para_ia(limite=100):

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
                        fabrica_id,
                        uf_origem,
                        uf_destino,
                        finalidade,
                        tipo_destinatario,
                        contribuinte_icms,
                        ncm,
                        cfop,
                        csosn,
                        icms_st_aplicavel,
                        icms_st_retido_origem,
                        antecipacao_aplicavel,
                        difal_aplicavel,
                        aliquota_icms_origem,
                        aliquota_icms_destino,
                        aliquota_simples,
                        valor_compra_centavos,
                        valor_venda_centavos,
                        icms_st_centavos,
                        antecipacao_centavos,
                        difal_centavos,
                        das_estimado_centavos,
                        carga_tributaria_total_centavos,
                        status_calculo,
                        fonte_regra,
                        observacoes,
                        verificado_por,
                        verificado_em,
                        atualizado_em
                    FROM cenarios_fiscais
                    ORDER BY
                        uf_origem,
                        uf_destino,
                        atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                cenarios = cur.fetchall()

        def texto_bool(valor):
            if valor is True:
                return "sim"

            if valor is False:
                return "não"

            return "não definido"

        def texto_dinheiro(valor):
            if valor is None:
                return "não informado"

            return f"R$ {valor / 100:.2f}"

        def texto_percentual(valor):
            if valor is None:
                return "não informado"

            return f"{float(valor):.4f}%"

        linhas = []

        for cenario in cenarios:

            linhas.append(
                (
                    f"- {cenario['nome']} "
                    f"| Origem: {cenario['uf_origem']} "
                    f"| Destino: {cenario['uf_destino']} "
                    f"| Finalidade: {cenario['finalidade']} "
                    f"| Destinatário: "
                    f"{cenario['tipo_destinatario'] or 'não informado'} "
                    f"| Contribuinte ICMS: "
                    f"{texto_bool(cenario['contribuinte_icms'])} "
                    f"| NCM: {cenario['ncm'] or 'não informado'} "
                    f"| CFOP: {cenario['cfop'] or 'não informado'} "
                    f"| CSOSN: {cenario['csosn'] or 'não informado'} "
                    f"| ICMS-ST aplicável: "
                    f"{texto_bool(cenario['icms_st_aplicavel'])} "
                    f"| ICMS-ST retido na origem: "
                    f"{texto_bool(cenario['icms_st_retido_origem'])} "
                    f"| Antecipação: "
                    f"{texto_bool(cenario['antecipacao_aplicavel'])} "
                    f"| DIFAL: "
                    f"{texto_bool(cenario['difal_aplicavel'])} "
                    f"| Alíquota ICMS origem: "
                    f"{texto_percentual(cenario['aliquota_icms_origem'])} "
                    f"| Alíquota ICMS destino: "
                    f"{texto_percentual(cenario['aliquota_icms_destino'])} "
                    f"| Alíquota Simples: "
                    f"{texto_percentual(cenario['aliquota_simples'])} "
                    f"| Valor compra: "
                    f"{texto_dinheiro(cenario['valor_compra_centavos'])} "
                    f"| Valor venda: "
                    f"{texto_dinheiro(cenario['valor_venda_centavos'])} "
                    f"| ICMS-ST: "
                    f"{texto_dinheiro(cenario['icms_st_centavos'])} "
                    f"| Antecipação: "
                    f"{texto_dinheiro(cenario['antecipacao_centavos'])} "
                    f"| DIFAL: "
                    f"{texto_dinheiro(cenario['difal_centavos'])} "
                    f"| DAS estimado: "
                    f"{texto_dinheiro(cenario['das_estimado_centavos'])} "
                    f"| Carga tributária total: "
                    f"{texto_dinheiro(cenario['carga_tributaria_total_centavos'])} "
                    f"| Status cálculo: {cenario['status_calculo']} "
                    f"| Fonte: "
                    f"{cenario['fonte_regra'] or 'não informada'} "
                    f"| Verificado por: "
                    f"{cenario['verificado_por'] or 'não verificado'} "
                    f"| Observações: "
                    f"{cenario['observacoes'] or 'sem observações'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "CENÁRIOS FISCAIS / TRIBUTÁRIOS\n"
                "Use estes cenários como estrutura para comparar operações. "
                "Não invente NCM, alíquota, ST, antecipação, DIFAL ou carga "
                "tributária quando estiverem ausentes. Campo nulo significa "
                "dado ainda não confirmado, e não zero. Diferencie regra "
                "informada pelo contador de regra efetivamente validada para "
                "o produto e a operação específica.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "cenarios": cenarios,
            "contexto": contexto
        }

    finally:
        conn.close()


def carregar_fabricas_para_ia(limite=50):

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
                        razao_social,
                        cnpj,
                        cidade,
                        estado,
                        regiao,
                        status_comercial,
                        status_regulatorio,
                        mapa_status,
                        lote_minimo_unidades,
                        lote_minimo_litros,
                        capacidade_maxima_unidades,
                        capacidade_maxima_litros,
                        custo_unitario_centavos,
                        custo_litro_centavos,
                        prazo_producao_dias,
                        embalagem_vidro,
                        embalagem_pet,
                        envase_200ml,
                        rotulagem,
                        responsabilidade_tecnica,
                        analises_laboratoriais,
                        pode_copack,
                        ncm_informado,
                        observacoes,
                        fonte_dados,
                        verificado_por,
                        verificado_em,
                        atualizado_em
                    FROM fabricas_parceiras
                    ORDER BY
                        CASE status_regulatorio
                            WHEN 'regular' THEN 1
                            WHEN 'em_analise' THEN 2
                            WHEN 'pendente' THEN 3
                            WHEN 'nao_verificado' THEN 4
                            WHEN 'incompativel' THEN 5
                            ELSE 6
                        END,
                        CASE status_comercial
                            WHEN 'homologada' THEN 1
                            WHEN 'negociacao' THEN 2
                            WHEN 'qualificada' THEN 3
                            WHEN 'prospectada' THEN 4
                            ELSE 5
                        END,
                        atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                fabricas = cur.fetchall()

        linhas = []

        for fabrica in fabricas:

            custo_unitario = (
                fabrica["custo_unitario_centavos"] / 100
                if fabrica["custo_unitario_centavos"] is not None
                else None
            )

            custo_litro = (
                fabrica["custo_litro_centavos"] / 100
                if fabrica["custo_litro_centavos"] is not None
                else None
            )

            texto_custo_unitario = (
                f"R$ {custo_unitario:.2f}"
                if custo_unitario is not None
                else "não informado"
            )

            texto_custo_litro = (
                f"R$ {custo_litro:.2f}"
                if custo_litro is not None
                else "não informado"
            )

            linhas.append(
                (
                    f"- {fabrica['nome']} "
                    f"| Local: "
                    f"{fabrica['cidade'] or 'não informada'}/"
                    f"{fabrica['estado'] or 'não informado'} "
                    f"| Região: "
                    f"{fabrica['regiao'] or 'não informada'} "
                    f"| Comercial: "
                    f"{fabrica['status_comercial']} "
                    f"| Regulatório: "
                    f"{fabrica['status_regulatorio']} "
                    f"| MAPA: "
                    f"{fabrica['mapa_status'] or 'não informado'} "
                    f"| Lote mínimo unidades: "
                    f"{fabrica['lote_minimo_unidades'] or 'não informado'} "
                    f"| Lote mínimo litros: "
                    f"{fabrica['lote_minimo_litros'] or 'não informado'} "
                    f"| Capacidade máxima unidades: "
                    f"{fabrica['capacidade_maxima_unidades'] or 'não informada'} "
                    f"| Capacidade máxima litros: "
                    f"{fabrica['capacidade_maxima_litros'] or 'não informada'} "
                    f"| Custo unitário: "
                    f"{texto_custo_unitario} "
                    f"| Custo por litro: "
                    f"{texto_custo_litro} "
                    f"| Prazo produção: "
                    f"{fabrica['prazo_producao_dias'] or 'não informado'} dias "
                    f"| Copack: "
                    f"{texto_booleano_verificado(fabrica['pode_copack'])} "
                    f"| Envase 200ml: "
                    f"{texto_booleano_verificado(fabrica['envase_200ml'])} "
                    f"| Vidro: "
                    f"{texto_booleano_verificado(fabrica['embalagem_vidro'])} "
                    f"| Rotulagem: "
                    f"{texto_booleano_verificado(fabrica['rotulagem'])} "
                    f"| RT: "
                    f"{texto_booleano_verificado(fabrica['responsabilidade_tecnica'])} "
                    f"| Análises: "
                    f"{texto_booleano_verificado(fabrica['analises_laboratoriais'])} "
                    f"| NCM informado: "
                    f"{fabrica['ncm_informado'] or 'não informado'} "
                    f"| Fonte: "
                    f"{fabrica['fonte_dados'] or 'não informada'} "
                    f"| Verificado por: "
                    f"{fabrica['verificado_por'] or 'não verificado'} "
                    f"| Observações: "
                    f"{fabrica['observacoes'] or 'sem observações'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "MATRIZ INDUSTRIAL / FÁBRICAS PARCEIRAS\n"
                "Use estes dados para avaliar capacidade produtiva, "
                "localização, lote mínimo, custos, prazo e situação "
                "regulatória. Não trate fábrica com status regulatório "
                "'pendente', 'nao_verificado' ou 'incompativel' como "
                "liberada para produção comercial. Diferencie informação "
                "cadastrada de informação efetivamente verificada.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "fabricas": fabricas,
            "contexto": contexto
        }

    finally:
        conn.close()



@app.route(
    "/api/admin/contatos-estrategicos",
    methods=["GET"]
)
def admin_listar_contatos_estrategicos():

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
                        ce.*,
                        fp.nome AS fabrica_nome
                    FROM contatos_estrategicos ce
                    LEFT JOIN fabricas_parceiras fp
                        ON fp.id = ce.fabrica_id
                    ORDER BY
                        ce.atualizado_em DESC
                """)

                contatos = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(contatos),
            "contatos": contatos
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/contatos-estrategicos",
    methods=["POST"]
)
def admin_criar_contato_estrategico():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    tipo = str(
        dados.get("tipo", "")
    ).strip().lower()

    if not tipo:
        return jsonify({
            "success": False,
            "error": "Tipo obrigatório."
        }), 400

    contato_id = str(
        uuid.uuid4()
    )

    campos = {
        "nome": dados.get("nome"),
        "empresa": dados.get("empresa"),
        "cargo": dados.get("cargo"),
        "telefone": dados.get("telefone"),
        "email": dados.get("email"),
        "cidade": dados.get("cidade"),
        "estado": dados.get("estado"),
        "fabrica_id": dados.get("fabrica_id"),
        "status_relacao":
            dados.get("status_relacao", "prospectado"),
        "origem_contato": dados.get("origem_contato"),
        "resumo": dados.get("resumo"),
        "capacidades": dados.get("capacidades"),
        "restricoes": dados.get("restricoes"),
        "proximo_passo": dados.get("proximo_passo"),
        "fonte_dados": dados.get("fonte_dados"),
        "verificado_por": dados.get("verificado_por")
    }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO contatos_estrategicos (
                        id,
                        nome,
                        empresa,
                        tipo,
                        cargo,
                        telefone,
                        email,
                        cidade,
                        estado,
                        fabrica_id,
                        status_relacao,
                        origem_contato,
                        resumo,
                        capacidades,
                        restricoes,
                        proximo_passo,
                        fonte_dados,
                        verificado_por,
                        verificado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        CASE
                            WHEN %s IS NOT NULL
                            THEN NOW()
                            ELSE NULL
                        END
                    )
                    RETURNING *
                """, (
                    contato_id,
                    campos["nome"],
                    campos["empresa"],
                    tipo,
                    campos["cargo"],
                    campos["telefone"],
                    campos["email"],
                    campos["cidade"],
                    campos["estado"],
                    campos["fabrica_id"],
                    campos["status_relacao"],
                    campos["origem_contato"],
                    campos["resumo"],
                    campos["capacidades"],
                    campos["restricoes"],
                    campos["proximo_passo"],
                    campos["fonte_dados"],
                    campos["verificado_por"],
                    campos["verificado_por"]
                ))

                contato = cur.fetchone()

        return jsonify({
            "success": True,
            "contato": contato
        }), 201

    finally:
        conn.close()


def carregar_contatos_estrategicos_para_ia(limite=100):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM contatos_estrategicos
                    ORDER BY atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                contatos = cur.fetchall()

        linhas = []

        for contato in contatos:

            linhas.append(
                (
                    f"- {contato['nome'] or 'Contato sem nome'} "
                    f"| Empresa: "
                    f"{contato['empresa'] or 'não informada'} "
                    f"| Tipo: {contato['tipo']} "
                    f"| Cargo: "
                    f"{contato['cargo'] or 'não informado'} "
                    f"| Telefone: "
                    f"{contato['telefone'] or 'não informado'} "
                    f"| E-mail: "
                    f"{contato['email'] or 'não informado'} "
                    f"| Status: {contato['status_relacao']} "
                    f"| Resumo: "
                    f"{contato['resumo'] or 'não informado'} "
                    f"| Capacidades: "
                    f"{contato['capacidades'] or 'não verificadas'} "
                    f"| Restrições: "
                    f"{contato['restricoes'] or 'não verificadas'} "
                    f"| Próximo passo: "
                    f"{contato['proximo_passo'] or 'não definido'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "REDE DE CONTATOS ESTRATÉGICOS\n"
                "Use estes contatos como memória de relacionamento "
                "da empresa. Diferencie fabricante, consultor, associação "
                "e indicador. Não trate indicação como fábrica homologada. "
                "Não invente capacidades não confirmadas. "
                "Considere sempre o próximo passo registrado.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "contatos": contatos,
            "contexto": contexto
        }

    finally:
        conn.close()


def carregar_rotas_logisticas_para_ia(limite=100):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        r.*,
                        f.nome AS fabrica_nome,
                        c.nome AS cenario_fiscal_nome
                    FROM rotas_logisticas r
                    LEFT JOIN fabricas_parceiras f
                        ON f.id = r.fabrica_id
                    LEFT JOIN cenarios_fiscais c
                        ON c.id = r.cenario_fiscal_id
                    ORDER BY r.atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                rotas = cur.fetchall()

        linhas = []

        for rota in rotas:

            custo_total = (
                rota["custo_total_logistico_centavos"]
                / 100
                if rota["custo_total_logistico_centavos"]
                is not None
                else None
            )

            custo_unitario = (
                rota["custo_logistico_unitario_centavos"]
                / 100
                if rota["custo_logistico_unitario_centavos"]
                is not None
                else None
            )

            valor_frete = (
                rota["valor_frete_centavos"]
                / 100
                if rota["valor_frete_centavos"]
                is not None
                else None
            )

            linhas.append(
                (
                    f"- Rota: {rota['nome']} "
                    f"| Fábrica: "
                    f"{rota['fabrica_nome'] or 'não vinculada'} "
                    f"| Cenário fiscal: "
                    f"{rota['cenario_fiscal_nome'] or 'não vinculado'} "
                    f"| Transportadora: "
                    f"{rota['transportadora'] or 'não informada'} "
                    f"| Origem: "
                    f"{rota['cidade_origem'] or 'não informada'}/"
                    f"{rota['uf_origem']} "
                    f"| Destino: "
                    f"{rota['cidade_destino'] or 'não informada'}/"
                    f"{rota['uf_destino']} "
                    f"| Quantidade: "
                    f"{rota['quantidade_unidades'] or 'não informada'} "
                    f"unidades "
                    f"| Peso: "
                    f"{rota['peso_total_kg'] if rota['peso_total_kg'] is not None else 'não informado'} kg "
                    f"| Volume: "
                    f"{rota['volume_total_m3'] if rota['volume_total_m3'] is not None else 'não informado'} m3 "
                    f"| Modalidade: "
                    f"{rota['modalidade'] or 'não informada'} "
                    f"| Condição: "
                    f"{rota['condicao_frete'] or 'não informada'} "
                    f"| Frete: "
                    f"{'R$ %.2f' % valor_frete if valor_frete is not None else 'não cotado'} "
                    f"| Custo logístico total: "
                    f"{'R$ %.2f' % custo_total if custo_total is not None else 'não calculado'} "
                    f"| Custo logístico unitário: "
                    f"{'R$ %.2f' % custo_unitario if custo_unitario is not None else 'não calculado'} "
                    f"| Prazo: "
                    f"{rota['prazo_minimo_dias'] if rota['prazo_minimo_dias'] is not None else '?'}"
                    f"–"
                    f"{rota['prazo_maximo_dias'] if rota['prazo_maximo_dias'] is not None else '?'} dias "
                    f"| Status: "
                    f"{rota['status_cotacao']} "
                    f"| Validade da cotação: "
                    f"{rota['validade_cotacao'] or 'não informada'} "
                    f"| Fonte: "
                    f"{rota['fonte_dados'] or 'não informada'} "
                    f"| Verificado por: "
                    f"{rota['verificado_por'] or 'não verificado'} "
                    f"| Observações: "
                    f"{rota['observacoes'] or 'sem observações'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "MATRIZ LOGÍSTICA / ROTAS E FRETES\n"
                "Use estes dados para avaliar frete, prazo, origem, "
                "destino e custo logístico por unidade. "
                "Uma rota com status 'aguardando_cotacao' não possui "
                "preço de frete confirmado. Valores ausentes não devem "
                "ser tratados como zero. Diferencie cotação, contrato, "
                "estimativa e informação ainda não verificada.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "rotas": rotas,
            "contexto": contexto
        }

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
    "/api/admin/acoes/<acao_id>/executar",
    methods=["POST"]
)
def admin_executar_acao_controlada(acao_id):

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
                    SELECT *
                    FROM acoes_empresariais
                    WHERE id = %s
                    LIMIT 1
                """, (
                    acao_id,
                ))

                acao = cur.fetchone()

        if not acao:
            return jsonify({
                "success": False,
                "error": "Ação não encontrada."
            }), 404

        registrar_auditoria(
            categoria="execucao",
            acao="execucao_solicitada",
            ator_tipo="admin",
            ator_id="admin",
            origem="painel_admin",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status="solicitada",
            requer_aprovacao=(
                acao.get("modo_execucao")
                == "requer_aprovacao"
            ),
            dados_entrada={
                "modo_execucao":
                    acao.get("modo_execucao"),
                "estado_execucao":
                    acao.get("estado_execucao"),
                "tipo_execucao":
                    acao.get("tipo_execucao")
            }
        )

        resultado = executar_acao_controlada(
            acao
        )

        status_http = (
            200
            if resultado.get("success")
            else 409
        )

        return jsonify(resultado), status_http

    except Exception as erro:
        print(
            "ERRO EXECUÇÃO CONTROLADA:",
            erro
        )

        registrar_auditoria(
            categoria="execucao",
            acao="erro_executor_controlado",
            ator_tipo="sistema",
            ator_id="backend",
            origem="api_admin",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status="falhou",
            erro=str(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Não foi possível executar a ação."
        }), 500

    finally:
        conn.close()


@app.route(
    "/api/admin/auditoria",
    methods=["GET"]
)
def admin_listar_auditoria():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        limite = request.args.get(
            "limite",
            default=100,
            type=int
        )

        limite = max(
            1,
            min(limite, 500)
        )

        conn = get_db_connection()

        try:
            with conn:
                with conn.cursor(
                    cursor_factory=RealDictCursor
                ) as cur:

                    cur.execute("""
                        SELECT
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
                            erro,
                            criado_em
                        FROM auditoria_eventos
                        ORDER BY criado_em DESC
                        LIMIT %s
                    """, (
                        limite,
                    ))

                    eventos = cur.fetchall()

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "total": len(eventos),
            "eventos": eventos
        }), 200

    except Exception as erro:
        print(
            "ERRO LISTAR AUDITORIA:",
            erro
        )

        return jsonify({
            "success": False,
            "error":
                "Não foi possível consultar a auditoria."
        }), 500


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

        fabricas_ia = (
            carregar_fabricas_para_ia()
        )

        contexto_fabricas = (
            fabricas_ia["contexto"]
            or ""
        )

        cenarios_fiscais_ia = (
            carregar_cenarios_fiscais_para_ia()
        )

        contexto_fiscal = (
            cenarios_fiscais_ia["contexto"]
            or ""
        )

        rotas_logisticas_ia = (
            carregar_rotas_logisticas_para_ia()
        )

        contexto_logistica = (
            rotas_logisticas_ia["contexto"]
            or ""
        )

        contatos_estrategicos_ia = (
            carregar_contatos_estrategicos_para_ia()
        )

        contexto_contatos = (
            contatos_estrategicos_ia["contexto"]
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
                + contexto_fabricas
                + contexto_fiscal
                + contexto_logistica
                + contexto_contatos
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

                "Responda de forma executiva, clara, curta e sequencial. "
                "Priorize responder exatamente à pergunta feita antes de trazer contexto adicional. "
                "Quando a pergunta pedir prioridade, ordem de contato ou próximo passo, "
                "compare os contatos estratégicos disponíveis e escolha UMA pessoa primeiro. "
                "Explique em no máximo duas frases por que essa pessoa é prioridade "
                "e qual resultado concreto deve ser buscado nesse contato. "
                "Não transforme perguntas operacionais em parecer regulatório completo. "
                "Use questões regulatórias como restrições da decisão, e não como resposta principal, "
                "a menos que a pergunta seja especificamente regulatória. "
                "Quando houver uma segunda alternativa relevante, cite no máximo uma. "
                "Finalize com 'Próximo passo:' seguido de uma única ação concreta. "
                "Por padrão, use no máximo 3 a 5 parágrafos curtos. "
                "Não repita toda a situação da empresa em cada resposta. "
                "Quando houver informação suficiente, dê uma conclusão direta. "
                "Quando faltar informação, cite no máximo os 3 dados mais importantes que faltam. "
                "Finalize com exatamente um próximo passo concreto quando houver ação útil. "
                "Preserve continuidade entre as perguntas: trate a resposta atual como parte de uma conversa, "
                "não como um relatório independente. "
                "Só produza análise longa quando o usuário pedir explicitamente relatório, detalhes, "
                "análise completa ou comparação extensa. "
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
                    "Faça uma análise executiva direta e curta. "
                    "Use somente fatos presentes no contexto e nos dados fornecidos. "
                    "Não invente números. "
                    "Responda primeiro exatamente ao que foi perguntado. "
                    "Evite repetir contexto já conhecido. "
                    "Use poucos parágrafos e termine com um único próximo passo concreto. "
                    + CONTEXTO_MARANHAO
                    + CONTEXTO_EMPRESARIAL_INTERNO
                    + HIERARQUIA_DECISAO_EMPRESARIAL
                    + contexto_documental
                    + contexto_decisoes
                    + contexto_acoes
                    + contexto_crm
                    + contexto_fabricas
                    + contexto_fiscal
                    + contexto_logistica
                    + contexto_contatos
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
                    len(crm_ia["leads"]),
                "fabricas_consultadas":
                    len(fabricas_ia["fabricas"]),
                "cenarios_fiscais_consultados":
                    len(cenarios_fiscais_ia["cenarios"]),
                "rotas_logisticas_consultadas":
                    len(rotas_logisticas_ia["rotas"]),
                "contatos_estrategicos_consultados":
                    len(contatos_estrategicos_ia["contatos"])
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
                    len(crm_ia["leads"]),
                "fabricas":
                    len(fabricas_ia["fabricas"]),
                "cenarios_fiscais":
                    len(cenarios_fiscais_ia["cenarios"]),
                "rotas_logisticas":
                    len(rotas_logisticas_ia["rotas"]),
                "contatos_estrategicos":
                    len(contatos_estrategicos_ia["contatos"])
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

        import traceback

        print(
            "ERRO IA EMPRESARIAL:",
            repr(erro)
        )

        traceback.print_exc()

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