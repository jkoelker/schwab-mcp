"""The container ships runtime dependencies only and runs as a non-root user."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTAINERFILE = (ROOT / "Containerfile").read_text()


def _export_command() -> str:
    match = re.search(r"uv export(?:\s*\\\n\s*--[\w-]+(?: [\w./-]+)?)+", CONTAINERFILE)
    assert match, "Containerfile no longer runs uv export"
    return match.group(0)


def test_export_excludes_dev_group_and_includes_signal() -> None:
    export = _export_command()

    assert "--no-dev" in export
    assert "--extra signal" in export
    assert "--group ta" in export
    assert "--frozen" in export


def test_runtime_stage_runs_as_non_root() -> None:
    runtime = CONTAINERFILE.split("\nFROM ")[-1]
    users = re.findall(r"^USER\s+(\S+)", runtime, re.MULTILINE)

    assert users, "runtime stage has no USER"
    assert users[-1].split(":")[0] not in {"root", "0"}


def test_latest_tag_follows_releases_only() -> None:
    workflow = (ROOT / ".github/workflows/container.yml").read_text()

    assert "latest=true" not in workflow
    assert "latest=auto" in workflow
