"""The brain: an agent loop with swappable providers.

Provider order in "auto" mode:
  1. Groq (free tier, stupid fast LPU inference) if GROQ_API_KEY is set
  2. Ollama local (llama3.1:8b, free + offline)
  3. OpenRouter free model if OPENROUTER_API_KEY is set

Groq and OpenRouter speak the OpenAI chat API, so they share one tool
loop. Ollama has its own client. Every provider runs the same agent loop:
the model decides when to call a tool, the tool runs, the result goes
back to the model, and then it answers.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

import router
from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MODEL_FAST,
    JARVIS_BRAIN,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)
from persona import system_prompt
from tools import TOOLS

MAX_TOOL_TURNS = 6          # a normal task needs 1-3; more means it is flailing
HISTORY_TURNS = 8
RESULT_CAP = 6000           # chars of tool output sent back to the model
HTTP_TIMEOUT = 30           # seconds; was 120, which made failures feel like hangs


def _tool_map(tools=None):
    return {t["schema"]["function"]["name"]: t["function"] for t in (tools or TOOLS)}


def _run_calls(calls, tool_map, cache):
    """Run tool calls (parallel when there are several), skipping exact repeats.

    `calls` is a list of (name, args_dict_or_error_str). Returns result strings.
    """
    def one(item):
        name, args = item
        fn = tool_map.get(name)
        if fn is None:
            return f"Tool error: there is no tool called '{name}'."
        if isinstance(args, str):
            return f"Tool error: bad arguments ({args})."
        key = (name, json.dumps(args, sort_keys=True))
        if key in cache:
            return cache[key] + "\n(same call already done - do not repeat it)"
        try:
            out = str(fn(**args))
        except TypeError as e:
            out = f"Tool error: wrong arguments for {name}: {e}"
        except Exception as e:
            out = f"Tool error: {e}"
        out = out[:RESULT_CAP]
        if not out.startswith("Tool error"):
            cache[key] = out
        return out

    if len(calls) == 1:
        return [one(calls[0])]
    with ThreadPoolExecutor(max_workers=min(4, len(calls))) as ex:
        return list(ex.map(one, calls))


def _parse_args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return f"not valid JSON: {str(raw)[:80]}"


def _post(url, headers, payload):
    """POST with one short retry on rate limit/5xx, then let the caller fall back."""
    for attempt in (0, 1):
        r = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code in (429, 500, 502, 503) and attempt == 0:
            wait = min(float(r.headers.get("retry-after", 2) or 2), 4)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def _openai_loop(base_url, api_key, model, messages, tools):
    """Agent loop against any OpenAI-compatible endpoint (Groq, OpenRouter)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tool_map, schemas, cache = _tool_map(tools), [t["schema"] for t in tools], {}
    convo = [{"role": "system", "content": system_prompt()}] + list(messages)
    for _ in range(MAX_TOOL_TURNS):
        data = _post(base_url + "/chat/completions", headers,
                     {"model": model, "messages": convo, "tools": schemas})
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        convo.append({"role": "assistant", "content": msg.get("content") or "",
                      **({"tool_calls": calls} if calls else {})})
        if not calls:
            return msg.get("content") or "I didn't catch that."
        parsed = [(c["function"]["name"], _parse_args(c["function"].get("arguments"))) for c in calls]
        for c, result in zip(calls, _run_calls(parsed, tool_map, cache)):
            convo.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    return "I got stuck in a loop there - try asking that a different way."


def _ollama_loop(messages, tools):
    # lazy import: a broken/missing ollama install must not kill the
    # Groq/OpenRouter paths (e.g. a bad proxy env breaking httpx).
    import ollama

    client = ollama.Client(host=OLLAMA_HOST, timeout=60)
    tool_map, schemas, cache = _tool_map(tools), [t["schema"] for t in tools], {}
    convo = [{"role": "system", "content": system_prompt()}] + list(messages)
    for _ in range(MAX_TOOL_TURNS):
        resp = client.chat(model=OLLAMA_MODEL, messages=convo, tools=schemas)
        msg = resp.message
        tool_calls = list(msg.tool_calls or [])
        convo.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{"function": {"name": c.function.name,
                                         "arguments": c.function.arguments}}
                           for c in tool_calls],
        })
        if not tool_calls:
            return msg.content or "I didn't catch that."
        parsed = [(c.function.name, _parse_args(c.function.arguments)) for c in tool_calls]
        for result in _run_calls(parsed, tool_map, cache):
            convo.append({"role": "tool", "content": result})
    return "I got stuck in a loop there - try asking that a different way."


def ask(messages):
    """Run one agent turn. `messages` is a list of {role, content} dicts."""
    messages = messages[-HISTORY_TURNS:]
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    quick = router.fast_path(last, _tool_map())
    if quick is not None:                      # no model needed: instant + can't mis-route
        return quick
    tools = router.select_tools(messages, TOOLS)
    if router.is_school_request(messages):
        # School pages contain private education data. Keep both the prompt and
        # tool results on-device, even when the general-purpose brain uses Groq.
        ollama_host = urlsplit(OLLAMA_HOST).hostname
        if ollama_host not in ("localhost", "127.0.0.1", "::1"):
            return "School requests require Ollama on this laptop; school data was not sent to a remote host."
        if OLLAMA_MODEL.lower().endswith(":cloud"):
            return "School requests need a locally installed Ollama model; school data was not sent to a cloud model."
        try:
            return _ollama_loop(messages, tools)
        except Exception:
            return "Local Ollama is unavailable, so I couldn't complete that school request. School data was not sent to a cloud model."

    order = []
    if JARVIS_BRAIN in ("auto", "groq") and GROQ_API_KEY:
        order.append(("groq", lambda: _openai_loop(
            "https://api.groq.com/openai/v1", GROQ_API_KEY, GROQ_MODEL, messages, tools)))
        if GROQ_MODEL != GROQ_MODEL_FAST:
            order.append(("groq-fast", lambda: _openai_loop(
                "https://api.groq.com/openai/v1", GROQ_API_KEY, GROQ_MODEL_FAST, messages, tools)))
    if JARVIS_BRAIN in ("auto", "ollama"):
        order.append(("ollama", lambda: _ollama_loop(messages, tools)))
    if OPENROUTER_API_KEY:
        order.append(("openrouter", lambda: _openai_loop(
            "https://openrouter.ai/api/v1", OPENROUTER_API_KEY, OPENROUTER_MODEL, messages, tools)))

    errors = []
    for name, fn in order:
        try:
            return fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
    if not order:
        return ("No brain configured. Set GROQ_API_KEY in .env (free at "
                "console.groq.com) or run Ollama: ollama pull llama3.1:8b")
    return "I can't reach any brain. " + " | ".join(errors)
