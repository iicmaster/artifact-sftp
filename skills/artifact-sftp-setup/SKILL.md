---
name: artifact-sftp-setup
description: First-run setup or repair for artifact-sftp. Pins the SFTP host key, creates the private client config, and checks local readiness. Use when installing, configuring, or setting up artifact-sftp on a machine. ใช้เมื่อติดตั้งหรือตั้งค่า artifact-sftp ครั้งแรกบนเครื่อง
---

# Set up artifact-sftp

Configure the local machine without publishing an artifact. First-time setup writes
`~/.config/artifact-sftp/config` and `~/.config/artifact-sftp/known_hosts`, both mode `0600`.
An explicitly approved reconfiguration also keeps private timestamped backups in that
directory.

## Command

- Codex: `$artifact-sftp:artifact-sftp-setup`
- OpenClaw: `/skill artifact-sftp-setup`

## Workflow

1. Resolve this active skill's directory from the loaded `SKILL.md` path. Do not search
   plugin caches, guess a version, or resolve it from the current working directory.
2. Run the bundled readiness check first:

   ```bash
   bash <this-skill-dir>/scripts/setup-wizard.sh --status
   ```

   On OpenClaw, the equivalent path is
   `bash "{baseDir}/scripts/setup-wizard.sh" --status`.
3. If it prints `READY`, report that setup is complete and stop. Do not rewrite a working
   config unless the user explicitly asks to reconfigure it.
4. If no config exists, print the exact local-terminal command:

   ```bash
   bash <this-skill-dir>/scripts/setup-wizard.sh
   ```

   Do not run this through an ordinary agent-owned PTY: the user generally cannot type into
   it safely. Launch it only when the runtime explicitly guarantees a terminal controlled
   directly by the user; otherwise let the user run the displayed command locally. Never
   relay their keystrokes through chat or tool-call input.
5. For an explicit repair or reconfiguration request, print
   `bash <this-skill-dir>/scripts/setup-wizard.sh --reconfigure` for the user's local
   terminal. Apply the same user-controlled-terminal rule as first-time setup. The wizard
   confirms the replacement and the implementation backs up both existing files first.
6. Run `--status` again and report only readiness, config path, default runtime, and auth
   mode. Never display config contents or secret values.

## Secret and network rules

- Never ask the user to paste an SFTP password, viewer password, private key, or Cloudflare
  Access secret into chat.
- Never place a secret in argv, a tool-call argument, shell history, logs, or the final answer.
  The wizard reads secrets silently from its controlling terminal and pipes them to the setup
  implementation over stdin.
- Show the scanned SFTP host-key fingerprints before asking the user to trust the host.
- Setup must not publish a smoke artifact. A later smoke publish is a separate, explicit
  user-authorized action handled by the `artifact-sftp` publishing skill.
- If host-key scanning fails or the fingerprint is unexpected, stop. Never disable strict
  host-key checking.
