import os
from pathlib import Path

import requests


def _json_resposta(resposta):
    try:
        return resposta.json()
    except Exception:
        return {
            "texto": resposta.text[:4000]
        }


# =====================================================
# X
# =====================================================

def publicar_x(texto):
    token = (
        os.getenv("X_ACCESS_TOKEN")
        or os.getenv("TWITTER_ACCESS_TOKEN")
    )

    texto = str(texto or "").strip()

    if not token:
        return {
            "success": False,
            "erro":
                "X_ACCESS_TOKEN não configurado."
        }

    if not texto:
        return {
            "success": False,
            "erro": "Conteúdo para X ausente."
        }

    try:
        resposta = requests.post(
            "https://api.x.com/2/tweets",
            headers={
                "Authorization":
                    "Bearer " + token,
                "Content-Type":
                    "application/json"
            },
            json={
                "text": texto
            },
            timeout=20
        )

        dados = _json_resposta(resposta)
        post_id = ""

        if isinstance(dados, dict):
            data = dados.get("data") or {}

            if isinstance(data, dict):
                post_id = str(
                    data.get("id") or ""
                ).strip()

        return {
            "success": bool(
                200 <= resposta.status_code < 300
                and post_id
            ),
            "status_code":
                resposta.status_code,
            "post_id": post_id or None,
            "meta": dados
        }

    except Exception as erro:
        return {
            "success": False,
            "erro": str(erro)
        }


# =====================================================
# LINKEDIN
# =====================================================

def publicar_linkedin(texto):
    token = os.getenv(
        "LINKEDIN_ACCESS_TOKEN"
    )

    organizacao = os.getenv(
        "LINKEDIN_ORGANIZATION_ID"
    )

    versao = os.getenv(
        "LINKEDIN_VERSION",
        "202605"
    )

    texto = str(texto or "").strip()

    if not token:
        return {
            "success": False,
            "erro":
                "LINKEDIN_ACCESS_TOKEN "
                "não configurado."
        }

    if not organizacao:
        return {
            "success": False,
            "erro":
                "LINKEDIN_ORGANIZATION_ID "
                "não configurado."
        }

    if not texto:
        return {
            "success": False,
            "erro":
                "Conteúdo para LinkedIn ausente."
        }

    autor = str(organizacao).strip()

    if not autor.startswith(
        "urn:li:organization:"
    ):
        autor = (
            "urn:li:organization:"
            + autor
        )

    payload = {
        "author": autor,
        "commentary": texto,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution":
                "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels":
                []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor":
            False
    }

    try:
        resposta = requests.post(
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization":
                    "Bearer " + token,
                "X-Restli-Protocol-Version":
                    "2.0.0",
                "Linkedin-Version":
                    versao,
                "Content-Type":
                    "application/json"
            },
            json=payload,
            timeout=20
        )

        dados = _json_resposta(resposta)

        post_id = str(
            resposta.headers.get(
                "x-restli-id"
            )
            or ""
        ).strip()

        return {
            "success": bool(
                200 <= resposta.status_code < 300
                and post_id
            ),
            "status_code":
                resposta.status_code,
            "post_id": post_id or None,
            "meta": dados
        }

    except Exception as erro:
        return {
            "success": False,
            "erro": str(erro)
        }


# =====================================================
# PINTEREST
# =====================================================

def publicar_pinterest(
    titulo,
    descricao,
    imagem_url,
    link=None,
    board_id=None
):
    token = os.getenv(
        "PINTEREST_ACCESS_TOKEN"
    )

    board = (
        str(board_id or "").strip()
        or str(
            os.getenv(
                "PINTEREST_BOARD_ID"
            )
            or ""
        ).strip()
    )

    titulo = str(
        titulo or ""
    ).strip()

    descricao = str(
        descricao or ""
    ).strip()

    imagem_url = str(
        imagem_url or ""
    ).strip()

    link = str(
        link or ""
    ).strip()

    if not token:
        return {
            "success": False,
            "erro":
                "PINTEREST_ACCESS_TOKEN "
                "não configurado."
        }

    if not board:
        return {
            "success": False,
            "erro":
                "PINTEREST_BOARD_ID "
                "não configurado."
        }

    if not imagem_url.startswith(
        ("http://", "https://")
    ):
        return {
            "success": False,
            "erro":
                "Pinterest exige "
                "imagem_url pública válida."
        }

    payload = {
        "board_id": board,
        "title": titulo,
        "description": descricao,
        "media_source": {
            "source_type":
                "image_url",
            "url":
                imagem_url
        }
    }

    if link:
        payload["link"] = link

    try:
        resposta = requests.post(
            "https://api.pinterest.com/v5/pins",
            headers={
                "Authorization":
                    "Bearer " + token,
                "Content-Type":
                    "application/json"
            },
            json=payload,
            timeout=30
        )

        dados = _json_resposta(resposta)
        pin_id = ""

        if isinstance(dados, dict):
            pin_id = str(
                dados.get("id") or ""
            ).strip()

        return {
            "success": bool(
                200 <= resposta.status_code < 300
                and pin_id
            ),
            "status_code":
                resposta.status_code,
            "post_id":
                pin_id or None,
            "meta": dados
        }

    except Exception as erro:
        return {
            "success": False,
            "erro": str(erro)
        }


