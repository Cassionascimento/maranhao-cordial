from flask import Flask, send_from_directory, request, jsonify, send_file, redirect, session

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from flask_socketio import SocketIO, emit
import os
import base64
from email.message import EmailMessage
import json
import hashlib
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

# Chave exclusiva para colaboradores que cadastram fábricas.
# Não concede acesso administrativo.
FABRICAS_CADASTRO_KEY = os.getenv("FABRICAS_CADASTRO_KEY")

# Chave exclusiva para colaboradores que cadastram
# bartenders/mixologistas na Rede Profissional.
# Não concede acesso administrativo nem industrial.
PROFISSIONAIS_CADASTRO_KEY = os.getenv(
    "PROFISSIONAIS_CADASTRO_KEY"
)

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





def executar_monitoramento_ga4():
    """
    Executa um ciclo completo de monitoramento do GA4:
    1. registra o snapshot atual;
    2. compara com o snapshot anterior;
    3. registra mudança relevante quando necessário.
    """

    try:
        print("GA4: iniciando monitoramento.")

        snapshot_id = registrar_snapshot_ga4()

        mudanca_id = analisar_mudanca_ga4()

        resultado = {
            "snapshot_id": snapshot_id,
            "mudanca_id": mudanca_id,
        }

        print(
            "GA4: monitoramento concluído:",
            resultado
        )

        return resultado

    except Exception as erro:
        print(
            "ERRO NO MONITORAMENTO GA4:",
            repr(erro)
        )

        return {
            "snapshot_id": None,
            "mudanca_id": None,
            "erro": str(erro),
        }

def registrar_snapshot_ga4():
    """
    Consulta o GA4 e registra um snapshot na central de eventos.
    O external_id evita duplicidade dentro da mesma janela temporal.
    """

    try:
        from analytics_service import resumo_geral
        from datetime import datetime, timezone

        dados = resumo_geral(dias=7)

        if not dados:
            print("GA4 sem dados nesta execução.")
            return None

        agora = datetime.now(timezone.utc)

        janela = agora.strftime("%Y-%m-%d-%H")

        external_id = f"ga4-resumo-7d-{janela}"

        descricao = (
            f"GA4 7 dias: "
            f"{dados.get('usuarios_ativos', '0')} usuários ativos, "
            f"{dados.get('sessoes', '0')} sessões, "
            f"{dados.get('visualizacoes', '0')} visualizações."
        )

        evento_id = registrar_evento_empresarial(
            fonte="google_analytics",
            tipo="snapshot_ga4",
            descricao=descricao,
            external_id=external_id,
            payload=dados,
            importancia="normal"
        )

        print("SNAPSHOT GA4 EVENTO ID:", evento_id)

        return evento_id

    except Exception as erro:
        print(
            "ERRO AO REGISTRAR SNAPSHOT GA4:",
            repr(erro)
        )

        return None


def analisar_mudanca_ga4():
    """
    Compara os dois últimos snapshots do GA4.
    Registra um evento somente quando encontra mudança relevante.
    """

    conn = None

    try:
        conn = get_db_connection()

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    payload_json,
                    criado_em
                FROM eventos_empresariais
                WHERE fonte = 'google_analytics'
                  AND tipo = 'snapshot_ga4'
                ORDER BY id DESC
                LIMIT 2
                """
            )

            snapshots = cur.fetchall()

        if len(snapshots) < 2:
            print(
                "GA4: ainda não existem dois snapshots para comparação."
            )
            return None

        atual = json.loads(
            snapshots[0]["payload_json"] or "{}"
        )

        anterior = json.loads(
            snapshots[1]["payload_json"] or "{}"
        )

        def numero(valor):
            try:
                return float(valor or 0)
            except (TypeError, ValueError):
                return 0.0

        def variacao_percentual(novo, antigo):
            novo = numero(novo)
            antigo = numero(antigo)

            if antigo == 0:
                if novo == 0:
                    return 0.0
                return 100.0

            return ((novo - antigo) / antigo) * 100

        variacao_usuarios = variacao_percentual(
            atual.get("usuarios_ativos"),
            anterior.get("usuarios_ativos")
        )

        variacao_sessoes = variacao_percentual(
            atual.get("sessoes"),
            anterior.get("sessoes")
        )

        engajamento_atual = numero(
            atual.get("taxa_engajamento")
        )

        engajamento_anterior = numero(
            anterior.get("taxa_engajamento")
        )

        diferenca_engajamento = (
            engajamento_atual - engajamento_anterior
        ) * 100

        mudancas = []

        if abs(variacao_usuarios) >= 20:
            mudancas.append(
                f"usuários ativos {variacao_usuarios:+.1f}%"
            )

        if abs(variacao_sessoes) >= 20:
            mudancas.append(
                f"sessões {variacao_sessoes:+.1f}%"
            )

        if abs(diferenca_engajamento) >= 10:
            mudancas.append(
                f"engajamento {diferenca_engajamento:+.1f} p.p."
            )

        if not mudancas:
            print("GA4: nenhuma mudança relevante detectada.")
            return None

        descricao = (
            "Mudança relevante detectada no Google Analytics: "
            + "; ".join(mudancas)
            + "."
        )

        external_id = (
            f"ga4-mudanca-"
            f"{snapshots[1]['id']}-"
            f"{snapshots[0]['id']}"
        )

        payload = {
            "snapshot_anterior_id": snapshots[1]["id"],
            "snapshot_atual_id": snapshots[0]["id"],
            "anterior": anterior,
            "atual": atual,
            "variacao_usuarios_percentual": round(
                variacao_usuarios, 2
            ),
            "variacao_sessoes_percentual": round(
                variacao_sessoes, 2
            ),
            "diferenca_engajamento_pontos_percentuais": round(
                diferenca_engajamento, 2
            ),
        }

        evento_id = registrar_evento_empresarial(
            fonte="google_analytics",
            tipo="mudanca_relevante_ga4",
            descricao=descricao,
            external_id=external_id,
            payload=payload,
            importancia="alta"
        )

        print(
            "MUDANÇA GA4 EVENTO ID:",
            evento_id
        )

        return evento_id

    except Exception as erro:
        print(
            "ERRO AO ANALISAR MUDANÇA GA4:",
            repr(erro)
        )

        return None

    finally:
        if conn:
            conn.close()

def registrar_evento_empresarial(
    fonte,
    tipo,
    descricao,
    external_id=None,
    payload=None,
    importancia="normal"
):
    """Registra eventos empresariais para análise pela IA."""

    if not DATABASE_URL:
        print("AVISO: DATABASE_URL não configurada.")
        return None

    conn = None

    try:
        payload_json = json.dumps(
            payload or {},
            ensure_ascii=False,
            default=str
        )

        conn = get_db_connection()

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                INSERT INTO eventos_empresariais (
                    fonte,
                    tipo,
                    descricao,
                    external_id,
                    payload_json,
                    importancia
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (fonte, external_id)
                WHERE external_id IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                (
                    fonte,
                    tipo,
                    descricao,
                    external_id,
                    payload_json,
                    importancia,
                )
            )

            resultado = cur.fetchone()

        conn.commit()

        return resultado["id"] if resultado else None

    except Exception as erro:
        print(
            "ERRO AO REGISTRAR EVENTO EMPRESARIAL:",
            repr(erro)
        )

        if conn:
            conn.rollback()

        return None

    finally:
        if conn:
            conn.close()


def buscar_eventos_pendentes_para_ia(limite=20):
    """
    Busca eventos empresariais ainda não analisados pela IA.

    Esta função apenas lê os eventos.
    Não marca como analisado e não executa ações.
    """

    conn = get_db_connection()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    fonte,
                    tipo,
                    descricao,
                    external_id,
                    payload_json,
                    importancia,
                    criado_em,
                    analisado,
                    notificado
                FROM eventos_empresariais
                WHERE analisado = FALSE
                  AND tipo NOT IN (
                      'snapshot_ga4'
                  )
                ORDER BY
                    CASE importancia
                        WHEN 'critica' THEN 1
                        WHEN 'alta' THEN 2
                        WHEN 'normal' THEN 3
                        WHEN 'media' THEN 4
                        WHEN 'baixa' THEN 5
                        ELSE 6
                    END,
                    criado_em ASC
                LIMIT %s
                """,
                (limite,)
            )

            eventos = cur.fetchall()

        resultado = []

        for evento in eventos:
            item = dict(evento)

            payload_bruto = item.get("payload_json")

            try:
                item["payload"] = (
                    json.loads(payload_bruto)
                    if payload_bruto
                    else {}
                )
            except Exception:
                item["payload"] = {}

            item.pop("payload_json", None)

            resultado.append(item)

        return resultado

    finally:
        conn.close()


def analisar_evento_empresarial_com_ia(evento):
    """
    Analisa um único evento empresarial usando a IA.

    Esta função apenas interpreta o evento e sugere ações.
    Não executa ações e não altera o status do evento.
    """

    if not isinstance(evento, dict):
        raise ValueError(
            "Evento empresarial inválido."
        )

    evento_para_ia = {
        "id": evento.get("id"),
        "fonte": evento.get("fonte"),
        "tipo": evento.get("tipo"),
        "descricao": evento.get("descricao"),
        "external_id": evento.get("external_id"),
        "importancia": evento.get("importancia"),
        "criado_em": str(
            evento.get("criado_em") or ""
        ),
        "payload": evento.get("payload") or {},
    }

    contexto_evento = json.dumps(
        evento_para_ia,
        ensure_ascii=False,
        default=str
    )

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "analise_evento_empresarial",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "resposta": {
                            "type": "string"
                        },
                        "acoes_sugeridas": {
                            "type": "array",
                            "maxItems": 2,
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

            "Analise o evento empresarial recebido. "

            "Determine se ele exige atenção, decisão "
            "ou alguma ação empresarial. "

            "Não execute nenhuma ação. "
            "Não assuma compromissos. "
            "Não autorize pagamentos, contratos, descontos, "
            "preços ou negociações. "

            "Se o evento for apenas informativo, técnico, "
            "redundante ou não exigir ação, retorne "
            "acoes_sugeridas como lista vazia. "

            + CONTEXTO_MARANHAO
            + CONTEXTO_EMPRESARIAL_INTERNO
            + HIERARQUIA_DECISAO_EMPRESARIAL
            + POLITICA_ACOES_SUGERIDAS_IA
            + POLITICA_LINGUAGEM_NATURAL_IA
        ),

        input=(
            "EVENTO EMPRESARIAL PARA ANÁLISE:\n"
            + contexto_evento
        )
    )

    texto_bruto = (
        resposta.output_text
        or ""
    ).strip()

    interpretada = interpretar_saida_ia_empresarial(
        texto_bruto
    )

    return {
        "evento_id": evento.get("id"),
        "resposta": interpretada["resposta"],
        "acoes_sugeridas":
            interpretada["acoes_sugeridas"]
    }


def criar_acao_sugerida_pela_ia(
    sugestao,
    evento_id,
    indice
):
    """
    Registra uma recomendação gerencial da IA
    como ação aguardando aprovação humana.

    Não executa a ação.
    """

    if not isinstance(sugestao, dict):
        raise ValueError(
            "Sugestão de ação inválida."
        )

    titulo = str(
        sugestao.get("titulo") or ""
    ).strip()

    descricao = str(
        sugestao.get("descricao") or ""
    ).strip()

    area = str(
        sugestao.get("area") or "estrategia"
    ).strip()

    prioridade = str(
        sugestao.get("prioridade") or "media"
    ).strip()

    justificativa = str(
        sugestao.get("justificativa") or ""
    ).strip()

    if not titulo:
        raise ValueError(
            "Ação sugerida sem título."
        )

    areas_validas = {
        "comercial",
        "financeiro",
        "operacional",
        "produto",
        "regulatorio",
        "marketing",
        "tecnologia",
        "estrategia"
    }

    prioridades_validas = {
        "baixa",
        "media",
        "alta",
        "critica"
    }

    if area not in areas_validas:
        area = "estrategia"

    if prioridade not in prioridades_validas:
        prioridade = "media"

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO acoes_empresariais (
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,

                        modo_execucao,
                        estado_execucao,
                        executor,
                        tentativas_execucao,
                        tipo_execucao,

                        tipo,
                        canal,
                        conteudo,
                        justificativa,

                        evento_origem_id,
                        acao_origem_indice
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, 0, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (
                        evento_origem_id,
                        acao_origem_indice
                    )
                    WHERE evento_origem_id IS NOT NULL
                    DO NOTHING
                    RETURNING id
                """, (
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    "aguardando_aprovacao",

                    "requer_aprovacao",
                    "nao_iniciada",
                    "gestao",
                    "acao_gerencial",

                    "acao_gerencial",
                    "interno",
                    descricao,
                    justificativa,

                    evento_id,
                    indice
                ))

                linha = cur.fetchone()

                if linha:
                    return str(linha[0])

                return None

    finally:
        conn.close()


def marcar_evento_como_analisado(
    evento_id
):
    """
    Marca o evento como analisado pela IA.
    Não altera o estado de notificação.
    """

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    UPDATE eventos_empresariais
                    SET analisado = TRUE
                    WHERE id = %s
                      AND analisado = FALSE
                    RETURNING id
                """, (
                    evento_id,
                ))

                linha = cur.fetchone()

        return bool(linha)

    finally:
        conn.close()


