"""Shared helpers for the paper test notebooks.

Every notebook does ``from common import *`` (or explicit imports). The helpers cover:

* environment loading from the repo-root ``.env`` (``OPENROUTER_API_KEY``, ``RCP_MODEL``,
  ``RCP_BASE_URL``) — the same variables the RCP platform uses;
* a thin OpenRouter chat client (OpenAI-compatible) with JSON parsing/retry and a usage
  tracker so each notebook can report how many calls/tokens it spent;
* vendoring helpers that fetch third-party code at a pinned commit into ``notebooks/vendor``
  (gitignored) and apply a small patch;
* the ``QUICK`` flag (``NB_QUICK=1``) that every notebook uses to shrink budgets.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NB_DIR = Path(__file__).resolve().parent
REPO_ROOT = NB_DIR.parent
VENDOR_DIR = NB_DIR / "vendor"
OUTPUT_DIR = NB_DIR / "outputs"
VENDOR_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

QUICK = os.environ.get("NB_QUICK", "0") not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- env / model
def load_env() -> dict[str, str]:
    """Load the repo-root .env (without overriding already-exported variables)."""
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    cfg = {
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "model": os.environ.get("RCP_MODEL", "deepseek/deepseek-v4-flash"),
        "base_url": os.environ.get("RCP_BASE_URL", "https://openrouter.ai/api/v1"),
    }
    if not cfg["api_key"]:
        raise RuntimeError("OPENROUTER_API_KEY is not set; fill in the repo-root .env first")
    return cfg


ENV = None


def env() -> dict[str, str]:
    global ENV
    if ENV is None:
        ENV = load_env()
    return ENV


# --------------------------------------------------------------------------- usage tracking
@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    by_tag: dict[str, int] = field(default_factory=dict)

    def add(self, usage: Any, seconds: float, tag: str) -> None:
        self.requests += 1
        self.seconds += seconds
        if usage is not None:
            self.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            self.cost_usd += float(getattr(usage, "cost", 0.0) or 0.0)  # OpenRouter reports cost
        self.by_tag[tag] = self.by_tag.get(tag, 0) + 1

    def summary(self) -> str:
        return (
            f"{self.requests} requests, {self.input_tokens} in / {self.output_tokens} out tokens, "
            f"{self.seconds:.0f}s in model calls, ${self.cost_usd:.4f}; by tag: {dict(sorted(self.by_tag.items()))}"
        )


USAGE = Usage()


# --------------------------------------------------------------------------- chat client
_client = None


def client():
    """Singleton OpenAI-SDK client pointed at OpenRouter."""
    global _client
    if _client is None:
        from openai import OpenAI

        e = env()
        _client = OpenAI(api_key=e["api_key"], base_url=e["base_url"], timeout=300, max_retries=2)
    return _client


def chat(
    prompt: str,
    system: str = "",
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    model: str | None = None,
    tag: str = "chat",
    messages: list[dict[str, str]] | None = None,
    reasoning: str | None = None,
) -> str:
    """One chat completion; returns the text. ``messages`` overrides prompt/system if given.

    ``reasoning`` controls hidden chain-of-thought on reasoning models via OpenRouter's
    ``reasoning`` field: ``"off"`` disables it, ``"low"|"medium"|"high"`` sets the effort, and
    None uses ``NB_REASONING`` (default ``"off"``). Reasoning tokens count against ``max_tokens``,
    so long code-generation prompts are cut off before any code appears unless it is capped.
    """
    if messages is None:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
    reasoning = reasoning or os.environ.get("NB_REASONING", "off")
    extra = {"reasoning": {"enabled": False}} if reasoning == "off" else {"reasoning": {"effort": reasoning}}
    t0 = time.time()
    resp = client().chat.completions.create(
        model=model or env()["model"],
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra,
    )
    USAGE.add(getattr(resp, "usage", None), time.time() - t0, tag)
    choice = resp.choices[0]
    content = choice.message.content or ""
    if choice.finish_reason == "length":
        content += "\n[TRUNCATED: hit max_tokens]"
    return content


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply (tolerates code fences and prose)."""
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError(f"no JSON found in model output: {text[:200]!r}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def chat_json(
    prompt: str,
    system: str = "",
    *,
    retries: int = 2,
    tag: str = "chat_json",
    validate=None,
    **kw,
) -> Any:
    """Chat and parse JSON; retries with the parse error appended when parsing/validation fails."""
    sys_text = (system + "\n\n" if system else "") + (
        "Respond with ONLY a JSON value (no prose, no code fences)."
    )
    p = prompt
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        raw = chat(p, sys_text, tag=tag, **kw)
        try:
            obj = extract_json(raw)
            if validate is not None:
                validate(obj)
            return obj
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc} | reply tail: {raw[-300:]!r}"
            p = prompt + f"\n\nYour previous reply was invalid ({type(exc).__name__}: {exc}). Reply with valid JSON only."
    raise ValueError(f"model did not return valid JSON after {retries + 1} attempts: {last_err}")


