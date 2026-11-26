"""Autenticacao por JWT - TAREFA 1."""
import importlib
import time

import jwt
import pytest
from fastapi import HTTPException


def recarregar(monkeypatch, **variaveis):
    """O modulo le as credenciais do ambiente no import."""
    for chave, valor in variaveis.items():
        monkeypatch.setenv(chave, valor)
    import gateway.autenticacao as autenticacao
    return importlib.reload(autenticacao)


@pytest.fixture
def auth(monkeypatch):
    import gateway.autenticacao as base
    senha_hash = base.gerar_hash("senha-boa")
    return recarregar(monkeypatch, JWT_SEGREDO="segredo-de-teste",
                      API_USUARIO="aluno", API_SENHA_HASH=senha_hash, API_SENHA="")


def test_senha_certa_e_aceita(auth):
    assert auth.conferir_senha("aluno", "senha-boa")


def test_senha_errada_e_recusada(auth):
    assert not auth.conferir_senha("aluno", "senha-ruim")


def test_usuario_errado_e_recusado(auth):
    assert not auth.conferir_senha("invasor", "senha-boa")


def test_hash_nunca_guarda_a_senha(auth):
    """O valor que vai para o ambiente nao pode conter a senha."""
    valor = auth.gerar_hash("senha-boa")
    assert "senha-boa" not in valor
    assert valor.startswith("pbkdf2_sha256$")


def test_mesmo_texto_gera_hashes_diferentes(auth):
    """Sal por hash: dois cadastros da mesma senha nao se parecem."""
    assert auth.gerar_hash("igual") != auth.gerar_hash("igual")


def test_token_emitido_identifica_o_dono(auth):
    token, validade = auth.emitir("aluno")
    assert auth.validar(token) == "aluno"
    assert validade > 0


def test_token_adulterado_e_recusado(auth):
    token, _ = auth.emitir("aluno")
    corpo, assinatura = token.rsplit(".", 1)
    with pytest.raises(HTTPException) as erro:
        auth.validar(f"{corpo}.{'a' * len(assinatura)}")
    assert erro.value.status_code == 401


def test_token_assinado_com_outro_segredo_e_recusado(auth):
    """O ataque obvio: assinar o proprio token."""
    forjado = jwt.encode({"sub": "invasor", "iss": "plataforma-ia",
                          "exp": int(time.time()) + 60}, "outro-segredo",
                         algorithm="HS256")
    with pytest.raises(HTTPException):
        auth.validar(forjado)


def test_token_expirado_diz_que_expirou(auth):
    vencido = jwt.encode({"sub": "aluno", "iss": "plataforma-ia",
                          "iat": int(time.time()) - 120,
                          "exp": int(time.time()) - 60},
                         "segredo-de-teste", algorithm="HS256")
    with pytest.raises(HTTPException) as erro:
        auth.validar(vencido)
    assert "expirado" in erro.value.detail


def test_producao_recusa_subir_com_o_segredo_de_exemplo(monkeypatch):
    """Segredo padrao em producao e o mesmo que nao ter autenticacao."""
    monkeypatch.setenv("AMBIENTE", "producao")
    monkeypatch.setenv("JWT_SEGREDO", "troque-este-segredo")
    import gateway.autenticacao as autenticacao
    with pytest.raises(RuntimeError, match="JWT_SEGREDO"):
        importlib.reload(autenticacao)
    # devolve o modulo a um estado sao para os testes seguintes
    monkeypatch.setenv("AMBIENTE", "local")
    importlib.reload(autenticacao)


def test_sem_credencial_configurada_ninguem_entra(monkeypatch):
    auth = recarregar(monkeypatch, JWT_SEGREDO="x", API_SENHA_HASH="", API_SENHA="")
    assert not auth.conferir_senha("aluno", "qualquer")