def processar_eventos_empresariais(
    limite=10
):
    """
    Processa eventos empresariais pendentes.

    Fluxo:
    evento -> IA -> auditoria -> ação pendente
    -> marca evento analisado.

    Nenhuma ação é executada automaticamente.
    """

    eventos = buscar_eventos_pendentes_para_ia(
        limite=limite
    )

    resumo = {
        "encontrados": len(eventos),
        "processados": 0,
        "acoes_criadas": 0,
        "erros": []
    }

    for evento in eventos:

        evento_id = evento.get("id")

        try:
            analise = (
                analisar_evento_empresarial_com_ia(
                    evento
                )
            )

            auditoria_id = registrar_auditoria(
                categoria="ia",
                acao="analise_evento_empresarial",
                ator_tipo="ia",
                ator_id="maranhao-empresarial-v1",
                origem="processador_eventos",
                entidade_tipo="evento_empresarial",
                entidade_id=str(evento_id),
                status="concluido",
                requer_aprovacao=bool(
                    analise.get(
                        "acoes_sugeridas"
                    )
                ),
                correlation_id=(
                    f"evento_empresarial:{evento_id}"
                ),
                dados_entrada={
                    "fonte": evento.get("fonte"),
                    "tipo": evento.get("tipo"),
                    "descricao":
                        evento.get("descricao"),
                    "importancia":
                        evento.get("importancia"),
                    "payload":
                        evento.get("payload")
                },
                dados_saida=analise
            )

            if not auditoria_id:
                raise RuntimeError(
                    "Falha ao registrar auditoria."
                )

            acoes_criadas = []

            for indice, sugestao in enumerate(
                analise.get(
                    "acoes_sugeridas",
                    []
                )
                or []
            ):
                acao_id = (
                    criar_acao_sugerida_pela_ia(
                        sugestao,
                        evento_id,
                        indice
                    )
                )

                if acao_id:
                    acoes_criadas.append(
                        acao_id
                    )

            marcado = (
                marcar_evento_como_analisado(
                    evento_id
                )
            )

            if not marcado:
                raise RuntimeError(
                    "Evento não pôde ser marcado como analisado."
                )

            resumo["processados"] += 1
            resumo["acoes_criadas"] += len(
                acoes_criadas
            )

            print(
                "EVENTO PROCESSADO:",
                evento_id,
                "| AÇÕES:",
                len(acoes_criadas)
            )

        except Exception as erro:

            print(
                "ERRO PROCESSAR EVENTO:",
                evento_id,
                repr(erro)
            )

            registrar_auditoria(
                categoria="ia",
                acao="falha_processamento_evento",
                ator_tipo="sistema",
                ator_id="processador-eventos-v1",
                origem="processador_eventos",
                entidade_tipo="evento_empresarial",
                entidade_id=str(evento_id),
                status="falhou",
                correlation_id=(
                    f"evento_empresarial:{evento_id}"
                ),
                erro=str(erro)
            )

            resumo["erros"].append({
                "evento_id": evento_id,
                "erro": str(erro)
            })

    return resumo

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
                # INSIGHTS EMPRESARIAIS
                # Conhecimento inferido a partir dos dados
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS insights_empresariais (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

                        titulo VARCHAR(220) NOT NULL,
                        descricao TEXT NOT NULL,

                        area VARCHAR(80) NOT NULL,
                        tipo_insight VARCHAR(60)
                            NOT NULL DEFAULT 'analise',

                        prioridade VARCHAR(30)
                            NOT NULL DEFAULT 'media',

                        confianca VARCHAR(30)
                            NOT NULL DEFAULT 'media',

                        status VARCHAR(30)
                            NOT NULL DEFAULT 'ativo',

                        justificativa TEXT,

                        evidencias_origem JSONB
                            NOT NULL DEFAULT '[]'::jsonb,

                        acoes_origem JSONB
                            NOT NULL DEFAULT '[]'::jsonb,

                        eventos_origem JSONB
                            NOT NULL DEFAULT '[]'::jsonb,

                        objetivo_id UUID,
                        decisao_id UUID,

                        origem VARCHAR(80)
                            NOT NULL DEFAULT 'ia_empresarial',

                        chave_deduplicacao VARCHAR(64),

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    ALTER TABLE insights_empresariais
                    ADD COLUMN IF NOT EXISTS acoes_origem JSONB
                    NOT NULL DEFAULT '[]'::jsonb
                """)

                cur.execute("""
                    ALTER TABLE insights_empresariais
                    ADD COLUMN IF NOT EXISTS
                    chave_deduplicacao VARCHAR(64)
                """)

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_insights_empresariais_chave_deduplicacao
                    ON insights_empresariais(chave_deduplicacao)
                    WHERE chave_deduplicacao IS NOT NULL
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_insights_empresariais_status
                    ON insights_empresariais(status)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_insights_empresariais_area
                    ON insights_empresariais(area)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_insights_empresariais_prioridade
                    ON insights_empresariais(prioridade)
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


                # Idempotência das ações originadas pela IA.

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    evento_origem_id BIGINT
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    acao_origem_indice INTEGER
                """)

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_acoes_evento_origem
                    ON acoes_empresariais (
                        evento_origem_id,
                        acao_origem_indice
                    )
                    WHERE evento_origem_id IS NOT NULL
                """)


                # Idempotência das ações originadas por insights.

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    insight_origem_id UUID
                """)

                cur.execute("""
                    ALTER TABLE acoes_empresariais
                    ADD COLUMN IF NOT EXISTS
                    acao_insight_indice INTEGER
                """)

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_acoes_insight_origem
                    ON acoes_empresariais (
                        insight_origem_id,
                        acao_insight_indice
                    )
                    WHERE insight_origem_id IS NOT NULL
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

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_auditoria_acao_correlation
                    ON auditoria_eventos (
                        acao,
                        correlation_id
                    )
                    WHERE correlation_id IS NOT NULL
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
                # OMNICHANNEL — INTERAÇÕES META
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS interacoes_omnichannel (
                        id UUID PRIMARY KEY,

                        canal VARCHAR(40) NOT NULL,
                        plataforma VARCHAR(40),

                        sender_id VARCHAR(220),
                        recipient_id VARCHAR(220),

                        message_id VARCHAR(300),

                        texto TEXT,

                        tipo_interacao VARCHAR(80),
                        classificacao VARCHAR(80),
                        interesse TEXT,

                        lead_id UUID,

                        processado_ia BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_interacao_lead
                            FOREIGN KEY (lead_id)
                            REFERENCES leads_crm(id)
                            ON DELETE SET NULL
                    )
                """)

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_interacoes_omnichannel_message_id
                    ON interacoes_omnichannel(message_id)
                    WHERE message_id IS NOT NULL
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_interacoes_omnichannel_sender
                    ON interacoes_omnichannel(
                        canal,
                        sender_id
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_interacoes_omnichannel_lead
                    ON interacoes_omnichannel(lead_id)
                """)

                # ==========================================
                # OMNICHANNEL — FILA DE RESPOSTAS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS
                    fila_respostas_omnichannel (
                        id UUID PRIMARY KEY,

                        interacao_id UUID NOT NULL,

                        canal VARCHAR(40) NOT NULL,

                        destinatario_id VARCHAR(220)
                            NOT NULL,

                        resposta_sugerida TEXT
                            NOT NULL,

                        status VARCHAR(40)
                            NOT NULL
                            DEFAULT 'aguardando_aprovacao',

                        modo_autonomia VARCHAR(40)
                            NOT NULL
                            DEFAULT 'manual',

                        aprovado_por VARCHAR(220),

                        aprovado_em TIMESTAMPTZ,

                        enviado_em TIMESTAMPTZ,

                        erro_envio TEXT,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_fila_interacao
                            FOREIGN KEY (interacao_id)
                            REFERENCES interacoes_omnichannel(id)
                            ON DELETE CASCADE
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fila_respostas_status
                    ON fila_respostas_omnichannel(status)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fila_respostas_interacao
                    ON fila_respostas_omnichannel(
                        interacao_id
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
                # GOVERNANCA / WORKFLOW DE FABRICAS
                # ==========================================

                # Cadastro externo nunca entra automaticamente
                # nos cálculos ou recomendações definitivas da IA.
                cur.execute("""
                    ALTER TABLE fabricas_parceiras

                    ADD COLUMN IF NOT EXISTS status_fluxo VARCHAR(40)
                        NOT NULL DEFAULT 'pendente',

                    ADD COLUMN IF NOT EXISTS origem_cadastro VARCHAR(60)
                        NOT NULL DEFAULT 'interno',

                    ADD COLUMN IF NOT EXISTS disponivel_calculo_ia BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    ADD COLUMN IF NOT EXISTS responsavel_dados_nome VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS responsavel_dados_email VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS responsavel_dados_whatsapp VARCHAR(50),

                    ADD COLUMN IF NOT EXISTS responsavel_dados_empresa VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS responsavel_dados_cargo VARCHAR(120),

                    ADD COLUMN IF NOT EXISTS cep VARCHAR(12),

                    ADD COLUMN IF NOT EXISTS endereco_operacional TEXT,

                    ADD COLUMN IF NOT EXISTS ufs_atendidas JSONB,

                    ADD COLUMN IF NOT EXISTS segmentos_atendidos JSONB,

                    ADD COLUMN IF NOT EXISTS modalidades_logisticas JSONB,

                    ADD COLUMN IF NOT EXISTS validado_por VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS validado_em TIMESTAMPTZ,

                    ADD COLUMN IF NOT EXISTS qualificado_por VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS qualificado_em TIMESTAMPTZ,

                    ADD COLUMN IF NOT EXISTS homologado_por VARCHAR(180),

                    ADD COLUMN IF NOT EXISTS homologado_em TIMESTAMPTZ,

                    ADD COLUMN IF NOT EXISTS motivo_status TEXT,

                    ADD COLUMN IF NOT EXISTS cadastro_externo_em TIMESTAMPTZ
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fabricas_status_fluxo
                    ON fabricas_parceiras(status_fluxo)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fabricas_disponivel_calculo_ia
                    ON fabricas_parceiras(disponivel_calculo_ia)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_fabricas_origem_cadastro
                    ON fabricas_parceiras(origem_cadastro)
                """)

                # =====================================================
                # REDE PROFISSIONAL — BARTENDERS / MIXOLOGISTAS
                # =====================================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS profissionais_rede (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(220) NOT NULL,
                        nome_profissional VARCHAR(220),

                        cidade VARCHAR(120),
                        estado VARCHAR(2),
                        regiao VARCHAR(40),

                        estabelecimento_nome VARCHAR(220),
                        estabelecimento_tipo VARCHAR(80),
                        cargo_funcao VARCHAR(160),

                        instagram VARCHAR(220),
                        whatsapp VARCHAR(80),
                        email VARCHAR(220),

                        especialidade VARCHAR(220),
                        experiencia_anos NUMERIC(8,2),

                        eventos TEXT[],
                        areas_atuacao TEXT[],

                        origem_cadastro VARCHAR(40)
                            NOT NULL DEFAULT 'externo',

                        status_fluxo VARCHAR(40)
                            NOT NULL DEFAULT 'mapeado',

                        status_relacionamento VARCHAR(40)
                            NOT NULL DEFAULT 'sem_contato',

                        recebeu_amostra BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        degustou BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        feedback_recebido BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        interessado BOOLEAN,

                        oportunidade_gerada BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        relevancia VARCHAR(40),

                        responsavel_dados_nome VARCHAR(220),
                        responsavel_dados_empresa VARCHAR(220),
                        responsavel_dados_cargo VARCHAR(160),
                        responsavel_dados_email VARCHAR(220),
                        responsavel_dados_whatsapp VARCHAR(80),

                        fonte_dados TEXT,
                        observacoes TEXT,

                        validado_por VARCHAR(220),
                        validado_em TIMESTAMPTZ,

                        qualificado_por VARCHAR(220),
                        qualificado_em TIMESTAMPTZ,

                        ativo_por VARCHAR(220),
                        ativo_em TIMESTAMPTZ,

                        disponivel_ia BOOLEAN
                            NOT NULL DEFAULT FALSE,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_profissionais_rede_status_fluxo
                    ON profissionais_rede(status_fluxo)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_profissionais_rede_estado
                    ON profissionais_rede(estado)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_profissionais_rede_disponivel_ia
                    ON profissionais_rede(disponivel_ia)
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
                # INTELIGENCIA COMERCIAL / RELACIONAMENTOS B2B
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS relacionamentos_b2b (
                        id UUID PRIMARY KEY,

                        nome VARCHAR(180) NOT NULL,
                        empresa VARCHAR(180),
                        cargo_funcao VARCHAR(180),

                        segmento VARCHAR(80),
                        tipo_relacao VARCHAR(80),

                        telefone VARCHAR(50),
                        email VARCHAR(180),
                        instagram VARCHAR(180),

                        cidade VARCHAR(120),
                        estado VARCHAR(2),

                        status_relacionamento VARCHAR(50)
                            NOT NULL DEFAULT 'prospectado',

                        primeiro_contato DATE,
                        ultimo_contato DATE,

                        respondeu BOOLEAN,
                        interesse_demonstrado BOOLEAN,
                        pediu_informacoes BOOLEAN,
                        conversa_tecnica BOOLEAN,

                        amostra_solicitada BOOLEAN,
                        amostra_enviada BOOLEAN,
                        amostra_provada BOOLEAN,
                        feedback_sensorial_recebido BOOLEAN,

                        oportunidade_comercial BOOLEAN,
                        compra_confirmada BOOLEAN,

                        evento_relacionado VARCHAR(220),

                        potencial_validacao_sensorial BOOLEAN,
                        potencial_networking BOOLEAN,
                        potencial_eventos BOOLEAN,
                        potencial_comercial BOOLEAN,

                        nivel_relacionamento INTEGER
                            NOT NULL DEFAULT 0,

                        proximo_passo TEXT,

                        evidencia TEXT,
                        fonte_dados TEXT,
                        observacoes TEXT,

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
                    idx_relacionamentos_b2b_status
                    ON relacionamentos_b2b (
                        status_relacionamento
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_relacionamentos_b2b_segmento
                    ON relacionamentos_b2b (
                        segmento
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_relacionamentos_b2b_nome
                    ON relacionamentos_b2b (
                        nome
                    )
                """)

                # ==========================================
                # EVIDENCIAS EMPRESARIAIS
                # ==========================================

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS evidencias_empresariais (
                        id UUID PRIMARY KEY,

                        titulo VARCHAR(250) NOT NULL,

                        categoria VARCHAR(80) NOT NULL,
                        area VARCHAR(80) NOT NULL,

                        entidade VARCHAR(180),

                        tipo_evidencia VARCHAR(60)
                            NOT NULL DEFAULT 'documental',

                        status VARCHAR(60)
                            NOT NULL DEFAULT 'vigente',

                        data_evidencia DATE,

                        resumo TEXT NOT NULL,
                        dados_estruturados JSONB,

                        fonte VARCHAR(250),
                        fonte_tipo VARCHAR(60),

                        confiabilidade VARCHAR(40)
                            NOT NULL DEFAULT 'documental',

                        substitui_id UUID,

                        observacoes TEXT,

                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),

                        CONSTRAINT fk_evidencia_substituida
                            FOREIGN KEY (substitui_id)
                            REFERENCES evidencias_empresariais(id)
                            ON DELETE SET NULL
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_evidencias_area
                    ON evidencias_empresariais (area)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_evidencias_categoria
                    ON evidencias_empresariais (categoria)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_evidencias_status
                    ON evidencias_empresariais (status)
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
            ] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"

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
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN")
META_INSTAGRAM_ACCESS_TOKEN = os.getenv("META_INSTAGRAM_ACCESS_TOKEN")


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
            executar_atualizacao_lead_crm,

        "responder_mensagem":
            executar_mensagem_instagram,

        "enviar_mensagem":
            executar_mensagem_instagram
    }

    executor = executores.get(tipo)

    if not executor:
        return {
            "success": False,
            "erro":
                "Tipo de execução não autorizado."
        }

    return executor(acao)


def executar_mensagem_instagram(acao):
    """
    Executor controlado de mensagens Instagram.

    Exige autorização prévia, evita execução duplicada
    e persiste o resultado real retornado pela Meta.
    """

    if not acao:
        return {
            "success": False,
            "erro": "Ação inexistente."
        }

    acao_id = str(
        acao.get("id")
        or ""
    ).strip()

    if not acao_id:
        return {
            "success": False,
            "erro": "Ação sem ID."
        }

    canal = str(
        acao.get("canal")
        or ""
    ).strip().lower()

    if canal != "instagram":
        return {
            "success": False,
            "erro":
                "Ação não pertence ao canal Instagram."
        }

    estado = str(
        acao.get("estado_execucao")
        or ""
    ).strip().lower()

    if estado != "autorizada":
        return {
            "success": False,
            "erro":
                "Ação Instagram ainda não autorizada."
        }

    destinatario = str(
        acao.get("destinatario")
        or ""
    ).strip()

    conteudo = str(
        acao.get("conteudo")
        or ""
    ).strip()

    destinatarios_invalidos = {
        "",
        "cliente",
        "cliente genérico",
        "cliente generico",
        "não especificado",
        "nao especificado",
        "não informado",
        "nao informado",
        "destinatário não especificado",
        "destinatario nao especificado"
    }

    if destinatario.lower() in destinatarios_invalidos:
        return {
            "success": False,
            "erro":
                "Destinatário Instagram real não informado."
        }

    if not conteudo:
        return {
            "success": False,
            "erro":
                "Conteúdo da mensagem Instagram ausente."
        }

    # -------------------------------------------------
    # RESERVA ATÔMICA DA EXECUÇÃO
    # Evita dois cliques enviarem a mesma mensagem.
    # -------------------------------------------------

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE acoes_empresariais
                    SET
                        estado_execucao = 'executando',
                        atualizado_em = NOW()
                    WHERE
                        id = %s
                        AND estado_execucao = 'autorizada'
                    RETURNING id
                """, (
                    acao_id,
                ))

                reservada = cur.fetchone()

        if not reservada:
            return {
                "success": False,
                "erro":
                    "Ação não está disponível para execução."
            }

    finally:
        conn.close()

    fila_compatibilidade = {
        "status": "aprovada",
        "destinatario_id": destinatario,
        "resposta_sugerida": conteudo
    }

    resultado = enviar_resposta_instagram(
        fila_compatibilidade
    )

    resultado_serializado = json.dumps(
        resultado,
        ensure_ascii=False,
        default=str
    )

    if resultado.get("success"):

        conn = get_db_connection()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            estado_execucao = 'executada',
                            status = 'concluida',
                            executor = 'instagram',
                            tentativas_execucao =
                                tentativas_execucao + 1,
                            executado_em = NOW(),
                            resultado = %s,
                            ultimo_erro = NULL,
                            atualizado_em = NOW()
                        WHERE
                            id = %s
                            AND estado_execucao = 'executando'
                    """, (
                        resultado_serializado,
                        acao_id
                    ))
        finally:
            conn.close()

        try:
            registrar_auditoria(
                categoria="execucao",
                acao="mensagem_instagram_enviada",
                ator_tipo="sistema",
                ator_id="backend",
                origem="motor_execucao",
                entidade_tipo="acao_empresarial",
                entidade_id=acao_id,
                status="executada",
                dados_saida={
                    "status_code":
                        resultado.get("status_code"),
                    "meta":
                        resultado.get("meta")
                }
            )
        except Exception as erro_auditoria:
            print(
                "ERRO AUDITORIA INSTAGRAM:",
                erro_auditoria
            )

        return resultado

    erro_resultado = resultado.get(
        "erro"
    )

    if not isinstance(erro_resultado, str):
        erro_resultado = json.dumps(
            erro_resultado,
            ensure_ascii=False,
            default=str
        )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE acoes_empresariais
                    SET
                        estado_execucao = 'falhou',
                        tentativas_execucao =
                            tentativas_execucao + 1,
                        resultado = %s,
                        ultimo_erro = %s,
                        atualizado_em = NOW()
                    WHERE
                        id = %s
                        AND estado_execucao = 'executando'
                """, (
                    resultado_serializado,
                    erro_resultado,
                    acao_id
                ))
    finally:
        conn.close()

    try:
        registrar_auditoria(
            categoria="execucao",
            acao="mensagem_instagram_falhou",
            ator_tipo="sistema",
            ator_id="backend",
            origem="motor_execucao",
            entidade_tipo="acao_empresarial",
            entidade_id=acao_id,
            status="falhou",
            erro=erro_resultado,
            dados_saida={
                "status_code":
                    resultado.get("status_code")
            }
        )
    except Exception as erro_auditoria:
        print(
            "ERRO AUDITORIA INSTAGRAM:",
            erro_auditoria
        )

    return resultado


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


def interpretar_saida_ia_empresarial(texto_bruto):
    """
    Interpreta a saída da IA empresarial.

    Aceita:
    - JSON correto;
    - JSON dentro de ```json;
    - pequeno erro comum de chave sem aspas;
    - texto puro como fallback.

    Nunca interrompe a operação por erro de formatação do modelo.
    """

    texto_bruto = str(
        texto_bruto or ""
    ).strip()

    if not texto_bruto:
        return {
            "resposta": "",
            "acoes_sugeridas": []
        }

    candidato = texto_bruto

    # Remove cercas Markdown.
    if candidato.startswith("```"):
        linhas = candidato.splitlines()

        if linhas:
            linhas = linhas[1:]

        if linhas and linhas[-1].strip() == "```":
            linhas = linhas[:-1]

        candidato = "\n".join(
            linhas
        ).strip()

    tentativas = [
        candidato
    ]

    # Correções conservadoras para erros comuns.
    corrigido = candidato.replace(
        "\nacoes_sugeridas:",
        '\n"acoes_sugeridas":'
    ).replace(
        ",acoes_sugeridas:",
        ',"acoes_sugeridas":'
    ).replace(
        " acoes_sugeridas:",
        ' "acoes_sugeridas":'
    )

    if corrigido != candidato:
        tentativas.append(
            corrigido
        )

    for tentativa in tentativas:

        try:
            dados = json.loads(
                tentativa
            )

            # Às vezes o JSON chega duplamente serializado.
            if isinstance(dados, str):
                try:
                    dados = json.loads(
                        dados
                    )
                except Exception:
                    return {
                        "resposta": dados.strip(),
                        "acoes_sugeridas": []
                    }

            if isinstance(dados, dict):

                resposta = str(
                    dados.get(
                        "resposta",
                        ""
                    )
                    or ""
                ).strip()

                acoes = dados.get(
                    "acoes_sugeridas",
                    []
                )

                if not isinstance(
                    acoes,
                    list
                ):
                    acoes = []

                return {
                    "resposta": resposta,
                    "acoes_sugeridas": acoes
                }

        except Exception:
            continue

    # Último fallback:
    # mantém a resposta utilizável sem derrubar a API.
    return {
        "resposta": texto_bruto,
        "acoes_sugeridas": []
    }


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
                        ON CONFLICT (
                            acao,
                            correlation_id
                        )
                        WHERE correlation_id IS NOT NULL
                        DO NOTHING
                        RETURNING id
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

                    resultado = cur.fetchone()

            if resultado:
                return str(resultado[0])

            # Registro já existente: operação idempotente.
            # Recupera o ID existente para distinguir
            # duplicidade legítima de falha real.
            if correlation_id:
                conn2 = get_db_connection()

                try:
                    with conn2.cursor() as cur:
                        cur.execute("""
                            SELECT id
                            FROM auditoria_eventos
                            WHERE acao = %s
                              AND correlation_id = %s
                            LIMIT 1
                        """, (
                            str(acao),
                            str(correlation_id)
                        ))

                        existente = cur.fetchone()

                    if existente:
                        return str(existente[0])

                finally:
                    conn2.close()

            return None

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
# DATA/HORA LOCAL — CONTEXTO EMPRESARIAL
# =====================================================

def formatar_data_hora_local(valor):
    """
    Converte timestamps do banco para o horário local
    da operação e devolve formato legível para a IA.
    """

    if not valor:
        return ""

    try:
        from datetime import timezone
        from zoneinfo import ZoneInfo

        if valor.tzinfo is None:
            valor = valor.replace(
                tzinfo=timezone.utc
            )

        valor_local = valor.astimezone(
            ZoneInfo("America/Sao_Paulo")
        )

        return valor_local.strftime(
            "%d/%m/%Y %H:%M"
        )

    except Exception:
        return str(valor)


# =====================================================
# INSTAGRAM — HISTÓRICO DE CONVERSAS PARA A IA
# =====================================================

def montar_contexto_conversas_instagram(
    limite=30,
    sender_id=None
):
    conn = get_db_connection()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            parametros = []
            filtro_sender = ""

            if sender_id:
                filtro_sender = (
                    "AND i.sender_id = %s"
                )
                parametros.append(
                    str(sender_id).strip()
                )

            parametros.append(
                int(limite)
            )

            cur.execute(
                f"""
                SELECT
                    i.id AS interacao_id,
                    i.sender_id,
                    i.texto AS mensagem_recebida,
                    i.criado_em AS mensagem_em,
                    i.classificacao,
                    i.interesse,
                    f.resposta_sugerida,
                    f.status AS resposta_status,
                    f.aprovado_em,
                    f.enviado_em,
                    f.erro_envio
                FROM interacoes_omnichannel i
                LEFT JOIN LATERAL (
                    SELECT
                        resposta_sugerida,
                        status,
                        aprovado_em,
                        enviado_em,
                        erro_envio
                    FROM fila_respostas_omnichannel
                    WHERE interacao_id = i.id
                    ORDER BY criado_em DESC
                    LIMIT 1
                ) f ON TRUE
                WHERE LOWER(i.canal) = 'instagram'
                {filtro_sender}
                ORDER BY i.criado_em DESC
                LIMIT %s
                """,
                tuple(parametros)
            )

            linhas = list(
                cur.fetchall()
            )

        if not linhas:
            return ""

        # -------------------------------------------------
        # AGRUPA CONVERSAS POR CONTATO
        # -------------------------------------------------

        conversas = {}

        for linha in linhas:
            sender = str(
                linha.get("sender_id") or ""
            ).strip()

            conversas.setdefault(
                sender,
                []
            ).append(
                linha
            )

        # Contatos mais recentes primeiro.
        grupos_ordenados = sorted(
            conversas.items(),
            key=lambda item: max(
                linha.get("mensagem_em")
                for linha in item[1]
                if linha.get("mensagem_em")
            ),
            reverse=True
        )

        blocos = [
            "\n\nHISTÓRICO REAL DE CONVERSAS DO INSTAGRAM:\n",
            (
                "As datas abaixo estão no horário local "
                "America/Sao_Paulo.\n"
            ),
            (
                "Cada contato aparece em um único bloco, "
                "com sua conversa em ordem cronológica.\n"
            ),
            (
                "Não trate resposta sugerida como mensagem enviada. "
                "Somente respostas com enviado_em preenchido representam "
                "fala efetivamente enviada pela Maranhão Cordial.\n"
            )
        ]

        for sender, mensagens in grupos_ordenados:

            blocos.append(
                "\nCONTATO INSTAGRAM "
                + sender
                + "\n"
            )

            mensagens = sorted(
                mensagens,
                key=lambda linha: (
                    linha.get("mensagem_em")
                )
            )

            for linha in mensagens:

                data_mensagem = (
                    formatar_data_hora_local(
                        linha.get("mensagem_em")
                    )
                )

                mensagem = str(
                    linha.get(
                        "mensagem_recebida"
                    )
                    or ""
                ).strip()

                blocos.append(
                    "["
                    + data_mensagem
                    + "] RECEBIDA: "
                    + mensagem
                    + "\n"
                )

                resposta = str(
                    linha.get(
                        "resposta_sugerida"
                    )
                    or ""
                ).strip()

                enviado_em = linha.get(
                    "enviado_em"
                )

                status = str(
                    linha.get(
                        "resposta_status"
                    )
                    or ""
                ).strip()

                if resposta and enviado_em:

                    data_envio = (
                        formatar_data_hora_local(
                            enviado_em
                        )
                    )

                    blocos.append(
                        "["
                        + data_envio
                        + "] MARANHÃO CORDIAL ENVIOU: "
                        + resposta
                        + "\n"
                    )

                elif resposta:

                    blocos.append(
                        "RESPOSTA SUGERIDA — NÃO ENVIADA"
                        " (status: "
                        + status
                        + "): "
                        + resposta
                        + "\n"
                    )

        return "".join(
            blocos
        )

    finally:
        conn.close()



# =====================================================
# INSTAGRAM — DETECTAR PEDIDO DE CONVERSAS
# =====================================================

def pergunta_requer_conversas_instagram(pergunta):
    import re

    texto = str(
        pergunta or ""
    ).lower().strip()

    termos = [
        "mensagem",
        "mensagens",
        "conversa",
        "conversas",
        "dm",
        "direct",
        "instagram",
        "respondeu",
        "resposta",
        "respostas",
        "histórico",
        "historico",
        "última mensagem",
        "ultima mensagem",
        "falou comigo",
        "mandou mensagem",
        "contato do instagram"
    ]

    for termo in termos:
        if " " in termo:
            if termo in texto:
                return True
        else:
            if re.search(
                r"(?<!\w)"
                + re.escape(termo)
                + r"(?!\w)",
                texto
            ):
                return True

    return False


# =====================================================
# OMNICHANNEL — REGISTRAR INTERAÇÃO
# =====================================================

def registrar_interacao_omnichannel(
    canal,
    sender_id,
    recipient_id,
    message_id,
    texto,
    plataforma="meta",
    tipo_interacao="mensagem",
    classificacao=None,
    interesse=None,
    lead_id=None
):
    canal = str(canal or "").strip().lower()
    plataforma = str(plataforma or "").strip().lower()

    sender_id = (
        str(sender_id).strip()
        if sender_id is not None
        else None
    )

    recipient_id = (
        str(recipient_id).strip()
        if recipient_id is not None
        else None
    )

    message_id = (
        str(message_id).strip()
        if message_id
        else None
    )

    texto = (
        str(texto).strip()
        if texto is not None
        else None
    )

    if not canal:
        raise ValueError(
            "Canal omnichannel obrigatório."
        )

    interacao_id = str(uuid.uuid4())

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                # Evita processar novamente a mesma
                # mensagem enviada pela Meta.
                if message_id:

                    cur.execute("""
                        SELECT *
                        FROM interacoes_omnichannel
                        WHERE message_id = %s
                        LIMIT 1
                    """, (
                        message_id,
                    ))

                    existente = cur.fetchone()

                    if existente:
                        return {
                            "success": True,
                            "duplicada": True,
                            "interacao":
                                dict(existente)
                        }

                cur.execute("""
                    INSERT INTO interacoes_omnichannel (
                        id,
                        canal,
                        plataforma,
                        sender_id,
                        recipient_id,
                        message_id,
                        texto,
                        tipo_interacao,
                        classificacao,
                        interesse,
                        lead_id,
                        processado_ia
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, FALSE
                    )
                    RETURNING *
                """, (
                    interacao_id,
                    canal,
                    plataforma,
                    sender_id,
                    recipient_id,
                    message_id,
                    texto,
                    tipo_interacao,
                    classificacao,
                    interesse,
                    lead_id
                ))

                interacao = cur.fetchone()

        return {
            "success": True,
            "duplicada": False,
            "interacao":
                dict(interacao)
                if interacao
                else None
        }

    finally:
        conn.close()


# =====================================================
# OMNICHANNEL — CLASSIFICAÇÃO COMERCIAL INICIAL
# =====================================================

def classificar_interacao_comercial(texto):

    texto_normalizado = str(
        texto or ""
    ).strip().lower()

    termos_b2b = (
        "bar",
        "restaurante",
        "hotel",
        "bartender",
        "barman",
        "distribuidor",
        "distribuidora",
        "revenda",
        "revender",
        "atacado",
        "fornecedor",
        "comprar para",
        "meu estabelecimento",
        "minha empresa",
        "meu restaurante",
        "meu bar",
        "meu hotel"
    )

    termos_degustacao = (
        "degustação",
        "degustacao",
        "experimentar",
        "provar",
        "amostra",
        "conhecer o produto",
        "apresentação",
        "apresentacao"
    )

    eh_b2b = any(
        termo in texto_normalizado
        for termo in termos_b2b
    )

    quer_degustacao = any(
        termo in texto_normalizado
        for termo in termos_degustacao
    )

    if eh_b2b:

        return {
            "relevante_crm": True,
            "tipo_lead": "b2b",
            "classificacao": "interesse_comercial_b2b",
            "interesse":
                "degustacao"
                if quer_degustacao
                else "contato_comercial",
            "estagio":
                "degustacao"
                if quer_degustacao
                else "novo"
        }

    return {
        "relevante_crm": False,
        "tipo_lead": None,
        "classificacao": "atendimento",
        "interesse": None,
        "estagio": None
    }


# =====================================================
# OMNICHANNEL — PROCESSAR PARA CRM
# =====================================================

def processar_interacao_omnichannel_crm(
    interacao
):

    if not interacao:
        return {
            "success": False,
            "erro": "Interação não informada."
        }

    interacao_id = str(
        interacao.get("id") or ""
    ).strip()

    canal = str(
        interacao.get("canal") or ""
    ).strip().lower()

    sender_id = str(
        interacao.get("sender_id") or ""
    ).strip()

    texto = str(
        interacao.get("texto") or ""
    ).strip()

    if not interacao_id:
        return {
            "success": False,
            "erro": "Interação sem ID."
        }

    classificacao = (
        classificar_interacao_comercial(
            texto
        )
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                # -----------------------------------------
                # NÃO É LEAD COMERCIAL
                # -----------------------------------------

                if not classificacao[
                    "relevante_crm"
                ]:

                    cur.execute("""
                        UPDATE interacoes_omnichannel
                        SET
                            classificacao = %s,
                            processado_ia = TRUE,
                            atualizado_em = NOW()
                        WHERE id = %s
                        RETURNING *
                    """, (
                        classificacao[
                            "classificacao"
                        ],
                        interacao_id
                    ))

                    atualizada = cur.fetchone()

                    return {
                        "success": True,
                        "lead_criado": False,
                        "lead_atualizado": False,
                        "classificacao":
                            classificacao,
                        "interacao":
                            dict(atualizada)
                            if atualizada
                            else None
                    }

                # -----------------------------------------
                # PROCURA LEAD EXISTENTE
                # canal + sender_id
                # -----------------------------------------

                cur.execute("""
                    SELECT *
                    FROM leads_crm
                    WHERE
                        canal = %s
                        AND contato = %s
                    ORDER BY criado_em DESC
                    LIMIT 1
                """, (
                    canal,
                    sender_id
                ))

                lead = cur.fetchone()

                lead_criado = False
                lead_atualizado = False

                # -----------------------------------------
                # ATUALIZA LEAD EXISTENTE
                # -----------------------------------------

                if lead:

                    observacao_nova = (
                        "["
                        + canal
                        + "] "
                        + texto[:1500]
                    )

                    observacao_anterior = (
                        lead.get(
                            "observacoes"
                        )
                        or ""
                    )

                    observacoes = (
                        observacao_anterior
                        + "\n"
                        + observacao_nova
                    ).strip()

                    cur.execute("""
                        UPDATE leads_crm
                        SET
                            interesse = %s,
                            estagio = CASE
                                WHEN estagio = 'novo'
                                     AND %s = 'degustacao'
                                THEN 'degustacao'
                                ELSE estagio
                            END,
                            observacoes = %s,
                            atualizado_em = NOW()
                        WHERE id = %s
                        RETURNING *
                    """, (
                        classificacao[
                            "interesse"
                        ],
                        classificacao[
                            "estagio"
                        ],
                        observacoes,
                        lead["id"]
                    ))

                    lead = cur.fetchone()
                    lead_atualizado = True

                # -----------------------------------------
                # CRIA NOVO LEAD
                # -----------------------------------------

                else:

                    lead_id = str(
                        uuid.uuid4()
                    )

                    observacoes = (
                        "Lead identificado "
                        "automaticamente pelo "
                        "omnichannel.\n"
                        "["
                        + canal
                        + "] "
                        + texto[:1500]
                    )

                    cur.execute("""
                        INSERT INTO leads_crm (
                            id,
                            nome,
                            empresa,
                            tipo_lead,
                            origem,
                            canal,
                            contato,
                            interesse,
                            estagio,
                            receita_acumulada_centavos,
                            observacoes
                        )
                        VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s
                        )
                        RETURNING *
                    """, (
                        lead_id,
                        None,
                        None,
                        classificacao[
                            "tipo_lead"
                        ],
                        canal,
                        canal,
                        sender_id,
                        classificacao[
                            "interesse"
                        ],
                        classificacao[
                            "estagio"
                        ],
                        0,
                        observacoes
                    ))

                    lead = cur.fetchone()
                    lead_criado = True

                # -----------------------------------------
                # LIGA INTERAÇÃO AO CRM
                # -----------------------------------------

                cur.execute("""
                    UPDATE interacoes_omnichannel
                    SET
                        classificacao = %s,
                        interesse = %s,
                        lead_id = %s,
                        processado_ia = TRUE,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    classificacao[
                        "classificacao"
                    ],
                    classificacao[
                        "interesse"
                    ],
                    lead["id"],
                    interacao_id
                ))

                atualizada = cur.fetchone()

                return {
                    "success": True,
                    "lead_criado":
                        lead_criado,
                    "lead_atualizado":
                        lead_atualizado,
                    "classificacao":
                        classificacao,
                    "lead":
                        dict(lead),
                    "interacao":
                        dict(atualizada)
                        if atualizada
                        else None
                }

    finally:
        conn.close()


# =====================================================
# OMNICHANNEL — GERAR RESPOSTA SUGERIDA
# =====================================================

def gerar_resposta_sugerida_omnichannel(
    interacao,
    processamento=None
):
    if not interacao:
        return {
            "success": False,
            "erro": "Interação não informada."
        }

    interacao_id = str(
        interacao.get("id") or ""
    ).strip()

    canal = str(
        interacao.get("canal") or ""
    ).strip().lower()

    sender_id = str(
        interacao.get("sender_id") or ""
    ).strip()

    texto = str(
        interacao.get("texto") or ""
    ).strip()

    if not interacao_id:
        return {
            "success": False,
            "erro": "Interação sem ID."
        }

    if not sender_id:
        return {
            "success": False,
            "erro": "Interação sem destinatário."
        }

    if not texto:
        return {
            "success": False,
            "erro": "Interação sem texto."
        }

    # -------------------------------------------------
    # NÃO DUPLICAR RESPOSTA PARA A MESMA INTERAÇÃO
    # -------------------------------------------------

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM fila_respostas_omnichannel
                    WHERE interacao_id = %s
                    ORDER BY criado_em DESC
                    LIMIT 1
                """, (
                    interacao_id,
                ))

                existente = cur.fetchone()

                if existente:
                    return {
                        "success": True,
                        "duplicada": True,
                        "fila":
                            dict(existente)
                    }

    finally:
        conn.close()

    # -------------------------------------------------
    # CLASSIFICAÇÃO JÁ REALIZADA
    # -------------------------------------------------

    classificacao = {}

    if isinstance(processamento, dict):
        classificacao = (
            processamento.get(
                "classificacao"
            )
            or {}
        )

    tipo_classificacao = str(
        classificacao.get(
            "classificacao"
        )
        or interacao.get(
            "classificacao"
        )
        or "atendimento"
    )

    interesse = str(
        classificacao.get(
            "interesse"
        )
        or interacao.get(
            "interesse"
        )
        or ""
    )

    # -------------------------------------------------
    # IDENTIFICA CONTEÚDO COMPARTILHADO
    # -------------------------------------------------

    texto_normalizado = (
        texto.strip()
    )

    texto_lower = (
        texto_normalizado.lower()
    )

    tipo_compartilhamento = ""

    if (
        texto_lower.startswith(
            "https://www.instagram.com/stories/"
        )
        or texto_lower.startswith(
            "https://instagram.com/stories/"
        )
    ):
        tipo_compartilhamento = "story"

    elif (
        texto_lower.startswith(
            "https://www.instagram.com/reel/"
        )
        or texto_lower.startswith(
            "https://instagram.com/reel/"
        )
        or texto_lower.startswith(
            "https://www.instagram.com/reels/"
        )
        or texto_lower.startswith(
            "https://instagram.com/reels/"
        )
    ):
        tipo_compartilhamento = "reel"

    elif (
        texto_lower.startswith(
            "https://www.instagram.com/p/"
        )
        or texto_lower.startswith(
            "https://instagram.com/p/"
        )
        or texto_lower.startswith(
            "https://www.instagram.com/tv/"
        )
        or texto_lower.startswith(
            "https://instagram.com/tv/"
        )
    ):
        tipo_compartilhamento = "publicacao"

    contexto_compartilhamento = ""

    if tipo_compartilhamento:

        contexto_compartilhamento = (
            "\nATENÇÃO SOBRE O CONTEÚDO RECEBIDO: "
            "A mensagem contém apenas um link de conteúdo "
            "compartilhado do Instagram. "
            "Você NÃO recebeu nem analisou a imagem, vídeo, "
            "áudio, legenda ou conteúdo interno desse link. "
            "Não diga nem insinue que viu, ouviu, gostou ou "
            "compreendeu o conteúdo compartilhado. "
            "Não deduza o assunto do conteúdo pelo link. "
            "Se responder, reconheça apenas que a pessoa "
            "compartilhou algo e mantenha a resposta neutra. "
        )

    # -------------------------------------------------
    # GERAÇÃO SEGURA DA RESPOSTA
    # -------------------------------------------------

    if not openai_client:

        resposta_sugerida = (
            "Olá! Obrigado pelo contato com a Maranhão Cordial. "
            "Recebemos sua mensagem e teremos prazer em orientar você."
        )

    else:

        try:
            resposta_ia = (
                openai_client.responses.create(
                    model="gpt-5-mini",

                    instructions=(
                        "Você é o atendimento externo oficial "
                        "da Maranhão Cordial. "

                        + CONTEXTO_MARANHAO +

                        "\nA mensagem veio de um canal público, "
                        "como Instagram ou WhatsApp. "

                        "Responda em português do Brasil. "
                        "Seja elegante, natural, cordial e objetivo. "
                        "Use no máximo 3 frases curtas. "

                        "Não revele informações internas da empresa. "
                        "Não mencione custos internos, fornecedores, "
                        "fábricas, margens, estratégias, CRM, documentos "
                        "internos, decisões empresariais ou dados de "
                        "outros clientes. "

                        "Não invente preço, prazo, disponibilidade, "
                        "condição comercial, desconto ou promessa. "

                        "Não aceite contratos, não feche negócios "
                        "e não assuma compromissos em nome da empresa. "

                        "Se houver interesse B2B, reconheça o interesse "
                        "e conduza naturalmente para continuidade do contato. "

                        "Se houver interesse em degustação, reconheça isso "
                        "sem prometer data, envio ou disponibilidade. "

                        "Faça no máximo uma pergunta, somente quando ela "
                        "for realmente útil para dar continuidade. "

                        "A resposta será revisada por um administrador "
                        "antes do envio. "

                        + contexto_compartilhamento
                    ),

                    input=(
                        "CANAL: "
                        + canal
                        + "\nCLASSIFICAÇÃO: "
                        + tipo_classificacao
                        + "\nINTERESSE: "
                        + interesse
                        + "\nTIPO DE COMPARTILHAMENTO: "
                        + (
                            tipo_compartilhamento
                            or "nenhum"
                        )
                        + "\nMENSAGEM DO CLIENTE:\n"
                        + texto
                    ),

                    reasoning={
                        "effort": "low"
                    },

                    max_output_tokens=220
                )
            )

            resposta_sugerida = (
                resposta_ia.output_text
                or ""
            ).strip()

            if not resposta_sugerida:
                resposta_sugerida = (
                    "Olá! Obrigado pelo contato com a Maranhão Cordial. "
                    "Recebemos sua mensagem e teremos prazer em orientar você."
                )

        except Exception as erro_ia:

            print(
                "ERRO IA RESPOSTA OMNICHANNEL:",
                repr(erro_ia)
            )

            resposta_sugerida = (
                "Olá! Obrigado pelo contato com a Maranhão Cordial. "
                "Recebemos sua mensagem e teremos prazer em orientar você."
            )

    # -------------------------------------------------
    # FILA — SEM ENVIO AUTOMÁTICO
    # -------------------------------------------------

    fila_id = str(
        uuid.uuid4()
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO fila_respostas_omnichannel (
                        id,
                        interacao_id,
                        canal,
                        destinatario_id,
                        resposta_sugerida,
                        status,
                        modo_autonomia
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s,
                        'aguardando_aprovacao',
                        'manual'
                    )
                    RETURNING *
                """, (
                    fila_id,
                    interacao_id,
                    canal,
                    sender_id,
                    resposta_sugerida
                ))

                fila = cur.fetchone()

        # -------------------------------------------------
        # FILA UNIVERSAL — AÇÃO EMPRESARIAL GOVERNADA
        # -------------------------------------------------

        acao_id = criar_acao_empresarial(
            tipo="responder_mensagem",
            canal=canal,
            conteudo=resposta_sugerida,
            destinatario=sender_id,
            justificativa=(
                "Resposta sugerida para interação omnichannel "
                + interacao_id
            ),
            prioridade="media",
            status="aguardando_aprovacao"
        )

        return {
            "success": True,
            "duplicada": False,
            "fila":
                dict(fila)
                if fila
                else None,
            "acao_empresarial_id":
                acao_id
        }

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


@app.route("/cadastro-fabrica")
@app.route("/cadastro-fabrica.html")
def cadastro_fabrica():
    return renderizar_html(
        "cadastro-fabrica.html"
    )


@app.route("/cadastro-profissional-rede")
@app.route("/cadastro-profissional-rede.html")
def cadastro_profissional_rede():
    return renderizar_html(
        "cadastro-profissional-rede.html"
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
# META — PÁGINAS LEGAIS
# =====================================================

@app.route("/politica-de-privacidade")
def politica_de_privacidade():
    return """
    <html>
    <head>
        <meta charset="utf-8">
        <title>Política de Privacidade - Maranhão Cordial</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:800px;margin:40px auto;line-height:1.6">
        <h1>Política de Privacidade</h1>

        <p>A Maranhão Cordial utiliza dados fornecidos por usuários para atendimento,
        relacionamento comercial, suporte, processamento de solicitações e melhoria
        dos seus serviços.</p>

        <p>Quando usuários entram em contato por Instagram, WhatsApp ou outros canais
        integrados, mensagens e dados necessários ao atendimento podem ser processados
        pelos sistemas da empresa.</p>

        <p>Os dados não são comercializados e são utilizados apenas para as finalidades
        relacionadas à operação da Maranhão Cordial.</p>

        <p>O titular pode solicitar esclarecimentos, correção ou exclusão de seus dados
        pelos canais oficiais da empresa.</p>

        <p>Última atualização: 24 de agosto de 2026.</p>
    </body>
    </html>
    """, 200


@app.route("/termos-de-servico")
def termos_de_servico():
    return """
    <html>
    <head>
        <meta charset="utf-8">
        <title>Termos de Serviço - Maranhão Cordial</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:800px;margin:40px auto;line-height:1.6">
        <h1>Termos de Serviço</h1>

        <p>Os canais digitais da Maranhão Cordial destinam-se ao atendimento,
        relacionamento comercial, suporte e fornecimento de informações sobre
        seus produtos e serviços.</p>

        <p>O uso dos canais implica concordância com estes termos e com a
        Política de Privacidade.</p>

        <p>As informações fornecidas pelos sistemas podem ser atualizadas
        conforme a operação da empresa.</p>

        <p>Última atualização: 24 de agosto de 2026.</p>
    </body>
    </html>
    """, 200


@app.route("/exclusao-de-dados")
def exclusao_de_dados():
    return """
    <html>
    <head>
        <meta charset="utf-8">
        <title>Exclusão de Dados - Maranhão Cordial</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:800px;margin:40px auto;line-height:1.6">
        <h1>Solicitação de Exclusão de Dados</h1>

        <p>Usuários podem solicitar a exclusão de dados pessoais associados
        ao atendimento realizado pelos canais digitais da Maranhão Cordial.</p>

        <p>Para solicitar a exclusão, entre em contato pelos canais oficiais
        da empresa e informe os dados necessários para identificação do atendimento.</p>

        <p>Após a validação da solicitação, os dados serão excluídos ou anonimizados
        quando aplicável, respeitadas as obrigações legais e regulatórias.</p>

        <p>Última atualização: 24 de agosto de 2026.</p>
    </body>
    </html>
    """, 200


# =====================================================
# ADMIN — OMNICHANNEL / FILA DE RESPOSTAS
# =====================================================

def validar_admin_omnichannel():

    chave = request.headers.get(
        "X-Admin-Key"
    )

    return bool(
        ADMIN_API_KEY
        and chave == ADMIN_API_KEY
    )


@app.route(
    "/api/admin/omnichannel/respostas",
    methods=["GET"]
)
def admin_listar_respostas_omnichannel():

    if not validar_admin_omnichannel():

        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    status = str(
        request.args.get(
            "status",
            ""
        )
    ).strip().lower()

    limite_raw = request.args.get(
        "limite",
        "100"
    )

    try:
        limite = int(
            limite_raw
        )
    except Exception:
        limite = 100

    limite = max(
        1,
        min(
            limite,
            200
        )
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                if status:

                    cur.execute("""
                        SELECT
                            f.*,
                            i.texto AS mensagem_recebida,
                            i.sender_id,
                            i.message_id,
                            i.classificacao,
                            i.interesse,
                            i.lead_id
                        FROM fila_respostas_omnichannel f
                        JOIN interacoes_omnichannel i
                            ON i.id = f.interacao_id
                        WHERE f.status = %s
                        ORDER BY f.criado_em DESC
                        LIMIT %s
                    """, (
                        status,
                        limite
                    ))

                else:

                    cur.execute("""
                        SELECT
                            f.*,
                            i.texto AS mensagem_recebida,
                            i.sender_id,
                            i.message_id,
                            i.classificacao,
                            i.interesse,
                            i.lead_id
                        FROM fila_respostas_omnichannel f
                        JOIN interacoes_omnichannel i
                            ON i.id = f.interacao_id
                        ORDER BY f.criado_em DESC
                        LIMIT %s
                    """, (
                        limite,
                    ))

                filas = cur.fetchall()

        return jsonify({
            "success": True,
            "total":
                len(filas),
            "respostas":
                [
                    dict(item)
                    for item in filas
                ]
        }), 200

    finally:
        conn.close()


@app.route(
    "/api/admin/omnichannel/respostas/<resposta_id>",
    methods=["PATCH"]
)
def admin_decidir_resposta_omnichannel(
    resposta_id
):

    if not validar_admin_omnichannel():

        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    acao = str(
        dados.get(
            "acao",
            ""
        )
    ).strip().lower()

    resposta_editada = str(
        dados.get(
            "resposta",
            ""
        )
    ).strip()

    admin_id = str(
        dados.get(
            "admin",
            "admin"
        )
    ).strip() or "admin"

    if acao not in {
        "aprovar",
        "rejeitar"
    }:

        return jsonify({
            "success": False,
            "error":
                "Ação deve ser aprovar ou rejeitar."
        }), 400

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM fila_respostas_omnichannel
                    WHERE id = %s
                    LIMIT 1
                """, (
                    resposta_id,
                ))

                fila = cur.fetchone()

                if not fila:

                    return jsonify({
                        "success": False,
                        "error":
                            "Resposta não encontrada."
                    }), 404

                status_atual = str(
                    fila.get(
                        "status"
                    )
                    or ""
                ).strip().lower()

                if status_atual not in {
                    "aguardando_aprovacao",
                    "aprovada"
                }:

                    return jsonify({
                        "success": False,
                        "error":
                            "Esta resposta já foi processada.",
                        "status":
                            status_atual
                    }), 409

                if acao == "rejeitar":

                    cur.execute("""
                        UPDATE fila_respostas_omnichannel
                        SET
                            status = 'rejeitada',
                            atualizado_em = NOW()
                        WHERE id = %s
                        RETURNING *
                    """, (
                        resposta_id,
                    ))

                    atualizada = cur.fetchone()

                    return jsonify({
                        "success": True,
                        "acao": "rejeitar",
                        "resposta":
                            dict(atualizada)
                    }), 200

                texto_final = (
                    resposta_editada
                    or str(
                        fila.get(
                            "resposta_sugerida"
                        )
                        or ""
                    ).strip()
                )

                if not texto_final:

                    return jsonify({
                        "success": False,
                        "error":
                            "Resposta final vazia."
                    }), 400

                cur.execute("""
                    UPDATE fila_respostas_omnichannel
                    SET
                        resposta_sugerida = %s,
                        status = 'aprovada',
                        aprovado_por = %s,
                        aprovado_em = NOW(),
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    texto_final,
                    admin_id,
                    resposta_id
                ))

                atualizada = cur.fetchone()

        return jsonify({
            "success": True,
            "acao": "aprovar",
            "resposta":
                dict(atualizada)
        }), 200

    finally:
        conn.close()


# =====================================================
# INSTAGRAM — ENVIO DE RESPOSTA APROVADA
# =====================================================

def obter_config_instagram_mensagens():

    token = (
        os.getenv("META_INSTAGRAM_ACCESS_TOKEN")
        or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("PAGE_ACCESS_TOKEN")
        or ""
    ).strip()

    conta_id = (
        os.getenv("META_INSTAGRAM_ACCOUNT_ID")
        or os.getenv("INSTAGRAM_ACCOUNT_ID")
        or os.getenv("INSTAGRAM_USER_ID")
        or os.getenv("INSTAGRAM_ID")
        or ""
    ).strip()

    endpoint_customizado = (
        os.getenv("INSTAGRAM_MESSAGES_ENDPOINT")
        or ""
    ).strip()

    return {
        "token": token,
        "conta_id": conta_id,
        "endpoint":
            endpoint_customizado
    }


def enviar_resposta_instagram(
    fila
):

    if not fila:
        return {
            "success": False,
            "erro": "Resposta não informada."
        }

    status = str(
        fila.get("status")
        or ""
    ).strip().lower()

    if status != "aprovada":

        return {
            "success": False,
            "erro":
                "Resposta ainda não foi aprovada."
        }

    destinatario = str(
        fila.get(
            "destinatario_id"
        )
        or ""
    ).strip()

    texto = str(
        fila.get(
            "resposta_sugerida"
        )
        or ""
    ).strip()

    if not destinatario:

        return {
            "success": False,
            "erro":
                "Destinatário Instagram ausente."
        }

    if not texto:

        return {
            "success": False,
            "erro":
                "Texto da resposta ausente."
        }

    config = (
        obter_config_instagram_mensagens()
    )

    token = config["token"]
    conta_id = config["conta_id"]
    endpoint = config["endpoint"]

    if not token:

        return {
            "success": False,
            "erro":
                "Token Instagram/Meta não configurado."
        }

    if not endpoint:

        if not conta_id:

            return {
                "success": False,
                "erro":
                    "INSTAGRAM_ACCOUNT_ID não configurado."
            }

        endpoint = (
            "https://graph.instagram.com/"
            "v26.0/"
            + conta_id
            + "/messages"
        )

    payload = {
        "recipient": {
            "id": destinatario
        },
        "message": {
            "text": texto
        }
    }

    try:

        resposta = requests.post(
            endpoint,
            headers={
                "Authorization":
                    "Bearer " + token,
                "Content-Type":
                    "application/json"
            },
            json=payload,
            timeout=30
        )

        corpo = {}

        try:
            corpo = resposta.json()
        except Exception:
            corpo = {
                "raw":
                    resposta.text[:1000]
            }

        if not resposta.ok:

            return {
                "success": False,
                "status_code":
                    resposta.status_code,
                "erro":
                    corpo
            }

        return {
            "success": True,
            "status_code":
                resposta.status_code,
            "meta":
                corpo
        }

    except Exception as erro:

        return {
            "success": False,
            "erro":
                str(erro)
        }


@app.route(
    "/api/admin/omnichannel/respostas/<resposta_id>/enviar",
    methods=["POST"]
)
def admin_enviar_resposta_omnichannel(
    resposta_id
):

    if not validar_admin_omnichannel():

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

                # Trava a linha durante a decisão de envio.
                cur.execute("""
                    SELECT *
                    FROM fila_respostas_omnichannel
                    WHERE id = %s
                    FOR UPDATE
                """, (
                    resposta_id,
                ))

                fila = cur.fetchone()

                if not fila:

                    return jsonify({
                        "success": False,
                        "error":
                            "Resposta não encontrada."
                    }), 404

                status = str(
                    fila.get("status") or ""
                ).strip().lower()

                # Idempotência: mensagem já confirmada.
                if status == "enviada":

                    return jsonify({
                        "success": True,
                        "ja_enviada": True,
                        "resposta": dict(fila)
                    }), 200

                # Uma tentativa anterior ficou em estado
                # intermediário. Não arrisca duplicidade.
                if status == "enviando":

                    return jsonify({
                        "success": False,
                        "envio_incerto": True,
                        "error":
                            "Já existe uma tentativa de envio em andamento ou sem confirmação. Verifique antes de reenviar.",
                        "status": status
                    }), 409

                if status != "aprovada":

                    return jsonify({
                        "success": False,
                        "error":
                            "A resposta precisa ser aprovada antes do envio.",
                        "status": status
                    }), 409

                canal = str(
                    fila.get("canal") or ""
                ).strip().lower()

                if canal != "instagram":

                    return jsonify({
                        "success": False,
                        "error":
                            "Este endpoint envia somente mensagens do Instagram."
                    }), 400

                # Marca ANTES da chamada externa.
                # Se a conexão cair depois que a Meta receber,
                # não permitimos um segundo envio automático.
                cur.execute("""
                    UPDATE fila_respostas_omnichannel
                    SET
                        status = 'enviando',
                        erro_envio = NULL,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    resposta_id,
                ))

                fila_envio = cur.fetchone()

                resultado = enviar_resposta_instagram(
                    {
                        **dict(fila_envio),
                        "status": "aprovada"
                    }
                )

                meta = (
                    resultado.get("meta")
                    if isinstance(resultado, dict)
                    else None
                )

                message_id = ""

                if isinstance(meta, dict):
                    message_id = str(
                        meta.get("message_id")
                        or meta.get("message")
                        or ""
                    ).strip()

                confirmado = bool(
                    resultado.get("success")
                    and message_id
                )

                if confirmado:

                    cur.execute("""
                        UPDATE fila_respostas_omnichannel
                        SET
                            status = 'enviada',
                            enviado_em = NOW(),
                            erro_envio = NULL,
                            atualizado_em = NOW()
                        WHERE id = %s
                        RETURNING *
                    """, (
                        resposta_id,
                    ))

                    atualizada = cur.fetchone()

                    return jsonify({
                        "success": True,
                        "confirmado_meta": True,
                        "message_id": message_id,
                        "envio": resultado,
                        "resposta":
                            dict(atualizada)
                    }), 200

                # HTTP/resultado sem confirmação inequívoca:
                # permanece "enviando" para impedir duplicidade.
                detalhe = str(resultado)[:4000]

                cur.execute("""
                    UPDATE fila_respostas_omnichannel
                    SET
                        erro_envio = %s,
                        atualizado_em = NOW()
                    WHERE id = %s
                    RETURNING *
                """, (
                    detalhe,
                    resposta_id
                ))

                atualizada = cur.fetchone()

                return jsonify({
                    "success": False,
                    "envio_incerto": True,
                    "error":
                        "O envio não teve confirmação inequívoca da Meta. O sistema bloqueou novo envio para evitar duplicidade.",
                    "detalhes": resultado,
                    "resposta":
                        dict(atualizada)
                }), 502

    except Exception as erro:

        print(
            "ERRO ENVIO OMNICHANNEL:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "envio_incerto": True,
            "error":
                "Falha durante a tentativa de envio. Novo envio foi bloqueado por segurança."
        }), 500

    finally:
        conn.close()


# =====================================================

# =====================================================
# GOOGLE / GMAIL — CONFIGURAÇÃO
# =====================================================

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

GMAIL_CLIENT_ID = os.getenv("GOOGLE_GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GOOGLE_GMAIL_CLIENT_SECRET")
GMAIL_REDIRECT_URI = os.getenv("GOOGLE_GMAIL_REDIRECT_URI")

GMAIL_CLIENT_CONFIG = {
    "web": {
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [
            GMAIL_REDIRECT_URI
        ] if GMAIL_REDIRECT_URI else []
    }
}


# =====================================================
# GOOGLE / GMAIL — OAUTH
# =====================================================

@app.route("/api/gmail/conectar")
def gmail_conectar():
    if not all([
        GMAIL_CLIENT_ID,
        GMAIL_CLIENT_SECRET,
        GMAIL_REDIRECT_URI
    ]):
        return jsonify({
            "success": False,
            "erro": "Configuração OAuth do Gmail incompleta."
        }), 500

    flow = Flow.from_client_config(
        GMAIL_CLIENT_CONFIG,
        scopes=GMAIL_SCOPES
    )

    flow.redirect_uri = GMAIL_REDIRECT_URI

    authorization_url, state = (
        flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
    )

    session["gmail_oauth_state"] = state
    session["gmail_code_verifier"] = flow.code_verifier

    return redirect(authorization_url)


@app.route("/api/gmail/callback")
def gmail_callback():
    state = session.get("gmail_oauth_state")

    if not state:
        return jsonify({
            "success": False,
            "erro": "Estado OAuth do Gmail não encontrado."
        }), 400

    flow = Flow.from_client_config(
        GMAIL_CLIENT_CONFIG,
        scopes=GMAIL_SCOPES,
        state=state
    )

    flow.redirect_uri = GMAIL_REDIRECT_URI
    flow.code_verifier = session.get("gmail_code_verifier")

    flow.fetch_token(
        authorization_response=request.url
    )

    credentials = flow.credentials

    session["gmail_credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }

    return jsonify({
        "success": True,
        "mensagem": "Gmail conectado com sucesso."
    })






# =====================================================
# GOOGLE / GMAIL — SINCRONIZAR COM IA EMPRESARIAL
# =====================================================

@app.route("/api/gmail/sincronizar")
def gmail_sincronizar():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    dados = session.get("gmail_credentials")

    if not dados:
        return jsonify({
            "success": False,
            "erro": "Gmail ainda não autorizado.",
            "conectar": "/api/gmail/conectar"
        }), 401

    credentials = Credentials(
        token=dados.get("token"),
        refresh_token=dados.get("refresh_token"),
        token_uri=dados.get("token_uri"),
        client_id=dados.get("client_id"),
        client_secret=dados.get("client_secret"),
        scopes=dados.get("scopes")
    )

    # Renova automaticamente o token quando necessário
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(
            GoogleRequest()
        )

        session["gmail_credentials"] = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }

    resultado = gmail_buscar_mensagens(
        access_token=credentials.token,
        limite=20
    )

    return jsonify(resultado)


# =====================================================
# GOOGLE / GMAIL — RECEBER MENSAGENS
# =====================================================

def gmail_buscar_mensagens(access_token, limite=20):
    import requests
    import base64

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    resposta = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={
            "maxResults": limite,
            "q": "in:inbox"
        },
        timeout=30
    )

    resposta.raise_for_status()

    mensagens = resposta.json().get(
        "messages",
        []
    )

    resultados = []

    for item in mensagens:

        gmail_id = item.get("id")

        detalhe = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gmail_id}",
            headers=headers,
            params={"format": "full"},
            timeout=30
        )

        detalhe.raise_for_status()

        dados = detalhe.json()
        payload = dados.get("payload", {})

        cabecalhos = {
            h.get("name", "").lower():
                h.get("value", "")
            for h in payload.get("headers", [])
        }

        remetente = cabecalhos.get("from", "")
        destinatario = cabecalhos.get("to", "")
        assunto = cabecalhos.get("subject", "")

        texto = ""

        body_data = (
            payload
            .get("body", {})
            .get("data")
        )

        if body_data:
            try:
                texto = base64.urlsafe_b64decode(
                    body_data + "=="
                ).decode(
                    "utf-8",
                    errors="replace"
                )
            except Exception:
                texto = ""

        if not texto:

            for parte in payload.get("parts", []):

                if parte.get("mimeType") == "text/plain":

                    data = (
                        parte
                        .get("body", {})
                        .get("data")
                    )

                    if data:
                        try:
                            texto = base64.urlsafe_b64decode(
                                data + "=="
                            ).decode(
                                "utf-8",
                                errors="replace"
                            )
                        except Exception:
                            texto = ""

                        break

        if not texto:
            texto = dados.get("snippet", "")

        texto_completo = (
            f"Assunto: {assunto}\n\n"
            f"{texto}"
        ).strip()

        registro = registrar_interacao_omnichannel(
            canal="gmail",
            plataforma="gmail",
            sender_id=remetente,
            recipient_id=destinatario,
            message_id=gmail_id,
            texto=texto_completo,
            tipo_interacao="email"
        )

        processamento = None

        if (
            registro.get("success")
            and
            not registro.get("duplicada")
        ):
            processamento = (
                processar_interacao_omnichannel_crm(
                    registro.get("interacao")
                )
            )

        resultados.append({
            "gmail_id": gmail_id,
            "remetente": remetente,
            "assunto": assunto,
            "registro": registro,
            "processamento": processamento
        })

    return {
        "success": True,
        "canal": "gmail",
        "quantidade": len(resultados),
        "mensagens": resultados
    }