def extract_code_block(text: str, lang: str = "python") -> str | None:
    """Return the contents of the last ```python fenced block (KTPO 'complete program' format)."""
    blocks = re.findall(rf"```{lang}\s*\n(.*?)```", text, flags=re.S)
    if not blocks:
        blocks = re.findall(r"```\s*\n(.*?)```", text, flags=re.S)
    return blocks[-1].strip() + "\n" if blocks else None


# --------------------------------------------------------------------------- vendoring
def ensure_repo(url: str, commit: str, dest: str | Path, sparse: list[str] | None = None) -> Path:
    """Clone ``url`` at ``commit`` into ``notebooks/vendor/<dest>`` if not already present."""
    dest = VENDOR_DIR / dest if not Path(dest).is_absolute() else Path(dest)
    marker = dest / ".vendored_commit"
    if marker.exists() and marker.read_text().strip() == commit:
        return dest
    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)]
    subprocess.run(args, check=True, capture_output=True)
    if sparse:
        subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", *sparse], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "checkout", commit], check=True, capture_output=True)
    import shutil

    shutil.rmtree(dest / ".git", ignore_errors=True)
    marker.write_text(commit + "\n")
    return dest


def apply_patch(patch_file: str | Path, cwd: str | Path) -> bool:
    """Apply a unified diff (``-p1``) with GNU ``patch`` unless it is already applied.

    Returns True if it was applied now, False if every hunk was already present. Uses ``patch``
    rather than ``git apply`` because the vendored tree lives inside this repository's worktree,
    where ``git apply`` resolves paths against the repository root instead of ``cwd``.
    """
    patch_file = Path(patch_file).resolve()
    cwd = Path(cwd)
    if not patch_file.exists():
        raise FileNotFoundError(patch_file)
    # --forward skips hunks that look already applied; --dry-run first to classify the state.
    dry = subprocess.run(["patch", "-p1", "--forward", "--dry-run", "-i", str(patch_file)], cwd=cwd, capture_output=True, text=True)
    if dry.returncode == 0:
        subprocess.run(["patch", "-p1", "--forward", "-i", str(patch_file)], cwd=cwd, check=True, capture_output=True, text=True)
        return True
    reverse = subprocess.run(["patch", "-p1", "--reverse", "--dry-run", "-i", str(patch_file)], cwd=cwd, capture_output=True, text=True)
    if reverse.returncode == 0:
        return False  # already applied
    raise RuntimeError(f"patch neither applies nor is already applied:\n{dry.stdout}\n{dry.stderr}")


# --------------------------------------------------------------------------- display helpers
def show_source(obj, title: str | None = None) -> None:
    """Print the source of a function/class (used to put code next to the paper's equations)."""
    import inspect

    from IPython.display import Markdown, display

    src = inspect.getsource(obj)
    display(Markdown(f"**{title or obj.__qualname__}**\n\n```python\n{src}\n```"))


def md(text: str) -> None:
    from IPython.display import Markdown, display

    display(Markdown(text))


def df(rows: list[dict], **kw):
    import pandas as pd

    return pd.DataFrame(rows, **kw)


def banner() -> None:
    e = env()
    md(
        f"Model: `{e['model']}` via `{e['base_url']}` · QUICK mode: `{QUICK}` · "
        f"outputs → `{OUTPUT_DIR.relative_to(REPO_ROOT)}`"
    )
