#!/usr/bin/env python3
"""Offline guard for the portable Agent Plugins / Agent Skills core."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
PLUGIN_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
SKILL_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
PLUGIN_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def fail(message: str) -> None:
    raise AssertionError(message)


def require_within_root(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        fail(f"package path escapes plugin root: {path}")


def check_manifest() -> None:
    manifest_path = ROOT / "plugin.json"
    require_within_root(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        fail("root plugin.json must be a regular file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        fail("root plugin.json must contain an object")
    unknown = set(manifest) - PLUGIN_FIELDS
    if unknown:
        fail(f"root plugin.json has non-portable fields: {sorted(unknown)}")
    if manifest.get("$schema") != PLUGIN_SCHEMA:
        fail("root plugin.json must declare the Agent Plugins 1.0.0 schema")
    name = manifest.get("name")
    if not isinstance(name, str) or len(name) > 64 or not PLUGIN_NAME_RE.fullmatch(name):
        fail("plugin name does not satisfy the Agent Plugins naming rules")
    for field in ("version", "description", "homepage", "repository", "license"):
        if field in manifest and not isinstance(manifest[field], str):
            fail(f"plugin field {field!r} must be a string")
    if "author" in manifest:
        author = manifest["author"]
        if not isinstance(author, dict) or set(author) - {"name", "email", "url"}:
            fail("plugin author must contain only name, email, and url strings")
        if not all(isinstance(value, str) for value in author.values()):
            fail("plugin author values must be strings")
    if "keywords" in manifest:
        if not isinstance(manifest["keywords"], list) or not all(
            isinstance(value, str) for value in manifest["keywords"]
        ):
            fail("plugin keywords must be an array of strings")
    if "extensions" in manifest:
        extensions = manifest["extensions"]
        if not isinstance(extensions, dict) or not all(
            isinstance(key, str) and isinstance(value, dict)
            for key, value in extensions.items()
        ):
            fail("plugin extensions must map namespace strings to objects")


def parse_frontmatter(skill_path: Path) -> dict[str, str]:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        fail(f"{skill_path.relative_to(ROOT)} must begin with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        fail(f"{skill_path.relative_to(ROOT)} has unterminated YAML frontmatter")

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)", line)
        if not match:
            fail(f"{skill_path.relative_to(ROOT)} has unsupported frontmatter syntax: {line!r}")
        key, value = match.groups()
        if key in fields:
            fail(f"{skill_path.relative_to(ROOT)} repeats frontmatter field {key!r}")
        fields[key] = value
    return fields


def check_skills() -> int:
    skills_root = ROOT / "skills"
    require_within_root(skills_root)
    if skills_root.is_symlink() or not skills_root.is_dir():
        fail("skills must be a directory within the plugin root")

    count = 0
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            continue
        require_within_root(skill_path)
        if skill_path.is_symlink() or not skill_path.is_file():
            fail(f"{skill_dir.relative_to(ROOT)} must contain a regular SKILL.md")
        fields = parse_frontmatter(skill_path)
        unknown = set(fields) - SKILL_FIELDS
        if unknown:
            fail(f"{skill_path.relative_to(ROOT)} has non-standard frontmatter fields: {sorted(unknown)}")
        name = fields.get("name", "")
        if len(name) > 64 or not SKILL_NAME_RE.fullmatch(name) or name != skill_dir.name:
            fail(f"{skill_path.relative_to(ROOT)} name must match its directory and Agent Skills rules")
        description = fields.get("description", "")
        if not description or len(description) > 1024:
            fail(f"{skill_path.relative_to(ROOT)} needs a non-empty description of at most 1024 characters")
        count += 1
    return count


def main() -> int:
    try:
        check_manifest()
        skills = check_skills()
    except (AssertionError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL Agent Plugins conformance: {error}", file=sys.stderr)
        return 1
    print(f"PASS Agent Plugins 1.0.0 portable core ({skills} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
