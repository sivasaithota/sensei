"""LLM backend adapter — one structured-call interface, two backends.

    backend="api"          Anthropic SDK (needs ANTHROPIC_API_KEY)
    backend="claude-code"  local `claude -p` headless mode (uses your
                           Claude subscription login; zero marginal cost)

Selection order:
    1. explicit `client=` arg (tests pass mocks; always the SDK path)
    2. SENSEI_LLM_BACKEND env var ("api" | "claude-code")
    3. auto: "api" if ANTHROPIC_API_KEY is set, else "claude-code"

Every call is structured: the model must fill `schema`; the result is
a validated dict either way, so callers never see backend differences.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

MODEL = os.environ.get("SENSEI_MODEL", "claude-sonnet-4-6")
_CLI_MODEL = os.environ.get("SENSEI_CLI_MODEL", "claude-sonnet-4-6")


def backend() -> str:
    forced = os.environ.get("SENSEI_LLM_BACKEND")
    if forced in ("api", "claude-code"):
        return forced
    return "api" if os.environ.get("ANTHROPIC_API_KEY") else "claude-code"


def structured_call(*, system: str, user: str, schema: dict, name: str,
                    client=None) -> dict:
    """Return a dict matching `schema` (a JSON Schema with required keys)."""
    if client is not None or backend() == "api":
        return _api_call(system=system, user=user, schema=schema, name=name,
                         client=client)
    return _cli_call(system=system, user=user, schema=schema)


# ---- backend: Anthropic SDK ----

def _api_call(*, system: str, user: str, schema: dict, name: str, client=None) -> dict:
    import anthropic
    client = client or anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, system=system,
        tools=[{"name": name, "description": f"Deliver your {name}.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": name},
        messages=[{"role": "user", "content": user}],
    )
    return next(b.input for b in resp.content if b.type == "tool_use")


# ---- backend: local claude -p (subscription auth) ----

_NO_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit"


def _cli_call(*, system: str, user: str, schema: dict) -> dict:
    if shutil.which("claude") is None:
        raise RuntimeError(
            "claude-code backend selected but the `claude` CLI is not on PATH; "
            "install Claude Code or set ANTHROPIC_API_KEY / SENSEI_LLM_BACKEND=api")
    prompt = (
        f"{user}\n\n"
        f"Respond with ONLY a JSON object matching this schema — no prose, "
        f"no markdown fences:\n{json.dumps(schema)}"
    )
    # A sanitized env: agent sessions export ANTHROPIC_*/CLAUDE_* vars
    # (proxy URLs, session tokens) that break the CLI's own login.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("ANTHROPIC", "CLAUDE"))}
    proc = subprocess.run(
        ["claude", "-p", "--model", _CLI_MODEL, "--output-format", "json",
         "--disallowedTools", _NO_TOOLS,
         "--append-system-prompt", system],
        input=prompt, capture_output=True, text=True, timeout=300, env=env,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"claude -p failed: {proc.stderr[:500]}")
    wrapper = json.loads(proc.stdout)
    if wrapper.get("is_error"):
        raise RuntimeError(
            f"claude -p error: {wrapper.get('result', '')[:300]} "
            f"(if this is a 401, run `claude` in a terminal and /login, "
            f"or set ANTHROPIC_API_KEY to use the api backend)")
    text = wrapper.get("result", "")
    obj = _extract_json(text)
    missing = [k for k in schema.get("required", []) if k not in obj]
    if missing:
        raise RuntimeError(f"claude -p response missing keys {missing}: {text[:300]}")
    return obj


def _extract_json(text: str) -> dict:
    """Parse a JSON object from model text, tolerating markdown fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"no JSON object in response: {text[:300]}")
    return json.loads(text[start:end + 1])
