FROM python:3.11-slim

WORKDIR /app

# Dependencias primeiro (cache de layer do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo do projeto
COPY agente_2w/ ./agente_2w/
COPY api/ ./api/
COPY webhook.py .

# Porta padrão
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Iniciar servidor
CMD ["uvicorn", "webhook:app", "--host", "0.0.0.0", "--port", "5001", "--workers", "1"]

COPY webhook_server.py .

EXPOSE 5001

CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "5001", "--timeout-keep-alive", "65"]





