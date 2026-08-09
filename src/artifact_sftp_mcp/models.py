"""Structured MCP results shared by every Artifact SFTP tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """A redacted, actionable tool error."""

    code: str
    message: str
    retryable: bool
    recovery: str
    url_withheld: bool = False


class ToolOutput(BaseModel):
    """Stable shape for both successful and failed tool calls."""

    ok: bool
    operation: str
    exit_code: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: ErrorDetail | None = None
