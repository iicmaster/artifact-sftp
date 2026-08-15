"""Safe, local wrappers around Artifact SFTP's existing script contracts.

The shell scripts remain the single source of truth for configuration, host-key
pinning, archive-before-upload, SFTP delivery, and privacy probes.  This module
only validates MCP input, invokes a fixed argv array, and translates the stable
script contract into structured results.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence
from urllib.parse import urlsplit

from .models import ErrorDetail, ToolOutput


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SNAPSHOT_RE = re.compile(r"^([a-z0-9][a-z0-9-]{0,62})--([1-9][0-9]*)--([0-9]{8}T[0-9]{6}Z)\.html$")
PUBLISHED_RE = re.compile(r"^published v([1-9][0-9]*) \(snapshot: ([^)]+)\)$")
READ_BACK_RE = re.compile(r"^read-back: (/.+)$")
SNAPSHOT_PATH_RE = re.compile(r"^snapshot: (/.+)$")
AUTH_RE = re.compile(r"^auth: (password|ssh-key|1password)$")
DEFAULT_TOOL_RE = re.compile(r"^default tool: (codex|openclaw|claude)$")
TOOLS = frozenset({"codex", "openclaw", "claude"})
VISIBILITIES = frozenset({"private", "public"})
MAX_READ_BYTES = 65_536
DEFAULT_READ_BYTES = 16_384

_SETUP_CATEGORIES = ("runtime", "config", "connection")
_SETUP_ISSUE_MARKERS = (
    "missing",
    "invalid",
    "unsafe",
    "malformed",
    "unreadable",
    "not a ",
    "no valid ",
)
_SETUP_SECRET_RE = re.compile(
    r"(?i)([A-Z0-9_]*(?:PASS(?:WORD)?|SECRET|TOKEN|AUTHORIZATION|"
    r"PRIVATE[_-]?KEY|SSH[_-]?KEY|CREDENTIALS?)[A-Z0-9_]*)\s*[=:]\s*\S+"
)
_SETUP_PEM_RE = re.compile(r"(?i)-----BEGIN [^-]*PRIVATE KEY-----.*")


@dataclass(frozen=True)
class CommandResult:
    """A subprocess result that never needs to expose its command output to MCP."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    spawn_error: bool = False


class Runner(Protocol):
    def run(self, args: Sequence[str], *, cwd: Path, timeout: float) -> CommandResult:
        """Run a fixed argv vector without a shell."""


