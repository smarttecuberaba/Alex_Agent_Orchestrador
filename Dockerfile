FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY agente_2w/ ./agente_2w/
COPY webhook.py .

# Porta padrão
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Iniciar servidor
CMD ["uvicorn", "webhook:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "1"]
