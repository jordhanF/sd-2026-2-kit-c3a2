"""
Autenticacao por JWT - TAREFA 1, Aula 16.

Decisoes que valem explicar:

SENHA NUNCA EM CLARO. O ambiente guarda o HASH (bcrypt-sha256 via passlib nao
entra aqui para manter a imagem enxuta; usamos PBKDF2 da propria biblioteca
padrao, que e suficiente e nao traz dependencia nativa). Em desenvolvimento,
sem hash configurado, aceita-se uma senha de ambiente - e o log avisa.

COMPARACAO EM TEMPO CONSTANTE. `compare_digest` em vez de `==`: comparacao que
sai no primeiro byte diferente vaza, pelo tempo de resposta, quantos bytes
estavam certos.

SEGREDO OBRIGATORIO EM PRODUCAO. Com `AMBIENTE=producao` o processo se recusa a
subir com o segredo de exemplo. Segredo padrao em producao e o mesmo que nao ter
autenticacao: qualquer um que leia o repositorio assina o proprio token.
"""
import base64
import hashlib
import hmac
import os
import time

import jwt

from comum.log import configurar

logger = configurar("autenticacao")

SEGREDO = os.getenv("JWT_SEGREDO", "troque-este-segredo")
ALGORITMO = "HS256"
VALIDADE = int(os.getenv("JWT_VALIDADE_SEGUNDOS", "3600"))
EMISSOR = os.getenv("JWT_EMISSOR", "plataforma-ia")

USUARIO = os.getenv("API_USUARIO", "aluno")
SENHA_HASH = os.getenv("API_SENHA_HASH", "")       # pbkdf2_sha256:<iteracoes>:<sal>:<hash>
SENHA_SIMPLES = os.getenv("API_SENHA", "")          # so para desenvolvimento
ITERACOES = 240_000

if os.getenv("AMBIENTE", "local") == "producao" and SEGREDO == "troque-este-segredo":
    raise RuntimeError(
        "JWT_SEGREDO nao configurado: em producao o segredo de exemplo e recusado")


def gerar_hash(senha: str, sal: bytes | None = None) -> str:
    """Gera o valor que vai em API_SENHA_HASH. Use o utilitario:
    python -m gateway.autenticacao <senha>
    """
    sal = sal or os.urandom(16)
    bruto = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES)
    # Separador ':' e nao '$', que e o convencional: este valor vai para o .env
    # lido pelo docker compose, que INTERPOLA cifrao - "pbkdf2_sha256$240000"
    # viraria "pbkdf2_sha256" com a variavel vazia, e o hash chegaria mutilado
    # ao container. Base64 nunca gera ':', entao a divisao continua sem ambiguidade.
    return (f"pbkdf2_sha256:{ITERACOES}:{base64.b64encode(sal).decode()}"
            f":{base64.b64encode(bruto).decode()}")


def conferir_senha(usuario: str, senha: str) -> bool:
    """Confere usuario e senha em tempo constante."""
    if not hmac.compare_digest(usuario, USUARIO):
        return False

    if SENHA_HASH:
        try:
            _algoritmo, iteracoes, sal_b64, hash_b64 = SENHA_HASH.split(":")
            bruto = hashlib.pbkdf2_hmac("sha256", senha.encode(),
                                        base64.b64decode(sal_b64), int(iteracoes))
            return hmac.compare_digest(bruto, base64.b64decode(hash_b64))
        except (ValueError, TypeError):
            logger.error("API_SENHA_HASH mal formada; login recusado")
            return False

    if SENHA_SIMPLES:
        logger.warning("usando API_SENHA em claro - aceitavel so em desenvolvimento")
        return hmac.compare_digest(senha, SENHA_SIMPLES)

    logger.error("nenhuma credencial configurada (API_SENHA_HASH ou API_SENHA)")
    return False


def emitir(usuario: str) -> tuple[str, int]:
    """Assina o token. `exp` curto: token vazado tem validade curta."""
    agora = int(time.time())
    carga = {"sub": usuario, "iss": EMISSOR, "iat": agora, "exp": agora + VALIDADE}
    return jwt.encode(carga, SEGREDO, algorithm=ALGORITMO), VALIDADE


def validar(token: str) -> str:
    """Devolve o dono do token ou levanta 401 com o motivo exato."""
    # Importado aqui dentro, e nao no topo, para que gerar_hash() rode com a
    # biblioteca padrao e nada mais: o roteiro de deploy gera o hash da senha
    # ANTES de existir qualquer dependencia instalada na maquina.
    from fastapi import HTTPException

    try:
        carga = jwt.decode(token, SEGREDO, algorithms=[ALGORITMO], issuer=EMISSOR)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, detail="token expirado: autentique de novo em /login")
    except jwt.InvalidTokenError as erro:
        # Nao repassamos o texto da biblioteca para nao descrever ao atacante
        # exatamente qual verificacao falhou.
        logger.warning("token invalido: %s", erro)
        raise HTTPException(401, detail="token invalido")

    dono = carga.get("sub")
    if not dono:
        raise HTTPException(401, detail="token sem identificacao de cliente")
    return dono


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) != 2:
        print("uso: python -m gateway.autenticacao <senha>")
        raise SystemExit(1)
    print(gerar_hash(sys.argv[1]))
