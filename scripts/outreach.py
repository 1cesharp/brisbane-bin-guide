#!/usr/bin/env python3
"""Outreach ledger + send-day pipeline state for Brisbane Bin Guide.

Tracks first contacts, followups, replies and status transitions against
the caps in meta/outreach/caps.yaml. The nightly agent:
  1. calls `outreach.py status` to see what's allowed tonight
  2. drafts/appends first-contact rows via `outreach.py add`
  3. marks sends via `outreach.py sent <id> <thread>`
  4. after reading Gmail, records replies via `outreach.py reply <id> <note>`

Nothing here sends email — sending happens through the NUC gws route and is
logged here afterwards.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "meta" / "outreach" / "ledger.jsonl"
CAPS = yaml.safe_load((ROOT / "meta" / "outreach" / "caps.yaml").read_text())


def now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]


def save(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))


def status() -> dict:
    rows = load()
    open_threads = [r for r in rows if r["status"] in ("sent", "replied", "negotiating")]
    today = [r for r in rows if r.get("first_sent_at", "").startswith(now().date().isoformat())]
    c = CAPS["caps"]
    return {
        "rows": len(rows),
        "open_threads": len(open_threads),
        "first_contacts_today": len(today),
        "can_first_contact": len(open_threads) < c["total_open_threads"]
        and len(today) < c["new_first_contacts_per_night"],
        "followup_due": [
            r["provider"]
            for r in open_threads
            if r["status"] == "sent"
            and r.get("last_sent_at")
            and datetime.fromisoformat(r["last_sent_at"]) < now() - timedelta(days=5)
            and r.get("followups", 0) < c["followups_per_thread"]
        ],
        "needs_ben": [r["provider"] + ": " + r.get("note", "") for r in rows if r["status"] in ("offer", "stop", "surface-to-ben")],
    }


def cmd_add(provider: str, contact: str, email: str, program: str, reason: str) -> str:
    rows = load()
    rid = f"oc_{len(rows)+1:03d}"
    rows.append(
        {
            "id": rid,
            "provider": provider,
            "contact": contact,
            "email": email,
            "program": program,
            "reason": reason,
            "status": "drafted",
            "first_sent_at": None,
            "last_sent_at": None,
            "followups": 0,
            "note": "",
        }
    )
    save(rows)
    return rid


def cmd_sent(rid: str) -> str:
    rows = load()
    for r in rows:
        if r["id"] == rid:
            ts = now().isoformat()
            r["status"] = "sent"
            r["first_sent_at"] = r["first_sent_at"] or ts
            r["last_sent_at"] = ts
            save(rows)
            return f"{rid} marked sent {ts}"
    return f"{rid} not found"


def cmd_followup(rid: str) -> str:
    rows = load()
    for r in rows:
        if r["id"] == rid:
            r["followups"] = r.get("followups", 0) + 1
            r["last_sent_at"] = now().isoformat()
            save(rows)
            return f"{rid} followup #{r['followups']} logged"
    return f"{rid} not found"


def cmd_reply(rid: str, note: str, new_status: str = "replied") -> str:
    rows = load()
    for r in rows:
        if r["id"] == rid:
            r["status"] = new_status
            r["note"] = note[:400]
            save(rows)
            return f"{rid} -> {new_status}: {note[:120]}"
    return f"{rid} not found"


def main() -> None:
    a = sys.argv[1:]
    if not a or a[0] == "status":
        s = status()
        caps = CAPS["caps"]
        print(json.dumps({**s, "caps": caps}, indent=1))
        return
    if a[0] == "add" and len(a) >= 6:
        print(cmd_add(a[1], a[2], a[3], a[4], a[5]))
    elif a[0] == "sent" and len(a) >= 2:
        print(cmd_sent(a[1]))
    elif a[0] == "followup" and len(a) >= 2:
        print(cmd_followup(a[1]))
    elif a[0] == "reply" and len(a) >= 3:
        print(cmd_reply(a[1], a[2], a[3] if len(a) > 3 else "replied"))
    elif a[0] == "list":
        for r in load():
            print(r["id"], r["status"].ljust(12), r["provider"], "|", r["note"][:60])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
