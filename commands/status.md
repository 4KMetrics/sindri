---
description: Print the status of the current sindri run (or report that there is no active run).
---

# /sindri:status — run status

Resolve `FORGE` to this plugin's `scripts/forge.sh` (absolute path; this command file lives at `<plugin-root>/commands/status.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`). Run `"$FORGE" status` and print its output verbatim. No skill invocation.

This is a fast read — the first-ever call does a one-time backend fetch; subsequent calls are cached.
