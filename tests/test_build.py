import unittest
from pathlib import Path

import yaml

from scripts.build import (
    crumbs_for,
    md,
    resolve_block,
    validate_all_council_builds,
    validate_all_council_configs,
    validate_council_build,
    validate_council_config,
)


class MarkdownRendererTests(unittest.TestCase):
    def test_ordered_list_keeps_wrapped_lines_in_the_same_list(self):
        rendered = md(
            "1. **Check first.** This instruction wraps\n"
            "   onto a second line.\n"
            "2. **Act next.** Finish the task."
        )

        self.assertEqual(rendered.count("<ol>"), 1)
        self.assertIn(
            "<li><strong>Check first.</strong> This instruction wraps onto a second line.</li>",
            rendered,
        )
        self.assertIn("<li><strong>Act next.</strong> Finish the task.</li>", rendered)


class MissedBinGuideTests(unittest.TestCase):
    def test_guide_matches_brisbane_councils_official_reporting_flow(self):
        research = yaml.safe_load(Path("data/research.yaml").read_text())
        rendered = md(research["missed_bin"])

        self.assertIn(
            "Bins are collected every day of the year, including public holidays.",
            rendered,
        )
        self.assertIn("after 4.30pm", rendered)
        self.assertIn("within 2 working days", rendered)
        self.assertIn(
            'href="https://services.brisbane.qld.gov.au/online-services/report-an-issue/bin-problem"',
            rendered,
        )


class SiteLinkTests(unittest.TestCase):
    def test_markdown_local_links_include_project_site_base_url(self):
        rendered = md(
            "[Council index →](/councils/)",
            base_url="https://1cesharp.github.io/brisbane-bin-guide",
        )

        self.assertIn(
            'href="https://1cesharp.github.io/brisbane-bin-guide/councils/"',
            rendered,
        )
        self.assertNotIn('href="/councils/"', rendered)

    def test_breadcrumb_links_include_project_site_base_url(self):
        crumbs = crumbs_for(
            "research/missed-bin-collection.html",
            {"base_url": "https://1cesharp.github.io/brisbane-bin-guide"},
        )

        self.assertEqual(
            crumbs,
            [
                {
                    "url": "https://1cesharp.github.io/brisbane-bin-guide/research/",
                    "label": "Research",
                }
            ],
        )

    def test_raw_html_local_links_include_project_site_base_url(self):
        rendered = resolve_block(
            "tools/skip-size-calculator.html",
            "raw",
            {"base_url": "https://1cesharp.github.io/brisbane-bin-guide"},
        )

        self.assertIn(
            'href="https://1cesharp.github.io/brisbane-bin-guide/councils/"',
            rendered,
        )
        self.assertNotIn('href="/councils/"', rendered)


class CouncilConfigTests(unittest.TestCase):
    def test_valid_council_config_has_required_identity_and_provenance(self):
        council = {
            "council": "Example Council",
            "council_slug": "example",
            "permit_required": True,
            "permit_url": "https://example.gov.au/skip-bins",
            "sources": ["https://example.gov.au/skip-bins"],
        }

        self.assertEqual(validate_council_config(council, "example.yaml"), [])

    def test_invalid_council_config_reports_missing_required_fields(self):
        errors = validate_council_config(
            {"council": "Example Council", "council_slug": "Example"},
            "example.yaml",
        )

        self.assertIn("example.yaml: council_slug must be lowercase URL-safe slug", errors)
        self.assertIn("example.yaml: permit_required must be true, false, or 'check council'", errors)
        self.assertIn("example.yaml: permit_url must be an absolute http(s) URL", errors)
        self.assertIn("example.yaml: sources must contain at least one absolute http(s) URL", errors)

    def test_all_current_council_fixtures_validate(self):
        validate_all_council_configs()

    def test_council_build_validation_requires_rendered_identity_and_source_links(self):
        errors = validate_council_build(
            {
                "council": "Example Council",
                "council_slug": "example",
                "permit_url": "https://example.gov.au/skip-bins",
                "sources": ["https://example.gov.au/skip-bins"],
            },
            "<html><h1>Skip bins in Example Council</h1>"
            '<a href="https://example.gov.au/skip-bins">Council permit page</a></html>',
            "example.yaml",
        )

        self.assertEqual(errors, [])

    def test_council_build_validation_reports_missing_rendered_identity_and_source_links(self):
        errors = validate_council_build(
            {"council": "Example Council", "council_slug": "example"},
            "<html><h1>Skip bins</h1></html>",
            "example.yaml",
        )

        self.assertIn("example.yaml: rendered page is missing council identity", errors)
        self.assertIn("example.yaml: rendered page is missing an official source link", errors)

    def test_all_current_council_fixtures_render_valid_pages(self):
        validate_all_council_builds()


if __name__ == "__main__":
    unittest.main()
