"""Unit tests for the executable shared-origin external-content gate.

skills/artifact-sftp/scripts/external_content_gate.py implements the
artifact-audit Dimension 5 rule with a real HTML parser (html.parser): real
element and attribute structure, entity-decoded values, comments ignored.
These tests pin its SEMANTICS — including the adversarial cases from the
gpt-6-luna[max] review rounds (attribute-value sandbox text, entity-encoded
schemes, srcdoc ordering) — independently of any regex spelling.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "skills" / "artifact-sftp" / "scripts" / "external_content_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("external_content_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()

    def flag(self, html: str) -> str:
        hit = self.gate.scan(html)
        self.assertIsNotNone(hit, f"expected the gate to flag: {html!r}")
        return hit  # type: ignore[return-value]

    def clean(self, html: str) -> None:
        self.assertIsNone(self.gate.scan(html), f"gate must not flag: {html!r}")

    # ---- positives: external / active sources ----

    def test_external_script_src(self) -> None:
        self.assertIn("evil.example", self.flag('<script src="https://evil.example/x.js"></script>'))

    def test_http_script_src(self) -> None:
        self.flag('<script src="http://evil.example/x.js"></script>')

    def test_protocol_relative_script_src(self) -> None:
        self.flag("<script src='//cdn.evil.dev/a.js'></script>")

    def test_unquoted_external_script_src(self) -> None:
        self.flag("<script src=https://evil.example/x.js></script>")

    def test_external_iframe_object_embed(self) -> None:
        self.flag('<iframe src="https://embed.example/page"></iframe>')
        self.flag('<object data="https://evil.example/o.svg"></object>')
        self.flag('<embed src="https://evil.example/e.swf">')

    def test_data_uri(self) -> None:
        self.flag('<script src="data:text/javascript,alert(1)"></script>')

    def test_same_origin_absolute_is_flagged(self) -> None:
        # Same-origin is not publisher identity (ADR 0002).
        self.flag('<script src="https://artifacts.example/codex/private/x.js"></script>')

    def test_entity_encoded_numeric_references(self) -> None:
        # html.parser decodes &#x3a;/&#x2f; before the gate sees the value.
        self.flag('<script src="https&#x3a;&#x2f;&#x2f;evil.example/x.js"></script>')

    def test_entity_encoded_decimal_references(self) -> None:
        self.flag('<iframe src="https&#58;//evil.example/frame"></iframe>')

    def test_entity_encoded_named_references(self) -> None:
        # Round-2 Luna bypass: &colon;/&sol; named refs.
        self.flag('<script src="https&colon;&sol;&sol;evil.example/x.js"></script>')

    def test_uppercase_and_spacing(self) -> None:
        self.flag("<SCRIPT SRC = 'HTTPS://EVIL.EXAMPLE/x.js'></SCRIPT>")

    def test_multiline_attribute_order(self) -> None:
        self.flag(
            "<script\n  defer\n  data-keep='1'\n  src = \"https://evil.example/x.js\"></script>"
        )

    def test_unsandboxed_srcdoc_is_flagged(self) -> None:
        self.flag('<iframe srcdoc="<script>alert(1)</script>"></iframe>')

    def test_srcdoc_flagging_is_order_independent(self) -> None:
        self.flag('<iframe srcdoc="<p>x</p>" height=10></iframe>')
        self.flag('<iframe height=10 srcdoc="<p>x</p>"></iframe>')

    def test_quoted_attribute_value_sandbox_text_does_not_clear_the_gate(self) -> None:
        # Round-3 Luna BLOCKER: sandbox inside another attribute's value.
        self.flag('<iframe title="prefix sandbox " srcdoc="<script>top.pwned=1</script>"></iframe>')

    def test_unquoted_sandbox_word_in_another_attribute_does_not_clear_it(self) -> None:
        self.flag('<iframe title=sandbox srcdoc="<script>alert(1)</script>"></iframe>')

    # ---- negatives: owner-authored or inactive content ----

    def test_inline_script_is_allowed(self) -> None:
        self.clean("<script>document.title = 'ok'</script>")

    def test_relative_sources_are_allowed(self) -> None:
        self.clean('<script src="assets/app.js"></script>')
        self.clean('<script src="/static/app.js"></script>')

    def test_plain_link_and_image_are_allowed(self) -> None:
        self.clean(
            '<a href="https://example.com/x">link</a>'
            '<img src="https://img.example/i.png" alt="">'
        )

    def test_hyphenated_data_src_attribute_is_not_the_real_src(self) -> None:
        self.clean('<script data-src="https://evil.example/x.js"></script>')

    def test_sandboxed_srcdoc_is_allowed(self) -> None:
        self.clean('<iframe sandbox="" srcdoc="<p>static preview</p>"></iframe>')

    def test_boolean_sandbox_attribute_is_allowed(self) -> None:
        self.clean('<iframe sandbox srcdoc="<p>static preview</p>"></iframe>')

    def test_sandbox_after_srcdoc_is_allowed(self) -> None:
        self.clean('<iframe srcdoc="<p>static preview</p>" sandbox></iframe>')

    def test_commented_example_is_not_flagged(self) -> None:
        # Round-3 N2 policy alignment: the parser ignores comments, so safe
        # documentation containing active-content examples stays publishable.
        self.clean("<!-- <script src='https://evil.example/x.js'></script> -->")

    def test_srcdoc_content_is_not_scanned_as_elements(self) -> None:
        # The srcdoc VALUE is not parsed as page elements: the gate judges the
        # iframe itself (sandbox present -> allowed).
        self.clean('<iframe sandbox srcdoc="<iframe src=\'https://evil.example/f\'></iframe>"></iframe>')

    def test_malformed_markup_fails_closed(self) -> None:
        # html.parser is tolerant by design, so the raise path is simulated:
        # scan() must return a flag (never None) if parsing ever blows up.
        original = self.gate.ExternalContentParser.feed

        def boom(parser, markup):
            raise ValueError("boom")

        self.gate.ExternalContentParser.feed = boom
        try:
            self.assertIsNotNone(self.gate.scan("<p>x</p>"))
        finally:
            self.gate.ExternalContentParser.feed = original


if __name__ == "__main__":
    unittest.main()
