---
description: ADVANCED/DEBUG. Run one orchestrator tick manually, without rescheduling. The loop is normally automatic.
---

# /sindri:loop — manual single tick (advanced)

**Normally automatic.** The orchestrator self-schedules via `ScheduleWakeup`; you rarely need this. Use it to step a stalled or idle run forward by one experiment while debugging.

## Guard

If `.sindri/current/` does not exist, print `sindri: no active run. Start one with /sindri:forge <goal>.` and stop.

## Run exactly one tick

Run the `sindri-loop` orchestrator for **exactly one cycle**: perform steps 1–9 of the `sindri-loop` skill (termination checks, pre-flight git, pick-next, dispatch the experiment subagent, parse, act, record, structural-halt check).

**Do NOT perform step 10 (`ScheduleWakeup`).** The autonomous wakeup already scheduled by the run remains in effect and continues the loop — a manual tick must never create a competing wakeup. If this single cycle hits a terminating condition (HALT sentinel, target hit, pool empty, structural halt), let the skill's normal terminal handling run (it does not reschedule, and may auto-invoke `sindri-finalize`).
