from __future__ import annotations

import json
import re
from typing import Dict


class CopilotResponseError(RuntimeError):
    """Raised when the intranet copilot returns content that is not usable JSON.

    Call sites enforce per-task schemas; this surfaces a clear, typed failure
    instead of silently returning ``{}`` (which would look like a valid-but-empty
    LLM answer and corrupt downstream cards/answers).
    """


class CopilotLLM:
    """Intranet copilot adapter for the LLM port.

    Boundary contract (read handoff/27 before editing):
      * The ONLY intranet-specific code lives in :meth:`_call_copilot` — the real
        transport (endpoint, auth, request/response shape) that cannot be tested
        on the external repo. opencode fills it in on the intranet.
      * Everything else here (port plumbing + :func:`_extract_json`) is generic,
        external-testable, and already done — reuse it, do not rewrite it.

    The adapter conforms to ``backend.ports.LLM`` (``complete_json`` /
    ``complete_text``). All prompts are sent verbatim and the JSON contract is
    enforced by each caller's schema (see the task list in handoff/27).
    """

    def __init__(self, config: Dict):
        self.config = config or {}
        # opencode wires real values from config["llm"] (base_url / model / auth /
        # api_key_env / ...). Kept permissive so the seam imports + constructs
        # cleanly on the external repo without intranet secrets.
        self.base_url = str(self.config.get("base_url", "")).rstrip("/")
        self.model = str(self.config.get("model", ""))

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema: Dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict:
        content = self._call_copilot(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            want_json=True,
        )
        return _extract_json(content)

    def complete_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        return self._call_copilot(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            want_json=False,
        )

    # ------------------------------------------------------------------
    # INTRANET-ONLY SEAM — opencode implements this on the intranet.
    # Do NOT add copilot endpoint/auth/SDK code anywhere outside this method.
    # ------------------------------------------------------------------
    def _call_copilot(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        want_json: bool,
    ) -> str:
        """Send (system, user) to the intranet copilot and return raw text content.

        Contract opencode must honour:
          * Return the copilot's message content as a ``str`` (for JSON calls it
            may be fenced / prose-wrapped — ``_extract_json`` will recover it; you
            do NOT need to parse JSON here).
          * When ``want_json`` is True, prefer the copilot's strict-JSON mode if it
            has one (e.g. response_format=json_object), but returning text is fine.
          * Pass ``temperature`` through (document it if the copilot ignores it).
          * On transport/auth/HTTP failure, raise a clear exception (not return "").
        """
        raise NotImplementedError(
            "CopilotLLM._call_copilot is the intranet integration seam. "
            "Implement the real copilot transport on the intranet per handoff/27."
        )


# ---------------------------------------------------------------------------
# Generic, external-testable JSON recovery (done — reuse, do not rewrite).
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json(content: str) -> Dict:
    """Recover a JSON object from a copilot reply.

    Tolerates the three things chat models routinely add around JSON:
    ```json fences, leading/trailing prose, and a single object embedded in text.
    Returns a ``dict`` (every LLM call site in this codebase expects an object).
    Raises :class:`CopilotResponseError` when nothing parseable is found.
    """
    text = (content or "").strip()
    if not text:
        raise CopilotResponseError("copilot returned empty content")

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    # Direct parse first (the happy path / strict-JSON mode).
    try:
        return _as_dict(json.loads(text))
    except json.JSONDecodeError:
        pass

    # Carve out the first balanced {...} and try again (prose-wrapped object).
    span = _first_object_span(text)
    if span is not None:
        try:
            return _as_dict(json.loads(span))
        except json.JSONDecodeError:
            pass

    raise CopilotResponseError(f"copilot did not return parseable JSON: {text[:200]!r}")


def _as_dict(value: object) -> Dict:
    if not isinstance(value, dict):
        raise CopilotResponseError(f"copilot returned JSON {type(value).__name__}, expected an object")
    return value


def _first_object_span(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, ignoring braces in strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
