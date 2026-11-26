"""
Verificacao de ponta a ponta da plataforma, pelo GATEWAY.

Exercita o que o edital pede em sequencia: rota fechada sem token, login,
indexacao assincrona pela fila, pergunta fundamentada, cota e saude. Sai com
codigo != 0 se qualquer etapa falhar - serve de teste de fumaca depois de um
deploy.

Uso:
    python exemplos/fluxo_completo.py
    API=https://168-75-70-16.sslip.io USUARIO=avaliador SENHA=... python exemplos/fluxo_completo.py
"""
import os
import sys
import time

import requests

API = os.getenv("API", "http://127.0.0.1:8000").rstrip("/")
USUARIO = os.getenv("USUARIO", "aluno")
SENHA = os.getenv("SENHA", "troque-esta-senha")

PERGUNTAS = [
    ("o que diz o teorema CAP?", "teorema_cap.txt"),
    ("como o Raft confirma uma operacao?", "consenso_raft.txt"),
]
falhas = []


def etapa(titulo: str, condicao: bool, detalhe: str = "") -> None:
    marca = "ok " if condicao else "FALHOU"
    print(f"[{marca}] {titulo}{(' - ' + detalhe) if detalhe else ''}", flush=True)
    if not condicao:
        falhas.append(titulo)


def main() -> int:
    print(f"plataforma: {API}\n")

    # 1. a porta esta fechada?
    sem_token = requests.post(f"{API}/perguntar", json={"pergunta": "oi"}, timeout=30)
    etapa("rota protegida recusa sem token", sem_token.status_code == 401,
          f"HTTP {sem_token.status_code}")

    # 2. saude e publica
    saude = requests.get(f"{API}/saude", timeout=30)
    etapa("saude responde sem token", saude.status_code == 200,
          saude.json().get("status", "") if saude.status_code == 200 else "")

    # 3. login
    entrada = requests.post(f"{API}/login",
                            json={"usuario": USUARIO, "senha": SENHA}, timeout=30)
    etapa("login emite token", entrada.status_code == 200, f"HTTP {entrada.status_code}")
    if entrada.status_code != 200:
        return 1
    cabecalho = {"Authorization": f"Bearer {entrada.json()['token']}"}

    # 4. senha errada nao entra
    recusado = requests.post(f"{API}/login",
                             json={"usuario": USUARIO, "senha": "senha-errada"}, timeout=30)
    etapa("senha errada e recusada", recusado.status_code == 401)

    # 5. indexacao assincrona
    documentos = [
        {"texto": "O teorema CAP afirma que, diante de uma particao de rede, um sistema "
                  "distribuido precisa escolher entre consistencia e disponibilidade.",
         "origem": "teorema_cap.txt"},
        {"texto": "Raft e um algoritmo de consenso baseado em eleicao de lider e log "
                  "replicado. Uma operacao e confirmada quando a maioria dos nos registra.",
         "origem": "consenso_raft.txt"},
    ]
    enviado = requests.post(f"{API}/indexar", json=documentos, headers=cabecalho, timeout=30)
    etapa("indexar responde 202 (entra na fila)", enviado.status_code == 202,
          f"HTTP {enviado.status_code}")
    if enviado.status_code != 202:
        return 1
    identificador = enviado.json()["id"]

    # 6. a fila anda
    estado = {}
    for _ in range(40):
        estado = requests.get(f"{API}/tarefa/{identificador}",
                              headers=cabecalho, timeout=30).json()
        if estado.get("status") in ("pronto", "erro"):
            break
        time.sleep(0.5)
    etapa("worker processou a tarefa", estado.get("status") == "pronto",
          f"status={estado.get('status')}")

    # 7. perguntas fundamentadas
    for pergunta, fonte_esperada in PERGUNTAS:
        inicio = time.perf_counter()
        resposta = requests.post(f"{API}/perguntar", headers=cabecalho,
                                 json={"pergunta": pergunta}, timeout=60)
        ms = (time.perf_counter() - inicio) * 1000
        if resposta.status_code != 200:
            etapa(f"pergunta: {pergunta}", False, f"HTTP {resposta.status_code}")
            continue
        corpo = resposta.json()
        fontes = [f["origem"] for f in corpo.get("fontes", [])]
        etapa(f"pergunta: {pergunta}", bool(fontes) and fontes[0] == fonte_esperada,
              f"{ms:.0f}ms · fontes={fontes} · trace={corpo.get('trace_id','')[:16]}")

    # 8. cota
    cota = requests.get(f"{API}/quota", headers=cabecalho, timeout=30).json()
    etapa("cota e informada", "restantes" in cota,
          f"{cota.get('usadas')}/{cota.get('limite_por_minuto')} usadas")

    print()
    if falhas:
        print(f"{len(falhas)} etapa(s) falharam: {', '.join(falhas)}")
        return 1
    print("FLUXO COMPLETO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
