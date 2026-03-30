# ─────────────────────────────────────────────────────────────
# Agente 2W Pneus — Dockerfile de producao
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Variaveis de build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencias do sistema (necessarias para httpx/supabase)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python primeiro (cache de layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo do agente
# COPY agente_2w/ ./agente_2w/
COPY api/ ./api/

# Usuario nao-root para seguranca
RUN useradd -m -u 1000 agente && chown -R agente:agente /app
USER agente

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8000} --log-level ${LOG_LEVEL:-info}"]
