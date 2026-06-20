---
description: Scaffold or repair the benchmark script for a sindri run.
---

# /sindri:setup — scaffold the benchmark

Invoke skill `sindri-scaffold-benchmark` (no active run required). It scans the repo, proposes a measurement in natural language, writes `.claude/scripts/sindri/benchmark.py`, and validates that it emits a `METRIC` line.

This command runs standalone; `sindri-start` also invokes the same skill automatically when a run needs a benchmark.
