"""One door to the language models, with the privacy rule built in.

private=True  -> LOCAL Ollama only (school data). Never Groq/OpenRouter.
private=False -> Groq (big, then fast) -> local Ollama -> OpenRouter, like brain.ask.
Returns {"content": str, "calls": [{"name": str, "args": dict}]}.
"""
import json
import re

from config import (GROQ_API_KEY, GROQ_MODEL, GROQ_MODEL_FAST, JARVIS_BRAIN, LOCAL_AGENT_MODEL,
                    OLLAMA_HOST, OPENROUTER_API_KEY, OPENROUTER_MODEL)
from edith_agent import privacy


class LLMUnavailable(RuntimeError):
    pass


def _args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _openai(base, key, model, messages, schemas):
    import brain
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    if schemas:
        payload["tools"] = schemas
    data = brain._post(base + "/chat/completions",
                       {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload)
    msg = data["choices"][0]["message"]
    calls = [{"name": c["function"]["name"], "args": _args(c["function"].get("arguments"))}
             for c in (msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "calls": calls}


def _local(messages, schemas):
    import ollama
    client = ollama.Client(host=OLLAMA_HOST, timeout=120)
    kw = {"tools": schemas} if schemas else {}
    resp = client.chat(model=LOCAL_AGENT_MODEL, messages=messages, options={"temperature": 0.1, "num_ctx": 8192}, **kw)
    msg = resp.message
    calls = [{"name": c.function.name, "args": _args(c.function.arguments)} for c in (msg.tool_calls or [])]
    return {"content": msg.content or "", "calls": calls}


def chat(messages, tools=None, private=False):
    schemas = [t["schema"] if "schema" in t else t for t in (tools or [])]
    if private:
        if not privacy.local_llm_available() or LOCAL_AGENT_MODEL.lower().endswith(":cloud"):
            raise privacy.PrivacyError(
                "That involves school data, which only a model on this laptop may see - and no local "
                "Ollama model is available. Install Ollama and run: ollama pull llama3.1:8b")
        try:
            return _local(messages, schemas)
        except Exception as e:
            raise privacy.PrivacyError(f"Local Ollama failed ({e}). School data was not sent to a cloud model.")
    errors, tried = [], False
    if JARVIS_BRAIN in ("auto", "groq") and GROQ_API_KEY:
        for model in dict.fromkeys((GROQ_MODEL, GROQ_MODEL_FAST)):
            tried = True
            try:
                return _openai("https://api.groq.com/openai/v1", GROQ_API_KEY, model, messages, schemas)
            except Exception as e:
                errors.append(f"groq {model}: {e}")
    if JARVIS_BRAIN in ("auto", "ollama"):
        tried = True
        try:
            return _local(messages, schemas)
        except Exception as e:
            errors.append(f"ollama: {e}")
    if OPENROUTER_API_KEY:
        tried = True
        try:
            return _openai("https://openrouter.ai/api/v1", OPENROUTER_API_KEY, OPENROUTER_MODEL, messages, schemas)
        except Exception as e:
            errors.append(f"openrouter: {e}")
    raise LLMUnavailable("No model reachable. " + (" | ".join(errors) if tried else
                         "Set GROQ_API_KEY in .env or run Ollama."))


def complete(system, user, private=False):
    """Plain text answer (summaries, extraction)."""
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                None, private=private)["content"].strip()


def parse_json(text):
    """Pull the first JSON object/array out of a model reply."""
    m = re.search(r"(\{.*\}|\[.*\])", text or "", re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(1))
