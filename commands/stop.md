---
description: Signal the current sindri run to halt at its next wakeup.
---

# /sindri:stop — halt the run

`touch .sindri/current/HALT` — a sentinel file. The orchestrator checks for it before every experiment and treats it as a `halted_by_user` termination. Then print verbatim:

`sindri: halt signal sent. The next wakeup will terminate without running another experiment.`

No backend call, no skill invocation.
