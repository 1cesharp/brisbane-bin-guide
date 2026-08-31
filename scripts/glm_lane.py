#!/usr/bin/env python3
"""GLM-5.3-Flash worker lane: build one tool/reference page from the calculator backlog.

Usage: python3 glm_lane.py            # build the next queued item
       python3 glm_lane.py <slug>     # build a specific item

GLM runs FREE via AIHubMix (coding-glm-5.3-flash-free). Output is a self-contained
HTML fragment (calculator JS allowed, no external assets) written to
data/tools/<slug>.html + registered in meta/content-queue.yaml, then the site
rebuilds. All figures on tool pages must be static-safe (no invented fees).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "meta" / "calculator-backlog.yaml"
QUEUE = ROOT / "meta" / "content-queue.yaml"
TOOLS = ROOT / "data" / "tools"

API = "https://inference-api.nousresearch.com/v1/chat/completions"
MODEL = "z-ai/glm-5.3-flash"
AUTH = "/home/hermes/.hermes/auth.json"


def glm_call(prompt: str, timeout: float = 240.0) -> str:
    d = json.load(open(AUTH))
    key = d["providers"]["nous"].get("agent_key", "")
    if not key:
        raise SystemExit("no nous agent_key in auth.json — cannot run GLM lane")
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise web builder. Output only the requested artifact, no commentary."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 3600,
    }
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Hermes-Agent/1.0"},
            )
            resp = json.load(urllib.request.urlopen(req, timeout=timeout))
            msg = resp["choices"][0]["message"]
            content = msg.get("content")
            if not content and isinstance(msg.get("reasoning_content"), str):
                # reasoning-style response: pull the tail after any final block
                content = msg["reasoning_content"]
            if content:
                return content
            last_err = RuntimeError("empty GLM response")
            time.sleep(6)
            continue
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (524, 502, 503, 504):
                time.sleep(8 * (attempt + 1))  # gateway timeout — retry shorter
                body["max_tokens"] = max(1600, body["max_tokens"] - 1000)
                continue
            raise
    raise RuntimeError(f"GLM call failed after retries: {last_err}")


def sh(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {r.stderr[-300:]}")
    return r.stdout


def slugify(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60]


def main() -> None:
    items = yaml.safe_load(BACKLOG.read_text()) or []
    want = sys.argv[1] if len(sys.argv) > 1 else None
    idx = next((i for i, it in enumerate(items)
                if it.get("status") == "queued" and (want is None or it["slug"] == want)), None)
    if idx is None:
        print("GLM lane: nothing queued.")
        return
    item = items[idx]
    print(f"GLM lane: building '{item['slug']}' ({item.get('kind', 'reference')})…")

    design = (ROOT / "meta" / "design-system.md").read_text()
    prompt = f"""Build ONE self-contained HTML fragment for a page on an Australian bin/waste reference site.

Page title: {item['title']}
Kind: {item['kind']}
Build plan: {item['plan']}

Rules:
- Output ONLY the HTML fragment (an <h2>-led content block). No <html>/<head>/<body> tags, no external assets, no frameworks.
- If kind=calculator: vanilla-JS interactive widget inline (ids prefixed {item['slug'].replace('-', '_')}_), works with zero network. Sensible defaults, clear output line, and a short 'how this is worked out' block.
- Never invent dollar figures. If the plan needs a council fee that is not verified, render a grey badge 'not yet verified' instead of a number.
- Include a short FAQ section (3-4 Q&As) targeting the long-tail searches around this tool.
- End with a 'Related on this site' list linking to /councils/ and /research/which-bin-basics.html (relative URLs fine).
- 300-600 words of guidance text around the widget. Australian English.
- IMPORTANT: total output under 130 lines / under 3500 tokens. Be terse. Output the HTML directly with zero preamble, no markdown fences.

## Design system you MUST follow
{design}
"""
    html = glm_call(prompt)
    # strip markdown fences GLM likes to add
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip(), flags=re.I)
    # basic hygiene
    if "<html" in html.lower() or "<style" in html.lower():
        html = re.sub(r"<html[^>]*>|</html>|<head>.*?</head>|<body[^>]*>|</body>|<style.*?</style>", "", html, flags=re.S | re.I)
    if len(html) < 400:
        print("GLM lane: output too short — keeping item queued. Output head:", html[:200])
        return

    TOOLS.mkdir(parents=True, exist_ok=True)
    (TOOLS / f"{item['slug']}.html").write_text(html)

    queue = yaml.safe_load(QUEUE.read_text()) or []
    rel = f"tools/{item['slug']}.html"
    if not any(q.get("path") == rel for q in queue):
        queue.append({
            "path": rel,
            "h1": item["title"],
            "meta_description": item.get("meta_description", item["title"]),
            "blocks": [{"key": f"tools/{item['slug']}.html:body", "render": "raw"}],
        })
        QUEUE.write_text(yaml.safe_dump(queue, allow_unicode=True, sort_keys=False))

    items[idx]["status"] = "done"
    BACKLOG.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False))

    sh([sys.executable, "scripts/build.py"])
    sh(["git", "add", "-A"])
    sh(["git", "commit", "-q", "-m", f"glm lane: {item['slug']}"])
    sh(["git", "push", "-q"])
    print(f"GLM lane: PUBLISHED https://1cesharp.github.io/brisbane-bin-guide/tools/{item['slug']}.html")


if __name__ == "__main__":
    main()
