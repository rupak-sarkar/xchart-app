"""Optimized OpenAI-compatible OpenWork adapter for Gemini Enterprise.

Design goals:
- Keep one Discovery Engine session per OpenWork conversation for speed.
- Send full context only on the first request or after history divergence.
- Send only newly appended OpenWork messages on normal subsequent requests.
- Send full tool schemas only when the tool set changes.
- Keep corrections small and local.
- Quarantine the exact message delta that triggered an organization-policy block.
- Reset only the unhealthy Discovery session after a block, so the next small
  prompt starts clean without losing the OpenWork conversation.
- Preserve OpenAI-compatible synchronous and streaming responses.
"""
from __future__ import annotations

import codecs
import hashlib
import html
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict


# =============================================================================
# Configuration
# =============================================================================

HOST = os.getenv("HOST", "127.0.0.1").strip()
PORT = int(os.getenv("PORT", "4000"))
MODEL_ID = os.getenv("MODEL_ID", "gemini-3.8-flash").strip()
GE_PROJECT = os.getenv("GE_PROJECT", "520175819682").strip()
GE_LOCATION = os.getenv("GE_LOCATION", "global").strip()
GE_COLLECTION = os.getenv("GE_COLLECTION", "default_collection").strip()
GE_ENGINE = os.getenv("GE_ENGINE", "gemini-prod-global_1775193874909").strip()
GE_ASSISTANT = os.getenv("GE_ASSISTANT", "default_assistant").strip()
GE_AGENT_ID = os.getenv("GE_AGENT_ID", "9535301977005303947").strip()
GE_AGENT_VERSION = os.getenv("GE_AGENT_VERSION", "deployed").strip()
GE_TIME_ZONE = os.getenv("GE_TIME_ZONE", "Asia/Calcutta").strip()
GE_LANGUAGE_CODE = os.getenv("GE_LANGUAGE_CODE", "en-US").strip()
CREDENTIAL_FILE = Path(os.getenv("GE_CREDENTIAL_FILE", "service-account.json"))
DISCOVERY_API_ROOT = "https://discoveryengine.googleapis.com"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
HTTP_TIMEOUT_SECONDS = int(os.getenv("GE_HTTP_TIMEOUT_SECONDS", "600"))
TOKEN_REFRESH_BUFFER_SECONDS = int(os.getenv("GE_TOKEN_REFRESH_BUFFER_SECONDS", "300"))
CORRECTION_ATTEMPTS = int(os.getenv("CORRECTION_ATTEMPTS", "2"))
FINAL_STREAM_CHARS = int(os.getenv("FINAL_STREAM_CHARS", "28"))
STREAM_CHUNK_SIZE = 4096
SSE_HEARTBEAT_SECONDS = float(os.getenv("SSE_HEARTBEAT_SECONDS", "5"))

# Prompt budgets are character budgets, not model-token limits. They prevent one
# huge tool result or repeated transcript from dominating a request.
MAX_INITIAL_HISTORY_CHARS = int(os.getenv("MAX_INITIAL_HISTORY_CHARS", "120000"))
MAX_DELTA_HISTORY_CHARS = int(os.getenv("MAX_DELTA_HISTORY_CHARS", "70000"))
MAX_SINGLE_MESSAGE_CHARS = int(os.getenv("MAX_SINGLE_MESSAGE_CHARS", "50000"))
MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "24000"))
MAX_TOOL_ARGUMENT_CHARS = int(os.getenv("MAX_TOOL_ARGUMENT_CHARS", "10000"))
MAX_TOOL_DESCRIPTION_CHARS = int(os.getenv("MAX_TOOL_DESCRIPTION_CHARS", "900"))
MAX_PROPERTY_DESCRIPTION_CHARS = int(os.getenv("MAX_PROPERTY_DESCRIPTION_CHARS", "180"))
MAX_INVALID_RESPONSE_CHARS = int(os.getenv("MAX_INVALID_RESPONSE_CHARS", "12000"))
MAX_QUARANTINED_HASHES = int(os.getenv("MAX_QUARANTINED_HASHES", "256"))
DEV_BUILD = os.getenv("DEV_BUILD", "false").strip().lower() in {"1", "true", "yes", "on"}
DEV_RESPONSE_DIR = Path(os.getenv("DEV_RESPONSE_DIR", "dev_responses"))

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("openwork.gemini_enterprise_backend")
for logger_name in ("google", "urllib3", "uvicorn.access"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)

