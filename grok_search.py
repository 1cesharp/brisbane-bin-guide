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


PROMPTS["page"] = """You are researching ONE page for Brisbane Bin Guide, a free Australian reference site about bin days, recycling rules, hard rubbish and skip permits (Brisbane / south-east Queensland focus). Today is {today}.

Page topic: {topic}
Angle/guardrails: {angle}

Requirements:
1. Use X search and web search to gather CURRENT, real information. Australian council sources (brisbane.qld.gov.au, logan.qld.gov.au, moretonbay.qld.gov.au, goldcoast.qld.gov.au, ipswich.qld.gov.au, qld.gov.au, data.qld.gov.au) outrank blogs.
2. EVERY factual claim in your output must be traceable to a specific URL you actually saw. End with a "### Source register" numbered list of those URLs.
3. NEVER invent figures (fees, dates, quantities). If a number cannot be verified, write "not yet verified" next to it and explain what to check.
4. If recent X/Reddit posts illustrate the pain point, cite them with platform + handle + approximate date. Do not fabricate posts.
5. Write for a resident doing a chore right now: direct, practical, no fluff. 400-700 words. Markdown with ## sections. Include a practical "what to do" section.
6. If you cannot verify the core of the topic, output "RESEARCH_FAILED: <one line why>" and nothing else.

Output ONLY the page body markdown.
"""

PROMPTS["products"] = """You are researching monetisable product angles for an Australian solo operator who runs boring niche websites (currently: bin days, recycling, skip bins in Brisbane/SEQ) with an agent workforce. Today is {today}.

Mission: find 3-5 "boring but necessary" physical or digital products with demonstrable daily search demand that could be dropshipped from AU-friendly suppliers or sold as digital downloads, where existing marketing is weak (bad SEO pages, no comparison content, ugly or nonexistent tools) - a 10x-marketing arbitrage opportunity.

Method (use web + X search for CURRENT evidence):
1. Demand: long-tail searches people actually type daily; quote recent complaints/posts of people wanting the product but having had a bad buying experience (with platform + date).
2. Suppliers: AliExpress/Alibaba or Australian wholesalers; unit cost and MOQ with the listing URL. NEVER invent prices; if unavailable say so.
3. Retail gap: what incumbents charge (with URL), and where the margin might sit.
4. 10x angle: exactly what we would build (calculator/comparison/bundle/content) to out-market the weak incumbents.

Avoid: regulated goods (electrical, therapeutic/supplement claims, food), counterfeit risk, saturated trivia (phone cases, fidget toys). Prefer adjacency to the operator's existing audience: waste, garden, home organisation, tools, pets, moving house.

Output markdown, one block per product:
## <product name>
Demand evidence / Supplier + unit cost (URL) / Retail gap (URL) / 10x marketing angle / Risks
End with ## Ranking (table: product | evidence strength | est. margin | build effort | verdict go/hold)
Flag anything you could not verify as unverified. Do not fabricate.
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
    if task == "page":
        # extra = "TOPIC :: ANGLE"
        topic, _, angle = extra.partition("::")
        from datetime import date

        prompt = prompt.format(today=date.today().isoformat(), topic=topic.strip(), angle=angle.strip() or "none")
    elif task == "products":
        from datetime import date

        prompt = prompt.format(today=date.today().isoformat())
    elif extra:
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
