"""Executable shared-origin external-content gate (artifact-audit Dimension 5).

All artifacts published to one custom domain share one browser trust domain
(ADR 0002): same-origin is NOT publisher identity, so active content loaded
from an absolute or protocol-relative URL — including this deployment's own
origin — runs with the embedding document's privileges beside private
artifacts.

This gate parses the artifact with html.parser — real element and attribute
structure, entity-decoded values, comments ignored — so attribute-value text
(such as `title="prefix sandbox "`) can neither bypass nor false-flag it, and
it flags:

- <script>/<iframe>/<object>/<embed> whose src/data references an absolute
  http(s):// or protocol-relative // URL (own origin included) or a data: URI;
- <iframe srcdoc> whose sandbox does not isolate it: no sandbox attribute at
  all, or a sandbox granting BOTH allow-scripts and allow-same-origin (that
  combination can run same-origin script against the embedding document).

Inline scripts authored for the artifact and same-document relative URLs are
allowed. Rewrite flagged sources inline or relative before publishing.

usage: external_content_gate.py FILE
exit: 0 clean | 1 flagged (a bounded snippet is printed to stdout)
"""

from __future__ import annotations

from html.parser import HTMLParser

ACTIVE_TAGS = frozenset({"script", "iframe", "object", "embed"})
EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:")


class ExternalContentParser(HTMLParser):
    """Flag external/active sources and unsandboxed srcdoc iframes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hit: str | None = None

    def _flag(self, snippet: str) -> None:
        if self.hit is None:
            self.hit = snippet[:160]

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if self.hit is not None or tag not in ACTIVE_TAGS:
            return
        named = dict(attrs)
        if tag == "iframe" and "srcdoc" in named and not self._sandbox_isolates(named):
            self._flag("<iframe srcdoc without an isolating sandbox>")
            return
        for name in ("src", "data"):
            value = named.get(name)
            if value and value.strip().lower().startswith(EXTERNAL_PREFIXES):
                self._flag(f"<{tag} {name}={value.strip()[:80]!r}>")
                return

    @staticmethod
    def _sandbox_isolates(named: dict) -> bool:
        """A sandbox isolates srcdoc only when it does not hand the frame both
        script execution and same-origin access — `allow-scripts
        allow-same-origin` together can reach the embedding document."""

        if "sandbox" not in named:
            return False
        value = named.get("sandbox") or ""
        tokens = {token.strip().lower() for token in value.split() if token.strip()}
        return not {"allow-scripts", "allow-same-origin"} <= tokens

    # Self-closing forms (<iframe ... />) route through handle_startendtag,
    # whose default implementation calls handle_starttag — covered.


def scan(text: str) -> str | None:
    """Return a bounded snippet of the first flagged element, or None."""

    parser = ExternalContentParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # malformed markup must fail closed, never pass silently
        return "<unparseable HTML — treated as flagged>"
    return parser.hit


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="HTML artifact to scan")
    args = parser.parse_args()
    with open(args.file, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    hit = scan(text)
    if hit is not None:
        print(f"external active content: {hit}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
