# TAREFAS - Trabalho C3.A2 (Plataforma de IA como Servico)

Este e o projeto integrador. Reaproveite o que voce fez em C1.A2 e C2.A2.

## Nucleo obrigatorio

- [x] **1. Autenticacao JWT no gateway** - `gateway/autenticacao.py`
      `/login` emite token HS256 com validade de 1h; as rotas de uso exigem
      `Authorization: Bearer` e devolvem 401 sem ele. A senha nunca e guardada:
      o ambiente tem so o hash PBKDF2-SHA256, com sal por senha, e a comparacao
      e em tempo constante.

- [x] **2. Rate limit no gateway** - `gateway/limite.py`
      Contador por cliente (o `sub` do token) com janela de um minuto, guardado
      no REDIS e nao em memoria - contador em processo mentiria com duas
      replicas. `/login` tem cota propria, por IP, para barrar varredura de senha.

- [x] **3. Dockerfile de cada servico**
      Cinco imagens: gateway, ingestao, recuperacao, inferencia e worker. Gateway
      e inferencia nao instalam scikit-learn.

- [x] **4. docker-compose completo**
      `docker compose up -d --build` sobe os sete processos. Validado por clone
      limpo em outra maquina.

- [x] **5. Deploy em nuvem (free tier)**
      https://168-75-70-16.sslip.io - Oracle Cloud Always Free (Ampere A1, ARM64).

- [x] **6. Resiliencia**
      Tempo-limite, retentativa com espera progressiva e um disjuntor POR
      destino. Medido em producao: 553 ms por falha com o circuito fechado,
      42 ms depois que ele abre.

- [x] **7. Observabilidade**
      Rastro unico cobrindo gateway -> fila -> worker: o `traceparent` do W3C
      viaja dentro da tarefa e o worker reabre o span como filho de quem
      publicou. Trace real com 22 spans e 3 servicos documentado no README.

- [x] **8. HTTPS** no servico publicado.
      Let's Encrypt via certbot, com redirecionamento de 80 para 443.

- [x] **9. Secao de conformidade no README**
      Tabela com cada dado tratado, finalidade, base legal e retencao, mais o
      que deliberadamente NAO e registrado (texto de pergunta e resposta).

- [x] **10. Relatorio de trade-offs**
      CAP (o indice escolhe C, a leitura e a cota escolhem A), custo (R$ 0,00 e
      o que mudaria com LLM pago) e latencia (medida pela internet).

## Extensoes opcionais

- [x] CI/CD: `.github/workflows/testes.yml` roda a suite, monta as cinco imagens
      e varre o repositorio atras de segredo a cada push.
- [ ] Autoescalonamento de workers conforme o tamanho da fila - o worker escala
      a mao (`--scale worker=3`); medir a fila e ajustar sozinho ficou de fora.
- [ ] Componente serverless ou na borda
- [ ] Painel de metricas - ha rastreamento (Jaeger), nao ha painel de metricas.
- [ ] Manifests de Kubernetes

## Antes de entregar

- [x] Clone em OUTRA maquina e rode o comando unico - funciona?
      Sim: clone limpo do GitHub no servidor, `docker compose up -d --build`, e
      o verificador de ponta a ponta passou em todas as etapas.
- [x] A URL publica esta no ar?
      https://168-75-70-16.sslip.io - HTTP redireciona para HTTPS, certificado
      valido ate 24/02/2027.
- [x] Toda configuracao esta em variavel de ambiente (nada fixo no codigo)?
      Sim; e com `AMBIENTE=producao` o gateway se recusa a subir com o segredo
      de exemplo.
- [x] Os logs estao livres de dados pessoais?
      Sim: o log guarda metodo, rota, status e duracao; nem o texto da pergunta
      nem o da resposta entram em log ou em atributo de span.