class SubprocessRunner:
    """Run trusted implementation scripts with a minimal MCP-owned environment."""

    _ENV_KEYS = frozenset(
        {
            "HOME",
            "PATH",
            "TMPDIR",
            "TMP",
            "TEMP",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TERM",
            "USER",
            "USERPROFILE",
            "SystemRoot",
            "SYSTEMROOT",
            "COMSPEC",
            "SSH_AUTH_SOCK",
            "SSH_AGENT_PID",
            "XDG_CONFIG_HOME",
            "XDG_RUNTIME_DIR",
        }
    )

    @staticmethod
    def _path_without_own_runtime(path: str) -> str:
        """Drop this adapter's own virtual environment from a child's PATH.

        The bundled scripts resolve ``python3`` from PATH and need the one that
        carries paramiko.  Launched by ``uv run`` — the documented way to start
        this server — the adapter's own environment is prepended to PATH, and it
        declares ``mcp`` and nothing else.  The scripts then answer about that
        interpreter: ``setup.sh --status`` reports ``python3-paramiko missing``
        through the MCP surface while the identical script run from a shell
        reports READY, and ``publish.sh`` would refuse for the same reason.

        The environment above is deliberately minimal for safety; PATH is the
        one variable in it that the launcher rewrites underneath us.  Ask about
        the interpreter the scripts actually need, and never let our own
        runtime answer in its place.
        """
        own: set[str] = set()
        for prefix in (sys.prefix, os.environ.get("VIRTUAL_ENV")):
            # Outside a virtual environment ``sys.prefix`` is the base install,
            # whose ``bin`` is where the system tools live.  Removing that would
            # be far worse than the bug being fixed.
            if not prefix or os.path.realpath(prefix) == os.path.realpath(sys.base_prefix):
                continue
            for leaf in ("bin", "Scripts"):
                own.add(os.path.normcase(os.path.realpath(Path(prefix, leaf))))
        if not own:
            return path
        kept = [
            entry
            for entry in path.split(os.pathsep)
            if entry and os.path.normcase(os.path.realpath(entry)) not in own
        ]
        return os.pathsep.join(kept) if kept else os.defpath

    def run(self, args: Sequence[str], *, cwd: Path, timeout: float) -> CommandResult:
        argv = tuple(str(arg) for arg in args)
        environment = {
            key: value for key, value in os.environ.items() if key in self._ENV_KEYS
        }
        environment.setdefault("HOME", str(Path.home()))
        environment.setdefault("PATH", os.defpath)
        environment["PATH"] = self._path_without_own_runtime(environment["PATH"])
        # The bundled scripts are implementation details, not an agent-facing
        # command surface. This marker is deliberately set only by the adapter.
        environment["ARTIFACT_SFTP_MCP_CALL"] = "1"
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                env=environment,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                args=argv,
                returncode=124,
                stdout="",
                stderr="",
                timed_out=True,
            )
        except OSError:
            return CommandResult(
                args=argv,
                returncode=127,
                stdout="",
                stderr="",
                spawn_error=True,
            )
        return CommandResult(
            args=argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class ServiceResponse:
    output: ToolOutput
    is_error: bool = False


class ArtifactSftpService:
    """MCP-facing operations, intentionally constrained to Artifact SFTP v1."""

    def __init__(
        self,
        *,
        plugin_root: Path | None = None,
        runner: Runner | None = None,
        start_cwd: Path | None = None,
    ) -> None:
        self.start_cwd = (start_cwd or Path.cwd()).resolve()
        self.plugin_root = self._resolve_plugin_root(plugin_root)
        self.runner = runner or SubprocessRunner()

    def setup_status(self, *, verify_connection: bool = False) -> ServiceResponse:
        """Inspect readiness, optionally including a no-write remote preflight.

        The default remains a local-only status check for API compatibility.
        When ``verify_connection`` is requested, the service invokes the
        publisher's existing ``--list`` contract with the selected default
        tool. That path authenticates with the owner-managed configuration and
        performs a bounded no-write SFTP preflight; it never receives credentials in
        MCP arguments and never writes configuration, artifacts, or remote
        state. Authentication may use secure temporary files that are removed
        by the publisher before it returns.
        """

        script = self._script("skills/artifact-sftp/scripts/setup.sh")
        if isinstance(script, ServiceResponse):
            return script
        command = self.runner.run(("bash", str(script), "--status"), cwd=self.start_cwd, timeout=20)
        if command.timed_out or command.spawn_error:
            return self._server_failure("setup_status", command)
        if command.returncode not in (0, 3):
            return self._error(
                "setup_status",
                command.returncode,
                "setup_status_failed",
                "Could not inspect Artifact SFTP readiness.",
                "Ask the MCP owner to repair the pre-provisioned configuration boundary.",
            )

        lines = self._safe_lines(command.stdout)
        local_ready = command.returncode == 0 and any(line == "READY" for line in lines)
        auth_mode = self._first_match(lines, AUTH_RE)
        default_tool = self._first_match(lines, DEFAULT_TOOL_RE)
        prerequisites, missing = self._setup_prerequisites(lines, overall_ready=local_ready)
        connection_probe: dict[str, object] = {
            "requested": verify_connection,
            "attempted": False,
            "status": "not_requested" if not verify_connection else "not_run",
            "operation": "authenticated_sftp_preflight",
        }
        if verify_connection and local_ready:
            connection_probe = self._verify_connection(default_tool)
            if connection_probe["status"] != "verified":
                prerequisites["connection"]["ready"] = False
                prerequisites["connection"]["status"] = str(connection_probe["status"])
                missing.append(
                    {
                        "category": "connection",
                        "code": str(connection_probe["code"]),
                        "diagnostic": str(connection_probe["diagnostic"]),
                    }
                )
        ready = local_ready and (
            not verify_connection or connection_probe["status"] == "verified"
        )
        result = {
            "ready": ready,
            "local_ready": local_ready,
            "auth_mode": auth_mode,
            "default_tool": default_tool,
            "diagnostics": lines,
            "status": "ready" if ready else "not_ready",
            "prerequisites": prerequisites,
            "missing_prerequisites": missing,
            "remote_connection": connection_probe,
            "remote_connection_checked": bool(connection_probe["attempted"]),
            "agent_action": "continue" if ready else "stop",
            # Preserve the historical meaning of this field: it describes the
            # owner-managed local config boundary, not remote reachability.
            "configuration_required": not local_ready,
            "remote_connection_required": verify_connection and not ready,
        }
        return ServiceResponse(
            ToolOutput(ok=True, operation="setup_status", exit_code=command.returncode, result=result)
        )

    def setup_instructions(self, *, verify_connection: bool = False) -> ServiceResponse:
        """Report the MCP-only boundary without exposing a shell fallback."""

        status = self.setup_status(verify_connection=verify_connection)
        if status.is_error:
            return status
        ready = bool(status.output.result["ready"])
        local_ready = bool(status.output.result.get("local_ready", ready))
        if ready:
            result = {
                "mode": "ready",
                "agent_action": "continue",
                "setup_status": status.output.result,
            }
        elif verify_connection and local_ready:
            result = {
                "mode": "connection_verification_required",
                "agent_action": "stop",
                "setup_status": status.output.result,
                "credential_boundary": (
                    "This MCP-only agent server never receives or relays passwords, Cloudflare secrets, or private keys."
                ),
                "configuration_boundary": (
                    "The local configuration is present, but the no-write remote connection preflight failed. "
                    "An MCP owner must repair the connection boundary out of band."
                ),
            }
        else:
            result = {
                "mode": "configuration_required",
                "agent_action": "stop",
                "setup_status": status.output.result,
                "credential_boundary": (
                    "This MCP-only agent server never receives or relays passwords, Cloudflare secrets, or private keys."
                ),
                "configuration_boundary": (
                    "Artifact SFTP must be provisioned out of band before an agent can publish. "
                    "Do not execute a direct setup script as a fallback."
                ),
            }
        return ServiceResponse(
            ToolOutput(ok=True, operation="setup", exit_code=status.output.exit_code, result=result)
        )

    def publish(
        self,
        *,
        project_path: str,
        source_path: str,
        slug: str,
        tool: str,
        visibility: str = "private",
        dry_run: bool = False,
        confirm: bool = False,
        confirm_public: bool = False,
    ) -> ServiceResponse:
        """Publish one project-local HTML file through the hardened publisher."""

        project = self._project(project_path, "publish")
        if isinstance(project, ServiceResponse):
            return project
        source = self._source_file(source_path, project)
        if isinstance(source, ServiceResponse):
            return source
        if not SLUG_RE.fullmatch(slug):
            return self._error(
                "publish", 2, "invalid_slug", "Slug must match the Artifact SFTP slug format.",
                "Use 1–63 lowercase letters, digits, and single hyphens.",
            )
        if tool not in TOOLS:
            return self._error(
                "publish", 2, "invalid_tool", "Tool must be codex, openclaw, or claude.",
                "Choose one supported runtime namespace.",
            )
        if visibility not in VISIBILITIES:
            return self._error(
                "publish", 2, "invalid_visibility", "Visibility must be private or public.",
                "Use private unless public sharing is intentional.",
            )
        if not dry_run and not confirm:
            return self._error(
                "publish", None, "confirmation_required",
                "Publishing sends the local HTML to the configured SFTP host.",
                "Show the target to the user and call again with confirm=true after approval.",
            )
        if visibility == "public" and not dry_run and not confirm_public:
            return self._error(
                "publish", None, "public_confirmation_required",
                "Public publishing makes the artifact readable to anyone with the URL.",
                "Obtain explicit public-sharing approval and call again with confirm_public=true.",
            )

        script = self._script("skills/artifact-sftp/scripts/publish.sh")
        if isinstance(script, ServiceResponse):
            return script
        argv = ["bash", str(script), "--slug", slug, "--tool", tool]
        if visibility == "public":
            argv.append("--public")
        if dry_run:
            argv.append("--dry-run")
        argv.append(str(source))
        command = self.runner.run(argv, cwd=project, timeout=120)
        if command.timed_out or command.spawn_error:
            return self._server_failure("publish", command)
        if command.returncode != 0:
            return self._publish_failure(command.returncode)

        url = self._published_url(command.stdout, tool, visibility, slug)
        if url is None:
            return self._error(
                "publish", 0, "publish_contract_error",
                "Publisher succeeded without a valid final artifact URL.",
                "Do not assume delivery; inspect the local publisher contract before retrying.",
            )
        if dry_run:
            return ServiceResponse(
                ToolOutput(
                    ok=True,
                    operation="publish",
                    exit_code=0,
                    result={
                        "status": "dry_run",
                        "dry_run": True,
                        "url": url,
                        "slug": slug,
                        "tool": tool,
                        "visibility": visibility,
                        "local_archive_created": False,
                    },
                )
            )

        markers = self._publish_markers(command.stderr)
        read_back = markers.get("read_back")
        snapshot = markers.get("snapshot")
        if read_back is None or snapshot is None:
            return self._error(
                "publish", 0, "publish_contract_error",
                "Publisher succeeded without the required local archive markers.",
                "Do not treat the remote URL as readable evidence; inspect the local archive gate.",
            )
        current = self._archive_details(read_back, project, "publish")
        snapshot_details = self._archive_details(snapshot, project, "publish")
        if isinstance(current, ServiceResponse):
            return current
        if isinstance(snapshot_details, ServiceResponse):
            return snapshot_details
        if current["kind"] != "current" or snapshot_details["kind"] != "snapshot":
            return self._error(
                "publish", 0, "publish_contract_error",
                "Publisher returned archive paths with unexpected identities.",
                "Do not retry blindly; inspect the archive path contract.",
            )
        if current["tool"] != tool or current["visibility"] != visibility or current["slug"] != slug:
            return self._error(
                "publish", 0, "publish_contract_error",
                "Publisher archive identity does not match the requested target.",
                "Stop and inspect the local project before publishing again.",
            )
        version = markers.get("version")
        result = {
            "status": "published",
            "dry_run": False,
            "url": url,
            "slug": slug,
            "tool": tool,
            "visibility": visibility,
            "version": version,
            "read_back_path": current["path"],
            "snapshot_path": snapshot_details["path"],
            "snapshot_filename": snapshot_details["filename"],
            "archive_sha256": current["sha256"],
            "verification": {
                "local_archive": "written",
                "privacy": "protected" if visibility == "private" else "not_applicable",
                "content": "public_hash_match" if visibility == "public" else "not_independently_byte_verified",
            },
        }
        return ServiceResponse(ToolOutput(ok=True, operation="publish", exit_code=0, result=result))

    def unpublish(
        self,
        *,
        project_path: str,
        slug: str,
        tool: str,
        visibility: str = "private",
        dry_run: bool = False,
        confirm: bool = False,
        confirm_public: bool = False,
    ) -> ServiceResponse:
        """Remove a published artifact slug from the remote SFTP server."""

        project = self._project(project_path, "unpublish")
        if isinstance(project, ServiceResponse):
            return project
        if not SLUG_RE.fullmatch(slug):
            return self._error(
                "unpublish", 2, "invalid_slug", "Slug must match the Artifact SFTP slug format.",
                "Use 1–63 lowercase letters, digits, and single hyphens.",
            )
        if tool not in TOOLS:
            return self._error(
                "unpublish", 2, "invalid_tool", "Tool must be codex, openclaw, or claude.",
                "Choose one supported runtime namespace.",
            )
        if visibility not in VISIBILITIES:
            return self._error(
                "unpublish", 2, "invalid_visibility", "Visibility must be private or public.",
                "Use private unless public sharing is intentional.",
            )
        if not dry_run and not confirm:
            return self._error(
                "unpublish", None, "confirmation_required",
                "Unpublishing removes the remote HTML artifact from the SFTP host.",
                "Show the target to the user and call again with confirm=true after approval.",
            )
        if visibility == "public" and not dry_run and not confirm_public:
            return self._error(
                "unpublish", None, "public_confirmation_required",
                "Public unpublishing removes a publicly accessible URL.",
                "Obtain explicit public-sharing approval and call again with confirm_public=true.",
            )

        script = self._script("skills/artifact-sftp/scripts/publish.sh")
        if isinstance(script, ServiceResponse):
            return script
        argv = ["bash", str(script), "--delete", slug, "--tool", tool]
        if visibility == "public":
            argv.append("--public")
        if dry_run:
            argv.append("--dry-run")
        command = self.runner.run(argv, cwd=project, timeout=120)
        if command.timed_out or command.spawn_error:
            return self._server_failure("unpublish", command)
        if command.returncode != 0:
            return self._unpublish_failure(command.returncode)

        result = {
            "status": "dry_run" if dry_run else "unpublished",
            "dry_run": dry_run,
            "slug": slug,
            "tool": tool,
            "visibility": visibility,
            "remote_removed": not dry_run,
            "local_archive_retained": True,
        }
        return ServiceResponse(
            ToolOutput(ok=True, operation="unpublish", exit_code=0, result=result)
        )

    def _unpublish_failure(self, exit_code: int) -> ServiceResponse:
        mapping = {
            2: ("invalid_input", "Publisher rejected the unpublish arguments.", "Correct the tool arguments and retry."),
            3: ("config_or_auth_failed", "Artifact SFTP configuration or authentication is not ready.", "Call artifact_sftp.setup_status and stop; an MCP owner must provision the environment out of band."),
            5: ("remote_operation_failed", "SFTP remote deletion failed.", "Check the pinned host, account access, and remote permissions."),
        }
        code, message, recovery = mapping.get(
            exit_code,
            ("unpublish_failed", "Unpublish failed without a recognized exit code.", "Stop and ask the MCP owner to inspect the server implementation before retrying."),
        )
        return self._error("unpublish", exit_code, code, message, recovery, retryable=exit_code == 5)

    def list_inventory(
        self,
        *,
        project_path: str,
        tool: str | None = None,
        visibility: str | None = None,
    ) -> ServiceResponse:
        """List local artifact archives and HTML drafts in a project (Local-First)."""

        project = self._project(project_path, "list")
        if isinstance(project, ServiceResponse):
            return project

        if tool is not None and tool not in TOOLS:
            return self._error(
                "list", 2, "invalid_tool",
                f"tool must be one of: {', '.join(sorted(TOOLS))}.",
                "Filter by a valid tool namespace or omit the filter.",
            )
        if visibility is not None and visibility not in VISIBILITIES:
            return self._error(
                "list", 2, "invalid_visibility",
                f"visibility must be one of: {', '.join(sorted(VISIBILITIES))}.",
                "Filter by a valid visibility ('private' or 'public') or omit the filter.",
            )

        artifacts_root = project / "docs/artifacts"
        artifacts: list[dict[str, object]] = []

        allowed_tools = (tool,) if tool else tuple(sorted(TOOLS))
        allowed_vis = (visibility,) if visibility else tuple(sorted(VISIBILITIES))

        if artifacts_root.is_dir() and not artifacts_root.is_symlink():
            for t_name in allowed_tools:
                t_dir = artifacts_root / t_name
                if not t_dir.is_dir() or t_dir.is_symlink():
                    continue
                for v_name in allowed_vis:
                    v_dir = t_dir / v_name
                    if not v_dir.is_dir() or v_dir.is_symlink():
                        continue
                    for slug_dir in sorted(v_dir.iterdir()):
                        if not slug_dir.is_dir() or slug_dir.is_symlink():
                            continue
                        slug = slug_dir.name
                        if not SLUG_RE.fullmatch(slug):
                            continue

                        index_file = slug_dir / "index.html"
                        index_present = index_file.is_file() and not index_file.is_symlink()
                        index_sha256 = ""
                        if index_present:
                            try:
                                index_sha256 = hashlib.sha256(index_file.read_bytes()).hexdigest()
                            except OSError:
                                pass

                        snapshots: list[tuple[int, str, Path]] = []
                        for child in slug_dir.iterdir():
                            if not child.is_file() or child.is_symlink():
                                continue
                            match = SNAPSHOT_RE.fullmatch(child.name)
                            if match and match.group(1) == slug:
                                v_num = int(match.group(2))
                                ts = match.group(3)
                                snapshots.append((v_num, ts, child))

                        snapshots.sort(key=lambda s: s[0])
                        latest_version = snapshots[-1][0] if snapshots else (1 if index_present else 0)
                        latest_snapshot = snapshots[-1][2].name if snapshots else ("index.html" if index_present else "")
                        latest_timestamp = snapshots[-1][1] if snapshots else ""

                        latest_mtime: int | None = None
                        try:
                            mtime_target = snapshots[-1][2] if snapshots else (index_file if index_present else slug_dir)
                            latest_mtime = int(mtime_target.stat().st_mtime)
                        except OSError:
                            pass

                        artifacts.append({
                            "tool": t_name,
                            "visibility": v_name,
                            "slug": slug,
                            "latest_version": latest_version,
                            "latest_snapshot": latest_snapshot,
                            "latest_timestamp": latest_timestamp,
                            "snapshot_count": len(snapshots),
                            "archive_dir": str(slug_dir),
                            "index_present": index_present,
                            "index_sha256": index_sha256,
                            "mtime": latest_mtime,
                        })

        local_drafts: list[str] = []
        ignored_names = {".git", ".venv", "node_modules", "__pycache__", ".agents", ".gemini", ".system_generated"}
        for root, dirs, files in os.walk(project):
            dirs[:] = [d for d in dirs if d not in ignored_names]
            rel_root = Path(root).relative_to(project)
            if rel_root.parts and rel_root.parts[0] == "docs" and len(rel_root.parts) >= 2 and rel_root.parts[1] == "artifacts":
                if len(rel_root.parts) >= 4:
                    continue
            for f in sorted(files):
                if f.lower().endswith((".html", ".htm")):
                    f_path = Path(root) / f
                    if not f_path.is_symlink():
                        local_drafts.append(str(f_path.relative_to(project)))

        result = {
            "project_path": str(project),
            "artifacts_count": len(artifacts),
            "artifacts": artifacts,
            "local_drafts_count": len(local_drafts),
            "local_drafts": local_drafts,
        }
        return ServiceResponse(
            ToolOutput(ok=True, operation="list", exit_code=0, result=result)
        )

    def read(
        self,
        *,
        project_path: str,
        reference: str,
        max_bytes: int = DEFAULT_READ_BYTES,
        cursor: int = 0,
    ) -> ServiceResponse:
        """Resolve and return a bounded local archive excerpt, never a viewer fetch."""

        project = self._project(project_path, "read")
        if isinstance(project, ServiceResponse):
            return project
        if not reference.strip():
            return self._error(
                "read", 2, "invalid_reference", "Artifact reference must not be empty.",
                "Provide a canonical URL, read-back line, or local archive path.",
            )
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_READ_BYTES:
            return self._error(
                "read", 2, "invalid_max_bytes",
                f"max_bytes must be between 1 and {MAX_READ_BYTES}.",
                "Request a bounded chunk and continue with next_cursor when needed.",
            )
        if type(cursor) is not int or cursor < 0:
            return self._error(
                "read", 2, "invalid_cursor", "cursor must be a non-negative byte offset.",
                "Start at cursor=0 or use the prior next_cursor value.",
            )

        script = self._script("skills/artifact-sftp-read/scripts/read-artifact.sh")
        if isinstance(script, ServiceResponse):
            return script
        command = self.runner.run(
            ("bash", str(script), "--project", str(project), reference),
            cwd=project,
            timeout=20,
        )
        if command.timed_out or command.spawn_error:
            return self._server_failure("read", command)
        if command.returncode != 0:
            code = "invalid_reference" if command.returncode == 2 else "archive_unavailable"
            recovery = (
                "Provide a canonical Artifact SFTP reference inside this project's docs/artifacts tree."
                if command.returncode == 2
                else "Run from the publishing project or pass the correct absolute project_path."
            )
            return self._error(
                "read", command.returncode, code,
                "The requested local artifact archive is not available for safe reading.", recovery,
            )
        paths = [line.strip() for line in command.stdout.splitlines() if line.strip()]
        if len(paths) != 1 or not Path(paths[0]).is_absolute():
            return self._error(
                "read", 0, "read_contract_error",
                "Resolver succeeded without exactly one absolute local archive path.",
                "Do not fetch the viewer URL; inspect the local resolver contract.",
            )
        details = self._archive_details(paths[0], project, "read")
        if isinstance(details, ServiceResponse):
            return details
        try:
            raw = Path(details["path"]).read_bytes()
        except OSError:
            return self._error(
                "read", 3, "archive_unavailable",
                "The local archive disappeared before it could be read safely.",
                "Retry only after confirming the publishing project's docs/artifacts archive is intact.",
            )
        end = min(cursor + max_bytes, len(raw))
        chunk = raw[cursor:end]
        result = {
            "archive_path": details["path"],
            "relative_archive_path": details["relative_path"],
            "artifact": {
                "tool": details["tool"],
                "visibility": details["visibility"],
                "slug": details["slug"],
                "kind": details["kind"],
                "version": details["version"],
            },
            "byte_length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "cursor": cursor,
            "max_bytes": max_bytes,
            "content": chunk.decode("utf-8", errors="replace"),
            "truncated": end < len(raw),
            "next_cursor": end if end < len(raw) else None,
            "network_accessed": False,
            "content_is_untrusted": True,
            "rendering_checked": False,
        }
        return ServiceResponse(ToolOutput(ok=True, operation="read", exit_code=0, result=result))

    def _resolve_plugin_root(self, configured: Path | None) -> Path | None:
        candidates: list[Path] = []
        if configured is not None:
            candidates.append(configured)
        env_root = os.environ.get("ARTIFACT_SFTP_PLUGIN_ROOT")
        if env_root:
            candidates.append(Path(env_root))
        for base in (self.start_cwd, Path(__file__).resolve()):
            candidates.append(base)
            candidates.extend(base.parents)
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            if (resolved / "plugin.json").is_file() and (
                resolved / "skills/artifact-sftp/scripts/publish.sh"
            ).is_file():
                return resolved
        return None

    def _script(self, relative: str) -> Path | ServiceResponse:
        if self.plugin_root is None:
            return self._error(
                "server", None, "plugin_root_not_found",
                "Artifact SFTP plugin root could not be located.",
                "Set ARTIFACT_SFTP_PLUGIN_ROOT to the absolute plugin checkout path.",
            )
        path = self.plugin_root / relative
        if path.is_symlink() or not path.is_file():
            return self._error(
                "server", None, "plugin_script_unavailable",
                "A required Artifact SFTP script is unavailable or unsafe.",
                "Reinstall the plugin from a trusted checkout and set ARTIFACT_SFTP_PLUGIN_ROOT.",
            )
        return path

    def _project(self, value: str, operation: str) -> Path | ServiceResponse:
        if not value:
            return self._error(
                operation, 2, "project_path_required",
                "project_path must be an absolute project directory.",
                "Pass the project that owns docs/artifacts and the HTML source.",
            )
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            return self._error(
                operation, 2, "invalid_project_path",
                "project_path must be an existing, non-symlink absolute directory.",
                "Pass the canonical absolute publishing-project path.",
            )
        return path.resolve()

    def _source_file(self, value: str, project: Path) -> Path | ServiceResponse:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = project / candidate
        if candidate.is_symlink() or not candidate.is_file():
            return self._error(
                "publish", 2, "invalid_source_path",
                "source_path must name a regular local HTML file.",
                "Write the artifact into the selected project and pass its path.",
            )
        try:
            source = candidate.resolve(strict=True)
            source.relative_to(project)
        except (OSError, ValueError):
            return self._error(
                "publish", 2, "source_outside_project",
                "source_path must resolve inside project_path.",
                "Stage the HTML inside the selected project before publishing.",
            )
        if source.suffix.lower() not in {".html", ".htm"}:
            return self._error(
                "publish", 2, "invalid_source_extension",
                "Artifact SFTP only publishes .html or .htm files.",
                "Create an HTML artifact inside the selected project first.",
            )
        return source

    def _archive_details(self, value: str, project: Path, operation: str) -> dict[str, object] | ServiceResponse:
        candidate = Path(value)
        if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_file():
            return self._error(
                operation, 3, "unsafe_archive_path",
                "Local archive path is missing, unsafe, or not a regular file.",
                "Use the publishing project's verified docs/artifacts archive.",
            )
        try:
            resolved = candidate.resolve(strict=True)
            archive_root = (project / "docs/artifacts").resolve(strict=True)
            relative = resolved.relative_to(archive_root)
        except (OSError, ValueError):
            return self._error(
                operation, 2, "archive_outside_project",
                "Resolved artifact archive is outside this project's docs/artifacts tree.",
                "Do not use an arbitrary local path as an Artifact SFTP read-back archive.",
            )
        parts = relative.parts
        if len(parts) != 4 or parts[0] not in TOOLS or parts[1] not in VISIBILITIES or not SLUG_RE.fullmatch(parts[2]):
            return self._error(
                operation, 2, "invalid_archive_identity",
                "Archive path does not match the Artifact SFTP layout.",
                "Use the read-back path returned by the publisher or a canonical artifact URL.",
            )
        filename = parts[3]
        kind = "current" if filename == "index.html" else "snapshot"
        version: int | None = None
        if kind == "snapshot":
            match = SNAPSHOT_RE.fullmatch(filename)
            if match is None or match.group(1) != parts[2]:
                return self._error(
                    operation, 2, "invalid_archive_identity",
                    "Snapshot filename does not match the artifact slug/version contract.",
                    "Use an immutable snapshot produced by Artifact SFTP.",
                )
            version = int(match.group(2))
        try:
            archive_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError:
            return self._error(
                operation, 3, "unsafe_archive_path",
                "Local archive path could not be read safely.",
                "Use the publishing project's verified docs/artifacts archive.",
            )
        return {
            "path": str(resolved),
            "relative_path": str(relative),
            "tool": parts[0],
            "visibility": parts[1],
            "slug": parts[2],
            "filename": filename,
            "kind": kind,
            "version": version,
            "sha256": archive_sha256,
        }

    def _published_url(self, stdout: str, tool: str, visibility: str, slug: str) -> str | None:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            return None
        value = lines[-1]
        parsed = urlsplit(value)
        expected = f"/{tool}/{visibility}/{slug}/"
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.query or parsed.fragment or parsed.path.rstrip("/") + "/" != expected:
            return None
        return value

    def _publish_markers(self, stderr: str) -> dict[str, object]:
        markers: dict[str, object] = {}
        for line in stderr.splitlines():
            if match := READ_BACK_RE.fullmatch(line):
                markers["read_back"] = match.group(1)
            elif match := SNAPSHOT_PATH_RE.fullmatch(line):
                markers["snapshot"] = match.group(1)
            elif match := PUBLISHED_RE.fullmatch(line):
                markers["version"] = int(match.group(1))
        return markers

    def _publish_failure(self, exit_code: int) -> ServiceResponse:
        mapping = {
            2: ("invalid_input", "Publisher rejected the requested input.", "Correct the tool arguments and retry."),
            3: ("config_or_auth_failed", "Artifact SFTP configuration or authentication is not ready.", "Call artifact_sftp.setup_status and stop; an MCP owner must provision the environment out of band."),
            4: ("secret_scan_blocked", "Publisher detected a possible secret and blocked upload.", "Remove the secret; the MCP server deliberately does not expose the unsafe override."),
            5: ("remote_operation_failed", "SFTP upload or remote-state operation failed.", "Check the pinned host, account access, and whether the slug already exists."),
            6: ("served_content_mismatch", "Published content did not pass its verification check.", "Do not share the URL; inspect the host and retry only after resolving the mismatch."),
            7: ("private_exposed", "The requested private artifact was publicly reachable.", "URL withheld. Fix the access policy before publishing another private artifact."),
            8: ("privacy_inconclusive", "Private protection could not be verified conclusively.", "URL withheld. Investigate the access gate rather than assuming privacy."),
            9: ("local_archive_failed", "The required local archive could not be written safely.", "Fix the project docs/artifacts path before retrying upload."),
        }
        code, message, recovery = mapping.get(
            exit_code,
            ("publish_failed", "Publisher failed without a recognized exit code.", "Stop and ask the MCP owner to inspect the trusted implementation before retrying."),
        )
        return self._error(
            "publish", exit_code, code, message, recovery,
            url_withheld=exit_code in {6, 7, 8}, retryable=exit_code == 5,
        )

    def _server_failure(self, operation: str, command: CommandResult) -> ServiceResponse:
        if command.timed_out:
            message = "Artifact SFTP command timed out without a usable result."
            recovery = "Check local connectivity and the SFTP host, then retry once the cause is known."
            code = "command_timed_out"
        else:
            message = "Artifact SFTP command could not be started."
            recovery = "Verify the local shell and the trusted plugin checkout."
            code = "command_unavailable"
        return self._error(operation, command.returncode, code, message, recovery, retryable=True)

    def _error(
        self,
        operation: str,
        exit_code: int | None,
        code: str,
        message: str,
        recovery: str,
        *,
        url_withheld: bool = False,
        retryable: bool = False,
    ) -> ServiceResponse:
        return ServiceResponse(
            ToolOutput(
                ok=False,
                operation=operation,
                exit_code=exit_code,
                error=ErrorDetail(
                    code=code,
                    message=message,
                    retryable=retryable,
                    recovery=recovery,
                    url_withheld=url_withheld,
                ),
            ),
            is_error=True,
        )

    def _verify_connection(self, default_tool: str | None) -> dict[str, object]:
        """Run a bounded, no-write authenticated SFTP preflight.

        The publisher owns authentication, host-key verification, and transport
        selection for every supported auth mode. Passing only a fixed list
        operation and the already validated default tool keeps secrets and
        connection details inside the owner-managed config boundary.
        """

        probe: dict[str, object] = {
            "requested": True,
            "attempted": False,
            "status": "not_run",
            "operation": "authenticated_sftp_preflight",
        }
        if default_tool not in TOOLS:
            probe.update(
                {
                    "status": "invalid_local_configuration",
                    "code": "default_tool_missing",
                    "diagnostic": "default tool is unavailable for remote preflight",
                }
            )
            return probe

        script = self._script("skills/artifact-sftp/scripts/publish.sh")
        if isinstance(script, ServiceResponse):
            error = script.output.error
            probe.update(
                {
                    "status": "local_script_unavailable",
                    "code": error.code if error else "plugin_script_unavailable",
                    "diagnostic": "trusted publisher is unavailable for remote preflight",
                }
            )
            return probe

        command = self.runner.run(
            ("bash", str(script), "--list", "--tool", default_tool),
            cwd=self.start_cwd,
            timeout=100,
        )
        probe["attempted"] = True
        if command.timed_out:
            probe.update(
                {
                    "status": "timed_out",
                    "code": "remote_connection_timed_out",
                    "diagnostic": "no-write remote connection preflight timed out",
                }
            )
            return probe
        if command.spawn_error:
            probe.update(
                {
                    "status": "unavailable",
                    "code": "remote_connection_unavailable",
                    "diagnostic": "no-write remote connection preflight could not start",
                }
            )
            return probe
        if command.returncode == 0:
            probe.update(
                {
                    "status": "verified",
                    "code": "remote_connection_verified",
                    "diagnostic": "no-write remote connection preflight succeeded",
                    "exit_code": 0,
                }
            )
            return probe

        code = "remote_connection_config_or_auth_failed" if command.returncode == 3 else "remote_connection_failed"
        probe.update(
            {
                "status": "failed",
                "code": code,
                "diagnostic": "no-write remote connection preflight failed",
                "exit_code": command.returncode,
            }
        )
        return probe

    @classmethod
    def _setup_prerequisites(
        cls,
        lines: Sequence[str],
        *,
        overall_ready: bool,
    ) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
        """Turn the setup script's stable status lines into safe structured checks.

        ``setup.sh --status`` intentionally does not print configuration values,
        but keeping this translation here makes the MCP contract useful on a
        fresh machine without asking an agent to interpret shell output. The
        status script only checks local prerequisites; this method must never
        turn a local ``READY`` into a claim that the remote host was contacted.
        """

        grouped: dict[str, dict[str, object]] = {
            category: {
                "ready": False,
                "status": "not_checked",
                "diagnostics": [],
            }
            for category in _SETUP_CATEGORIES
        }
        missing: list[dict[str, str]] = []
        checked: dict[str, bool] = {category: False for category in _SETUP_CATEGORIES}

        for line in lines:
            category = cls._setup_category(line)
            if category is None:
                continue
            checked[category] = True
            diagnostics = grouped[category]["diagnostics"]
            assert isinstance(diagnostics, list)
            diagnostics.append(line)
            if not cls._setup_line_is_issue(line):
                continue

            reason = cls._setup_issue_reason(line)
            code = cls._setup_issue_code(line, reason)
            grouped[category]["ready"] = False
            grouped[category]["status"] = reason
            missing.append(
                {
                    "category": category,
                    "code": code,
                    "diagnostic": line,
                }
            )

        for category in _SETUP_CATEGORIES:
            if not checked[category]:
                # A dependency branch is only evaluated after a valid config
                # selects an auth mode. Keep that distinction visible on a
                # fresh machine instead of claiming that it passed.
                if overall_ready:
                    grouped[category]["ready"] = True
                    grouped[category]["status"] = "ready"
                continue
            if not any(item["category"] == category for item in missing):
                grouped[category]["ready"] = True
                grouped[category]["status"] = "ready"

        return grouped, missing

    @staticmethod
    def _setup_category(line: str) -> str | None:
        """Map stable setup status prefixes to an agent-facing category."""

        prefix = line.split(":", 1)[0].strip().lower()
        if prefix == "dependency":
            return "runtime"
        if prefix in {"config directory", "config", "config key", "default tool"}:
            return "config"
        if prefix in {"auth", "config port", "known_hosts", "ssh key"}:
            return "connection"
        return None

    @staticmethod
    def _setup_line_is_issue(line: str) -> bool:
        lower = line.lower()
        return lower.startswith("not ready") or any(
            marker in lower for marker in _SETUP_ISSUE_MARKERS
        )

    @staticmethod
    def _setup_issue_reason(line: str) -> str:
        lower = line.lower()
        if "missing" in lower or "unreadable" in lower:
            return "missing"
        return "invalid"

    @staticmethod
    def _setup_issue_code(line: str, reason: str) -> str:
        prefix = line.split(":", 1)[0].strip().lower()
        prefix = re.sub(r"[^a-z0-9]+", "_", prefix).strip("_") or "setup"
        return f"{prefix}_{reason}"

    @staticmethod
    def _safe_lines(value: str) -> list[str]:
        lines: list[str] = []
        for raw in value.splitlines():
            line = raw.strip()
            if not line:
                continue
            line = _SETUP_SECRET_RE.sub(r"\1=<redacted>", line)
            line = _SETUP_PEM_RE.sub("-----BEGIN PRIVATE KEY-----=<redacted>", line)
            line = re.sub(r"op://\S+", "op://<redacted>", line)
            line = re.sub(r"https?://\S+", "<url-redacted>", line)
            lines.append(line[:300])
        return lines[:30]

    @staticmethod
    def _first_match(lines: Sequence[str], pattern: re.Pattern[str]) -> str | None:
        for line in lines:
            if match := pattern.fullmatch(line):
                return match.group(1)
        return None
