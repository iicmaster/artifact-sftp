#!/usr/bin/env python3
"""Offline guard for the portable Agent Plugins / Agent Skills core."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
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
MCP_SERVER_FIELDS = {"type", "command", "cwd", "env"}
MCP_ONLY_SKILLS = {
    "artifact-sftp": "artifact_sftp.publish",
    "artifact-sftp-read": "artifact_sftp.read",
    "artifact-sftp-setup": "artifact_sftp.setup_status",
}
INTERNAL_SCRIPT_NAMES = {"publish.sh", "read-artifact.sh", "setup.sh", "setup-wizard.sh"}
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


def check_mcp() -> int:
    mcp_path = ROOT / "mcp.json"
    require_within_root(mcp_path)
    if mcp_path.is_symlink() or not mcp_path.is_file():
        fail("root mcp.json must be a regular file")
    manifest = json.loads(mcp_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"$schema", "mcpServers"}:
        fail("root mcp.json must contain only $schema and mcpServers")
    if manifest.get("$schema") != MCP_SCHEMA:
        fail("root mcp.json must declare the Agent Plugins 1.0.0 MCP schema")
    servers = manifest.get("mcpServers")
    if not isinstance(servers, dict) or set(servers) != {"artifact-sftp"}:
        fail("root mcp.json must declare exactly the artifact-sftp MCP server")
    server = servers["artifact-sftp"]
    if not isinstance(server, dict) or set(server) != MCP_SERVER_FIELDS:
        fail("artifact-sftp MCP server must use only portable stdio fields")
    if server.get("type") != "stdio":
        fail("artifact-sftp MCP server must use stdio")
    if server.get("command") != "./bin/artifact-sftp-mcp":
        fail("artifact-sftp MCP server must use the plugin-relative launcher")
    if server.get("cwd") != "${PLUGIN_ROOT}":
        fail("artifact-sftp MCP server must run from ${PLUGIN_ROOT}")
    if server.get("env") != {"ARTIFACT_SFTP_PLUGIN_ROOT": "${PLUGIN_ROOT}"}:
        fail("artifact-sftp MCP server must pass only the portable plugin-root variable")
    launcher = ROOT / "bin/artifact-sftp-mcp"
    require_within_root(launcher)
    if launcher.is_symlink() or not launcher.is_file() or (launcher.stat().st_mode & 0o111) == 0:
        fail("artifact-sftp MCP launcher must be an executable regular file")
    return len(servers)


def check_claude_mcp_compatibility() -> None:
    """Keep the Claude Code entry explicit without weakening portable mcp.json.

    Claude Code discovers project/plugin MCP servers from a root ``.mcp.json``.
    It does not supply the Agent Plugins host variables used by the portable
    manifest, so this is intentionally a small host-specific compatibility
    entry instead of a byte-for-byte copy of ``mcp.json``.
    """

    mcp_path = ROOT / ".mcp.json"
    require_within_root(mcp_path)
    if mcp_path.is_symlink() or not mcp_path.is_file():
        fail("root .mcp.json must be a regular Claude Code compatibility file")
    manifest = json.loads(mcp_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) - {"$schema", "mcpServers"}:
        fail("root .mcp.json must contain only $schema and mcpServers")
    servers = manifest.get("mcpServers")
    if not isinstance(servers, dict) or set(servers) != {"artifact-sftp"}:
        fail("root .mcp.json must declare exactly the artifact-sftp server")
    server = servers["artifact-sftp"]
    expected = {
        "type": "stdio",
        "command": "${CLAUDE_PLUGIN_ROOT}/bin/artifact-sftp-mcp",
        "cwd": "${CLAUDE_PLUGIN_ROOT}",
        "env": {
            "ARTIFACT_SFTP_PLUGIN_ROOT": "${CLAUDE_PLUGIN_ROOT}",
            "PLUGIN_ROOT": "${CLAUDE_PLUGIN_ROOT}",
            "PLUGIN_DATA": "${HOME}/.local/share/artifact-sftp",
        },
    }
    if server != expected:
        fail("root .mcp.json must retain the tested Claude Code launch contract")


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


def check_mcp_only_agent_routing() -> None:
    policy_path = ROOT / "AGENTS.md"
    require_within_root(policy_path)
    if policy_path.is_symlink() or not policy_path.is_file():
        fail("root AGENTS.md must be a regular MCP-only agent policy")
    policy = policy_path.read_text(encoding="utf-8")
    if "MCP-only" not in policy or "artifact_sftp.*" not in policy:
        fail("root AGENTS.md must require artifact_sftp MCP-only routing")

    for skill_name, required_tool in MCP_ONLY_SKILLS.items():
        skill_path = ROOT / "skills" / skill_name / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        if "MCP-only" not in content or required_tool not in content:
            fail(f"{skill_path.relative_to(ROOT)} must route agents through {required_tool}")
        leaked = sorted(name for name in INTERNAL_SCRIPT_NAMES if name in content)
        if leaked:
            fail(f"{skill_path.relative_to(ROOT)} must not teach direct internal scripts: {leaked}")


def main() -> int:
    try:
        check_manifest()
        servers = check_mcp()
        check_claude_mcp_compatibility()
        skills = check_skills()
        check_mcp_only_agent_routing()
    except (AssertionError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL Agent Plugins conformance: {error}", file=sys.stderr)
        return 1
    print(f"PASS Agent Plugins 1.0.0 portable core ({skills} skills, {servers} MCP server)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
