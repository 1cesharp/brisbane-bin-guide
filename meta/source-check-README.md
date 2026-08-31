# Source-check operation

The maintenance receipt is produced by `python3 scripts/source_check.py --output meta/source-check.json`.

It inventories each council fixture's `permit_url`, optional `bin_day_lookup`, and `sources`, deduplicates URLs, fetches them with a stable user agent, strips scripts/styles/noscript/markup, hashes the remaining text with SHA-256, and records `new`, `unchanged`, `changed`, `removed`, and access/error states. HTTP 4xx/5xx responses are errors, never valid freshness evidence.

The receipt is intentionally local-only; `meta/source-check.json` is ignored from publication. Run it before a build or before trusting a council-data refresh. A blocked source is a maintenance blocker requiring a browser/search fallback or a corrected official URL, not a reason to claim freshness.
