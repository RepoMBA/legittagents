#!/usr/bin/env python3
"""
keyword_research_llm_pytrends.py

1. Uses OpenAI to expand each seed into N semantically-related phrases.
2. Uses PyTrends to fetch interest-over-time for each candidate with retry/backoff.
3. Filters by MIN_AVG_INTEREST and outputs the top TOP_N keywords.

"""

import os
import json
import time
import random
import re
import openai
from pytrends.request import TrendReq
import warnings
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
warnings.simplefilter("ignore", FutureWarning)
load_dotenv()

# ---------------------------------------------------------------------------
# Compatibility patch: pytrends < 5.0 still passes `method_whitelist` to
# urllib3 Retry(..).  urllib3 2.0 renamed that argument to `allowed_methods`.
# This shim aliases the old name so Retry(...) doesn't crash on newer urllib3.
# ---------------------------------------------------------------------------
try:
    from urllib3.util import retry as _retry_mod

    _Retry = _retry_mod.Retry  # type: ignore[attr-defined]

    if "method_whitelist" not in _Retry.__init__.__code__.co_varnames:  # noqa: SLF001
        _orig_init = _Retry.__init__  # type: ignore[assignment]

        def _patched_init(self, *args, method_whitelist=None, **kwargs):  # type: ignore[no-self-arg]
            if method_whitelist is not None and "allowed_methods" not in kwargs:
                kwargs["allowed_methods"] = method_whitelist
            _orig_init(self, *args, **kwargs)

        _Retry.__init__ = _patched_init  # type: ignore[assignment]

except Exception:  # pragma: no cover – best-effort patch
    pass

# === CONFIG ===
SEED_FILE = str(os.getenv("SEED_FILE"))
with open(SEED_FILE, "r", encoding="utf-8") as f:
    SEED_KEYWORDS = json.load(f)
openai.api_key     = os.getenv("OPENAI_API_KEY", "YOUR_KEY_HERE")
LLM_CANDIDATES_PER = 9
# MUST use valid timeframe strings.
TIMEFRAME          = "today 3-m"    # last 3 months
GEO                = "US"
HL                 = "en-US"
TZ                 = 360
MIN_AVG_INTEREST   = 1
TOP_N              = 30
KEYWORDS_JSON        = str(os.getenv("KEYWORDS_FILE"))

# Batch-control: pause after every N seed words processed
SEED_BATCH_SIZE   = 8   # process this many seeds concurrently
SEED_PAUSE_SEC    = int(os.getenv("SEED_BATCH_PAUSE", "60"))  # long break duration

# === HELPERS ===

def sanitize(text: str) -> str:
    """Strip out anything except letters, numbers and spaces."""
    clean = re.sub(r'[^A-Za-z0-9 \-]+', ' ', text)
    return re.sub(r'\s{2,}', ' ', clean).strip()

def generate_candidates(seed: str):
    """Expand a seed into concise related keyword phrases via OpenAI."""
    prompt = (
        f"""Give me {LLM_CANDIDATES_PER} concise keyword phrases that are popularly used, preferably two words for instance instead of using intelligent 
        contracts automation prefer breaking it and using more apt synonyms such as smart contracts, contract automation etc (2–4 words) use 3 words if two of the words are contract and management"""
        f"that are semantically similar to \"{seed}\" in the contracts management domain."
    )
    _acquire_openai_slot()
    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role":"system", "content":"You are a helpful assistant for keyword ideation."},
            {"role":"user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=150
    )
    text = str(resp.choices[0].message.content)
    # split on lines and strip bullets/numbers
    lines = [re.sub(r"^[\d\.\-\)\s]+", "", l).strip() for l in text.splitlines()]
    return [l for l in lines if 2 <= len(l.split()) <= 5]

def init_pytrends():
    """Initialize PyTrends with retries, backoff, and a browser User-Agent."""
    return TrendReq(
        hl=HL,
        tz=TZ,
        retries=3,
        backoff_factor=1,
        timeout=(10, 25),  
        requests_args={
            'headers': {'User-Agent': 'Mozilla/5.0'},
            # no timeout here anymore
        }
    )

def avg_interest(pytrends, kw: str):
    """
    Return the average interest over TIMEFRAME for kw, or None if no data.
    Retries with exponential backoff on failure.
    """
    # (global PyTrends rate-limit handled inside the retry loop below)

    clean_kw = sanitize(kw)
    for attempt in range(1, 4):
        # Ensure we don't hammer Google Trends when running with multiple
        # threads.  Global rate-limit enforced across all workers.
        _acquire_pytrends_slot()
        try:
            pytrends.build_payload([clean_kw], timeframe=TIMEFRAME, geo=GEO)
            df = pytrends.interest_over_time()
            if df.empty:
                return None
            # ignore 'isPartial'
            data_cols = [c for c in df.columns if c.lower() != "ispartial"]
            if not data_cols:
                return None
            return float(df[data_cols[0]].mean())
        except Exception as e:
            wait = (2 ** (attempt - 1)) + random.random()
            print(f"[avg_interest] attempt {attempt} for '{clean_kw}' failed: {e}. retry in {wait:.1f}s")
            time.sleep(wait)
    print(f"[avg_interest] giving up on '{clean_kw}' after retries")
    return None

