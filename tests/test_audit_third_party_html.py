"""Regression lock for the artifact-audit third-party active-content rule.

The v1.0 spec (ADR 0002) declares every artifact on one custom domain a single
browser trust domain, and the audit gate therefore blocks third-party active
content before it can share an origin with private artifacts. The rule carries
NO automatic first-party exemption: same-origin is not publisher identity, so
absolute URLs pointing at the deployment's own origin are flagged too (the
artifact must rewrite them to inline or relative sources).

This test pins the EXACT detection patterns published in
skills/artifact-audit/SKILL.md (so the rule text and the detector cannot drift)
and exercises them against positive and negative HTML samples, case-insensitively,
the way the auditor runs them against the serialized HTML the artifact serves.

Scope note: these are pattern-text regressions for the published rule — the
audit itself is an instruction skill whose BLOCK verdict is enforced by the
publishing workflow, not by an executable scanner in this repository.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "artifact-audit" / "SKILL.md"

P_EXTERNAL = (
    r"""<(?:script|iframe|object|embed)\b[^>]*?(?<![-\w])(?:src|data)(?![-\w])"""
    r"""\s*=\s*(["']?)\s*(?:(?:https?:)?//|data:)"""
)
P_ENTITY = (
    r"""<(?:script|iframe|object|embed)\b[^>]*?(?<![-\w])(?:src|data)(?![-\w])"""
    r"""\s*=\s*(["']?)\s*[^"'>]*(?:&#x0*3a;|&#0*58;|&#x0*2f;|&#0*47;|&colon;|&sol;)"""
)
P_SRCDOC = r"""<iframe\b(?![^>]*?[\s"']sandbox(?:\s*=|[\s/>]))[^>]*?(?<![-\w])srcdoc(?![-\w])"""

PATTERNS = (P_EXTERNAL, P_ENTITY, P_SRCDOC)


def hits(html: str) -> list[str]:
    found: list[str] = []
    for pattern in PATTERNS:
        found.extend(
            match.group(0)
            for match in re.finditer(pattern, html, flags=re.IGNORECASE)
        )
    return found


class PatternDocumentedTests(unittest.TestCase):
    def test_skill_document_pins_every_exact_pattern(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            self.assertIn(pattern, text, "SKILL.md rule drifted from the tested pattern")
        self.assertIn("Third-Party Active Content on a Shared Origin", text)
        self.assertIn("no automatic first-party", text)


class PositiveSamplesTests(unittest.TestCase):
    def assert_flags(self, html: str) -> None:
        self.assertTrue(hits(html), f"expected the rule to flag: {html!r}")

    def test_external_script_src(self) -> None:
        self.assert_flags('<script src="https://evil.example/tracker.js"></script>')

    def test_external_http_script_src(self) -> None:
        self.assert_flags('<script src="http://evil.example/x.js"></script>')

    def test_protocol_relative_script_src(self) -> None:
        self.assert_flags("<script src='//cdn.evil.dev/a.js'></script>")

    def test_unquoted_external_script_src(self) -> None:
        self.assert_flags("<script src=https://evil.example/x.js></script>")

    def test_external_iframe_src(self) -> None:
        self.assert_flags('<iframe src="https://embed.example/page"></iframe>')

    def test_external_object_data(self) -> None:
        self.assert_flags('<object data="https://evil.example/o.svg"></object>')

    def test_external_embed_src(self) -> None:
        self.assert_flags('<embed src="https://evil.example/e.swf">')

    def test_data_uri_in_active_element(self) -> None:
        self.assert_flags(
            '<script src="data:text/javascript,alert(1)"></script>'
        )

    def test_same_origin_absolute_url_is_still_flagged(self) -> None:
        # Same-origin is not publisher identity: an absolute URL to this very
        # deployment can point at another project's active artifact.
        self.assert_flags(
            '<script src="https://artifacts.example/codex/private/x.js"></script>'
        )

    def test_entity_encoded_colon_bypass(self) -> None:
        # The browser decodes &#x3a; into ':'; the raw source has no https://.
        self.assert_flags(
            '<script src="https&#x3a;&#x2f;&#x2f;evil.example/x.js"></script>'
        )

    def test_entity_encoded_decimal_colon(self) -> None:
        self.assert_flags(
            '<iframe src="https&#58;//evil.example/frame"></iframe>'
        )

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

    def test_srcdoc_iframe_without_sandbox_is_flagged(self) -> None:
        self.assert_flags('<iframe srcdoc="<script>alert(1)</script>"></iframe>')

    def test_entity_encoded_named_references(self) -> None:
        self.assert_flags(
            '<script src="https&colon;&sol;&sol;evil.example/x.js"></script>'
        )

    def test_unrelated_sandbox_text_does_not_satisfy_the_guard(self) -> None:
        self.assert_flags(
            '<iframe title=sandbox srcdoc="<script>alert(1)</script>"></iframe>'
        )


class NegativeSamplesTests(unittest.TestCase):
    def assert_clean(self, html: str) -> None:
        self.assertEqual(hits(html), [], f"rule must not flag: {html!r}")

    def test_inline_script_is_owner_authored(self) -> None:
        self.assert_clean("<script>document.title = 'ok'</script>")

    def test_relative_script_src(self) -> None:
        self.assert_clean('<script src="assets/app.js"></script>')

    def test_root_relative_script_src(self) -> None:
        self.assert_clean('<script src="/static/app.js"></script>')

    def test_plain_link_and_image_are_not_active_embeds(self) -> None:
        self.assert_clean(
            '<a href="https://example.com/x">link</a>'
            '<img src="https://img.example/i.png" alt="">'
        )

    def test_hyphenated_attribute_data_src_is_not_the_real_src(self) -> None:
        self.assert_clean(
            '<script data-src="https://evil.example/x.js"></script>'
        )

    def test_sandboxed_srcdoc_is_allowed(self) -> None:
        self.assert_clean(
            '<iframe sandbox="" srcdoc="<p>static preview</p>"></iframe>'
        )

    def test_boolean_sandbox_attribute_is_allowed(self) -> None:
        self.assert_clean(
            '<iframe sandbox srcdoc="<p>static preview</p>"></iframe>'
        )

    def test_publish_gate_embeds_the_same_patterns(self) -> None:
        # The executable gate in publish.sh must carry the exact published
        # patterns — rule text, test fixtures, and gate cannot drift apart.
        import ast
        publisher = (ROOT / "skills" / "artifact-sftp" / "scripts" / "publish.sh").read_text(encoding="utf-8")
        start = publisher.index("PATTERNS = ") + len("PATTERNS = ")
        end = publisher.index("\n)", start)
        embedded = ast.literal_eval(publisher[start : end + 2])
        self.assertEqual(tuple(embedded), PATTERNS)


if __name__ == "__main__":
    unittest.main()
