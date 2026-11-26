"""
API Gateway - a UNICA porta de entrada da plataforma.

Nenhum servico interno fica exposto na internet: o compose publica apenas este,
e so em 127.0.0.1, atras do nginx com HTTPS. Isso concentra num lugar so o que
nao se quer repetido em quatro servicos:

  autenticacao (TAREFA 1)  - JWT emitido em /login, exigido nas rotas de uso
  limite de uso (TAREFA 2) - contador por cliente, compartilhado no Redis
  resiliencia  (TAREFA 6)  - tempo-limite, retentativa e disjuntor por destino
  rastreamento (TAREFA 7)  - o trace comeca aqui e segue ate o worker

Rodar: uvicorn gateway.app:app --port 8000
"""
import os
import time

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from comum import ambiente  # noqa: F401  carrega o .env primeiro
from comum import log, tracing
from comum.circuit_breaker import CircuitBreaker, CircuitoAberto
from comum.retentativa import com_retentativa
from gateway import autenticacao, limite

logger = log.configurar("gateway")

tracing.configurar("gateway")
tracing.instrumentar_clientes()

app = FastAPI(title="Gateway - C3.A2",
              description="Porta de entrada da plataforma de IA como servico.")
log.registrar_requisicoes(app, logger)
tracing.instrumentar_fastapi(app)

URL_INGESTAO = os.getenv("URL_INGESTAO", "http://127.0.0.1:8001")
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://127.0.0.1:8003")
TIMEOUT = float(os.getenv("TIMEOUT_INTERNO", "15"))
REPOSITORIO = os.getenv(
    "URL_REPOSITORIO", "https://github.com/jordhanF/sd-2026-2-kit-c3a2")

# Um disjuntor POR DESTINO. Com um contador unico, a inferencia fora do ar
# cortaria tambem a indexacao, que esta saudavel - falhas diferentes precisam
# de contadores diferentes.
disjuntores = {
    "ingestao": CircuitBreaker(limite_falhas=3, espera_segundos=20),
    "inferencia": CircuitBreaker(limite_falhas=3, espera_segundos=20),
}


class Credenciais(BaseModel):
    usuario: str = Field(min_length=1)
    senha: str = Field(min_length=1)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=20)


class Documento(BaseModel):
    texto: str = Field(min_length=1)
    origem: str = "desconhecida"