# === MAIN ===

def generate_keywords(seeds: list[str] | None = None):
    """Expand the given seeds (comma-separated words) into trending keywords.

    If *seeds* is None we fall back to the default SEED_KEYWORDS list loaded
    from the file configured by the SEED_FILE env-var.  When provided we use
    the supplied list instead (white-space stripped per element).
    """

    target_seeds = [s.strip() for s in (seeds or SEED_KEYWORDS) if s.strip()]

    def process_seed(seed: str):
        """Expand *seed*, score it plus its candidates, return list of dicts."""
        local_py = init_pytrends()
        print(f"Expanding seed: {seed}")
        cand_list = generate_candidates(seed)
        print(f" → got {len(cand_list)} candidates plus seed itself")

        kws = [seed.lower()] + [c.lower() for c in cand_list]
        local_scored: list[dict] = []
        for kw in kws:
            score = avg_interest(local_py, kw)
            print(f"{kw!r}: {score}")
            if score is not None and score >= MIN_AVG_INTEREST:
                local_scored.append({"keyword": kw, "avg_interest": score})
            time.sleep(random.uniform(0.3, 0.6))
        return local_scored

    scored: list[dict] = []

    # Process seeds in batches with a cooldown between batches
    for i in range(0, len(target_seeds), SEED_BATCH_SIZE):
        batch = target_seeds[i : i + SEED_BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=min(4, len(batch))) as ex:
            futures = {ex.submit(process_seed, s): s for s in batch}
            for fut in as_completed(futures):
                scored.extend(fut.result())

        # Long pause between batches except after the last one
        if i + SEED_BATCH_SIZE < len(target_seeds):
            print(f"⏸️  Processed {i + len(batch)} seeds — sleeping {SEED_PAUSE_SEC}s before next batch…")
            time.sleep(SEED_PAUSE_SEC)

    # deduplicate keywords keeping max score
    by_kw: dict[str, float] = {}
    for item in scored:
        kw, sc = item["keyword"], item["avg_interest"]
        by_kw[kw] = max(sc, by_kw.get(kw, 0))

    combined = [{"keyword": k, "avg_interest": v} for k, v in by_kw.items()]
    combined.sort(key=lambda x: x["avg_interest"], reverse=True)
    top = combined[:TOP_N]
    os.makedirs(os.path.dirname(KEYWORDS_JSON), exist_ok=True)
    with open(KEYWORDS_JSON, "w") as f:
        json.dump(top, f, indent=2)

    print(f"\n✅ Exported {len(top)} trending keywords to {KEYWORDS_JSON}")

    # Return a concise, human-readable summary instead of None so the caller
    # (Streamlit chat) can display feedback to the user.
    return {
        "count": len(top),
        "keywords": [k["keyword"] for k in top],
        "file": KEYWORDS_JSON,
    }

# ── Rate-limiter for PyTrends calls ──────────────────────────────────────────

_PYTRENDS_MIN_INTERVAL = 1.0  # seconds between calls (adjust as desired)
_last_pytrends_ts: float = 0.0
_pytrends_lock = threading.Lock()

def _acquire_pytrends_slot():
    """Block until at least _PYTRENDS_MIN_INTERVAL seconds passed since the
    previous PyTrends request across *all* threads. This helps prevent rate
    limiting or temporary bans from Google Trends when many worker threads
    are active simultaneously."""

    global _last_pytrends_ts
    with _pytrends_lock:
        now = time.time()
        wait = _PYTRENDS_MIN_INTERVAL - (now - _last_pytrends_ts)
        if wait > 0:
            time.sleep(wait)
        _last_pytrends_ts = time.time()

# ── Rate-limiter for OpenAI calls ───────────────────────────────────────────

_OPENAI_MIN_INTERVAL = 1.2  # seconds between calls (adjust as desired)
_last_call_ts: float = 0.0
_rate_lock = threading.Lock()

def _acquire_openai_slot():
    """Block until at least MIN_INTERVAL seconds passed since last OpenAI call."""
    global _last_call_ts
    with _rate_lock:
        now = time.time()
        wait = _OPENAI_MIN_INTERVAL - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.time()

if __name__ == "__main__":
    generate_keywords()