# META / WHATSAPP — WEBHOOK
# =====================================================

@app.route(
    "/webhooks/meta",
    methods=["GET", "POST"]
)
def webhook_meta():

    # -------------------------------------------------
    # GET — VERIFICAÇÃO INICIAL DA META
    # -------------------------------------------------

    if request.method == "GET":

        modo = request.args.get(
            "hub.mode",
            ""
        )

        token_recebido = request.args.get(
            "hub.verify_token",
            ""
        )

        desafio = request.args.get(
            "hub.challenge",
            ""
        )

        if (
            modo == "subscribe"
            and META_WEBHOOK_VERIFY_TOKEN
            and token_recebido
                == META_WEBHOOK_VERIFY_TOKEN
        ):

            print(
                "META WEBHOOK VERIFICADO"
            )

            return (
                desafio,
                200,
                {
                    "Content-Type":
                        "text/plain; charset=utf-8"
                }
            )

        print(
            "META WEBHOOK — FALHA DE VERIFICACAO"
        )

        return jsonify({
            "success": False,
            "error":
                "Falha na verificação do webhook."
        }), 403

    # -------------------------------------------------
    # POST — EVENTOS DO WHATSAPP
    # -------------------------------------------------

    payload = request.get_json(
        silent=True
    ) or {}

    try:

        objeto = payload.get(
            "object"
        )

        entradas = payload.get(
            "entry"
        ) or []

        total_changes = 0
        total_messaging = 0

        for entrada in entradas:

            changes = entrada.get(
                "changes"
            ) or []

            messaging = entrada.get(
                "messaging"
            ) or []

            total_changes += len(
                changes
            )

            total_messaging += len(
                messaging
            )

            for evento in messaging:

                remetente = (
                    evento.get("sender")
                    or {}
                ).get("id")

                destinatario = (
                    evento.get("recipient")
                    or {}
                ).get("id")

                mensagem = (
                    evento.get("message")
                    or {}
                )

                texto = mensagem.get(
                    "text"
                )

                mid = mensagem.get(
                    "mid"
                )

                echo = mensagem.get(
                    "is_echo",
                    False
                )

                print(
                    "INSTAGRAM MENSAGEM RECEBIDA",
                    {
                        "sender_id":
                            remetente,
                        "recipient_id":
                            destinatario,
                        "mid":
                            mid,
                        "is_echo":
                            echo,
                        "text":
                            texto[:300]
                            if isinstance(texto, str)
                            else None
                    }
                )

                # -----------------------------------------
                # REGISTRO OMNICHANNEL
                # -----------------------------------------

                if (
                    not echo
                    and isinstance(texto, str)
                    and texto.strip()
                ):

                    try:
                        registro = (
                            registrar_interacao_omnichannel(
                                canal="instagram",
                                sender_id=remetente,
                                recipient_id=destinatario,
                                message_id=mid,
                                texto=texto,
                                plataforma="meta",
                                tipo_interacao="mensagem"
                            )
                        )

                        print(
                            "OMNICHANNEL REGISTRADO",
                            {
                                "canal":
                                    "instagram",
                                "duplicada":
                                    registro.get(
                                        "duplicada"
                                    )
                            }
                        )

                        # ---------------------------------
                        # PROCESSAMENTO CRM
                        # ---------------------------------

                        if not registro.get(
                            "duplicada"
                        ):

                            try:
                                processamento = (
                                    processar_interacao_omnichannel_crm(
                                        registro.get(
                                            "interacao"
                                        )
                                    )
                                )

                                print(
                                    "OMNICHANNEL CRM PROCESSADO",
                                    {
                                        "lead_criado":
                                            processamento.get(
                                                "lead_criado"
                                            ),
                                        "lead_atualizado":
                                            processamento.get(
                                                "lead_atualizado"
                                            ),
                                        "classificacao":
                                            (
                                                processamento.get(
                                                    "classificacao"
                                                )
                                                or {}
                                            ).get(
                                                "classificacao"
                                            )
                                    }
                                )

                            # ---------------------------------
                                # RESPOSTA SUGERIDA — FILA MANUAL
                                # ---------------------------------

                                try:
                                    sugestao = (
                                        gerar_resposta_sugerida_omnichannel(
                                            registro.get(
                                                "interacao"
                                            ),
                                            processamento
                                        )
                                    )

                                    print(
                                        "OMNICHANNEL RESPOSTA SUGERIDA",
                                        {
                                            "criada":
                                                not sugestao.get(
                                                    "duplicada",
                                                    False
                                                ),
                                            "status":
                                                (
                                                    sugestao.get(
                                                        "fila"
                                                    )
                                                    or {}
                                                ).get(
                                                    "status"
                                                )
                                        }
                                    )

                                except Exception as erro_sugestao:

                                    print(
                                        "ERRO RESPOSTA SUGERIDA:",
                                        repr(
                                            erro_sugestao
                                        )
                                    )

                            except Exception as erro_crm:

                                print(
                                    "ERRO PROCESSAMENTO CRM:",
                                    repr(
                                        erro_crm
                                    )
                                )

                    except Exception as erro_registro:

                        print(
                            "ERRO REGISTRO OMNICHANNEL:",
                            repr(
                                erro_registro
                            )
                        )

        print(
            "META WEBHOOK RECEBIDO",
            {
                "object":
                    objeto,
                "entries":
                    len(entradas),
                "changes":
                    total_changes,
                "messaging":
                    total_messaging
            }
        )

        # Nesta etapa:
        # - recebemos eventos da Meta;
        # - identificamos mensagens do Instagram;
        # - ainda NÃO enviamos resposta automática.

        return jsonify({
            "success": True
        }), 200

    except Exception as erro:

        print(
            "ERRO META WEBHOOK:",
            repr(erro)
        )

        # A Meta prefere confirmação rápida do webhook.
        # Mantemos 200 para evitar retries desnecessários
        # enquanto a integração está em desenvolvimento.

        return jsonify({
            "success": True
        }), 200


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

    status_documento = dados.get(
        "status_documento"
    )

    usar_na_ia = dados.get(
        "usar_na_ia"
    )

    atualizacoes = []
    valores = []

    if status_documento is not None:

        status_documento = str(
            status_documento
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

        atualizacoes.append(
            "status_documento = %s"
        )

        valores.append(
            status_documento
        )

    if usar_na_ia is not None:

        if isinstance(
            usar_na_ia,
            str
        ):
            usar_na_ia = (
                usar_na_ia.strip().lower()
                in {
                    "1",
                    "true",
                    "sim",
                    "on"
                }
            )
        else:
            usar_na_ia = bool(
                usar_na_ia
            )

        atualizacoes.append(
            "usar_na_ia = %s"
        )

        valores.append(
            usar_na_ia
        )

    if not atualizacoes:
        return jsonify({
            "success": False,
            "error":
                "Informe status_documento ou usar_na_ia."
        }), 400

    atualizacoes.append(
        "atualizado_em = NOW()"
    )

    valores.append(
        documento_id
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                query = f"""
                    UPDATE documentos_empresariais
                    SET
                        {", ".join(atualizacoes)}
                    WHERE id = %s
                    RETURNING
                        id,
                        status_documento,
                        usar_na_ia
                """

                cur.execute(
                    query,
                    tuple(valores)
                )

                atualizado = cur.fetchone()

        if not atualizado:
            return jsonify({
                "success": False,
                "error": "Documento não encontrado."
            }), 404

        return jsonify({
            "success": True,
            "documento":
                dict(atualizado)
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




# =====================================================
# ADMIN — EVIDÊNCIAS EMPRESARIAIS
# =====================================================

@app.route(
    "/api/admin/evidencias",
    methods=["GET", "POST"]
)
def admin_evidencias_empresariais():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:

        # ---------------------------------------------
        # GET — LISTAR EVIDÊNCIAS
        # ---------------------------------------------

        if request.method == "GET":

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM evidencias_empresariais
                    ORDER BY
                        data_evidencia DESC NULLS LAST,
                        criado_em DESC
                """)

                evidencias = cur.fetchall()

            return jsonify({
                "success": True,
                "total": len(evidencias),
                "evidencias": evidencias
            }), 200

        # ---------------------------------------------
        # POST — CRIAR EVIDÊNCIA
        # ---------------------------------------------

        dados = request.get_json(
            silent=True
        ) or {}

        titulo = str(
            dados.get("titulo") or ""
        ).strip()

        categoria = str(
            dados.get("categoria") or ""
        ).strip().lower()

        area = str(
            dados.get("area") or ""
        ).strip().lower()

        resumo = str(
            dados.get("resumo") or ""
        ).strip()

        if not titulo:
            return jsonify({
                "success": False,
                "error": "titulo obrigatório."
            }), 400

        if not categoria:
            return jsonify({
                "success": False,
                "error": "categoria obrigatória."
            }), 400

        if not area:
            return jsonify({
                "success": False,
                "error": "area obrigatória."
            }), 400

        if not resumo:
            return jsonify({
                "success": False,
                "error": "resumo obrigatório."
            }), 400

        evidencia_id = str(
            uuid.uuid4()
        )

        dados_estruturados = (
            dados.get("dados_estruturados")
        )

        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO evidencias_empresariais (
                        id,
                        titulo,
                        categoria,
                        area,
                        entidade,
                        tipo_evidencia,
                        status,
                        data_evidencia,
                        resumo,
                        dados_estruturados,
                        fonte,
                        fonte_tipo,
                        confiabilidade,
                        substitui_id,
                        observacoes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s, %s
                    )
                    RETURNING *
                """, (
                    evidencia_id,
                    titulo,
                    categoria,
                    area,
                    dados.get("entidade"),
                    dados.get(
                        "tipo_evidencia",
                        "documental"
                    ),
                    dados.get(
                        "status",
                        "vigente"
                    ),
                    dados.get("data_evidencia"),
                    resumo,
                    (
                        json.dumps(
                            dados_estruturados,
                            ensure_ascii=False,
                            default=str
                        )
                        if dados_estruturados is not None
                        else None
                    ),
                    dados.get("fonte"),
                    dados.get("fonte_tipo"),
                    dados.get(
                        "confiabilidade",
                        "documental"
                    ),
                    dados.get("substitui_id"),
                    dados.get("observacoes")
                ))

                evidencia = cur.fetchone()

        registrar_auditoria(
            categoria="evidencia_empresarial",
            acao="evidencia_registrada",
            ator_tipo="admin",
            ator_id="admin",
            origem="api_admin",
            entidade_tipo="evidencia_empresarial",
            entidade_id=evidencia_id,
            status="criado",
            dados_entrada={
                "titulo": titulo,
                "categoria": categoria,
                "area": area,
                "status":
                    dados.get(
                        "status",
                        "vigente"
                    )
            }
        )

        return jsonify({
            "success": True,
            "evidencia": evidencia
        }), 201

    finally:
        conn.close()



def detectar_comando_memoria_empresarial(texto):
    """
    Retorna True somente quando a direção dá uma ordem explícita
    para registrar uma informação empresarial.
    """

    texto = str(texto or "").strip()

    if not texto:
        return False

    normalizado = unicodedata.normalize(
        "NFKD",
        texto.lower()
    )

    normalizado = "".join(
        c for c in normalizado
        if not unicodedata.combining(c)
    )

    comandos = [
        r"\bregistre\b",
        r"\bregistrar\b",
        r"\banote\b",
        r"\bguarde\b",
        r"\bsalve\b",
        r"\badicione\b",
        r"\bacrescente\b",
        r"\binclua\b"
    ]

    return any(
        re.search(padrao, normalizado)
        for padrao in comandos
    )


def estruturar_memoria_empresarial(texto):
    """
    Usa a IA para transformar uma declaração da direção
    em registro estruturado, sem inventar informações.
    """

    if not openai_client:
        raise RuntimeError(
            "OpenAI indisponível."
        )

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "memoria_empresarial",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "registrar": {
                            "type": "boolean"
                        },
                        "titulo": {
                            "type": "string"
                        },
                        "categoria": {
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
                                "estrategia",
                                "juridico"
                            ]
                        },
                        "entidade": {
                            "type": "string"
                        },
                        "status": {
                            "type": "string"
                        },
                        "resumo": {
                            "type": "string"
                        },
                        "fato_principal": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "registrar",
                        "titulo",
                        "categoria",
                        "area",
                        "entidade",
                        "status",
                        "resumo",
                        "fato_principal"
                    ],
                    "additionalProperties": False
                }
            }
        },

        instructions=(
            "Você estrutura memória empresarial privada "
            "da Maranhão Cordial. "

            "Extraia SOMENTE fatos explicitamente declarados "
            "pela direção. Não complete informações ausentes. "

            "Não invente datas, valores, contratos, pagamentos, "
            "parcerias, aprovações ou documentos. "

            "Uma declaração da direção é uma fonte interna, "
            "não uma prova documental externa. "

            "Não transforme negociação em contrato. "
            "Não transforme pedido de marca em concessão. "
            "Não transforme intenção em fato realizado. "
            "Não transforme participação em evento em parceria. "

            "Se houver dúvida ou hipótese na declaração, "
            "preserve essa incerteza no status e no resumo."
        ),

        input=texto,

        reasoning={
            "effort": "low"
        },

        max_output_tokens=600
    )

    bruto = (
        resposta.output_text
        or ""
    ).strip()

    if not bruto:
        raise RuntimeError(
            "Não foi possível estruturar a memória."
        )

    return json.loads(bruto)


