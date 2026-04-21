"""Validate plugin artifacts (manifest, commands, skills, prompts) parse and contain required fields."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_CLI_SUBCOMMANDS = {
    "init", "validate-benchmark", "detect-mode", "read-state", "pick-next",
    "record-result", "check-termination", "generate-pr-body", "archive", "status",
}


def _parse_frontmatter(md_path: Path) -> dict:
    """Extract YAML frontmatter from a markdown file. Returns {} if none."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, frontmatter, _ = text.split("---\n", 2)
    return yaml.safe_load(frontmatter) or {}


def _skill_path(name: str) -> Path:
    return REPO_ROOT / "skills" / name / "SKILL.md"


def _cli_calls(body: str) -> set[str]:
    """Extract sub-command names from `python -m sindri <cmd>` references."""
    return set(re.findall(r"python -m sindri ([a-z][a-z0-9-]*)", body))


class TestPluginManifest:
    def test_plugin_json_exists(self) -> None:
        assert (REPO_ROOT / ".claude-plugin" / "plugin.json").is_file()

    def test_plugin_json_parses(self) -> None:
        data = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert isinstance(data, dict)

    def test_plugin_json_required_fields(self) -> None:
        data = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
        for key in ("name", "description", "version", "author"):
            assert key in data, f"missing required field: {key}"
        assert data["name"] == "sindri"


class TestMarketplaceManifest:
    PATH = REPO_ROOT / ".claude-plugin" / "marketplace.json"

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_parses(self) -> None:
        data = json.loads(self.PATH.read_text())
        assert isinstance(data, dict)

    def test_required_fields(self) -> None:
        data = json.loads(self.PATH.read_text())
        for key in ("name", "owner", "plugins"):
            assert key in data, f"missing top-level field: {key}"
        assert isinstance(data["plugins"], list) and data["plugins"], "plugins must be a non-empty list"

    def test_sindri_plugin_entry(self) -> None:
        data = json.loads(self.PATH.read_text())
        sindri = next((p for p in data["plugins"] if p.get("name") == "sindri"), None)
        assert sindri is not None, "marketplace.json must list a plugin named 'sindri'"
        assert sindri.get("source"), "sindri entry must have a source"
        # source may be a relative string ('./') or an object; tolerate both.
        src = sindri["source"]
        assert isinstance(src, (str, dict))


class TestSlashCommand:
    COMMAND_PATH = REPO_ROOT / "commands" / "sindri.md"

    def test_command_file_exists(self) -> None:
        assert self.COMMAND_PATH.is_file()

    def test_command_frontmatter_has_description(self) -> None:
        fm = _parse_frontmatter(self.COMMAND_PATH)
        assert "description" in fm and fm["description"].strip(), "command needs a description"

    def test_command_mentions_subcommands(self) -> None:
        body = self.COMMAND_PATH.read_text()
        for sub in ("status", "stop", "scaffold-benchmark", "clear"):
            assert sub in body, f"command body should reference subcommand: {sub}"

    def test_command_routes_to_skills(self) -> None:
        body = self.COMMAND_PATH.read_text()
        for skill in ("sindri-start", "sindri-loop", "sindri-finalize", "sindri-scaffold-benchmark"):
            assert skill in body, f"command body should name skill: {skill}"


class TestSkillSindriStart:
    PATH = _skill_path("sindri-start")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter_has_name_and_description(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-start"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known_subcommands(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS, f"unknown subcommand: {cmd}"

    def test_references_scaffold_benchmark_subflow(self) -> None:
        body = self.PATH.read_text()
        assert "sindri-scaffold-benchmark" in body


class TestSkillSindriScaffoldBenchmark:
    PATH = _skill_path("sindri-scaffold-benchmark")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-scaffold-benchmark"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_mentions_metric_output_contract(self) -> None:
        body = self.PATH.read_text()
        assert "METRIC" in body


class TestSkillSindriLoop:
    PATH = _skill_path("sindri-loop")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-loop"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_references_experiment_subagent_prompt(self) -> None:
        body = self.PATH.read_text()
        assert "experiment-subagent" in body

    def test_references_schedule_wakeup(self) -> None:
        body = self.PATH.read_text()
        assert "ScheduleWakeup" in body

    def test_references_finalize_skill(self) -> None:
        body = self.PATH.read_text()
        assert "sindri-finalize" in body


class TestSkillSindriFinalize:
    PATH = _skill_path("sindri-finalize")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-finalize"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_mentions_gh_pr_create(self) -> None:
        body = self.PATH.read_text()
        assert "gh pr create" in body

    def test_mentions_git_push(self) -> None:
        body = self.PATH.read_text()
        assert "git push" in body

    def test_mentions_archive(self) -> None:
        body = self.PATH.read_text()
        assert "archive" in body.lower()


class TestExperimentSubagentPrompt:
    PATH = REPO_ROOT / "prompts" / "experiment-subagent.md"

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_declares_output_contract(self) -> None:
        body = self.PATH.read_text()
        for field in ("metric_value", "reps_used", "confidence_ratio", "status", "files_modified"):
            assert field in body, f"output contract missing field: {field}"
        for status in ("improved", "regressed", "inconclusive", "check_failed", "errored", "timeout"):
            assert status in body, f"status value missing: {status}"

    def test_declares_input_placeholders(self) -> None:
        body = self.PATH.read_text()
        for placeholder in ("$CANDIDATE", "$BENCHMARK_CMD", "$METRIC", "$CURRENT_BEST", "$NOISE_FLOOR", "$MODE", "$TIMEOUT_SECONDS"):
            assert placeholder in body, f"placeholder missing: {placeholder}"

    def test_prohibits_commit_push_and_sindri_writes(self) -> None:
        body = self.PATH.read_text().lower()
        # Allow "do not commit", "do not `git commit`", "must not commit", etc.
        assert re.search(r"(do|must) not\W+(`?git )?commit", body), "must prohibit git commit"
        assert re.search(r"(do|must) not\W+(`?git )?push", body), "must prohibit git push"
        assert ".sindri/" in body
