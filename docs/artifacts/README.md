# Local artifact archive

`skills/artifact-sftp/scripts/publish.sh` keeps a local copy of every non-dry-run publish
before it contacts SFTP.

```text
docs/artifacts/<tool>/<visibility>/<slug>/index.html
docs/artifacts/<tool>/<visibility>/<slug>/<slug>--<version>--<timestamp>.html
```

The current file is replaced on republish; timestamped snapshots remain as local history.

## Read back from here

This is how an agent reads its own private artifact. A private artifact's URL cannot be
fetched over HTTP — the Cloudflare Zero Trust gate blocks even the publishing
account. To read one back:

- Open `docs/artifacts/<tool>/<visibility>/<slug>/index.html` (current bytes, identical
  to what the server serves) or a `<slug>--<version>--<timestamp>.html` snapshot.
- The URL path maps to this layout: `https://.../<tool>/<visibility>/<slug>/` →
  `docs/artifacts/<tool>/<visibility>/<slug>/`.
- If this archive is out of reach (fresh session, another machine), fall back to SFTP:
  `<remote-base>/<tool>/<visibility>/<slug>/index.html` on the host in
  `~/.config/artifact-sftp/config`.

Do not WebFetch the artifact URL to read it back.

This archive is local custody evidence only. It does not prove SFTP delivery, HTTP byte
identity, privacy, public availability, runtime behavior, or release approval.

Do not put credentials or other sensitive content here. The publisher scans before copying,
but `--allow-sensitive` is an explicit override and can write sensitive bytes locally.