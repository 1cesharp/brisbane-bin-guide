import unittest

from scripts.source_check import _normalise_text, build_receipt, compare_records, inventory_sources


class SourceInventoryTests(unittest.TestCase):
    def test_normalise_text_removes_dynamic_script_and_style_content(self):
        body = b"<h1>Stable</h1><script>timestamp()</script><style>.x{}</style><noscript>Fallback</noscript>"

        self.assertEqual(_normalise_text(body), "Stable")

    def test_inventory_deduplicates_urls_and_keeps_owners(self):
        fixtures = [
            {
                "council": "Example Council",
                "council_slug": "example",
                "permit_url": "https://example.gov.au/skip",
                "sources": ["https://example.gov.au/skip", "https://example.gov.au/waste"],
            },
            {
                "council": "Other Council",
                "council_slug": "other",
                "permit_url": "https://example.gov.au/waste",
                "sources": ["https://other.gov.au/waste"],
            },
        ]

        records = inventory_sources(fixtures)

        self.assertEqual(
            [record["url"] for record in records],
            [
                "https://example.gov.au/skip",
                "https://example.gov.au/waste",
                "https://other.gov.au/waste",
            ],
        )
        self.assertEqual(
            records[1]["owners"],
            [
                {"council": "Example Council", "council_slug": "example", "fields": ["sources"]},
                {"council": "Other Council", "council_slug": "other", "fields": ["permit_url"]},
            ],
        )

    def test_inventory_includes_bin_day_lookup_as_authoritative_source(self):
        fixtures = [
            {
                "council": "Example Council",
                "council_slug": "example",
                "permit_url": "https://example.gov.au/skip",
                "bin_day_lookup": "https://example.gov.au/bin-days",
                "sources": [],
            }
        ]

        records = inventory_sources(fixtures)
        by_url = {record["url"]: record for record in records}

        self.assertEqual(by_url["https://example.gov.au/bin-days"]["owners"][0]["fields"], ["bin_day_lookup"])


class SourceComparisonTests(unittest.TestCase):
    def test_compare_records_classifies_new_unchanged_changed_and_error(self):
        previous = [
            {"url": "https://same.test", "text_sha256": "same"},
            {"url": "https://changed.test", "text_sha256": "old"},
            {"url": "https://gone.test", "text_sha256": "gone"},
        ]
        current = [
            {"url": "https://same.test", "text_sha256": "same"},
            {"url": "https://changed.test", "text_sha256": "new"},
            {"url": "https://new.test", "text_sha256": "new"},
            {"url": "https://error.test", "error": "timeout"},
        ]

        result = compare_records(current, previous)

        self.assertEqual(result["unchanged"], ["https://same.test"])
        self.assertEqual(result["changed"], ["https://changed.test"])
        self.assertEqual(result["new"], ["https://new.test"])
        self.assertEqual(result["errors"], ["https://error.test"])
        self.assertEqual(result["removed"], ["https://gone.test"])


class SourceReceiptTests(unittest.TestCase):
    def test_build_receipt_hashes_success_and_preserves_fetch_errors(self):
        inventory = [{"url": "https://ok.test", "owners": []}, {"url": "https://bad.test", "owners": []}]

        def fake_fetch(url):
            if url.endswith("bad.test"):
                raise TimeoutError("simulated timeout")
            return {"status": 200, "final_url": url, "content_type": "text/html", "body": b"<h1>Stable</h1>"}

        receipt = build_receipt(inventory, fetcher=fake_fetch, checked_at="2026-08-31T00:00:00Z")

        self.assertEqual(receipt["checked_at_utc"], "2026-08-31T00:00:00Z")
        self.assertEqual(receipt["summary"], {"total": 2, "ok": 1, "errors": 1})
        self.assertEqual(receipt["sources"][0]["text_sha256"], "90ee305714d7103317705bfffd734c654b78807e5a0f51fcc61bc1d81105ebd1")
        self.assertEqual(receipt["sources"][1]["error"], "TimeoutError: simulated timeout")

    def test_http_403_is_recorded_as_access_error_not_success(self):
        inventory = [{"url": "https://blocked.test", "owners": []}]

        def fake_fetch(_url):
            return {"status": 403, "final_url": _url, "content_type": "text/html", "body": b"Access denied"}

        receipt = build_receipt(inventory, fetcher=fake_fetch, checked_at="2026-08-31T00:00:00Z")

        self.assertEqual(receipt["summary"], {"total": 1, "ok": 0, "errors": 1})
        self.assertEqual(receipt["sources"][0]["error"], "HTTP status 403")


if __name__ == "__main__":
    unittest.main()
