"""Thin subprocess wrappers around git. Each function raises GitError on failure.

All operations run in the current working directory — callers are responsible
for being in the right repo root. Sindri invokes these from the directory the
user ran `/sindri` in.
"""
from __future__ import annotations

import subprocess


class GitError(RuntimeError):
    """Raised when a git operation fails."""


def _run(args: list[str]) -> str:
    """Run git with args, return stdout, raise GitError on non-zero exit."""
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def current_branch() -> str:
    """Return the current branch name."""
    return _run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def branch_exists(name: str) -> bool:
    """True if a local branch with `name` exists. Never raises."""
    try:
        _run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
        return True
    except GitError:
        return False


def is_working_tree_clean() -> bool:
    """True if there are no uncommitted tracked or untracked changes."""
    out = _run(["status", "--porcelain"])
    return out.strip() == ""


def create_branch(name: str, *, from_ref: str = "HEAD") -> None:
    """Create a new branch from `from_ref` and check it out.

    Fails if the branch already exists — callers must handle that.
    """
    _run(["checkout", "-b", name, from_ref])


def commit_all_with_message(msg: str) -> str:
    """Stage all changes and commit with `msg`. Returns the new commit SHA.

    Raises GitError if there's nothing to commit (strict: refuse empty commits).
    """
    _run(["add", "-A"])
    # Refuse empty commits; a vanilla `git commit` with nothing staged exits
    # non-zero but with a generic message — we want an explicit error.
    status = _run(["status", "--porcelain"]).strip()
    if not status:
        raise GitError("nothing to commit — working tree clean after git add")
    _run(["commit", "-m", msg])
    return _run(["rev-parse", "HEAD"]).strip()


def reset_hard_to_head() -> None:
    """`git reset --hard HEAD` — discards all tracked file changes."""
    _run(["reset", "--hard", "HEAD"])


def delete_branch(name: str, *, force: bool = False) -> None:
    """Delete a local branch. Use force=True to delete an unmerged branch."""
    if current_branch() == name:
        raise GitError(f"cannot delete currently-checked-out branch {name!r}")
    flag = "-D" if force else "-d"
    _run(["branch", flag, name])


def push_with_upstream(branch: str, *, remote: str = "origin") -> None:
    """`git push -u <remote> <branch>`. Called by finalize, not by the main loop."""
    _run(["push", "-u", remote, branch])