def cliente_autenticado(authorization: str = Header(default="")) -> str:
    """Dependencia das rotas protegidas: devolve o dono do token ou 401."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, detail="informe o token: Authorization: Bearer <token>")
    return autenticacao.validar(authorization.removeprefix("Bearer ").strip())


def cliente_no_limite(cliente: str = Depends(cliente_autenticado)) -> str:
    """Aplica o limite de requisicoes DEPOIS de identificar o cliente.

    A cota e por dono do token, nao por IP: varios clientes atras do mesmo IP
    (escritorio, celular em NAT) nao disputam a mesma cota, e um token nao escapa
    do limite trocando de rede.
    """
    permitido, restante, segundos = limite.registrar(cliente)
    if not permitido:
        raise HTTPException(
            429, detail=f"limite de {limite.MAXIMO} requisicoes por minuto atingido; "
                        f"tente em {segundos}s",
            headers={"Retry-After": str(segundos)})
    return cliente


def _chamar(destino: str, metodo: str, caminho: str, **kwargs):
    """Chamada a um servico interno com as tres protecoes somadas.

    tempo-limite -> corta a chamada travada
    retentativa  -> cobre o que e transitorio (timeout, 5xx, conexao caida)
    disjuntor    -> para de tentar quando a falha deixou de ser transitoria

    A retentativa fica DENTRO do disjuntor: uma sequencia esgotada conta como
    uma falha so, senao o circuito abriria no primeiro solucinho de rede.
    """
    def executar():
        resposta = requests.request(metodo, caminho, timeout=TIMEOUT, **kwargs)
        resposta.raise_for_status()
        return resposta.json()

    try:
        return disjuntores[destino].chamar(com_retentativa, executar, tentativas=2)
    except CircuitoAberto:
        logger.warning("disjuntor de %s ABERTO: recusando sem tentar", destino)
        raise HTTPException(503, detail=f"servico de {destino} indisponivel: disjuntor "
                                        f"aberto, a chamada foi recusada sem tentar")
    except requests.HTTPError as erro:
        # Erro de cliente (4xx) e resposta legitima do servico, nao falha de
        # infraestrutura: repassa o status em vez de mascarar tudo como 503.
        codigo = erro.response.status_code if erro.response is not None else 503
        if 400 <= codigo < 500:
            raise HTTPException(codigo, detail=_detalhe(erro.response))
        raise HTTPException(503, detail=f"servico de {destino} indisponivel: {erro}")
    except requests.RequestException as erro:
        raise HTTPException(503, detail=f"servico de {destino} indisponivel: {erro}")


def _detalhe(resposta) -> str:
    try:
        return resposta.json().get("detail", resposta.text[:200])
    except ValueError:
        return resposta.text[:200]


# ---------- rotas publicas ----------

@app.post("/login")
def login(credenciais: Credenciais, request: Request):
    """Emite o token. Unica rota de uso que nao exige token (seria circular).

    O limite aqui e por IP, justamente porque ainda nao ha cliente identificado:
    e o que impede alguem de varrer senhas sem custo.
    """
    ip = request.client.host if request.client else "desconhecido"
    permitido, _restante, segundos = limite.registrar(f"login:{ip}", maximo=limite.MAXIMO_LOGIN)
    if not permitido:
        raise HTTPException(429, detail=f"tentativas demais; tente em {segundos}s",
                            headers={"Retry-After": str(segundos)})

    if not autenticacao.conferir_senha(credenciais.usuario, credenciais.senha):
        # Mesma mensagem para usuario inexistente e senha errada: dizer qual dos
        # dois errou entrega metade da credencial.
        logger.warning("login recusado (ip=%s)", ip)
        raise HTTPException(401, detail="usuario ou senha invalidos")

    token, expira_em = autenticacao.emitir(credenciais.usuario)
    logger.info("login aceito: %s", credenciais.usuario)
    return {"token": token, "tipo": "Bearer", "expira_em_segundos": expira_em}


PAGINA_INICIAL = """<!doctype html>
<html lang="pt-br"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plataforma de IA como Servico</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 16px/1.6 system-ui, sans-serif; max-width: 46rem; margin: 0 auto;
         padding: 3rem 1.25rem; }
  h1 { font-size: 1.6rem; margin-bottom: .25rem; }
  p.sub { margin-top: 0; opacity: .75; }
  code, pre { font-family: ui-monospace, monospace; font-size: .875rem; }
  pre { padding: 1rem; border-radius: .5rem; overflow-x: auto;
        background: color-mix(in srgb, currentColor 8%%, transparent); }
  a.botao { display: inline-block; margin: .25rem .5rem .25rem 0; padding: .5rem .9rem;
            border-radius: .5rem; text-decoration: none;
            background: color-mix(in srgb, currentColor 12%%, transparent);
            color: inherit; }
  table { border-collapse: collapse; width: 100%%; margin: 1rem 0; }
  td, th { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid
           color-mix(in srgb, currentColor 15%%, transparent); }
  footer { margin-top: 2.5rem; opacity: .7; font-size: .875rem; }
</style>
<h1>Plataforma de IA como Servico</h1>
<p class="sub">C3.A2 &middot; Sistemas Distribuidos e Computacao em Nuvem &middot; FAESA 2026/2</p>

<p>Perguntas e respostas sobre documentos proprios (RAG), servidas por sete processos em
containers: gateway, inferencia, recuperacao, ingestao, worker de fila, Redis e coletor de
rastros.</p>

<p>
  <a class="botao" href="/docs">Documentacao interativa (testar aqui)</a>
  <a class="botao" href="/saude">Saude da plataforma</a>
  <a class="botao" href="%(repo)s">Codigo no GitHub</a>
</p>

