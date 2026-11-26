# Imagem do servico 'gateway' - TAREFA 3 (um Dockerfile por servico).
#
# O CONTEXTO DE BUILD E A RAIZ DO REPOSITORIO, nao esta pasta: a biblioteca
# comum/ precisa entrar na imagem, e o Docker nao copia de fora do contexto.
# Por isso o compose declara "context: ." com "dockerfile: gateway/Dockerfile".
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias antes do codigo: editar um .py nao invalida a camada do pip, que
# e a cara. Cada servico instala so o que usa - o gateway e a inferencia nao
# levam scikit-learn, o que corta ~100 MB de cada imagem.
COPY requirements-comum.txt ./
COPY gateway/requirements.txt gateway/
RUN pip install --no-cache-dir -r gateway/requirements.txt

COPY comum/ ./comum/
COPY gateway/ ./gateway/

# Container nao roda como root: se um servico for comprometido, o estrago fica
# limitado ao que este usuario pode fazer.
RUN useradd --create-home --uid 10001 plataforma \
    && mkdir -p /app/dados \
    && chown -R plataforma:plataforma /app
USER plataforma

EXPOSE 8000

# O compose espera por esta sonda antes de subir quem depende deste servico.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude')"

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
