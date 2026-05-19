"""
MCP server — exposes GitLab tools to Claude (or any MCP client).

Tools exposed:
  - create_issue       : create a GitLab issue
  - list_issues        : list open issues on a project
  - get_issue          : get a single issue by IID
  - add_issue_comment  : add a comment to an existing issue

Run with:
  python -m mcp_server.main
or via the MCP CLI:
  mcp dev mcp_server/main.py
"""
from __future__ import annotations

import structlog
from mcp.server.fastmcp import FastMCP

from common import gitlab_client as gc
from common.config import settings

log = structlog.get_logger()

mcp = FastMCP(
    "gitlab-ai-agent",
    instructions=(
        "You have access to a GitLab instance. "
        "Use these tools to manage issues on behalf of the user."
    ),
)

# ---------------------------------------------------------------------------
# Tool helpers — lazy client init per call (MCP servers are long-lived)
# ---------------------------------------------------------------------------

def _project(project_id: int | str):
    gl = gc.get_client()
    return gc.get_project(gl, project_id)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def create_issue(
    project_id: str,
    title: str,
    description: str = "",
    labels: str = "",
) -> dict:
    """
    Create a new issue on a GitLab project.

    Args:
        project_id:  Project ID (numeric) or path like 'mygroup/myrepo'.
        title:       Issue title.
        description: Issue description (Markdown supported).
        labels:      Comma-separated labels, e.g. "bug,backend".
    """
    label_list = [l.strip() for l in labels.split(",") if l.strip()]
    project = _project(project_id)
    issue = gc.create_issue(project, title=title, description=description, labels=label_list)
    return {
        "iid": issue.iid,
        "id": issue.id,
        "title": issue.title,
        "url": issue.web_url,
        "state": issue.state,
    }


@mcp.tool()
def list_issues(
    project_id: str,
    state: str = "opened",
    labels: str = "",
    limit: int = 20,
) -> list[dict]:
    """
    List issues on a GitLab project.

    Args:
        project_id: Project ID or path.
        state:      'opened', 'closed', or 'all'.
        labels:     Comma-separated label filters.
        limit:      Maximum number of issues to return (max 100).
    """
    project = _project(project_id)
    params: dict = {"state": state, "per_page": min(limit, 100)}
    if labels:
        params["labels"] = labels
    issues = project.issues.list(**params)
    return [
        {
            "iid": i.iid,
            "title": i.title,
            "state": i.state,
            "labels": i.labels,
            "url": i.web_url,
            "created_at": i.created_at,
        }
        for i in issues
    ]


@mcp.tool()
def get_issue(project_id: str, issue_iid: int) -> dict:
    """
    Get details of a single issue.

    Args:
        project_id: Project ID or path.
        issue_iid:  Issue internal ID (the number shown in GitLab UI).
    """
    project = _project(project_id)
    issue = project.issues.get(issue_iid)
    return {
        "iid": issue.iid,
        "title": issue.title,
        "description": issue.description,
        "state": issue.state,
        "labels": issue.labels,
        "assignees": [a["username"] for a in issue.assignees],
        "url": issue.web_url,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
    }


@mcp.tool()
def add_issue_comment(project_id: str, issue_iid: int, body: str) -> dict:
    """
    Add a comment to an existing issue.

    Args:
        project_id: Project ID or path.
        issue_iid:  Issue internal ID.
        body:       Comment body (Markdown supported).
    """
    project = _project(project_id)
    issue = project.issues.get(issue_iid)
    note = issue.notes.create({"body": body})
    log.info("comment_added", issue_iid=issue_iid, note_id=note.id)
    return {"note_id": note.id, "url": f"{issue.web_url}#note_{note.id}"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
