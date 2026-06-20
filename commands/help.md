---
description: Show the sindri command list and a one-line overview of each.
---

# /sindri:help — command overview

Print this table verbatim. No backend call, no skill invocation.

| Command | What it does |
|---|---|
| `/sindri:forge <goal>` | Start a new optimization run (e.g. `reduce bundle_bytes by 15%`). |
| `/sindri:status` | Print the current run's status. |
| `/sindri:stop` | Signal the run to halt at its next wakeup. |
| `/sindri:clear` | Abandon the run (destructive — deletes state + branch). |
| `/sindri:setup` | Scaffold or repair the benchmark script. |
| `/sindri:help` | This overview. |
| `/sindri:loop` | ADVANCED/DEBUG — run one orchestrator tick by hand. |
| `/sindri:finalize` | ADVANCED/DEBUG — force a push + PR from kept commits. |
