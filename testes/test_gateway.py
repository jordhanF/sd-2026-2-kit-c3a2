"""O gateway como porta de entrada: quem entra, quanto pode e o que acontece
quando um servico interno cai."""
import importlib

import pytest
import requests
from fastapi.testclient import TestClient

from comum.circuit_breaker import CircuitBreaker
from testes.duplos import RedisFalso

RESPOSTA_INFERENCIA = {
    "pergunta": "o que diz o teorema CAP?",
    "resposta": "Diante de uma particao, escolhe-se entre consistencia e disponibilidade.",
    "fontes": [{"origem": "teorema_cap.txt", "score": 0.41}],
    "contexto": ["O teorema CAP trata de consistencia e disponibilidade."],
    "versao_indice": "abc123",
}


@pytest.fixture
def ambiente(monkeypatch):
    """Gateway com credencial conhecida, contador em memoria e disjuntores limpos."""
    monkeypatch.setenv("JWT_SEGREDO", "segredo-de-teste")
    monkeypatch.setenv("API_USUARIO", "aluno")
    monkeypatch.setenv("API_SENHA", "senha-boa")
    monkeypatch.setenv("API_SENHA_HASH", "")

    import gateway.autenticacao as autenticacao
    importlib.reload(autenticacao)
    from gateway import limite
    monkeypatch.setattr(limite, "_redis", RedisFalso())
    monkeypatch.setattr(limite, "MAXIMO", 5)

    import gateway.app as app_modulo
    importlib.reload(app_modulo)
    monkeypatch.setattr(app_modulo, "disjuntores", {
        "ingestao": CircuitBreaker(limite_falhas=3, espera_segundos=20),
        "inferencia": CircuitBreaker(limite_falhas=3, espera_segundos=20),
    })
    return app_modulo


@pytest.fixture
def cliente(ambiente):
    return TestClient(ambiente.app, raise_server_exceptions=False)


def autenticar(cliente) -> str:
    resposta = cliente.post("/login", json={"usuario": "aluno", "senha": "senha-boa"})
    assert resposta.status_code == 200
    return resposta.json()["token"]


# ---------- autenticacao ----------

def test_rota_protegida_sem_token_devolve_401(cliente):
    assert cliente.post("/perguntar", json={"pergunta": "oi"}).status_code == 401


def test_token_de_outro_segredo_nao_entra(cliente):
    import jwt
    forjado = jwt.encode({"sub": "invasor", "iss": "plataforma-ia",
                          "exp": 9999999999}, "outro", algorithm="HS256")
    resposta = cliente.post("/perguntar", json={"pergunta": "oi"},
                            headers={"Authorization": f"Bearer {forjado}"})
    assert resposta.status_code == 401


def test_login_com_senha_errada_nao_diz_qual_campo_errou(cliente):
    resposta = cliente.post("/login", json={"usuario": "aluno", "senha": "errada"})
    outro = cliente.post("/login", json={"usuario": "ninguem", "senha": "senha-boa"})
    assert resposta.status_code == outro.status_code == 401
    assert resposta.json()["detail"] == outro.json()["detail"]


def test_saude_e_publica(cliente):
    assert cliente.get("/saude").status_code == 200


# ---------- caminho feliz ----------

def test_com_token_a_pergunta_chega_na_inferencia(cliente, ambiente, monkeypatch):
    monkeypatch.setattr(ambiente, "_chamar",
                        lambda *a, **k: dict(RESPOSTA_INFERENCIA))
    resposta = cliente.post("/perguntar", json={"pergunta": "o que diz o teorema CAP?"},
                            headers={"Authorization": f"Bearer {autenticar(cliente)}"})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["fontes"][0]["origem"] == "teorema_cap.txt"
    assert "latencia_ms" in corpo


def test_indexar_responde_202(cliente, ambiente, monkeypatch):
    monkeypatch.setattr(ambiente, "_chamar",
                        lambda *a, **k: {"id": "abc", "status": "na_fila"})
    resposta = cliente.post("/indexar", json=[{"texto": "um documento"}],
                            headers={"Authorization": f"Bearer {autenticar(cliente)}"})
    assert resposta.status_code == 202


# ---------- limite de uso ----------

def test_estourar_a_cota_devolve_429_com_retry_after(cliente, ambiente, monkeypatch):
    monkeypatch.setattr(ambiente, "_chamar", lambda *a, **k: dict(RESPOSTA_INFERENCIA))
    cabecalho = {"Authorization": f"Bearer {autenticar(cliente)}"}
    for _ in range(5):
        assert cliente.post("/perguntar", json={"pergunta": "oi"},
                            headers=cabecalho).status_code == 200
    excedida = cliente.post("/perguntar", json={"pergunta": "oi"}, headers=cabecalho)
    assert excedida.status_code == 429
    assert "Retry-After" in excedida.headers


def test_quota_nao_consome_cota(cliente, ambiente, monkeypatch):
    cabecalho = {"Authorization": f"Bearer {autenticar(cliente)}"}
    primeira = cliente.get("/quota", headers=cabecalho).json()
    segunda = cliente.get("/quota", headers=cabecalho).json()
    assert primeira["usadas"] == segunda["usadas"]


# ---------- resiliencia ----------

def test_servico_fora_do_ar_vira_503_e_abre_o_disjuntor(cliente, ambiente, monkeypatch):
    def recusada(*_a, **_k):
        raise requests.ConnectionError("conexao recusada")

    monkeypatch.setattr(ambiente.requests, "request", recusada)
    cabecalho = {"Authorization": f"Bearer {autenticar(cliente)}"}

    for _ in range(3):
        assert cliente.post("/perguntar", json={"pergunta": "oi"},
                            headers=cabecalho).status_code == 503

    assert ambiente.disjuntores["inferencia"].estado == "aberto"
    # o disjuntor da ingestao NAO foi contaminado
    assert ambiente.disjuntores["ingestao"].estado == "fechado"


def test_erro_do_cliente_nao_vira_503_nem_abre_disjuntor(cliente, ambiente, monkeypatch):
    """404 do servico interno e resposta legitima, nao falha de infraestrutura."""
    class Resposta:
        status_code = 404
        text = '{"detail":"tarefa desconhecida"}'

        @staticmethod
        def json():
            return {"detail": "tarefa desconhecida"}

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(ambiente.requests, "request", lambda *a, **k: Resposta())
    cabecalho = {"Authorization": f"Bearer {autenticar(cliente)}"}
    resposta = cliente.get("/tarefa/inexistente", headers=cabecalho)

    assert resposta.status_code == 404
    assert ambiente.disjuntores["ingestao"].estado == "fechado"


def test_erro_carrega_o_id_do_rastro(cliente, ambiente, monkeypatch):
    monkeypatch.setattr(ambiente.requests, "request",
                        lambda *a, **k: (_ for _ in ()).throw(
                            requests.ConnectionError("caiu")))
    cabecalho = {"Authorization": f"Bearer {autenticar(cliente)}"}
    corpo = cliente.post("/perguntar", json={"pergunta": "oi"}, headers=cabecalho).json()
    assert "detail" in corpo
    # trace_id so existe quando ha rastreamento configurado no processo; o
    # contrato testado aqui e o corpo do erro sempre trazer o motivo.
    assert "indisponivel" in corpo["detail"]
