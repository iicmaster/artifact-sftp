"""Local stdio MCP server for Artifact SFTP.

No code in this module writes to stdout.  MCPServer owns stdout for JSON-RPC
frames; shell-script output is captured by the service layer.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .models import ToolOutput
from .service import ArtifactSftpService, ServiceResponse


def _tool_result(response: ServiceResponse) -> ToolOutput | CallToolResult:
    """Keep structured schemas for success and structured isError payloads for failure."""

    if not response.is_error:
        return response.output
    payload = response.output.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(text=json.dumps(payload, ensure_ascii=False, sort_keys=True))],
        structuredContent=payload,
        isError=True,
    )


def build_server(service: ArtifactSftpService | None = None) -> MCPServer:
    """Build a server that can be tested in-memory without a subprocess."""

    adapter = service or ArtifactSftpService()
    server = MCPServer(
        "Artifact SFTP",
        version="0.10.0",
        description="Publish and locally read self-contained HTML artifacts through an existing pinned SFTP configuration.",
        instructions=(
            "Use setup_status before a first publish. Private URLs are viewer links, not read sources: "
            "call artifact_sftp.read on the local read-back reference instead. Never put credentials, tokens, "
            "or private-key contents in tool arguments. Publish is private by default and needs user approval."
        ),
    )

    @server.tool(
        name="artifact_sftp.setup_status",
        title="Check Artifact SFTP setup",
        description="Read local Artifact SFTP readiness without changing configuration or using SFTP.",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def setup_status() -> ToolOutput:
        return _tool_result(adapter.setup_status())  # type: ignore[return-value]

    @server.tool(
        name="artifact_sftp.setup",
        title="Get safe Artifact SFTP setup instructions",
        description=(
            "Return the local terminal command for initial setup or reconfiguration. "
            "This tool never starts the interactive wizard and never accepts credentials."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def setup(reconfigure: bool = False) -> ToolOutput:
        return _tool_result(adapter.setup_instructions(reconfigure=reconfigure))  # type: ignore[return-value]

    @server.tool(
        name="artifact_sftp.publish",
        title="Publish an Artifact SFTP HTML file",
        description=(
            "Publish one regular .html/.htm file within an absolute project_path. "
            "Private is the default. A real publish requires confirm=true; a public publish also requires "
            "confirm_public=true. This v1 tool never exposes force or allow-sensitive overrides."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    )
    def publish(
        project_path: str,
        source_path: str,
        slug: str,
        tool: str,
        visibility: str = "private",
        dry_run: bool = False,
        confirm: bool = False,
        confirm_public: bool = False,
    ) -> ToolOutput:
        return _tool_result(
            adapter.publish(
                project_path=project_path,
                source_path=source_path,
                slug=slug,
                tool=tool,
                visibility=visibility,
                dry_run=dry_run,
                confirm=confirm,
                confirm_public=confirm_public,
            )
        )  # type: ignore[return-value]

    @server.tool(
        name="artifact_sftp.read",
        title="Read a local Artifact SFTP archive",
        description=(
            "Resolve a canonical URL, read-back line, or archive path to the selected project's local archive. "
            "Returns a bounded, untrusted HTML excerpt and never fetches a private viewer URL."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def read(
        project_path: str,
        reference: str,
        max_bytes: int = 16_384,
        cursor: int = 0,
    ) -> ToolOutput:
        return _tool_result(
            adapter.read(
                project_path=project_path,
                reference=reference,
                max_bytes=max_bytes,
                cursor=cursor,
            )
        )  # type: ignore[return-value]

    return server


def main() -> None:
    """Run a blocking local stdio server; MCPServer exclusively owns stdout."""

    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
