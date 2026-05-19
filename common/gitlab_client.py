"""
Thin wrapper around python-gitlab.
All GitLab I/O goes through here so the rest of the code stays testable.
"""
from __future__ import annotations

import gitlab
import structlog
from gitlab.v4.objects import Issue, Project

from common.config import settings

log = structlog.get_logger()


def get_client() -> gitlab.Gitlab:
    return gitlab.Gitlab(settings.gitlab_url, private_token=settings.gitlab_token)


def get_project(gl: gitlab.Gitlab, project_id: int | str) -> Project:
    return gl.projects.get(project_id)


# ---------------------------------------------------------------------------
# Issue helpers
# ---------------------------------------------------------------------------

def create_issue(
    project: Project,
    title: str,
    description: str = "",
    labels: list[str] | None = None,
    assignee_ids: list[int] | None = None,
) -> Issue:
    data: dict = {"title": title, "description": description}
    if labels:
        data["labels"] = ",".join(labels)
    if assignee_ids:
        data["assignee_ids"] = assignee_ids
    issue = project.issues.create(data)
    log.info("issue_created", project=project.path_with_namespace, iid=issue.iid, title=title)
    return issue


def post_issue_comment(project: Project, issue_iid: int, body: str) -> None:
    issue = project.issues.get(issue_iid)
    # Avoid duplicate comments: skip if agent tag already present
    for note in issue.notes.list(iterator=True):
        if settings.agent_comment_tag in note.body:
            log.info("comment_already_posted", issue_iid=issue_iid)
            return
    issue.notes.create({"body": f"{settings.agent_comment_tag}\n{body}"})
    log.info("comment_posted", issue_iid=issue_iid)


# ---------------------------------------------------------------------------
# Code browsing helpers (used as agent tools)
# ---------------------------------------------------------------------------

def list_directory(project: Project, path: str = "", ref: str = "HEAD") -> list[dict]:
    """Return files and directories at *path* in the repo."""
    try:
        items = project.repository_tree(path=path, ref=ref, all=True)
        return [{"name": i["name"], "type": i["type"], "path": i["path"]} for i in items]
    except gitlab.exceptions.GitlabGetError as e:
        log.warning("list_directory_failed", path=path, error=str(e))
        return []


def fetch_file(project: Project, file_path: str, ref: str = "HEAD") -> str | None:
    """Return decoded content of a file, or None if too large / not found."""
    try:
        f = project.files.get(file_path=file_path, ref=ref)
        size_kb = len(f.content) * 3 / 4 / 1024  # rough base64 estimate
        if size_kb > settings.agent_max_file_size_kb:
            log.info("file_too_large", path=file_path, size_kb=round(size_kb))
            return f"[File too large to include ({round(size_kb)} KB)]"
        return f.decode().decode("utf-8", errors="replace")
    except gitlab.exceptions.GitlabGetError as e:
        log.warning("fetch_file_failed", path=file_path, error=str(e))
        return None


def search_code(project: Project, query: str) -> list[dict]:
    """Full-text search across the project's codebase."""
    try:
        results = project.search(scope="blobs", search=query)
        return [
            {
                "file": r["filename"],
                "ref": r["ref"],
                "snippet": r["data"][:300],
            }
            for r in results[:10]  # cap at 10 results
        ]
    except gitlab.exceptions.GitlabSearchError as e:
        log.warning("search_code_failed", query=query, error=str(e))
        return []
