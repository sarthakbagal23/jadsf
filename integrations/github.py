"""GitHub — repos, issues, files.

Same coverage as the github-mcp-server PersonalJarvis ships, minus the
MCP middleman: direct REST calls to the same endpoints, so the code stays
small and readable.

Setup: github.com/settings/tokens -> Generate new token (classic) with
`repo` scope -> set GITHUB_TOKEN in .env.
"""
import base64

import requests

from config import GITHUB_TOKEN
from integrations._common import tool

if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN not set")

BASE = "https://api.github.com"
H = {"Authorization": f"Bearer {GITHUB_TOKEN}",
     "Accept": "application/vnd.github+json"}


def list_repos():
    r = requests.get(BASE + "/user/repos",
                     headers=H, params={"per_page": 10, "sort": "updated"},
                     timeout=15)
    r.raise_for_status()
    return "\n".join(f"- {x['full_name']}" for x in r.json()) or "No repos."


def list_issues(repo):
    r = requests.get(BASE + f"/repos/{repo}/issues", headers=H,
                     params={"state": "open", "per_page": 10}, timeout=15)
    r.raise_for_status()
    out = [f"- #{x['number']}: {x['title']}" for x in r.json()]
    return "\n".join(out) if out else f"No open issues in {repo}."


def create_issue(repo, title, body=""):
    r = requests.post(BASE + f"/repos/{repo}/issues", headers=H,
                      json={"title": title, "body": body}, timeout=15)
    r.raise_for_status()
    d = r.json()
    return f"Created issue #{d['number']}: {title} ({d['html_url']})"


def get_file(repo, path, branch="main"):
    r = requests.get(BASE + f"/repos/{repo}/contents/{path}", headers=H,
                     params={"ref": branch}, timeout=15)
    r.raise_for_status()
    d = r.json()
    if d.get("encoding") == "base64":
        return base64.b64decode(d["content"]).decode("utf-8", "ignore")
    return str(d)


def search_code(query):
    r = requests.get(BASE + "/search/code", headers=H,
                     params={"q": query, "per_page": 5}, timeout=15)
    r.raise_for_status()
    out = [f"- {x['repository']['full_name']}/{x['path']}"
           for x in r.json().get("items", [])]
    return "\n".join(out) if out else "No code matches."


TOOLS = [
    tool("github_repos", "List your most recently updated GitHub repos.",
         {}, [], list_repos),
    tool("github_issues", "List open issues in a repo (owner/name).",
         {"repo": {"type": "string"}}, ["repo"], list_issues),
    tool("github_create_issue", "Create a GitHub issue.",
         {"repo": {"type": "string"}, "title": {"type": "string"},
          "body": {"type": "string"}}, ["repo", "title"], create_issue),
    tool("github_read_file", "Read a file from a GitHub repo.",
         {"repo": {"type": "string"}, "path": {"type": "string"},
          "branch": {"type": "string"}}, ["repo", "path"], get_file),
    tool("github_search_code", "Search code across GitHub.",
         {"query": {"type": "string"}}, ["query"], search_code),
]
