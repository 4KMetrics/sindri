# Plan — chore/secret-scanning (prevent secret/PII leaks in the public repo)

## Why
`4KMetrics/sindri` is a **public** repo. A leaked API key / token / private key is exposed instantly and must be assumed compromised. Need defense in depth: catch secrets *before commit*, *before merge*, and *before push to GitHub*, plus confirm history is clean.

## Status check (done)
- `gitleaks detect` over full history: **129 commits, no leaks** (2026-06-26).

## Layers (defense in depth)
1. **Pre-commit hook** (`.pre-commit-config.yaml`) — gitleaks + detect-private-key + large-file guard. Blocks a secret locally before it's ever committed. Opt-in: `pipx install pre-commit && pre-commit install`.
2. **CI gate** (`.github/workflows/secret-scan.yml`) — gitleaks-action on every push/PR to `main`, full history (`fetch-depth: 0`). Blocks merge if a secret is present. Action SHA-pinned (matches `ci.yml` convention).
3. **GitHub-native push protection + secret scanning** — free for public repos; blocks a recognized secret at `git push` time, even if the hook/CI were skipped. Enabled via repo settings (API or Settings → Code security).
4. **Docs** (`docs/security.md`) — how to run locally, and the rotate-first incident steps if a secret ever lands.

## Decisions
- gitleaks default ruleset (history scan proved it clean — no custom `.gitleaks.toml` to maintain; add an allowlist only if a real false positive appears).
- No third-party action beyond gitleaks-action (SHA-pinned), matching the repo's minimal-trusted-deps posture.
- PII: git author emails are inherently public and not in scope; the secret rules also flag emails embedded in code. A custom PII regex can be added to a `.gitleaks.toml` later if needed.

## Build order
- [ ] `.github/workflows/secret-scan.yml`
- [ ] `.pre-commit-config.yaml`
- [ ] `docs/security.md`
- [ ] enable GitHub secret scanning + push protection (API; manual fallback documented)
- [ ] PR to main
