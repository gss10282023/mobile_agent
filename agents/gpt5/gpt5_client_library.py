"""
A reusable GPT-5 (OpenRouter) client library with:
- Built-in tools (web_search, fetch_url, get_time, read_file, write_file)
- Vision/image attachments (local path → data URL, or remote URL)
- Conversation state helpers (system prompt, history mgmt)
- Tool-calling loop (function calling)
- Resilient API wrapper with retry/backoff for transient 5xx/Cloudflare errors

Design goals:
- No CLI / REPL / rich UI; import and call from other scripts.
- Graceful degradation when optional deps are missing.
- Extensible: allow extra tools & registries to be injected.

Dependencies (minimal):
    pip install --upgrade openai

Optional (enable built-in tools fully):
    pip install --upgrade duckduckgo-search httpx trafilatura

Env:
    export OPENROUTER_API_KEY="..."
    # Optional telemetry headers for OpenRouter best practices:
    export OR_SITE_URL="https://your.site"
    export OR_SITE_TITLE="Your Site Name"

Usage (basic):
    from gpt5_client_library import Gpt5Client

    client = Gpt5Client()
    client.add_user_message("Hello!")
    resp = client.run_tools_loop()
    print(resp["choices"][0]["message"]["content"])  # final text (on success)

Usage (with an image and tools):
    client = Gpt5Client()
    client.attach_image("/path/to/local.png", caption="See this")
    client.add_user_message("Describe the image.")
    resp = client.run_tools_loop()

You can also pass extra tools/registries:
    tools = [{"type":"function", "function": {"name":"ping", "parameters":{"type":"object","properties":{}}}}]
    def ping(): return {"ok": True, "data": "pong"}
    client = Gpt5Client(extra_tools_schema=tools, extra_tool_registry={"ping": ping})
"""

from __future__ import annotations

import os
import json
import base64
import mimetypes
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Callable, Tuple

from openai import OpenAI

# Optional libs (graceful degradation if missing)
try:
    from duckduckgo_search import DDGS  # web search
except Exception:  # pragma: no cover
    DDGS = None  # type: ignore

try:
    import httpx  # robust HTTP client
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

try:
    import trafilatura  # article text extraction
except Exception:  # pragma: no cover
    trafilatura = None  # type: ignore

# -------- Exceptions compatibility layer (OpenAI SDK variants) --------
try:
    from openai import (  # type: ignore
        APIStatusError,
        APIConnectionError,
        RateLimitError,
        APITimeoutError,
        Timeout,
        InternalServerError,
    )
except Exception:  # pragma: no cover
    class _E(Exception):
        pass
    APIStatusError = _E  # type: ignore
    APIConnectionError = _E  # type: ignore
    RateLimitError = _E  # type: ignore
    InternalServerError = _E  # type: ignore
    try:
        from openai import Timeout as _Timeout  # type: ignore
        Timeout = _Timeout  # type: ignore
    except Exception:  # pragma: no cover
        class Timeout(_E):  # type: ignore
            pass
    try:
        from openai import APITimeoutError as _APITimeout  # type: ignore
        APITimeoutError = _APITimeout  # type: ignore
    except Exception:  # pragma: no cover
        APITimeoutError = Timeout  # type: ignore

DEFAULT_MODEL = os.environ.get("OR_MODEL", "openai/gpt-5")

__all__ = [
    "Gpt5Client",
    "DEFAULT_MODEL",
    # Built-in tool APIs (exported in case you want to reuse them directly)
    "tool_web_search",
    "tool_fetch_url",
    "tool_get_time",
    "tool_read_file",
    "tool_write_file",
    "build_builtin_tools_json",
]

# ------------------------------ Built-in Tool Implementations ------------------------------

