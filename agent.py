"""
Agent orchestrator.

Given a GitLab issue, runs a tool-calling loop that:
  1. Reads the issue title + description
  2. Browses the codebase (list_directory, fetch_file, search_code)
  3. Produces a structured analysis comment

The loop is LLM-agnostic: it uses common.llm which delegates to LiteLLM.
"""
from __future__ import annotations

import json

import structlog
from gitlab.v4.objects import Project

from common import gitlab_client as gc
from common import llm
from common.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI-compatible, supported by LiteLLM for all backends)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories at a given path in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository path to list. Use empty string for root.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_file",
            "description": "Read the content of a file in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full path of the file to read.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Full-text search across the codebase. "
                "Use to find relevant files, function names, class names, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are a senior software engineer assistant embedded in a GitLab project.
Your job is to analyse a GitLab issue and help the team understand how to resolve or implement it.

You have access to tools to browse the repository:
- list_directory: explore the file tree
- fetch_file: read source files
- search_code: search for relevant identifiers or patterns

Workflow:
1. Read the issue carefully.
2. Use the tools to find relevant code (start broad with search_code, then read specific files).
3. Once you have enough context, write your analysis.

Your final response must be a Markdown comment structured as follows:
## 🤖 AI Analysis

### Summary
One paragraph describing what the issue is asking for.

### Relevant code
List the files/functions/classes you found that are relevant, with a brief explanation of each.

### Suggested approach
Concrete implementation or fix suggestions, with code snippets where useful.

### Open questions
Any ambiguities or decisions left to the team.

Be concise and actionable. Do not hallucinate file paths or function names you haven't verified with tools.\
"""


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _dispatch_tool(project: Project, name: str, arguments: dict) -> str:
    if name == "list_directory":
        result = gc.list_directory(project, path=arguments.get("path", ""))
        return json.dumps(result)
    elif name == "fetch_file":
        content = gc.fetch_file(project, file_path=arguments["file_path"])
        return content or "[File not found]"
    elif name == "search_code":
        result = gc.search_code(project, query=arguments["query"])
        return json.dumps(result)
    else:
        return f"[Unknown tool: {name}]"


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def analyse_issue(project: Project, issue_iid: int) -> str:
    """
    Run the agentic loop for a given issue.
    Returns the final Markdown comment to post.
    """
    issue = project.issues.get(issue_iid)
    log.info("agent_start", issue_iid=issue_iid, title=issue.title)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"**Issue #{issue.iid}: {issue.title}**\n\n"
                f"{issue.description or '_No description provided._'}"
            ),
        },
    ]

    for iteration in range(settings.agent_max_iterations):
        log.debug("agent_iteration", iteration=iteration)
        response = llm.chat(messages, tools=TOOLS)
        message = response.choices[0].message

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": message.content, "tool_calls": getattr(message, "tool_calls", None)})

        tool_calls = llm.extract_tool_calls(response)

        # No tool calls → the model is done, return its text
        if not tool_calls:
            final = llm.extract_text(response)
            log.info("agent_done", iterations=iteration + 1, chars=len(final))
            return final

        # Execute each tool call and feed results back
        for tc in tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            log.debug("tool_call", tool=fn_name, args=fn_args)

            result = _dispatch_tool(project, fn_name, fn_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    log.warning("agent_max_iterations_reached", issue_iid=issue_iid)
    return "_Agent reached maximum iterations without producing a final answer._"
