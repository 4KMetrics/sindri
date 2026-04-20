"""Integration tests for git subprocess wrappers — use real git in tmp repos."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sindri.core.git_ops import (
    GitError,
    branch_exists,
    commit_all_with_message,
    create_branch,
    current_branch,
    delete_branch,
    is_working_tree_clean,
    reset_hard_to_head,
)


class TestCurrentBranch:
    def test_returns_main(self, tmp_git_repo: Path) -> None:
        assert current_branch() == "main"

    def test_returns_feature_branch(self, tmp_git_repo: Path) -> None:
        subprocess.run(["git", "checkout", "-b", "feature/test"], check=True, cwd=tmp_git_repo, capture_output=True)
        assert current_branch() == "feature/test"


class TestIsWorkingTreeClean:
    def test_clean_after_init(self, tmp_git_repo: Path) -> None:
        assert is_working_tree_clean() is True

    def test_dirty_with_unstaged(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("hi")
        assert is_working_tree_clean() is False

    def test_dirty_with_modified_tracked(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# modified\n")
        assert is_working_tree_clean() is False


class TestCreateBranch:
    def test_creates_and_checks_out(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/test-goal")
        assert current_branch() == "sindri/test-goal"

    def test_fails_if_name_exists(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/first")
        with pytest.raises(GitError):
            create_branch("sindri/first")


class TestCommitAllWithMessage:
    def test_commits_staged_changes(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("content\n")
        sha = commit_all_with_message("kept: test change")
        assert len(sha) >= 7
        out = subprocess.run(
            ["git", "log", "-1", "--format=%s"], check=True, capture_output=True, text=True, cwd=tmp_git_repo,
        ).stdout.strip()
        assert out == "kept: test change"

    def test_raises_if_nothing_to_commit(self, tmp_git_repo: Path) -> None:
        with pytest.raises(GitError):
            commit_all_with_message("empty commit")


class TestResetHardToHead:
    def test_clears_uncommitted_changes(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# modified\n")
        (tmp_git_repo / "new.txt").write_text("untracked\n")
        assert is_working_tree_clean() is False
        reset_hard_to_head()
        # Modified tracked file reverts; untracked file remains (git reset doesn't touch untracked).
        assert (tmp_git_repo / "README.md").read_text() == "# test\n"


class TestDeleteBranch:
    def test_deletes_after_switch(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/temp")
        subprocess.run(["git", "checkout", "main"], check=True, cwd=tmp_git_repo, capture_output=True)
        delete_branch("sindri/temp", force=True)
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            check=True, capture_output=True, text=True, cwd=tmp_git_repo,
        ).stdout.strip().splitlines()
        assert "sindri/temp" not in branches

    def test_cannot_delete_current_branch(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/current-feature")
        with pytest.raises(GitError):
            delete_branch("sindri/current-feature", force=True)


class TestBranchExists:
    def test_main_exists(self, tmp_git_repo: Path) -> None:
        assert branch_exists("main") is True

    def test_nonexistent_returns_false(self, tmp_git_repo: Path) -> None:
        assert branch_exists("sindri/definitely-not-there") is False

    def test_after_create(self, tmp_git_repo: Path) -> None:
        assert branch_exists("sindri/fresh") is False
        create_branch("sindri/fresh")
        assert branch_exists("sindri/fresh") is True
