#!/usr/bin/env python3
"""Check authoritative council URLs and emit a deterministic freshness receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_RECEIPT = ROOT / "meta" / "source-check.json"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text()) or {}


def _normalise_text(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _owner(council: dict, field: str) -> dict:
    return {
        "council": council.get("council", council.get("council_slug", "unknown")),
        "council_slug": council.get("council_slug", "unknown"),
        "fields": [field],
    }


def inventory_sources(fixtures: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for council in fixtures:
        for field, value in (
            ("permit_url", council.get("permit_url")),
            ("bin_day_lookup", council.get("bin_day_lookup")),
            ("sources", council.get("sources", [])),
        ):
            values = [value] if field != "sources" else value
            if not isinstance(values, list):
                continue
            for url in values:
                if not isinstance(url, str) or not url.strip():
                    continue
                url = url.strip()
                record = by_url.setdefault(url, {"url": url, "owners": []})
                owner = _owner(council, field)
                existing = next((item for item in record["owners"] if item["council_slug"] == owner["council_slug"]), None)
                if existing is None:
                    record["owners"].append(owner)
                elif field not in existing["fields"]:
                    existing["fields"].append(field)
    return [by_url[url] for url in sorted(by_url)]


def _fetch(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Brisbane-Bin-Guide-source-check/1.0"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=20, context=context) as response:
        body = response.read()
        return {
            "status": response.status,
            "final_url": response.geturl(),
            "content_type": response.headers.get("content-type", ""),
            "body": body,
        }


def build_receipt(inventory: list[dict], fetcher: Callable[[str], dict] = _fetch, checked_at: str | None = None) -> dict:
    sources = []
    for item in inventory:
        record = {"url": item["url"], "owners": item.get("owners", [])}
        try:
            response = fetcher(item["url"])
            status = response.get("status", 200)
            if status < 200 or status >= 400:
                record["error"] = f"HTTP status {status}"
                sources.append(record)
                continue
            text = _normalise_text(response["body"])
            record.update(
                {
                    "status": response["status"],
                    "final_url": response["final_url"],
                    "content_type": response["content_type"],
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "text_chars": len(text),
                }
            )
        except Exception as exc:  # receipt must preserve failures rather than hide them
            record["error"] = f"{type(exc).__name__}: {exc}"
        sources.append(record)
    return {
        "schema_version": 1,
        "checked_at_utc": checked_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "summary": {
            "total": len(sources),
            "ok": sum("text_sha256" in source for source in sources),
            "errors": sum("error" in source for source in sources),
        },
        "sources": sources,
    }


def compare_records(current: list[dict], previous: list[dict]) -> dict:
    old = {item["url"]: item for item in previous}
    current_urls = {item["url"] for item in current}
    result = {"unchanged": [], "changed": [], "new": [], "errors": [], "removed": []}
    for item in current:
        url = item["url"]
        if "error" in item:
            result["errors"].append(url)
        elif url not in old:
            result["new"].append(url)
        elif item.get("text_sha256") == old[url].get("text_sha256"):
            result["unchanged"].append(url)
        else:
            result["changed"].append(url)
    result["removed"] = sorted(set(old) - current_urls)
    for key in result:
        result[key].sort()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    fixtures = [load_yaml(path) for path in sorted((DATA / "councils").glob("*.yaml"))]
    inventory = inventory_sources(fixtures)
    receipt = build_receipt(inventory)
    previous = json.loads(args.output.read_text()).get("sources", []) if args.output.exists() else []
    receipt["diff"] = compare_records(receipt["sources"], previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": receipt["summary"], "diff": receipt["diff"]}, indent=2))


if __name__ == "__main__":
    main()