def registrar_memoria_natural_empresarial(texto):

    memoria = estruturar_memoria_empresarial(
        texto
    )

    if not memoria.get("registrar"):
        return None

    evidencia_id = str(
        uuid.uuid4()
    )

    dados_estruturados = {
        "fato_principal":
            memoria["fato_principal"],
        "origem_declaracao":
            "declaracao_direcao"
    }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO evidencias_empresariais (
                        id,
                        titulo,
                        categoria,
                        area,
                        entidade,
                        tipo_evidencia,
                        status,
                        resumo,
                        dados_estruturados,
                        fonte,
                        fonte_tipo,
                        confiabilidade,
                        observacoes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s
                    )
                    RETURNING *
                """, (
                    evidencia_id,
                    memoria["titulo"],
                    memoria["categoria"],
                    memoria["area"],
                    memoria["entidade"] or None,
                    "declaracao_direcao",
                    memoria["status"],
                    memoria["resumo"],
                    json.dumps(
                        dados_estruturados,
                        ensure_ascii=False
                    ),
                    "Direção da Maranhão Cordial",
                    "declaracao_interna",
                    "declarada",
                    (
                        "Criado por comando explícito da direção "
                        "na IA Empresarial. Não constitui, sozinho, "
                        "prova documental externa."
                    )
                ))

                evidencia = cur.fetchone()

        registrar_auditoria(
            categoria="memoria_empresarial",
            acao="memoria_natural_registrada",
            ator_tipo="admin",
            ator_id="direcao",
            origem="ia_empresarial",
            entidade_tipo="evidencia_empresarial",
            entidade_id=evidencia_id,
            status="criado",
            dados_entrada={
                "texto_original": texto
            },
            dados_saida={
                "evidencia_id": evidencia_id,
                "titulo": memoria["titulo"]
            }
        )

        return evidencia

    finally:
        conn.close()


def carregar_evidencias_para_ia(limite=150):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM evidencias_empresariais
                    WHERE status NOT IN (
                        'cancelada',
                        'descartada'
                    )
                    ORDER BY
                        data_evidencia DESC NULLS LAST,
                        atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                evidencias = cur.fetchall()

        linhas = []

        for ev in evidencias:

            linhas.append(
                (
                    f"- ID: {ev['id']} "
                    f"| {ev['titulo']} "
                    f"| Área: {ev['area']} "
                    f"| Categoria: {ev['categoria']} "
                    f"| Entidade: "
                    f"{ev['entidade'] or 'não informada'} "
                    f"| Tipo: {ev['tipo_evidencia']} "
                    f"| Status: {ev['status']} "
                    f"| Data: "
                    f"{ev['data_evidencia'] or 'não informada'} "
                    f"| Confiabilidade: "
                    f"{ev['confiabilidade']} "
                    f"| Fato: {ev['resumo']} "
                    f"| Dados estruturados: "
                    f"{json.dumps(ev['dados_estruturados'], ensure_ascii=False, default=str) if ev['dados_estruturados'] is not None else 'não informados'} "
                    f"| Fonte: "
                    f"{ev['fonte'] or 'não informada'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "EVIDÊNCIAS EMPRESARIAIS VERIFICADAS\n"
                "Estas evidências representam fatos documentais, "
                "interações ou registros empresariais. "
                "Diferencie pedido de concessão, negociação de contrato, "
                "cotação de preço e operação efetivamente concluída. "
                "Não transforme status pendente em concluído. "
                "Quando houver versões substituídas, priorize a evidência "
                "mais recente e vigente.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "evidencias": evidencias,
            "contexto": contexto
        }

    finally:
        conn.close()


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



# =====================================================
# CADASTRO EXTERNO DE FABRICAS
# =====================================================

@app.route(
    "/api/parceiros/fabricas/cadastro",
    methods=["POST"]
)
def parceiro_cadastrar_fabrica():
    """
    Permite que colaborador autorizado alimente
    a matriz industrial.

    SEGURANCA:
    - nunca homologa;
    - nunca valida;
    - nunca libera fábrica para cálculo da IA;
    - registra obrigatoriamente a origem dos dados.
    """

    chave = request.headers.get(
        "X-Cadastro-Key",
        ""
    )

    if (
        not FABRICAS_CADASTRO_KEY
        or chave != FABRICAS_CADASTRO_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    nome = str(
        dados.get("nome") or ""
    ).strip()

    estado = str(
        dados.get("estado") or ""
    ).strip().upper()

    responsavel_nome = str(
        dados.get(
            "responsavel_dados_nome"
        ) or ""
    ).strip()

    responsavel_empresa = str(
        dados.get(
            "responsavel_dados_empresa"
        ) or ""
    ).strip()

    responsavel_cargo = str(
        dados.get(
            "responsavel_dados_cargo"
        ) or ""
    ).strip()

    responsavel_email = str(
        dados.get(
            "responsavel_dados_email"
        ) or ""
    ).strip()

    responsavel_whatsapp = str(
        dados.get(
            "responsavel_dados_whatsapp"
        ) or ""
    ).strip()

    fonte_dados = str(
        dados.get("fonte_dados") or ""
    ).strip()

    erros = []

    if not nome:
        erros.append(
            "Nome da fábrica é obrigatório."
        )

    if len(estado) != 2:
        erros.append(
            "UF da fábrica deve ter 2 letras."
        )

    if not responsavel_nome:
        erros.append(
            "Responsável pelos dados é obrigatório."
        )

    if not responsavel_empresa:
        erros.append(
            "Empresa/organização do responsável é obrigatória."
        )

    if not responsavel_cargo:
        erros.append(
            "Cargo/função do responsável é obrigatório."
        )

    if not responsavel_email:
        erros.append(
            "E-mail do responsável é obrigatório."
        )

    if not responsavel_whatsapp:
        erros.append(
            "WhatsApp do responsável é obrigatório."
        )

    if not fonte_dados:
        erros.append(
            "Fonte dos dados é obrigatória."
        )

    if erros:
        return jsonify({
            "success": False,
            "errors": erros
        }), 400

    fabrica_id = str(uuid.uuid4())

    def json_lista(nome_campo):
        valor = dados.get(
            nome_campo,
            []
        )

        if not isinstance(valor, list):
            valor = []

        return json.dumps(
            valor,
            ensure_ascii=False
        )

    conn = get_db_connection()

    try:

        with conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                # ==========================================
                # PREVENCAO DE DUPLICIDADE
                # ==========================================
                #
                # Regra:
                # 1. Se houver CNPJ, ele é a identidade principal.
                # 2. Sem CNPJ, usa nome + UF.
                #
                # Isso também protege contra clique/reenvio
                # acidental do mesmo cadastro.

                cnpj_recebido = str(
                    dados.get("cnpj") or ""
                ).strip()

                cnpj_normalizado = re.sub(
                    r"\D",
                    "",
                    cnpj_recebido
                )

                fabrica_existente = None

                if cnpj_normalizado:

                    cur.execute("""
                        SELECT
                            id,
                            nome,
                            cnpj,
                            estado,
                            status_fluxo,
                            origem_cadastro,
                            criado_em

                        FROM fabricas_parceiras

                        WHERE regexp_replace(
                            COALESCE(cnpj, ''),
                            '[^0-9]',
                            '',
                            'g'
                        ) = %s

                        ORDER BY criado_em DESC
                        LIMIT 1
                    """, (
                        cnpj_normalizado,
                    ))

                    fabrica_existente = (
                        cur.fetchone()
                    )

                else:

                    cur.execute("""
                        SELECT
                            id,
                            nome,
                            cnpj,
                            estado,
                            status_fluxo,
                            origem_cadastro,
                            criado_em

                        FROM fabricas_parceiras

                        WHERE LOWER(TRIM(nome))
                              = LOWER(TRIM(%s))

                          AND UPPER(TRIM(
                              COALESCE(estado, '')
                          )) = UPPER(TRIM(%s))

                        ORDER BY criado_em DESC
                        LIMIT 1
                    """, (
                        nome,
                        estado
                    ))

                    fabrica_existente = (
                        cur.fetchone()
                    )

                if fabrica_existente:

                    return jsonify({
                        "success": False,
                        "error":
                            "Esta fábrica já possui cadastro no sistema.",
                        "duplicado": True,
                        "fabrica_existente": {
                            "id":
                                fabrica_existente[
                                    "id"
                                ],
                            "nome":
                                fabrica_existente[
                                    "nome"
                                ],
                            "estado":
                                fabrica_existente[
                                    "estado"
                                ],
                            "status":
                                fabrica_existente[
                                    "status_fluxo"
                                ],
                            "origem":
                                fabrica_existente[
                                    "origem_cadastro"
                                ]
                        }
                    }), 409

                cur.execute("""
                    INSERT INTO fabricas_parceiras (

                        id,

                        nome,
                        razao_social,
                        cnpj,

                        cidade,
                        estado,
                        regiao,
                        cep,
                        endereco_operacional,

                        contato_nome,
                        contato_email,
                        contato_whatsapp,
                        site,

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

                        mapa_status,
                        ncm_informado,

                        observacoes,
                        fonte_dados,

                        ufs_atendidas,
                        segmentos_atendidos,
                        modalidades_logisticas,

                        responsavel_dados_nome,
                        responsavel_dados_email,
                        responsavel_dados_whatsapp,
                        responsavel_dados_empresa,
                        responsavel_dados_cargo,

                        origem_cadastro,
                        status_fluxo,
                        status_comercial,
                        status_regulatorio,

                        disponivel_calculo_ia,

                        cadastro_externo_em

                    )

                    VALUES (

                        %s,

                        %s, %s, %s,

                        %s, %s, %s, %s, %s,

                        %s, %s, %s, %s,

                        %s, %s,

                        %s, %s,

                        %s, %s,

                        %s,

                        %s, %s, %s, %s,
                        %s, %s, %s,

                        %s, %s,

                        %s, %s,

                        %s::jsonb,
                        %s::jsonb,
                        %s::jsonb,

                        %s, %s, %s, %s, %s,

                        'externo',
                        'pendente',
                        'prospectada',
                        'nao_verificado',

                        FALSE,

                        NOW()
                    )

                    RETURNING *
                """, (

                    fabrica_id,

                    nome,
                    dados.get("razao_social"),
                    dados.get("cnpj"),

                    dados.get("cidade"),
                    estado,
                    dados.get("regiao"),
                    dados.get("cep"),
                    dados.get(
                        "endereco_operacional"
                    ),

                    dados.get("contato_nome"),
                    dados.get("contato_email"),
                    dados.get(
                        "contato_whatsapp"
                    ),
                    dados.get("site"),

                    dados.get(
                        "lote_minimo_unidades"
                    ),
                    dados.get(
                        "lote_minimo_litros"
                    ),

                    dados.get(
                        "capacidade_maxima_unidades"
                    ),
                    dados.get(
                        "capacidade_maxima_litros"
                    ),

                    dados.get(
                        "custo_unitario_centavos"
                    ),
                    dados.get(
                        "custo_litro_centavos"
                    ),

                    dados.get(
                        "prazo_producao_dias"
                    ),

                    dados.get("embalagem_vidro")
                        if "embalagem_vidro" in dados
                        else None,

                    dados.get("embalagem_pet")
                        if "embalagem_pet" in dados
                        else None,

                    dados.get("envase_200ml")
                        if "envase_200ml" in dados
                        else None,

                    dados.get("rotulagem")
                        if "rotulagem" in dados
                        else None,

                    dados.get(
                        "responsabilidade_tecnica"
                    )
                        if "responsabilidade_tecnica" in dados
                        else None,

                    dados.get(
                        "analises_laboratoriais"
                    )
                        if "analises_laboratoriais" in dados
                        else None,

                    dados.get("pode_copack")
                        if "pode_copack" in dados
                        else None,

                    dados.get("mapa_status"),
                    dados.get("ncm_informado"),

                    dados.get("observacoes"),
                    fonte_dados,

                    json_lista("ufs_atendidas"),
                    json_lista(
                        "segmentos_atendidos"
                    ),
                    json_lista(
                        "modalidades_logisticas"
                    ),

                    responsavel_nome,
                    responsavel_email,
                    responsavel_whatsapp,
                    responsavel_empresa,
                    responsavel_cargo

                ))

                fabrica = cur.fetchone()

        registrar_auditoria(
            categoria="industrial",
            acao="fabrica_cadastrada_externamente",
            ator_tipo="colaborador_externo",
            ator_id=responsavel_nome,
            origem="cadastro_externo_fabricas",
            entidade_tipo="fabrica_parceira",
            entidade_id=fabrica_id,
            status="pendente",
            dados_entrada={
                "nome": nome,
                "estado": estado,
                "responsavel_dados":
                    responsavel_nome,
                "responsavel_empresa":
                    responsavel_empresa,
                "fonte_dados":
                    fonte_dados
            }
        )

        return jsonify({
            "success": True,
            "mensagem":
                "Fábrica cadastrada e enviada "
                "para validação da direção.",
            "fabrica_id": fabrica_id,
            "status": "pendente",
            "disponivel_calculo_ia": False,
            "fabrica": fabrica
        }), 201

    except Exception as erro:

        print(
            "ERRO CADASTRO EXTERNO FABRICA:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Erro ao cadastrar fábrica."
        }), 500

    finally:
        conn.close()



# =====================================================
# ADMIN — WORKFLOW / HOMOLOGACAO DE FABRICAS
# =====================================================

@app.route(
    "/api/admin/fabricas/<fabrica_id>/workflow",
    methods=["PATCH"]
)
def admin_workflow_fabrica(fabrica_id):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    novo_status = str(
        dados.get("status") or ""
    ).strip().lower()

    responsavel = str(
        dados.get("responsavel") or ""
    ).strip()

    motivo = str(
        dados.get("motivo") or ""
    ).strip()

    status_validos = {
        "pendente",
        "em_validacao",
        "qualificada",
        "homologada",
        "suspensa",
        "rejeitada"
    }

    if novo_status not in status_validos:
        return jsonify({
            "success": False,
            "error": "Status de workflow inválido."
        }), 400

    if not responsavel:
        return jsonify({
            "success": False,
            "error":
                "Responsável pela alteração é obrigatório."
        }), 400

    # ----------------------------------------------
    # FLUXO PERMITIDO
    # ----------------------------------------------

    transicoes_permitidas = {
        "pendente": {
            "em_validacao",
            "rejeitada"
        },

        "em_validacao": {
            "pendente",
            "qualificada",
            "rejeitada"
        },

        "qualificada": {
            "em_validacao",
            "homologada",
            "rejeitada"
        },

        "homologada": {
            "suspensa"
        },

        "suspensa": {
            "em_validacao",
            "homologada",
            "rejeitada"
        },

        "rejeitada": {
            "pendente",
            "em_validacao"
        }
    }

    conn = get_db_connection()

    try:

        with conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                # Bloqueia a linha durante a alteração
                # para evitar duas aprovações simultâneas.
                cur.execute("""
                    SELECT *
                    FROM fabricas_parceiras
                    WHERE id = %s
                    FOR UPDATE
                """, (
                    fabrica_id,
                ))

                fabrica_atual = cur.fetchone()

                if not fabrica_atual:
                    return jsonify({
                        "success": False,
                        "error":
                            "Fábrica não encontrada."
                    }), 404

                status_atual = (
                    fabrica_atual.get(
                        "status_fluxo"
                    )
                    or "pendente"
                )

                if novo_status != status_atual:

                    permitidos = (
                        transicoes_permitidas.get(
                            status_atual,
                            set()
                        )
                    )

                    if novo_status not in permitidos:
                        return jsonify({
                            "success": False,
                            "error":
                                "Transição de status não permitida.",
                            "status_atual":
                                status_atual,
                            "status_solicitado":
                                novo_status,
                            "transicoes_permitidas":
                                sorted(
                                    list(permitidos)
                                )
                        }), 409

                # ------------------------------------------
                # COMPATIBILIDADE COM STATUS COMERCIAL
                # EXISTENTE
                # ------------------------------------------

                mapa_status_comercial = {
                    "pendente":
                        "prospectada",

                    "em_validacao":
                        "prospectada",

                    "qualificada":
                        "qualificada",

                    "homologada":
                        "homologada",

                    "suspensa":
                        "inativa",

                    "rejeitada":
                        "descartada"
                }

                status_comercial = (
                    mapa_status_comercial[
                        novo_status
                    ]
                )

                disponivel_ia = (
                    novo_status
                    == "homologada"
                )

                cur.execute("""
                    UPDATE fabricas_parceiras

                    SET
                        status_fluxo = %s,

                        status_comercial = %s,

                        disponivel_calculo_ia = %s,

                        motivo_status = %s,

                        validado_por =
                            CASE
                                WHEN %s = 'em_validacao'
                                THEN %s
                                ELSE validado_por
                            END,

                        validado_em =
                            CASE
                                WHEN %s = 'em_validacao'
                                THEN NOW()
                                ELSE validado_em
                            END,

                        qualificado_por =
                            CASE
                                WHEN %s = 'qualificada'
                                THEN %s
                                ELSE qualificado_por
                            END,

                        qualificado_em =
                            CASE
                                WHEN %s = 'qualificada'
                                THEN NOW()
                                ELSE qualificado_em
                            END,

                        homologado_por =
                            CASE
                                WHEN %s = 'homologada'
                                THEN %s
                                ELSE homologado_por
                            END,

                        homologado_em =
                            CASE
                                WHEN %s = 'homologada'
                                THEN NOW()
                                ELSE homologado_em
                            END,

                        atualizado_em = NOW()

                    WHERE id = %s

                    RETURNING *
                """, (

                    novo_status,
                    status_comercial,
                    disponivel_ia,
                    motivo or None,

                    novo_status,
                    responsavel,

                    novo_status,

                    novo_status,
                    responsavel,

                    novo_status,

                    novo_status,
                    responsavel,

                    novo_status,

                    fabrica_id
                ))

                fabrica = cur.fetchone()

        registrar_auditoria(
            categoria="industrial",
            acao="workflow_fabrica_atualizado",
            ator_tipo="admin",
            ator_id=responsavel,
            origem="painel_admin",
            entidade_tipo="fabrica_parceira",
            entidade_id=fabrica_id,
            status=novo_status,
            dados_entrada={
                "status_anterior":
                    status_atual,

                "status_novo":
                    novo_status,

                "motivo":
                    motivo or None,

                "disponivel_calculo_ia":
                    disponivel_ia
            }
        )

        return jsonify({
            "success": True,

            "mensagem":
                "Workflow da fábrica atualizado.",

            "status_anterior":
                status_atual,

            "status_atual":
                novo_status,

            "disponivel_calculo_ia":
                disponivel_ia,

            "fabrica":
                fabrica
        }), 200

    except Exception as erro:

        print(
            "ERRO WORKFLOW FABRICA:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Erro ao atualizar workflow da fábrica."
        }), 500

    finally:
        conn.close()



# =====================================================
# REDE PROFISSIONAL — CADASTRO EXTERNO
# =====================================================

@app.route(
    "/api/parceiros/profissionais/cadastro",
    methods=["POST"]
)
def parceiro_cadastrar_profissional():

    chave = request.headers.get(
        "X-Cadastro-Key"
    )

    if (
        not PROFISSIONAIS_CADASTRO_KEY
        or chave != PROFISSIONAIS_CADASTRO_KEY
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
    ).strip()

    estado = str(
        dados.get("estado", "")
    ).strip().upper()

    if not nome:
        return jsonify({
            "success": False,
            "error":
                "Nome do profissional obrigatório."
        }), 400

    if estado and len(estado) != 2:
        return jsonify({
            "success": False,
            "error": "UF inválida."
        }), 400

    responsavel_nome = str(
        dados.get(
            "responsavel_dados_nome",
            ""
        )
    ).strip()

    responsavel_empresa = str(
        dados.get(
            "responsavel_dados_empresa",
            ""
        )
    ).strip()

    responsavel_cargo = str(
        dados.get(
            "responsavel_dados_cargo",
            ""
        )
    ).strip()

    responsavel_email = str(
        dados.get(
            "responsavel_dados_email",
            ""
        )
    ).strip()

    responsavel_whatsapp = str(
        dados.get(
            "responsavel_dados_whatsapp",
            ""
        )
    ).strip()

    fonte_dados = str(
        dados.get(
            "fonte_dados",
            ""
        )
    ).strip()

    obrigatorios = {
        "responsável pelos dados":
            responsavel_nome,
        "empresa/organização":
            responsavel_empresa,
        "cargo/função":
            responsavel_cargo,
        "e-mail do responsável":
            responsavel_email,
        "WhatsApp do responsável":
            responsavel_whatsapp,
        "fonte dos dados":
            fonte_dados
    }

    faltantes = [
        campo
        for campo, valor
        in obrigatorios.items()
        if not valor
    ]

    if faltantes:
        return jsonify({
            "success": False,
            "error":
                "Campos obrigatórios ausentes: "
                + ", ".join(faltantes)
        }), 400

    profissional_id = str(
        uuid.uuid4()
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                instagram = str(
                    dados.get("instagram") or ""
                ).strip().lower()

                existente = None

                # -----------------------------------------
                # PREVENÇÃO DE DUPLICIDADE
                # -----------------------------------------
                # Com Instagram: usa Instagram.
                # Sem Instagram: nome + UF + estabelecimento.

                if instagram:

                    cur.execute("""
                        SELECT
                            id,
                            nome,
                            instagram,
                            estado,
                            status_fluxo
                        FROM profissionais_rede
                        WHERE LOWER(
                            TRIM(
                                COALESCE(
                                    instagram,
                                    ''
                                )
                            )
                        ) = LOWER(TRIM(%s))
                        ORDER BY criado_em DESC
                        LIMIT 1
                    """, (
                        instagram,
                    ))

                    existente = cur.fetchone()

                else:

                    estabelecimento = str(
                        dados.get(
                            "estabelecimento_nome"
                        ) or ""
                    ).strip()

                    cur.execute("""
                        SELECT
                            id,
                            nome,
                            instagram,
                            estado,
                            status_fluxo
                        FROM profissionais_rede
                        WHERE LOWER(TRIM(nome))
                              = LOWER(TRIM(%s))
                          AND UPPER(
                              TRIM(
                                  COALESCE(
                                      estado,
                                      ''
                                  )
                              )
                          ) = UPPER(TRIM(%s))
                          AND LOWER(
                              TRIM(
                                  COALESCE(
                                      estabelecimento_nome,
                                      ''
                                  )
                              )
                          ) = LOWER(TRIM(%s))
                        ORDER BY criado_em DESC
                        LIMIT 1
                    """, (
                        nome,
                        estado,
                        estabelecimento
                    ))

                    existente = cur.fetchone()

                if existente:
                    return jsonify({
                        "success": False,
                        "duplicado": True,
                        "error":
                            "Este profissional já possui cadastro.",
                        "profissional_existente":
                            existente
                    }), 409

                cur.execute("""
                    INSERT INTO profissionais_rede (
                        id,
                        nome,
                        nome_profissional,
                        cidade,
                        estado,
                        regiao,
                        estabelecimento_nome,
                        estabelecimento_tipo,
                        cargo_funcao,
                        instagram,
                        whatsapp,
                        email,
                        especialidade,
                        experiencia_anos,
                        eventos,
                        areas_atuacao,
                        origem_cadastro,
                        status_fluxo,
                        status_relacionamento,
                        recebeu_amostra,
                        degustou,
                        feedback_recebido,
                        oportunidade_gerada,
                        responsavel_dados_nome,
                        responsavel_dados_empresa,
                        responsavel_dados_cargo,
                        responsavel_dados_email,
                        responsavel_dados_whatsapp,
                        fonte_dados,
                        observacoes,
                        disponivel_ia
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s,
                        'externo',
                        'mapeado',
                        'sem_contato',
                        FALSE,
                        FALSE,
                        FALSE,
                        FALSE,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        FALSE
                    )
                    RETURNING *
                """, (
                    profissional_id,
                    nome,
                    dados.get(
                        "nome_profissional"
                    ),
                    dados.get("cidade"),
                    estado or None,
                    dados.get("regiao"),
                    dados.get(
                        "estabelecimento_nome"
                    ),
                    dados.get(
                        "estabelecimento_tipo"
                    ),
                    dados.get(
                        "cargo_funcao"
                    ),
                    dados.get("instagram"),
                    dados.get("whatsapp"),
                    dados.get("email"),
                    dados.get(
                        "especialidade"
                    ),
                    dados.get(
                        "experiencia_anos"
                    ),
                    dados.get("eventos") or [],
                    dados.get(
                        "areas_atuacao"
                    ) or [],
                    responsavel_nome,
                    responsavel_empresa,
                    responsavel_cargo,
                    responsavel_email,
                    responsavel_whatsapp,
                    fonte_dados,
                    dados.get("observacoes")
                ))

                profissional = cur.fetchone()

        return jsonify({
            "success": True,
            "mensagem":
                "Profissional cadastrado e enviado "
                "para validação.",
            "profissional_id":
                profissional_id,
            "status": "mapeado",
            "disponivel_ia": False,
            "profissional":
                profissional
        }), 201

    except Exception as erro:

        print(
            "ERRO CADASTRO EXTERNO PROFISSIONAL:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Erro ao cadastrar profissional."
        }), 500

    finally:
        conn.close()



# =====================================================
# REDE PROFISSIONAL — ADMIN / LISTAGEM
# =====================================================

@app.route(
    "/api/admin/profissionais",
    methods=["GET"]
)
def admin_listar_profissionais():

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
                    FROM profissionais_rede

                    ORDER BY
                        CASE status_fluxo
                            WHEN 'ativo' THEN 1
                            WHEN 'relacionamento' THEN 2
                            WHEN 'qualificado' THEN 3
                            WHEN 'em_validacao' THEN 4
                            WHEN 'mapeado' THEN 5
                            WHEN 'inativo' THEN 6
                            WHEN 'rejeitado' THEN 7
                            ELSE 8
                        END,
                        atualizado_em DESC
                """)

                profissionais = cur.fetchall()

        return jsonify({
            "success": True,
            "total": len(profissionais),
            "profissionais": profissionais
        }), 200

    except Exception as erro:

        print(
            "ERRO LISTAGEM REDE PROFISSIONAL:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Erro ao listar profissionais."
        }), 500

    finally:
        conn.close()


# =====================================================
# REDE PROFISSIONAL — WORKFLOW
# =====================================================

