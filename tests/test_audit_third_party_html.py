"""Regression lock for the artifact-audit third-party active-content rule.

The v1.0 spec (ADR 0002) declares every artifact on one custom domain a single
browser trust domain, and the audit gate therefore blocks third-party active
content — external `<script>/<iframe>/<object>/<embed>` sources — before it can
share an origin with private artifacts.

This test pins the EXACT detection pattern published in
skills/artifact-audit/SKILL.md (so the rule text and the detector cannot drift)
and exercises it against positive and negative HTML samples, case-insensitively,
the way the auditor runs it against the serialized HTML the artifact serves.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "artifact-audit" / "SKILL.md"

PATTERN = r"""<(?:script|iframe|object|embed)\b[^>]*?\b(?:src|data)\s*=\s*(["']?)\s*(?:https?:)?//"""


def hits(html: str) -> list[str]:
    return [
        match.group(0)
        for match in re.finditer(PATTERN, html, flags=re.IGNORECASE)
    ]


class PatternDocumentedTests(unittest.TestCase):
    def test_skill_document_pins_this_exact_pattern(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn(PATTERN, text, "SKILL.md rule drifted from the tested pattern")
        self.assertIn("Third-Party Active Content on a Shared Origin", text)


class PositiveSamplesTests(unittest.TestCase):
    def assert_flags(self, html: str) -> None:
        self.assertTrue(hits(html), f"expected the rule to flag: {html!r}")

    def test_external_script_src(self) -> None:
        self.assert_flags('<script src="https://evil.example/tracker.js"></script>')

    def test_protocol_relative_script_src(self) -> None:
        self.assert_flags("<script src='//cdn.evil.dev/a.js'></script>")

    def test_external_iframe_src(self) -> None:
        self.assert_flags('<iframe src="https://embed.example/page"></iframe>')

    def test_external_object_data(self) -> None:
        self.assert_flags('<object data="https://evil.example/o.svg"></object>')

    def test_external_embed_src(self) -> None:
        self.assert_flags('<embed src="https://evil.example/e.swf">')

    def test_uppercase_attributes_and_spacing(self) -> None:
        self.assert_flags("<SCRIPT SRC = 'HTTPS://EVIL.EXAMPLE/x.js'></SCRIPT>")

    def test_multiline_attribute_order(self) -> None:
        self.assert_flags(
            "<script\n  defer\n  data-keep='1'\n  src = \"https://evil.example/x.js\"></script>"
        )

    def test_flags_every_external_source_in_one_document(self) -> None:
        html = (
            '<script src="https://a.example/x.js"></script>'
            '<iframe src="//b.example/f"></iframe>'
            '<object data="https://c.example/o"></object>'
            '<embed src="https://d.example/e">'
        )
        self.assertEqual(len(hits(html)), 4)


class NegativeSamplesTests(unittest.TestCase):
    def assert_clean(self, html: str) -> None:
        self.assertEqual(hits(html), [], f"rule must not flag: {html!r}")

    def test_inline_script_is_owner_authored(self) -> None:
        self.assert_clean("<script>document.title = 'ok'</script>")

    def test_relative_script_src(self) -> None:
        self.assert_clean('<script src="assets/app.js"></script>')

    def test_root_relative_script_src(self) -> None:
        self.assert_clean('<script src="/static/app.js"></script>')

    def test_same_document_iframe_without_src(self) -> None:
        self.assert_clean('<iframe srcdoc="<p>local</p>"></iframe>')

    def test_plain_link_and_image_are_not_active_embeds(self) -> None:
        self.assert_clean(
            '<a href="https://example.com/x">link</a>'
            '<img src="https://img.example/i.png" alt="">'
        )


if __name__ == "__main__":
    unittest.main()
