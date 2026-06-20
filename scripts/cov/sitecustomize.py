"""Subprocess coverage hook (dev/CI only — not packaged).

Python imports a module named ``sitecustomize`` at interpreter startup if one is
on the path. ``scripts/coverage.sh`` puts *this* directory on ``PYTHONPATH`` and
sets ``COVERAGE_PROCESS_START``, so every ``python -m sindri`` subprocess the
integration/e2e tests spawn starts coverage too — that's how ``cli.py``'s real
coverage gets measured. Outside that script this dir is never on the path, and
``coverage.process_startup()`` is a no-op unless ``COVERAGE_PROCESS_START`` is
set, so there is zero effect on normal runs.
"""
try:  # pragma: no cover - measurement plumbing
    import coverage

    coverage.process_startup()
except Exception:
    pass