@app.route(
    "/api/admin/profissionais/<profissional_id>/workflow",
    methods=["PATCH"]
)
def admin_workflow_profissional(
    profissional_id
):

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    novo_status = str(
        dados.get("status", "")
    ).strip().lower()

    responsavel = str(
        dados.get("responsavel", "")
    ).strip()

    motivo = str(
        dados.get("motivo", "")
    ).strip()

    if not novo_status:
        return jsonify({
            "success": False,
            "error": "Novo status obrigatório."
        }), 400

    if not responsavel:
        return jsonify({
            "success": False,
            "error": "Responsável obrigatório."
        }), 400

    transicoes_permitidas = {

        "mapeado": {
            "em_validacao",
            "rejeitado"
        },

        "em_validacao": {
            "mapeado",
            "qualificado",
            "rejeitado"
        },

        "qualificado": {
            "em_validacao",
            "relacionamento",
            "rejeitado"
        },

        "relacionamento": {
            "qualificado",
            "ativo",
            "inativo"
        },

        "ativo": {
            "relacionamento",
            "inativo"
        },

        "inativo": {
            "relacionamento",
            "ativo"
        },

        "rejeitado": {
            "mapeado",
            "em_validacao"
        }
    }

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM profissionais_rede
                    WHERE id = %s
                    FOR UPDATE
                """, (
                    profissional_id,
                ))

                profissional = cur.fetchone()

                if not profissional:
                    return jsonify({
                        "success": False,
                        "error":
                            "Profissional não encontrado."
                    }), 404

                status_atual = (
                    profissional.get(
                        "status_fluxo"
                    )
                    or "mapeado"
                )

                permitidas = (
                    transicoes_permitidas.get(
                        status_atual,
                        set()
                    )
                )

                if novo_status not in permitidas:
                    return jsonify({
                        "success": False,
                        "error":
                            "Transição de status não permitida.",
                        "status_atual":
                            status_atual,
                        "transicoes_permitidas":
                            sorted(permitidas)
                    }), 400

                # Somente profissionais já qualificados
                # podem alimentar consultas estratégicas.
                disponivel_ia = (
                    novo_status in {
                        "qualificado",
                        "relacionamento",
                        "ativo"
                    }
                )

                cur.execute("""
                    UPDATE profissionais_rede

                    SET
                        status_fluxo = %s,
                        disponivel_ia = %s,

                        validado_por =
                            CASE
                                WHEN %s = 'em_validacao'
                                THEN %s
                                ELSE validado_por
                            END,

                        validado_em =
                            CASE
                                WHEN %s = 'em_validacao'
                                THEN NOW()
                                ELSE validado_em
                            END,

                        qualificado_por =
                            CASE
                                WHEN %s = 'qualificado'
                                THEN %s
                                ELSE qualificado_por
                            END,

                        qualificado_em =
                            CASE
                                WHEN %s = 'qualificado'
                                THEN NOW()
                                ELSE qualificado_em
                            END,

                        ativo_por =
                            CASE
                                WHEN %s = 'ativo'
                                THEN %s
                                ELSE ativo_por
                            END,

                        ativo_em =
                            CASE
                                WHEN %s = 'ativo'
                                THEN NOW()
                                ELSE ativo_em
                            END,

                        observacoes =
                            CASE
                                WHEN %s <> ''
                                THEN CONCAT(
                                    COALESCE(
                                        observacoes,
                                        ''
                                    ),
                                    CASE
                                        WHEN COALESCE(
                                            observacoes,
                                            ''
                                        ) <> ''
                                        THEN E'\\n'
                                        ELSE ''
                                    END,
                                    '[Workflow] ',
                                    %s
                                )
                                ELSE observacoes
                            END,

                        atualizado_em = NOW()

                    WHERE id = %s

                    RETURNING *
                """, (
                    novo_status,
                    disponivel_ia,

                    novo_status,
                    responsavel,

                    novo_status,

                    novo_status,
                    responsavel,

                    novo_status,

                    novo_status,
                    responsavel,

                    novo_status,

                    motivo,
                    motivo,

                    profissional_id
                ))

                atualizado = cur.fetchone()

        return jsonify({
            "success": True,
            "status_anterior":
                status_atual,
            "status_atual":
                novo_status,
            "disponivel_ia":
                disponivel_ia,
            "profissional":
                atualizado
        }), 200

    except Exception as erro:

        print(
            "ERRO WORKFLOW REDE PROFISSIONAL:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error":
                "Erro ao atualizar workflow profissional."
        }), 500

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
                fabrica.get('custo_unitario_centavos') / 100
                if fabrica.get('custo_unitario_centavos') is not None
                else None
            )

            custo_litro = (
                fabrica.get('custo_litro_centavos') / 100
                if fabrica.get('custo_litro_centavos') is not None
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
                    f"- {fabrica.get('nome')} "
                    f"| Local: "
                    f"{fabrica.get('cidade') or 'não informada'}/"
                    f"{fabrica.get('estado') or 'não informado'} "
                    f"| Região: "
                    f"{fabrica.get('regiao') or 'não informada'} "
                    f"| Comercial: "
                    f"{fabrica.get('status_comercial')} "
                    f"| Regulatório: "
                    f"{fabrica.get('status_regulatorio')} "
                    f"| MAPA: "
                    f"{fabrica.get('mapa_status') or 'não informado'} "
                    f"| Lote mínimo unidades: "
                    f"{fabrica.get('lote_minimo_unidades') or 'não informado'} "
                    f"| Lote mínimo litros: "
                    f"{fabrica.get('lote_minimo_litros') or 'não informado'} "
                    f"| Capacidade máxima unidades: "
                    f"{fabrica.get('capacidade_maxima_unidades') or 'não informada'} "
                    f"| Capacidade máxima litros: "
                    f"{fabrica.get('capacidade_maxima_litros') or 'não informada'} "
                    f"| Custo unitário: "
                    f"{texto_custo_unitario} "
                    f"| Custo por litro: "
                    f"{texto_custo_litro} "
                    f"| Prazo produção: "
                    f"{fabrica.get('prazo_producao_dias') or 'não informado'} dias "
                    f"| Copack: "
                    f"{texto_booleano_verificado(fabrica.get('pode_copack'))} "
                    f"| Envase 200ml: "
                    f"{texto_booleano_verificado(fabrica.get('envase_200ml'))} "
                    f"| Vidro: "
                    f"{texto_booleano_verificado(fabrica.get('embalagem_vidro'))} "
                    f"| Rotulagem: "
                    f"{texto_booleano_verificado(fabrica.get('rotulagem'))} "
                    f"| RT: "
                    f"{texto_booleano_verificado(fabrica.get('responsabilidade_tecnica'))} "
                    f"| Análises: "
                    f"{texto_booleano_verificado(fabrica.get('analises_laboratoriais'))} "
                    f"| NCM informado: "
                    f"{fabrica.get('ncm_informado') or 'não informado'} "

                    f"| Workflow: "
                    f"{fabrica.get('status_fluxo') or 'pendente'} "

                    f"| Origem cadastro: "
                    f"{fabrica.get('origem_cadastro') or 'não informada'} "

                    f"| Disponível para cálculo IA: "
                    f"{'SIM' if fabrica.get('disponivel_calculo_ia') else 'NÃO'} "

                    f"| Responsável original pelos dados: "
                    f"{fabrica.get('responsavel_dados_nome') or 'não informado'} "

                    f"| Empresa do responsável: "
                    f"{fabrica.get('responsavel_dados_empresa') or 'não informada'} "

                    f"| Cargo do responsável: "
                    f"{fabrica.get('responsavel_dados_cargo') or 'não informado'} "

                    f"| Validado por: "
                    f"{fabrica.get('validado_por') or 'não validado'} "

                    f"| Qualificado por: "
                    f"{fabrica.get('qualificado_por') or 'não qualificado'} "

                    f"| Homologado por: "
                    f"{fabrica.get('homologado_por') or 'não homologado'} "

                    f"| Fonte: "
                    f"{fabrica.get('fonte_dados') or 'não informada'} "

                    f"| Verificado por legado: "
                    f"{fabrica.get('verificado_por') or 'não verificado'} "

                    f"| Observações: "
                    f"{fabrica.get('observacoes') or 'sem observações'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "MATRIZ INDUSTRIAL / FÁBRICAS PARCEIRAS\n"

                "REGRAS OBRIGATÓRIAS DE GOVERNANÇA INDUSTRIAL:\n"

                "- Cadastro com status_fluxo 'pendente' representa apenas "
                "informação recebida. Pode ser citado como prospecção, "
                "mas NÃO como fábrica validada.\n"

                "- Status 'em_validacao' significa que a direção está "
                "checando as informações. Ainda NÃO use a fábrica para "
                "cálculo final de custo, margem ou decisão operacional.\n"

                "- Status 'qualificada' significa que a fábrica passou "
                "por qualificação empresarial/técnica preliminar, mas "
                "ainda NÃO equivale a homologação.\n"

                "- SOMENTE fábrica com status_fluxo='homologada' E "
                "disponivel_calculo_ia=TRUE pode ser usada como fábrica "
                "aprovada em cálculo definitivo de custo industrial, "
                "margem, capacidade, logística ou recomendação operacional.\n"

                "- Fábrica suspensa ou rejeitada NÃO pode ser utilizada "
                "em recomendação operacional.\n"

                "- Nunca transforme informação fornecida por terceiro "
                "em informação validada pela direção.\n"

                "- Quando houver dúvida sobre a confiabilidade de um dado, "
                "informe quem foi o responsável original pelos dados, "
                "a fonte e o estágio do workflow.\n"

                "- Diferencie sempre: responsável pelos dados, validador, "
                "qualificador e homologador.\n"

                "- O status regulatório continua sendo uma trava adicional: "
                "não trate fábrica com status regulatório 'pendente', "
                "'nao_verificado' ou 'incompativel' como liberada para "
                "produção comercial, mesmo que outros dados sejam favoráveis.\n"

                "Use os demais dados para avaliar localização, lote mínimo, "
                "capacidade, custos, prazo, processo e situação regulatória.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "fabricas": fabricas,
            "contexto": contexto
        }

    finally:
        conn.close()




# =====================================================
# REDE PROFISSIONAL — CONTEXTO PARA IA EMPRESARIAL
# =====================================================

def carregar_profissionais_para_ia(limite=150):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM profissionais_rede
                    ORDER BY
                        CASE status_fluxo
                            WHEN 'ativo' THEN 1
                            WHEN 'relacionamento' THEN 2
                            WHEN 'qualificado' THEN 3
                            WHEN 'em_validacao' THEN 4
                            WHEN 'mapeado' THEN 5
                            WHEN 'inativo' THEN 6
                            WHEN 'rejeitado' THEN 7
                            ELSE 8
                        END,
                        atualizado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                profissionais = cur.fetchall()

        linhas = []

        for profissional in profissionais:

            eventos = profissional.get("eventos") or []
            areas = profissional.get("areas_atuacao") or []

            interessado = profissional.get("interessado")

            if interessado is True:
                texto_interessado = "sim"
            elif interessado is False:
                texto_interessado = "não"
            else:
                texto_interessado = "não verificado"

            linhas.append(
                (
                    f"- {profissional['nome']} "

                    f"| Cidade: "
                    f"{profissional.get('cidade') or 'não informada'} "

                    f"| UF: "
                    f"{profissional.get('estado') or 'não informada'} "

                    f"| Região: "
                    f"{profissional.get('regiao') or 'não informada'} "

                    f"| Estabelecimento: "
                    f"{profissional.get('estabelecimento_nome') or 'não informado'} "

                    f"| Tipo estabelecimento: "
                    f"{profissional.get('estabelecimento_tipo') or 'não informado'} "

                    f"| Função: "
                    f"{profissional.get('cargo_funcao') or 'não informada'} "

                    f"| Instagram: "
                    f"{profissional.get('instagram') or 'não informado'} "

                    f"| WhatsApp: "
                    f"{profissional.get('whatsapp') or 'não informado'} "

                    f"| Especialidade: "
                    f"{profissional.get('especialidade') or 'não informada'} "

                    f"| Eventos: "
                    f"{', '.join(eventos) if eventos else 'não informados'} "

                    f"| Áreas de atuação: "
                    f"{', '.join(areas) if areas else 'não informadas'} "

                    f"| Workflow: "
                    f"{profissional.get('status_fluxo') or 'não informado'} "

                    f"| Relacionamento: "
                    f"{profissional.get('status_relacionamento') or 'não informado'} "

                    f"| Recebeu amostra: "
                    f"{'sim' if profissional.get('recebeu_amostra') else 'não'} "

                    f"| Degustou: "
                    f"{'sim' if profissional.get('degustou') else 'não'} "

                    f"| Feedback: "
                    f"{'sim' if profissional.get('feedback_recebido') else 'não'} "

                    f"| Interessado: "
                    f"{texto_interessado} "

                    f"| Oportunidade gerada: "
                    f"{'sim' if profissional.get('oportunidade_gerada') else 'não'} "

                    f"| Relevância: "
                    f"{profissional.get('relevancia') or 'não classificada'} "

                    f"| Disponível IA: "
                    f"{'sim' if profissional.get('disponivel_ia') else 'não'} "

                    f"| Responsável pelos dados: "
                    f"{profissional.get('responsavel_dados_nome') or 'não informado'} "

                    f"| Empresa responsável: "
                    f"{profissional.get('responsavel_dados_empresa') or 'não informada'} "

                    f"| Fonte: "
                    f"{profissional.get('fonte_dados') or 'não informada'} "

                    f"| Validado por: "
                    f"{profissional.get('validado_por') or 'não validado'} "

                    f"| Qualificado por: "
                    f"{profissional.get('qualificado_por') or 'não qualificado'} "

                    f"| Ativado por: "
                    f"{profissional.get('ativo_por') or 'não ativo'} "

                    f"| Observações: "
                    f"{profissional.get('observacoes') or 'sem observações'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "REDE PROFISSIONAL — BARTENDERS E MIXOLOGISTAS\n"

                "REGRAS DE GOVERNANÇA DA REDE PROFISSIONAL:\n"

                "- 'mapeado' é apenas um contato identificado; "
                "não equivale a profissional validado.\n"

                "- 'em_validacao' está em conferência e não deve "
                "ser tratado como recomendação definitiva.\n"

                "- 'qualificado' representa profissional já "
                "validado como relevante para a rede.\n"

                "- 'relacionamento' representa vínculo ativo "
                "em desenvolvimento com a Maranhão Cordial.\n"

                "- 'ativo' representa integrante atual da rede "
                "e pode ser priorizado quando pertinente.\n"

                "- 'inativo' pode ser considerado apenas como "
                "histórico, não como prioridade atual.\n"

                "- 'rejeitado' não deve ser recomendado.\n"

                "- Nunca transforme informação fornecida por "
                "terceiro em informação validada pela direção.\n"

                "- Antes de recomendar envio de produto, confira "
                "se recebeu_amostra já é verdadeiro.\n"

                "- Não invente influência, reputação, alcance ou "
                "poder comercial não registrados no sistema.\n"

                "- Diferencie identificação, qualificação, "
                "relacionamento e participação ativa.\n"

                "- Quando relevante, informe a fonte e o "
                "responsável original pelos dados.\n"

                + "\n".join(linhas)
                + "\n"
            )

        return {
            "profissionais": profissionais,
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
                    f"- ID: {acao['id']} "
                    f"| [{acao['status']}] "
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




def analisar_contexto_empresarial_para_insights():
    """
    Analisa o contexto empresarial e produz possíveis insights.

    Insight é uma inferência analítica, não um fato documental.

    Esta função não grava no banco, não cria ações,
    não altera objetivos e não executa operações empresariais.
    """

    evidencias_ia = carregar_evidencias_para_ia()
    decisoes_ia = carregar_decisoes_para_ia()
    acoes_ia = carregar_acoes_para_ia()
    insights_atuais = carregar_insights_para_ia()
    objetivos_contexto = carregar_objetivos_estrategicos_para_ia()

    contexto = (
        (evidencias_ia.get("contexto") or "")
        + (decisoes_ia.get("contexto") or "")
        + (acoes_ia.get("contexto") or "")
        + (insights_atuais.get("contexto") or "")
        + (objetivos_contexto or "")
    )

    if not contexto.strip():
        return {
            "resposta": "Contexto empresarial insuficiente.",
            "insights": []
        }

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "geracao_insights_empresariais",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "resposta": {
                            "type": "string"
                        },
                        "insights": {
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
                                    "tipo_insight": {
                                        "type": "string",
                                        "enum": [
                                            "analise",
                                            "oportunidade",
                                            "risco",
                                            "padrao",
                                            "gargalo",
                                            "alerta"
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
                                    "confianca": {
                                        "type": "string",
                                        "enum": [
                                            "baixa",
                                            "media",
                                            "alta"
                                        ]
                                    },
                                    "justificativa": {
                                        "type": "string"
                                    },
                                    "evidencias_origem": {
                                        "type": "array",
                                        "items": {
                                            "type": "string"
                                        }
                                    },
                                    "acoes_origem": {
                                        "type": "array",
                                        "items": {
                                            "type": "string"
                                        }
                                    },
                                    "objetivo_id": {
                                        "type": "string"
                                    },
                                    "decisao_id": {
                                        "type": "string"
                                    }
                                },
                                "required": [
                                    "titulo",
                                    "descricao",
                                    "area",
                                    "tipo_insight",
                                    "prioridade",
                                    "confianca",
                                    "justificativa",
                                    "evidencias_origem",
                                    "acoes_origem",
                                    "objetivo_id",
                                    "decisao_id"
                                ],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": [
                        "resposta",
                        "insights"
                    ],
                    "additionalProperties": False
                }
            }
        },

        instructions=(
            "Você é a camada analítica de conhecimento "
            "da inteligência empresarial privada da Maranhão Cordial. "

            "Identifique conclusões úteis pelo cruzamento de "
            "evidências, decisões, ações, objetivos estratégicos "
            "e insights existentes. "

            "Insight é inferência, não fato documental. "
            "Não invente informações, relações, resultados ou IDs. "
            "Use somente IDs explicitamente presentes no contexto. "

            "Se objetivo ou decisão não estiver diretamente "
            "relacionado, use string vazia para o respectivo ID. "

            "Use em evidencias_origem somente evidências que "
            "realmente sustentem a conclusão. "
            "Use em acoes_origem somente ações relevantes à análise. "

            "Não confunda correlação com causalidade. "
            "Preserve a incerteza. "
            "Não transforme possibilidade, pendência ou associação "
            "em impedimento, obrigação ou certeza sem suporte explícito. "

            "A existência de pendência, ação aberta ou processo não concluído "
            "não demonstra, por si só, gargalo, bloqueio, dependência crítica "
            "ou impedimento. Só faça essa classificação quando houver "
            "evidência explícita da relação de dependência. "

            "Diferencie risco localizado de risco empresarial geral. "
            "Não amplie uma limitação de canal, fornecedor, integração "
            "ou processo específico para toda a operação quando existirem "
            "alternativas possíveis ou quando o contexto não demonstrar "
            "dependência exclusiva. "

            "Registro documental de existência, atividade, contrato, "
            "pagamento ou disponibilidade não comprova, por si só, "
            "capacidade operacional, desempenho, urgência, economia, "
            "eficiência ou resultado. "

            "Conhecimento geral de negócios pode ajudar a formular hipóteses, "
            "mas não deve ser apresentado como conclusão específica sobre "
            "a empresa sem suporte no contexto fornecido. "
            "Quando uma relação for apenas plausível, trate-a explicitamente "
            "como hipótese ou oportunidade a validar e reduza a confiança. "

            "Não transforme efeito plausível em benefício demonstrado. "
            "Simplificação, destravamento, redução de atrito, redução de risco, "
            "ganho operacional, vantagem comercial ou melhoria de resultado "
            "exigem evidência específica de que esse efeito ocorreu ou de que "
            "a relação causal está explicitamente sustentada no contexto. "
            "Quando forem apenas consequências possíveis, formule como hipótese "
            "condicional a validar e não como conclusão sobre a empresa. "

            "A prioridade ou urgência atribuída a uma ação interna não comprova, "
            "por si só, a prioridade do insight derivado dela. A prioridade do "
            "insight deve refletir impacto, prazo, dependência ou consequência "
            "sustentados pelo conjunto do contexto. "

            "Pedido, protocolo, negociação, intenção ou processo em andamento "
            "não equivalem a concessão, aprovação, contrato concluído "
            "ou direito definitivamente adquirido. "
            "Não descreva protocolo ou pedido de registro como proteção, "
            "garantia, autorização ou base jurídica adquirida. "

            "Respeite rigorosamente o escopo de documentos, contratos, licenças "
            "e autorizações. Um documento que comprova direito, permissão ou "
            "capacidade em determinado canal, finalidade ou modalidade não "
            "comprova automaticamente direito, permissão ou capacidade em outro "
            "uso, ambiente, canal ou finalidade. Quando o novo uso depender de "
            "interpretação do escopo documental, trate-o como hipótese sujeita "
            "a verificação e não como capacidade formal ou possibilidade garantida. "

            "Ausência de evidência no contexto disponível não é evidência de "
            "ausência na empresa. Não conclua inexistência, insuficiência, lacuna, "
            "falta de capacidade, falta de parceiros, falta de alternativas ou "
            "outro estado negativo apenas porque não há registro correspondente "
            "nas fontes fornecidas. Nesses casos, diga somente que o contexto "
            "disponível não permite confirmar a existência ou suficiência e, "
            "quando útil, formule a necessidade de verificação como hipótese. "

            "Não trate uma ação recomendada como benefício demonstrado. "
            "Mapear, contratar, integrar, homologar, monitorar, estabelecer "
            "parcerias ou executar outra ação pode ter benefícios plausíveis, "
            "mas não comprova que reduzirá risco, acelerará resultados, aumentará "
            "vendas, melhorará eficiência ou produzirá outro efeito específico "
            "sem evidência que sustente essa relação. "

            "A mera existência de cláusula, obrigação, condição ou previsão "
            "contratual não comprova efeito operacional concreto. Não conclua "
            "gargalo, atraso, custo adicional, restrição de fluxo, necessidade "
            "de autorização, controle adicional ou outro impacto apenas pela "
            "existência do texto contratual. Esses efeitos exigem suporte "
            "específico no próprio documento ou evidência operacional adicional. "
            "Se o alcance prático da cláusula for desconhecido, preserve esse "
            "estado como questão a verificar, sem atribuir impacto presumido. "

            "A resposta textual deve mencionar somente a quantidade real "
            "de insights presentes no array insights. "

            "Não gere insight apenas para preencher a resposta. "
            "Evite repetir insights ativos existentes. "

            "Não execute ações nem crie compromissos. "
            "Não altere objetivos estratégicos. "

            + CONTEXTO_MARANHAO
            + CONTEXTO_EMPRESARIAL_INTERNO
            + HIERARQUIA_DECISAO_EMPRESARIAL
            + POLITICA_LINGUAGEM_NATURAL_IA
        ),

        input=(
            "CONTEXTO EMPRESARIAL PARA GERAÇÃO DE INSIGHTS:\n"
            + contexto
        )
    )

    texto_bruto = (
        resposta.output_text
        or ""
    ).strip()

    if not texto_bruto:
        return {
            "resposta": "",
            "insights": []
        }

    try:
        dados = json.loads(texto_bruto)
    except Exception as erro:
        raise ValueError(
            "A IA retornou insights em formato inválido."
        ) from erro

    if not isinstance(dados, dict):
        raise ValueError(
            "Estrutura de insights inválida."
        )

    insights = dados.get("insights") or []

    if not isinstance(insights, list):
        insights = []

    return {
        "resposta": str(
            dados.get("resposta") or ""
        ),
        "insights": insights
    }


def registrar_insight_empresarial(insight):

    if not isinstance(insight, dict):
        raise ValueError(
            "Insight empresarial inválido."
        )

    titulo = str(
        insight.get("titulo") or ""
    ).strip()

    descricao = str(
        insight.get("descricao") or ""
    ).strip()

    area = str(
        insight.get("area") or "estrategia"
    ).strip().lower()

    tipo_insight = str(
        insight.get("tipo_insight") or "analise"
    ).strip().lower()

    prioridade = str(
        insight.get("prioridade") or "media"
    ).strip().lower()

    confianca = str(
        insight.get("confianca") or "media"
    ).strip().lower()

    justificativa = str(
        insight.get("justificativa") or ""
    ).strip()

    if not titulo:
        raise ValueError(
            "Insight sem título."
        )

    if not descricao:
        raise ValueError(
            "Insight sem descrição."
        )

    evidencias_origem = (
        insight.get("evidencias_origem")
        or []
    )

    acoes_origem = (
        insight.get("acoes_origem")
        or []
    )

    eventos_origem = (
        insight.get("eventos_origem")
        or []
    )

    if not isinstance(
        evidencias_origem,
        list
    ):
        evidencias_origem = []

    if not isinstance(
        acoes_origem,
        list
    ):
        acoes_origem = []

    if not isinstance(
        eventos_origem,
        list
    ):
        eventos_origem = []

    evidencias_origem = sorted(
        {
            str(item).strip()
            for item in evidencias_origem
            if str(item).strip()
        }
    )

    acoes_origem = sorted(
        {
            str(item).strip()
            for item in acoes_origem
            if str(item).strip()
        }
    )

    eventos_origem = sorted(
        {
            str(item).strip()
            for item in eventos_origem
            if str(item).strip()
        }
    )

    def normalizar_uuid_referencia(valor):

        if not valor:
            return None

        texto = str(valor).strip()

        if not texto:
            return None

        try:
            return str(
                uuid.UUID(texto)
            )
        except (
            ValueError,
            TypeError,
            AttributeError
        ):
            return None

    objetivo_id = normalizar_uuid_referencia(
        insight.get("objetivo_id")
    )

    decisao_id = normalizar_uuid_referencia(
        insight.get("decisao_id")
    )

    titulo_normalizado = " ".join(
        titulo.lower().split()
    )

    base_deduplicacao = {
        "titulo": titulo_normalizado,
        "area": area,
        "tipo_insight": tipo_insight,
        "evidencias_origem":
            evidencias_origem,
        "acoes_origem":
            acoes_origem,
        "eventos_origem":
            eventos_origem,
        "objetivo_id":
            objetivo_id,
        "decisao_id":
            decisao_id
    }

    chave_deduplicacao = hashlib.sha256(
        json.dumps(
            base_deduplicacao,
            ensure_ascii=False,
            sort_keys=True
        ).encode("utf-8")
    ).hexdigest()

    insight_id = str(
        uuid.uuid4()
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO insights_empresariais (
                        id,
                        titulo,
                        descricao,
                        area,
                        tipo_insight,
                        prioridade,
                        confianca,
                        status,
                        justificativa,
                        evidencias_origem,
                        acoes_origem,
                        eventos_origem,
                        objetivo_id,
                        decisao_id,
                        origem,
                        chave_deduplicacao
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s,
                        %s::jsonb,
                        %s::jsonb,
                        %s::jsonb,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT (
                        chave_deduplicacao
                    )
                    WHERE
                        chave_deduplicacao
                        IS NOT NULL
                    DO NOTHING
                    RETURNING *
                """, (
                    insight_id,
                    titulo,
                    descricao,
                    area,
                    tipo_insight,
                    prioridade,
                    confianca,
                    "ativo",
                    justificativa or None,
                    json.dumps(
                        evidencias_origem,
                        ensure_ascii=False
                    ),
                    json.dumps(
                        acoes_origem,
                        ensure_ascii=False
                    ),
                    json.dumps(
                        eventos_origem,
                        ensure_ascii=False
                    ),
                    objetivo_id,
                    decisao_id,
                    "ia_empresarial",
                    chave_deduplicacao
                ))

                registro = cur.fetchone()

                criado = registro is not None

                if not criado:
                    cur.execute("""
                        SELECT *
                        FROM insights_empresariais
                        WHERE chave_deduplicacao = %s
                        LIMIT 1
                    """, (
                        chave_deduplicacao,
                    ))

                    registro = cur.fetchone()

        registro_id = (
            str(registro["id"])
            if registro
            else insight_id
        )

        registrar_auditoria(
            categoria="insight_empresarial",
            acao=(
                "insight_empresarial_registrado"
                if criado
                else
                "insight_empresarial_deduplicado"
            ),
            ator_tipo="ia",
            ator_id="ia_empresarial",
            origem="ia_empresarial",
            entidade_tipo="insight_empresarial",
            entidade_id=registro_id,
            status=(
                "criado"
                if criado
                else "existente"
            ),
            dados_entrada={
                "titulo": titulo,
                "area": area,
                "tipo_insight":
                    tipo_insight,
                "evidencias_origem":
                    evidencias_origem,
                "acoes_origem":
                    acoes_origem,
                "eventos_origem":
                    eventos_origem
            },
            dados_saida={
                "insight_id":
                    registro_id,
                "criado":
                    criado,
                "chave_deduplicacao":
                    chave_deduplicacao
            }
        )

        return {
            "insight": registro,
            "criado": criado,
            "chave_deduplicacao":
                chave_deduplicacao
        }

    finally:
        conn.close()




def validar_insight_empresarial(insight):
    """
    Valida epistemologicamente um insight antes da persistência.

    Esta função não grava no banco, não cria ações,
    não altera objetivos e não executa operações empresariais.
    """

    if not isinstance(insight, dict):
        return {
            "aprovado": False,
            "motivo": "Insight candidato não é um objeto válido."
        }

    contexto = (
        (carregar_evidencias_para_ia().get("contexto") or "")
        + (carregar_decisoes_para_ia().get("contexto") or "")
        + (carregar_acoes_para_ia().get("contexto") or "")
        + (carregar_objetivos_estrategicos_para_ia() or "")
    )

    if not contexto.strip():
        return {
            "aprovado": False,
            "motivo": "Contexto empresarial insuficiente para validação."
        }

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "validacao_insight_empresarial",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "aprovado": {
                            "type": "boolean"
                        },
                        "motivo": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "aprovado",
                        "motivo"
                    ],
                    "additionalProperties": False
                }
            }
        },

        instructions=(
            "Você é o validador epistemológico da inteligência "
            "empresarial privada da Maranhão Cordial. "

            "Sua função é verificar se um insight candidato é "
            "sustentado pelo contexto empresarial fornecido. "

            "Seja conservador. Rejeite o insight quando ele transformar "
            "possibilidade, associação, pendência ou hipótese em certeza, "
            "necessidade, impedimento, bloqueio ou causalidade sem suporte "
            "explícito no contexto. "

            "Rejeite quando ampliar um risco localizado para toda a "
            "operação sem evidência de dependência exclusiva. "

            "Rejeite quando existência documental, contrato, pagamento, "
            "cadastro, atividade registrada ou disponibilidade forem usados "
            "como prova de capacidade operacional, desempenho, urgência, "
            "economia, eficiência ou resultado sem suporte específico. "

            "Rejeite quando protocolo, pedido, negociação, intenção ou "
            "processo em andamento forem tratados como concessão, aprovação, "
            "direito adquirido ou resultado concluído. "

            "Verifique também se as evidências, ações, objetivo e decisão "
            "citados pelo candidato realmente sustentam a conclusão. "

            "Valide separadamente título, descrição, tipo, prioridade e confiança. "
            "Rejeite quando o título for mais categórico, amplo ou conclusivo "
            "do que a descrição e as fontes permitem. "

            "Prioridade alta ou crítica exige suporte explícito de impacto, "
            "urgência, prazo, dependência ou consequência relevante. "
            "Não classifique como crítico apenas porque existe pendência "
            "ou porque o tema é importante para a empresa. "
            "A prioridade ou confiança registrada em uma ação interna não é, "
            "sozinha, evidência suficiente para validar a prioridade ou confiança "
            "do insight. Avalie esses campos pela força das evidências e pela "
            "consequência empresarial efetivamente sustentada. "

            "Não transforme risco de um canal específico de pagamento, fornecedor, "
            "integração ou processo em risco para recebimentos, operação ou empresa "
            "como um todo sem evidência de dependência exclusiva ou ausência "
            "de alternativas relevantes. "

            "Não trate reputação, profissionalização percebida, vantagem comercial, "
            "ganho de credibilidade, eficiência ou valorização como resultado "
            "demonstrado quando forem apenas efeitos plausíveis. Nesses casos, "
            "a formulação deve permanecer explicitamente como hipótese ou "
            "oportunidade a validar. "

            "Também rejeite quando protocolo, pedido, cadastro, contrato ou outro "
            "ato documental for usado para concluir redução de risco, redução de "
            "conflito, destravamento, simplificação, ganho operacional ou benefício "
            "sem evidência específica de que esse efeito ocorreu ou de que a "
            "relação causal está explicitamente demonstrada. "

            "Valide também o escopo do documento citado. Contrato, licença, "
            "autorização ou outro documento que sustente determinado direito, "
            "canal, finalidade ou modalidade não deve ser usado para comprovar "
            "outro uso ou finalidade sem suporte explícito. Rejeite quando o "
            "insight extrapolar o alcance documental e apresentar essa extensão "
            "como capacidade formal, direito disponível ou possibilidade comprovada. "

            "Ausência de registro ou evidência no contexto disponível não comprova "
            "inexistência, insuficiência ou lacuna real. Rejeite quando o insight "
            "transformar falta de evidência sobre parceiro, fornecedor, capacidade, "
            "alternativa, processo, recurso ou outro elemento em evidência de que "
            "esse elemento não existe ou é insuficiente. A formulação aceitável "
            "deve preservar que o estado é desconhecido e pode exigir verificação. "

            "Rejeite também quando uma ação sugerida ou recomendada for usada como "
            "prova de benefício futuro. A plausibilidade de mapear, contratar, "
            "integrar, homologar, monitorar, estabelecer parceria ou executar outra "
            "ação não demonstra, por si só, redução de risco, aceleração, aumento "
            "de vendas, ganho de eficiência ou outro resultado empresarial. "

            "Rejeite quando a mera existência de cláusula, obrigação, condição "
            "ou previsão contratual for transformada em gargalo, atraso, custo, "
            "restrição operacional, necessidade de autorização, controle adicional "
            "ou outro efeito concreto sem suporte explícito. A possibilidade "
            "abstrata de uma cláusula produzir determinado impacto não comprova "
            "que esse impacto existe ou ocorrerá nesta empresa. Se o efeito "
            "operacional depender da interpretação do alcance da cláusula, "
            "o estado deve permanecer desconhecido até verificação específica. "

            "Uma oportunidade ou hipótese plausível pode ser aprovada quando "
            "estiver claramente apresentada como possibilidade, preservar "
            "a incerteza e tiver confiança compatível. "

            "Não corrija nem reescreva o insight. "
            "Apenas aprove ou rejeite e explique brevemente o motivo. "
            "No campo motivo, não cite, abrevie, reproduza ou invente IDs, "
            "UUIDs ou identificadores internos. Explique a validação em "
            "linguagem conceitual e rastreável pelos campos estruturados. "

            + CONTEXTO_MARANHAO
            + CONTEXTO_EMPRESARIAL_INTERNO
            + HIERARQUIA_DECISAO_EMPRESARIAL
            + POLITICA_LINGUAGEM_NATURAL_IA
        ),

        input=(
            "INSIGHT CANDIDATO:\n"
            + json.dumps(
                insight,
                ensure_ascii=False,
                default=str
            )
            + "\n\nCONTEXTO EMPRESARIAL DISPONÍVEL:\n"
            + contexto
        )
    )

    texto_bruto = (
        resposta.output_text
        or ""
    ).strip()

    if not texto_bruto:
        return {
            "aprovado": False,
            "motivo": "Validador não retornou resposta."
        }

    try:
        dados = json.loads(texto_bruto)
    except Exception as erro:
        raise ValueError(
            "A IA retornou validação de insight em formato inválido."
        ) from erro

    if not isinstance(dados, dict):
        raise ValueError(
            "Estrutura de validação de insight inválida."
        )

    return {
        "aprovado": bool(
            dados.get("aprovado")
        ),
        "motivo": str(
            dados.get("motivo")
            or ""
        )
    }



def verificar_duplicidade_semantica_insight(insight):

    if not isinstance(insight, dict):
        return {
            "duplicado": False,
            "insight_existente_id": None,
            "motivo": "Candidato inválido para comparação semântica."
        }

    existentes = carregar_insights_para_ia(
        limite=50
    ).get("insights") or []

    if not existentes:
        return {
            "duplicado": False,
            "insight_existente_id": None,
            "motivo": "Não há insights ativos para comparação."
        }

    candidatos_existentes = []

    for existente in existentes:

        candidatos_existentes.append({
            "id": str(existente.get("id") or ""),
            "titulo": str(
                existente.get("titulo") or ""
            ),
            "descricao": str(
                existente.get("descricao") or ""
            ),
            "area": str(
                existente.get("area") or ""
            ),
            "tipo_insight": str(
                existente.get("tipo_insight") or ""
            ),
            "justificativa": str(
                existente.get("justificativa") or ""
            )
        })

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "duplicidade_semantica_insight",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "duplicado": {
                            "type": "boolean"
                        },
                        "insight_existente_id": {
                            "type": "string"
                        },
                        "motivo": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "duplicado",
                        "insight_existente_id",
                        "motivo"
                    ],
                    "additionalProperties": False
                }
            }
        },

        instructions=(
            "Você atua como verificador conservador de duplicidade "
            "semântica de insights empresariais. "

            "Compare o insight candidato somente com os insights ativos "
            "fornecidos. Considere duplicado apenas quando candidato e "
            "insight existente expressarem essencialmente a mesma conclusão "
            "empresarial central, mesmo que usem palavras diferentes. "

            "Semelhança de tema, área, evidência, entidade, objetivo ou "
            "vocabulário não é suficiente para declarar duplicidade. "
            "Dois insights sobre o mesmo assunto podem representar conclusões "
            "diferentes e devem permanecer distintos. "

            "Compartilhar a mesma evidência documental também não é suficiente. "
            "Um insight que descreve o estado, existência ou situação de um "
            "documento, processo, contrato, ativo ou fato não é automaticamente "
            "duplicado de outro insight que deriva dessa mesma evidência uma "
            "oportunidade, risco, uso estratégico ou aplicação operacional. "

            "Considere materialmente diferentes os insights que introduzam "
            "uma ação estratégica, finalidade, público-alvo, canal, mercado, "
            "localidade, etapa operacional, efeito esperado ou condição que "
            "não faça parte da conclusão central do insight existente. "
            "Por exemplo, constatar que um ativo documental existe e concluir "
            "que esse ativo pode ser usado em uma estratégia comercial "
            "específica são conclusões relacionadas, mas não equivalentes. "

            "Não considere duplicado quando houver diferença material de "
            "causa, efeito, risco, oportunidade, hipótese, escopo, condição, "
            "finalidade, público, mercado ou conclusão. "
            "Na dúvida, responda duplicado=false. "

            "Se duplicado=true, insight_existente_id deve conter exatamente "
            "o ID de um dos insights ativos fornecidos. "
            "Se duplicado=false, insight_existente_id deve ser string vazia. "

            "Não invente IDs. Não altere nem reescreva os insights. "
        ),

        input=(
            "INSIGHT CANDIDATO:\n"
            + json.dumps(
                insight,
                ensure_ascii=False,
                default=str
            )
            + "\n\nINSIGHTS ATIVOS EXISTENTES:\n"
            + json.dumps(
                candidatos_existentes,
                ensure_ascii=False,
                default=str
            )
        )
    )

    try:
        dados = json.loads(
            resposta.output_text
        )
    except Exception as erro:
        raise ValueError(
            "A IA retornou verificação de duplicidade "
            "semântica em formato inválido."
        ) from erro

    if not isinstance(dados, dict):
        raise ValueError(
            "Estrutura de duplicidade semântica inválida."
        )

    duplicado = bool(
        dados.get("duplicado")
    )

    insight_existente_id = str(
        dados.get("insight_existente_id")
        or ""
    ).strip()

    ids_validos = {
        str(item.get("id"))
        for item in candidatos_existentes
        if item.get("id")
    }

    if (
        duplicado
        and insight_existente_id not in ids_validos
    ):
        raise ValueError(
            "Duplicidade semântica retornou "
            "insight existente inválido."
        )

    if not duplicado:
        insight_existente_id = None

    return {
        "duplicado": duplicado,
        "insight_existente_id":
            insight_existente_id,
        "motivo": str(
            dados.get("motivo") or ""
        )
    }


