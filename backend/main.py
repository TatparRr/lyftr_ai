from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

import litellm
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from litellm import Cache, completion
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant.")
MODEL = os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash-lite")
CACHE_ENABLED = True
_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = RLock()
_CACHE_LIMIT = 256

# LiteLLM's local cache is enabled for every provider call. The small response
# index below lets the API reliably report whether that call was a cache hit.
litellm.cache = Cache(type="local")

app = FastAPI(title="Lyftr AI Chat", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)

origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Simulate-Failure"],
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1)
    system_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("session_id")
    @classmethod
    def session_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must not be empty")
        return value

    @field_validator("message")
    @classmethod
    def message_must_be_trimmed_and_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        if len(value) > 4000:
            raise ValueError("message must be at most 4000 characters")
        return value


@lru_cache(maxsize=1)
def configured_keys() -> tuple[str, ...]:
    return tuple(key.strip() for key in os.getenv("LLM_API_KEYS", "").split(",") if key.strip())


def database_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:////data/app.db")
    if not url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL must use SQLite")
    path = url[len("sqlite:///"):]
    if not path:
        raise RuntimeError("DATABASE_URL must include a database path")
    if path != ":memory:":
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return path


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with closing(connect_db()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
                ON messages(session_id, id);
            """
        )
        connection.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_signature(messages: list[dict[str, str]]) -> str:
    canonical = json.dumps({"model": MODEL, "messages": messages}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def token_count(value: Any, *, messages: list[dict[str, str]] | None = None) -> int:
    try:
        if messages is not None:
            count = litellm.token_counter(model=MODEL, messages=messages)
        else:
            count = litellm.token_counter(model=MODEL, text=str(value))
        return max(0, int(count))
    except Exception:
        text = json.dumps(messages, ensure_ascii=False) if messages is not None else str(value)
        return max(1, math.ceil(len(text.encode("utf-8")) / 4))


def usage_value(usage: Any, name: str, fallback: int) -> int:
    if usage is None:
        return fallback
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return max(0, int(value)) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def parse_simulated_failures(header_value: str | None, key_count: int) -> dict[str, int]:
    if not header_value or os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() != "true":
        return {}
    failures: dict[str, int] = {}
    allowed_statuses = {429, 500, 502, 503}
    valid_keys = {f"key_{index}" for index in range(1, key_count + 1)}
    for item in header_value.split(","):
        match = re.fullmatch(r"\s*(\*|key_[1-9][0-9]*)\s*=\s*(429|500|502|503)\s*", item)
        if not match:
            raise HTTPException(status_code=422, detail="invalid X-Simulate-Failure header")
        key_id, status_text = match.groups()
        if key_id != "*" and key_id not in valid_keys:
            raise HTTPException(status_code=422, detail="unknown key_id in X-Simulate-Failure header")
        status = int(status_text)
        if status not in allowed_statuses:
            raise HTTPException(status_code=422, detail="unsupported simulated status")
        failures[key_id] = status
    return failures


def reply_text(response: Any) -> str:
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("provider returned an empty reply")
    return content.strip()


def infer(messages: list[dict[str, str]], failures: dict[str, int]) -> tuple[str, dict[str, Any]]:
    keys = configured_keys()
    if not keys:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    signature = cache_signature(messages)
    started = time.perf_counter()
    with _CACHE_LOCK:
        cached = _CACHE.get(signature)
    if cached is not None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return cached["reply"], {
            "resolution_source": "LLM_CACHE",
            "model": MODEL,
            "latency_ms": elapsed_ms,
            "input_tokens": cached["input_tokens"],
            "output_tokens": cached["output_tokens"],
            "key_id": None,
            "fallback_attempts": 0,
        }

    failed_attempts = 0
    for index, api_key in enumerate(keys, start=1):
        key_id = f"key_{index}"
        if failures.get("*") is not None or failures.get(key_id) is not None:
            failed_attempts += 1
            continue
        try:
            response = completion(
                model=MODEL,
                messages=messages,
                api_key=api_key,
                caching=True,
                num_retries=0,
                timeout=60,
            )
            reply = reply_text(response)
            usage = getattr(response, "usage", None)
            input_tokens = usage_value(usage, "prompt_tokens", token_count(None, messages=messages))
            output_tokens = usage_value(usage, "completion_tokens", token_count(reply))
            elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
            metadata = {
                "resolution_source": "LIVE_INFERENCE",
                "model": MODEL,
                "latency_ms": elapsed_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "key_id": key_id,
                "fallback_attempts": failed_attempts,
            }
            with _CACHE_LOCK:
                _CACHE[signature] = {"reply": reply, "input_tokens": input_tokens, "output_tokens": output_tokens}
                if len(_CACHE) > _CACHE_LIMIT:
                    _CACHE.pop(next(iter(_CACHE)))
            return reply, metadata
        except Exception:
            failed_attempts += 1

    raise HTTPException(status_code=503, detail="all providers unavailable")


@app.get("/health")
def health() -> dict[str, Any]:
    keys = configured_keys()
    try:
        initialize_database()
        with closing(connect_db()) as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None
    if len(keys) < 2:
        raise HTTPException(status_code=503, detail="at least two provider keys are required")
    return {"status": "ok", "keys_configured": len(keys), "cache_enabled": CACHE_ENABLED}


@app.post("/chat")
def chat(
    payload: ChatRequest,
    x_simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
) -> dict[str, Any]:
    keys = configured_keys()
    failures = parse_simulated_failures(x_simulate_failure, len(keys))
    try:
        initialize_database()
        with closing(connect_db()) as connection:
            session = connection.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (payload.session_id,)
            ).fetchone()
            history = connection.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (payload.session_id,)
            ).fetchall()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None

    system_prompt = payload.system_prompt or (session["system_prompt"] if session else DEFAULT_SYSTEM_PROMPT)
    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages.extend({"role": row["role"], "content": row["content"]} for row in history)
    llm_messages.append({"role": "user", "content": payload.message})

    reply, metadata = infer(llm_messages, failures)
    timestamp = utc_now()
    try:
        with closing(connect_db()) as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, system_prompt, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt",
                (payload.session_id, system_prompt, timestamp),
            )
            connection.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
                (payload.session_id, payload.message, timestamp),
            )
            connection.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                (payload.session_id, reply, json.dumps(metadata), timestamp),
            )
            connection.commit()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"session_id": payload.session_id, "reply": reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str) -> dict[str, Any]:
    if not 1 <= len(session_id) <= 128 or not session_id.strip():
        raise HTTPException(status_code=422, detail="invalid session_id")
    try:
        initialize_database()
        with closing(connect_db()) as connection:
            session = connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            rows = connection.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
            ).fetchall()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None

    messages = []
    for row in rows:
        item: dict[str, Any] = {"role": row["role"], "content": row["content"]}
        if row["metadata"] is not None:
            item["metadata"] = json.loads(row["metadata"])
        messages.append(item)
    return {"session_id": session_id, "messages": messages}
