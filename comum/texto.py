"""
Normalizacao de texto - sem dependencia pesada, de proposito.

Isto morava em comum/ranking.py, que importa o vetorizador e, com ele, o
scikit-learn inteiro. So que quem avalia a resposta (servico de inferencia) usa
apenas a comparacao de palavras: puxar 100 MB de biblioteca cientifica para
dobrar acento e um custo que aparece no tamanho da imagem e no tempo de build
de cada deploy.
"""
import unicodedata


def normalizar(texto: str) -> set:
    """Palavras em minuscula, sem acento, com mais de dois caracteres.

    Sem dobrar o acento, "consistencia" e "consistência" seriam termos
    diferentes e a comparacao falharia justamente nas perguntas bem escritas.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return {palavra for palavra in
            "".join(c if c.isalnum() else " " for c in sem_acento).split()
            if len(palavra) > 2}


def cobertura(pergunta: str, texto: str) -> float:
    """Fracao dos termos da pergunta que aparecem no trecho (0 a 1)."""
    termos = normalizar(pergunta)
    if not termos:
        return 0.0
    return len(termos & normalizar(texto)) / len(termos)
