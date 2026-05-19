# --- Base ---
FROM python:3.11-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# --- Dev (all services + hot reload, source mounted as volume) ---
FROM base AS dev
# Install cloudflared for webhook tunnelling (replaces ngrok, no account needed)
RUN curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
      -o /usr/share/keyrings/cloudflare-main.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
      > /etc/apt/sources.list.d/cloudflared.list && \
    apt-get update && apt-get install -y cloudflared && \
    rm -rf /var/lib/apt/lists/*
# Source is mounted at runtime — no COPY needed
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
