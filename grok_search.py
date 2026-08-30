#!/usr/bin/env python3
"""Run a Grok (x.ai) /v1/responses call with built-in web_search + x_search tools.

Usage: python3 grok_search.py <task: research|page|outreach> [out_path]

Reads the xAI OAuth token from the Hermes secondbrain auth store.
Never prints the token. Writes markdown output + usage/citations JSON.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

AUTH = "/home/ben/.hermes/profiles/secondbrain/auth.json"
API = "https://api.x.ai/v1/responses"
MODEL = "grok-4.6"

PROMPTS = {}

PROMPTS["research"] = """You are doing niche research for an automated affiliate-directory business. Today is 30 August 2026.

Task: identify THE ONE best "boring but searched-every-day" niche for a small programmatic directory/reference site that a solo operator in Brisbane, Australia can build and monetise with affiliate/referral deals.

Hard requirements:
1. Boring, unsexy, chore-like territory. People search for it EVERY DAY (recurring need, not one-off research).
2. Real, current pain: use X search and web search (include Reddit results) to find ACTUAL recent complaints/questions about this niche. Quote or closely paraphrase the most representative 4-8 posts WITH platform, approximate date (last 90 days), and subreddit/marketplace/handle where possible. If live search cannot find recent ones, say so explicitly - do not invent.
3. Monetisation must exist TODAY: name at least 6 real affiliate/referral programs serving that niche (company, network e.g. Impact/ShareASale/CJ/PartnerStack/in-house, typical commission if discoverable, signup URL). NEVER invent commission rates - mark unverified ones as 'rate not verified'.
4. Directory data must be buildable from public sources (gov open data, public APIs, public pricing pages) without scraping walled gardens.
5. Competition check: do existing directory sites exist? Name main incumbents and gaps (stale data, bad UX, no AU focus, no programmatic long-tail).
6. Give 12 example long-tail page titles people would actually search.
7. Quick sanity check on 2-3 runner-up niches you considered and why they lost.

Constraints: solo operator, Brisbane Australia. Prefer niches where an AU/NZ or local angle is a moat. Avoid: crypto, gambling, adult, anything needing a financial licence (no credit/insurance advice), medical advice. Budget near-zero: static site on free hosting, content generated nightly by an LLM agent.

Output format (markdown):
## Chosen niche
## Why it wins (recurrence, search logic, pain evidence)
## Live complaints (X + Reddit, dated; flag anything unverified)
## Affiliate/referral programs (table: company | network | commission | signup URL | verified?)
## Data sources for directory content
## Competition + gaps (named incumbents)
## 12 example pages
## Runner-ups considered
## Honest risks
"""


def token() -> str:
    d = json.load(open(AUTH))
    return d["providers"]["xai-oauth"]["tokens"]["access_token"]


def run(prompt: str, timeout: float = 560.0) -> dict:
    body = {
        "model": MODEL,
        "input": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search"}, {"type": "x_search"}],
        "stream": False,
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"},
    )
    t0 = time.time()
    resp = json.load(urllib.request.urlopen(req, timeout=timeout))
    texts, anns = [], []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    texts.append(c.get("text", ""))
                    anns.extend(a for a in (c.get("annotations") or []))
    return {
        "text": "\n".join(texts),
        "annotations": anns,
        "usage": resp.get("usage", {}),
        "elapsed_s": round(time.time() - t0, 1),
    }


def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else "research"
    out = sys.argv[2] if len(sys.argv) > 2 else f"research/{task}.md"
    extra = sys.argv[3] if len(sys.argv) > 3 else ""
    prompt = PROMPTS.get(task)
    if prompt is None:
        print(f"unknown task {task}; have: {', '.join(PROMPTS)}")
        sys.exit(2)
    if extra:
        prompt = prompt + "\n\nAdditional context from operator:\n" + extra
    try:
        r = run(prompt)
    except urllib.error.HTTPError as e:
        print("HTTP FAIL", e.code, e.read()[:600])
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print("FAIL:", type(e).__name__, str(e)[:300])
        sys.exit(1)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        f.write(r["text"])
    meta = out + ".meta.json"
    with open(meta, "w") as f:
        json.dump({"annotations": r["annotations"], "usage": r["usage"], "elapsed_s": r["elapsed_s"]}, f, indent=1)
    u = r["usage"]
    print(f"OK {out} | {len(r['text'])} chars | {r['elapsed_s']}s | tools {u.get('num_server_side_tools_used')} | cost_ticks {u.get('cost_in_usd_ticks')}")
    print("---HEAD---")
    print(r["text"][:3500])


if __name__ == "__main__":
    main()