def processar_insights_empresariais():

    analise = (
        analisar_contexto_empresarial_para_insights()
    )

    candidatos = (
        analise.get("insights")
        if isinstance(analise, dict)
        else []
    ) or []

    resultados = []

    for indice, insight in enumerate(candidatos):

        try:

            validacao = validar_insight_empresarial(
                insight
            )

            if not validacao.get("aprovado"):
                resultados.append({
                    "indice": indice,
                    "titulo": str(
                        insight.get("titulo") or ""
                    ),
                    "sucesso": True,
                    "aprovado": False,
                    "criado": False,
                    "insight_id": None,
                    "chave_deduplicacao": None,
                    "motivo_rejeicao": (
                        validacao.get("motivo")
                        or ""
                    )
                })
                continue

            duplicidade = verificar_duplicidade_semantica_insight(
                insight
            )

            if duplicidade.get("duplicado"):

                resultados.append({
                    "indice": indice,
                    "titulo": str(
                        insight.get("titulo") or ""
                    ),
                    "sucesso": True,
                    "aprovado": True,
                    "criado": False,
                    "insight_id": (
                        duplicidade.get(
                            "insight_existente_id"
                        )
                    ),
                    "chave_deduplicacao": None,
                    "duplicado_semanticamente": True,
                    "motivo_validacao": (
                        validacao.get("motivo")
                        or ""
                    ),
                    "motivo_deduplicacao": (
                        duplicidade.get("motivo")
                        or ""
                    )
                })
                continue

            registro = registrar_insight_empresarial(
                insight
            )

            resultados.append({
                "indice": indice,
                "titulo": str(
                    insight.get("titulo") or ""
                ),
                "sucesso": True,
                "aprovado": True,
                "criado": registro["criado"],
                "insight_id": (
                    str(registro["insight"]["id"])
                    if registro.get("insight")
                    else None
                ),
                "chave_deduplicacao": (
                    registro[
                        "chave_deduplicacao"
                    ]
                ),
                "motivo_validacao": (
                    validacao.get("motivo")
                    or ""
                )
            })

        except Exception as erro:

            resultados.append({
                "indice": indice,
                "titulo": str(
                    insight.get("titulo") or ""
                ),
                "sucesso": False,
                "criado": False,
                "insight_id": None,
                "erro": str(erro)
            })

    aprovados = sum(
        1
        for item in resultados
        if (
            item.get("sucesso")
            and item.get("aprovado") is True
        )
    )

    rejeitados = sum(
        1
        for item in resultados
        if (
            item.get("sucesso")
            and item.get("aprovado") is False
        )
    )

    erros = sum(
        1
        for item in resultados
        if not item.get("sucesso")
    )

    return {
        "resposta": (
            f"{len(candidatos)} candidatos processados: "
            f"{aprovados} aprovados, "
            f"{rejeitados} rejeitados e "
            f"{erros} erros."
        ),
        "candidatos": len(candidatos),
        "aprovados": aprovados,
        "criados": sum(
            1
            for item in resultados
            if item.get("criado")
        ),
        "existentes": sum(
            1
            for item in resultados
            if (
                item.get("sucesso")
                and item.get("aprovado") is True
                and not item.get("criado")
                and not item.get(
                    "duplicado_semanticamente"
                )
            )
        ),
        "duplicados_semanticamente": sum(
            1
            for item in resultados
            if (
                item.get("sucesso")
                and item.get(
                    "duplicado_semanticamente"
                ) is True
            )
        ),
        "rejeitados": rejeitados,
        "erros": erros,
        "resultados": resultados
    }


def carregar_insights_para_ia(limite=50):

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
                        tipo_insight,
                        prioridade,
                        confianca,
                        status,
                        justificativa,
                        evidencias_origem,
                        acoes_origem,
                        eventos_origem,
                        objetivo_id,
                        decisao_id,
                        origem,
                        criado_em,
                        atualizado_em
                    FROM insights_empresariais
                    WHERE status = 'ativo'
                    ORDER BY
                        CASE prioridade
                            WHEN 'critica' THEN 1
                            WHEN 'alta' THEN 2
                            WHEN 'media' THEN 3
                            WHEN 'baixa' THEN 4
                            ELSE 5
                        END,
                        criado_em DESC
                    LIMIT %s
                """, (limite,))

                insights = cur.fetchall()

        linhas = []

        for insight in insights:

            linhas.append(
                (
                    f"- {insight['titulo']} "
                    f"| Área: {insight['area']} "
                    f"| Tipo: {insight['tipo_insight']} "
                    f"| Prioridade: {insight['prioridade']} "
                    f"| Confiança: {insight['confianca']} "
                    f"| Descrição: {insight['descricao']} "
                    f"| Justificativa: "
                    f"{insight['justificativa'] or 'não informada'} "
                    f"| Evidências de origem: "
                    f"{insight['evidencias_origem'] or []} "
                    f"| Ações de origem: "
                    f"{insight['acoes_origem'] or []} "
                    f"| Eventos de origem: "
                    f"{insight['eventos_origem'] or []} "
                    f"| Objetivo relacionado: "
                    f"{insight['objetivo_id'] or 'não informado'} "
                    f"| Decisão relacionada: "
                    f"{insight['decisao_id'] or 'não informada'}"
                )
            )

        contexto = ""

        if linhas:
            contexto = (
                "\n\n"
                "INSIGHTS EMPRESARIAIS ATIVOS\n"
                "Os itens abaixo são conclusões analíticas inferidas "
                "a partir de dados empresariais. "
                "Não os trate como fatos documentais. "
                "Considere a confiança, as evidências de origem "
                "e o contexto atual antes de utilizá-los. "
                "Um insight pode orientar uma recomendação, "
                "mas não constitui autorização para executar ações "
                "ou alterar objetivos estratégicos.\n"
                + "\n".join(linhas)
                + "\n"
            )

        return {
            "insights": insights,
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
                f"ID: {decisao['id']}\n"
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




# =====================================================
# IA EMPRESARIAL — EXPANSÃO DE OPORTUNIDADES
# =====================================================

POLITICA_EXPANSAO_OPORTUNIDADES_IA = """
PRINCÍPIO DE EXPANSÃO DE OPORTUNIDADES

Não trate os recursos, alternativas, orçamento, canal, fornecedor,
produto ou limites apresentados inicialmente pelo usuário como o
espaço total de solução.

Antes de recomendar uma ação, identifique o OBJETIVO ECONÔMICO REAL
por trás da pergunta.

Faça internamente estas perguntas:

1. O resultado desejado pode ser alcançado sem utilizar o recurso
   inicialmente apresentado?

2. Existe forma de obter resultado maior usando ativos já existentes
   da empresa, como:
   - marca;
   - conteúdo;
   - propriedade intelectual;
   - relacionamento;
   - contatos;
   - distribuição;
   - tecnologia;
   - dados;
   - conhecimento;
   - fornecedores;
   - comunidade;
   - eventos;
   - canais digitais?

3. Existe oportunidade adjacente de:
   - receita;
   - parceria;
   - licenciamento;
   - serviço;
   - distribuição;
   - B2B;
   - comissão;
   - conteúdo;
   - cross-selling;
   - redução estrutural de custo;
   - aquisição de cliente;
   - geração de caixa?

4. O problema apresentado pode ser reformulado de maneira que gere
   uma oportunidade maior?

5. Existe alternativa com maior retorno esperado, menor capital
   incremental ou melhor relação risco/retorno?

Quando houver uma alternativa não óbvia plausivelmente superior,
apresente-a explicitamente.

Não proponha criatividade pela criatividade.

Toda alternativa deve ser comparada considerando:
- retorno potencial;
- custo incremental;
- velocidade;
- risco;
- reversibilidade;
- aderência à estratégia;
- uso dos ativos existentes.

Não invente receitas, custos, probabilidades ou resultados.
Quando não houver dados suficientes, identifique a alternativa como
HIPÓTESE, SUGESTÃO ou OPORTUNIDADE A TESTAR.

Exemplo mental:
Se alguém disser "tenho R$ 5 para ganhar dinheiro", não presuma que
os R$ 5 precisam ser gastos. O objetivo é maximizar geração de valor,
e o recurso apresentado pode ser irrelevante para a melhor solução.

OBJETIVO REAL > ENQUADRAMENTO INICIAL DO PROBLEMA.
"""

POLITICA_ECONOMICA_IA = """
POLÍTICA DE EFICIÊNCIA ECONÔMICA E USO DE ATIVOS EXISTENTES

Ao analisar problemas ou recomendar ações para a Maranhão Cordial:

1. PRIORIZE ATIVOS JÁ EXISTENTES
Antes de recomendar nova contratação, assinatura, plataforma,
consultoria, mídia paga, equipamento ou serviço externo,
verifique se o problema pode ser resolvido com ativos que a
empresa já possui.

Considere especialmente:
- site e backend próprios;
- IA empresarial;
- CRM e banco de dados;
- SAC;
- rede de contatos estratégicos;
- bartenders e especialistas já relacionados;
- fabricantes já prospectados;
- documentos e conhecimento já produzidos;
- canais digitais existentes;
- estrutura de pagamentos existente;
- infraestrutura tecnológica já contratada;
- conteúdo, marca e ativos intelectuais existentes.

2. MINIMIZE GASTO INCREMENTAL
Entre duas soluções com resultado esperado semelhante,
prefira a que exigir menor desembolso adicional,
menor custo recorrente e menor dependência de terceiros.

Antes de recomendar criar nova página, formulário, módulo,
integração ou fluxo operacional, verifique se já existe
funcionalidade equivalente na infraestrutura atual.
Prefira adaptar, reutilizar, conectar ou ampliar ativos existentes
antes de criar novos componentes.

3. MAXIMIZE RESULTADO ECONÔMICO
Priorize:
- margem de contribuição;
- geração de caixa;
- lucro operacional;
- conversão de demanda existente;
- utilização de capacidade já disponível;
- redução de desperdício;
- redução de CAC;
- aumento de recompra e LTV;
- melhor aproveitamento dos ativos existentes.

4. NÃO CONFUNDA ECONOMIA COM RESULTADO
Uma alternativa mais barata não é necessariamente melhor.
Compare custo, retorno, prazo, risco, capacidade, impacto em vendas
e margem esperada.

5. NOVOS GASTOS PRECISAM DE JUSTIFICATIVA
Somente recomende despesa adicional quando:
- houver ganho econômico esperado claramente superior;
- o ativo atual for insuficiente;
- houver risco regulatório, jurídico, técnico ou operacional relevante;
- a despesa destravar receita ou capacidade materialmente superior.

Quando recomendar gasto novo, explique brevemente:
- por que os ativos atuais não bastam;
- qual benefício esperado;
- qual informação falta para avaliar retorno.

6. PROTEJA MARGEM E POSICIONAMENTO
Não recomende desconto, comissão, frete subsidiado,
CAC ou condição comercial apenas para aumentar volume.
Avalie impacto sobre margem, posicionamento premium,
recorrência e valor estratégico do cliente.

7. USE DADOS REAIS ANTES DE ESTIMATIVAS
Prefira, nesta ordem:
a) realizado;
b) cotado/verificado;
c) estimado documentado;
d) hipótese.

Nunca trate hipótese como fato.

8. RESTRIÇÕES SUPERIORES
Eficiência econômica nunca autoriza:
- descumprimento regulatório;
- redução indevida de qualidade;
- violação contratual;
- exposição de informação confidencial;
- assumir compromisso comercial não autorizado;
- movimentação financeira não autorizada.

Objetivo:
resolver cada necessidade empresarial utilizando a menor quantidade
razoável de recursos adicionais e buscando a maior geração sustentável
de valor econômico para a Maranhão Cordial.
"""



POLITICA_PRIORIDADE_CONTEXTO_INTERNO = """
PRIORIDADE DE CONTEXTO — MARANHÃO CORDIAL

Para perguntas sobre a própria Maranhão Cordial,
priorize informações nesta ordem:

1. Evidências empresariais documentais vigentes.
2. Documentos internos vigentes.
3. Resultados realizados e registros transacionais.
4. CRM e histórico de relacionamento.
5. Decisões empresariais registradas.
6. Fábricas, fiscal e logística verificados.
7. Cotações e informações de contraparte.
8. Estimativas internas documentadas.
9. Hipóteses.
10. Conhecimento geral do modelo.

Quando houver conflito entre conhecimento genérico
e informação empresarial documentada,
priorize o dado empresarial documentado,
desde que não haja evidência de que esteja desatualizado.

Nunca transforme ausência de dado em fato.

Quando uma resposta depender de informação que ainda
não existe na base, diga claramente:
"Este dado ainda não está confirmado no sistema."

A vantagem desta IA é o contexto proprietário.
Use esse contexto antes de responder genericamente.
"""

POLITICA_COMUNICACAO_EMPRESARIAL = """
POLÍTICA DE COMUNICAÇÃO EXTERNA — MARANHÃO CORDIAL

Quando a direção solicitar uma mensagem para cliente,
fornecedor, fabricante, bartender, mixologista, restaurante,
hotel, parceiro, evento, instituição ou outro contato externo:

1. ENTENDA PRIMEIRO A DECISÃO
Identifique qual decisão empresarial já foi tomada
e qual objetivo a comunicação deve alcançar.

2. SEPARE MOTIVO INTERNO DE MENSAGEM EXTERNA
Diferencie:
- razão interna da decisão;
- fato que precisa ser comunicado;
- informação estratégica ou confidencial que não precisa ser revelada.

3. NÃO EXPONHA A IA
Nunca diga ao destinatário:
- "a IA decidiu";
- "a IA recomendou";
- "nosso sistema mandou";
- ou expressão equivalente.

Externamente, decisões devem ser apresentadas
como decisões da Maranhão Cordial ou de sua direção.

4. NÃO INVENTE JUSTIFICATIVAS
Utilize apenas fatos disponíveis no contexto.
Pode selecionar quais fatos são adequados para comunicar,
mas nunca criar uma razão falsa.

5. PRESERVE RELACIONAMENTOS
Em adiamentos, recusas, cancelamentos ou negativas:
- comunique com clareza;
- seja respeitoso;
- evite excesso de justificativa;
- preserve a possibilidade real de relação futura,
quando isso fizer sentido estratégico.

6. NÃO INFLAR RELACIONAMENTOS
Nunca confunda:
contato != parceiro formal
interesse != compra
conversa != negociação
negociação != contrato
evento != patrocínio
amostra != cliente
engajamento != validação sensorial
pedido de marca != marca concedida

7. ADAPTE AO CANAL

WhatsApp:
- natural;
- profissional;
- humano;
- direto;
- sem excesso de formalidade.

Instagram/DM:
- curto;
- pessoal;
- contextual.

E-mail:
- estruturado;
- profissional;
- mais completo quando necessário.

8. USE O HISTÓRICO REAL
Antes de redigir, considere quando disponível:
- quem é o contato;
- empresa;
- cargo/função;
- histórico das conversas;
- último contato;
- compromissos anteriores;
- estágio da relação;
- próximo passo registrado;
- oportunidades e riscos.

9. PROTEJA OS INTERESSES DA EMPRESA
A comunicação deve preservar:
- reputação;
- posicionamento premium;
- margem;
- poder de negociação;
- confidencialidade;
- coerência estratégica.

10. NÃO REVELE FRAGILIDADE DESNECESSÁRIA
Se houver decisão de contenção de custos,
não diga automaticamente que a empresa está sem dinheiro.
Se houver problema de fornecedor,
não exponha detalhes além do necessário.
Comunique a decisão verdadeira de forma apropriada.

11. RESPOSTA PRONTA PRIMEIRO
Quando o usuário pedir uma mensagem,
entregue primeiro a versão pronta para envio.
Só faça análise extensa se for solicitada.

12. OBJETIVO FINAL
Transformar decisões internas corretas
em mensagens externas claras, elegantes,
verdadeiras e estrategicamente adequadas.
"""


REGRA_MENSAGENS_ESTRATEGICAS = """
Para redigir comunicação externa, determine internamente:

DECISÃO:
O que a Maranhão Cordial decidiu?

OBJETIVO:
O que queremos conseguir, evitar ou preservar?

RELACIONAMENTO:
Quem é a contraparte e qual é o estágio real da relação?

LIMITE:
O que é verdadeiro, mas não precisa ser revelado?

Use essas quatro dimensões para escrever a mensagem.
Não exponha essa análise ao destinatário.
"""



# =====================================================
# ROTEADOR DE CONTEXTO — IA EMPRESARIAL
# =====================================================

def classificar_contexto_empresarial(pergunta):

    import re

    texto = str(
        pergunta or ""
    ).strip().lower()

    categorias = set()

    grupos = {

        "industrial": {
            "fábrica",
            "fabrica",
            "fabricante",
            "produção",
            "producao",
            "lote",
            "copack",
            "envase",
            "capacidade",
            "industrial",
            "terceirização",
            "terceirizacao",
            "white label"
        },

        "financeiro": {
            "custo",
            "margem",
            "preço",
            "preco",
            "lucro",
            "ebitda",
            "cmv",
            "caixa",
            "faturamento",
            "rentabilidade",
            "ticket",
            "capital",
            "investimento",
            "valuation",
            "valor da empresa",
            "geração de caixa",
            "geracao de caixa"
        },

        "fiscal": {
            "imposto",
            "tributo",
            "icms",
            "difal",
            "st",
            "ncm",
            "cfop",
            "csosn",
            "simples",
            "fiscal"
        },

        "logistica": {
            "frete",
            "logística",
            "logistica",
            "entrega",
            "rota",
            "transportadora",
            "distância",
            "distancia",
            "prazo de entrega"
        },

        "comercial": {
            "cliente",
            "lead",
            "venda",
            "comprador",
            "hotel",
            "bar",
            "restaurante",
            "distribuidor",
            "proposta",
            "negociação",
            "negociacao",
            "b2b",
            "degustação",
            "degustacao",
            "conversão",
            "conversao",
            "recompra"
        },

        "profissional": {
            "bartender",
            "mixologista",
            "sommelier",
            "chef",
            "profissional",
            "embaixador",
            "influenciador",
            "amostra",
            "evento"
        },

        "regulatorio": {
            "mapa",
            "registro",
            "regulatório",
            "regulatorio",
            "rótulo",
            "rotulo",
            "legislação",
            "legislacao",
            "anvisa",
            "responsável técnico",
            "responsavel tecnico"
        },

        "marca": {
            "marca",
            "branding",
            "posicionamento",
            "reputação",
            "reputacao",
            "desejo",
            "percepção",
            "percepcao",
            "imagem da marca",
            "identidade",
            "território de marca",
            "territorio de marca"
        },

        "comunicacao": {
            "imprensa",
            "assessoria de imprensa",
            "relações públicas",
            "relacoes publicas",
            "relações publicas",
            "rp",
            "mídia",
            "midia",
            "comunicação",
            "comunicacao",
            "release",
            "jornalista"
        },

        "tecnologia": {
            "tecnologia",
            "software",
            "sistema",
            "ia",
            "inteligência artificial",
            "inteligencia artificial",
            "automação",
            "automacao",
            "backend",
            "api",
            "integração",
            "integracao",
            "crm"
        },

        "estrategia": {
            "estratégia",
            "estrategia",
            "prioridade",
            "decisão",
            "decisao",
            "vale a pena",
            "melhor opção",
            "melhor opcao",
            "recomenda",
            "o que fazer",
            "próximo passo",
            "proximo passo",
            "crescimento",
            "escalar",
            "escala",
            "modelo de negócio",
            "modelo de negocio",
            "vantagem competitiva",
            "criação de valor",
            "criacao de valor",
            "valor estratégico",
            "valor estrategico"
        }
    }

    def termo_presente(termo):

        termo = termo.strip().lower()

        if " " in termo:
            return termo in texto

        padrao = (
            r"(?<!\w)"
            + re.escape(termo)
            + r"(?!\w)"
        )

        return bool(
            re.search(
                padrao,
                texto,
                flags=re.IGNORECASE
            )
        )

    for categoria, termos in grupos.items():

        if any(
            termo_presente(termo)
            for termo in termos
        ):
            categorias.add(
                categoria
            )

    if not categorias:
        categorias.add(
            "geral"
        )

    return categorias

def montar_contexto_empresarial_seletivo(
    pergunta,
    *,
    contexto_documental="",
    contexto_evidencias="",
    contexto_decisoes="",
    contexto_insights="",
    contexto_acoes="",
    contexto_crm="",
    contexto_fabricas="",
    contexto_profissionais="",
    contexto_fiscal="",
    contexto_logistica="",
    contexto_contatos="",
    contexto_operacional=""
):

    categorias = (
        classificar_contexto_empresarial(
            pergunta
        )
    )

    blocos = []

    # -------------------------------------------------
    # CONTEXTO CENTRAL
    # Sempre disponível para qualquer decisão.
    # -------------------------------------------------

    blocos.append(
        contexto_decisoes
    )

    blocos.append(
        contexto_evidencias
    )

    blocos.append(
        contexto_insights
    )

    # -------------------------------------------------
    # DOCUMENTOS
    # -------------------------------------------------

    if categorias & {
        "industrial",
        "regulatorio",
        "financeiro",
        "estrategia",
        "marca",
        "comunicacao",
        "geral"
    }:
        blocos.append(
            contexto_documental
        )

    # -------------------------------------------------
    # FÁBRICAS
    # Somente quando a pergunta realmente envolve
    # produção, regulação ou logística industrial.
    # -------------------------------------------------

    if categorias & {
        "industrial",
        "regulatorio",
        "logistica"
    }:
        blocos.append(
            contexto_fabricas
        )

    # -------------------------------------------------
    # REDE PROFISSIONAL
    # -------------------------------------------------

    if categorias & {
        "profissional",
        "comercial",
        "comunicacao",
        "marca"
    }:
        blocos.append(
            contexto_profissionais
        )

    # -------------------------------------------------
    # CRM
    # -------------------------------------------------

    if categorias & {
        "comercial",
        "comunicacao",
        "marca"
    }:
        blocos.append(
            contexto_crm
        )

    # -------------------------------------------------
    # FISCAL
    # -------------------------------------------------

    if categorias & {
        "fiscal",
        "industrial",
        "regulatorio"
    }:
        blocos.append(
            contexto_fiscal
        )

    # -------------------------------------------------
    # LOGÍSTICA
    # -------------------------------------------------

    if categorias & {
        "logistica",
        "industrial",
        "comercial"
    }:
        blocos.append(
            contexto_logistica
        )

    # -------------------------------------------------
    # CONTATOS ESTRATÉGICOS
    # -------------------------------------------------

    if categorias & {
        "comercial",
        "profissional",
        "comunicacao",
        "marca",
        "estrategia"
    }:
        blocos.append(
            contexto_contatos
        )

    # -------------------------------------------------
    # OPERAÇÃO
    # -------------------------------------------------

    if categorias & {
        "industrial",
        "financeiro",
        "tecnologia",
        "estrategia",
        "geral"
    }:
        blocos.append(
            contexto_operacional
        )

    # -------------------------------------------------
    # AÇÕES EMPRESARIAIS
    # -------------------------------------------------

    if categorias & {
        "comercial",
        "estrategia",
        "tecnologia",
        "comunicacao",
        "marca",
        "geral"
    }:
        blocos.append(
            contexto_acoes
        )

    contexto_final = "".join(
        bloco
        for bloco in blocos
        if bloco
    )

    cabecalho = (
        "\n\nROTEAMENTO DE CONTEXTO DA IA\n"
        "Categorias detectadas: "
        + ", ".join(
            sorted(categorias)
        )
        + "\n"
        "Use os contextos selecionados como evidência empresarial, "
        "sem limitar o raciocínio apenas a eles.\n"
    )

    return {
        "categorias":
            sorted(categorias),

        "contexto":
            cabecalho
            + contexto_final
    }



# =====================================================
# TRAVAS DE ELEGIBILIDADE — IA EMPRESARIAL
# =====================================================

def montar_travas_elegibilidade_ia(
    pergunta,
    *,
    fabricas=None,
    profissionais=None
):

    import unicodedata

    fabricas = fabricas or []
    profissionais = profissionais or []

    texto_original = str(
        pergunta or ""
    ).strip().lower()

    texto = "".join(
        caractere
        for caractere in unicodedata.normalize(
            "NFD",
            texto_original
        )
        if unicodedata.category(
            caractere
        ) != "Mn"
    )

    regras = []

    # -------------------------------------------------
    # REDE PROFISSIONAL
    # -------------------------------------------------

    termos_profissionais = {
        "bartender",
        "bartenders",
        "mixologista",
        "mixologistas",
        "profissional",
        "profissionais",
        "sommelier",
        "sommeliers"
    }

    consulta_profissional = any(
        termo in texto
        for termo in termos_profissionais
    )

    pede_qualificado = (
        "qualificad" in texto
    )

    pede_ativo = (
        "ativo" in texto
        or "ativos" in texto
    )

    if consulta_profissional:

        if pede_ativo:
            elegiveis_profissionais = [
                item
                for item in profissionais
                if (
                    item.get(
                        "status_fluxo"
                    )
                    == "ativo"
                    and item.get(
                        "disponivel_ia"
                    ) is True
                )
            ]

            descricao_status = (
                "status_fluxo='ativo' "
                "e disponivel_ia=TRUE"
            )

        elif pede_qualificado:
            elegiveis_profissionais = [
                item
                for item in profissionais
                if (
                    item.get(
                        "status_fluxo"
                    )
                    in {
                        "qualificado",
                        "relacionamento",
                        "ativo"
                    }
                    and item.get(
                        "disponivel_ia"
                    ) is True
                )
            ]

            descricao_status = (
                "qualificado, relacionamento "
                "ou ativo e disponivel_ia=TRUE"
            )

        else:
            elegiveis_profissionais = [
                item
                for item in profissionais
                if item.get(
                    "disponivel_ia"
                ) is True
            ]

            descricao_status = (
                "disponivel_ia=TRUE"
            )

        total_profissionais = len(
            elegiveis_profissionais
        )

        regras.append(
            "- A pergunta atual está direcionada "
            "à REDE PROFISSIONAL."
        )

        regras.append(
            "- Não substitua bartender, mixologista "
            "ou profissional por fábrica, fornecedor, "
            "consultor industrial ou contato de outra "
            "categoria."
        )

        regras.append(
            "- Critério de elegibilidade profissional "
            f"nesta consulta: {descricao_status}."
        )

        regras.append(
            "- Quantidade de profissionais elegíveis "
            f"encontrados: {total_profissionais}."
        )

        if total_profissionais == 0:
            regras.append(
                "- NÃO HÁ profissionais elegíveis "
                "para a solicitação atual. "
                "A resposta deve declarar explicitamente "
                "a ausência de profissionais elegíveis "
                "na base. NÃO escolha entidade de outra "
                "rede para preencher a lacuna."
            )

        else:
            nomes = [
                str(
                    item.get("nome")
                    or "sem nome"
                )
                for item
                in elegiveis_profissionais[:20]
            ]

            regras.append(
                "- Profissionais elegíveis nesta consulta: "
                + "; ".join(nomes)
                + "."
            )

    # -------------------------------------------------
    # REDE INDUSTRIAL
    # -------------------------------------------------

    termos_fabricas = {
        "fabrica",
        "fabricas",
        "fabricante",
        "fabricantes",
        "industria",
        "industrias"
    }

    consulta_fabrica = any(
        termo in texto
        for termo in termos_fabricas
    )

    pede_homologada = (
        "homologad" in texto
    )

    pede_qualificada_fabrica = (
        "qualificad" in texto
        and consulta_fabrica
    )

    if consulta_fabrica:

        if pede_homologada:

            elegiveis_fabricas = [
                item
                for item in fabricas
                if (
                    item.get(
                        "status_fluxo"
                    )
                    == "homologada"
                    and item.get(
                        "disponivel_calculo_ia"
                    ) is True
                )
            ]

            descricao_status_fabrica = (
                "status_fluxo='homologada' "
                "e disponivel_calculo_ia=TRUE"
            )

        elif pede_qualificada_fabrica:

            elegiveis_fabricas = [
                item
                for item in fabricas
                if item.get(
                    "status_fluxo"
                )
                in {
                    "qualificada",
                    "homologada"
                }
            ]

            descricao_status_fabrica = (
                "status_fluxo qualificada "
                "ou homologada"
            )

        else:

            elegiveis_fabricas = [
                item
                for item in fabricas
                if item.get(
                    "status_fluxo"
                )
                not in {
                    "rejeitada",
                    "suspensa"
                }
            ]

            descricao_status_fabrica = (
                "não rejeitada e não suspensa"
            )

        total_fabricas = len(
            elegiveis_fabricas
        )

        regras.append(
            "- A pergunta atual envolve "
            "a REDE INDUSTRIAL."
        )

        regras.append(
            "- Critério industrial desta consulta: "
            f"{descricao_status_fabrica}."
        )

        regras.append(
            "- Quantidade de fábricas elegíveis "
            f"encontradas: {total_fabricas}."
        )

        if (
            pede_homologada
            and total_fabricas == 0
        ):
            regras.append(
                "- NÃO HÁ fábrica homologada elegível "
                "na base para esta consulta. "
                "É proibido apresentar uma fábrica "
                "qualificada, pendente ou em validação "
                "como se estivesse homologada."
            )

        elif total_fabricas:

            nomes = [
                str(
                    item.get("nome")
                    or "sem nome"
                )
                + " ["
                + str(
                    item.get(
                        "status_fluxo"
                    )
                    or "sem status"
                )
                + "]"
                for item
                in elegiveis_fabricas[:20]
            ]

            regras.append(
                "- Fábricas elegíveis nesta consulta: "
                + "; ".join(nomes)
                + "."
            )

    # -------------------------------------------------
    # NÚMEROS / FATOS EMPRESARIAIS
    # -------------------------------------------------

    termos_numericos = {
        "custo",
        "preco",
        "margem",
        "percentual",
        "volume",
        "litros",
        "unidades",
        "prazo",
        "faturamento",
        "ebitda",
        "ticket",
        "capacidade"
    }

    if any(
        termo in texto
        for termo in termos_numericos
    ):
        regras.append(
            "- Qualquer número apresentado como fato "
            "empresarial deve existir no contexto atual. "
            "Se não existir, identifique-o explicitamente "
            "como ESTIMATIVA, HIPÓTESE ou SUGESTÃO."
        )

    # -------------------------------------------------
    # REGRA GERAL CONTRA PREENCHIMENTO DE LACUNAS
    # -------------------------------------------------

    regras.append(
        "- Se os dados elegíveis forem insuficientes "
        "para concluir, diga que não há dados suficientes. "
        "Não complete a resposta usando entidade, status "
        "ou número de outra categoria."
    )

    if not regras:
        return ""

    return (
        "\n\n"
        "TRAVAS OBRIGATÓRIAS DA CONSULTA ATUAL\n"
        + "\n".join(regras)
        + "\n"
    )



# =====================================================
# OBJETIVO SUPERIOR DA EMPRESA — IA EMPRESARIAL
# =====================================================

POLITICA_OBJETIVO_SUPERIOR_EMPRESA = """
OBJETIVO SUPERIOR DA MARANHÃO CORDIAL:

A função-objetivo da empresa NÃO é maximizar simplesmente
o número de garrafas vendidas no curto prazo.

O objetivo estratégico de longo prazo é construir uma empresa
cada vez mais valiosa, desejável, diferenciada, defensável e
estrategicamente relevante, aumentando sua capacidade de geração
de valor econômico e sua atratividade para uma eventual venda,
aquisição, investimento ou operação societária futura.

A venda futura da empresa é uma possibilidade estratégica de
longo prazo e deve ser considerada na criação de valor desde agora,
sem transformar a operação atual em busca precipitada por comprador.

A lógica de criação de valor pode ocorrer por diferentes caminhos,
inclusive:

contexto social
→ identificação
→ comunidade
→ circulação cultural
→ reputação
→ relevância da marca
→ desejo
→ poder de distribuição e precificação
→ valor econômico
→ aumento do valor estratégico da empresa.

Essa cadeia NÃO é obrigatoriamente linear e nem toda interação
precisa resultar em compra imediata.

Uma pessoa, contato ou comunidade pode gerar valor para a empresa
mesmo sem comprar produto naquele momento, por exemplo por meio de:

- identificação cultural;
- construção de comunidade;
- circulação da marca;
- reputação;
- legitimidade;
- validação de território simbólico;
- influência;
- acesso a novas redes;
- inteligência de mercado;
- relacionamento;
- formação de desejo;
- fortalecimento de posicionamento;
- criação de propriedade intelectual;
- produção de dados proprietários;
- fortalecimento da capacidade futura de distribuição.

NÃO transforme automaticamente todo contato em lead comercial.

Antes de avaliar uma interação, pergunte:

"Que ativo esta interação pode estar fortalecendo para a empresa?"

Esse ativo pode ser:

- receita;
- margem;
- recorrência;
- distribuição;
- marca;
- comunidade;
- reputação;
- relacionamento;
- acesso;
- conhecimento;
- dados;
- tecnologia;
- propriedade intelectual;
- eficiência;
- opcionalidade estratégica.

VENDAS:

Venda de produto é importante quando contribui para a construção
de valor estratégico da empresa.

Volume vendido, isoladamente, NÃO é objetivo superior.

Uma venda pode ser especialmente relevante quando comprova ou melhora:

- disposição real a pagar;
- margem;
- recorrência;
- recompra;
- eficiência comercial;
- distribuição;
- posicionamento;
- poder de preço;
- qualidade da demanda;
- reputação;
- acesso a mercados;
- geração de dados;
- aprendizado proprietário;
- previsibilidade de receita.

Não recomende crescimento de volume que destrua margem,
posicionamento, desejo, reputação ou capacidade futura de criação
de valor apenas para aumentar unidades vendidas no curto prazo.

COMUNIDADE E CAPITAL SIMBÓLICO:

Também não romantize atenção, comunidade ou engajamento.

Curtidas, elogios, identificação cultural e audiência são sinais,
não valor econômico automaticamente realizado.

Quando considerar comunidade, reputação ou circulação cultural como
ativos, procure explicar qual mecanismo pode transformar esse ativo
em vantagem econômica ou estratégica futura.

Uma interação social pode ser mais estratégica que uma venda
isolada quando ela fortalece um ativo acumulativo importante,
como comunidade, reputação, legitimidade, acesso ou distribuição.

AVALIAÇÃO DE DECISÕES:

Ao comparar alternativas, pergunte primeiro:

"Qual alternativa aumenta mais a probabilidade de a Maranhão Cordial
se tornar uma empresa mais valiosa e estrategicamente desejável
no futuro?"

Depois identifique POR QUAL MECANISMO isso ocorre.

Não confunda:
- faturamento com valor empresarial;
- volume com qualidade de crescimento;
- cliente com comunidade;
- comunidade com cliente;
- produto com empresa;
- engajamento com receita;
- receita de curto prazo com criação de valor de longo prazo.

A melhor decisão é aquela que preserva a sobrevivência econômica
da empresa e, ao mesmo tempo, fortalece os ativos que aumentam
seu valor estratégico futuro.
"""


# =====================================================
# POLÍTICA DE RACIOCÍNIO ESTRATÉGICO — IA EMPRESARIAL
# =====================================================

POLITICA_RACIOCINIO_ESTRATEGICO_IA = """
RACIOCÍNIO ESTRATÉGICO PARA A DIREÇÃO:

Você é assessoria da DIREÇÃO da Maranhão Cordial, não apenas
uma assistente do produto, da fábrica ou da operação corrente.

Antes de responder, identifique qual é a natureza real da pergunta.
Ela pode envolver, entre outros temas:

- estratégia empresarial;
- modelo de negócio;
- crescimento;
- valuation e criação de valor;
- marca e posicionamento;
- reputação e relações públicas;
- comunicação;
- comercial e vendas;
- distribuição;
- relacionamento e networking;
- finanças e alocação de capital;
- operação;
- tecnologia;
- pessoas e fornecedores;
- produto;
- produção;
- logística;
- regulatório;
- riscos;
- oportunidades adjacentes.

NÃO direcione automaticamente toda análise para o produto físico,
fábrica, produção, bartender ou mercado B2B.

O produto é um ativo da empresa, não a empresa inteira.

Quando a pergunta for ampla ou estratégica:
1. compreenda primeiro o objetivo da direção;
2. raciocine sobre o negócio como um sistema;
3. considere alternativas fora do enquadramento inicial;
4. use conhecimento empresarial geral quando ele ajudar;
5. confronte esse conhecimento com os dados proprietários disponíveis;
6. diferencie claramente fato interno de inferência ou recomendação;
7. procure efeitos de segunda ordem, riscos, oportunidades e trade-offs;
8. não force uma ação operacional imediata quando a melhor resposta
   for reflexão, diagnóstico, comparação ou orientação estratégica.

O contexto proprietário da Maranhão Cordial deve ENRIQUECER o
raciocínio, não restringi-lo.

Quando houver dados internos relevantes, use-os.
Quando conhecimento empresarial geral for útil e não contradizer
dados internos confirmados, utilize-o normalmente.

Não confunda:
- ausência de dado interno com impossibilidade de raciocinar;
- contexto operacional com objetivo estratégico;
- produto com empresa;
- tarefa imediata com melhor decisão;
- atividade com criação de valor.

Pense como assessoria empresarial da direção:
com visão ampla, crítica, econômica, estratégica e prática.
"""

# =====================================================
# POLÍTICA DE DIAGNÓSTICO CONCISO — IA EMPRESARIAL
# =====================================================

POLITICA_DIAGNOSTICO_CONCISO_IA = """
REGRAS DE RESPOSTA EXECUTIVA:

1. Responda primeiro à pergunta feita.

2. Seja curto.
Por padrão, use de 1 a 3 parágrafos curtos.
Não produza relatório se o usuário não pedir.

3. Não exponha linguagem interna de banco de dados,
código ou implementação ao usuário.

Não escreva expressões como:
- disponivel_ia=TRUE
- status_fluxo='qualificado'
- FALSE
- NULL
- nome de coluna
- nome de tabela
- nome de variável
- sintaxe SQL ou Python

Traduza sempre para linguagem empresarial natural.

Exemplos:

Em vez de:
"status_fluxo='homologada'"

diga:
"fábrica homologada"

Em vez de:
"disponivel_ia=TRUE"

diga:
"disponível para análise pela IA"

Em vez de:
"0 registros elegíveis"

diga:
"não há profissionais elegíveis na base atual"

4. Não explique mecanismos internos da IA,
roteamento, flags, banco de dados ou travas,
a menos que o usuário pergunte especificamente
sobre o funcionamento técnico do sistema.

5. Diferencie claramente:
- fato confirmado;
- informação em validação;
- hipótese;
- sugestão.

Mas não coloque esses rótulos desnecessariamente
quando a frase já for clara.

6. Não repita na conclusão todos os dados usados
para chegar à conclusão.

7. Quando não houver dados suficientes,
diga isso diretamente e indique somente o dado
mais importante que falta.

8. Finalize com no máximo um próximo passo,
quando houver uma ação realmente útil.
"""


POLITICA_ACOES_SUGERIDAS_IA = """
GOVERNANÇA DAS AÇÕES SUGERIDAS:

1. Sugira no máximo 2 ações.

2. Prefira 1 ação.
Use 2 somente quando forem independentes
e realmente necessárias.

3. Não crie ação apenas para preencher espaço.
Se nenhuma ação for necessária, retorne lista vazia.

4. Toda ação deve ser concreta, curta e executável.

5. O título deve ter no máximo 8 palavras.

6. A descrição deve ter no máximo 2 frases curtas.

7. A justificativa deve ter no máximo 1 frase curta.

8. Não invente metas numéricas.
Não diga "captar 3", "buscar 10", "produzir 1.000"
ou qualquer quantidade como recomendação,
a menos que essa quantidade esteja registrada
como meta, requisito ou decisão no contexto.

Se uma quantidade nova for apenas uma ideia,
não a transforme em ação operacional.

9. Nunca sugira alterar diretamente campos técnicos
ou flags internas do sistema.

Exemplos proibidos:
- marcar disponivel_ia;
- definir TRUE ou FALSE;
- editar status_fluxo;
- alterar campo diretamente no banco.

A ação deve representar o processo empresarial.

Exemplo correto:
"Validar os profissionais cadastrados."

Não:
"Alterar disponivel_ia para TRUE."

10. Nunca pule o workflow de governança.

Não sugira:
- homologar fábrica sem validação;
- qualificar profissional sem validação;
- aprovar informação de terceiro automaticamente;
- transformar cadastro em evidência confirmada.

11. Se a base estiver vazia ou sem entidades elegíveis,
a ação deve atacar a causa imediatamente anterior.

Exemplo:
Se não há profissionais qualificados,
prefira:
"Validar os profissionais já cadastrados."

Somente recomende nova prospecção se a base atual
não oferecer candidatos adequados.

12. Não recomende novo gasto, contratação ou ferramenta
antes de considerar os ativos e contatos já existentes.

13. Não transforme sugestão em obrigação.

14. Não repita como ação aquilo que a empresa
já concluiu ou executou.

15. A prioridade deve refletir impacto real:
crítica somente quando houver bloqueio imediato;
alta para ação importante;
média para melhoria;
baixa para ação opcional.
"""


POLITICA_LINGUAGEM_NATURAL_IA = """
LINGUAGEM PARA A DIREÇÃO:

Fale como assessor empresarial, não como sistema.

Prefira:
"Não há profissionais qualificados hoje."

Evite:
"A consulta retornou 0 registros com
status qualificado e flag disponível."

Prefira:
"A Amazônia Mix ainda está em qualificação."

Evite:
"A entidade possui status_fluxo qualificada."

Prefira:
"Não há fábrica homologada para essa decisão."

Evite:
"Quantidade elegível encontrada: 0."

A resposta deve parecer uma análise empresarial
natural, objetiva e segura.
"""

@app.route(
    "/api/admin/ia-empresarial/transcrever",
    methods=["POST"]
)
def transcrever_comando_ia_empresarial():

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

    if not openai_client:
        return jsonify({
            "success": False,
            "error": "OpenAI não configurada."
        }), 503

    arquivo = request.files.get("audio")

    if not arquivo or not arquivo.filename:
        return jsonify({
            "success": False,
            "error": "Áudio não recebido."
        }), 400

    try:

        transcricao = (
            openai_client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=(
                    arquivo.filename,
                    arquivo.stream,
                    arquivo.mimetype
                    or "audio/webm"
                ),
                language="pt",
                prompt=(
                    "Comando empresarial em português do Brasil. "
                    "Contexto: Maranhão Cordial, guaraná, gengibre, "
                    "cordial, bartender, bares, restaurantes, B2B, "
                    "Instagram, WhatsApp, e-mail, Facebook, TikTok, "
                    "LinkedIn, Pinterest, anúncios, campanhas, leads, "
                    "CRM, fábrica, produção e distribuição. "
                    "Preserve nomes próprios, números, valores em reais, "
                    "percentuais, datas e nomes de canais com precisão."
                )
            )
        )

        texto = str(
            getattr(
                transcricao,
                "text",
                ""
            )
            or ""
        ).strip()

        if not texto:
            return jsonify({
                "success": False,
                "error": "Não consegui compreender o áudio."
            }), 422

        return jsonify({
            "success": True,
            "texto": texto
        })

    except Exception as erro:

        print(
            "ERRO TRANSCRICAO IA EMPRESARIAL:",
            repr(erro)
        )

        return jsonify({
            "success": False,
            "error": "Não foi possível transcrever o áudio."
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

    # =================================================
    # MEMÓRIA EMPRESARIAL POR LINGUAGEM NATURAL
    # =================================================

    if detectar_comando_memoria_empresarial(pergunta):

        try:
            memoria_registrada = (
                registrar_memoria_natural_empresarial(
                    pergunta
                )
            )

            if memoria_registrada:
                return jsonify({
                    "success": True,
                    "agent": "maranhao-empresarial-v1",
                    "modo": "registro_memoria",
                    "resposta":
                        "Informação registrada na memória empresarial.",
                    "memoria_registrada": {
                        "id": str(
                            memoria_registrada["id"]
                        ),
                        "titulo":
                            memoria_registrada["titulo"],
                        "area":
                            memoria_registrada["area"],
                        "categoria":
                            memoria_registrada["categoria"],
                        "status":
                            memoria_registrada["status"],
                        "resumo":
                            memoria_registrada["resumo"],
                        "confiabilidade":
                            memoria_registrada[
                                "confiabilidade"
                            ]
                    }
                }), 201

        except Exception as erro_memoria:

            print(
                "ERRO MEMÓRIA EMPRESARIAL:",
                repr(erro_memoria)
            )

            return jsonify({
                "success": False,
                "modo": "registro_memoria",
                "error":
                    "Não foi possível registrar a informação."
            }), 500

    if not openai_client:
        return jsonify({
            "success": False,
            "error":
                "IA empresarial indisponível."
        }), 503

    try:

        # =============================================
        # CONTEXTO DINÂMICO — INSTAGRAM
        # =============================================
        contexto_instagram = ""

        if pergunta_requer_analytics_instagram(
            pergunta
        ):
            contexto_instagram = (
                montar_contexto_analytics_instagram()
            )

            print(
                "IA EMPRESARIAL: "
                "analytics Instagram consultado."
            )

        # =============================================
        # CONTEXTO DINÂMICO — CONVERSAS INSTAGRAM
        # =============================================
        contexto_conversas_instagram = ""

        if pergunta_requer_conversas_instagram(
            pergunta
        ):
            try:
                contexto_conversas_instagram = (
                    montar_contexto_conversas_instagram(
                        limite=30
                    )
                )

                print(
                    "IA EMPRESARIAL: "
                    "histórico de conversas Instagram consultado."
                )

            except Exception as erro_conversas_instagram:
                print(
                    "ERRO CONVERSAS INSTAGRAM:",
                    repr(erro_conversas_instagram)
                )

                contexto_conversas_instagram = (
                    "\n\n=== CONVERSAS INSTAGRAM ===\n"
                    "O histórico de conversas não pôde ser "
                    "consultado nesta execução. "
                    "Não invente mensagens ou respostas.\n"
                )

        # =============================================
        # CONTEXTO DINÂMICO — GOOGLE ANALYTICS 4
        # =============================================
        contexto_ga4 = ""

        if comando_pede_analytics(pergunta):
            try:
                contexto_ga4 = (
                    montar_contexto_analytics_ga4()
                )

                print(
                    "IA EMPRESARIAL: "
                    "Google Analytics 4 consultado."
                )

            except Exception as erro_ga4:
                print(
                    "ERRO ANALYTICS GA4:",
                    repr(erro_ga4)
                )

                contexto_ga4 = (
                    "\n\n=== GOOGLE ANALYTICS 4 ===\n"
                    "A consulta ao GA4 falhou nesta execução. "
                    "Não invente métricas do site.\n"
                )

        resumo = (
            obter_resumo_empresarial_postgres()
        )

        evidencias_ia = (
            carregar_evidencias_para_ia()
        )

        contexto_evidencias = (
            evidencias_ia["contexto"]
            or ""
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

        insights_ia = (
            carregar_insights_para_ia()
        )

        contexto_insights = (
            insights_ia["contexto"]
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

        profissionais_ia = (
            carregar_profissionais_para_ia()
        )

        contexto_profissionais = (
            profissionais_ia["contexto"]
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

        contexto_seletivo_ia = (
            montar_contexto_empresarial_seletivo(
                pergunta,

                contexto_documental=
                    contexto_documental,

                contexto_evidencias=
                    contexto_evidencias,

                contexto_decisoes=
                    contexto_decisoes,

                contexto_insights=
                    contexto_insights,

                contexto_acoes=
                    contexto_acoes,

                contexto_crm=
                    contexto_crm,

                contexto_fabricas=
                    contexto_fabricas,

                contexto_profissionais=
                    contexto_profissionais,

                contexto_fiscal=
                    contexto_fiscal,

                contexto_logistica=
                    contexto_logistica,

                contexto_contatos=
                    contexto_contatos,

                contexto_operacional=
                    contexto_operacional
            )
        )

        contexto_diagnostico = (
            contexto_seletivo_ia[
                "contexto"
            ]
        )

        travas_elegibilidade = (
            montar_travas_elegibilidade_ia(
                pergunta,

                fabricas=
                    fabricas_ia.get(
                        "fabricas",
                        []
                    ),

                profissionais=
                    profissionais_ia.get(
                        "profissionais",
                        []
                    )
            )
        )

        contexto_diagnostico = (
            contexto_diagnostico
            + travas_elegibilidade
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
                                "maxItems": 2,
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
                + POLITICA_OBJETIVO_SUPERIOR_EMPRESA
                + POLITICA_RACIOCINIO_ESTRATEGICO_IA
                + POLITICA_ECONOMICA_IA
                + POLITICA_EXPANSAO_OPORTUNIDADES_IA
                + POLITICA_PRIORIDADE_CONTEXTO_INTERNO
                + POLITICA_DIAGNOSTICO_CONCISO_IA
                + POLITICA_ACOES_SUGERIDAS_IA
                + POLITICA_LINGUAGEM_NATURAL_IA
                + carregar_feedback_para_ia()
                + carregar_objetivos_estrategicos_para_ia()
                + contexto_instagram
                + contexto_conversas_instagram
                + contexto_ga4
                + contexto_diagnostico +

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
                "Quando a pergunta pedir lista, inventário, comparação, evidências, ativos, documentos, "
                "fatos conhecidos ou itens existentes, responda todos os itens relevantes encontrados "
                "no contexto, de forma objetiva. Não reduza uma pergunta de inventário a apenas um resumo. "
                "Nesses casos, não é obrigatório usar o formato Prioridade/Por quê/Próximo passo. "
                "Quando a pergunta pedir prioridade, ordem de contato ou próximo passo, "
                "compare os contatos estratégicos disponíveis e escolha UMA pessoa primeiro. "
                "A resposta visível deve obrigatoriamente conter exatamente três blocos curtos: "
                "'Prioridade:', 'Por quê:' e 'Próximo passo:'. "
                "Em 'Prioridade:', informe a pessoa ou empresa escolhida. "
                "Em 'Por quê:', explique em uma frase o motivo principal da escolha. "
                "Em 'Próximo passo:', indique uma única ação concreta e executável. "
                "Não repita 'Próximo passo:' mais de uma vez. "
                "Não acrescente listas de dados ausentes, riscos ou contexto extra "
                "a menos que o usuário peça explicitamente. "
                "Antes de recomendar qualquer novo gasto, contratação ou ferramenta, "
                "verifique se os ativos existentes da empresa podem resolver a necessidade. "
                "Entre alternativas equivalentes, priorize menor gasto incremental e maior "
                "margem de contribuição ou geração de caixa. "
                "Não responda apenas com o nome do contato. "
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

        interpretada = (
            interpretar_saida_ia_empresarial(
                texto_bruto
            )
        )

        texto = interpretada[
            "resposta"
        ]

        acoes_sugeridas = interpretada[
            "acoes_sugeridas"
        ]

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
                    + POLITICA_OBJETIVO_SUPERIOR_EMPRESA
                    + POLITICA_RACIOCINIO_ESTRATEGICO_IA
                    + POLITICA_ECONOMICA_IA
                    + POLITICA_EXPANSAO_OPORTUNIDADES_IA
                    + POLITICA_PRIORIDADE_CONTEXTO_INTERNO
                    + POLITICA_DIAGNOSTICO_CONCISO_IA
                    + POLITICA_ACOES_SUGERIDAS_IA
                    + POLITICA_LINGUAGEM_NATURAL_IA
                    + carregar_feedback_para_ia()
                    + carregar_objetivos_estrategicos_para_ia()
                    + contexto_instagram
                    + contexto_conversas_instagram
                    + POLITICA_COMUNICACAO_EMPRESARIAL
                    + REGRA_MENSAGENS_ESTRATEGICAS
                    + contexto_diagnostico
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
                "evidencias_consultadas":
                    len(evidencias_ia["evidencias"]),
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
                "evidencias":
                    len(evidencias_ia["evidencias"]),
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
# CENTRAL DE COMANDO — IA EMPRESARIAL
# =====================================================

def garantir_tabelas_central_comando():

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ordens_empresariais (
                        id UUID PRIMARY KEY,
                        comando TEXT NOT NULL,
                        categoria VARCHAR(80),
                        canal VARCHAR(40),
                        destino TEXT,
                        payload JSONB,
                        prioridade VARCHAR(20)
                            NOT NULL DEFAULT 'media',
                        estado VARCHAR(40)
                            NOT NULL DEFAULT 'pendente',
                        requer_aprovacao BOOLEAN
                            NOT NULL DEFAULT TRUE,
                        aprovado_por VARCHAR(180),
                        aprovado_em TIMESTAMPTZ,
                        executado_em TIMESTAMPTZ,
                        resultado JSONB,
                        erro TEXT,
                        criado_por VARCHAR(180),
                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW(),
                        atualizado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS feedback_empresarial (
                        id UUID PRIMARY KEY,
                        entidade_tipo VARCHAR(80) NOT NULL,
                        entidade_id VARCHAR(220) NOT NULL,
                        avaliacao VARCHAR(40) NOT NULL,
                        resultado_negocio VARCHAR(80),
                        nota INTEGER,
                        comentario TEXT,
                        registrado_por VARCHAR(180),
                        criado_em TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_ordens_empresariais_estado
                    ON ordens_empresariais(estado)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_feedback_empresarial_entidade
                    ON feedback_empresarial(
                        entidade_tipo,
                        entidade_id
                    )
                """)

    finally:
        conn.close()


def instagram_config():

    token = (
        os.getenv("META_INSTAGRAM_ACCESS_TOKEN")
        or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        or ""
    ).strip()

    conta_id = (
        os.getenv("META_INSTAGRAM_ACCOUNT_ID")
        or os.getenv("INSTAGRAM_ACCOUNT_ID")
        or os.getenv("INSTAGRAM_USER_ID")
        or ""
    ).strip()

    return token, conta_id


def meta_get_instagram(caminho, params=None):

    token, _ = instagram_config()

    if not token:
        raise RuntimeError(
            "META_INSTAGRAM_ACCESS_TOKEN não configurado."
        )

    parametros = dict(params or {})
    parametros["access_token"] = token

    resposta = requests.get(
        "https://graph.instagram.com/v26.0/"
        + str(caminho).lstrip("/"),
        params=parametros,
        timeout=30
    )

    dados = resposta.json()

    if not resposta.ok:
        raise RuntimeError(
            "Meta Instagram: " + str(dados)
        )

    return dados



def montar_contexto_analytics_instagram():
    """
    Monta contexto executivo de Instagram para a IA.

    Regras:
    - identifica publicações de forma humana;
    - entrega métricas oficiais disponíveis;
    - não confunde maior volume de views com melhor anúncio;
    - não inventa métricas ausentes;
    - permite comparação estratégica entre conteúdos.
    """

    try:
        posts = listar_desempenho_posts_instagram(
            limite=25
        )

        demografia = (
            obter_demografia_instagram_genero()
        )

        if not posts:
            return (
                "\n\n=== INSTAGRAM ANALYTICS ===\n"
                "A consulta ao Instagram foi realizada, "
                "mas nenhuma publicação com métricas "
                "foi retornada.\n"
            )

        posts_ordenados = sorted(
            posts,
            key=lambda item: (
                item.get("insights", {})
                .get("views", 0)
                or 0
            ),
            reverse=True
        )

        linhas = [
            "",
            "",
            "=== INSTAGRAM ANALYTICS OFICIAL ===",
            (
                "Fonte: API oficial do Instagram. "
                f"Publicações retornadas: "
                f"{len(posts_ordenados)}."
            ),
            "",
            "PUBLICAÇÕES:",
        ]

        for indice, post in enumerate(
            posts_ordenados[:10],
            start=1
        ):
            insights = (
                post.get("insights") or {}
            )

            views = insights.get("views")
            reach = insights.get("reach")
            saved = insights.get("saved")
            shares = insights.get("shares")
            likes = post.get("like_count")
            comments = post.get(
                "comments_count"
            )

            caption = (
                post.get("caption")
                or "(sem legenda)"
            ).strip()

            if len(caption) > 120:
                caption = caption[:117] + "..."

            timestamp = (
                post.get("timestamp")
                or ""
            )

            data = (
                timestamp[:10]
                if timestamp
                else "data indisponível"
            )

            permalink = (
                post.get("permalink")
                or "link indisponível"
            )

            tipo = (
                post.get("media_product_type")
                or post.get("media_type")
                or "conteúdo"
            )

            linhas.extend([
                "",
                (
                    f"{indice}. {tipo} de {data}"
                ),
                f'Legenda: "{caption}"',
                (
                    "Métricas: "
                    f"views={views}; "
                    f"alcance={reach}; "
                    f"curtidas={likes}; "
                    f"comentários={comments}; "
                    f"salvamentos={saved}; "
                    f"compartilhamentos={shares}."
                ),
                f"Link: {permalink}",
            ])

            if (
                isinstance(reach, (int, float))
                and reach > 0
            ):
                interacoes = sum(
                    valor
                    for valor in [
                        likes,
                        comments,
                        saved,
                        shares
                    ]
                    if isinstance(
                        valor,
                        (int, float)
                    )
                )

                taxa = (
                    interacoes
                    / reach
                    * 100
                )

                linhas.append(
                    "Interações observáveis/"
                    f"alcance: {taxa:.2f}% "
                    "(indicador calculado; "
                    "não é métrica oficial da Meta)."
                )

        linhas.extend([
            "",
            "REGRAS DE INTERPRETAÇÃO:",
            (
                "- Maior número de visualizações "
                "NÃO significa automaticamente "
                "melhor publicação para anúncio."
            ),
            (
                "- Compare visualizações, alcance, "
                "salvamentos, compartilhamentos, "
                "curtidas e comentários."
            ),
            (
                "- Salvamentos e compartilhamentos "
                "podem indicar valor ou intenção "
                "diferentes de simples visualização."
            ),
            (
                "- Não recomende impulsionamento "
                "apenas porque um conteúdo teve "
                "mais views."
            ),
            (
                "- Antes de recomendar mídia paga, "
                "considere o objetivo: descoberta, "
                "engajamento, tráfego, lead ou venda."
            ),
            (
                "- Se não houver dados de cliques, "
                "conversão ou gasto de mídia, diga "
                "explicitamente que não é possível "
                "concluir qual publicação vende melhor."
            ),
            (
                "- Quando recomendar replicação, "
                "explique QUAL característica parece "
                "merecer teste: tema, música, estética, "
                "gancho, formato ou abordagem."
            ),
            (
                "- Identifique a publicação pela data, "
                "legenda e/ou link. Nunca responda "
                "apenas 'postagem 1'."
            ),
            (
                "- Não peça relatório manual de "
                "Instagram Insights quando estes dados "
                "já estiverem presentes neste contexto."
            ),
            (
                "- Não confunda curtidas exibidas "
                "publicamente com visualizações "
                "retornadas pelos Insights."
            ),
        ])

        # ---------------------------------------------
        # DEMOGRAFIA
        # ---------------------------------------------

        try:
            dados_demo = (
                demografia.get("dados", [])
                if isinstance(demografia, dict)
                else []
            )

            resultados_genero = []

            for item in dados_demo:
                total_value = (
                    item.get("total_value")
                    or {}
                )

                for breakdown in (
                    total_value.get(
                        "breakdowns",
                        []
                    )
                ):
                    if (
                        breakdown.get(
                            "dimension_keys"
                        )
                        == ["gender"]
                    ):
                        resultados_genero.extend(
                            breakdown.get(
                                "results",
                                []
                            )
                        )

            if resultados_genero:
                mapa = {}

                for resultado in (
                    resultados_genero
                ):
                    valores = (
                        resultado.get(
                            "dimension_values"
                        )
                        or []
                    )

                    if not valores:
                        continue

                    mapa[valores[0]] = (
                        resultado.get(
                            "value",
                            0
                        )
                        or 0
                    )

                feminino = mapa.get("F", 0)
                masculino = mapa.get("M", 0)
                indefinido = mapa.get("U", 0)

                total = (
                    feminino
                    + masculino
                    + indefinido
                )

                linhas.extend([
                    "",
                    "DEMOGRAFIA DE SEGUIDORES:",
                    (
                        f"Feminino: {feminino}; "
                        f"Masculino: {masculino}; "
                        f"Não classificado: "
                        f"{indefinido}."
                    ),
                ])

                if total > 0:
                    linhas.append(
                        "Distribuição calculada: "
                        f"F={feminino/total*100:.1f}%; "
                        f"M={masculino/total*100:.1f}%; "
                        f"U={indefinido/total*100:.1f}%."
                    )

        except Exception as erro_demo:
            print(
                "INSTAGRAM DEMOGRAFIA "
                "INDISPONIVEL:",
                erro_demo
            )

        linhas.extend([
            "",
            (
                "Use estes dados como contexto atual "
                "e factual. Não invente métricas que "
                "não estejam acima."
            ),
            "",
        ])

        return "\n".join(linhas)

    except Exception as erro:
        print(
            "ERRO CONTEXTO ANALYTICS INSTAGRAM:",
            erro
        )

        return (
            "\n\n=== INSTAGRAM ANALYTICS ===\n"
            "Consulta temporariamente indisponível. "
            "Não invente métricas nem conclusões "
            "sobre performance do Instagram.\n"
        )

def pergunta_requer_analytics_instagram(
    pergunta
):

    texto = str(
        pergunta or ""
    ).lower()

    termos = (
        "instagram",
        "post",
        "postagem",
        "reels",
        "reel",
        "story",
        "stories",
        "seguidores",
        "seguidor",
        "visualização",
        "visualizações",
        "visualizacoes",
        "alcance",
        "engajamento",
        "curtida",
        "marketing",
        "conteúdo",
        "conteudo",
        "demografia",
        "homens",
        "mulheres",
        "gênero",
        "genero"
    )

    return any(
        termo in texto
        for termo in termos
    )


def obter_demografia_instagram_genero():

    _, conta_id = instagram_config()

    if not conta_id:
        raise RuntimeError(
            "META_INSTAGRAM_ACCOUNT_ID não configurado."
        )

    try:
        dados = meta_get_instagram(
            f"{conta_id}/insights",
            {
                "metric":
                    "follower_demographics",
                "period":
                    "lifetime",
                "metric_type":
                    "total_value",
                "breakdown":
                    "gender",
                "timeframe":
                    "this_month"
            }
        )

        return {
            "success": True,
            "dados": dados.get("data", [])
        }

    except Exception as erro:

        return {
            "success": False,
            "erro": str(erro),
            "observacao":
                "A Meta pode não disponibilizar "
                "demografia quando não houver "
                "audiência/dados suficientes."
        }


