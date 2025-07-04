from langchain.tools import Tool, StructuredTool
from pydantic import BaseModel, Field
from core import (
    generate_keywords, create_content, publish_medium,
    post_linkedin, post_twitter,
    refresh_twitter_token, refresh_linkedin_token
)
import io, contextlib, sys, types


# --- helper to capture prints -------------------------------------------------

def _run_with_logs(fn, *args, **kwargs):
    """Execute *fn* capturing anything printed to stdout.

    If the underlying result is a dict we append a "logs" field. Otherwise we
    wrap it in a dict like {"result": <value>, "logs": <captured>}.
    """
    buf = io.StringIO()
    tee = _TeeStdout(buf)
    with contextlib.redirect_stdout(tee):
        result = fn(*args, **kwargs)
    logs = buf.getvalue().strip()

    if isinstance(result, dict):
        result = {**result, "logs": logs}
    else:
        result = {"result": result, "logs": logs}
    return result

# --- Wrappers so LangChain can pass unused input without error ---

def _generate_keywords_dynamic(seeds: str | None = None):
    """Generate keywords.  If *seeds* provided (comma-separated) they override the default list."""
    parsed = None
    if seeds:
        parsed = [s.strip() for s in seeds.split(",") if s.strip()]
    return _run_with_logs(generate_keywords, parsed)

class _ContentArgs(BaseModel):
    keywords: str = Field(
        default="",
        description="Optional comma-separated list of keyword(s) to generate content for. If omitted, the top keyword is used.",
    )

def _create_content_dynamic(keywords: str = ""):
    parsed = None
    if keywords:
        parsed = [k.strip() for k in keywords.split(",") if k.strip()]
    return _run_with_logs(create_content, parsed)

# wrappers for posting tools that also take no arguments

class _PublishArgs(BaseModel):
    filename: str = Field(
        default="",
        description="Exact filename to publish on Medium (e.g. 2024-06-30_smart_contracts.txt). If omitted, a random unpublished draft is chosen.",
    )

def _publish_medium_dynamic(filename: str = ""):
    arg = filename.strip() or None
    return _run_with_logs(publish_medium, arg)

def _post_linkedin_wrapper(*_args, **_kwargs):
    return _run_with_logs(post_linkedin)

def _post_twitter_wrapper(*_args, **_kwargs):
    return _run_with_logs(post_twitter)

# -----------------------------

# Pydantic schemas

class _NoArgs(BaseModel):
    """Schema for tools that truly expect no arguments."""

class _KeywordArgs(BaseModel):
    seeds: str = Field(
        default="",
        description=(
            "Optional comma-separated seed words. If omitted the built-in seed list is used."
        ),
    )

TOOLS = [
    StructuredTool.from_function(
        name="generate_keywords",
        func=_generate_keywords_dynamic,
        description=(
            "Generate trending keywords. Optionally provide a comma-separated list of seed words "
            "to override the default internal seed list."
        ),
        args_schema=_KeywordArgs,
    ),
    StructuredTool.from_function(
        name="create_content",
        func=_create_content_dynamic,
        description=(
            "Generate Medium article(s) and social summaries. Optionally provide a comma-separated list of keyword(s) to target; if omitted the top keyword is used."
        ),
        args_schema=_ContentArgs,
    ),
    StructuredTool.from_function(
        name="publish_medium",
        func=_publish_medium_dynamic,
        description="Publish a specific draft to Medium. Provide its filename; if omitted, a random draft is chosen.",
        args_schema=_PublishArgs,
    ),
    StructuredTool.from_function(
        name="post_linkedin",
        func=_post_linkedin_wrapper,
        description="Post on LinkedIn embedding the Medium URL",
        args_schema=_NoArgs,
    ),
    StructuredTool.from_function(
        name="post_twitter",
        func=_post_twitter_wrapper,
        description="Post on X/Twitter embedding the Medium URL",
        args_schema=_NoArgs,
    ),
    Tool.from_function(
        name="refresh_twitter_token",
        func=refresh_twitter_token,
        description="Renew the Twitter OAuth token (rarely needed)",
        high_cost = True,
    ),
    Tool.from_function(
        name="refresh_linkedin_token",
        func=refresh_linkedin_token,
        description="Renew the LinkedIn OAuth token",
        high_cost = True,
    ),
]

# ---- live Streamlit container (set from app.py) -----------------------------

_LIVE_CONTAINER = None  # will hold a st.empty() container set by the UI


def set_live_container(container):
    """Called by the Streamlit app to enable real-time log streaming."""
    global _LIVE_CONTAINER
    _LIVE_CONTAINER = container


class _TeeStdout(io.StringIO):
    """Tee writes to both StringIO buffer and a Streamlit container (if any)."""

    def __init__(self, buf: io.StringIO):
        super().__init__()
        self._buf   = buf
        self._accum = ""  # accumulate log text for nicer live display

    def write(self, s: str):  # type: ignore[override]
        self._buf.write(s)
        self._accum += s

        if _LIVE_CONTAINER is not None and s.strip():
            try:
                # Render full log block so user sees history rather than only
                # the last line. Using markdown preserves whitespace nicely.
                _LIVE_CONTAINER.markdown(f"```text\n{self._accum}\n```")
            except Exception:
                # Streamlit may raise NoSessionContext if container.write is
                # called from a worker thread. Ignore so execution continues.
                pass
        return len(s)

    def flush(self):
        self._buf.flush()