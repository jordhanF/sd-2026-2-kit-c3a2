"""
Limite de requisicoes por cliente - TAREFA 2, Aula 8.

O CONTADOR MORA NO REDIS, NAO NA MEMORIA DO PROCESSO. Um contador em memoria
funciona com um gateway e mente com dois: subindo `--scale gateway=2`, cada
replica concederia a cota inteira e o limite real viraria o dobro do anunciado.
Como o Redis ja esta na plataforma para a fila, o estado compartilhado sai de
graca - e o gateway continua sem estado, que e o que permite replica-lo.

JANELA FIXA POR MINUTO: a chave carrega o minuto corrente, `INCR` cria com valor
1 e `EXPIRE` faz a chave sumir sozinha. Simples e barato (dois comandos), com a
desvantagem conhecida de permitir ate 2x o limite na virada do minuto. Janela
deslizante por ZSET resolveria, ao custo de guardar um item por requisicao -
trade-off registrado no README.

SE O REDIS CAIR, A PLATAFORMA NAO CAI JUNTO: o limite abre (fail-open). Perder o
teto de uso e menos grave do que recusar todo mundo por causa do contador. A
escolha oposta (fail-closed) seria a certa se o limite existisse para proteger
custo de terceiros, e nao a capacidade do proprio servico.
"""
import os
import time

import redis

from comum.fila import conectar
from comum.log import configurar

logger = configurar("limite")

MAXIMO = int(os.getenv("LIMITE_POR_MINUTO", "30"))
MAXIMO_LOGIN = int(os.getenv("LIMITE_LOGIN_POR_MINUTO", "5"))
JANELA = 60

_redis = None


def _cliente_redis():
    global _redis
    if _redis is None:
        _redis = conectar()
    return _redis


def _chave(cliente: str, agora: float) -> str:
    return f"limite:{cliente}:{int(agora // JANELA)}"


def registrar(cliente: str, maximo: int | None = None) -> tuple[bool, int, int]:
    """Conta uma requisicao. Devolve (permitido, restante, segundos_ate_zerar)."""
    teto = maximo if maximo is not None else MAXIMO
    agora = time.time()
    segundos = JANELA - int(agora % JANELA)
    try:
        conexao = _cliente_redis()
        chave = _chave(cliente, agora)
        usado = conexao.incr(chave)
        if usado == 1:
            # TTL so na criacao: renovar a cada requisicao esticaria a janela
            # para sempre e o contador nunca zeraria.
            conexao.expire(chave, JANELA)
    except redis.RedisError as erro:
        logger.error("contador indisponivel (%s): liberando a requisicao", erro)
        return True, teto, segundos

    return usado <= teto, max(teto - usado, 0), segundos


def consultar(cliente: str) -> dict:
    """Quanto resta, SEM consumir requisicao."""
    agora = time.time()
    try:
        usado = int(_cliente_redis().get(_chave(cliente, agora)) or 0)
    except redis.RedisError as erro:
        return {"limite_por_minuto": MAXIMO, "contador": f"indisponivel: {erro}"}
    return {"limite_por_minuto": MAXIMO, "usadas": usado,
            "restantes": max(MAXIMO - usado, 0),
            "zera_em_segundos": JANELA - int(agora % JANELA)}
