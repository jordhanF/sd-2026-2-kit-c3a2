"""Limite de requisicoes por cliente - TAREFA 2."""
import redis

from gateway import limite
from testes.duplos import RedisFalso


def preparar(monkeypatch, maximo=3):
    falso = RedisFalso()
    monkeypatch.setattr(limite, "_redis", falso)
    monkeypatch.setattr(limite, "MAXIMO", maximo)
    return falso


def test_deixa_passar_ate_o_teto_e_barra_depois(monkeypatch):
    preparar(monkeypatch, maximo=3)
    assert [limite.registrar("cliente-a")[0] for _ in range(3)] == [True, True, True]
    permitido, restante, segundos = limite.registrar("cliente-a")
    assert permitido is False
    assert restante == 0
    assert 0 < segundos <= 60


def test_clientes_nao_dividem_a_mesma_cota(monkeypatch):
    preparar(monkeypatch, maximo=2)
    limite.registrar("cliente-a")
    limite.registrar("cliente-a")
    assert limite.registrar("cliente-a")[0] is False
    # o segundo cliente comeca com a cota inteira
    assert limite.registrar("cliente-b")[0] is True


def test_a_chave_expira_sozinha(monkeypatch):
    """TTL so na criacao: renovar a cada requisicao esticaria a janela e o
    contador nunca zeraria."""
    falso = preparar(monkeypatch, maximo=5)
    limite.registrar("cliente-a")
    limite.registrar("cliente-a")
    assert len(falso.expiracoes) == 1
    assert list(falso.expiracoes.values()) == [60]


def test_janela_nova_zera_o_contador(monkeypatch):
    preparar(monkeypatch, maximo=1)
    assert limite.registrar("cliente-a")[0] is True
    assert limite.registrar("cliente-a")[0] is False

    # A chave carrega o minuto corrente; avancar o relogio cria outra chave.
    # O valor real e capturado ANTES de substituir time.time - senao a funcao
    # substituta chamaria a si mesma.
    agora = limite.time.time()
    monkeypatch.setattr(limite.time, "time", lambda: agora + 61)
    assert limite.registrar("cliente-a")[0] is True


def test_contador_fora_do_ar_libera_em_vez_de_derrubar(monkeypatch):
    """Fail-open deliberado: perder o teto e menos grave do que recusar todo
    mundo porque o contador caiu."""
    class RedisQuebrado(RedisFalso):
        def incr(self, chave):
            raise redis.ConnectionError("redis fora do ar")

    monkeypatch.setattr(limite, "_redis", RedisQuebrado())
    permitido, _restante, _segundos = limite.registrar("cliente-a")
    assert permitido is True


def test_consultar_nao_consome_requisicao(monkeypatch):
    preparar(monkeypatch, maximo=5)
    limite.registrar("cliente-a")
    antes = limite.consultar("cliente-a")
    depois = limite.consultar("cliente-a")
    assert antes["usadas"] == depois["usadas"] == 1
    assert depois["restantes"] == 4


def test_login_tem_cota_propria(monkeypatch):
    preparar(monkeypatch, maximo=30)
    assert limite.registrar("login:1.2.3.4", maximo=2)[0] is True
    assert limite.registrar("login:1.2.3.4", maximo=2)[0] is True
    assert limite.registrar("login:1.2.3.4", maximo=2)[0] is False
