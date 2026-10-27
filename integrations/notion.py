"""Notion — search, read, and create pages.

Pattern follows PersonalJarvis's plugin-notion skill: search first,
read-first, confirm before overwriting. Uses the Notion REST API
directly (no MCP server needed).

Setup:
  1. notion.so/my-integrations -> New integration -> copy the
     "Internal Integration Secret" as NOTION_API_KEY in .env.
  2. In Notion, open each page/database you want JARVIS to touch ->
     "..." -> Add connections -> pick your integration.
"""
import requests

from config import NOTION_API_KEY
from integrations._common import tool

if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY not set")

BASE = "https://api.notion.com/v1"
H = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _page_title(page):
    for v in page.get("properties", {}).values():
        if v.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in v.get("title", []))
    return "(untitled)"


def search_notion(query):
    r = requests.post(BASE + "/search", headers=H,
                      json={"query": query, "page_size": 5}, timeout=15)
    r.raise_for_status()
    out = []
    for res in r.json().get("results", []):
        if res["object"] == "page":
            out.append(f"- {_page_title(res)} ({res['id']})")
        else:
            title = "".join(x.get("plain_text", "") for x in res.get("title", []))
            out.append(f"- [db] {title} ({res['id']})")
    return "\n".join(out) if out else "Nothing found in Notion."


def _blocks_text(blocks):
    out = []
    for b in blocks:
        data = b.get(b.get("type"), {})
        text = "".join(x.get("plain_text", "") for x in data.get("rich_text", []))
        if text:
            out.append(text)
    return "\n".join(out)


def read_notion_page(page_id):
    r = requests.get(BASE + f"/blocks/{page_id}/children", headers=H, timeout=15)
    r.raise_for_status()
    return _blocks_text(r.json().get("results", [])) or "(page is empty)"


def create_notion_page(title, content="", parent_page_id=None):
    if not parent_page_id:
        return ("To create a page I need a parent page id — search for the "
                "page you want it under and give me its id.")
    children = []
    if content:
        children.append({"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": [{"type": "text",
                                                      "text": {"content": content}}]}})
    r = requests.post(BASE + "/pages", headers=H, json={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": children,
    }, timeout=15)
    r.raise_for_status()
    return f"Created page '{title}' ({r.json()['id']})."


def query_notion_database(database_id):
    r = requests.post(BASE + f"/databases/{database_id}/query", headers=H,
                      json={"page_size": 10}, timeout=15)
    r.raise_for_status()
    rows = []
    for page in r.json().get("results", []):
        props = []
        for k, v in page.get("properties", {}).items():
            t = v.get("type")
            if t == "title":
                val = "".join(x.get("plain_text", "") for x in v.get("title", []))
            elif t == "rich_text":
                val = "".join(x.get("plain_text", "") for x in v.get("rich_text", []))
            elif t == "select":
                val = (v.get("select") or {}).get("name", "")
            elif t == "date":
                val = ((v.get("date") or {}).get("start", ""))
            elif t == "checkbox":
                val = str(v.get("checkbox"))
            else:
                continue
            if val:
                props.append(f"{k}: {val}")
        rows.append("- " + (" | ".join(props) if props else _page_title(page)))
    return "\n".join(rows) if rows else "Database is empty."


TOOLS = [
    tool("search_notion", "Search Notion pages and databases by title/keyword.",
         {"query": {"type": "string"}}, ["query"], search_notion),
    tool("read_notion_page", "Read the text of a Notion page by its id.",
         {"page_id": {"type": "string"}}, ["page_id"], read_notion_page),
    tool("create_notion_page", "Create a Notion page under a parent page.",
         {"title": {"type": "string"}, "content": {"type": "string"},
          "parent_page_id": {"type": "string"}}, ["title"], create_notion_page),
    tool("query_notion_database", "List the first 10 rows of a Notion database by its id.",
         {"database_id": {"type": "string"}}, ["database_id"], query_notion_database),
]