<h2>Rotas</h2>
<table>
  <tr><th>Rota</th><th>O que faz</th><th>Token</th></tr>
  <tr><td><code>POST /login</code></td><td>emite o JWT</td><td>nao</td></tr>
  <tr><td><code>GET /saude</code></td><td>saude da plataforma inteira</td><td>nao</td></tr>
  <tr><td><code>POST /perguntar</code></td><td>resposta fundamentada nos documentos</td><td>sim</td></tr>
  <tr><td><code>POST /indexar</code></td><td>enfileira documentos (202)</td><td>sim</td></tr>
  <tr><td><code>GET /tarefa/{id}</code></td><td>andamento da indexacao</td><td>sim</td></tr>
  <tr><td><code>GET /quota</code></td><td>quanto resta da cota</td><td>sim</td></tr>
</table>

<h2>Em dois comandos</h2>
<pre>TOKEN=$(curl -s -X POST %(url)s/login -H "Content-Type: application/json"   -d '{"usuario":"SEU-USUARIO","senha":"SUA-SENHA"}' | jq -r .token)

curl -s -X POST %(url)s/perguntar -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json" -d '{"pergunta":"o que diz o teorema CAP?"}'</pre>

<footer>Sem token, as rotas de uso respondem 401 &mdash; e proposital.</footer>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def inicio(request: Request):
    """Porta de entrada legivel por gente.

    Sem esta rota, abrir a URL da plataforma no navegador devolve
    {"detail":"Not Found"} - tecnicamente correto e pessimo como primeira
    impressao: quem abre nao tem como saber se o sistema esta no ar ou quebrado.
    """
    base = str(request.base_url).rstrip("/")
    return PAGINA_INICIAL % {"url": base, "repo": REPOSITORIO}


@app.get("/saude")
def saude():
    """Saude da plataforma inteira, vista da porta de entrada."""
    estado = {"status": "ok", "servicos": {}, "disjuntores": {
        nome: d.estado for nome, d in disjuntores.items()}}
    for nome, url in (("ingestao", URL_INGESTAO), ("inferencia", URL_INFERENCIA)):
        try:
            resposta = requests.get(f"{url}/saude", timeout=5)
            resposta.raise_for_status()
            estado["servicos"][nome] = resposta.json()
        except requests.RequestException as erro:
            estado["servicos"][nome] = {"status": "indisponivel", "erro": str(erro)}
            estado["status"] = "degradado"
    return estado


# ---------- rotas protegidas ----------

@app.post("/perguntar")
def perguntar(p: Pergunta, cliente: str = Depends(cliente_no_limite)):
    """Fluxo de leitura: pergunta entra, resposta fundamentada sai."""
    inicio = time.perf_counter()
    corpo = _chamar("inferencia", "POST", f"{URL_INFERENCIA}/perguntar",
                    json=p.model_dump())
    corpo["trace_id"] = tracing.id_do_trace()
    corpo["latencia_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
    return corpo


@app.post("/indexar", status_code=202)
def indexar(docs: list[Documento], cliente: str = Depends(cliente_no_limite)):
    """Fluxo de escrita: entra na fila e responde 202 com o comprovante."""
    corpo = _chamar("ingestao", "POST", f"{URL_INGESTAO}/indexar",
                    json=[d.model_dump() for d in docs])
    corpo["trace_id"] = tracing.id_do_trace()
    return corpo


@app.get("/tarefa/{identificador}")
def tarefa(identificador: str, cliente: str = Depends(cliente_no_limite)):
    """Acompanha a indexacao: na_fila -> processando -> pronto (ou erro)."""
    return _chamar("ingestao", "GET", f"{URL_INGESTAO}/tarefa/{identificador}")


@app.get("/quota")
def quota(cliente: str = Depends(cliente_autenticado)):
    """Quanto resta da cota deste cliente. Nao consome requisicao."""
    return {"cliente": cliente, **limite.consultar(cliente)}


@app.exception_handler(HTTPException)
async def com_id_de_rastreamento(request: Request, exc: HTTPException):
    """Todo erro sai com o id do trace.

    E o que liga a reclamacao concreta ("deu 503 agora") ao rastro exato, sem
    ter de procurar por horario no meio de todas as requisicoes.
    """
    corpo = {"detail": exc.detail}
    identificador = tracing.id_do_trace()
    if identificador:
        corpo["trace_id"] = identificador
    return JSONResponse(status_code=exc.status_code, content=corpo,
                        headers=getattr(exc, "headers", None))
