"""
The AI service, chosen by COPILOT_PROVIDER. The rest of the copilot speaks one
format (Anthropic's content blocks); other providers use the OpenAI-compatible
chat API and are translated here. Calls use the `requests` dependency the CRM
already has.
"""
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger("crmbook.copilot")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Free options for trying Copilot out; all speak the OpenAI-compatible API.
COMPATIBLE = {
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.8-flash",
               "embed_model": "gemini-embedding-001"},
    "groq": {"base": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "model": ""},
    "ollama": {"base": "http://localhost:11434/v1", "model": "llama3.1", "keyless": True},
}
# Some models spend part of this budget on thinking before they answer.
MIN_COMPATIBLE_TOKENS = 2048


class LLMError(Exception):
    """Safe to show to staff: never contains the key or customer data."""


def _provider():
    return COMPATIBLE.get(settings.COPILOT_PROVIDER)


def _key():
    return settings.COPILOT_API_KEY or (settings.ANTHROPIC_API_KEY if settings.COPILOT_PROVIDER == "anthropic" else "")


def _model():
    provider = _provider()
    if settings.COPILOT_MODEL:
        return settings.COPILOT_MODEL
    return provider["model"] if provider else "claude-sonnet-5-5"


def is_configured():
    provider = _provider()
    if provider is None and settings.COPILOT_PROVIDER != "anthropic":
        return False
    return bool(_model()) and bool(_key() or (provider and provider.get("keyless")))


def _not_configured():
    provider = settings.COPILOT_PROVIDER
    if provider == "anthropic":
        return "Copilot isn't set up yet: add ANTHROPIC_API_KEY to the backend environment."
    if provider not in COMPATIBLE:
        return f"COPILOT_PROVIDER must be anthropic or one of: {', '.join(COMPATIBLE)}."
    return f"Copilot isn't set up yet: add COPILOT_API_KEY (and COPILOT_MODEL if needed) for {provider} to the backend environment."


def _post(url, payload, headers):
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=settings.COPILOT_LLM_TIMEOUT)
    except requests.Timeout as exc:
        raise LLMError("The AI service took too long to answer. Try again.") from exc
    except requests.RequestException as exc:
        raise LLMError("Couldn't reach the AI service. Try again shortly.") from exc
    if response.status_code in (401, 403):
        raise LLMError("The AI service rejected the API key. Check the key in the backend environment.")
    if response.status_code == 429:
        raise LLMError("The AI service's rate limit was reached. Wait a minute and try again.")
    if response.status_code >= 400:
        logger.warning("AI service returned %s: %s", response.status_code, response.text[:300])
        raise LLMError("The AI service returned an error. Try again shortly.")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError("The AI service sent an unreadable answer. Try again.") from exc


def _compatible_messages(system, messages):
    out = [{"role": "system", "content": system}]
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
        elif message["role"] == "assistant":
            calls = []
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                call = {"id": block["id"], "type": "function", "function": {
                    "name": block["name"], "arguments": json.dumps(block.get("input") or {})}}
                if block.get("extra_content"):
                    call["extra_content"] = block["extra_content"]  # Gemini needs this returned with the call
                calls.append(call)
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
            out.append({"role": "assistant", "content": text or None, "tool_calls": calls})
        else:
            for block in content:
                out.append({"role": "tool", "tool_call_id": block.get("tool_use_id"), "content": block.get("content", "")})
    return out


def _from_compatible(data):
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("The AI service sent an unreadable answer. Try again.") from exc
    blocks = [{"type": "text", "text": message["content"]}] if message.get("content") else []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        block = {"type": "tool_use", "id": call.get("id"), "name": function.get("name"),
                 "input": arguments if isinstance(arguments, dict) else {}}
        if call.get("extra_content"):
            block["extra_content"] = call["extra_content"]
        blocks.append(block)
    return {"content": blocks, "stop_reason": "tool_use" if message.get("tool_calls") else "end_turn"}


def _complete_compatible(system, messages, tools, max_tokens):
    payload = {"model": _model(), "max_tokens": max(max_tokens, MIN_COMPATIBLE_TOKENS),
               "messages": _compatible_messages(system, messages)}
    if tools:
        payload["tools"] = [{"type": "function", "function": {
            "name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]}} for tool in tools]
    headers = {"Authorization": f"Bearer {_key()}"} if _key() else {}
    base = (settings.COPILOT_API_BASE or _provider()["base"]).rstrip("/")
    return _from_compatible(_post(f"{base}/chat/completions", payload, headers))


def complete(system, messages, tools=None, max_tokens=1500):
    """One model turn, as {"content": [...blocks], "stop_reason": ...}."""
    if not is_configured():
        raise LLMError(_not_configured())
    if _provider():
        return _complete_compatible(system, messages, tools, max_tokens)
    payload = {"model": _model(), "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        payload["tools"] = tools
    return _post(ANTHROPIC_URL, payload, {"x-api-key": _key(), "anthropic-version": ANTHROPIC_VERSION})


def _embed_provider():
    return settings.COPILOT_EMBED_PROVIDER or settings.COPILOT_PROVIDER


def embed_model():
    return settings.COPILOT_EMBED_MODEL or COMPATIBLE.get(_embed_provider(), {}).get("embed_model", "")


def _embed_key():
    return settings.COPILOT_EMBED_API_KEY or settings.COPILOT_API_KEY


def embeddings_configured():
    provider = COMPATIBLE.get(_embed_provider())
    return bool(provider and embed_model() and (_embed_key() or provider.get("keyless")))


def embed(texts):
    """Vectors for `texts`, through the provider's OpenAI-compatible /embeddings."""
    if not embeddings_configured():
        raise LLMError("Search isn't set up: add COPILOT_EMBED_MODEL (and COPILOT_EMBED_PROVIDER if needed). "
                       "Anthropic has no embeddings; use gemini or a local model for search.")
    name = _embed_provider()
    base = settings.COPILOT_EMBED_API_BASE or (settings.COPILOT_API_BASE if name == settings.COPILOT_PROVIDER else "")
    base = (base or COMPATIBLE[name]["base"]).rstrip("/")
    headers = {"Authorization": f"Bearer {_embed_key()}"} if _embed_key() else {}
    data = _post(f"{base}/embeddings", {"model": embed_model(), "input": texts}, headers)
    try:
        rows = sorted(data["data"], key=lambda row: row.get("index", 0))
        vectors = [row["embedding"] for row in rows]
    except (KeyError, TypeError, AttributeError) as exc:
        raise LLMError("The AI service sent unreadable embeddings. Check COPILOT_EMBED_MODEL.") from exc
    if len(vectors) != len(texts):
        raise LLMError("The AI service returned the wrong number of embeddings.")
    return vectors


def text_of(result):
    return "\n".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text").strip()
