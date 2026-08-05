# Local artifact archive

`skills/artifact-sftp/scripts/publish.sh` keeps a local copy of every non-dry-run publish
before it contacts SFTP.

```text
docs/artifacts/<tool>/<visibility>/<slug>/index.html
docs/artifacts/<tool>/<visibility>/<slug>/<slug>--<version>--<timestamp>.html
```

The current file is replaced on republish; timestamped snapshots remain as local history.
This archive is local custody evidence only. It does not prove SFTP delivery, HTTP byte
identity, privacy, public availability, runtime behavior, or release approval.

Do not put credentials or other sensitive content here. The publisher scans before copying,
but `--allow-sensitive` is an explicit override and can write sensitive bytes locally.
