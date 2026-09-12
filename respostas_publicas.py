import re
import unicodedata


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