POLICY_BLOCK_RE = re.compile(
    r"(?:response\s+(?:was\s+)?blocked.*?(?:content|safety)\s+policy|"
    r"blocked.*?organi[sz]ation(?:'s)?\s+(?:content|safety)\s+policy|"
    r"customer_policy_violation|modelarmorviolation)",
    re.I | re.S,
)

# =============================================================================
# API models
# =============================================================================

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = MODEL_ID
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    stream: bool = False


class Decision(BaseModel):
    type: Literal["final", "tool_call"]
    content: str = ""
    name: str = ""
    arguments: dict[str, Any] | None = None


class BackendError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PreparedPrompt:
    key: str
    prompt: str
    all_hashes: list[str]
    sent_hashes: list[str]
    tools_hash: str
    message_total: int
    message_delta: int
    total_chars: int
    delta_chars: int
    tool_chars: int
    prompt_chars: int
    session_reused: bool
    history_reset: bool
    tools_resent: bool


@dataclass
class ConversationState:
    session: str
    synced_hashes: list[str] = field(default_factory=list)
    tools_hash: str = ""
    quarantined_hashes: list[str] = field(default_factory=list)
    last_used_at: float = field(default_factory=time.time)


@dataclass
class GeminiResult:
    answer: str
    blocked: bool
    events: list[dict[str, Any]]


# =============================================================================
# Streaming HTTP wrapper
# =============================================================================

class StreamingHttpResponse:
    def __init__(self, response: Any):
        self.response = response

    def iter_text(self) -> Iterator[str]:
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            while True:
                chunk = self.response.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        yield tail
                    return
                text = decoder.decode(chunk)
                if text:
                    yield text
        finally:
            self.response.close()


# =============================================================================
# Message and tool normalization
# =============================================================================

def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "[attachment]") if isinstance(item, dict) else str(item)
            for item in value
        )
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _strip_tagged_section(text: str, tag: str) -> str:
    return re.sub(
        rf"\s*<{re.escape(tag)}>.*?</{re.escape(tag)}>\s*",
        "\n",
        text,
        flags=re.I | re.S,
    )


def compact_system_content(text: str) -> str:
    """Preserve OpenWork instructions exactly as supplied by the client.

    OpenWork owns the agent prompt, workspace rules, permissions, and operating
    behavior. This compatibility backend must not remove, replace, or add its
    own behavioral persona. Only harmless excess blank lines are normalized.
    """
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _truncate_text(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    keep = max(limit - 120, 0)
    return text[:keep] + f"\n...[{label} truncated; original_chars={len(text)}]"


def _compact_json_value(value: Any, max_string: int = 4000) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, max_string, "value")
    if isinstance(value, list):
        return [_compact_json_value(item, max_string) for item in value]
    if isinstance(value, dict):
        return {key: _compact_json_value(child, max_string) for key, child in value.items()}
    return value


