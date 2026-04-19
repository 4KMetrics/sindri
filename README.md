# sindri

A Claude Code plugin for bounded, target-driven optimization loops.

> In the myth, Sindri is the dwarf smith who forged Mjölnir by iterating under adversity — each hammer-strike tested, kept only if it survived. This plugin is the same pattern: make a change, benchmark it, keep it if it's better, revert otherwise, repeat until the target is hit or the pool of ideas is exhausted.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch), adapted to Claude Code.

## Status

Design phase. See [`docs/superpowers/specs/`](docs/superpowers/specs/) for the current design spec.

## Quick example (once implemented)

```
/sindri reduce bundle_bytes by 15%
```

Sindri will scan your repo, draft a pool of candidate optimizations, ask you to approve the pool, run a baseline to establish a noise floor, then autonomously iterate — dispatching a fresh subagent per candidate, keeping wins, reverting losses. When the target is hit or the pool is exhausted, it automatically pushes a branch and opens a PR with a detailed description of everything that was tried.

## License

MIT
