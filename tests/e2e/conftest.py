"""E2E fixtures: build a throwaway target repo with a deterministic benchmark."""
from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with a deterministic benchmark that counts lines.

    Layout:
        <tmp_path>/target/
          ├── src/
          │   ├── a.py        (10 non-blank lines)
          │   ├── b.py        (10 non-blank lines)
          │   └── c.py        (10 non-blank lines)
          └── .claude/scripts/sindri/benchmark.py
               — emits `METRIC lines=<total>` counting src/**/*.py.

    Each "candidate" that deletes a file drops the metric by 10.
    """
    repo = tmp_path / "target"
    (repo / "src").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (repo / "src" / f"{name}.py").write_text("x = 1\n" * 10, encoding="utf-8")

    bench_dir = repo / ".claude" / "scripts" / "sindri"
    bench_dir.mkdir(parents=True)
    bench = bench_dir / "benchmark.py"
    bench.write_text(
        dedent(
            '''\
            #!/usr/bin/env python3
            """Count total non-blank lines in src/**/*.py, emit METRIC lines=<n>."""
            from __future__ import annotations
            import sys
            from pathlib import Path


            def main() -> int:
                total = 0
                for p in sorted(Path("src").rglob("*.py")):
                    total += sum(1 for line in p.read_text().splitlines() if line.strip())
                print(f"METRIC lines={total}")
                return 0


            if __name__ == "__main__":
                sys.exit(main())
            '''
        ),
        encoding="utf-8",
    )
    bench.chmod(0o755)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo
