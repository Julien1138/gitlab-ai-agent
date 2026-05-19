# gitlab-ai-agent

AI agent for GitLab — two features, one repo:

| Feature | How it works |
|---|---|
| **Issue management** | MCP server exposed to Claude Desktop / claude.ai → create, list, read, and comment on issues via GitLab API |
| **Issue analysis** | GitLab webhook → FastAPI handler → agentic loop browses the codebase → posts an analysis comment on the issue |

Both features share the same GitLab client, LLM abstraction, and config.

---

## LLM backends

Switch model by editing `.env` — no code changes needed:

```env
# Anthropic
LLM_MODEL=claude-sonnet-4-20250514

# Local Ollama
LLM_MODEL=ollama/llama3
LLM_API_BASE=http://localhost:11434

# vLLM (OpenAI-compatible)
LLM_MODEL=openai/mistral-7b-instruct
LLM_API_BASE=http://localhost:8000/v1
```

---

## Getting started

### 1. Config

```bash
cp .env.example .env
# Renseigner GITLAB_TOKEN, LLM_MODEL, et l'une des deux options d'auth webhook ci-dessous
```

**Authentification webhook — choisir une méthode :**

| Variable | Méthode | Recommandé |
|---|---|---|
| `GITLAB_WEBHOOK_SIGNING_SECRET` | HMAC-SHA256 ([Standard Webhooks](https://www.standardwebhooks.com/)) | ✅ |
| `GITLAB_WEBHOOK_SECRET` | Comparaison de token plain-text (`X-Gitlab-Token`) | Legacy |

Si les deux sont définis, le signing secret a la priorité. Si aucun n'est défini, la vérification est désactivée (dev uniquement).

**Paramètres optionnels de l'agent :**

```env
AGENT_MAX_ITERATIONS=10      # nombre maximum d'appels d'outils par analyse
AGENT_MAX_FILE_SIZE_KB=100   # ignore les fichiers plus grands que cette limite
```

### 2. Dev (Docker, hot reload, tunnel public inclus)

```bash
docker compose --profile dev up --build
```

Trois conteneurs démarrent :
- **webhook-handler-dev** sur `localhost:8000` avec `--reload`
- **tunnel-dev** (Cloudflare Tunnel) — l'URL publique apparaît dans ses logs :
  ```
  tunnel-dev  | +----------------------------+
  tunnel-dev  | | https://xxxx.trycloudflare.com |
  ```
- **mcp-server-dev** avec source montée en volume

Copier l'URL du tunnel dans GitLab → Project → Settings → Webhooks :
- URL : `https://xxxx.trycloudflare.com/webhook`
- Secret token : valeur de `GITLAB_WEBHOOK_SECRET` (ou laisser vide si tu utilises `GITLAB_WEBHOOK_SIGNING_SECRET`)
- Trigger : ✅ Issues events

> Le tunnel Cloudflare est éphémère (l'URL change à chaque redémarrage) et ne
> nécessite pas de compte. Pour une URL stable en dev, utiliser un tunnel
> Cloudflare nommé ou déployer directement en prod.

### 3. MCP server — connexion à Claude Desktop

Claude Desktop est disponible sur Linux, macOS et Windows.

Outils exposés : `create_issue`, `list_issues`, `get_issue`, `add_issue_comment`.

Ajouter dans `~/.config/Claude/claude_desktop_config.json` (Linux) :
```json
{
  "mcpServers": {
    "gitlab": {
      "command": "docker",
      "args": [
        "compose", "--profile", "dev",
        "exec", "mcp-server-dev",
        "python", "-m", "mcp_server.main"
      ],
      "cwd": "/chemin/vers/gitlab-ai-agent"
    }
  }
}
```

Ou sans Docker :
```bash
pip install -e ".[dev]"
python -m mcp_server.main
```

### 4. Prod

```bash
docker compose --profile prod up -d
```

---

## Project structure

```
gitlab-ai-agent/
├── common/
│   ├── config.py          # pydantic-settings, all config from .env
│   ├── gitlab_client.py   # python-gitlab wrapper (issues, code browsing)
│   ├── llm.py             # LiteLLM abstraction
│   └── agent.py           # agentic tool-calling loop
├── mcp_server/
│   └── main.py            # MCP server (create_issue, list_issues, get_issue, add_issue_comment)
├── webhook_handler/
│   └── main.py            # FastAPI webhook receiver + signature verification
├── Dockerfile             # multi-stage (webhook-handler / mcp-server)
├── docker-compose.yml
└── pyproject.toml
```

---

## Extending

**Add a new agent tool:**
1. Add the function to `common/gitlab_client.py`
2. Add the tool definition to `TOOLS` in `common/agent.py`
3. Add the dispatch case in `_dispatch_tool`

**Add a new MCP tool:**
1. Add a `@mcp.tool()` decorated function in `mcp_server/main.py`

**Handle more webhook events** (e.g. issue comments, MR opened):
1. Add a new condition in `webhook_handler/main.py` → `webhook()`
