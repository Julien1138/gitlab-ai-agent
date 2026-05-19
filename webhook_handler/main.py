"""
Webhook handler — FastAPI service.

Receives GitLab system hooks / project webhooks and triggers the agent
when a new issue is opened.

Endpoint: POST /webhook
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks

from common import agent, gitlab_client as gc
from common.config import settings

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("webhook_handler_starting", gitlab_url=settings.gitlab_url, model=settings.llm_model)
    yield
    log.info("webhook_handler_stopped")


app = FastAPI(title="gitlab-ai-agent / webhook-handler", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(
    body: bytes,
    token: str | None,
    webhook_id: str | None,
    webhook_timestamp: str | None,
    webhook_signature: str | None,
) -> None:
    """Validate GitLab webhook authenticity.

    Priority:
      1. Signing secret (Standard Webhooks format, webhook-signature header) — recommended
      2. Legacy secret token (X-Gitlab-Token) — plain equality check
      3. Neither configured → skip (dev/test only)
    """
    if settings.gitlab_webhook_signing_secret:
        if not (webhook_id and webhook_timestamp and webhook_signature):
            raise HTTPException(status_code=401, detail="Missing webhook signature headers")

        # Standard Webhooks: signed content = "{id}.{timestamp}.{body}" as bytes
        to_sign = f"{webhook_id}.{webhook_timestamp}.".encode() + body

        secret = settings.gitlab_webhook_signing_secret
        if secret.startswith("whsec_"):
            secret = secret[len("whsec_"):]

        # Try base64-decoded key first (Standard Webhooks spec), then raw UTF-8
        keys: list[bytes] = [secret.encode()]
        try:
            keys.insert(0, base64.b64decode(secret))
        except Exception:
            pass

        # Header may carry multiple signatures: "v1,sig1 v1,sig2"
        for part in webhook_signature.split(" "):
            if not part.startswith("v1,"):
                continue
            received = part[3:]
            for key in keys:
                expected = base64.b64encode(
                    hmac.new(key, to_sign, hashlib.sha256).digest()
                ).decode()
                if hmac.compare_digest(received, expected):
                    return

        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if settings.gitlab_webhook_secret:
        if token != settings.gitlab_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook token")


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

def _handle_issue_event(project_id: int | str, issue_iid: int) -> None:
    try:
        gl = gc.get_client()
        project = gc.get_project(gl, project_id)
        comment = agent.analyse_issue(project, issue_iid)
        gc.post_issue_comment(project, issue_iid, comment)
    except Exception:
        log.exception("issue_handler_error", project_id=project_id, issue_iid=issue_iid)


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: str | None = Header(default=None),
    webhook_id: str | None = Header(default=None),
    webhook_timestamp: str | None = Header(default=None),
    webhook_signature: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    _verify_signature(body, x_gitlab_token, webhook_id, webhook_timestamp, webhook_signature)

    payload = await request.json()
    event = x_gitlab_event or payload.get("event_type", "")

    log.info("webhook_received", gitlab_event=event)

    # We only care about new issues labelled "bug"
    if event == "Issue Hook" and payload.get("object_attributes", {}).get("action") == "open":
        attrs = payload["object_attributes"]
        labels = [lbl.get("title", "") for lbl in attrs.get("labels", [])]

        if "bug" not in labels:
            log.info("issue_skipped_no_bug_label", labels=labels)
            return {"status": "ignored", "reason": "no 'bug' label"}

        project_id = payload["project"]["id"]
        issue_iid = attrs["iid"]

        log.info("new_bug_issue_detected", project_id=project_id, issue_iid=issue_iid)
        background_tasks.add_task(_handle_issue_event, project_id, issue_iid)
        return {"status": "accepted", "issue_iid": issue_iid}

    return {"status": "ignored", "event": event}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": settings.llm_model}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("webhook_handler.main:app", host="0.0.0.0", port=8000, reload=True)
