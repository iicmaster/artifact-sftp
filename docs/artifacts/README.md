# Local artifact archive

Every successful non-dry-run `artifact_sftp.publish` call writes a stamped local copy before
it contacts SFTP:

```text
docs/artifacts/<tool>/<visibility>/<slug>/index.html
docs/artifacts/<tool>/<visibility>/<slug>/<slug>--<version>--<timestamp>.html
```

The current file is replaced on republish; timestamped snapshots remain as local history.

## MCP read-back only

Use `artifact_sftp.read` to inspect a current or versioned local archive. A private artifact's
URL is a viewer link behind the access gate, not a read source. Do not WebFetch it, use direct
SFTP, or invoke an implementation script as a fallback.

The URL path maps to this layout:

```text
https://.../<tool>/<visibility>/<slug>/
docs/artifacts/<tool>/<visibility>/<slug>/
```

This archive is local custody evidence only. It does not independently prove SFTP delivery,
HTTP byte identity, privacy, public availability, runtime behavior, or release approval.

Do not put credentials or other sensitive content here. The agent-facing MCP publisher has no
sensitive-content override.
