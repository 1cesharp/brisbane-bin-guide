#!/usr/bin/env python3
"""Nightly routine for Brisbane Bin Guide.

Steps:
  1. pick first topic without done:true from meta/topic-backlog.yaml
  2. Grok (grok-4.6 + x_search/web_search) researches the page with source register
  3. RESEARCH_FAILED -> mark topic done(no-page), report, skip publish
  4. else -> write data/pages/<slug>.yaml, append page to meta/content-queue.yaml
  5. rebuild site/, git commit + push (GitHub Pages rebuilds)
  6. print a report line (cron delivers to Telegram)

Also appends an outreach status line (what's pending / needs Ben) so Ben sees
money-relevant motion in the same report.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "meta" / "topic-backlog.yaml"
QUEUE = ROOT / "meta" / "content-queue.yaml"
PAGES_DATA = ROOT / "data" / "pages"


def sh(cmd: list[str], **kw) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=kw.pop("timeout", 120), **kw)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed {' '.join(cmd[:3])}...: {r.stderr[-400:]}")
    return r.stdout


def slugify(t: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return s[:60]


def pick_topic() -> tuple[int, dict] | None:
    topics = yaml.safe_load(BACKLOG.read_text()) or []
    for i, t in enumerate(topics):
        if not t.get("done"):
            return i, t
    return None


def main() -> None:
    today = date.today().isoformat()
    picked = pick_topic()
    if not picked:
        print("Nightly: backlog empty — add topics to meta/topic-backlog.yaml. Nothing published.")
        return
    idx, topic_entry = picked
    topic = topic_entry["topic"]
    angle = topic_entry.get("angle", "")
    slug = slugify(topic)
    print(f"Nightly {today}: researching '{topic}' (grok-4.6, live search)…")

    try:
        out = sh(
            [sys.executable, "grok_search.py", "page", f"research/pages/{slug}.md", f"{topic} :: {angle}"],
            timeout=560,
        )
    except subprocess.TimeoutExpired:
        print(f"Nightly {today}: Grok research timed out for '{topic}'. Nothing published; topic left for retry.")
        return
    except RuntimeError as e:
        print(f"Nightly {today}: research call failed: {e}")
        return

    body = Path(ROOT / "research" / "pages" / f"{slug}.md").read_text()
    if body.startswith("RESEARCH_FAILED"):
        topics = yaml.safe_load(BACKLOG.read_text())
        topics[idx]["done"] = True
        topics[idx]["done_note"] = body.strip()[:200]
        BACKLOG.write_text(yaml.safe_dump(topics, allow_unicode=True, sort_keys=False))
        print(f"Nightly {today}: research FAILED for '{topic}' — {body.strip()[:150]}")
        print("Nothing published (guardrail: no page without verified sources).")
    else:
        PAGES_DATA.mkdir(parents=True, exist_ok=True)
        (PAGES_DATA / f"{slug}.yaml").write_text(
            f"# Generated nightly from Grok live research {today}\nbody: |\n"
            + "\n".join("  " + ln for ln in body.splitlines())
            + "\n"
        )
        queue = yaml.safe_load(QUEUE.read_text()) or []
        queue.append(
            {
                "path": f"guides/{slug}.html",
                "h1": topic,
                "meta_description": f"{topic} — Brisbane Bin Guide, updated {today} with sources.",
                "blocks": [{"key": f"pages/{slug}.yaml:body", "render": "markdown"}],
            }
        )
        QUEUE.write_text(yaml.safe_dump(queue, allow_unicode=True, sort_keys=False))
        sh([sys.executable, "scripts/build.py"])
        sh(["git", "add", "-A"])
        sh(["git", "commit", "-q", "-m", f"nightly {today}: {topic}"])
        sh(["git", "push", "-q"])
        topics = yaml.safe_load(BACKLOG.read_text())
        topics[idx]["done"] = True
        BACKLOG.write_text(yaml.safe_dump(topics, allow_unicode=True, sort_keys=False))
        print(f"Nightly {today}: PUBLISHED https://1cesharp.github.io/brisbane-bin-guide/guides/{slug}.html")
        print(f"  '{topic}' ({len(body.split())} words, source register included)")

    # outreach status line
    try:
        st = json.loads(sh([sys.executable, "scripts/outreach.py", "status"], timeout=30))
        lines = ["", "💰 Money report:"]
        lines.append(f"  outreach: {st['open_threads']} open threads / cap {st['caps']['total_open_threads']}")
        for n in st.get("needs_ben", []):
            lines.append(f"  ⚠️ needs Ben: {n}")
        if st.get("followup_due"):
            lines.append(f"  followups due: {', '.join(st['followup_due'])}")
        if st["open_threads"] == 0:
            lines.append("  (no affiliate threads open yet — site building audience first)")
        print("\n".join(lines))
    except Exception as e:  # noqa: BLE001
        print(f"(outreach status unavailable: {e})")


if __name__ == "__main__":
    main()
