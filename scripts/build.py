#!/usr/bin/env python3
"""Static site builder for the daily-niche-directory engine.

Reads config.yaml + data/*.yaml + data/councils/*.yaml + meta/content-queue.yaml,
renders templates/page.html.j2 for every queued page, writes site/.

Block spec in content-queue.yaml:
  - key: "home.yaml:welcome"   -> data/home.yaml['welcome']
  - key: "@why_expensive"      -> data/research.yaml['why_expensive']
  - key: "@council_table"      -> generated table from data/councils/*.yaml
Render hints: markdown | list | table
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
STATE = ROOT / "meta" / "build-state.json"


# ---------- tiny markdown renderer (deterministic, no deps) ----------

def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def md(text: str) -> str:
    out: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"^(#{2,4})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1)) + 0
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append('<div style="overflow-x:auto"><table><thead><tr>')
            out.extend(f"<th>{_inline(c)}</th>" for c in hdr)
            out.append("</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table></div>")
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ol>")
            continue
        if re.match(r"^\s*>", ln):
            quote = []
            while i < len(lines) and re.match(r"^\s*>", lines[i]):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{2,4}\s|\s*[-*]\s|\s*\d+\.\s|\s*\|)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(para)) + "</p>")
    return "\n".join(out)


# ---------- data loading ----------

def load_yaml(p: Path):
    return yaml.safe_load(p.read_text()) or {}


def council_rows(cfg) -> list[dict]:
    rows = []
    for p in sorted((DATA / "councils").glob("*.yaml")):
        d = load_yaml(p)
        slug = d.get("council_slug") or p.stem
        permit = d.get("permit_required")
        if permit is True:
            ptxt = "Permit required"
        elif permit is False:
            ptxt = "No permit (own property)"
        else:
            ptxt = "Check council"
        fee = d.get("permit_fee") or "?"
        band = d.get("price_band_m3") or {}
        if band:
            cheapest = min(
                (v[0] for v in band.values() if isinstance(v, list) and len(v) == 2),
                default=None,
            )
            price = f"from ~${cheapest}" if cheapest else "see page"
        else:
            price = "research pending"
        rows.append(
            {
                "council": d.get("council", slug),
                "url": f"/councils/{slug}.html",
                "permit": ptxt,
                "fee": fee,
                "price": price,
            }
        )
    return rows


def resolve_block(key: str, render: str, cfg) -> str:
    if key == "@council_table":
        rows = council_rows(cfg)
        lines = ["| Council | Permit | Permit fee | Indicative price |", "|---|---|---|---|"]
        for r in rows:
            lines.append(f"| [{r['council']}]({r['url']}) | {r['permit']} | {r['fee']} | {r['price']} |")
        return md("\n".join(lines))
    if key.startswith("@"):
        name = key[1:]
        val = load_yaml(DATA / "research.yaml").get(name)
    else:
        fname, _, ck = key.partition(":")
        val = load_yaml(DATA / fname).get(ck)
    if val is None:
        raise SystemExit(f"block {key} not found")
    if render == "list":
        items = "\n".join(f"- {v}" for v in val)
        return md(items)
    if render == "table":
        raise SystemExit("generic table render not supported; use @council_table or markdown")
    return md(str(val))


# ---------- build ----------

def council_page_body(d: dict) -> str:
    """Render a council detail page body from its data dict. Unknowns stay visible."""
    lines: list[str] = []
    permit = d.get("permit_required")
    if permit is True:
        lines.append('<p><span class="badge warn">Permit required for on-street placement</span></p>')
    elif permit is False:
        lines.append('<p><span class="badge">No permit needed on your own property</span></p>')
    else:
        lines.append('<p><span class="badge grey">Permit status: check council</span></p>')
    lines.append("## Placement rules\n")
    lines.append(md(d.get("placement_rules", "Not yet researched.")))
    lines.append("\n## Permit\n")
    fee = d.get("permit_fee") or "not verified"
    flag = "" if d.get("permit_fee_verified") else ' <span class="badge grey">not yet verified</span>'
    lines.append(f"<p>Permit fee: {html.escape(str(fee))}{flag}</p>")
    if d.get("permit_url"):
        lines.append(f'<p><a href="{html.escape(d["permit_url"])}">Council permit page (official source)</a></p>')
    band = d.get("price_band_m3") or {}
    if band:
        lines.append("\n## Indicative delivered prices\n")
        rows = ["| Size | Band (AUD) |", "|---|---|"]
        for size in sorted(band, key=lambda s: float(s.replace("m³", "").strip() or 0)):
            v = band[size]
            if isinstance(v, list) and len(v) == 2:
                rows.append(f"| {size} | ${v[0]}–${v[1]} |")
        lines.append(md("\n".join(rows)))
        flag2 = "" if d.get("price_band_verified") else ' <span class="badge grey">indicative band — verify at booking</span>'
        lines.append(f"<p>{html.escape(str(d.get('price_band_basis', '')))}{flag2}</p>")
    else:
        lines.append("\n## Indicative delivered prices\n")
        lines.append("<p><span class=\"badge grey\">research pending</span> First nightly research pass will add a verified band.</p>")
    lines.append("\n## Weight limits\n")
    lines.append(f"<p>{html.escape(str(d.get('weight_limits', 'Check with supplier at booking')))}</p>")
    if d.get("sources"):
        lines.append("\n## Sources\n")
        items = "\n".join(f"- <a href=\"{html.escape(s.strip())}\">{html.escape(s.strip())}</a>" for s in d["sources"])
        lis = "".join("<li>" + l + "</li>" for l in items.split("\n"))
        lines.append("<ul>" + lis + "</ul>")
    return "\n".join(lines)


def crumbs_for(path: str, cfg) -> list[dict]:
    parts = path.split("/")
    crumbs = []
    if len(parts) > 1:
        section = parts[0]
        label = {"councils": "Councils", "research": "Research"}.get(section, section.title())
        crumbs.append({"url": f"/{section}/", "label": label})
    return crumbs


def main() -> None:
    cfg = load_yaml(ROOT / "config.yaml")
    queue = load_yaml(ROOT / "meta" / "content-queue.yaml")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(ROOT / "templates")),
        autoescape=True,
    )
    tpl = env.get_template("page.html.j2")
    base = cfg["base_url"].rstrip("/")
    today = date.today().isoformat()
    built = []
    for entry in queue:
        rel = entry["path"]
        blocks_html = []
        for b in entry.get("blocks", []):
            blocks_html.append(resolve_block(b["key"], b.get("render", "markdown"), cfg))
        body = "\n".join(blocks_html)
        canonical = base + "/" + rel
        page = tpl.render(
            site_name=cfg["site_name"],
            base_url=base,
            build_date=today,
            page_title=entry.get("page_title") or entry["h1"],
            meta_description=entry["meta_description"],
            canonical=canonical,
            crumbs=crumbs_for(rel, cfg),
            h1=entry["h1"],
            body=body,
            affiliate_disclosure=cfg.get("affiliate_disclosure", ""),
        )
        out = SITE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page)
        built.append(rel)
    # auto-generate council detail pages from data/councils/*.yaml
    import datetime as _dt

    for p in sorted((DATA / "councils").glob("*.yaml")):
        d = load_yaml(p)
        slug = d.get("council_slug") or p.stem
        rel = f"councils/{slug}.html"
        if rel in built:
            continue
        body = council_page_body(d)
        page = tpl.render(
            site_name=cfg["site_name"],
            base_url=base,
            build_date=today,
            page_title=f"Skip bins in {d.get('council', slug)} — permits, sizes, prices",
            meta_description=f"Skip bin permit rules, placement rules and indicative prices for {d.get('council', slug)}.",
            canonical=base + "/" + rel,
            crumbs=crumbs_for(rel, cfg),
            h1=f"Skip bins in {d.get('council', slug)}",
            body=body,
            affiliate_disclosure=cfg.get("affiliate_disclosure", ""),
        )
        out = SITE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page)
        built.append(rel)

    # about page
    about_rel = "about.html"
    if about_rel not in built:
        about_body = md(
            "**What this is.** A small, free reference for skip bin sizes, council permits "
            "and indicative prices around Brisbane. It is rebuilt nightly by an automated "
            "agent, which re-checks the council pages in the source register and refreshes "
            "the build date.\n\n"
            "**How to read the numbers.** Facts about permits and rules link to the official "
            "council page. Price bands are indicative market ranges compiled at build time — "
            "always confirm the final price with the provider, since weight limits and waste "
            "type change the total.\n\n"
            "**Money.** Some outbound links may later earn a commission if you book through "
            "them. That never changes the data: rules and permit facts come from councils, "
            "not from advertisers.\n\n"
            "**Contact.** Corrections welcome — the site is maintained as part of a small "
            "automation experiment and can be reached via the operator's contact on file."
        )
        page = tpl.render(
            site_name=cfg["site_name"],
            base_url=base,
            build_date=today,
            page_title="About",
            meta_description="About this site: nightly-rebuilt skip bin reference for Brisbane, sources and methodology.",
            canonical=base + "/" + about_rel,
            crumbs=[],
            h1="About this site",
            body=about_body,
            affiliate_disclosure=cfg.get("affiliate_disclosure", ""),
        )
        (SITE / about_rel).write_text(page)
        built.append(about_rel)

    # sitemap
    urls = "\n".join(
        f"  <url><loc>{base}/{r}</loc><lastmod>{today}</lastmod></url>" for r in built
    )
    (SITE / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'
    )
    STATE.parent.mkdir(parents=True, exist_ok=True)
    prev = {}
    if STATE.exists():
        prev = json.loads(STATE.read_text())
    pages_total = len(set(prev.get("pages", [])).union(built))
    STATE.write_text(
        json.dumps({"last_built": today, "built_this_run": built, "pages": sorted(set(prev.get("pages", [])) | set(built))}, indent=1)
    )
    print(f"BUILD OK {len(built)} pages -> site/ (total known {pages_total})")


if __name__ == "__main__":
    main()
