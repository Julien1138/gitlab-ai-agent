from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- GitLab ---
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str  # personal or project access token
    gitlab_webhook_secret: str = ""          # legacy: exact token in X-Gitlab-Token
    gitlab_webhook_signing_secret: str = ""  # recommended: HMAC-SHA256 in X-Gitlab-Signature-256

    # --- LLM (LiteLLM format) ---
    # Examples:
    #   "claude-sonnet-4-20250514"        → Anthropic API
    #   "openai/gpt-4o"                   → OpenAI API
    #   "ollama/llama3"                   → local Ollama
    #   "openai/mistral-7b"               → vLLM compatible endpoint
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_base: str | None = None   # override for Ollama/vLLM (e.g. http://localhost:11434)
    llm_api_key: str | None = None    # not needed for Ollama

    # --- Agent behaviour ---
    agent_max_iterations: int = 10
    agent_max_file_size_kb: int = 100  # skip files larger than this
    agent_comment_tag: str = "<!-- gitlab-ai-agent -->"  # idempotency marker


settings = Settings()
