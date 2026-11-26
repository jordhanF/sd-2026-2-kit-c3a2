"""
Rastreamento distribuido (OpenTelemetry) - TAREFA 7, Aula 15.

O PROBLEMA QUE ESTE MODULO RESOLVE

Um pedido entra pelo gateway, vira tarefa numa FILA e e processado depois, por
outro processo, em outro container. Entre HTTP e fila a propagacao do contexto
e muito diferente:

  HTTP  -> automatica. A instrumentacao do `requests` injeta o cabecalho
           `traceparent` na requisicao e a do FastAPI o extrai do outro lado.

  FILA  -> NAO existe. A tarefa fica parada no Redis e quem a consome e outro
           processo, mais tarde. Sem tratamento, o trace MORRE no gateway e
           justamente a metade cara do trabalho - a indexacao - fica invisivel.

Por isso o contexto e injetado no CORPO da tarefa (`injetar_contexto`) e
reconstruido pelo worker (`span_consumindo_fila`). E o que faz o rastro cobrir
gateway -> fila -> worker, como o edital pede, e nao apenas as chamadas HTTP.
"""
import os
from contextlib import contextmanager

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import SpanKind

from comum.log import configurar as configurar_log

logger = configurar_log("tracing")

ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
EXPORTAR_NO_CONSOLE = os.getenv("OTEL_CONSOLE", "") == "1"
_configurado = False


def configurar(nome_servico: str) -> None:
    """Liga o rastreamento deste processo. Idempotente.

    Sem OTEL_EXPORTER_OTLP_ENDPOINT os spans continuam sendo criados, mas nao
    sao enviados a lugar nenhum: a plataforma roda offline sem coletor, e o
    rastreamento nao pode ser uma dependencia dura para o sistema subir.
    """
    global _configurado
    if _configurado:
        return

    provedor = TracerProvider(resource=Resource.create({
        "service.name": nome_servico,
        "deployment.environment": os.getenv("AMBIENTE", "local"),
    }))

    if ENDPOINT:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provedor.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{ENDPOINT.rstrip('/')}/v1/traces")))
        logger.info("rastreamento ligado: %s -> %s", nome_servico, ENDPOINT)
    elif EXPORTAR_NO_CONSOLE:
        provedor.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("rastreamento no console: %s", nome_servico)
    else:
        logger.info("rastreamento sem coletor: spans criados, nao exportados")

    trace.set_tracer_provider(provedor)
    _configurado = True


def instrumentar_fastapi(app) -> None:
    """Cada requisicao HTTP vira um span, com o contexto extraido do cabecalho."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app, excluded_urls="saude,metricas")


def instrumentar_clientes() -> None:
    """Chamadas de saida (requests) e comandos do Redis entram no rastro."""
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RequestsInstrumentor().instrument()
    RedisInstrumentor().instrument()


def tracer(nome: str = "plataforma"):
    return trace.get_tracer(nome)


# ---------- a travessia da fila ----------

def injetar_contexto() -> dict:
    """Serializa o contexto atual (traceparent W3C) para viajar DENTRO da tarefa."""
    portador: dict = {}
    propagate.inject(portador)
    return portador


@contextmanager
def span_consumindo_fila(nome: str, portador: dict | None, **atributos):
    """Abre no worker um span filho do span que PUBLICOU a tarefa.

    `SpanKind.CONSUMER` e a convencao do OpenTelemetry para o lado consumidor de
    uma fila: e o que permite a interface de rastreamento desenhar a espera entre
    publicar e processar, que e exatamente o tempo que a fila existe para comprar.
    """
    contexto_pai = propagate.extract(portador or {})
    with tracer().start_as_current_span(nome, context=contexto_pai,
                                        kind=SpanKind.CONSUMER) as span:
        for chave, valor in atributos.items():
            span.set_attribute(chave, valor)
        yield span


def id_do_trace() -> str:
    """Id do trace em curso, para aparecer no log e na resposta HTTP.

    E o que liga uma reclamacao concreta ("minha pergunta falhou") ao rastro
    correspondente, sem ter de caçar por horario.
    """
    contexto = trace.get_current_span().get_span_context()
    if not contexto.is_valid:
        return ""
    return format(contexto.trace_id, "032x")
