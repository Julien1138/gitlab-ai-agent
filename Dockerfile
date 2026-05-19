# --- Base ---
FROM python:3.11-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
  curl git && \
  rm -rf /var/lib/apt/lists/*

# Installer uniquement les dépendances (pas le package en mode editable)
# Le code sera copié ou monté en volume selon le stage
COPY pyproject.toml .
RUN pip install --no-cache-dir \
  "python-gitlab>=4.0.0" \
  "litellm>=1.40.0" \
  "mcp>=1.0.0" \
  "fastapi>=0.111.0" \
  "uvicorn[standard]>=0.30.0" \
  "httpx>=0.27.0" \
  "pydantic-settings>=2.0.0" \
  "structlog>=24.0.0" \
  "pytest>=8.0.0" \
  "pytest-asyncio>=0.23.0" \
  "pytest-httpx>=0.30.0" \
  "ruff>=0.4.0" \
  "mypy>=1.10.0"

# --- Dev (hot reload, source montée en volume) ---
FROM base AS dev
# cloudflared pour exposer le webhook sans compte ngrok
RUN curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  -o /usr/share/keyrings/cloudflare-main.gpg && \
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  > /etc/apt/sources.list.d/cloudflared.list && \
  apt-get update && apt-get install -y cloudflared && \
  rm -rf /var/lib/apt/lists/*
# Le source est monté via volume dans docker-compose — pas de COPY ici
CMD ["bash"]

# --- Webhook handler (prod) ---
FROM base AS webhook-handler
COPY common/ common/
COPY webhook_handler/ webhook_handler/
CMD ["python", "-m", "uvicorn", "webhook_handler.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- MCP server (prod) ---
FROM base AS mcp-server
COPY common/ common/
COPY mcp_server/ mcp_server/
CMD ["python", "-m", "mcp_server.main"]