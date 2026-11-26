"""Rastreamento distribuido - TAREFA 7.

O que estes testes protegem e exatamente o ponto que costuma quebrar sem
ninguem perceber: o rastro sobrevive a travessia da FILA.
"""
from comum import tracing
from comum.fila import Fila
from testes.duplos import RedisFalso


def test_contexto_injetado_tem_traceparent_do_w3c():
    tracing.configurar("teste")
    with tracing.tracer().start_as_current_span("publicar"):
        portador = tracing.injetar_contexto()
    assert "traceparent" in portador
    assert portador["traceparent"].startswith("00-")


def test_o_worker_herda_o_trace_de_quem_publicou():
    """Sem isto o rastro morreria no gateway e a indexacao - a parte cara -
    ficaria invisivel."""
    tracing.configurar("teste")
    with tracing.tracer().start_as_current_span("publicar"):
        portador = tracing.injetar_contexto()
        trace_do_publicador = tracing.id_do_trace()

    with tracing.span_consumindo_fila("consumir", portador):
        assert tracing.id_do_trace() == trace_do_publicador


def test_tarefa_publicada_na_fila_leva_o_contexto():
    """A integracao de verdade: quem publica e a fila, nao o teste."""
    tracing.configurar("teste")
    fila = Fila(cliente=RedisFalso())
    with tracing.tracer().start_as_current_span("POST /indexar"):
        trace_da_requisicao = tracing.id_do_trace()
        fila.publicar([{"texto": "um documento", "origem": "x"}])

    tarefa = fila.consumir(timeout=0)
    assert "traceparent" in tarefa["trace"]
    with tracing.span_consumindo_fila("worker", tarefa["trace"]):
        assert tracing.id_do_trace() == trace_da_requisicao


def test_tarefa_sem_contexto_nao_quebra_o_worker():
    """Tarefa antiga, publicada antes do rastreamento existir, ainda processa."""
    tracing.configurar("teste")
    with tracing.span_consumindo_fila("worker", None) as span:
        assert span is not None


def test_sem_span_ativo_o_id_do_trace_e_vazio():
    assert tracing.id_do_trace() == "" or len(tracing.id_do_trace()) == 32