def tool_web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web with DuckDuckGo (no API key needed).
    Returns: {ok: bool, results?: [{title,url,snippet,source}], error?: str}
    """
    if DDGS is None:
        return {
            "ok": False,
            "error": "duckduckgo-search not installed. pip install duckduckgo-search",
        }
    results: List[Dict[str, Any]] = []
    with DDGS() as ddgs:  # type: ignore
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body"),
                "source": r.get("source"),
            })
    return {"ok": True, "results": results}


def tool_fetch_url(url: str, max_chars: int = 6000, timeout: float = 15.0) -> Dict[str, Any]:
    """Fetch a URL and return title + extracted text (if possible).
    Returns: {ok: bool, title?: str, url?: str, content?: str, content_type?: str, error?: str}
    """
    if httpx is None:
        return {"ok": False, "error": "httpx not installed. pip install httpx"}
    try:
        headers = {
            "User-Agent": "gpt5-client/1.0 (+https://openrouter.ai)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:  # type: ignore
            resp = client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text
        title = None
        extracted = None
        if "html" in content_type and trafilatura is not None:
            extracted = trafilatura.extract(text, include_comments=False, include_images=False)  # type: ignore
            if extracted:
                doc = trafilatura.bare_extraction(text, include_comments=False)  # type: ignore
                title = (doc or {}).get("title") if isinstance(doc, dict) else None
        if extracted is None:
            extracted = text
        if title is None:
            # Try to parse <title> cheaply
            import re
            m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
            if m:
                title = m.group(1).strip()
        if extracted and len(extracted) > max_chars:
            extracted = extracted[:max_chars] + "\n... [truncated]"
        return {
            "ok": True,
            "title": title,
            "url": url,
            "content": extracted,
            "content_type": content_type,
        }
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_get_time(tz: Optional[str] = None) -> Dict[str, Any]:
    """Return current time (ISO/epoch), using IANA timezone if provided or env TIMEZONE else UTC.
    Returns: {ok: True, iso: str, epoch: float, tz: str}
    """
    try:
        if tz:
            z = ZoneInfo(tz)
        else:
            env_tz = os.environ.get("TIMEZONE")
            z = ZoneInfo(env_tz) if env_tz else timezone.utc
    except Exception:
        z = timezone.utc
    now = datetime.now(tz=z)
    return {"ok": True, "iso": now.isoformat(), "epoch": now.timestamp(), "tz": str(z)}


def tool_read_file(path: str, max_bytes: int = 1_000_000) -> Dict[str, Any]:
    """Read a local text file (<=1MB). Returns {ok, path, size, content} or {ok:False,error}."""
    p = Path(path).expanduser().absolute()
    if not p.exists():
        return {"ok": False, "error": f"File not found: {p}"}
    if p.is_dir():
        return {"ok": False, "error": f"Path is a directory: {p}"}
    size = p.stat().st_size
    if size > max_bytes:
        return {"ok": False, "error": f"File too large: {size} bytes > {max_bytes}"}
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": str(p), "size": size, "content": data}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_write_file(path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
    """Write text content to a local file. Returns {ok, path} or {ok:False,error}."""
    p = Path(path).expanduser().absolute()
    if p.exists() and not overwrite:
        return {"ok": False, "error": f"File exists: {p} (use overwrite=True)"}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p)}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ------------------------------ Helpers ------------------------------

def file_to_data_url(path: str) -> str:
    """Convert a local file to a data URL (useful for images in vision messages)."""
    p = Path(path).expanduser().absolute()
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")
    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_builtin_tools_json() -> List[Dict[str, Any]]:
    """Schemas for built-in function calling tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public internet (DuckDuckGo). Useful to find recent information and links.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Download a web page by URL and extract readable text when possible.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer", "default": 6000},
                        "timeout": {"type": "number", "default": 15.0},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get the current time in a specified timezone (IANA tz).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tz": {"type": "string", "description": "IANA timezone like 'Australia/Sydney'"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a small local text file (<=1MB).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer", "default": 1000000},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write a local text file. Overwrites by default.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean", "default": True},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    ]


DEFAULT_TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {
    "web_search": tool_web_search,
    "fetch_url": tool_fetch_url,
    "get_time": tool_get_time,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
}

