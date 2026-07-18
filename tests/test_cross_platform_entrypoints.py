from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_top_level_package_exposes_setup_start_and_dev() -> None:
    package_path = ROOT / "package.json"
    assert package_path.is_file(), "top-level package.json is missing"

    scripts = json.loads(package_path.read_text(encoding="utf-8"))["scripts"]
    assert scripts["setup"] == "node scripts/gloss.mjs setup"
    assert scripts["start"] == "node scripts/gloss.mjs start"
    assert scripts["dev"] == "node scripts/gloss.mjs dev"


def test_native_linux_and_windows_wrappers_exist() -> None:
    expected = [
        "scripts/setup.sh",
        "scripts/run.sh",
        "scripts/dev.sh",
        "scripts/setup.ps1",
        "scripts/run.ps1",
        "scripts/dev.ps1",
        "gloss",
        "gloss.ps1",
    ]
    for relative in expected:
        assert (ROOT / relative).is_file(), f"missing native wrapper: {relative}"


def test_linux_setup_no_longer_contains_machine_specific_data_disk() -> None:
    setup = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "/root/autodl-tmp" not in setup
    assert 'gloss.mjs" setup' in setup


def test_tagline_mentions_multiple_provider_choices() -> None:
    library = (ROOT / "frontend" / "src" / "components" / "Library.tsx").read_text(
        encoding="utf-8"
    )
    assert "powered by Claude, Codex, or your preferred AI provider" in library
    assert "由 Claude、Codex 或你选择的 AI 提供方驱动" in library


def test_url_import_status_explains_that_network_import_can_take_time() -> None:
    library = (ROOT / "frontend" / "src" / "components" / "Library.tsx").read_text(
        encoding="utf-8"
    )
    assert "Downloading and parsing" in library
    assert "正在下载并解析" in library


def test_launcher_treats_empty_cache_environment_values_as_unset() -> None:
    launcher = (ROOT / "scripts" / "gloss.mjs").read_text(encoding="utf-8")
    assert "process.env.LOCALAPPDATA ||" in launcher
    assert "process.env.XDG_CACHE_HOME ||" in launcher


def test_normal_test_commands_include_frontend_regressions() -> None:
    frontend_scripts = json.loads(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )["scripts"]
    launcher = (ROOT / "scripts" / "gloss.mjs").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert frontend_scripts["test"] == "node --test tests/*.test.mjs"
    assert 'runPackage(packageManager(), ["test"], { cwd: FRONTEND })' in launcher
    assert "npm test" in workflow