# =====================================================
# YOUTUBE
# =====================================================

def publicar_youtube(
    arquivo_video,
    titulo,
    descricao="",
    privacidade="private"
):
    token = os.getenv(
        "YOUTUBE_ACCESS_TOKEN"
    )

    caminho = Path(
        str(
            arquivo_video or ""
        )
    ).expanduser()

    titulo = str(
        titulo or ""
    ).strip()

    descricao = str(
        descricao or ""
    ).strip()

    privacidade = str(
        privacidade or "private"
    ).strip().lower()

    if not token:
        return {
            "success": False,
            "erro":
                "YOUTUBE_ACCESS_TOKEN "
                "não configurado."
        }

    if not titulo:
        return {
            "success": False,
            "erro":
                "Título do vídeo ausente."
        }

    if not caminho.is_file():
        return {
            "success": False,
            "erro":
                "Arquivo de vídeo não "
                "encontrado no servidor."
        }

    if privacidade not in {
        "private",
        "unlisted",
        "public"
    }:
        privacidade = "private"

    try:
        from google.oauth2.credentials import (
            Credentials
        )

        from googleapiclient.discovery import (
            build
        )

        from googleapiclient.http import (
            MediaFileUpload
        )

        credenciais = Credentials(
            token=token
        )

        youtube = build(
            "youtube",
            "v3",
            credentials=credenciais,
            cache_discovery=False
        )

        corpo = {
            "snippet": {
                "title": titulo,
                "description":
                    descricao,
                "categoryId": "22"
            },
            "status": {
                "privacyStatus":
                    privacidade
            }
        }

        requisicao = (
            youtube
            .videos()
            .insert(
                part="snippet,status",
                body=corpo,
                media_body=MediaFileUpload(
                    str(caminho),
                    resumable=True
                )
            )
        )

        resposta = requisicao.execute()

        video_id = str(
            (resposta or {}).get(
                "id"
            )
            or ""
        ).strip()

        return {
            "success":
                bool(video_id),
            "status_code":
                200 if video_id else None,
            "post_id":
                video_id or None,
            "meta":
                resposta
        }

    except Exception as erro:
        return {
            "success": False,
            "erro": str(erro)
        }


# =====================================================
# DESPACHANTE CENTRAL
# =====================================================

def executar_publicacao_canal(
    canal,
    conteudo,
    **dados
):
    """
    Adaptador único.

    Não decide publicar.
    Apenas executa uma publicação que já tenha
    passado pelo mecanismo de autorização.
    """

    canal = str(
        canal or ""
    ).strip().lower()

    if canal == "x":
        return publicar_x(
            conteudo
        )

    if canal == "linkedin":
        return publicar_linkedin(
            conteudo
        )

    if canal == "pinterest":
        return publicar_pinterest(
            titulo=dados.get("titulo"),
            descricao=(
                dados.get("descricao")
                or conteudo
            ),
            imagem_url=dados.get(
                "imagem_url"
            ),
            link=dados.get("link"),
            board_id=dados.get(
                "board_id"
            )
        )

    if canal == "youtube":
        return publicar_youtube(
            arquivo_video=dados.get(
                "arquivo_video"
            ),
            titulo=(
                dados.get("titulo")
                or "Maranhão Cordial"
            ),
            descricao=(
                dados.get("descricao")
                or conteudo
            ),
            privacidade=dados.get(
                "privacidade",
                "private"
            )
        )

    return {
        "success": False,
        "erro":
            "Canal digital não suportado: "
            + canal
    }
