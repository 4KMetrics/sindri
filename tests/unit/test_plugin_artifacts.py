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
    return set(re.findall(r"python -m sindri (\S+)", body))


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
