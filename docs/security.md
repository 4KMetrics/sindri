# Security — secret & key leak prevention

`sindri` is a **public** repository. A committed credential is exposed the instant
it's pushed and **must be treated as compromised** even after deletion (it lives in
history, forks, and caches). We defend in depth so a secret is caught before commit,
before merge, and before it reaches GitHub.

## The three layers

| Layer | Mechanism | Catches a secret… | Config |
|---|---|---|---|
| 1. Local | [pre-commit](https://pre-commit.com) + gitleaks | before it's committed | `.pre-commit-config.yaml` |
| 2. CI | `gitleaks-action` on every push/PR to `main` | before it's merged | `.github/workflows/secret-scan.yml` |
| 3. GitHub | native **secret scanning + push protection** | before it reaches the remote at all | repo Settings → Code security |

No single layer is trusted alone: the hook can be skipped (`--no-verify`), CI runs
only after the push, and push protection only knows GitHub's provider patterns — so
all three run together.

## Set up the local hook (one time per clone)

```bash
pipx install pre-commit        # or: brew install pre-commit
pre-commit install             # installs the git hook
pre-commit run --all-files     # optional: scan the whole tree now
```

## Scan history on demand

```bash
gitleaks detect --source . --redact   # scans every commit; --redact hides values
```

A clean baseline was recorded on 2026-06-26 (129 commits, no leaks).

## GitHub push protection (layer 3)

Free for public repos. Enable once, in **Settings → Code security and analysis**:
enable **Secret scanning** and **Push protection**. (Or via the API — see
`plan-chore-secret-scanning.md`.) Once on, GitHub rejects a `git push` that contains
a recognized secret and tells the author which one.

## If a secret DOES leak — do this in order

1. **Rotate/revoke the credential immediately.** Deleting the commit is *not* enough;
   assume it was scraped the moment it was public.
2. Remove it from the working tree and open a fix.
3. Purge it from history only after rotation (`git filter-repo` / BFG), then
   force-push and notify anyone with a clone/fork.
4. Add a gitleaks allowlist entry only for a confirmed **false positive** (a fake
   value in a test/fixture) — never to silence a real secret.

## Notes

- Git author emails are inherently public in any git repo and are out of scope here.
- gitleaks uses its default ruleset (proven clean against this repo's history). Add a
  `.gitleaks.toml` with an `[allowlist]` only if a genuine false positive appears, or
  to add custom PII/secret patterns.