def normalized_messages(body: ChatRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in body.messages:
        role = str(message.get("role") or "")
        content = content_text(message.get("content"))
        if role == "system":
            content = compact_system_content(content)
        elif role == "tool":
            content = _truncate_text(content, MAX_TOOL_RESULT_CHARS, "tool result")
        else:
            content = _truncate_text(content, MAX_SINGLE_MESSAGE_CHARS, "message")

        row: dict[str, Any] = {"role": role, "content": content}

        if message.get("tool_calls"):
            compact_calls: list[dict[str, Any]] = []
            for call in message["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                arguments = content_text(fn.get("arguments"))
                compact_calls.append(
                    {
                        "id": call.get("id"),
                        "type": call.get("type", "function"),
                        "function": {
                            "name": fn.get("name"),
                            "arguments": _truncate_text(
                                arguments,
                                MAX_TOOL_ARGUMENT_CHARS,
                                "tool arguments",
                            ),
                        },
                    }
                )
            row["tool_calls"] = compact_calls

        if message.get("tool_call_id"):
            row["tool_call_id"] = message["tool_call_id"]

        result.append(row)
    return result


def message_hash(message: dict[str, Any]) -> str:
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tools(body: ChatRequest) -> list[dict[str, Any]]:
    result = []
    for item in body.tools or []:
        function = item.get("function") if item.get("type") == "function" else item
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            result.append(
                {
                    "name": function["name"],
                    "description": function.get("description") or "",
                    "parameters": function.get("parameters") or {"type": "object"},
                }
            )
    return result


def _compact_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "$schema":
            continue
        if key == "description" and isinstance(value, str):
            result[key] = _truncate_text(
                " ".join(value.split()),
                MAX_PROPERTY_DESCRIPTION_CHARS,
                "description",
            )
        elif key == "properties" and isinstance(value, dict):
            result[key] = {name: _compact_schema(spec) for name, spec in value.items()}
        elif key == "items":
            result[key] = _compact_schema(value)
        elif key in {"type", "required", "enum", "additionalProperties", "anyOf", "oneOf"}:
            result[key] = _compact_schema(value) if isinstance(value, dict) else value
    return result


def prompt_tools(body: ChatRequest) -> list[dict[str, Any]]:
    compacted = []
    for item in tools(body):
        compacted.append(
            {
                "name": item["name"],
                "description": _truncate_text(
                    " ".join(str(item["description"]).split()),
                    MAX_TOOL_DESCRIPTION_CHARS,
                    "tool description",
                ),
                "parameters": _compact_schema(item["parameters"]),
            }
        )
    return compacted


def tool_hash(body: ChatRequest) -> str:
    encoded = json.dumps(
        prompt_tools(body),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def conversation_key(body: ChatRequest) -> str:
    seed = []
    for message in body.messages:
        if message.get("role") in {"system", "user"}:
            value = content_text(message.get("content"))
            if message.get("role") == "system":
                value = compact_system_content(value)
            seed.append({"role": message.get("role"), "content": value})
        if len(seed) == 2:
            break
    return hashlib.sha256(
        json.dumps(seed, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def is_policy_message(message: dict[str, Any]) -> bool:
    return bool(POLICY_BLOCK_RE.search(content_text(message.get("content"))))


def causal_turn_hashes(
    rows: list[dict[str, Any]],
    hashes: list[str],
) -> list[str]:
    """Return only the most recent user turn and everything after it.

    If that request is blocked, older healthy conversation turns remain eligible
    for reconstruction. This prevents one oversized or policy-triggering task
    from causing the adapter to quarantine the entire conversation history.
    """
    last_user = -1
    for index, row in enumerate(rows):
        if row.get("role") == "user":
            last_user = index
    if last_user >= 0:
        return hashes[last_user:]
    return hashes[-1:] if hashes else []


def bounded_history(
    rows: list[dict[str, Any]],
    hashes: list[str],
    quarantined: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep system context plus the newest safe turns within the budget."""
    safe_pairs = [
        (row, digest)
        for row, digest in zip(rows, hashes)
        if digest not in quarantined and not is_policy_message(row)
    ]
    if not safe_pairs:
        return [], []

    system_pairs = [pair for pair in safe_pairs if pair[0].get("role") == "system"][:1]
    non_system = [pair for pair in safe_pairs if pair[0].get("role") != "system"]

    selected_reversed: list[tuple[dict[str, Any], str]] = []
    used = sum(len(json.dumps(row, ensure_ascii=False)) for row, _ in system_pairs)

    for row, digest in reversed(non_system):
        size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        if selected_reversed and used + size > limit:
            break
        selected_reversed.append((row, digest))
        used += size

    selected = system_pairs + list(reversed(selected_reversed))
    if len(selected) < len(safe_pairs):
        omitted = len(safe_pairs) - len(selected)
        note = {
            "role": "system",
            "content": f"[Older context omitted by Gemini adapter: {omitted} messages. Continue from the retained recent context.]",
        }
        insert_at = 1 if system_pairs else 0
        selected.insert(insert_at, (note, message_hash(note)))

    return [row for row, _ in selected], [digest for _, digest in selected]


# =============================================================================
# Prompt construction and synchronization
# =============================================================================

OUTPUT_CONTRACT = (
    "OPENWORK PROTOCOL BRIDGE: Follow the system instructions, workspace "
    "instructions, user messages, permissions, conversation context, and tool "
    "definitions supplied in this request. Do not invent tools, arguments, files, "
    "commands, results, or additional agent behavior. Return exactly one raw JSON "
    "object and no other text. For a tool action use "
    '{"type":"tool_call","name":"<exact_available_tool>","arguments":{}}. '
    "When no tool is required use "
    '{"type":"final","content":"<complete non-empty response>"}. '
    "The top-level type is mandatory. Never use args, parameters, tool, or "
    "function_call. Do not wrap the JSON object in Markdown."
)


def build_prompt(
    body: ChatRequest,
    state: ConversationState,
    key: str,
) -> PreparedPrompt:
    rows = normalized_messages(body)
    hashes = [message_hash(row) for row in rows]
    current_tools_hash = tool_hash(body)
    quarantined = set(state.quarantined_hashes)

    # Normal case: OpenWork appended new messages to the history already
    # synchronized into this Discovery session.
    prefix_ok = (
        len(hashes) >= len(state.synced_hashes)
        and hashes[: len(state.synced_hashes)] == state.synced_hashes
    )
    history_reset = bool(state.synced_hashes) and not prefix_ok
    first_sync = not state.synced_hashes or history_reset

    if first_sync:
        selected_rows, _ = bounded_history(
            rows,
            hashes,
            quarantined,
            MAX_INITIAL_HISTORY_CHARS,
        )
        delta_rows = selected_rows
        # If this request is blocked, quarantine only the current causal
        # user turn, not every historical message included for initial context.
        sent_hashes = [
            digest
            for digest in causal_turn_hashes(rows, hashes)
            if digest not in quarantined
        ]
        history_label = "CURRENT SAFE CONTEXT"
    else:
        delta_rows = []
        sent_hashes = []
        for row, digest in zip(rows[len(state.synced_hashes):], hashes[len(state.synced_hashes):]):
            if digest in quarantined or is_policy_message(row):
                continue
            delta_rows.append(row)
            sent_hashes.append(digest)

        delta_rows, _ = bounded_history(
            delta_rows,
            sent_hashes,
            set(),
            MAX_DELTA_HISTORY_CHARS,
        )
        # The delta can contain tool calls/results but no repeated user row.
        # Quarantine from the latest user turn in the complete history so one
        # problematic task can be omitted safely during recovery.
        sent_hashes = [
            digest
            for digest in causal_turn_hashes(rows, hashes)
            if digest not in quarantined
        ]
        history_label = "NEW ANTIGRAVITY EVENTS"

    tools_changed = current_tools_hash != state.tools_hash
    full_tools = prompt_tools(body) if first_sync or tools_changed else []
    names = [item["name"] for item in tools(body)]

    sections = [OUTPUT_CONTRACT]
    if full_tools:
        sections.append(
            "AVAILABLE TOOLS (schema):\n"
            + json.dumps(full_tools, ensure_ascii=False, separators=(",", ":"))
        )
    else:
        sections.append("AVAILABLE TOOLS (unchanged): " + ", ".join(names))

    sections.append(
        history_label
        + ":\n"
        + json.dumps(delta_rows, ensure_ascii=False, separators=(",", ":"))
    )
    sections.append("Produce the next response required by the supplied OpenWork context.")
    prompt = "\n\n".join(sections)

    total_chars = len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    delta_chars = len(json.dumps(delta_rows, ensure_ascii=False, separators=(",", ":")))
    tool_chars = len(json.dumps(full_tools, ensure_ascii=False, separators=(",", ":")))

    return PreparedPrompt(
        key=key,
        prompt=prompt,
        all_hashes=hashes,
        sent_hashes=sent_hashes,
        tools_hash=current_tools_hash,
        message_total=len(rows),
        message_delta=len(delta_rows),
        total_chars=total_chars,
        delta_chars=delta_chars,
        tool_chars=tool_chars,
        prompt_chars=len(prompt),
        session_reused=True,
        history_reset=history_reset,
        tools_resent=bool(full_tools),
    )


def correction_prompt(body: ChatRequest, raw: str, error: str) -> str:
    names = [item["name"] for item in tools(body)]
    return (
        "Correct only the previous protocol-format error. Preserve the supplied OpenWork instructions and return one raw JSON object.\n"
        'Allowed: {"type":"tool_call","name":"<available_tool>","arguments":{}} '
        'or {"type":"final","content":"<complete response>"}\n'
        f"Available tools: {', '.join(names)}\n"
        f"Validation error: {error}\n"
        "Invalid response:\n"
        + _truncate_text(raw, MAX_INVALID_RESPONSE_CHARS, "invalid response")
    )


# =============================================================================
# Gemini Enterprise backend
# =============================================================================

class GeminiEnterpriseBackend:
    def __init__(self) -> None:
        self._credentials: Any = None
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self._states: dict[str, ConversationState] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    def initialize(self) -> None:
        self._get_access_token()

    def _prefix(self) -> str:
        return (
            f"projects/{GE_PROJECT}/locations/{GE_LOCATION}/collections/"
            f"{GE_COLLECTION}/engines/{GE_ENGINE}"
        )

    def _lock_for(self, key: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    def _get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        with self._guard:
            if (
                self._token
                and self._token_expiry
                and now + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS) < self._token_expiry
            ):
                return self._token

            if self._credentials is None:
                path = CREDENTIAL_FILE.expanduser().resolve()
                if not path.is_file():
                    raise BackendError(f"Credential file not found: {path}")
                self._credentials = service_account.Credentials.from_service_account_file(
                    str(path),
                    scopes=list(SCOPES),
                )

            self._credentials.refresh(GoogleAuthRequest())
            self._token = self._credentials.token
            expiry = self._credentials.expiry
            self._token_expiry = (
                expiry
                if expiry and expiry.tzinfo
                else expiry.replace(tzinfo=timezone.utc)
                if expiry
                else now + timedelta(minutes=50)
            )
            if not self._token:
                raise BackendError("Google authentication returned no token")
            return self._token

    def _post(
        self,
        url: str,
        token: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> Any:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Goog-User-Project": GE_PROJECT,
            },
            method="POST",
        )
        try:
            response = urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)
            if stream:
                return StreamingHttpResponse(response)
            with response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:4000]
            raise BackendError(f"Gemini HTTP {error.code}: {body}", error.code) from error
        except URLError as error:
            raise BackendError(f"Gemini connection failed: {error}", 502) from error

    def _create_session(self, token: str, key: str) -> str:
        data = self._post(
            f"{DISCOVERY_API_ROOT}/v1alpha/{self._prefix()}/sessions",
            token,
            {"displayName": f"OpenWork {key[:24]}"},
        )
        session = str(data.get("name") or "")
        if not session:
            raise BackendError("Gemini did not return a session name", 502)
        return session

    def _events(self, token: str, session: str, prompt: str) -> list[dict[str, Any]]:
        response = self._post(
            f"{DISCOVERY_API_ROOT}/v1alpha/{self._prefix()}/assistants/{GE_ASSISTANT}:streamAssist",
            token,
            {
                "session": session,
                "query": {"parts": [{"text": prompt}]},
                "agentsConfig": {"agent": GE_AGENT_ID},
                "agentsSpec": {
                    "agentSpecs": [
                        {"agentId": GE_AGENT_ID, "version": GE_AGENT_VERSION}
                    ]
                },
                "answerGenerationMode": "AGENT",
                "assistSkippingMode": "REQUEST_ASSIST",
                "languageCode": GE_LANGUAGE_CODE,
                "userMetadata": {"timeZone": GE_TIME_ZONE},
            },
            stream=True,
        )
        decoder = json.JSONDecoder()
        buffer = ""
        events: list[dict[str, Any]] = []
        for chunk in response.iter_text():
            buffer += chunk
            while True:
                buffer = buffer.lstrip()
                if not buffer:
                    break
                if buffer[0] in "[,]":
                    buffer = buffer[1:]
                    continue
                try:
                    value, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                if isinstance(value, dict):
                    events.append(value)
                elif isinstance(value, list):
                    events.extend(item for item in value if isinstance(item, dict))
                buffer = buffer[end:]
        return events

    @staticmethod
    def _answer(events: list[dict[str, Any]]) -> str:
        parts: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("thought") is True:
                    return
                for key, child in value.items():
                    if key == "text" and isinstance(child, str) and child:
                        parts.append(child)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for event in events:
            answer = event.get("answer")
            if isinstance(answer, dict):
                walk(answer.get("replies") or answer.get("reply") or [])

        deduped: list[str] = []
        for part in parts:
            if not deduped or deduped[-1] != part:
                deduped.append(part)
        return html.unescape("".join(deduped)).strip()

    @staticmethod
    def _blocked(events: list[dict[str, Any]], answer: str) -> bool:
        if POLICY_BLOCK_RE.search(answer):
            return True
        for event in events:
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            if (
                "CUSTOMER_POLICY_VIOLATION" in payload
                or '"verdict":"BLOCK"' in payload
                or "modelArmorViolation" in payload
            ):
                return True
        return False

    def _save_dev_response(
        self,
        key: str,
        session: str,
        prompt: str,
        events: list[dict[str, Any]],
        answer: str,
    ) -> None:
        if not DEV_BUILD:
            return
        try:
            DEV_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            target = DEV_RESPONSE_DIR / f"gemini_response_{stamp}_{key[:12]}.json"
            target.write_text(
                json.dumps(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "conversation_key": key,
                        "session": session,
                        "prompt": prompt,
                        "raw_events": events,
                        "extracted_answer": answer,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            LOGGER.exception("Could not save development response")

    def ensure_state(self, key: str) -> ConversationState:
        with self._lock_for(key):
            state = self._states.get(key)
            if state:
                state.last_used_at = time.time()
                return state
            token = self._get_access_token()
            session = self._create_session(token, key)
            state = ConversationState(session=session)
            self._states[key] = state
            LOGGER.info("Created Gemini session | key=%s", key[:12])
            return state

    def execute(self, key: str, prompt: str) -> GeminiResult:
        with self._lock_for(key):
            state = self.ensure_state(key)
            token = self._get_access_token()
            events = self._events(token, state.session, prompt)
            answer = self._answer(events)
            blocked = self._blocked(events, answer)
            self._save_dev_response(key, state.session, prompt, events, answer)

            if not answer and not blocked:
                raise BackendError("Gemini returned no answer text", 502)

            return GeminiResult(answer=answer, blocked=blocked, events=events)

    def commit(self, prepared: PreparedPrompt) -> None:
        with self._lock_for(prepared.key):
            state = self._states.get(prepared.key)
            if not state:
                return
            # Track the full original normalized history prefix, not only the
            # bounded prompt representation. This enables true append-only deltas.
            state.synced_hashes = prepared.all_hashes
            state.tools_hash = prepared.tools_hash
            state.last_used_at = time.time()

    def quarantine_and_reset(self, prepared: PreparedPrompt) -> None:
        """Remove only the blocked delta from future Gemini prompts.

        OpenWork history remain intact. The adapter creates one
        replacement Discovery session on the next request because the old server-
        side session contains the blocked query. It does not create a new session
        for ordinary requests.
        """
        with self._lock_for(prepared.key):
            previous = self._states.get(prepared.key)
            quarantined = list(previous.quarantined_hashes if previous else [])
            for digest in prepared.sent_hashes:
                if digest not in quarantined:
                    quarantined.append(digest)
            quarantined = quarantined[-MAX_QUARANTINED_HASHES:]

            token = self._get_access_token()
            replacement = self._create_session(token, prepared.key + "-recovered")
            self._states[prepared.key] = ConversationState(
                session=replacement,
                quarantined_hashes=quarantined,
            )
            LOGGER.warning(
                "Policy block isolated | key=%s | quarantined=%d | replacement_session=true",
                prepared.key[:12],
                len(prepared.sent_hashes),
            )

    def reset_for_history_divergence(self, key: str) -> ConversationState:
        with self._lock_for(key):
            old = self._states.get(key)
            token = self._get_access_token()
            session = self._create_session(token, key + "-resync")
            state = ConversationState(
                session=session,
                quarantined_hashes=list(old.quarantined_hashes if old else []),
            )
            self._states[key] = state
            LOGGER.info("History divergence resync | key=%s", key[:12])
            return state


BACKEND = GeminiEnterpriseBackend()


# =============================================================================
# Action parsing and validation
# =============================================================================

def _action_score(value: dict[str, Any]) -> int:
    """Score only objects that plausibly represent an OpenWork action."""
    action_type = value.get("type")

    if action_type == "tool_call":
        if isinstance(value.get("name"), str) and isinstance(
            value.get("arguments"), dict
        ):
            return 100
        return 80

    if action_type == "final":
        return 100 if "content" in value else 80

    if isinstance(value.get("tool_call"), dict):
        return 70

    if isinstance(value.get("name"), str) and any(
        isinstance(value.get(key), dict) for key in ("arguments", "args")
    ):
        return 60

    if "content" in value and "name" not in value:
        return 40

    return 0


def parse_action(text: str) -> dict[str, Any]:
    """Extract the best action-shaped JSON object from a model response.

    Exact whole-response JSON is preferred. If surrounding text leaked, all
    parseable dictionaries are scored, preventing an inner arguments object or
    unrelated preamble object from being mistaken for the top-level action.
    """
    cleaned = html.unescape(text).strip()
    if POLICY_BLOCK_RE.search(cleaned):
        return {
            "type": "final",
            "content": (
                "The model response was blocked by the organization's content policy. "
                "The blocked request was isolated so the next smaller prompt can continue."
            ),
        }

    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    try:
        whole = json.loads(cleaned)
        if isinstance(whole, dict) and _action_score(whole) > 0:
            return whole
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for position, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[position:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        score = _action_score(value)
        if score > 0:
            candidates.append((score, -position, value))

    if not candidates:
        raise ValueError(
            "response did not contain a valid OpenWork action object"
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def normalize_action(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize only common, unambiguous model variations."""
    if "type" not in value and isinstance(value.get("tool_call"), dict):
        inner = value["tool_call"]
        arguments = inner.get("arguments")
        if not isinstance(arguments, dict):
            arguments = inner.get("args")
        return {
            "type": "tool_call",
            "name": inner.get("name"),
            "arguments": arguments if isinstance(arguments, dict) else {},
        }

    if "type" not in value and isinstance(value.get("name"), str):
        arguments = value.get("arguments")
        if not isinstance(arguments, dict):
            arguments = value.get("args")
        if isinstance(arguments, dict):
            return {
                "type": "tool_call",
                "name": value["name"],
                "arguments": arguments,
            }

    if "type" not in value and "content" in value and "name" not in value:
        return {"type": "final", "content": value["content"]}

    return value


def validate(value: dict[str, Any], body: ChatRequest) -> Decision:
    value = normalize_action(value)

    if value.get("type") == "final":
        content = value.get("content")
        # Compatibility for an older fallback format. The Gemini agent should
        # normally return a string, but safely serialize a structured fallback.
        if isinstance(content, (dict, list)):
            content = json.dumps(
                content,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("final.content must be a non-empty string")
        return Decision(type="final", content=content.strip())

    if value.get("type") != "tool_call":
        raise ValueError("type must be final or tool_call")

    by_name = {item["name"]: item for item in tools(body)}
    name = value.get("name")
    arguments = value.get("arguments")

    if name not in by_name:
        raise ValueError(f"unknown tool: {name!r}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")

    required = (by_name[name].get("parameters") or {}).get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"missing required arguments: {', '.join(missing)}")

    return Decision(type="tool_call", name=str(name), arguments=arguments)


def decide(body: ChatRequest) -> Decision:
    key = conversation_key(body)
    state = BACKEND.ensure_state(key)
    prepared = build_prompt(body, state, key)

    if prepared.history_reset:
        state = BACKEND.reset_for_history_divergence(key)
        prepared = build_prompt(body, state, key)

    LOGGER.info(
        "Prompt sync | key=%s | messages_total=%d | messages_delta=%d | "
        "total_chars=%d | delta_chars=%d | tool_chars=%d | prompt_chars=%d | "
        "tools_resent=%s | history_reset=%s",
        key[:12],
        prepared.message_total,
        prepared.message_delta,
        prepared.total_chars,
        prepared.delta_chars,
        prepared.tool_chars,
        prepared.prompt_chars,
        prepared.tools_resent,
        prepared.history_reset,
    )

    result = BACKEND.execute(key, prepared.prompt)
    if result.blocked:
        BACKEND.quarantine_and_reset(prepared)
        return Decision(
            type="final",
            content=(
                "The model response was blocked by the organization's content policy. "
                "The blocked request was isolated; send a smaller focused prompt to continue."
            ),
        )

    raw = result.answer
    for attempt in range(CORRECTION_ATTEMPTS + 1):
        LOGGER.info("Gemini response | attempt=%d | %s", attempt + 1, raw[:1200])
        try:
            decision = validate(parse_action(raw), body)
            BACKEND.commit(prepared)
            return decision
        except ValueError as error:
            LOGGER.warning("Invalid action | attempt=%d | %s", attempt + 1, error)
            if attempt >= CORRECTION_ATTEMPTS:
                raise BackendError(
                    f"Gemini failed the action contract: {error}",
                    502,
                ) from error
            correction = BACKEND.execute(
                key,
                correction_prompt(body, raw, str(error)),
            )
            if correction.blocked:
                BACKEND.quarantine_and_reset(prepared)
                return Decision(
                    type="final",
                    content=(
                        "The correction response was blocked by the organization's content policy. "
                        "The blocked request was isolated; send a smaller focused prompt to continue."
                    ),
                )
            raw = correction.answer

    raise BackendError("Gemini failed the action contract", 502)


# =============================================================================
# OpenAI-compatible response generation
# =============================================================================

def completion_id() -> str:
    return "chatcmpl_" + uuid.uuid4().hex


def sync_response(body: ChatRequest, decision: Decision) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": None}
    finish = "stop"
    if decision.type == "final":
        message["content"] = decision.content
    else:
        finish = "tool_calls"
        message["tool_calls"] = [
            {
                "id": "call_" + uuid.uuid4().hex[:24],
                "type": "function",
                "function": {
                    "name": decision.name,
                    "arguments": json.dumps(
                        decision.arguments or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
        ]
    return {
        "id": completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }


def text_chunks(text: str) -> Iterator[str]:
    position = 0
    while position < len(text):
        end = min(position + max(FINAL_STREAM_CHARS, 8), len(text))
        if end < len(text):
            boundary = max(text.rfind(" ", position, end), text.rfind("\n", position, end))
            if boundary > position:
                end = boundary + 1
        yield text[position:end]
        position = end


def _chunk(cid: str, created: int, model: str, delta: dict[str, Any], finish: str | None) -> str:
    payload = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def live_stream_response(body: ChatRequest) -> Iterator[str]:
    """Open SSE immediately, send heartbeats while Gemini is deciding.

    Partial Gemini JSON is never exposed. Final text is chunked after validation;
    tool calls are emitted atomically after validation.
    """
    cid = completion_id()
    created = int(time.time())
    yield _chunk(cid, created, body.model, {"role": "assistant"}, None)

    outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            outcome.put(("ok", decide(body)))
        except BaseException as error:
            outcome.put(("error", error))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        try:
            status, value = outcome.get(timeout=SSE_HEARTBEAT_SECONDS)
            break
        except queue.Empty:
            # SSE comment: keeps proxies and clients alive without adding assistant text.
            yield ": keep-alive\n\n"

    if status == "error":
        error = value
        message = str(error)
        LOGGER.exception("Streaming completion failed", exc_info=error)
        # Once SSE headers are sent, an HTTP status cannot be changed. Return a
        # normal assistant error message and close the stream cleanly.
        for piece in text_chunks("Gemini backend error: " + message):
            yield _chunk(cid, created, body.model, {"content": piece}, None)
        yield _chunk(cid, created, body.model, {}, "stop")
        yield "data: [DONE]\n\n"
        return

    decision: Decision = value
    if decision.type == "final":
        for piece in text_chunks(decision.content):
            yield _chunk(cid, created, body.model, {"content": piece}, None)
        finish = "stop"
    else:
        yield _chunk(
            cid,
            created,
            body.model,
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_" + uuid.uuid4().hex[:24],
                        "type": "function",
                        "function": {
                            "name": decision.name,
                            "arguments": json.dumps(
                                decision.arguments or {},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                ]
            },
            None,
        )
        finish = "tool_calls"

    yield _chunk(cid, created, body.model, {}, finish)
    yield "data: [DONE]\n\n"


# =============================================================================
# FastAPI application
# =============================================================================

app = FastAPI(
    title="Optimized Gemini Enterprise Backend for OpenWork",
    version="2.0.0",
)


@app.on_event("startup")
def startup() -> None:
    BACKEND.initialize()
    LOGGER.info(
        "Ready at http://%s:%d/v1 | model=%s | agent=%s | prompt_sync=delta",
        HOST,
        PORT,
        MODEL_ID,
        GE_AGENT_ID,
    )


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": app.title,
        "status": "ok",
        "base_url": f"http://{HOST}:{PORT}/v1",
        "prompt_mode": "session_delta",
    }


@app.get("/health")
@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_ID,
        "agent_id": GE_AGENT_ID,
        "active_sessions": len(BACKEND._states),
        "session_mode": "reused_with_incremental_context",
        "streaming": True,
        "prompt_optimization": {
            "delta_history": True,
            "tool_schema_cache": True,
            "policy_block_quarantine": True,
            "focused_corrections": True,
        },
    }


@app.get("/v1/models")
def model_list() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "gemini-enterprise",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(body: ChatRequest):
    started = time.perf_counter()
    available_tools = tools(body)
    LOGGER.info(
        "OpenWork request | messages=%d | tools=%d | names=%s | stream=%s",
        len(body.messages),
        len(available_tools),
        [item["name"] for item in available_tools],
        body.stream,
    )

    if body.stream:
        return StreamingResponse(
            live_stream_response(body),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    try:
        decision = decide(body)
        LOGGER.info(
            "Decision ready | type=%s | elapsed=%.2fs",
            decision.type,
            time.perf_counter() - started,
        )
        return JSONResponse(sync_response(body, decision))
    except BackendError as error:
        LOGGER.exception("Completion failed")
        raise HTTPException(error.status_code, str(error)) from error
    except Exception as error:
        LOGGER.exception("Completion failed")
        raise HTTPException(500, str(error)) from error


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
