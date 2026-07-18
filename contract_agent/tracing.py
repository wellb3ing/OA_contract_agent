"""LangSmith tracing setup — import this module early, before any LLM calls.

Usage::

    from contract_agent.tracing import init_tracing, get_traced_openai
    init_tracing()               # once at startup
    client = get_traced_openai() # instead of openai.OpenAI(...)

LangChain ``ChatOpenAI`` instances are traced automatically when
``LANGSMITH_TRACING=true`` is set.

--------------------------------------------------------------------
Pipeline-level tracing (rich observability)
--------------------------------------------------------------------

    from contract_agent.tracing import trace_step, log_metadata, log_feedback

    with trace_step("ocr", inputs={"pages": 3}) as span:
        text = ocr_images(...)
        span.add_metadata({"text_length": len(text)})

    log_metadata({"verdict": "passed", "amount_diff": 0.0})
    log_feedback("passed", 1.0, comment="all checks green")
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Optional, Dict

_SKIP_TRACING = False  # set to True when langsmith is not installed


# ── Initialisation ───────────────────────────────────────────────────────────

def init_tracing() -> None:
    """Call once at application startup.  Reads ``config.yaml`` and sets
    the environment variables that LangSmith / LangChain need.

    If no API key is configured the function does nothing and tracing
    stays off — no errors, no warnings (just a console info line).
    """
    global _SKIP_TRACING

    # Avoid double-init
    if os.environ.get("LANGSMITH_TRACING") == "true":
        return

    try:
        from contract_agent.config import load_config
    except Exception:
        return  # config not yet available (e.g. during test collection)

    try:
        config = load_config()
    except Exception:
        return

    ls = config.get("langsmith", {}) if config else {}
    api_key = (ls.get("api_key") or "").strip()

    if not api_key:
        print("[tracing] LangSmith API key not configured — tracing disabled", flush=True)
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = ls.get("project", "contract-agent")

    endpoint = ls.get("endpoint")
    if endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = endpoint

    print(
        f"[tracing] LangSmith enabled "
        f"project={os.environ['LANGSMITH_PROJECT']}",
        flush=True,
    )


def get_traced_openai() -> Any:
    """Return an OpenAI client that is traced by LangSmith.

    Use this in place of ``openai.OpenAI(...)`` for the DeepSeek
    function-calling loop so every LLM call appears in LangSmith.
    """
    from contract_agent.config import load_config

    config = load_config()
    ds = config["deepseek"]

    try:
        from openai import OpenAI
    except ImportError:
        print("[tracing] openai package not installed", flush=True)
        raise

    client = OpenAI(api_key=ds["api_key"], base_url=ds["base_url"])

    # Wrap with LangSmith — the wrapper automatically reads
    # LANGSMITH_API_KEY from the environment (set by init_tracing).
    if os.environ.get("LANGSMITH_TRACING") == "true":
        try:
            from langsmith.wrappers import wrap_openai
            return wrap_openai(client)
        except ImportError:
            print("[tracing] langsmith not installed — OpenAI calls will NOT be traced", flush=True)
        except Exception as exc:
            print(f"[tracing] wrap_openai failed: {exc} — continuing without tracing", flush=True)

    return client


# ── Pipeline tracing helpers ─────────────────────────────────────────────────

def is_tracing_enabled() -> bool:
    """Return True when LangSmith tracing is active."""
    return os.environ.get("LANGSMITH_TRACING") == "true"


@contextmanager
def trace_step(
    name: str,
    inputs: Optional[Dict[str, Any]] = None,
    run_type: str = "tool",
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context manager that creates a child *span* inside the current run.

    Usage::

        with trace_step("download_contract", {"file_id": 42}) as span:
            path = downloader(...)
            span.add_metadata({"file_size_kb": os.path.getsize(path) // 1024})

    When tracing is disabled this is a no-op, so callers can use it
    unconditionally.
    """
    if not is_tracing_enabled():
        yield None
        return

    try:
        from langsmith.run_helpers import trace
    except ImportError:
        yield None
        return

    started = time.time()
    try:
        with trace(name=name, inputs=inputs or {}, run_type=run_type) as span:
            if metadata:
                span.add_metadata(metadata)
            # Stash start_time on the span so the caller's finally block
            # can compute duration even without the span object.
            yield span
    except Exception:
        yield None
        return
    finally:
        elapsed_ms = round((time.time() - started) * 1000)
        if is_tracing_enabled():
            try:
                from langsmith.run_helpers import get_current_run_tree
                run = get_current_run_tree()
                if run is not None:
                    existing = run.metadata or {}
                    existing["duration_ms"] = elapsed_ms
            except Exception:
                pass


def log_metadata(data: Dict[str, Any]) -> None:
    """Attach key-value metadata to the **current** LangSmith run.

    Safe to call when tracing is disabled — does nothing.
    """
    if not is_tracing_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree
        run = get_current_run_tree()
        if run is not None:
            run.add_metadata(data)
    except Exception:
        pass


def log_feedback(key: str, score: float, comment: str = "") -> None:
    """Attach a numeric feedback score to the **current** LangSmith run.

    ``score`` should be a float in ``[0.0, 1.0]`` (or a boolean, where
    True → 1.0 and False → 0.0).

    Example::

        log_feedback("passed", 1.0, comment="金额一致 + 签字通过")
    """
    if not is_tracing_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree
        run = get_current_run_tree()
        if run is None:
            return
        feedbacks = run.metadata.get("_feedbacks", {}) if run.metadata else {}
        feedbacks[key] = {"score": float(score), "comment": comment}
        run.add_metadata({"_feedbacks": feedbacks})
    except Exception:
        pass


def trace_function(name: str = None, run_type: str = "chain"):
    """Decorator that traces a function as a LangSmith run.

    Usage::

        @trace_function("contract_check")
        def run_contract_check(query_params: dict) -> dict:
            ...

    When tracing is disabled the function runs normally (no overhead).
    """
    if not is_tracing_enabled():
        return lambda fn: fn  # no-op decorator

    try:
        from langsmith import traceable
        return traceable(name=name, run_type=run_type)
    except ImportError:
        return lambda fn: fn
    except Exception:
        return lambda fn: fn
