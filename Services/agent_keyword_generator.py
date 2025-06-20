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
warnings.simplefilter("ignore", FutureWarning)
load_dotenv()

# === CONFIG ===
SEED_FILE = os.getenv("SEED_FILE")
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
KEYWORDS_JSON        = os.getenv("KEYWORDS_FILE")

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
    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role":"system", "content":"You are a helpful assistant for keyword ideation."},
            {"role":"user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=150
    )
    text = resp.choices[0].message.content
    # split on lines and strip bullets/numbers
    lines = [re.sub(r"^[\d\.\-\)\s]+", "", l).strip() for l in text.splitlines()]
    return [l for l in lines if 2 <= len(l.split()) <= 5]

def init_pytrends():
    """Initialize PyTrends with retries, backoff, and a browser User-Agent."""
    return TrendReq(
        hl=HL,
        tz=TZ,
        retries=5,
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
    clean_kw = sanitize(kw)
    for attempt in range(1, 6):
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

def generate_keys():
    pytrends = init_pytrends()
    all_candidates = set()

    # 1) Expand each seed via LLM
    for seed in SEED_KEYWORDS:
        print(f"Expanding seed: {seed}")
        cands = generate_candidates(seed)
        print(f" → got {len(cands)} candidates plus seed itself")
        all_candidates.add(seed.lower())
        all_candidates.update([c.lower() for c in cands])
        time.sleep(random.uniform(1, 2))

    print(f"\nTotal unique candidates: {len(all_candidates)}")

    # 2) Score with Trends
    scored = []
    for kw in all_candidates:
        score = avg_interest(pytrends, kw)
        print(f"{kw!r}: {score}")
        if score is not None and score >= MIN_AVG_INTEREST:
            scored.append({"keyword": kw, "avg_interest": score})
        time.sleep(random.uniform(2, 4))

    # 3) Sort & output
    scored.sort(key=lambda x: x["avg_interest"], reverse=True)
    top = scored[:TOP_N]
    os.makedirs(os.path.dirname(KEYWORDS_JSON), exist_ok=True)
    with open(KEYWORDS_JSON, "w") as f:
        json.dump(top, f, indent=2)

    print(f"\n✅ Exported {len(top)} trending keywords to {KEYWORDS_JSON}")