def listar_desempenho_posts_instagram(
    limite=50
):

    _, conta_id = instagram_config()

    if not conta_id:
        raise RuntimeError(
            "META_INSTAGRAM_ACCOUNT_ID não configurado."
        )

    media = meta_get_instagram(
        f"{conta_id}/media",
        {
            "fields":
                "id,caption,media_type,"
                "media_product_type,permalink,"
                "timestamp,like_count,comments_count",
            "limit":
                limite
        }
    )

    resultados = []

    metricas_tentativa = [
        "views",
        "reach",
        "shares",
        "saved"
    ]

    for item in media.get("data", []):

        registro = dict(item)

        registro["insights"] = {}

        for metrica in metricas_tentativa:

            try:
                resp = meta_get_instagram(
                    f"{item['id']}/insights",
                    {
                        "metric":
                            metrica
                    }
                )

                valores = resp.get(
                    "data",
                    []
                )

                valor = None

                if valores:
                    primeiro = valores[0]

                    if "values" in primeiro:
                        lista_valores = (
                            primeiro.get("values")
                            or []
                        )

                        if lista_valores:
                            valor = (
                                lista_valores[-1]
                                .get("value")
                            )

                    elif "total_value" in primeiro:
                        valor = (
                            primeiro.get(
                                "total_value",
                                {}
                            ).get("value")
                        )

                registro[
                    "insights"
                ][metrica] = valor

            except Exception:
                registro[
                    "insights"
                ][metrica] = None

        resultados.append(
            registro
        )

    resultados.sort(
        key=lambda x: (
            x.get("insights", {})
            .get("views")
            or 0
        ),
        reverse=True
    )

    return resultados


def carregar_feedback_para_ia(
    limite=80
):

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT
                        entidade_tipo,
                        entidade_id,
                        avaliacao,
                        resultado_negocio,
                        nota,
                        comentario,
                        registrado_por,
                        criado_em
                    FROM feedback_empresarial
                    ORDER BY criado_em DESC
                    LIMIT %s
                """, (
                    limite,
                ))

                linhas = cur.fetchall()

        if not linhas:
            return (
                "\nFEEDBACK OPERACIONAL:\n"
                "Ainda não há feedback registrado.\n"
            )

        texto = [
            "\nFEEDBACK OPERACIONAL / CLOSED LOOP:"
        ]

        for f in linhas:

            texto.append(
                "- "
                + str(f.get("entidade_tipo"))
                + " "
                + str(f.get("entidade_id"))
                + " | avaliação="
                + str(f.get("avaliacao"))
                + " | resultado="
                + str(
                    f.get("resultado_negocio")
                    or "não informado"
                )
                + " | nota="
                + str(
                    f.get("nota")
                    if f.get("nota") is not None
                    else "não informada"
                )
                + " | comentário="
                + str(
                    f.get("comentario")
                    or "sem comentário"
                )
            )

        texto.append(
            "\nUse esse histórico para ajustar "
            "prioridades e recomendações futuras. "
            "Não trate correlação como causalidade."
        )

        return "\n".join(texto)

    finally:
        conn.close()


@app.route(
    "/api/admin/instagram/analytics",
    methods=["GET"]
)
def admin_instagram_analytics():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:

        posts = (
            listar_desempenho_posts_instagram()
        )

        genero = (
            obter_demografia_instagram_genero()
        )

        return jsonify({
            "success": True,
            "total_posts":
                len(posts),
            "posts":
                posts,
            "top_post":
                posts[0]
                if posts else None,
            "demografia_genero":
                genero
        }), 200

    except Exception as erro:

        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


@app.route(
    "/api/admin/feedback",
    methods=["POST"]
)
def admin_registrar_feedback():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    entidade_tipo = str(
        dados.get("entidade_tipo", "")
    ).strip()

    entidade_id = str(
        dados.get("entidade_id", "")
    ).strip()

    avaliacao = str(
        dados.get("avaliacao", "")
    ).strip().lower()

    if not entidade_tipo \
       or not entidade_id \
       or avaliacao not in {
           "positivo",
           "negativo",
           "neutro"
       }:

        return jsonify({
            "success": False,
            "error":
                "Feedback inválido."
        }), 400

    feedback_id = str(
        uuid.uuid4()
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO feedback_empresarial (
                        id,
                        entidade_tipo,
                        entidade_id,
                        avaliacao,
                        resultado_negocio,
                        nota,
                        comentario,
                        registrado_por
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """, (
                    feedback_id,
                    entidade_tipo,
                    entidade_id,
                    avaliacao,
                    dados.get(
                        "resultado_negocio"
                    ),
                    dados.get("nota"),
                    dados.get("comentario"),
                    dados.get(
                        "registrado_por",
                        "admin"
                    )
                ))

        return jsonify({
            "success": True,
            "feedback_id":
                feedback_id
        }), 201

    finally:
        conn.close()


@app.route(
    "/api/admin/ordens",
    methods=["POST"]
)
def admin_criar_ordem_empresarial():

    if not validar_admin_request():
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    comando = str(
        dados.get("comando", "")
    ).strip()

    if not comando:
        return jsonify({
            "success": False,
            "error": "Comando obrigatório."
        }), 400

    ordem_id = str(
        uuid.uuid4()
    )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO ordens_empresariais (
                        id,
                        comando,
                        categoria,
                        canal,
                        destino,
                        payload,
                        prioridade,
                        estado,
                        requer_aprovacao,
                        criado_por
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        'pendente',
                        TRUE,
                        %s
                    )
                """, (
                    ordem_id,
                    comando,
                    dados.get("categoria"),
                    dados.get("canal"),
                    dados.get("destino"),
                    json.dumps(
                        dados.get("payload") or {},
                        ensure_ascii=False
                    ),
                    dados.get(
                        "prioridade",
                        "media"
                    ),
                    dados.get(
                        "criado_por",
                        "admin"
                    )
                ))

        return jsonify({
            "success": True,
            "ordem_id":
                ordem_id,
            "estado":
                "pendente",
            "requer_aprovacao":
                True
        }), 201

    finally:
        conn.close()



# =====================================================
# INICIALIZAÇÃO
# =====================================================


# Cria as tabelas automaticamente quando o serviço inicia.
if DATABASE_URL:
    try:
        inicializar_banco()
        garantir_tabelas_central_comando()
        print("✓ BANCO DE LEADS INICIALIZADO")
        print("✓ CENTRAL DE COMANDO INICIALIZADA")
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

# =====================================================
# ADMIN — RELACIONAMENTOS B2B
# =====================================================

@app.route(
    "/api/admin/relacionamentos-b2b",
    methods=["GET", "POST"]
)
def admin_relacionamentos_b2b():

    if request.headers.get("X-Admin-Key") != ADMIN_KEY:
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:

        if request.method == "GET":

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    SELECT *
                    FROM relacionamentos_b2b
                    ORDER BY
                        nivel_relacionamento DESC,
                        ultimo_contato DESC NULLS LAST,
                        criado_em DESC
                """)

                registros = cur.fetchall()

            return jsonify({
                "success": True,
                "total": len(registros),
                "relacionamentos": registros
            }), 200

        dados = request.get_json(
            silent=True
        ) or {}

        nome = str(
            dados.get("nome") or ""
        ).strip()

        if not nome:
            return jsonify({
                "success": False,
                "error": "nome é obrigatório."
            }), 400

        registro_id = str(uuid.uuid4())

        with conn:
            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    INSERT INTO relacionamentos_b2b (
                        id,
                        nome,
                        empresa,
                        cargo_funcao,
                        segmento,
                        tipo_relacao,
                        telefone,
                        email,
                        instagram,
                        cidade,
                        estado,
                        status_relacionamento,
                        primeiro_contato,
                        ultimo_contato,
                        respondeu,
                        interesse_demonstrado,
                        pediu_informacoes,
                        conversa_tecnica,
                        amostra_solicitada,
                        amostra_enviada,
                        amostra_provada,
                        feedback_sensorial_recebido,
                        oportunidade_comercial,
                        compra_confirmada,
                        evento_relacionado,
                        potencial_validacao_sensorial,
                        potencial_networking,
                        potencial_eventos,
                        potencial_comercial,
                        nivel_relacionamento,
                        proximo_passo,
                        evidencia,
                        fonte_dados,
                        observacoes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING *
                """, (
                    registro_id,
                    nome,
                    dados.get("empresa"),
                    dados.get("cargo_funcao"),
                    dados.get("segmento"),
                    dados.get("tipo_relacao"),
                    dados.get("telefone"),
                    dados.get("email"),
                    dados.get("instagram"),
                    dados.get("cidade"),
                    dados.get("estado"),
                    dados.get(
                        "status_relacionamento",
                        "prospectado"
                    ),
                    dados.get("primeiro_contato"),
                    dados.get("ultimo_contato"),
                    dados.get("respondeu"),
                    dados.get("interesse_demonstrado"),
                    dados.get("pediu_informacoes"),
                    dados.get("conversa_tecnica"),
                    dados.get("amostra_solicitada"),
                    dados.get("amostra_enviada"),
                    dados.get("amostra_provada"),
                    dados.get(
                        "feedback_sensorial_recebido"
                    ),
                    dados.get("oportunidade_comercial"),
                    dados.get("compra_confirmada"),
                    dados.get("evento_relacionado"),
                    dados.get(
                        "potencial_validacao_sensorial"
                    ),
                    dados.get("potencial_networking"),
                    dados.get("potencial_eventos"),
                    dados.get("potencial_comercial"),
                    dados.get("nivel_relacionamento", 0),
                    dados.get("proximo_passo"),
                    dados.get("evidencia"),
                    dados.get("fonte_dados"),
                    dados.get("observacoes")
                ))

                registro = cur.fetchone()

        return jsonify({
            "success": True,
            "relacionamento": registro
        }), 201

    finally:
        conn.close()


# ============================================================
# ORQUESTRADOR EMPRESARIAL
# IA → OBJETIVOS → ORDENS → EXECUÇÃO → FEEDBACK
# ============================================================

def garantir_tabelas_orquestrador_empresarial():
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS objetivos_estrategicos (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        titulo TEXT NOT NULL,
                        descricao TEXT NOT NULL,
                        area TEXT NOT NULL DEFAULT 'estrategia',
                        prioridade TEXT NOT NULL DEFAULT 'media',
                        status TEXT NOT NULL DEFAULT 'ativo',
                        origem TEXT NOT NULL DEFAULT 'direcao',
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        encerrado_em TIMESTAMPTZ,
                        substitui_objetivo_id UUID,
                        observacoes TEXT
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_objetivos_estrategicos_status
                    ON objetivos_estrategicos(status)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS comandos_empresariais (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        comando_original TEXT NOT NULL,
                        origem TEXT NOT NULL DEFAULT 'texto',
                        intencao TEXT,
                        canal TEXT,
                        destinatario TEXT,
                        conteudo TEXT,
                        requer_aprovacao BOOLEAN NOT NULL DEFAULT TRUE,
                        status TEXT NOT NULL DEFAULT 'interpretado',
                        resultado TEXT,
                        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        executado_em TIMESTAMPTZ
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_comandos_empresariais_status
                    ON comandos_empresariais(status)
                """)

        print("✓ ORQUESTRADOR EMPRESARIAL INICIALIZADO")

    finally:
        conn.close()


def carregar_objetivos_estrategicos_para_ia():
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    criado_em
                FROM objetivos_estrategicos
                WHERE status = 'ativo'
                ORDER BY
                    CASE prioridade
                        WHEN 'critica' THEN 1
                        WHEN 'alta' THEN 2
                        WHEN 'media' THEN 3
                        ELSE 4
                    END,
                    criado_em DESC
            """)

            linhas = cur.fetchall()

        if not linhas:
            return (
                "\n\n=== OBJETIVOS ESTRATÉGICOS ATIVOS ===\n"
                "Nenhum objetivo estratégico formal ativo.\n"
            )

        texto = [
            "",
            "",
            "=== OBJETIVOS ESTRATÉGICOS ATIVOS ==="
        ]

        for linha in linhas:
            texto.append(
                f"- ID: {linha[0]} | "
                f"{linha[1]} | "
                f"área={linha[3]} | "
                f"prioridade={linha[4]} | "
                f"{linha[2]}"
            )

        texto.extend([
            "",
            "Use estes objetivos para priorizar recomendações.",
            "Não altere objetivos estratégicos sem comando explícito da direção.",
            ""
        ])

        return "\n".join(texto)

    finally:
        conn.close()


def registrar_objetivo_estrategico(
    titulo,
    descricao,
    area="estrategia",
    prioridade="media",
    substitui_objetivo_id=None
):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                if substitui_objetivo_id:
                    cur.execute("""
                        UPDATE objetivos_estrategicos
                        SET
                            status = 'substituido',
                            encerrado_em = NOW()
                        WHERE id = %s
                    """, (substitui_objetivo_id,))

                cur.execute("""
                    INSERT INTO objetivos_estrategicos (
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        origem,
                        substitui_objetivo_id
                    )
                    VALUES (
                        %s, %s, %s, %s, 'direcao', %s
                    )
                    RETURNING id
                """, (
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    substitui_objetivo_id
                ))

                objetivo_id = cur.fetchone()[0]

        return str(objetivo_id)

    finally:
        conn.close()


def interpretar_comando_empresarial(comando):
    if not openai_client:
        raise RuntimeError("OpenAI indisponível.")

    resposta = openai_client.responses.create(
        model="gpt-5-mini",

        text={
            "format": {
                "type": "json_schema",
                "name": "comando_empresarial",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {

                        "intencao": {
                            "type": "string",
                            "enum": [
                                "consultar",
                                "enviar_mensagem",
                                "responder_mensagem",
                                "registrar_objetivo",
                                "alterar_objetivo",
                                "registrar_informacao",
                                "analisar",
                                "outra"
                            ]
                        },

                        "canal": {
                            "type": "string",
                            "enum": [
                                "instagram",
                                "whatsapp",
                                "email",
                                "interno",
                                "nenhum"
                            ]
                        },

                        "destinatario": {
                            "type": "string"
                        },

                        "conteudo": {
                            "type": "string"
                        },

                        "area": {
                            "type": "string",
                            "enum": [
                                "comercial",
                                "marketing",
                                "financeiro",
                                "operacional",
                                "produto",
                                "regulatorio",
                                "estrategia",
                                "tecnologia"
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

                        "requer_aprovacao": {
                            "type": "boolean"
                        },

                        "justificativa": {
                            "type": "string"
                        }
                    },

                    "required": [
                        "intencao",
                        "canal",
                        "destinatario",
                        "conteudo",
                        "area",
                        "prioridade",
                        "requer_aprovacao",
                        "justificativa"
                    ],

                    "additionalProperties": False
                }
            }
        },

        instructions=(
            "Você interpreta comandos da DIREÇÃO da Maranhão Cordial. "
            "Não execute nada; apenas transforme o comando em estrutura. "

            "O comando recebido nesta rota vem diretamente da DIREÇÃO. "

            "Quando a direção disser explicitamente para registrar, alterar, "
            "definir ou substituir um objetivo estratégico, considere o próprio "
            "comando como autorização. Nesse caso requer_aprovacao=false. "

            "Consultas, análises e registros internos também não requerem aprovação. "

            "Para comunicação externa, diferencie PREPARAR de ENVIAR. "
            "Se a direção pedir apenas para escrever, preparar ou sugerir uma "
            "mensagem, não envie e mantenha a ação como preparação. "

            "Se houver uma ação externa ainda não explicitamente autorizada, "
            "como resposta sugerida pelo sistema, e-mail sugerido pela IA ou "
            "contato proativo recomendado pela IA, requer_aprovacao=true. "

            "Preço, desconto, contrato, pagamento, obrigação financeira e "
            "aceitação de negociação nunca devem ser inferidos automaticamente. "

            "Nunca invente destinatários, números, preços ou conteúdo."
        ),

        input=comando,

        reasoning={
            "effort": "low"
        },

        max_output_tokens=800
    )

    import json

    return json.loads(
        resposta.output_text
    )



def comando_pede_analytics(comando):
    texto = (comando or "").lower()

    termos = [
        "analytics",
        "ga4",
        "google analytics",
        "tráfego",
        "trafego",
        "site",
        "visitantes",
        "visitas",
        "sessões",
        "sessoes",
        "usuários do site",
        "usuarios do site",
        "página mais acessada",
        "pagina mais acessada",
        "páginas mais acessadas",
        "paginas mais acessadas",
        "origem do tráfego",
        "origem do trafego",
        "desempenho digital",
    ]

    return any(termo in texto for termo in termos)


def montar_contexto_analytics_ga4():
    import json

    from analytics_service import (
        resumo_geral,
        origens_trafego,
        paginas_mais_acessadas,
    )

    dados = {
        "resumo_ultimos_7_dias": resumo_geral(7),
        "origens_trafego_ultimos_30_dias": origens_trafego(30),
        "paginas_mais_acessadas_ultimos_30_dias": paginas_mais_acessadas(30),
    }

    return (
        "\n\n=== GOOGLE ANALYTICS 4 — DADOS REAIS DO SITE ===\n"
        "Os dados abaixo foram consultados diretamente no GA4 nesta execução.\n"
        "Não invente métricas que não estejam presentes.\n"
        "A taxa_engajamento é retornada pelo GA4 como proporção entre 0 e 1.\n"
        "Não há métrica de conversão neste conjunto de dados; não invente taxa de conversão.\n\n"
        + json.dumps(
            dados,
            ensure_ascii=False,
            indent=2,
        )
        + "\n=== FIM DOS DADOS GA4 ===\n"
    )


def analisar_google_analytics_empresarial(comando):
    import json

    from analytics_service import (
        resumo_geral,
        origens_trafego,
        paginas_mais_acessadas,
    )

    if not openai_client:
        raise RuntimeError("OpenAI indisponível.")

    dados_analytics = {
        "resumo_7_dias": resumo_geral(7),
        "origens_30_dias": origens_trafego(30),
        "paginas_30_dias": paginas_mais_acessadas(30),
    }

    contexto = json.dumps(
        dados_analytics,
        ensure_ascii=False,
        indent=2,
    )

    resposta = openai_client.responses.create(
        model="gpt-5-mini",
        instructions=(
            "Você é a inteligência empresarial da Maranhão Cordial. "
            "Responda à DIREÇÃO usando os dados reais do Google Analytics "
            "fornecidos no contexto. "
            "Nunca invente números, conversões, causas ou conclusões que "
            "os dados não sustentem. "
            "Diferencie claramente dado observado de interpretação. "
            "Quando não houver evidência suficiente, diga isso. "
            "Seja objetivo, empresarial e indique ações práticas quando "
            "forem pertinentes."
        ),
        input=(
            f"PERGUNTA DA DIREÇÃO:\n{comando}\n\n"
            f"DADOS REAIS DO GOOGLE ANALYTICS:\n{contexto}"
        ),
        reasoning={
            "effort": "low"
        },
        max_output_tokens=1000,
    )

    return {
        "resposta": resposta.output_text,
        "dados": dados_analytics,
    }


def registrar_comando_empresarial(
    comando_original,
    interpretacao,
    origem="texto"
):
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO comandos_empresariais (
                        comando_original,
                        origem,
                        intencao,
                        canal,
                        destinatario,
                        conteudo,
                        requer_aprovacao,
                        status
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    comando_original,
                    origem,
                    interpretacao["intencao"],
                    interpretacao["canal"],
                    interpretacao["destinatario"],
                    interpretacao["conteudo"],
                    interpretacao["requer_aprovacao"],
                    (
                        "aguardando_aprovacao"
                        if interpretacao["requer_aprovacao"]
                        else "pronta_execucao"
                    )
                ))

                comando_id = cur.fetchone()[0]

        return str(comando_id)

    finally:
        conn.close()


@app.route(
    "/api/admin/comando-empresarial",
    methods=["POST"]
)
def comando_empresarial():

    chave = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    dados = request.get_json(
        silent=True
    ) or {}

    comando = (
        dados.get("comando")
        or ""
    ).strip()

    origem = (
        dados.get("origem")
        or "texto"
    ).strip()

    if not comando:
        return jsonify({
            "success": False,
            "error": "Comando vazio."
        }), 400

    try:
        interpretacao = (
            interpretar_comando_empresarial(
                comando
            )
        )

        # ------------------------------------------
        # CONSULTA GOOGLE ANALYTICS / GA4
        # ------------------------------------------

        if (
            interpretacao["intencao"] in [
                "consultar",
                "analisar"
            ]
            and comando_pede_analytics(comando)
        ):
            resultado_analytics = (
                analisar_google_analytics_empresarial(
                    comando
                )
            )

            comando_id = (
                registrar_comando_empresarial(
                    comando,
                    interpretacao,
                    origem
                )
            )

            return jsonify({
                "success": True,
                "tipo": "google_analytics",
                "comando_id": comando_id,
                "resposta": resultado_analytics["resposta"],
                "dados_analytics": resultado_analytics["dados"],
                "interpretacao": interpretacao
            }), 200

        # ------------------------------------------
        # ALTERAÇÃO / CRIAÇÃO DE OBJETIVO
        # ------------------------------------------

        if interpretacao["intencao"] in [
            "registrar_objetivo",
            "alterar_objetivo"
        ]:
            objetivo_id = (
                registrar_objetivo_estrategico(
                    titulo=comando[:140],
                    descricao=(
                        interpretacao["conteudo"]
                        or comando
                    ),
                    area=interpretacao["area"],
                    prioridade=(
                        interpretacao[
                            "prioridade"
                        ]
                    )
                )
            )

            comando_id = (
                registrar_comando_empresarial(
                    comando,
                    interpretacao,
                    origem
                )
            )

            return jsonify({
                "success": True,
                "tipo": "objetivo_estrategico",
                "objetivo_id": objetivo_id,
                "comando_id": comando_id,
                "interpretacao": interpretacao
            })

        comando_id = (
            registrar_comando_empresarial(
                comando,
                interpretacao,
                origem
            )
        )

        acao_id = criar_acao_a_partir_de_comando(
            comando_id,
            interpretacao
        )

        return jsonify({
            "success": True,
            "comando_id": comando_id,
            "acao_id": acao_id,
            "aguardando_aprovacao": bool(acao_id),
            "interpretacao": interpretacao
        })

    except Exception as erro:
        print(
            "ERRO COMANDO EMPRESARIAL:",
            erro
        )

        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


@app.route(
    "/api/admin/objetivos-estrategicos",
    methods=["GET"]
)
def listar_objetivos_estrategicos():

    chave = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    status,
                    origem,
                    criado_em,
                    encerrado_em
                FROM objetivos_estrategicos
                ORDER BY criado_em DESC
                LIMIT 100
            """)

            colunas = [
                d[0]
                for d in cur.description
            ]

            dados = [
                dict(zip(colunas, linha))
                for linha in cur.fetchall()
            ]

        return jsonify({
            "success": True,
            "objetivos": dados
        })

    finally:
        conn.close()


try:
    garantir_tabelas_orquestrador_empresarial()
except Exception as erro:
    print(
        "ERRO AO INICIALIZAR ORQUESTRADOR:",
        erro
    )



# ============================================================
# FILA UNIVERSAL DE AÇÕES DA IA EMPRESARIAL
# ============================================================

def garantir_tabela_acoes_empresariais():
    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS
                    acoes_empresariais (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

                        comando_id UUID,

                        tipo TEXT NOT NULL,
                        canal TEXT NOT NULL,

                        destinatario TEXT,
                        conteudo TEXT NOT NULL,

                        justificativa TEXT,

                        status TEXT NOT NULL
                            DEFAULT 'aguardando_aprovacao',

                        prioridade TEXT NOT NULL
                            DEFAULT 'media',

                        criado_em TIMESTAMPTZ NOT NULL
                            DEFAULT NOW(),

                        aprovado_em TIMESTAMPTZ,
                        recusado_em TIMESTAMPTZ,
                        executado_em TIMESTAMPTZ,

                        resultado TEXT,
                        erro TEXT
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_acoes_empresariais_status
                    ON acoes_empresariais(status)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS
                    idx_acoes_empresariais_canal
                    ON acoes_empresariais(canal)
                """)

        print(
            "✓ FILA UNIVERSAL DE AÇÕES INICIALIZADA"
        )

    finally:
        conn.close()


def criar_acao_empresarial(
    tipo,
    canal,
    conteudo,
    destinatario="",
    justificativa="",
    prioridade="media",
    comando_id=None,
    status="aguardando_aprovacao"
):
    """
    Cria ação usando a estrutura histórica de acoes_empresariais
    e os campos novos do orquestrador.
    """

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                titulo = (
                    f"{tipo.replace('_', ' ').title()} "
                    f"via {canal.title()}"
                )

                descricao = conteudo

                area = (
                    "marketing"
                    if canal == "instagram"
                    else "comercial"
                )

                modo_execucao = (
                    "requer_aprovacao"
                    if status == "aguardando_aprovacao"
                    else "manual"
                )

                estado_execucao = "nao_iniciada"

                executor = canal

                tipo_execucao = tipo

                cur.execute("""
                    INSERT INTO acoes_empresariais (
                        titulo,
                        descricao,
                        area,
                        prioridade,
                        status,

                        modo_execucao,
                        estado_execucao,
                        executor,
                        tentativas_execucao,
                        tipo_execucao,

                        comando_id,
                        tipo,
                        canal,
                        destinatario,
                        conteudo,
                        justificativa
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, 0, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    titulo,
                    descricao,
                    area,
                    prioridade,
                    status,

                    modo_execucao,
                    estado_execucao,
                    executor,
                    tipo_execucao,

                    comando_id,
                    tipo,
                    canal,
                    destinatario,
                    conteudo,
                    justificativa
                ))

                acao_id = cur.fetchone()[0]

        return str(acao_id)

    finally:
        conn.close()


def listar_acoes_empresariais(
    status="aguardando_aprovacao"
):
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    comando_id,
                    tipo,
                    canal,
                    destinatario,
                    conteudo,
                    justificativa,
                    status,
                    prioridade,
                    criado_em,
                    aprovado_em,
                    executado_em,
                    resultado,
                    erro
                FROM acoes_empresariais
                WHERE
                    (%s = 'todas' OR status = %s)
                ORDER BY
                    CASE prioridade
                        WHEN 'critica' THEN 1
                        WHEN 'alta' THEN 2
                        WHEN 'media' THEN 3
                        ELSE 4
                    END,
                    criado_em DESC
                LIMIT 100
            """, (
                status,
                status
            ))

            colunas = [
                d[0]
                for d in cur.description
            ]

            return [
                dict(zip(colunas, linha))
                for linha in cur.fetchall()
            ]

    finally:
        conn.close()


def obter_acao_empresarial(acao_id):
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    comando_id,
                    tipo,
                    canal,
                    destinatario,
                    conteudo,
                    justificativa,
                    status,
                    prioridade,
                    criado_em,
                    aprovado_em,
                    recusado_em,
                    executado_em,
                    resultado,
                    erro
                FROM acoes_empresariais
                WHERE id = %s
            """, (acao_id,))

            linha = cur.fetchone()

            if not linha:
                return None

            colunas = [
                d[0]
                for d in cur.description
            ]

            return dict(
                zip(colunas, linha)
            )

    finally:
        conn.close()


def atualizar_status_acao_empresarial(
    acao_id,
    status
):
    permitidos = {
        "aguardando_aprovacao",
        "aprovada",
        "recusada",
        "executando",
        "executada",
        "erro"
    }

    if status not in permitidos:
        raise ValueError(
            "Status de ação inválido."
        )

    conn = get_db_connection()

    try:
        with conn:
            with conn.cursor() as cur:

                if status == "aprovada":
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            status = %s,
                            aprovado_em = NOW()
                        WHERE id = %s
                    """, (
                        status,
                        acao_id
                    ))

                elif status == "recusada":
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            status = %s,
                            recusado_em = NOW()
                        WHERE id = %s
                    """, (
                        status,
                        acao_id
                    ))

                else:
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET status = %s
                        WHERE id = %s
                    """, (
                        status,
                        acao_id
                    ))

                if cur.rowcount == 0:
                    raise ValueError(
                        "Ação não encontrada."
                    )

    finally:
        conn.close()


# ------------------------------------------------------------
# CONVERTE COMANDO EXTERNO EM AÇÃO PENDENTE
# ------------------------------------------------------------

def criar_acao_a_partir_de_comando(
    comando_id,
    interpretacao
):
    intencao = interpretacao.get(
        "intencao"
    )

    canal = interpretacao.get(
        "canal"
    )

    if intencao not in {
        "enviar_mensagem",
        "responder_mensagem"
    }:
        return None

    if canal not in {
        "instagram",
        "whatsapp",
        "email"
    }:
        return None

    return criar_acao_empresarial(
        comando_id=comando_id,
        tipo=intencao,
        canal=canal,
        destinatario=(
            interpretacao.get(
                "destinatario"
            )
            or ""
        ),
        conteudo=(
            interpretacao.get(
                "conteudo"
            )
            or ""
        ),
        justificativa=(
            interpretacao.get(
                "justificativa"
            )
            or ""
        ),
        prioridade=(
            interpretacao.get(
                "prioridade"
            )
            or "media"
        ),
        status="aguardando_aprovacao"
    )


# ------------------------------------------------------------
# API — LISTAR AÇÕES
# ------------------------------------------------------------

@app.route(
    "/api/admin/acoes-empresariais",
    methods=["GET"]
)
def api_listar_acoes_empresariais():

    chave = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    status = (
        request.args.get("status")
        or "aguardando_aprovacao"
    )

    try:
        acoes = (
            listar_acoes_empresariais(
                status=status
            )
        )

        return jsonify({
            "success": True,
            "total": len(acoes),
            "acoes": acoes
        })

    except Exception as erro:
        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


# ------------------------------------------------------------
# API — APROVAR
# Ainda NÃO envia externamente.
# ------------------------------------------------------------

@app.route(
    "/api/admin/acoes-empresariais/<acao_id>/aprovar",
    methods=["POST"]
)
def api_aprovar_acao_empresarial(acao_id):

    chave = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        acao = obter_acao_empresarial(
            acao_id
        )

        if not acao:
            return jsonify({
                "success": False,
                "error": "Ação não encontrada."
            }), 404

        if acao["status"] != (
            "aguardando_aprovacao"
        ):
            return jsonify({
                "success": False,
                "error": (
                    "Ação não está aguardando "
                    "aprovação."
                )
            }), 409

        conn = get_db_connection()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE acoes_empresariais
                        SET
                            status = 'aprovada',
                            aprovado_em = NOW(),
                            estado_execucao = 'autorizada',
                            autorizado_em = NOW(),
                            autorizado_por = 'direcao',
                            atualizado_em = NOW()
                        WHERE
                            id = %s
                            AND status = 'aguardando_aprovacao'
                    """, (
                        acao_id,
                    ))

                    if cur.rowcount != 1:
                        raise ValueError(
                            "Ação não pôde ser autorizada."
                        )

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "acao_id": acao_id,
            "status": "aprovada",
            "executada": False,
            "mensagem": (
                "Ação aprovada. "
                "Executor externo ainda "
                "não foi acionado."
            )
        })

    except Exception as erro:
        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


# ------------------------------------------------------------
# API — RECUSAR
# ------------------------------------------------------------

@app.route(
    "/api/admin/acoes-empresariais/<acao_id>/recusar",
    methods=["POST"]
)
def api_recusar_acao_empresarial(acao_id):

    chave = request.headers.get(
        "X-Admin-Key"
    )

    if (
        not ADMIN_API_KEY
        or chave != ADMIN_API_KEY
    ):
        return jsonify({
            "success": False,
            "error": "Não autorizado."
        }), 401

    try:
        acao = obter_acao_empresarial(
            acao_id
        )

        if not acao:
            return jsonify({
                "success": False,
                "error": "Ação não encontrada."
            }), 404

        if acao["status"] != (
            "aguardando_aprovacao"
        ):
            return jsonify({
                "success": False,
                "error": (
                    "Ação não está aguardando "
                    "aprovação."
                )
            }), 409

        atualizar_status_acao_empresarial(
            acao_id,
            "recusada"
        )

        return jsonify({
            "success": True,
            "acao_id": acao_id,
            "status": "recusada"
        })

    except Exception as erro:
        return jsonify({
            "success": False,
            "error": str(erro)
        }), 500


try:
    garantir_tabela_acoes_empresariais()
except Exception as erro:
    print(
        "ERRO AO INICIALIZAR FILA UNIVERSAL:",
        erro
    )

