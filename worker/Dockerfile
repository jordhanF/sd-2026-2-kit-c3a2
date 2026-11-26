# Imagem do servico 'worker' - TAREFA 3 (um Dockerfile por servico).
#
# O CONTEXTO DE BUILD E A RAIZ DO REPOSITORIO, nao esta pasta: a biblioteca
# comum/ precisa entrar na imagem, e o Docker nao copia de fora do contexto.
# Por isso o compose declara "context: ." com "dockerfile: worker/Dockerfile".
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias antes do codigo: editar um .py nao invalida a camada do pip, que
# e a cara. Cada servico instala so o que usa - o gateway e a inferencia nao
# levam scikit-learn, o que corta ~100 MB de cada imagem.
COPY requirements-comum.txt requirements-vetorial.txt ./
COPY worker/requirements.txt worker/
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY comum/ ./comum/
COPY worker/ ./worker/

# Container nao roda como root: se um servico for comprometido, o estrago fica
# limitado ao que este usuario pode fazer.
RUN useradd --create-home --uid 10001 plataforma \
    && mkdir -p /app/dados \
    && chown -R plataforma:plataforma /app
USER plataforma

# Sem HEALTHCHECK: o worker nao atende HTTP. Quem diz se ele esta vivo e a fila
# andando - visivel no GET /saude da ingestao (tamanho da fila) e no rastro.

CMD ["python", "-m", "worker.indexador"]