# ------------------------------ Resilient API wrapper ------------------------------

TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}

def _looks_like_cloudflare_html(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    keys = ("cloudflare", "cf-error-code", "temporarily unavailable", "ray id", "cdn-cgi")
    return any(k in t for k in keys)

def _err_status_and_text(e: Exception) -> Tuple[Optional[int], str]:
    status = getattr(e, "status_code", None)
    resp = getattr(e, "response", None)
    text = ""
    if status is None and resp is not None:
        status = getattr(resp, "status_code", None)
    if hasattr(resp, "text"):
        try:
            text = resp.text  # type: ignore[attr-defined]
        except Exception:
            text = str(e)
    else:
        text = str(e)
    return status, text

def safe_chat_create(client: OpenAI, **kwargs):
    """Wrapper for chat.completions.create with retry/backoff and Cloudflare HTML detection."""
    max_tries = kwargs.pop("max_tries", 8)
    backoff = kwargs.pop("backoff", 0.5)
    cap = kwargs.pop("cap", 90.0)

    for i in range(max_tries):
        try:
            return client.chat.completions.create(**kwargs)
        except (APIStatusError, InternalServerError) as e:
            status, text = _err_status_and_text(e)
            if (status in TRANSIENT_STATUS) or _looks_like_cloudflare_html(text):
                sleep = min(cap, backoff * (2 ** i)) * (0.8 + 0.4 * random.random())
                time.sleep(sleep)
                continue
            raise
        except (APIConnectionError, RateLimitError, Timeout, APITimeoutError) as _:
            sleep = min(cap, backoff * (2 ** i)) * (0.8 + 0.4 * random.random())
            time.sleep(sleep)
            continue
        except Exception as e:
            if _looks_like_cloudflare_html(str(e)):
                sleep = min(cap, backoff * (2 ** i)) * (0.8 + 0.4 * random.random())
                time.sleep(sleep)
                continue
            raise
    raise RuntimeError("Upstream temporarily unavailable after retries (Cloudflare/OpenRouter 5xx/429).")

# ------------------------------ Client ------------------------------

class Gpt5Client:
    """A reusable OpenRouter client with vision + built-in tools + tool-calling loop.

    Attributes:
        model: model name (default from OR_MODEL or 'openai/gpt-5-mini')
        client: OpenAI client
        messages: chat history (list of dicts)
        pending_images: content parts to be attached to the next user message
        tools_schema: list of tool schemas (built-in + optional extra)
        tool_registry: callable registry mapping tool name -> function
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        site_url: Optional[str] = os.environ.get("OR_SITE_URL"),
        site_title: Optional[str] = os.environ.get("OR_SITE_TITLE"),
        system_prompt: Optional[str] = None,
        enable_builtin_tools: bool = True,
        extra_tools_schema: Optional[List[Dict[str, Any]]] = None,
        extra_tool_registry: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY not set. Export it or pass api_key=")

        # Disable SDK internal retries; use our own safe_chat_create for consistent behavior.
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
            max_retries=0,
            timeout=60.0,
        )
        self.extra_headers: Dict[str, str] = {}
        if site_url:
            self.extra_headers["HTTP-Referer"] = site_url
        if site_title:
            self.extra_headers["X-Title"] = site_title

        self.model = model
        self.messages: List[Dict[str, Any]] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
        self.pending_images: List[Dict[str, Any]] = []

        self.tools_schema: List[Dict[str, Any]] = []
        if enable_builtin_tools:
            self.tools_schema.extend(build_builtin_tools_json())
        if extra_tools_schema:
            self.tools_schema.extend(extra_tools_schema)

        # Merge registries (extra overrides built-ins on name clash)
        self.tool_registry: Dict[str, Callable[..., Any]] = dict(DEFAULT_TOOL_REGISTRY) if enable_builtin_tools else {}
        if extra_tool_registry:
            self.tool_registry.update(extra_tool_registry)

    # --------- Conversation helpers ---------
    def set_model(self, model: str) -> None:
        self.model = model

    def set_system_prompt(self, text: str) -> None:
        # Replace or insert system message
        for m in self.messages:
            if m.get("role") == "system":
                m["content"] = text
                return
        self.messages.insert(0, {"role": "system", "content": text})

    def add_user_message(self, text: str) -> None:
        content: List[Dict[str, Any]] = []
        if text.strip():
            content.append({"type": "text", "text": text})
        content.extend(self.pending_images)
        self.pending_images.clear()
        self.messages.append({"role": "user", "content": content or [{"type": "text", "text": ""}]})

    def attach_image(self, path_or_url: str, caption: Optional[str] = None) -> None:
        # Accept http(s)/data URLs or local file path → data URL
        if path_or_url.lower().startswith(("http://", "https://", "data:")):
            image_url = path_or_url
        else:
            image_url = file_to_data_url(path_or_url)
        if caption:
            self.pending_images.append({"type": "text", "text": caption})
        self.pending_images.append({"type": "image_url", "image_url": {"url": image_url}})

    def clear_history(self, keep_system: bool = True) -> None:
        if keep_system:
            sys_msgs = [m for m in self.messages if m.get("role") == "system"]
            self.messages = sys_msgs
        else:
            self.messages = []

    # --------- Core tool-calling loop ---------
    def run_tools_loop(self, max_hops: int = 8) -> Dict[str, Any]:
        """Call chat API; execute any requested tools; feed results back until final answer.
        Returns the last OpenAI response (dict via model_dump()) on success.
        On transient failure, returns {"ok": False, "error": "...", "status_code": int|None, "detail": "..."}.
        """
        hop = 0
        last_response = None
        tools = self.tools_schema or None
        tool_choice = "auto" if tools else None

        while hop < max_hops:
            hop += 1
            try:
                response = safe_chat_create(
                    self.client,
                    model=self.model,
                    messages=self.messages,
                    extra_headers=self.extra_headers,
                    tools=tools,
                    tool_choice=tool_choice,
                    max_tries=6,
                    backoff=0.6,
                    cap=60.0,
                )
            except Exception as e:
                status, _text = _err_status_and_text(e)
                return {
                    "ok": False,
                    "error": "transient_api_error",
                    "status_code": status,
                    "detail": str(e)[:800],
                }

            last_response = response
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                # Append assistant tool-call request
                self.messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })
                # Execute tools and append tool results
                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    func = self.tool_registry.get(name)
                    if not func:
                        result = {"ok": False, "error": f"Unknown tool: {name}"}
                    else:
                        try:
                            # Try **kwargs first, fallback to single-arg style
                            try:
                                result = func(**args)  # type: ignore[arg-type]
                            except TypeError:
                                result = func(args)  # type: ignore[misc]
                        except Exception as ex:  # pragma: no cover
                            result = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                # Let the model see tool results, continue loop
                continue
            else:
                # Final assistant message
                self.messages.append({"role": "assistant", "content": msg.content or ""})
                break

        if not last_response:
            return {"ok": False, "error": "no_response"}

        # Convert to dict
        try:
            return last_response.model_dump()
        except Exception:
            # As a fallback, serialize minimally
            return json.loads(last_response.json()) if hasattr(last_response, "json") else {"ok": False, "error": "serialize_failed"}

    # --------- Utility: export transcript ---------
    def save_markdown(self, path: str) -> str:
        p = Path(path).expanduser().absolute()
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Chat Transcript", ""]
        for m in self.messages:
            role = m.get("role", "")
            content = m.get("content")
            if isinstance(content, list):
                parts: List[str] = []
                for c in content:
                    if c.get("type") == "text":
                        parts.append(c.get("text", ""))
                    elif c.get("type") == "image_url":
                        parts.append(f"[image]({c.get('image_url', {}).get('url', '')})")
                text = "\n".join(parts)
            else:
                text = str(content)
            lines.append(f"**{role}**:\n\n{text}\n")
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)
